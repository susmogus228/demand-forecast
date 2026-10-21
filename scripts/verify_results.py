"""Reconcile exported CSVs and hashes using the Python standard library only."""

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(actual, expected, name):
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9):
        raise ValueError(f'{name} mismatch: recomputed {actual}, exported {expected}')


def score(rows, expected, name):
    errors = [float(row['y_pred']) - float(row['y_true']) for row in rows]
    if not errors or len(errors) != expected['n']:
        raise ValueError(f'{name} sample count mismatch.')
    close(sum(map(abs, errors)) / len(errors), expected['mae'], f'{name} MAE')
    close(math.sqrt(sum(value * value for value in errors) / len(errors)), expected['rmse'], f'{name} RMSE')


def verify(folder):
    def read(name):
        return json.loads((folder / name).read_text(encoding='utf-8'))

    artifact, metrics, source = read('artifact.json'), read('metrics.json'), read('source_manifest.json')
    for filename, key in [('model.joblib', 'sha256'), ('observations.csv', 'observations_sha256'), ('predictions.csv', 'predictions_sha256')]:
        if digest(folder / filename) != artifact[key]:
            raise ValueError(f'{filename} checksum mismatch.')
    source_csv = folder / 'source' / 'hour.csv'
    if source_csv.exists() and digest(source_csv) != source['hour_csv_sha256']:
        raise ValueError('Raw source checksum mismatch.')
    with (folder / 'observations.csv').open(encoding='utf-8', newline='') as handle:
        observations = {datetime.fromisoformat(row['timestamp']): None if not row['cnt'] else float(row['cnt']) for row in csv.DictReader(handle)}
    with (folder / 'predictions.csv').open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    groups = defaultdict(list)
    for row in rows:
        stamp, origin = datetime.fromisoformat(row['target_timestamp']), datetime.fromisoformat(row['origin'])
        if origin.hour != 0 or stamp != origin + timedelta(hours=int(row['horizon'])):
            raise ValueError('Origin or horizon mismatch.')
        if observations.get(stamp) is None:
            raise ValueError('A scored target has no observed count.')
        close(float(row['y_true']), observations[stamp], 'Target truth')
        if not math.isfinite(float(row['y_pred'])) or float(row['y_pred']) < 0:
            raise ValueError('Invalid prediction.')
        for lag in [24, 168]:
            source_stamp = stamp - timedelta(hours=lag)
            if source_stamp >= origin:
                raise ValueError('Lag source reaches forecast origin.')
            observed = observations.get(source_stamp) is not None
            if (row[f'lag{lag}_observed'] == 'True') != observed:
                raise ValueError('Lag availability mismatch.')
        groups[(row['split'], row['role'], row['model'])].append(row)
    for name, expected in metrics['validation'].items():
        score(groups[('validation', 'candidate', name)], expected, f'Validation {name}')
    selected = metrics['selection']['selected_model']
    selected_rows = groups[('test', 'selected', selected)]
    score(selected_rows, metrics['test']['selected'], 'Final selected')
    score(groups[('test', 'baseline', 'seasonal_naive')], metrics['test']['baseline'], 'Final baseline')
    for summary in metrics['test']['by_horizon']:
        score([row for row in selected_rows if int(row['horizon']) == summary['horizon']], summary, f"Horizon {summary['horizon']}")
    expected_best = min(metrics['validation'], key=lambda name: metrics['validation'][name]['mae'])
    if selected != expected_best:
        close(metrics['validation'][selected]['mae'], metrics['validation'][expected_best]['mae'], 'Selection tie')
    close(metrics['test']['selected']['mae'] - metrics['test']['baseline']['mae'],
          metrics['test']['comparison']['mae_difference_selected_minus_baseline'], 'MAE difference')
    protocol = read('protocol.json')
    protocol_sha = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    if any(value != protocol_sha for value in [artifact['protocol_sha256'], metrics['protocol_sha256'], read('split_manifest.json')['protocol_sha256']]):
        raise ValueError('Protocol hash mismatch.')
    return {'status': 'verified', 'prediction_rows': len(rows), 'final_test_observed_hours': len(selected_rows),
            'selected_model': selected, 'source_sha256': source['hour_csv_sha256'],
            'checks': ['model/observations/predictions hashes', 'all candidate MAE/RMSE and counts',
                       'horizon metrics', 'CSV truth', 'lag timestamps/availability', 'selection', 'protocol hash']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('results'))
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.results), indent=2))
    except (ValueError, KeyError, OSError) as exc:
        print(f'Verification failed: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

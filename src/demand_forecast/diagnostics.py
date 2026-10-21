"""Paired, descriptive test-set diagnostics. No fitting or model selection."""

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def paired_diagnostics(rows, selected_model):
    """Reject unmatched targets rather than silently comparing different samples."""
    groups = {'selected': {}, 'baseline': {}}
    for row in rows:
        if row['split'] != 'test' or row['role'] not in groups:
            continue
        role = row['role']
        expected = selected_model if role == 'selected' else 'seasonal_naive'
        if row['model'] != expected:
            raise ValueError('Final-test model does not match the frozen selection.')
        origin = datetime.fromisoformat(row['origin'])
        target = datetime.fromisoformat(row['target_timestamp'])
        horizon = int(row['horizon'])
        if (origin.tzinfo or target.tzinfo or origin.time().isoformat() != '00:00:00'
                or not 0 <= horizon <= 23 or target != origin + timedelta(hours=horizon)):
            raise ValueError('Invalid midnight origin or target horizon.')
        key = (origin, target, horizon)
        if key in groups[role]:
            raise ValueError('Duplicate final-test target within one role.')
        truth, prediction = float(row['y_true']), float(row['y_pred'])
        if not all(math.isfinite(value) and value >= 0 for value in [truth, prediction]):
            raise ValueError('Targets and predictions must be finite nonnegative values.')
        groups[role][key] = (truth, prediction)
    selected, baseline = groups['selected'], groups['baseline']
    if not selected or selected.keys() != baseline.keys():
        raise ValueError('Final-test targets must be nonempty and exactly paired.')
    pairs = []
    for (origin, target, horizon), (truth, prediction) in sorted(selected.items()):
        base_truth, base_prediction = baseline[(origin, target, horizon)]
        if truth != base_truth:
            raise ValueError('Paired target truth differs between model and baseline.')
        pairs.append({'month': target.strftime('%Y-%m'), 'day': target.date().isoformat(),
                      'hour': target.hour, 'horizon': horizon,
                      'model_error': abs(prediction-truth), 'baseline_error': abs(base_prediction-truth)})

    def score(subset):
        n = len(subset)
        model = math.fsum(item['model_error'] for item in subset) / n
        base = math.fsum(item['baseline_error'] for item in subset) / n
        return {'n': n, 'model_mae': model, 'baseline_mae': base, 'delta_mae': model-base}

    def slices(field):
        by_key = defaultdict(list)
        for pair in pairs:
            by_key[pair[field]].append(pair)
        return [dict({field: key}, **({'horizon': key} if field == 'hour' else {}), **score(subset))
                for key, subset in sorted(by_key.items())]

    result = {'schema_version': 1, 'kind': 'post_hoc_paired_historical_diagnostic',
              'selected_model': selected_model, 'baseline_model': 'seasonal_naive',
              'unit': 'rentals/hour', 'delta_definition': 'model MAE minus baseline MAE; positive means model is worse',
              'hour_definition': 'Target clock hour equals zero-based horizon for the daily 00:00 origin; horizon 0 is 00:00.',
              'overall': score(pairs), 'by_month': slices('month'),
              'by_hour': slices('hour'), 'by_day': slices('day')}
    result['loss_counts'] = {name: sum(row['delta_mae'] > 1e-12 for row in result[key])
                             for name, key in [('months', 'by_month'), ('hours', 'by_hour'), ('days', 'by_day')]}
    result['limitations'] = ['Post-hoc descriptive slices of the same final holdout; no retuning or retraining.',
                            'Only targets observed for both methods are scored; missing target hours are not zero.',
                            'No uncertainty interval, statistical significance or other-city guarantee.',
                            'Day and hour slices are correlated observations, not independent experiments.']
    return result


def build_diagnostics(folder):
    """Derive each response from hash-checked inputs, never trust a saved summary."""
    folder = Path(folder)
    names = ['artifact.json', 'predictions.csv', 'metrics.json', 'protocol.json',
             'selection.json', 'split_manifest.json', 'source_manifest.json']
    blobs = {name: (folder/name).read_bytes() for name in names}
    hashes = {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()}
    docs = {name: json.loads(blobs[name]) for name in names if name.endswith('.json')}
    artifact, metrics, selection = (docs[name] for name in ['artifact.json', 'metrics.json', 'selection.json'])
    if hashes['predictions.csv'] != artifact['predictions_sha256']:
        raise ValueError('Prediction checksum mismatch.')
    protocol_sha = hashlib.sha256(json.dumps(docs['protocol.json'], sort_keys=True).encode()).hexdigest()
    if any(doc['protocol_sha256'] != protocol_sha for doc in [artifact, metrics, selection, docs['split_manifest.json']]):
        raise ValueError('Protocol checksum mismatch.')
    selected = selection['selected_model']
    if artifact['selected_model'] != selected or metrics['selection'] != selection:
        raise ValueError('Model selection lineage mismatch.')
    if metrics['source_sha256'] != artifact['source_sha256'] or artifact['source_sha256'] != docs['source_manifest.json']['hour_csv_sha256']:
        raise ValueError('Source lineage mismatch.')
    rows = csv.DictReader(blobs['predictions.csv'].decode('utf-8').splitlines())
    result = paired_diagnostics(rows, selected)
    for field, key in [('model_mae', 'selected'), ('baseline_mae', 'baseline')]:
        expected = metrics['test'][key]
        if result['overall']['n'] != expected['n'] or not math.isclose(result['overall'][field], expected['mae'], abs_tol=1e-9):
            raise ValueError('Paired diagnostic does not reconcile with recorded metrics.')
    bounds = docs['split_manifest.json']['splits']['test']
    if len(result['by_day']) != bounds['days'] or result['by_day'][0]['day'] != bounds['start'] or result['by_day'][-1]['day'] != bounds['end_inclusive']:
        raise ValueError('Paired diagnostic does not reconcile with test dates.')
    result['validation_candidates'] = [{'model': model, **scores, 'selected': model == selected}
                                       for model, scores in metrics['validation'].items()]
    result['lineage'] = {'files': hashes, 'protocol_sha256': protocol_sha,
                         'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         'verification': 'Local hash and cross-file consistency, not authenticity of untrusted files.'}
    return result


def markdown_report(result):
    lines = ['# Paired historical failure diagnostic v1', '',
             'Derived from the existing frozen predictions; no new fitting or model selection.', '',
             result['delta_definition'] + '. All MAEs and deltas use rentals/hour.', '',
             result['hour_definition'], '',
             f"Observed paired targets: {result['overall']['n']}. "
             f"Model loses on {result['loss_counts']['months']}/{len(result['by_month'])} months, "
             f"{result['loss_counts']['hours']}/{len(result['by_hour'])} hours, "
             f"{result['loss_counts']['days']}/{len(result['by_day'])} days.", '']
    for heading, key, label in [('Months', 'by_month', 'month'), ('Target hours / zero-based horizons', 'by_hour', 'hour'), ('Days', 'by_day', 'day')]:
        lines += [f'## {heading}', '', '| Slice | Paired hours | Model MAE | Baseline MAE | Model minus baseline |',
                  '|---|---:|---:|---:|---:|']
        for row in result[key]:
            lines.append(f"| {row[label]} | {row['n']} | {row['model_mae']:.6f} | {row['baseline_mae']:.6f} | {row['delta_mae']:+.6f} |")
        lines.append('')
    lines += ['## Limits', ''] + [f'- {text}' for text in result['limitations']]
    lines += ['', 'Input and implementation SHA-256 hashes are in `diagnostics-v1.json`.']
    return '\n'.join(lines) + '\n'

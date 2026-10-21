import csv
import json
from pathlib import Path

import pytest


def rows():
    result = []
    for stamp, horizon, truth, model, base in [
        ('2012-08-07T00:00:00', 0, 10, 12, 14),
        ('2012-08-07T08:00:00', 8, 10, 18, 12),
        ('2012-09-01T08:00:00', 8, 20, 21, 24),
    ]:
        for role, name, prediction in [('selected', 'ridge', model), ('baseline', 'seasonal_naive', base)]:
            result.append(dict(split='test', role=role, model=name, origin=stamp[:10]+'T00:00:00',
                               target_timestamp=stamp, horizon=str(horizon), y_true=str(truth), y_pred=str(prediction)))
    # Validation rows must never enter final-test slices.
    result.append(dict(result[0], split='validation', y_pred='9999'))
    return result


def test_paired_diagnostics_uses_identical_observed_targets_and_hour_zero():
    from demand_forecast.diagnostics import paired_diagnostics
    report = paired_diagnostics(rows(), 'ridge')
    assert report['overall']['n'] == 3
    assert report['overall']['model_mae'] == pytest.approx(11/3)
    assert report['overall']['baseline_mae'] == pytest.approx(10/3)
    assert report['overall']['delta_mae'] == pytest.approx(1/3)
    assert report['by_hour'][0]['hour'] == report['by_hour'][0]['horizon'] == 0
    assert report['by_hour'][1]['hour'] == report['by_hour'][1]['horizon'] == 8
    assert report['by_month'][0]['delta_mae'] == 2
    assert report['loss_counts'] == {'months': 1, 'hours': 1, 'days': 1}
    assert sum(row['n'] for row in report['by_day']) == 3


@pytest.mark.parametrize('mutation,match', [
    ('missing', 'paired'), ('duplicate', 'Duplicate'), ('truth', 'truth'),
    ('hour', 'horizon'), ('nonfinite', 'finite'), ('empty', 'paired'),
])
def test_incomplete_or_invalid_pairs_are_rejected(mutation, match):
    from demand_forecast.diagnostics import paired_diagnostics
    source = rows()
    if mutation == 'missing': source.pop(1)
    if mutation == 'duplicate': source.append(dict(source[0]))
    if mutation == 'truth': source[1]['y_true'] = '11'
    if mutation == 'hour': source[0]['horizon'] = '1'
    if mutation == 'nonfinite': source[0]['y_pred'] = 'nan'
    if mutation == 'empty': source = []
    with pytest.raises(ValueError, match=match): paired_diagnostics(source, 'ridge')


def test_real_diagnostics_reconcile_audit_and_lineage():
    from demand_forecast.diagnostics import build_diagnostics
    folder = Path(__file__).parents[1] / 'results'
    report = build_diagnostics(folder)
    assert report['overall']['n'] == 3488
    assert report['loss_counts'] == {'months': 2, 'hours': 8, 'days': 65}
    assert report['by_month'][0]['delta_mae'] == pytest.approx(5.104, abs=.0005)
    assert report['by_month'][1]['delta_mae'] == pytest.approx(3.772, abs=.0005)
    assert report['by_hour'][8]['delta_mae'] == pytest.approx(20.797, abs=.0005)
    assert report['overall']['delta_mae'] == pytest.approx(-4.536204351431543)
    assert report['lineage']['files']['predictions.csv'] == json.loads((folder/'artifact.json').read_text(encoding='utf-8'))['predictions_sha256']
    assert len(report['by_day']) == 147


def test_loader_rejects_prediction_tamper(tmp_path):
    from demand_forecast.diagnostics import build_diagnostics
    import shutil
    folder = Path(__file__).parents[1] / 'results'
    for name in ['artifact.json', 'predictions.csv', 'metrics.json', 'protocol.json', 'selection.json', 'split_manifest.json', 'source_manifest.json']:
        shutil.copyfile(folder/name, tmp_path/name)
    with (tmp_path/'predictions.csv').open('a', encoding='utf-8') as handle: handle.write('\n')
    with pytest.raises(ValueError, match='checksum'): build_diagnostics(tmp_path)


def test_diagnostics_endpoint_and_openapi():
    import threading
    from urllib.request import urlopen
    from demand_forecast.demo import make_server
    class Service:
        def diagnostics(self): return {'schema_version': 1, 'overall': {'n': 3}}
    server = make_server(Path('results'), service=Service())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        with urlopen(base+'/api/diagnostics') as response:
            assert json.load(response)['overall']['n'] == 3
        with urlopen(base+'/openapi.json') as response:
            assert '/api/diagnostics' in json.load(response)['paths']
    finally:
        server.shutdown(); server.server_close(); thread.join()

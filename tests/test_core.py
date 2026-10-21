import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def fixture_csv(path, days=40):
    stamps = pd.date_range('2020-01-01', periods=days * 24, freq='h')
    pd.DataFrame({'dteday': stamps.strftime('%Y-%m-%d'), 'hr': stamps.hour,
                  'cnt': [20 + t.hour * 3 + t.dayofweek for t in stamps]}).to_csv(path, index=False)
    return path


def test_missing_hour_is_unknown_and_lags_use_timestamps(tmp_path):
    from demand_forecast.data import load_hourly, make_features
    path = fixture_csv(tmp_path / 'hour.csv')
    raw = pd.read_csv(path).drop(index=[10])
    raw.to_csv(path, index=False)
    frame, validation = load_hourly(path)
    assert pd.isna(frame.loc[pd.Timestamp('2020-01-01 10:00'), 'cnt'])
    features = make_features(frame, pd.DatetimeIndex(['2020-01-02 10:00']))
    assert pd.isna(features.iloc[0]['lag24'])
    assert validation['missing_timestamp_count'] == 1


def test_future_changes_do_not_change_origin_features(tmp_path):
    from demand_forecast.data import load_hourly, make_features
    frame, _ = load_hourly(fixture_csv(tmp_path / 'hour.csv'))
    origin = pd.Timestamp('2020-01-20')
    targets = pd.date_range(origin, periods=24, freq='h')
    expected = make_features(frame, targets)
    frame.loc[frame.index >= origin, 'cnt'] = 999999
    pd.testing.assert_frame_equal(expected, make_features(frame, targets))


def test_day_splits_are_ordered_and_preserve_all_hours(tmp_path):
    from demand_forecast.data import load_hourly, split_days
    frame, _ = load_hourly(fixture_csv(tmp_path / 'hour.csv'))
    split, manifest = split_days(frame)
    assert [manifest['splits'][key]['days'] for key in ['train', 'validation', 'test']] == [24, 8, 8]
    assert set(split.loc['2020-01-24']) == {'train'}
    assert set(split.loc['2020-01-25']) == {'validation'}
    assert set(split.loc['2020-02-02']) == {'test'}


def test_duplicate_timestamps_rejected(tmp_path):
    from demand_forecast.data import load_hourly
    path = fixture_csv(tmp_path / 'hour.csv')
    raw = pd.read_csv(path)
    pd.concat([raw, raw.iloc[:1]]).to_csv(path, index=False)
    with pytest.raises(ValueError, match='duplicate'):
        load_hourly(path)


def test_missing_date_cannot_silently_disappear(tmp_path):
    from demand_forecast.data import load_hourly
    path = fixture_csv(tmp_path / 'hour.csv')
    raw = pd.read_csv(path)
    raw.loc[0, 'dteday'] = None
    raw.to_csv(path, index=False)
    with pytest.raises(ValueError, match='Dates'):
        load_hourly(path)


def test_noninteger_counts_rejected(tmp_path):
    from demand_forecast.data import load_hourly
    path = fixture_csv(tmp_path / 'hour.csv')
    raw = pd.read_csv(path).astype({'cnt': float})
    raw.loc[0, 'cnt'] = .5
    raw.to_csv(path, index=False)
    with pytest.raises(ValueError, match='counts'):
        load_hourly(path)


@pytest.fixture(scope='module')
def trained(tmp_path_factory):
    from demand_forecast.training import train
    folder = tmp_path_factory.mktemp('forecast')
    source = fixture_csv(folder / 'hour.csv')
    output = folder / 'results'
    train(output, source_path=source)
    return output


def test_training_exports_reconcile_and_selection_uses_validation(trained):
    metrics = json.loads((trained / 'metrics.json').read_text())
    predictions = pd.read_csv(trained / 'predictions.csv')
    final = predictions[(predictions['split'] == 'test') & (predictions['role'] == 'selected')]
    recomputed = np.mean(np.abs(final.y_true - final.y_pred))
    assert recomputed == pytest.approx(metrics['test']['selected']['mae'])
    assert metrics['selection']['partition'] == 'validation'
    assert metrics['selection']['selected_model'] in metrics['validation']
    assert len((trained / 'artifact.json').read_text()) > 100


def test_service_forecast_has_24_rows_and_no_future_dependence(trained):
    from demand_forecast.service import ForecastService
    service = ForecastService(trained)
    meta = service.metadata()
    result = service.forecast(meta['origins'][0])
    assert len(result['rows']) == result['horizon_hours'] == 24
    assert result['kind'] == 'historical_replay'
    assert all(row['prediction'] >= 0 for row in result['rows'])
    assert all(row['actual'] is not None for row in result['rows'])


def test_custom_history_never_falls_back_to_archive(trained):
    from demand_forecast.service import ForecastService
    service = ForecastService(trained)
    origin = service.metadata()['origins'][0]
    result = service.forecast(origin, history=[])
    assert result['kind'] == 'custom_history'
    assert all(row['actual'] is None for row in result['rows'])
    assert not any(row['lag24_observed'] or row['lag168_observed'] for row in result['rows'])
    assert result['warnings']


def test_independent_result_verifier_rejects_changed_metric(trained, tmp_path):
    import shutil
    script = Path(__file__).parents[1] / 'scripts' / 'verify_results.py'
    assert script.exists(), 'Independent CSV reconciliation command is missing.'
    valid = subprocess.run([sys.executable, str(script), '--results', str(trained)], capture_output=True, text=True)
    assert valid.returncode == 0, valid.stderr
    changed = tmp_path / 'changed'
    shutil.copytree(trained, changed)
    metrics = json.loads((changed / 'metrics.json').read_text())
    metrics['test']['selected']['mae'] += 1
    (changed / 'metrics.json').write_text(json.dumps(metrics))
    invalid = subprocess.run([sys.executable, str(script), '--results', str(changed)], capture_output=True, text=True)
    assert invalid.returncode != 0
    assert 'mae' in invalid.stderr.lower()


@pytest.mark.parametrize('history', [
    [{'timestamp': '2020-02-10T00:00:00', 'count': 1}],
    [{'timestamp': '2019-12-31T23:00:00', 'count': True}],
    [{'timestamp': '2019-12-31T23:00:00', 'count': float('nan')}],
    [{'timestamp': '2019-12-31T23:00:00', 'count': -1}],
    [{'timestamp': '2019-12-31T23:00:00', 'count': 1}] * 2,
])
def test_custom_history_invalid_values_rejected(trained, history):
    from demand_forecast.service import ForecastService
    with pytest.raises(ValueError):
        ForecastService(trained).forecast('2020-02-10', history=history)


@pytest.mark.parametrize('origin', ['bad', '2020-02-10T01:00:00', '2020-02-10T00:00:00Z', True])
def test_invalid_origin_rejected(trained, origin):
    from demand_forecast.service import ForecastService
    with pytest.raises(ValueError):
        ForecastService(trained).forecast(origin, history=[])

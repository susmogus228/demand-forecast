"""Frozen chronological evaluation and export pipeline."""

import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .data import (FEATURES, acquire, baseline, fit_history_statistics, impute,
                   load_hourly, make_features, sha256, split_days, write_json)

PROTOCOL = {
    'version': '1.0', 'primary_metric': 'mae', 'train_validation_test_day_fractions': [.6, .2, .2],
    'origin': 'daily midnight', 'horizon_hours': 24, 'warmup_days': 7,
    'features': FEATURES, 'calendar': 'hour, weekday, month cycles and weekend; no holidays or actual future weather',
    'lag_semantics': 'exact naive-local timestamp lookups at 24 and 168 hours before each target',
    'availability': 'counts strictly before origin; previous 23:00 count assumed available at midnight',
    'missing': 'unknown targets excluded from every score; training-only lag median and fixed indicators',
    'baseline': 'lag168, then lag24, then training target-hour median, then training overall median',
    'candidates': {'seasonal_naive': {}, 'ridge': {'alpha': 10},
                   'hist_gradient_boosting': {'loss': 'squared_error', 'learning_rate': .1, 'max_iter': 100,
                                             'max_leaf_nodes': 15, 'l2_regularization': 1, 'early_stopping': False, 'random_state': 42}},
    'selection': 'lowest validation MAE; ties within 1e-12: baseline, Ridge, boosting',
    'postprocess': 'clip below zero, no rounding',
    'final_test': 'selected candidate refit on development; fixed baseline; rolling observed history; no parameter updates',
    'uncertainty': 'no prediction intervals or population uncertainty claim',
}


def protocol_hash():
    return hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest()


def metric(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    if len(y_true) == 0:
        raise ValueError('No observed evaluation targets.')
    errors = y_pred - y_true
    return {'n': len(errors), 'mae': float(np.abs(errors).mean()), 'rmse': float(np.sqrt(np.square(errors).mean()))}


def candidate(name):
    if name == 'ridge':
        return make_pipeline(StandardScaler(), Ridge(alpha=10))
    if name == 'hist_gradient_boosting':
        return HistGradientBoostingRegressor(**PROTOCOL['candidates'][name])
    return None


def predict_model(bundle, features):
    if bundle['selected_model'] == 'seasonal_naive':
        return baseline(features, bundle['statistics'])[0]
    return np.maximum(0., bundle['model'].predict(impute(features, bundle['statistics'])))


def _export_rows(timestamps, y, predictions, raw_features, split, model, role, routes):
    return pd.DataFrame({'origin': timestamps.normalize().strftime('%Y-%m-%dT00:00:00'),
                         'target_timestamp': timestamps.strftime('%Y-%m-%dT%H:%M:%S'),
                         'horizon': timestamps.hour, 'split': split, 'model': model, 'role': role,
                         'y_true': np.asarray(y), 'y_pred': predictions,
                         'lag24_observed': raw_features.lag24.notna().to_numpy(),
                         'lag168_observed': raw_features.lag168.notna().to_numpy(),
                         'baseline_source': routes})


def train(output: Path, source_path: Path | None = None):
    """Fit/evaluate the fixed protocol. Caller supplies a new or intentional output directory."""
    with threadpool_limits(limits=1):
        return _train(Path(output), source_path)


def _train(output, source_path):
    started = time.perf_counter()
    output.mkdir(parents=True, exist_ok=True)
    if source_path is None:
        source_path, source = acquire(output / 'source')
    else:
        source_path = Path(source_path)
        source = {'kind': 'user_supplied_csv', 'filename': source_path.name,
                  'hour_csv_sha256': sha256(source_path), 'license': 'Caller must supply permission and attribution.'}
    frame, validation = load_hourly(source_path)
    partition, split_manifest = split_days(frame)
    raw_features = make_features(frame, frame.index)
    warmup_end = frame.index.min().normalize() + pd.Timedelta(days=7)
    observed = frame.cnt.notna()
    train_mask = (partition == 'train') & observed & (frame.index >= warmup_end)
    val_mask = (partition == 'validation') & observed
    test_mask = (partition == 'test') & observed
    statistics = fit_history_statistics(frame[partition == 'train'], raw_features[train_mask])
    write_json(output / 'protocol.json', PROTOCOL)
    write_json(output / 'source_manifest.json', source)
    split_manifest['protocol_sha256'] = protocol_hash()
    write_json(output / 'split_manifest.json', split_manifest)
    validation['partitions'] = {name: {'grid_hours': int((partition == name).sum()),
                                      'observed_targets': int(((partition == name) & observed).sum()),
                                      'missing_targets': int(((partition == name) & ~observed).sum())}
                                for name in ['train', 'validation', 'test']}
    validation['training_rows_after_warmup'] = int(train_mask.sum())
    validation['lag_missing_by_split'] = {name: {lag: int(raw_features.loc[partition == name, lag].isna().sum())
                                                for lag in ['lag24', 'lag168']}
                                        for name in ['train', 'validation', 'test']}
    write_json(output / 'data_validation.json', validation)
    y_train = frame.loc[train_mask, 'cnt'].to_numpy()
    x_train = impute(raw_features[train_mask], statistics)
    x_val = raw_features[val_mask]
    baseline_val, routes_val = baseline(x_val, statistics)
    validation_metrics, exports = {}, []
    for name in PROTOCOL['candidates']:
        fitted = candidate(name)
        if fitted is None:
            predicted = baseline_val
        else:
            fitted.fit(x_train, y_train)
            predicted = np.maximum(0., fitted.predict(impute(x_val, statistics)))
        validation_metrics[name] = metric(frame.loc[val_mask, 'cnt'], predicted)
        exports.append(_export_rows(x_val.index, frame.loc[val_mask, 'cnt'], predicted, x_val,
                                    'validation', name, 'candidate', routes_val))
    order = list(PROTOCOL['candidates'])
    best_score = min(value['mae'] for value in validation_metrics.values())
    selected = next(name for name in order if validation_metrics[name]['mae'] <= best_score + 1e-12)
    selection = {'partition': 'validation', 'metric': 'mae', 'selected_model': selected,
                 'scores': {name: value['mae'] for name, value in validation_metrics.items()},
                 'tie_tolerance': 1e-12, 'tie_order': order, 'protocol_sha256': protocol_hash()}
    write_json(output / 'selection.json', selection)
    dev_mask = (partition != 'test') & observed & (frame.index >= warmup_end)
    dev_statistics = fit_history_statistics(frame[partition != 'test'], raw_features[dev_mask])
    final_model = candidate(selected)
    if final_model is not None:
        final_model.fit(impute(raw_features[dev_mask], dev_statistics), frame.loc[dev_mask, 'cnt'])
    bundle = {'selected_model': selected, 'model': final_model, 'statistics': dev_statistics,
              'protocol_sha256': protocol_hash(), 'feature_names': FEATURES}
    x_test, y_test = raw_features[test_mask], frame.loc[test_mask, 'cnt']
    baseline_test, routes_test = baseline(x_test, dev_statistics)
    selected_test = predict_model(bundle, x_test)
    test_metrics = {'selected': metric(y_test, selected_test), 'baseline': metric(y_test, baseline_test)}
    delta = test_metrics['selected']['mae'] - test_metrics['baseline']['mae']
    base_mae = test_metrics['baseline']['mae']
    test_metrics['comparison'] = {'mae_difference_selected_minus_baseline': delta,
                                 'relative_mae_difference': delta / base_mae if base_mae else None,
                                 'relative_denominator': 'baseline MAE', 'interval': None}
    test_metrics['by_horizon'] = [{'horizon': hour, **metric(y_test.loc[y_test.index.hour == hour], selected_test[y_test.index.hour == hour])}
                                  for hour in range(24) if np.any(y_test.index.hour == hour)]
    for name, role, predicted in [(selected, 'selected', selected_test), ('seasonal_naive', 'baseline', baseline_test)]:
        exports.append(_export_rows(x_test.index, y_test, predicted, x_test, 'test', name, role, routes_test))
    all_predictions = pd.concat(exports, ignore_index=True)
    all_predictions.to_csv(output / 'predictions.csv', index=False)
    frame.to_csv(output / 'observations.csv', date_format='%Y-%m-%dT%H:%M:%S')
    pd.DataFrame({'timestamp': frame.index.strftime('%Y-%m-%dT%H:%M:%S'), 'split': partition.to_numpy(),
                  'target_observed': observed.to_numpy(), 'warmup': frame.index < warmup_end}).to_csv(output / 'splits.csv', index=False)
    joblib.dump(bundle, output / 'model.joblib')
    metrics = {'kind': 'recorded_historical_evaluation', 'selection': selection, 'validation': validation_metrics,
               'test': test_metrics, 'baseline_fallback_counts': {'validation': pd.Series(routes_val).value_counts().to_dict(),
                                                                'test': pd.Series(routes_test).value_counts().to_dict()},
               'source_sha256': source['hour_csv_sha256'], 'protocol_sha256': protocol_hash(),
               'runtime_seconds': time.perf_counter() - started, 'native_threads': 1}
    write_json(output / 'metrics.json', metrics)
    artifact = {'file': 'model.joblib', 'sha256': sha256(output / 'model.joblib'),
                'observations_sha256': sha256(output / 'observations.csv'), 'predictions_sha256': sha256(output / 'predictions.csv'),
                'source_sha256': source['hour_csv_sha256'], 'protocol_sha256': protocol_hash(),
                'selected_model': selected, 'python': platform.python_version(),
                'versions': {name: importlib.metadata.version(name) for name in ['numpy', 'pandas', 'scipy', 'scikit-learn', 'joblib']},
                'purpose': 'Trusted local artifact; never deserialize untrusted joblib files.',
                'fit_end_exclusive': split_manifest['splits']['test']['start']}
    write_json(output / 'artifact.json', artifact)
    _report(output, metrics, validation, split_manifest, source)
    _plots(output, all_predictions, metrics)
    return metrics


def _report(output, metrics, validation, splits, source):
    table = '\n'.join(f"| {name} | {m['mae']:.3f} | {m['rmse']:.3f} | {m['n']} |" for name, m in metrics['validation'].items())
    selected, base = metrics['test']['selected'], metrics['test']['baseline']
    text = f"""# DemandForecast evaluation

The frozen validation rule selected **{metrics['selection']['selected_model']}**. The final historical test MAE is **{selected['mae']:.3f} rentals/hour**, compared with **{base['mae']:.3f}** for seasonal naive with fallback. These measurements concern one old bicycle-rental system and one chronological split.

## Data and split

Source kind: `{source['kind']}`. CSV SHA-256: `{source['hour_csv_sha256']}`. Observed rows: {validation['source_rows']}; full grid hours: {validation['grid_hours']}; absent hours: {validation['missing_timestamp_count']}. Missing targets remain unknown. No actual future weather or target components enter the model.

{json.dumps(splits['splits'], indent=2)}

At each daily midnight origin, forecasts cover hours 0–23. Previous hours are assumed available without reporting delay. Lags refer to exact dataset-local timestamps. Scoring uses rolling observed history; model parameters remain frozen. This is not one long-range forecast from the beginning of test.

## Validation selection

| Candidate | MAE | RMSE | Observed hours |
|---|---:|---:|---:|
{table}

## Final test

Selected MAE: {selected['mae']:.6f}; RMSE: {selected['rmse']:.6f}; observed hours: {selected['n']}. Baseline MAE: {base['mae']:.6f}. Selected-minus-baseline MAE: {metrics['test']['comparison']['mae_difference_selected_minus_baseline']:.6f}. The selected model was refit on development data before this test; test did not choose its parameters.

## Limits

No prediction intervals are estimated. Scores describe observed hours; the mechanism behind absent hours is unknown, so excluded targets may differ from observed targets. A single time split cannot separate seasonality, growth, or other changes. No present-day or China deployment performance follows from these results. Custom histories can be outside the evaluated distribution. Predictions and exact split IDs are exported for independent recalculation. Source attribution and license details are in source_manifest.json and docs/SOURCES.md.
"""
    (output / 'report.md').write_text(text, encoding='utf-8')


def _plots(output, predictions, metrics):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder = output / 'figures'
    folder.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11})
    selected = predictions[(predictions.split == 'test') & (predictions.role == 'selected')].copy()
    selected['target_timestamp'] = pd.to_datetime(selected.target_timestamp)
    first = selected[selected.target_timestamp < selected.target_timestamp.min() + pd.Timedelta(days=7)]
    fig, ax = plt.subplots(figsize=(12, 4.5), layout='constrained')
    ax.plot(first.target_timestamp, first.y_true, label='Observed', color='#202020', lw=1.5)
    ax.plot(first.target_timestamp, first.y_pred, label=metrics['selection']['selected_model'], color='#0969da', lw=1.3)
    ax.set(title='First seven test days: daily midnight forecasts', ylabel='Rentals per hour', xlabel='Dataset-local timestamp')
    ax.legend(frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    fig.autofmt_xdate()
    for extension in ['png', 'svg']:
        fig.savefig(folder / f'forecast-example.{extension}', dpi=170)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.5), layout='constrained')
    names = list(metrics['validation'])
    labels = {'seasonal_naive': 'Seasonal naive with fallback', 'ridge': 'Ridge (alpha 10)',
              'hist_gradient_boosting': 'Histogram gradient boosting'}
    values = [metrics['validation'][name]['mae'] for name in names]
    bars = ax.barh([labels[name] for name in names], values,
                  color=['#0969da' if name == metrics['selection']['selected_model'] else '#6b7280' for name in names])
    ax.bar_label(bars, fmt='%.3f', padding=5)
    ax.set_xlim(0, max(values) * 1.16)
    ax.set(title='Validation comparison used for model selection', xlabel='MAE, rentals per observed hour')
    ax.invert_yaxis()
    ax.spines[['top', 'right']].set_visible(False)
    for extension in ['png', 'svg']:
        fig.savefig(folder / f'validation-comparison.{extension}', dpi=170)
    plt.close(fig)
    splits = json.loads((output / 'split_manifest.json').read_text(encoding='utf-8'))['splits']
    fig, ax = plt.subplots(figsize=(12, 2.7), layout='constrained')
    cursor = 0
    for name, color in [('train', '#4b5563'), ('validation', '#6b7280'), ('test', '#0969da')]:
        part = splits[name]
        ax.barh(0, part['days'], left=cursor, height=.6, color=color)
        ax.text(cursor + part['days'] / 2, 0, f"{name.title()}\n{part['days']} days", ha='center', va='center', color='white')
        ax.text(cursor, -.48, part['start'], ha='left', va='top', fontsize=9)
        cursor += part['days']
    ax.text(cursor, -.48, splits['test']['end_inclusive'], ha='right', va='top', fontsize=9)
    ax.set(xlim=(0, cursor), ylim=(-.9, .55), title='Chronological whole-day split; first seven train days are warm-up')
    ax.axis('off')
    for extension in ['png', 'svg']:
        fig.savefig(folder / f'chronological-split.{extension}', dpi=170)
    plt.close(fig)

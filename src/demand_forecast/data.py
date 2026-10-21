"""Validate hourly observations and construct timestamp-based features."""

import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE_URL = 'https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip'
SOURCE_PAGE = 'https://archive.ics.uci.edu/dataset/275/bike%2Bsharing%2Bdataset'
FEATURES = ['hour_sin', 'hour_cos', 'weekday_sin', 'weekday_cos', 'month_sin',
            'month_cos', 'weekend', 'lag24', 'lag168', 'lag24_missing', 'lag168_missing']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def acquire(folder: Path):
    """Download the official small archive and preserve its original notice."""
    folder.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(SOURCE_URL, headers={'User-Agent': 'DemandForecast/0.1'})
    with urllib.request.urlopen(request, timeout=45) as response:
        blob = response.read(5_000_001)
    if len(blob) > 5_000_000:
        raise ValueError('Source archive exceeds the 5 MB limit.')
    archive = folder / 'bike-sharing-dataset.zip'
    archive.write_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as zipped:
        for member in ['hour.csv', 'Readme.txt']:
            (folder / member).write_bytes(zipped.read(member))
    manifest = {'kind': 'official_uci', 'url': SOURCE_URL, 'page': SOURCE_PAGE,
                'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                'archive_sha256': sha256(archive), 'hour_csv_sha256': sha256(folder / 'hour.csv'),
                'notice_sha256': sha256(folder / 'Readme.txt'), 'license': 'CC-BY-4.0',
                'citation': 'Fanaee-T, H. (2013). Bike Sharing. UCI. DOI:10.24432/C5W894.'}
    return folder / 'hour.csv', manifest


def load_hourly(path: Path):
    raw = pd.read_csv(path)
    missing = {'dteday', 'hr', 'cnt'} - set(raw.columns)
    if missing:
        raise ValueError(f'Missing CSV columns: {sorted(missing)}')
    if len(raw) == 0:
        raise ValueError('The source CSV is empty.')
    hours = pd.to_numeric(raw['hr'], errors='coerce')
    counts = pd.to_numeric(raw['cnt'], errors='coerce')
    if not np.all(np.isfinite(hours)) or not np.all((hours >= 0) & (hours <= 23) & (hours % 1 == 0)):
        raise ValueError('Hours must be integers from 0 to 23.')
    if not np.all(np.isfinite(counts)) or not np.all((counts >= 0) & (counts % 1 == 0)):
        raise ValueError('Rental counts must be finite nonnegative integers.')
    try:
        dates = pd.to_datetime(raw['dteday'], format='%Y-%m-%d', errors='raise')
    except (ValueError, TypeError) as exc:
        raise ValueError('Dates must use YYYY-MM-DD.') from exc
    if dates.isna().any():
        raise ValueError('Dates must be present and use YYYY-MM-DD.')
    timestamps = pd.DatetimeIndex(dates + pd.to_timedelta(hours, unit='h'))
    if timestamps.has_duplicates:
        raise ValueError('Source contains duplicate timestamps.')
    calendar_checks = {}
    expected_fields = {'mnth': timestamps.month, 'hr': timestamps.hour,
                       'weekday': (timestamps.dayofweek + 1) % 7}
    for column, expected in expected_fields.items():
        if column in raw:
            mismatch = int(np.count_nonzero(pd.to_numeric(raw[column], errors='coerce').to_numpy() != expected))
            calendar_checks[column] = mismatch
            if mismatch:
                raise ValueError(f'Inconsistent calendar column: {column}.')
    grid = pd.date_range(timestamps.min().normalize(), timestamps.max().normalize() + pd.Timedelta(hours=23), freq='h')
    observed = pd.DataFrame({'cnt': counts.to_numpy(dtype=float)}, index=timestamps).sort_index()
    frame = observed.reindex(grid)
    frame.index.name = 'timestamp'
    validation = {'source_rows': len(raw), 'grid_hours': len(grid),
                  'missing_timestamp_count': int(frame.cnt.isna().sum()),
                  'duplicate_timestamp_count': 0, 'calendar_mismatches': calendar_checks,
                  'first_timestamp': grid.min().isoformat(), 'last_timestamp': grid.max().isoformat(),
                  'source_sha256': sha256(path), 'missing_hours_assumed_zero': False}
    return frame, validation


def split_days(frame):
    days = pd.date_range(frame.index.min().normalize(), frame.index.max().normalize(), freq='D')
    first, second = int(.6 * len(days)), int(.8 * len(days))
    if first <= 7 or second <= first or second >= len(days):
        raise ValueError('At least 15 calendar days are required for the fixed protocol.')
    label = pd.Series('test', index=frame.index, name='split')
    label.loc[label.index < days[second]] = 'validation'
    label.loc[label.index < days[first]] = 'train'
    partitions = {}
    for name, subset in [('train', days[:first]), ('validation', days[first:second]), ('test', days[second:])]:
        partitions[name] = {'start': subset[0].strftime('%Y-%m-%d'), 'end_inclusive': subset[-1].strftime('%Y-%m-%d'), 'days': len(subset)}
    return label, {'time_interpretation': 'naive dataset-local calendar; no UTC or DST reconstruction',
                   'origin': 'daily 00:00', 'horizons': list(range(24)), 'warmup_days': 7,
                   'splits': partitions}


def make_features(frame, targets):
    targets = pd.DatetimeIndex(targets)
    result = pd.DataFrame(index=targets)
    for name, values, period in [('hour', targets.hour, 24), ('weekday', targets.dayofweek, 7), ('month', targets.month - 1, 12)]:
        result[f'{name}_sin'] = np.sin(2 * np.pi * values / period)
        result[f'{name}_cos'] = np.cos(2 * np.pi * values / period)
    result['weekend'] = (targets.dayofweek >= 5).astype(float)
    for lag in [24, 168]:
        values = frame['cnt'].reindex(targets - pd.Timedelta(hours=lag)).to_numpy(dtype=float)
        result[f'lag{lag}'] = values
        result[f'lag{lag}_missing'] = np.isnan(values).astype(float)
    return result[FEATURES]


def fit_history_statistics(frame, features):
    medians = {key: float(features[key].median()) for key in ['lag24', 'lag168']}
    if not all(np.isfinite(v) for v in medians.values()):
        raise ValueError('Training data must contain observations for both lags.')
    observed = frame.dropna(subset=['cnt'])
    if observed.empty:
        raise ValueError('Training counts are empty.')
    return {'lag_medians': medians, 'hour_medians': {str(int(k)): float(v) for k, v in observed.groupby(observed.index.hour).cnt.median().items()},
            'overall_median': float(observed.cnt.median())}


def impute(features, statistics):
    return features.fillna(statistics['lag_medians'])


def baseline(features, statistics):
    values, routes = [], []
    for timestamp, row in features.iterrows():
        if pd.notna(row['lag168']):
            value, route = row['lag168'], 'lag168'
        elif pd.notna(row['lag24']):
            value, route = row['lag24'], 'lag24'
        else:
            key = str(timestamp.hour)
            value = statistics['hour_medians'].get(key, statistics['overall_median'])
            route = 'training_hour_median' if key in statistics['hour_medians'] else 'training_overall_median'
        values.append(max(0., float(value)))
        routes.append(route)
    return np.asarray(values), routes

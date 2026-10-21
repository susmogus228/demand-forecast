"""Validated inference for historical replay and explicit custom histories."""

import json
import math
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .data import baseline, make_features, sha256
from .training import predict_model


def parse_origin(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T00:00(?::00)?)?', value):
        raise ValueError('Origin must be a naive midnight date, YYYY-MM-DD or YYYY-MM-DDT00:00:00.')
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('Origin date is invalid.') from exc
    if stamp.year < 1900 or stamp.year > 2200:
        raise ValueError('Origin year must be between 1900 and 2200.')
    return stamp


def custom_frame(records, origin):
    if not isinstance(records, list) or len(records) > 10_000:
        raise ValueError('History must be an array containing at most 10000 hourly records.')
    rows, seen = [], set()
    for row in records:
        if not isinstance(row, dict) or set(row) != {'timestamp', 'count'}:
            raise ValueError('Each history record must contain only timestamp and count.')
        text, count = row['timestamp'], row['count']
        if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:00(?::00)?', text):
            raise ValueError('History timestamps must be naive whole hours in ISO format.')
        try:
            stamp = pd.Timestamp(text)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('History timestamp is invalid.') from exc
        if stamp >= origin:
            raise ValueError('History timestamps must precede the forecast origin.')
        if stamp in seen:
            raise ValueError('History contains duplicate timestamps.')
        if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count) or count < 0 or count % 1 or count > 10_000_000:
            raise ValueError('History counts must be finite nonnegative integers no greater than 10000000.')
        seen.add(stamp)
        rows.append((stamp, float(count)))
    return pd.DataFrame({'cnt': [count for _, count in rows]}, index=pd.DatetimeIndex([stamp for stamp, _ in rows]))


class ForecastService:
    def __init__(self, results_dir: Path):
        self.results_dir = Path(results_dir)
        self.artifact = self._read('artifact.json')
        if sha256(self.results_dir / 'model.joblib') != self.artifact['sha256']:
            raise ValueError('Model artifact checksum mismatch.')
        if sha256(self.results_dir / 'observations.csv') != self.artifact['observations_sha256']:
            raise ValueError('Observation checksum mismatch.')
        self.bundle = joblib.load(self.results_dir / 'model.joblib')
        self.metrics = self._read('metrics.json')
        self.source = self._read('source_manifest.json')
        self.splits = self._read('split_manifest.json')
        frame = pd.read_csv(self.results_dir / 'observations.csv')
        self.frame = frame.set_index(pd.DatetimeIndex(pd.to_datetime(frame.pop('timestamp'))))
        bounds = self.splits['splits']['test']
        self.origins = pd.date_range(bounds['start'], bounds['end_inclusive'], freq='D').strftime('%Y-%m-%d').tolist()

    def _read(self, filename):
        return json.loads((self.results_dir / filename).read_text(encoding='utf-8'))

    def metadata(self):
        return {'name': 'DemandForecast', 'selected_model': self.bundle['selected_model'],
                'origins': self.origins, 'available_origins': self.origins,
                'horizon_hours': 24, 'metrics': self.metrics, 'source': self.source,
                'splits': self.splits, 'provenance': self.artifact,
                'limitations': ['One historical bicycle-rental system, 2011–2012 for the bundled UCI run.',
                                'Rolling daily origins; counts before midnight assumed available.',
                                'Naive dataset-local calendar; no UTC/DST reconstruction.',
                                'No prediction interval or new-city performance guarantee.']}

    def diagnostics(self):
        from .diagnostics import build_diagnostics
        return build_diagnostics(self.results_dir)

    def forecast(self, origin: str, history: list[dict] | None = None):
        stamp = parse_origin(origin)
        warnings = []
        if history is None:
            if stamp.strftime('%Y-%m-%d') not in self.origins:
                raise ValueError('Historical replay origin must be one of the available final-test dates.')
            history_frame = self.frame.loc[self.frame.index < stamp]
            kind = 'historical_replay'
        else:
            history_frame = custom_frame(history, stamp)
            kind = 'custom_history'
            warnings.append('Custom history is outside the recorded benchmark; model training statistics supply missing-lag fallbacks.')
        targets = pd.date_range(stamp, periods=24, freq='h')
        features = make_features(history_frame, targets)
        baseline_values, routes = baseline(features, self.bundle['statistics'])
        with threadpool_limits(limits=1):
            predictions = predict_model(self.bundle, features)
        if np.any(features.lag24.isna()) or np.any(features.lag168.isna()):
            warnings.append('Some exact timestamp lags are absent; training-only imputation and baseline fallbacks were used.')
        actual = self.frame.cnt.reindex(targets) if history is None else pd.Series(np.nan, index=targets)
        rows = [{'timestamp': target.isoformat(), 'horizon': hour, 'prediction': float(predictions[hour]),
                 'baseline': float(baseline_values[hour]), 'actual': None if pd.isna(actual.iloc[hour]) else float(actual.iloc[hour]),
                 'lag24_observed': bool(pd.notna(features.iloc[hour].lag24)),
                 'lag168_observed': bool(pd.notna(features.iloc[hour].lag168)), 'baseline_source': routes[hour]}
                for hour, target in enumerate(targets)]
        return {'origin': stamp.isoformat(), 'horizon_hours': 24, 'kind': kind,
                'selected_model': self.bundle['selected_model'], 'warnings': warnings, 'rows': rows}

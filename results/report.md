# DemandForecast evaluation

The frozen validation rule selected **ridge**. The final historical test MAE is **60.295 rentals/hour**, compared with **64.831** for seasonal naive with fallback. These measurements concern one old bicycle-rental system and one chronological split.

## Data and split

Source kind: `official_uci`. CSV SHA-256: `e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f`. Observed rows: 17379; full grid hours: 17544; absent hours: 165. Missing targets remain unknown. No actual future weather or target components enter the model.

{
  "train": {
    "start": "2011-01-01",
    "end_inclusive": "2012-03-13",
    "days": 438
  },
  "validation": {
    "start": "2012-03-14",
    "end_inclusive": "2012-08-06",
    "days": 146
  },
  "test": {
    "start": "2012-08-07",
    "end_inclusive": "2012-12-31",
    "days": 147
  }
}

At each daily midnight origin, forecasts cover hours 0–23. Previous hours are assumed available without reporting delay. Lags refer to exact dataset-local timestamps. Scoring uses rolling observed history; model parameters remain frozen. This is not one long-range forecast from the beginning of test.

## Validation selection

| Candidate | MAE | RMSE | Observed hours |
|---|---:|---:|---:|
| seasonal_naive | 62.236 | 106.361 | 3502 |
| ridge | 60.768 | 97.206 | 3502 |
| hist_gradient_boosting | 66.324 | 104.211 | 3502 |

## Final test

Selected MAE: 60.294644; RMSE: 96.775335; observed hours: 3488. Baseline MAE: 64.830849. Selected-minus-baseline MAE: -4.536204. The selected model was refit on development data before this test; test did not choose its parameters.

## Limits

No prediction intervals are estimated. Scores describe observed hours; the mechanism behind absent hours is unknown, so excluded targets may differ from observed targets. A single time split cannot separate seasonality, growth, or other changes. No present-day or China deployment performance follows from these results. Custom histories can be outside the evaluated distribution. Predictions and exact split IDs are exported for independent recalculation. Source attribution and license details are in source_manifest.json and docs/SOURCES.md.

# Changelog

## 0.1.1 — 2026-10-20

- Added paired model/baseline MAE diagnostics for final-test months, target hours and days.
- Added GET `/api/diagnostics`, reproducible versioned derived files and validation-candidate tables.
- Added loading/error/retry handling and collapsed raw JSON in Evaluation.
- Kept the frozen model, original predictions, metrics, selection and research protocol unchanged.

## 0.1.0 — 2026-10-19

- Added timestamp-safe daily-origin forecasting with a frozen chronological evaluation.
- Compared seasonal naive, Ridge and histogram gradient boosting; exported the actual selection and final test.
- Added a reusable Python service, CLI, local application/API, provenance, plots and independent result reconciliation.
- Documented missing hours, custom-history behavior, model limitations and dataset attribution.

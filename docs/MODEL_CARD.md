# Model card

**Task:** Hourly bicycle-rental count regression, next 24 hours at each daily midnight origin.

**Intended use:** Reproducible educational evaluation, historical replay, and local integration examples. Users can inspect feature availability and compare the selected model against a seasonal baseline.

**Data:** UCI Bike Sharing hourly counts, 2011–2012. One rental system, 17,379 observed rows. The exact raw file, splits, provenance and validation counts accompany the release.

**Model:** Ridge regression with alpha 10 and training-only standardized features. Validation compared it with a seasonal naive fallback rule and a fixed histogram gradient boosting model. The final Ridge pipeline refits on development data. See `results/protocol.json` for feature/selection parameters and `artifact.json` for versions and hashes.

**Evaluation:** Chronological whole-day 60/20/20 split. Final test dates 2012-08-07 through 2012-12-31, 3,488 observed hours. MAE 60.294644 and RMSE 96.775335 rentals/hour. Baseline MAE 64.830849. No test-tuned hyperparameters or uncertainty interval.

**Availability assumptions:** Daily midnight forecasts may use actual rental counts through the preceding 23:00 hour without reporting delay. Calendar features and exact timestamp lags 24/168 are the only inputs. Target-day weather and count components are excluded. Missing lags use development-fitted medians/indicators for the released final model; missing evaluation targets are excluded consistently.

**Limitations:** One old system and one split do not establish transfer performance. Naive-local timestamp arithmetic has no audited timezone/DST reconstruction. Point forecasts omit predictive uncertainty. The model can extrapolate poorly under unusual events or different demand scales. Custom history remains outside the benchmark.

**Safety and deployment:** No operational allocation decision is validated here. The demo is a loopback local service. It has no production authentication, monitoring, availability or drift guarantee. Load only trusted joblib files; manifest hash verification detects accidental mismatch but cannot authenticate an attacker-supplied manifest.

**Maintenance:** Changes to features, split rules, model selection or source data require a new protocol/version and new result exports. Keep old results when reporting comparisons.

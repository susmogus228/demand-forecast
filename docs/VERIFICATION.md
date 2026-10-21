# Core verification evidence

Date: 2026-10-19. This record covers the domain/training/service workstream. Browser/HTTP/build verification belongs to the integrated release evidence.

- Initial pre-implementation run: four failed imports and twelve fixture setup errors because the package did not exist yet.
- Additional regression RED: missing dates returned an unrelated calendar-field error; added explicit date-presence validation.
- Independent reconciliation RED: the result-verifier command did not exist. Added a standard-library implementation and a test that corrupts a metric to prove rejection.
- Final core suite: **19 passed in 37.10 seconds**, using the new portfolio-local virtual environment and one native thread. A previous temporary-directory setup failure was infrastructure setup, not a passing check.
- Actual UCI experiment completed through `python -m demand_forecast train --output results`, with one native compute thread.
- Independent CSV reconciliation verified **17,482 prediction rows** and **3,488 final-test observed hours**, including every candidate MAE/RMSE/count, horizon metrics, target truth, lag availability/timestamps, model selection, protocol hash and artifact/CSV hashes.

The tests cover timestamp-based lag behavior with missing hours, future-data invariance, whole-day split boundaries, duplicate/missing/invalid observations, training exports, historical replay, custom history isolation, invalid histories/origins, and independent metric-tamper detection. They use a synthetic fixture for fast deterministic checks; the separate reconciliation command checks the actual recorded UCI outputs.

Final test MAE: Ridge 60.29464427242167; seasonal baseline 64.83084862385321. These are measured historical point estimates, without interval claims.


## Paired diagnostic fix, 2026-10-20

Scope: present the failure breakdown identified in the portfolio audit. Preserve the frozen experiment and add derived reporting, an API endpoint and Evaluation tables. No retraining, new data, statistical-significance claim or deployment.

- TDD RED: 9 diagnostic cases failed because the diagnostic module did not exist; the HTTP case returned 404 for the missing endpoint. Four Node UI cases failed because the new UI module did not exist.
- Python: `python -m pytest -q --basetemp work/audit-fixes-2026-10-20/pytest-full` passed **36 tests in 20.76 seconds**. This includes 10 diagnostic/API tests: paired target integrity, count/sign/hour mapping, missing/duplicate/truth-mismatched/nonfinite rejection, real-audit reconciliation, CSV tamper rejection, endpoint and OpenAPI.
- Node: `node --test tests/evaluation-ui.cjs` passed **4 tests** for signed values/counts, error/retry, stale-response rejection and empty data. These are UI state tests with DOM adapters; they do not establish visual layout or screen-reader behavior.
- `python scripts/verify_results.py --results results` reconciled **17,482 original prediction rows and 3,488 test targets** with the saved metrics, truths, lags, selection and hashes.
- `python scripts/derive_diagnostics.py --results results --check` reproduced both new outputs. Counts reconcile to **2/5 months, 8/24 clock hours and 65/147 test days** with higher model MAE.
- The pre-edit SHA-256 snapshot of all **21 existing results files** is retained under ignored `work/audit-fixes-2026-10-20/frozen-results-before.json`. A post-edit comparison confirms that these files keep their original bytes. Only `results/diagnostics-v1.json` and `results/diagnostics-v1.md` were added to results.
- Browser verification and server restarts belong to the integrating parent task; they were not performed by this workstream. No Git push or public service verification was performed.

The installed pandas version is 3.0.6. Context7's official pandas groupby/datetime reference was consulted before implementation; the diagnostic uses standard-library CSV, datetime and `math.fsum` to avoid row-wise missing-value aggregation. The existing pandas-based inference/training path is unchanged.

## Integrated audit correction, 2026-10-20

See [the current integrated record](AUDIT_FIXES_2026-10-20.md) for the corrected behavior, fresh browser cases, result preservation and installed-wheel smoke. Earlier counts above describe their own source snapshots.

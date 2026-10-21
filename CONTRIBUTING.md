# Contributing

Create a project virtual environment and install `python -m pip install -e ".[dev]"`. Run `python -m pytest` and `python scripts/verify_results.py --results results` before proposing changes.

For a bug report, include the command or API request, Python/package versions, expected behavior and the smallest reproducible input. Remove private history records and credentials. Include a screenshot for an interface problem and specify the viewport.

Keep time availability explicit. Add a regression test for any change involving lags, split boundaries, missing data, preprocessing or custom history. Do not change protocol parameters after inspecting a final-test result. A research change needs a versioned protocol and a new result directory so reviewers can compare the old run.

For a pull request, describe the concrete behavior change and verification performed. Confirm dataset/asset attribution for new resources. Avoid committing environments, credentials, caches or temporary work files. The local demo does not establish production deployment readiness.

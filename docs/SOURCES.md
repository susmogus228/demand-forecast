# Sources and attribution

## Dataset

- **Source:** [UCI Bike Sharing](https://archive.ics.uci.edu/dataset/275/bike%2Bsharing%2Bdataset).
- **Official archive:** [bike+sharing+dataset.zip](https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip).
- **Citation:** Fanaee-T, H. (2013). *Bike Sharing* [Dataset]. UCI Machine Learning Repository. [DOI:10.24432/C5W894](https://doi.org/10.24432/C5W894).
- **Dataset license:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), as listed by UCI at retrieval on 2026-10-19. The project's MIT code license does not replace dataset terms.
- **Original notice:** [Preserved source Readme.txt](../results/source/Readme.txt).
- **Machine-readable provenance:** [source_manifest.json](../results/source_manifest.json).

The official archive SHA-256 is `b70182d0d0508e9abbb79306ce5c0cec34869000f8220175ac83d11dbe845401`; `hour.csv` SHA-256 is `e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f`.

The downloaded CSV contains 17,379 hourly records. The UCI webpage currently describes 17,389 instances. The project reports the count measured from its preserved file, not a corrected or assumed count. A full calendar grid has 17,544 hours and 165 missing timestamps; no missing count is filled with zero. The project derives features, splits, forecasts and plots from this file. It does not edit the original CSV.

## Methods and API references

- [sklearn time-series lagged-feature example](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html): background for time-aware evaluation. This project adds explicit daily origins and missing timestamp handling.
- [Ridge documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html).
- [HistGradientBoostingRegressor documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).

The implementation ran with sklearn 1.9.0, and `results/artifact.json` records actual installed package versions. Online stable docs may advance independently. No published benchmark score is compared directly with this project's different split and feature contract.

## Visual assets

Scientific figures in `results/figures/` come from the exported real predictions and metrics using Matplotlib. The frontend uses editable HTML/CSS/JavaScript and data-driven charts. Application screenshots must show the running application. No generated concept image represents a measured forecast or live application screenshot.

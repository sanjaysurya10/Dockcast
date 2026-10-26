# Experiments

## E1 — ML vs baselines (persistence, seasonal naive 7 d, ridge, LightGBM quantiles)

MLflow run `fb0d738826974ae9982cc4e96b96e5ba` · git `f67fa9c` · generated 2026-10-26 04:45 UTC · data 2026-04-28 23:45 → 2026-06-30 23:45 UTC

Rolling origin, 8 test weeks on Format B (PRD 9.1a, 13.1; `reports/folds.json`). Training: hourly issue times on all Format B history before each fold, early stopping on the last training week (15-min). Targets: state at t + h; closed, imputed and flat-lined targets excluded; every model scored on the same common rows. Features: lags, rolling, seasonal, calendar, station static (PRD 10.2-10.4); **no weather**. Means over folds (± std of fold MAE). Coverage = share inside P10-P90 (target 80 %).

| horizon | model | MAE | ± | RMSE | MASE | bias | coverage P10-P90 | width | rows |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| +30 | lgbm_global | 0.995 | 0.050 | 1.988 | 0.933 | -0.002 | 0.825 | 3.10 | 604621 |
| +30 | persistence | 1.066 | 0.058 | 2.218 | 1.000 | +0.000 | — | — | 604621 |
| +30 | ridge | 1.179 | 0.043 | 2.135 | 1.108 | +0.025 | — | — | 604621 |
| +30 | seasonal_naive_7d | 6.355 | 0.552 | 8.689 | 5.993 | -0.022 | — | — | 604621 |
| +60 | lgbm_global | 1.461 | 0.061 | 2.688 | 0.849 | -0.042 | 0.814 | 4.59 | 602561 |
| +60 | persistence | 1.721 | 0.087 | 3.326 | 1.000 | +0.001 | — | — | 602561 |
| +60 | ridge | 1.869 | 0.056 | 3.104 | 1.087 | +0.017 | — | — | 602561 |
| +60 | seasonal_naive_7d | 6.354 | 0.549 | 8.688 | 3.708 | -0.022 | — | — | 602561 |
| +120 | lgbm_global | 2.047 | 0.075 | 3.446 | 0.740 | -0.099 | 0.797 | 6.44 | 598447 |
| +120 | persistence | 2.768 | 0.141 | 4.989 | 1.000 | +0.002 | — | — | 598447 |
| +120 | ridge | 2.874 | 0.076 | 4.344 | 1.040 | +0.025 | — | — | 598447 |
| +120 | seasonal_naive_7d | 6.354 | 0.544 | 8.688 | 2.306 | -0.021 | — | — | 598447 |

**Champion per horizon (PRD 12.5):**

- +30: `lgbm_global` (MAE 0.995, coverage 0.825; lowest MAE with coverage in range)
- +60: `lgbm_global` (MAE 1.461, coverage 0.814; lowest MAE with coverage in range)
- +120: `lgbm_global` (MAE 2.047, coverage 0.797; lowest MAE with coverage in range)

**S1** (+60 MAE <= 0.85 x persistence = 1.463): lgbm_global 1.461 -> **met** (MASE 0.849).

Test rows per horizon (all folds), issued / valid target / common:

- +30: 617320 / 608186 / 604621
- +60: 615480 / 606358 / 602561
- +120: 611800 / 602702 / 598447

MAE by slice at +60 (mean over folds):

| slice | value | lgbm_global | persistence | ridge | seasonal_naive_7d |
|---|---|---:|---:|---:|---:|
| rush_hour | other | 1.203 | 1.271 | 1.549 | 6.337 |
| rush_hour | rush | 2.235 | 3.075 | 2.831 | 6.407 |
| weekend | weekday | 1.596 | 1.955 | 2.030 | 6.313 |
| weekend | weekend | 1.127 | 1.145 | 1.473 | 6.457 |
| capacity_band | 20-29 | 1.382 | 1.515 | 1.669 | 5.089 |
| capacity_band | 30-39 | 1.454 | 1.736 | 1.875 | 6.527 |
| capacity_band | 40+ | 1.539 | 1.874 | 2.028 | 7.206 |
| capacity_band | <20 | 1.126 | 1.225 | 1.322 | 3.253 |
| rebalance | flagged | 11.307 | 13.156 | 12.220 | 8.848 |
| rebalance | normal | 1.394 | 1.643 | 1.798 | 6.337 |

| fold | train end (UTC) | test start (UTC) | test end (UTC) |
|---:|---|---|---|
| 1 | 2026-05-05 21:45 | 2026-05-05 23:45 | 2026-05-12 23:45 |
| 2 | 2026-05-12 21:45 | 2026-05-12 23:45 | 2026-05-19 23:45 |
| 3 | 2026-05-19 21:45 | 2026-05-19 23:45 | 2026-05-26 23:45 |
| 4 | 2026-05-26 21:45 | 2026-05-26 23:45 | 2026-06-02 23:45 |
| 5 | 2026-06-02 21:45 | 2026-06-02 23:45 | 2026-06-09 23:45 |
| 6 | 2026-06-09 21:45 | 2026-06-09 23:45 | 2026-06-16 23:45 |
| 7 | 2026-06-16 21:45 | 2026-06-16 23:45 | 2026-06-23 23:45 |
| 8 | 2026-06-23 21:45 | 2026-06-23 23:45 | 2026-06-30 23:45 |


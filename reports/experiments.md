# Experiments

## E1 — Baselines (persistence, seasonal naive 7 d)

MLflow run `2692ee7f49494167ba225ccc3c9c5303` · git `0c5b9de` · generated 2026-10-26 00:34 UTC · data 2026-04-28 23:45 → 2026-06-30 23:45 UTC

Rolling origin, 8 test weeks, Format B (PRD 9.1a, 13.1); fold dates in `reports/folds.json`. Targets: state at t + h (bucket ending at t + h); closed, imputed and flat-lined targets excluded; all models scored on common rows. MAE/RMSE in bikes; values are means over folds (± std of fold MAE). No weather is used by these models.

| horizon | model | MAE | ± | RMSE | MASE | bias | rows |
|---:|---|---:|---:|---:|---:|---:|---:|
| +30 | persistence | 1.066 | 0.058 | 2.218 | 1.000 | +0.000 | 604621 |
| +30 | seasonal_naive_7d | 6.355 | 0.552 | 8.689 | 5.993 | -0.022 | 604621 |
| +60 | persistence | 1.721 | 0.087 | 3.326 | 1.000 | +0.001 | 602561 |
| +60 | seasonal_naive_7d | 6.354 | 0.549 | 8.688 | 3.708 | -0.022 | 602561 |
| +120 | persistence | 2.768 | 0.141 | 4.989 | 1.000 | +0.002 | 598447 |
| +120 | seasonal_naive_7d | 6.354 | 0.544 | 8.688 | 2.306 | -0.021 | 598447 |

Rows per horizon (all folds): issue times x stations / valid target / common:

- +30: 617320 / 608186 / 604621
- +60: 615480 / 606358 / 602561
- +120: 611800 / 602702 / 598447

Persistence MAE by slice at +60 (mean over folds):

- rush_hour: other 1.271, rush 3.075
- weekend: weekday 1.955, weekend 1.145
- capacity_band: 20-29 1.515, 30-39 1.736, 40+ 1.874, <20 1.225
- rebalance: flagged 13.156, normal 1.643

| fold | test start (UTC) | test end (UTC) |
|---:|---|---|
| 1 | 2026-05-05 23:45 | 2026-05-12 23:45 |
| 2 | 2026-05-12 23:45 | 2026-05-19 23:45 |
| 3 | 2026-05-19 23:45 | 2026-05-26 23:45 |
| 4 | 2026-05-26 23:45 | 2026-06-02 23:45 |
| 5 | 2026-06-02 23:45 | 2026-06-09 23:45 |
| 6 | 2026-06-09 23:45 | 2026-06-16 23:45 |
| 7 | 2026-06-16 23:45 | 2026-06-23 23:45 |
| 8 | 2026-06-23 23:45 | 2026-06-30 23:45 |


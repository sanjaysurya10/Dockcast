# DockCast

Station-level bike availability forecasting for Dublin Bikes: bikes at +30/+60/+120 min with a
P10-P90 range, and an honest account of where the model is wrong.

Status: **v1** (PRD 17, M0-M6). A live collector and a 15-min forecast job run in the cloud; the
API runs locally (`make serve`). Every number below is copied from a generated report and carries
its MLflow run ID; nothing is hand-typed.

## Results (E1 backtest)

From `reports/experiments.md`, MLflow run `e4819616d7034b90abcb3adc882313da` (git `ed13e96`).
Rolling origin over 8 test weeks (2026-05-05 to 2026-06-30 UTC), 115 stations, about 600 k common
test rows per horizon, 120-min gap between training end and test start. **No weather features.**
MAE in bikes, mean over folds.

| horizon | LightGBM quantile | persistence | ridge | MASE (LightGBM) | P10-P90 coverage |
|---:|---:|---:|---:|---:|---:|
| +30 | 0.995 | 1.066 | 1.179 | 0.933 | 0.825 |
| +60 | 1.461 | 1.721 | 1.869 | 0.849 | 0.814 |
| +120 | 2.047 | 2.768 | 2.874 | 0.740 | 0.797 |

- LightGBM is the champion at every horizon (lowest MAE with coverage in range, PRD 12.5).
- Success criterion S1 (+60 MAE <= 0.85 x persistence = 1.463) is **met by 0.002 bikes**
  (1.461; fold std 0.061). Treat it as borderline.
- Ridge is worse than persistence at every horizon.
- This run reproduces the original E1 run `fb0d738826974ae9982cc4e96b96e5ba` exactly: every value
  in the E1 table and in `reports/error_analysis.md` is identical.

Where it is wrong (`reports/error_analysis.md`, same run): the largest +60 errors are at busy
40-dock stations (Charlemont Place 2.939, Grand Canal Dock 2.923); rush hour MAE at +60 is 2.235
against 1.203 off-peak; rebalancing-flagged rows have +60 MAE 11.307.

Production model: bundle `lgbm-q-2026-06-30-3c421b6`, MLflow run
`5c34442ebc3a4b46aca09893377ab030`, trained on all Format B history to 2026-06-30.

## Limitations

- **No weather.** Weather is collected but not yet a model feature; the backtest is weather-free.
- **S1 is borderline** (0.002 bikes margin, well inside one fold std).
- **Untuned.** 51 of 72 LightGBM boosters used all 2000 rounds without early stopping
  (PRD 12.3 defaults); tuning is a v2 task.
- **Weekend +30:** LightGBM MAE 0.750 vs persistence 0.732 — slightly worse than "no change".
- **Rebalancing** is not observed directly; van moves show up as large errors (flagged rows).
- **Training/live gap.** Training data ends 2026-06-30; the live collector started 2026-10-22, so
  live forecasts run on a model that has not seen recent months.
- **New stations.** Station 118 is not in the training set and has no forecast until a retrain.
- **No trip data.** There are no origin-destination flows; only dock counts are modelled.
- Forecasts are estimates, not guarantees of availability.

## Architecture

```
GBFS feed (60 s) ─► collector ─► Postgres (raw status) ─► resample 15 min ─► features (cutoff-safe)
Historical CSVs ──► backfill ──┘                                               │
                                                     LightGBM P10/P50/P90 per horizon ◄─┘
                                                                │
                                   forecast job (every 15 min) ─► forecasts table ─► FastAPI
```

- `dockcast/ingest` — live GBFS collector, historical CSV loaders, calendar, weather.
- `dockcast/transform`, `dockcast/quality` — 15-min resample, gap and data-quality reports.
- `dockcast/features` — lags, rolling, seasonal, calendar, static; every feature takes a `cutoff`
  and has a leakage test in `tests/leakage/`.
- `dockcast/models`, `dockcast/evaluation` — baselines, ridge, LightGBM quantiles, rolling-origin
  backtest, champion selection, error analysis. Tracked in MLflow.
- `dockcast/serving`, `dockcast/api` — production training, forecast job, FastAPI.
- Stack: Python 3.12, uv, PostgreSQL (Supabase in the cloud), Alembic, LightGBM, scikit-learn,
  MLflow, FastAPI, Docker (Oracle Cloud VM). `deploy/oracle/README.md` has the cloud setup.

## Reproduce

Requires `uv`, Docker and GNU Make.

```bash
cp .env.example .env   # set POSTGRES_PORT / DATABASE_URL if 5432 is taken
make all               # setup, db-up, backfill, gaps, capacity, calendar, weather, resample,
                       # eda, backtest E=E1, error-analysis, results
make test              # ruff, mypy --strict, pytest (unit, leakage, integration, api)
```

`make all` downloads about 2.4 GB of historical CSVs and the E1 backtest takes about 3.5 hours on
a laptop. Outputs: `reports/experiments.md`, `reports/error_analysis.md`, `reports/site/index.html`.

**How v1 was checked:** the E1 table above was reproduced with `make backtest E=E1` and
`make error-analysis` on the existing local database. The download and load steps of `make all`
(`backfill` through `eda`) were **not** rerun from a fresh clone for this release.

Live pieces: `make collect` (poll the feed every 60 s), `make train`, `make forecast`,
`make serve` (API on localhost), `make health` (collector uptime).

## Data

Dublin Bikes data © Dublin City Council / Smart Dublin, CC BY 4.0. Weather data © Met Éireann.

## Licence

Code: MIT (see `LICENSE`).

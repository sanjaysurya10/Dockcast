# DockCast — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | DockCast — station-level bike availability forecasting for Dublin Bikes |
| Owner | Sanjay |
| Version | 1.0 |
| Date | 2026-10-15 |
| Status | Approved for build |
| Builder | Claude Code, guided by `CLAUDE.md` |

> **How to use this document.** This PRD is the single source of truth. Build it in the order of Section 17 (Releases & Milestones). Every section number is referenced from `CLAUDE.md` and from tasks. Anything marked **[VERIFY]** is an assumption that must be checked against real data or official docs before code depends on it. Anything marked **[DECISION]** is fixed — do not change it without the owner's approval.

---

## Table of contents

1. Summary
2. Goals, non-goals and success criteria
3. Users and use cases
4. Research questions
5. Data sources
6. System architecture
7. Repository structure
8. Database schema
9. Data pipeline (ingestion, cleaning, resampling)
10. Feature engineering
11. Targets and labels
12. Models
13. Evaluation and backtesting
14. Experiments
15. Backend API
16. Frontend (UI/UX)
17. Releases and milestones
18. Infrastructure, deployment and cost
19. Testing and quality
20. Observability and data health
21. Security, licensing and ethics
22. Risks and mitigations
23. Open questions and verification list
24. Glossary

---

## 1. Summary

DockCast forecasts how many bikes and free docks each Dublin Bikes station will have **30, 60 and 120 minutes** from now, estimates the **probability that a station runs empty or full** within the next hour, and explains **where and why the model is wrong**.

It is a data-science-first project: a rigorous, leakage-free forecasting study with an honest evaluation, served through a FastAPI backend and an interactive React + MapLibre frontend that opens on a 3D globe and flies into Dublin.

**Central research question:**
> How accurately can we forecast short-term bike availability across Dublin's shared bike network, and which temporal, spatial and station-level features give the biggest improvement over simple forecasting baselines?

---

## 2. Goals, non-goals and success criteria

### 2.1 Goals

- G1. Forecast available bikes per station at +30, +60, +120 min with calibrated uncertainty (10th / 50th / 90th percentiles).
- G2. Predict the probability that a station hits **zero bikes** or **zero docks** within the next 60 minutes.
- G3. Beat two naive baselines (persistence, seasonal naive) in an 8-fold rolling-origin backtest, and report the result honestly even if the margin is small.
- G4. Explain model behaviour: error by station, hour, horizon and station type; feature-group ablation.
- G5. Serve forecasts through a documented API and an interactive web app.
- G6. Be publishable: reproducible from a clean clone, documented, tested, deployed with HTTPS.

### 2.2 Non-goals

- NG1. **No invented flows.** No arcs between stations or cities unless they are computed from real trip data. The feeds provide station status, not trips **[VERIFY in M1]**. Use **net flow** (Section 10.6) instead.
- NG2. No real-time rebalancing instructions to an operator. Rebalancing is only a simulation (Experiment E9).
- NG3. No user accounts, logins or payments.
- NG4. No WebSockets. Data changes at most once a minute; polling every 60 s is sufficient **[DECISION]**.
- NG5. No database partitioning for scale until there is a measured performance problem.
- NG6. No deep learning models in v1/v2. Can be explored after v3 as an optional experiment.

### 2.3 Success criteria (measurable)

| ID | Criterion | Target | Measured by |
|---|---|---|---|
| S1 | MAE at +60 min vs persistence | ≥ 15% lower **(starting goal; reset after baselines are measured in M3)** | Backtest report |
| S2 | 80% interval coverage (P10–P90) at +60 min | 75–85% | Backtest report |
| S3 | Empty-event classifier PR-AUC at +60 min | Beats a "current bikes ≤ k" rule baseline | Backtest report |
| S4 | Leakage tests | 100% pass | `pytest -m leakage` |
| S5 | Collector uptime | ≥ 95% of scheduled polls stored, weekly | `collector_runs` table |
| S6 | API p95 latency for `/v1/stations/{id}/forecast` | < 300 ms | Load test (Section 19.5) |
| S7 | Frontend first load on mobile 4G | < 3 s to interactive map | Lighthouse |
| S8 | Reproducibility | `make all` on a clean clone reproduces the results table within ±1% | CI job |
| S9 | Test coverage (Python) | ≥ 80% lines in `dockcast/` | `pytest --cov` |

**Rule:** no number goes into the README, UI or CV unless it is produced by the pipeline and traceable to an MLflow run ID.

---

## 3. Users and use cases

| User | Primary question | Screens used |
|---|---|---|
| Rider (primary) | Will there be a bike (or dock) at my station when I get there? If not, where should I go? | Map, Station detail, Mobile view |
| Operations analyst (secondary) | Which stations will run empty/full in the next hour? Where does the model fail? | Map (risk view), At-risk list, Model page |
| Recruiter / interviewer (hidden) | Can this person build, evaluate and ship a real model? | README, Model page, Demo GIF |

### 3.1 Key use cases

- UC1. Rider opens the app → sees the globe → camera flies to Dublin → stations coloured by 60-min risk.
- UC2. Rider taps a station → sees bikes/docks now, forecast for +30/+60/+120 with ranges, and the two nearest backup stations.
- UC3. Analyst opens "At risk" → ranked stations by P(empty) or P(full) in next 60 min.
- UC4. Analyst presses **Autopilot** → camera tours the top 10 at-risk stations, 6 s each.
- UC5. Analyst toggles **Net flow** → stations pulse by net bikes in/out over the last 60 min.
- UC6. Anyone opens **Model performance** → baselines vs models, error by hour/station, ablation, calibration.

---

## 4. Research questions

| ID | Question | Answered by |
|---|---|---|
| RQ1 | How much does ML improve over persistence and seasonal naive at each horizon? | E1 |
| RQ2 | Does one global model beat per-station and per-cluster models, especially for low-data stations? | E2 |
| RQ3 | Do stations form meaningful, stable behaviour groups? | E3 |
| RQ4 | Do neighbouring-station features improve forecasts? | E4 |
| RQ5 | Can a dedicated classifier estimate P(empty/full) better than thresholding the count forecast? | E5 |
| RQ6 | Are the prediction intervals well calibrated, and does uncertainty grow with horizon? | E6 |
| RQ7 | Which feature groups matter (ablation)? | E7 |
| RQ8 | Does performance drift over time, and does frequent retraining help? | E8 |
| RQ9 | (Optional) Could forecasts reduce stockouts in a simple rebalancing simulation? | E9 |

---

## 5. Data sources

### 5.1 Source table

| ID | Source | Content | Frequency | Licence | Status |
|---|---|---|---|---|---|
| D1 | Dublin Bikes GBFS feed (Dublin City Council, via Smart Dublin) — listing: https://data.gov.ie/en_GB/dataset/dublinbikes-api | Live station information + status | Updated every minute | CC BY 4.0 | Listing verified. **Exact endpoint URLs [VERIFY]** — discover from the listing / `gbfs.json` |
| D2 | Dublin Bikes historical CSVs (same listing) | Monthly station snapshots, Oct 2021 onward | Monthly files | CC BY 4.0 | Verified. Some files empty. Two formats (see 5.3) |
| D3 | Met Éireann point forecast API — `http://metwdb-openaccess.ichec.ie/metno-wdb2ts/locationforecast?lat={lat};long={lon}` | Temperature, precipitation, wind, humidity, pressure, cloud | Hourly to 90 h | Met Éireann open licence (attribution required) | Listing verified. XML format |
| D4 | Historical hourly weather for Dublin (training) | Same variables, observed | Hourly | **[VERIFY]** | Candidates in order: (a) Met Éireann historical station data (e.g. Dublin Airport / Phoenix Park) **[VERIFY]**, (b) Open-Meteo historical API **[VERIFY licence]** |
| D5 | Irish public holidays | Calendar | Static | — | Python `holidays` package, country `IE` **[VERIFY coverage]** |
| D6 | School terms + university terms (TCD, UCD, DCU, TU Dublin) | Calendar | Static, yearly | Public | Hand-maintained CSV in `data/reference/terms.csv`, with source URL per row |

### 5.2 GBFS fields used (standard GBFS; confirm against the real feed)

`station_information`: `station_id`, `name`, `lat`, `lon`, `capacity`, `address` (optional)
`station_status`: `station_id`, `num_bikes_available`, `num_docks_available`, `is_installed`, `is_renting`, `is_returning`, `last_reported`

### 5.3 Historical file formats **[VERIFY exact columns in M1]**

- Format A — "DublinBike historical data YYYY-MM" (approx. Oct 2021 – mid 2024).
- Format B — "Dublin Bikes Historical Station Data MMYYYY" (mid 2024 onward), filename pattern `dublin-bikes_station_status_MMYYYY.csv`.
- Each format gets its own loader that maps to the canonical schema (Section 8, `station_status_raw`).
- Record per file: rows, date range, stations, median snapshot interval, % missing. Store in `data_quality_files` table and `reports/data_profile.md`.

### 5.4 Known data issues to handle

1. Empty monthly files (publisher disclaimer).
2. Format change mid-2024.
3. Unknown snapshot interval in history **[VERIFY]** — decides whether empty/full labels can come from history or only from our own collector.
4. Station IDs or names may change between formats → build `station_id_map` reconciled by name + coordinates (within 30 m).
5. Duplicate snapshots, out-of-order timestamps, `last_reported` older than poll time (stale stations).
6. Rebalancing trucks cause sudden jumps (not demand).
7. Stations closed (`is_renting = false`) must be excluded from training targets and flagged in the UI.
8. Timezone: store **UTC** everywhere; convert to `Europe/Dublin` only for calendar features and display. DST changes must not create duplicate or missing hours.

---

## 6. System architecture

### 6.1 Overview

```
 D1 GBFS live ─┐
 D2 hist CSV ──┼─► Ingestion (Python jobs) ─► PostgreSQL ─► Feature builder ─► Training + backtest (MLflow)
 D3/D4 weather ┘          │                       ▲                                   │
                          │                       │                                   ▼
                          └─ raw Parquet archive  │                         Model registry (MLflow)
                                                  │                                   │
                                        Forecast job (every 15 min) ◄─────────────────┘
                                                  │
                                         forecasts table
                                                  │
                                       FastAPI (read-only API)
                                                  │
                                 React + MapLibre + deck.gl frontend
```

### 6.2 Components

| Component | Responsibility | Tech |
|---|---|---|
| `collector` | Poll GBFS every 60 s, write raw rows, log run | Python, httpx |
| `backfill` | Download + parse historical CSVs into canonical rows | Python, pandas |
| `weather` | Fetch forecast hourly; load historical weather once | Python, httpx, lxml |
| `resampler` | Raw → 15-min grid per station (`station_status_15m`) | SQL + pandas |
| `features` | Build the feature matrix from DB, leakage-safe | pandas / polars |
| `train` | Train models, run backtests, log to MLflow | LightGBM, scikit-learn, Prophet |
| `forecast` | Every 15 min: load champion model, write `forecasts` + `risk` | Python |
| `api` | Serve stations, forecasts, risk, net flow, metrics | FastAPI, SQLAlchemy |
| `web` | Globe/map UI, station detail, model pages | React, TypeScript, Vite, MapLibre GL JS, deck.gl |

### 6.3 Tech stack **[DECISION]**

| Area | Choice | Notes |
|---|---|---|
| Language (backend/ML) | Python 3.12 | |
| Package manager | `uv` | `pyproject.toml` + `uv.lock` |
| Lint / format | `ruff` (lint + format) | line length 100 |
| Types | `mypy` (strict on `dockcast/`) | |
| Data | pandas 2.x (polars allowed for heavy transforms) | |
| DB | PostgreSQL 16 | Local via Docker; hosted via Supabase or Neon **[VERIFY free-tier limits]** |
| ORM / migrations | SQLAlchemy 2.x + Alembic | |
| ML | LightGBM, scikit-learn, Prophet, SHAP | |
| Tracking | MLflow (local file store, artefacts committed to releases, not git) | |
| API | FastAPI + Pydantic v2 + Uvicorn | |
| Frontend | React 18+, TypeScript, Vite | |
| Map | MapLibre GL JS (globe projection — **[VERIFY minimum version]**) + deck.gl layers | No Mapbox token needed |
| Basemap tiles | Free vector style (e.g. OpenFreeMap) **[VERIFY terms]** | Attribution required |
| Data fetching | TanStack Query | 60 s refetch for live, 15 min for forecasts |
| Charts | Recharts | |
| Styling | Tailwind CSS with design tokens (Section 16.2) | |
| Tests | pytest, hypothesis (property tests), Vitest, Playwright | |
| CI/CD | GitHub Actions | |
| Containers | Docker + docker-compose | |

---

## 7. Repository structure

```
dockcast/
├── CLAUDE.md                     # Working rules for Claude Code
├── PRD.md                        # This document
├── README.md                     # Public-facing; results generated, not hand-typed
├── LICENSE                       # MIT for code
├── Makefile                      # make setup | db-up | backfill | collect | train | backtest | serve | web | test | all
├── docker-compose.yml            # postgres, api, (optional) mlflow ui
├── .env.example                  # every env var documented (Section 18.3)
├── pyproject.toml / uv.lock
├── alembic.ini
├── migrations/                   # Alembic versions
├── config/
│   ├── settings.toml             # non-secret config: horizons, quantiles, radii, fold count
│   └── cities/dublin.toml        # GBFS URLs, bbox, timezone, centre lat/lon, zoom
├── data/                         # git-ignored except reference/
│   ├── raw/                      # downloaded CSVs, raw GBFS JSON (parquet archive)
│   ├── interim/
│   ├── processed/
│   └── reference/terms.csv       # school/university terms, with source URL column
├── dockcast/                     # Python package
│   ├── __init__.py
│   ├── config.py                 # loads settings.toml + env via pydantic-settings
│   ├── db/                       # engine, session, models.py (SQLAlchemy), queries.py
│   ├── ingest/
│   │   ├── gbfs.py               # fetch + parse live feed
│   │   ├── collector.py          # poll loop, idempotent writes, run logging
│   │   ├── historical/
│   │   │   ├── download.py
│   │   │   ├── loader_format_a.py
│   │   │   ├── loader_format_b.py
│   │   │   └── reconcile.py      # station_id_map
│   │   ├── weather_forecast.py   # Met Éireann XML
│   │   ├── weather_history.py
│   │   └── calendar.py           # holidays + terms
│   ├── quality/                  # validators, profile report
│   ├── transform/resample.py     # raw → 15-min grid
│   ├── features/
│   │   ├── temporal.py
│   │   ├── lags.py
│   │   ├── spatial.py
│   │   ├── weather.py
│   │   ├── station.py            # static + cluster labels
│   │   ├── build.py              # assembles matrix with cut-off time
│   │   └── registry.py           # feature-group names for ablation
│   ├── targets/
│   │   ├── regression.py
│   │   └── events.py             # empty/full labels
│   ├── models/
│   │   ├── base.py               # Forecaster interface
│   │   ├── baselines.py          # persistence, seasonal naive
│   │   ├── linear.py             # ridge
│   │   ├── prophet_model.py
│   │   ├── lgbm_quantile.py
│   │   ├── lgbm_event.py         # classifier + calibration
│   │   └── clustering.py
│   ├── evaluation/
│   │   ├── splits.py             # rolling-origin folds
│   │   ├── metrics.py
│   │   ├── backtest.py
│   │   ├── error_analysis.py
│   │   └── reports.py            # writes reports/*.md + figures
│   ├── experiments/              # e1_baselines.py ... e9_rebalancing.py
│   ├── serving/
│   │   ├── forecast_job.py
│   │   └── netflow.py
│   └── api/
│       ├── main.py
│       ├── routes/               # stations.py, forecasts.py, risk.py, netflow.py, model.py, health.py
│       ├── schemas.py
│       └── deps.py
├── notebooks/                    # exploration only; never imported by the package
├── reports/                      # generated markdown + figures (committed)
├── tests/
│   ├── unit/
│   ├── leakage/
│   ├── integration/              # uses Postgres testcontainer
│   ├── api/
│   └── fixtures/                 # tiny CSV/JSON samples, real-shaped
├── web/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── app/routes.tsx
│   │   ├── api/client.ts         # typed client generated from OpenAPI
│   │   ├── components/
│   │   │   ├── map/GlobeMap.tsx
│   │   │   ├── map/StationLayer.ts
│   │   │   ├── map/NetFlowLayer.ts
│   │   │   ├── map/Autopilot.ts
│   │   │   ├── HorizonToggle.tsx
│   │   │   ├── RiskList.tsx
│   │   │   ├── ForecastChart.tsx
│   │   │   └── ...
│   │   ├── pages/                # MapPage, StationPage, ModelPage, AboutPage
│   │   ├── styles/tokens.css
│   │   └── lib/
│   └── tests/                    # vitest + playwright
└── .github/workflows/
    ├── ci.yml
    ├── collector.yml             # fallback scheduled collector
    ├── forecast.yml              # every 15 min (if not run by worker)
    ├── retrain.yml               # weekly
    └── deploy.yml
```

---

## 8. Database schema

All timestamps `timestamptz` in UTC. All tables have `created_at timestamptz default now()`.

```sql
-- Multi-city ready from day one [DECISION]
CREATE TABLE cities (
  city_code      text PRIMARY KEY,            -- 'dublin'
  name           text NOT NULL,
  timezone       text NOT NULL,               -- 'Europe/Dublin'
  gbfs_root_url  text,
  centre_lat     double precision NOT NULL,
  centre_lon     double precision NOT NULL,
  default_zoom   real NOT NULL
);

CREATE TABLE stations (
  station_key    bigserial PRIMARY KEY,       -- internal stable key
  city_code      text NOT NULL REFERENCES cities,
  source_id      text NOT NULL,               -- GBFS station_id
  name           text NOT NULL,
  lat            double precision NOT NULL,
  lon            double precision NOT NULL,
  capacity       integer NOT NULL CHECK (capacity >= 0),
  first_seen     timestamptz NOT NULL,
  last_seen      timestamptz NOT NULL,
  is_active      boolean NOT NULL DEFAULT true,
  cluster_id     integer,                     -- from E3, nullable
  UNIQUE (city_code, source_id)
);

CREATE TABLE station_id_map (                 -- reconciles historical IDs
  city_code      text NOT NULL,
  legacy_id      text NOT NULL,
  station_key    bigint NOT NULL REFERENCES stations,
  method         text NOT NULL,               -- 'exact' | 'name+coords'
  PRIMARY KEY (city_code, legacy_id)
);

CREATE TABLE station_status_raw (
  station_key          bigint NOT NULL REFERENCES stations,
  observed_at          timestamptz NOT NULL,  -- poll time (collector) or snapshot time (historical)
  last_reported        timestamptz,
  bikes_available      integer NOT NULL CHECK (bikes_available >= 0),
  docks_available      integer NOT NULL CHECK (docks_available >= 0),
  is_renting           boolean,
  is_returning         boolean,
  source               text NOT NULL,         -- 'live' | 'hist_a' | 'hist_b'
  PRIMARY KEY (station_key, observed_at)
);
CREATE INDEX ON station_status_raw (observed_at);
-- Retention: keep live raw rows 30 days in Postgres; archive older to Parquet (Section 18.4)

CREATE TABLE station_status_15m (
  station_key      bigint NOT NULL REFERENCES stations,
  ts               timestamptz NOT NULL,      -- start of 15-min bucket
  bikes_last       real,                      -- last observation in bucket
  bikes_min        real,
  bikes_max        real,
  docks_last       real,
  docks_min        real,
  n_obs            integer NOT NULL,
  is_imputed       boolean NOT NULL DEFAULT false,
  is_closed        boolean NOT NULL DEFAULT false,
  PRIMARY KEY (station_key, ts)
);

CREATE TABLE weather_hourly (
  city_code        text NOT NULL REFERENCES cities,
  ts               timestamptz NOT NULL,
  kind             text NOT NULL,             -- 'observed' | 'forecast'
  issued_at        timestamptz,               -- forecast issue time (null for observed)
  temp_c           real,
  precip_mm        real,
  wind_speed_ms    real,
  humidity_pct     real,
  cloud_pct        real,
  PRIMARY KEY (city_code, ts, kind, issued_at)
);

CREATE TABLE calendar_days (
  city_code        text NOT NULL REFERENCES cities,
  date             date NOT NULL,             -- local date
  is_public_holiday boolean NOT NULL,
  holiday_name     text,
  is_school_term   boolean NOT NULL,
  is_uni_term      boolean NOT NULL,
  PRIMARY KEY (city_code, date)
);

CREATE TABLE model_versions (
  model_version    text PRIMARY KEY,          -- e.g. 'lgbm-q-2026-11-02-a1b2c3'
  mlflow_run_id    text NOT NULL,
  kind             text NOT NULL,             -- 'regression' | 'event_empty' | 'event_full'
  horizon_min      integer,
  trained_at       timestamptz NOT NULL,
  train_end        timestamptz NOT NULL,
  is_champion      boolean NOT NULL DEFAULT false,
  metrics          jsonb NOT NULL
);

CREATE TABLE forecasts (
  station_key      bigint NOT NULL REFERENCES stations,
  issued_at        timestamptz NOT NULL,
  horizon_min      integer NOT NULL CHECK (horizon_min IN (30, 60, 120)),
  target_ts        timestamptz NOT NULL,
  bikes_p10        real NOT NULL,
  bikes_p50        real NOT NULL,
  bikes_p90        real NOT NULL,
  model_version    text NOT NULL REFERENCES model_versions,
  PRIMARY KEY (station_key, issued_at, horizon_min)
);

CREATE TABLE risk_scores (
  station_key      bigint NOT NULL REFERENCES stations,
  issued_at        timestamptz NOT NULL,
  window_min       integer NOT NULL DEFAULT 60,
  p_empty          real NOT NULL CHECK (p_empty BETWEEN 0 AND 1),
  p_full           real NOT NULL CHECK (p_full BETWEEN 0 AND 1),
  model_version    text NOT NULL REFERENCES model_versions,
  PRIMARY KEY (station_key, issued_at, window_min)
);

CREATE TABLE backtest_results (               -- one row per model x fold x horizon x slice
  run_id           text NOT NULL,
  experiment       text NOT NULL,             -- 'E1'...'E9'
  model_name       text NOT NULL,
  fold             integer NOT NULL,
  horizon_min      integer NOT NULL,
  slice_kind       text NOT NULL,             -- 'overall' | 'hour' | 'station' | 'cluster' | 'dow'
  slice_value      text NOT NULL,
  n                integer NOT NULL,
  mae              real, rmse real, mase real,
  pinball_p10      real, pinball_p50 real, pinball_p90 real,
  coverage_80      real, interval_width real,
  pr_auc           real, brier real,
  PRIMARY KEY (run_id, model_name, fold, horizon_min, slice_kind, slice_value)
);

CREATE TABLE collector_runs (
  run_id           bigserial PRIMARY KEY,
  city_code        text NOT NULL,
  started_at       timestamptz NOT NULL,
  finished_at      timestamptz,
  status           text NOT NULL,             -- 'ok' | 'partial' | 'error'
  stations_seen    integer,
  rows_written     integer,
  error            text
);

CREATE TABLE data_quality_files (
  file_name        text PRIMARY KEY,
  format           text NOT NULL,
  rows             integer NOT NULL,
  min_ts           timestamptz, max_ts timestamptz,
  stations         integer,
  median_interval_s integer,
  pct_missing      real,
  is_empty         boolean NOT NULL,
  checked_at       timestamptz NOT NULL
);
```

**Storage budget check:** the 15-min table is ~96 rows per station per day. Raw 1-minute live rows are ~1,440 per station per day, so raw rows older than 30 days move to Parquet. Re-estimate after M1 when the real station count is known.

---

## 9. Data pipeline

### 9.1 Collector (live)

- Poll `station_status` every **60 s**; refresh `station_information` every **24 h** and on unknown `station_id`.
- Write with `INSERT ... ON CONFLICT DO NOTHING` (idempotent).
- `observed_at` = poll time truncated to the second; keep `last_reported` separately.
- Stale rule: if `observed_at - last_reported > 15 min`, mark row as stale (`is_renting` left as given, add to quality log).
- Retries: 3 attempts with exponential backoff (1 s, 4 s, 16 s); timeout 10 s; log to `collector_runs`.
- Also write each raw JSON response to `data/raw/gbfs/YYYY/MM/DD/HHMM.json.gz` (for audit and replay) — rotate to object storage per Section 18.4.
- Runs as an always-on worker (preferred) **or** the GitHub Actions fallback every 5 min (Section 18.2).

### 9.2 Historical backfill

1. `download.py` reads the dataset listing, downloads every monthly CSV to `data/raw/hist/` (skip if exists, verify size > 0).
2. Detect format by header; route to loader A or B; reject unknown headers loudly.
3. Map to canonical columns; parse timestamps → UTC.
4. Reconcile station IDs (`reconcile.py`): exact ID match, else name + coordinates within 30 m, else new station with a warning.
5. Profile every file → `data_quality_files` + `reports/data_profile.md`.
6. Bulk load with `COPY`.

### 9.3 Cleaning rules

| Rule | Action |
|---|---|
| `bikes + docks > capacity + 2` | Keep, flag `capacity_mismatch`; update capacity if persistent > 7 days |
| Negative counts | Drop row, log |
| Duplicate `(station, observed_at)` | Keep first |
| `is_renting = false` | Keep row; bucket marked `is_closed`; excluded from training targets |
| Jump of ≥ 8 bikes within 5 min **[tune in EDA]** | Flag as likely rebalancing (`rebalance_flag`); kept, analysed in E-error |
| Gaps | Forward-fill at most 2 buckets (30 min) in the 15-min table and mark `is_imputed`; never impute targets |

### 9.4 Resampling to 15-min grid

- Bucket by `date_trunc` to 15 min in UTC.
- `bikes_last` is the main series; `bikes_min/max` support event labels.
- One row per station per bucket for the station's active period, even if empty (then `n_obs = 0`).

### 9.5 Weather

- Forecast: fetch hourly for Dublin centre point; store each issue (`issued_at`) — needed to train on "forecast available at the time" in v2.
- History: one-off load from D4.
- Join to 15-min grid by the hour containing the bucket.

### 9.6 Calendar

- `calendar_days` from `holidays` (IE) + `data/reference/terms.csv`.
- Local date in `Europe/Dublin`.

### 9.7 Orchestration (Make targets)

```
make setup        # uv sync, pre-commit install, npm ci in web/
make db-up        # docker compose up -d postgres; alembic upgrade head
make backfill     # download + load historical CSVs + profile report
make weather      # load weather history; fetch current forecast
make collect      # run collector loop locally
make resample     # rebuild station_status_15m (incremental by default)
make features     # build feature parquet for training
make backtest E=E1 # run an experiment; writes MLflow + reports/
make train        # train champion models on all data
make forecast     # run one forecast cycle
make serve        # uvicorn api
make web          # vite dev server
make test         # all python + web unit tests
make all          # clean reproduction from raw data to reports
```

---

## 10. Feature engineering

### 10.1 The leakage rule **[DECISION — most important rule in the project]**

For a prediction issued at time `t` (start of a 15-min bucket), every feature may use **only data with timestamp `< t`** (observations in bucket `t - 15 min` and earlier, plus the observation that closes at `t`). Weather features use either:
- **v1:** observed weather at the target hour, explicitly labelled "oracle weather" in all reports (upper bound), **and**
- **v2:** the forecast issued before `t` (realistic). E7 reports the gap.

Every feature function receives `cutoff: datetime` and a test asserts no row after the cutoff is read (Section 19.2).

### 10.2 Temporal

`hour_local`, `minute_of_day` (sin/cos), `dow` (sin/cos), `is_weekend`, `is_public_holiday`, `is_school_term`, `is_uni_term`, `days_to_next_holiday`, `month` (sin/cos).

### 10.3 Lag and rolling (per station, from `bikes_last` ratio = bikes / capacity, plus raw count)

- Lags: 1, 2, 3, 4, 8 buckets (15 to 120 min).
- Seasonal lags: same bucket 1 day ago, 7 days ago.
- Rolling mean and std: 4 buckets (1 h), 12 buckets (3 h).
- Rate of change: `bikes(t) - bikes(t-1)`, `bikes(t) - bikes(t-4)`, and the change in that rate (acceleration).
- Count of zero-bike buckets in the last 24 h; same for zero-dock.

### 10.4 Station static

`capacity`, `lat`, `lon`, `cluster_id` (from E3, v2), station mean occupancy by hour over training data only (target encoding computed inside each fold).

### 10.5 Spatial (v2)

- Neighbour set: k = 5 nearest stations within 600 m (haversine) **[tune 400/600/800 m in E4]**.
- Features: neighbours' mean occupancy ratio at lag 1, mean change over last hour, count of neighbours with bikes = 0, total bikes within radius, distance-weighted mean.
- All neighbour values use lags only (same leakage rule).
- Behavioural neighbours (optional): top-5 stations by correlation of weekly profiles, computed on training folds only.

### 10.6 Net flow (for UI and analysis, not a model target in v1)

`net_flow_60 = bikes(t) - bikes(t - 60 min)` per station, with rebalancing-flagged jumps excluded. Displayed as inflow (positive) / outflow (negative). Documented limitation: it is the net change, not separate arrivals and departures.

### 10.7 Weather

`temp_c`, `precip_mm`, `is_raining` (precip > 0.2 mm), `wind_speed_ms`, `precip_next_hour` (forecast only).

### 10.8 Feature groups (for ablation, `features/registry.py`)

`lags`, `rolling`, `seasonal`, `calendar`, `weather`, `station_static`, `spatial`, `cluster`.

---

## 11. Targets and labels

### 11.1 Regression target

`y_h = bikes_last(t + h)` for `h ∈ {30, 60, 120}` min (2, 4, 8 buckets). Docks are derived: `docks = capacity - bikes`, clipped to `[0, capacity]`. Rows where the target bucket is closed or imputed are excluded.

### 11.2 Event labels (v2)

- `empty_60 = 1` if `min(bikes_min over buckets (t, t+60]) == 0`, else 0.
- `full_60 = 1` if `min(docks_min over buckets (t, t+60]) == 0`, else 0.
- Only built where the bucket coverage has `n_obs ≥ 1` per bucket in the window **and** the source interval is ≤ 5 min **[VERIFY historical interval in M1; if coarser, train event models on collector data only]**.
- Exclude rows where the station was already empty (or full) at `t` from the "becomes empty" variant; keep both variants and report which one the UI uses (**UI uses "will be empty at any point", including already empty**).

---

## 12. Models

### 12.1 Common interface (`models/base.py`)

```python
class Forecaster(Protocol):
    name: str

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "Forecaster": ...
    def predict(self, X: pd.DataFrame) -> pd.DataFrame:  # columns: p10, p50, p90
        ...
```

Point-only models return `p10 = p50 = p90` and are excluded from interval metrics.

### 12.2 Model list

| Name | Release | Type | Details |
|---|---|---|---|
| `persistence` | v1 | Baseline | `ŷ = bikes(t)` |
| `seasonal_naive_7d` | v1 | Baseline | `ŷ = bikes(t + h - 7 days)` |
| `ridge` | v1 | Linear | Same features, standardised, one-hot hour/dow |
| `lgbm_global` | v1 | Main | One model per horizon, quantile objective α ∈ {0.1, 0.5, 0.9}; station as categorical |
| `prophet_station` | v2 | Classical | Per station, daily + weekly seasonality, holidays; run on a stratified sample of ≥ 20 stations if full run > 2 h |
| `lgbm_per_station` | v2 | Comparison | One model per station (E2) |
| `lgbm_per_cluster` | v2 | Comparison | One model per E3 cluster |
| `lgbm_event_empty`, `lgbm_event_full` | v2 | Classifier | Binary, `is_unbalance` or class weights; isotonic calibration on the fold's last training week |
| `rule_event_baseline` | v2 | Baseline | `P(empty) = 1 if bikes(t) ≤ k` with k tuned on training folds |

### 12.3 LightGBM defaults (starting point; tune with Optuna in v2, inside training folds only)

`num_leaves=63, learning_rate=0.05, n_estimators=2000 with early stopping (100) on the last training week, min_data_in_leaf=100, feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, seed=42`.

### 12.4 Post-processing

- Clip predictions to `[0, capacity]`.
- Enforce quantile order: `p10 ≤ p50 ≤ p90` (sort per row).
- Display rounding to integers happens only in the UI.

### 12.5 Champion selection

The champion per horizon is the model with the lowest mean MAE across folds **and** coverage_80 within 70–90%. Ties within 1% go to the simpler model. Recorded in `model_versions.is_champion`.

---

## 13. Evaluation and backtesting

### 13.1 Rolling-origin protocol **[DECISION]**

- Folds: **8**. Each test window: **7 days**. Training: expanding window, all data before the test window.
- **Gap:** 120 min between the end of training and the start of test (max horizon) to stop label overlap.
- Test windows spread over the last 8 weeks of available data by default; E8 uses windows across seasons.
- Hyperparameter tuning only inside training data (inner validation = last week of training).
- Same folds for every model in an experiment (folds are saved to `reports/folds.json`).

### 13.2 Metrics

| Task | Metrics |
|---|---|
| Regression | MAE, RMSE, MASE (scaled by persistence MAE), bias (mean error) |
| Intervals | Coverage of P10–P90, mean interval width, pinball loss per quantile |
| Events | PR-AUC, ROC-AUC, Brier score, reliability curve (10 bins), precision/recall at thresholds 0.3/0.5/0.7, false alarms per day |

### 13.3 Slices (all metrics are reported per slice)

Overall · horizon · hour of day · weekday vs weekend · station · cluster · capacity band · rush hour (07–10, 16–19 local) · rebalance-flagged periods vs normal.

### 13.4 Error analysis (first-class, `evaluation/error_analysis.py`)

Must answer and write to `reports/error_analysis.md`:
1. Top 10 stations by MAE and their characteristics.
2. Error by hour heatmap (station × hour).
3. Bias: does the model under-predict sharp drops? (error vs recent rate of change)
4. Error growth from +30 to +120.
5. Share of large errors (> 5 bikes) explained by rebalancing flags.
6. Weekend vs weekday.

### 13.5 Reporting rules

- Every chart and table is produced by code into `reports/` and the `/v1/model/*` API.
- Every report header lists: MLflow run ID, git commit, data range, fold dates.
- Report bad results as clearly as good ones.

---

## 14. Experiments

Each experiment = one script in `dockcast/experiments/`, one MLflow experiment, one section in `reports/experiments.md`.

| ID | Release | Question | Setup | Output |
|---|---|---|---|---|
| E1 | v1 | ML vs baselines | persistence, seasonal naive, ridge, lgbm_global; all horizons | Results table + MASE |
| E2 | v2 | Global vs per-station vs per-cluster | Same features; compare overall and for low-data stations (bottom quartile by rows) | Table + chart |
| E3 | v2 | Station behaviour groups | Weekday & weekend 24-h occupancy profiles (normalised by capacity) → k-means (k = 3–8, silhouette + stability across folds) and hierarchical (Ward); map clusters | Cluster map, profiles, stability score |
| E4 | v2 | Spatial features | Model A (no spatial) vs B (+spatial), radii 400/600/800 m | Δ MAE by slice |
| E5 | v2 | Risk classifier vs rule | lgbm_event vs rule baseline vs "p10 of regression ≤ 0" | PR-AUC, Brier, reliability |
| E6 | v2 | Uncertainty quality | Coverage and width by horizon, hour, cluster | Calibration table |
| E7 | v2 | Ablation | Remove one feature group at a time; also oracle vs forecast weather | Δ MAE table |
| E8 | v3 | Drift + retraining | Fixed model vs weekly retrain vs rolling 12-week window across ≥ 6 months | MAE over time chart |
| E9 | v3+ (optional) | Rebalancing simulation | Simple greedy policy using forecasts vs no-action vs persistence-based policy; objective = stockout-minutes avoided − λ·moves | Simulation report, clearly labelled as simulation |

---

## 15. Backend API

Base path `/v1`. JSON only. Read-only. CORS limited to the frontend origin. OpenAPI docs at `/docs`. Typed TS client generated from OpenAPI (`openapi-typescript`).

### 15.1 Endpoints

| Method & path | Purpose | Cache |
|---|---|---|
| `GET /health` | `{status, db, last_collector_run, last_forecast_issued_at}` | none |
| `GET /v1/cities` | List cities with centre and zoom | 1 h |
| `GET /v1/cities/{city}/stations` | All stations with latest status + latest risk | 60 s |
| `GET /v1/stations/{station_key}` | Station detail + latest status | 60 s |
| `GET /v1/stations/{station_key}/forecast` | Forecasts for 30/60/120 with p10/p50/p90 | 15 min |
| `GET /v1/stations/{station_key}/history?hours=24` | 15-min series for chart | 5 min |
| `GET /v1/stations/{station_key}/alternatives?horizon=30` | 2 nearest stations with p50 bikes ≥ 3 | 5 min |
| `GET /v1/cities/{city}/risk?window=60&kind=empty\|full&limit=20` | Ranked at-risk list | 60 s |
| `GET /v1/cities/{city}/netflow?window=60` | Net flow per station | 60 s |
| `GET /v1/model/summary` | Champion versions, last retrain, headline metrics | 1 h |
| `GET /v1/model/backtest?experiment=E1` | Rows from `backtest_results` | 1 h |
| `GET /v1/model/error-analysis` | Pre-computed slices | 1 h |

### 15.2 Example response — `GET /v1/stations/{station_key}/forecast`

```json
{
  "station_key": 42,
  "name": "Smithfield North",
  "capacity": 30,
  "issued_at": "2026-11-03T14:00:00Z",
  "model_version": "lgbm-q-2026-11-02-a1b2c3",
  "now": {"bikes": 3, "docks": 27, "observed_at": "2026-11-03T14:09:00Z", "is_renting": true},
  "forecasts": [
    {"horizon_min": 30,  "target_ts": "2026-11-03T14:30:00Z", "bikes_p10": 0, "bikes_p50": 1.4, "bikes_p90": 4.1},
    {"horizon_min": 60,  "target_ts": "2026-11-03T15:00:00Z", "bikes_p10": 0, "bikes_p50": 0.9, "bikes_p90": 3.8},
    {"horizon_min": 120, "target_ts": "2026-11-03T16:00:00Z", "bikes_p10": 2, "bikes_p50": 6.2, "bikes_p90": 10.5}
  ],
  "risk": {"window_min": 60, "p_empty": 0.82, "p_full": 0.01},
  "data_freshness": {"status_age_s": 51, "forecast_age_s": 540, "stale": false}
}
```
(Values above are an illustrative shape only.)

### 15.3 Error format

`{"error": {"code": "station_not_found", "message": "..."}}` with correct HTTP status. 404 for unknown station, 503 if data is stale beyond 30 min (with `Retry-After`).

### 15.4 Rules

- Pagination with `limit`/`offset` where lists can exceed 200 rows.
- Response time budget: p95 < 300 ms; use indexed queries on `(station_key, issued_at desc)`.
- Rate limit: 60 requests/min per IP (slowapi) **[DECISION]**.
- No secrets or internal IDs beyond `station_key` exposed.

---

## 16. Frontend (UI/UX)

### 16.1 Routes

| Route | Page |
|---|---|
| `/` | Map page (globe → Dublin) with risk layer, horizon toggle, at-risk panel |
| `/station/:stationKey` | Station detail |
| `/model` | Model performance |
| `/about` | Method, data sources, attribution, limitations |

### 16.2 Design tokens (from the approved canvas)

```css
--ground: #F4F5F2;  --surface: #FFFFFF;  --ink: #15201B;  --muted: #5A6560;
--line: #DDE2DE;    --brand: #0F766E;    --brand-ink: #0F5F58; --brand-tint: #E3F1EE;
--risk-empty: #C2410C; --risk-empty-ink: #9A3412; --risk-empty-tint: #FDEEE3;
--risk-full:  #1D4ED8; --risk-full-ink:  #1E40AF; --risk-full-tint:  #E6EDFC;
--risk-ok:    #7C8B84;
font-family: 'IBM Plex Sans' (UI), 'IBM Plex Mono' (numbers);
radius: 8px (controls), 12px (cards); spacing scale 4/8/12/16/24/32.
```
Dark mode: provide equivalent tokens; map style switches to a dark basemap. Orange (empty) vs blue (full) is chosen for colour-blind safety; never use red/green.

### 16.3 Map page behaviour (the "command center")

1. **Load:** MapLibre with **globe projection**, camera at a zoomed-out world view, slow auto-rotation (≈ 3°/s) until the user interacts or 2.5 s pass.
2. **Fly-in:** `flyTo` Dublin centre (from `/v1/cities`), duration ~4 s, ease-in-out; switch to mercator below zoom ~6 if globe rendering costs too much on mobile **[VERIFY performance]**.
3. **Level of detail:**
   - Zoom < 9: one marker per city (Dublin only for now) with a station count badge.
   - Zoom ≥ 9: deck.gl `ScatterplotLayer` of stations; radius scales with capacity; fill colour = risk at the selected horizon; outline thicker for selected station.
   - Zoom ≥ 15: station name labels.
4. **Horizon toggle:** Now · +30 · +60 · +120. "Now" colours by current state (empty/full/OK); others by forecast risk.
5. **Click station:** side panel (desktop) or bottom sheet (mobile) with now/forecast/alternatives; "Open details" → `/station/:id`.
6. **At-risk panel:** top 20 by `p_empty` or `p_full` (tabs), each row shows name, current count, ETA to empty/full (first horizon where p50 ≤ 0.5), probability badge.
7. **Autopilot:** button toggles a loop over the top 10 at-risk stations: `flyTo` (zoom 16, pitch 45°, 2 s), hold 4 s with panel open, next. Any user input stops it. Respects `prefers-reduced-motion` (then jumps without animation).
8. **Net flow layer:** toggle; deck.gl layer with pulsing rings, outward (inflow, brand colour) or inward (outflow, muted), size by |net_flow_60|. Legend explains it is net change, not trips.
9. **City selector:** dropdown listing `/v1/cities`; selecting flies the globe to that city. Only Dublin at launch.
10. **Freshness banner:** if status age > 5 min show "Live data delayed (last update hh:mm)".
11. **Attribution:** basemap, Dublin City Council / Smart Dublin (CC BY 4.0), Met Éireann — always visible.

### 16.4 Station detail page

- Header: name, capacity, area, risk badge.
- Tiles: bikes now, docks now, bikes at +60 (p10–p90), bikes at +120 (p10–p90).
- Chart: last 6 h actual + next 2 h forecast with P10–P90 band, "now" marker, shaded empty zone.
- Backup stations (2), walking distance (haversine × 1.3 walking factor, labelled "approx.").
- "What drives this forecast": top 4 SHAP feature groups for this station's latest prediction, as plain-language chips.

### 16.5 Model performance page

- Results table (E1, later E2/E4/E7) from `/v1/model/backtest`; best per column highlighted.
- Backtest explainer diagram (folds).
- Error by hour × station heatmap; error vs horizon line.
- Calibration plot (events) and coverage table (intervals).
- Data health: collector uptime 7 d, training data span, stations modelled, last retrain.
- Every number shows its MLflow run ID on hover.

### 16.6 Mobile

- Map full screen with bottom sheet; bottom nav: Nearby · Map · Accuracy.
- "Nearby" uses browser geolocation **only after a tap** on "Use my location"; never stored or sent beyond the request.
- Touch targets ≥ 44 px.

### 16.7 Accessibility

WCAG 2.1 AA: text contrast ≥ 4.5:1, keyboard navigation for all controls, map has a list alternative (at-risk list + station search), `aria-live` for risk updates, reduced-motion support.

### 16.8 Performance

Initial JS ≤ 300 KB gzip excluding map library; lazy-load the model page charts; station layer re-renders only on data change.

---

## 17. Releases and milestones

Each milestone ends with: tests green, `reports/` updated, a short entry in `CHANGELOG.md`, and a commit tagged `m<number>`.

### v1 — "Credible forecaster"

| M | Name | Tasks | Acceptance criteria |
|---|---|---|---|
| M0 | Scaffold | Repo tree (Section 7), uv, ruff, mypy, pytest, pre-commit, docker-compose Postgres, Alembic baseline, CI running | `make setup && make test` passes on clean clone; CI green |
| M1 | Data foundation | Discover GBFS URLs; collector running; download + profile all historical files; loaders A/B; ID reconciliation; schema + migrations | `reports/data_profile.md` lists every file; collector writes rows for 24 h with ≥ 95% uptime; **VERIFY items in 5.x resolved and written in Section 23** |
| M2 | Clean + resample + EDA | Cleaning rules, 15-min table, calendar, weather history; EDA notebook → `reports/eda.md` (usage by hour/dow/weather, closures, rebalancing jumps) | Resample tests pass; EDA report generated from code |
| M3 | Baselines + backtest framework | Folds, metrics, persistence, seasonal naive, leakage test suite | E1 baselines table produced; leakage tests pass; S1 target reset based on real baseline numbers |
| M4 | LightGBM + ridge | Features 10.2–10.4, quantile models per horizon, MLflow logging, champion selection | E1 full table; coverage reported; error analysis v1 report |
| M5 | Minimal API + results page | `/health`, stations, forecast, model summary; forecast job every 15 min; a simple results page (can be static HTML generated from reports) | API tests pass; forecasts table fills every 15 min for 48 h |
| M6 | v1 release | README with real results, limitations, reproduction steps | `make all` reproduces table; tag `v1.0.0` |

### v2 — "Data science depth"

| M | Name | Acceptance criteria |
|---|---|---|
| M7 | Station clustering (E3) | Clusters stable across folds (report adjusted Rand index); cluster map + profiles |
| M8 | Spatial features (E4) | Δ MAE reported per slice; leakage tests extended to spatial |
| M9 | Global vs per-station vs cluster + Prophet (E2) | Comparison table incl. low-data stations |
| M10 | Event classifiers (E5) | Calibrated probabilities; reliability plot; beats or honestly fails vs rule baseline |
| M11 | Uncertainty study (E6) + ablation (E7) incl. forecast vs oracle weather | Reports generated |
| M12 | Full error analysis + v2 release | `reports/error_analysis.md` answers all 13.4 questions; tag `v2.0.0` |

### v3 — "Command center"

| M | Name | Acceptance criteria |
|---|---|---|
| M13 | Web scaffold | Vite + React + TS + Tailwind + tokens; typed API client; routes |
| M14 | Globe map | Globe → Dublin fly-in, LOD, risk colouring, horizon toggle, at-risk panel |
| M15 | Station detail + model pages | Charts from API, SHAP chips |
| M16 | Net flow + autopilot + mobile | Behaviour per 16.3 (7, 8), reduced-motion respected |
| M17 | Deploy | HTTPS frontend + API + DB; always-on collector; uptime monitor |
| M18 | Drift study (E8) + polish | E8 report; Lighthouse ≥ 90 performance/accessibility; demo GIF; tag `v3.0.0` |
| M19 (optional) | Rebalancing simulation (E9) | Simulation report clearly labelled |
| M20 (optional) | Second city via GBFS | Only after v3; config-only addition proves the multi-city design |

---

## 18. Infrastructure, deployment and cost

### 18.1 Environments

`local` (docker-compose) · `ci` (GitHub Actions + Postgres service) · `prod`.

### 18.2 Production layout (free or near-free) **[VERIFY each provider's current free tier before choosing]**

| Part | Option A (preferred) | Option B |
|---|---|---|
| Frontend | Cloudflare Pages or Vercel | Netlify |
| API | Fly.io / Render small instance | Railway |
| Database | Supabase or Neon Postgres | Postgres on the API VM |
| Collector + forecast job | Always-on small worker (same host as API) | GitHub Actions cron every 5 min (accept delays; labels then use 5-min data) |
| Raw archive | Cloudflare R2 / Backblaze B2 (Parquet) | GitHub Releases assets |
| Uptime | UptimeRobot (free) on `/health` | Better Stack |

### 18.3 Environment variables (`.env.example`)

```
DATABASE_URL=postgresql+psycopg://dockcast:dockcast@localhost:5432/dockcast
CITY=dublin
GBFS_ROOT_URL=                 # filled in M1 after discovery
MET_FORECAST_URL=http://metwdb-openaccess.ichec.ie/metno-wdb2ts/locationforecast
MLFLOW_TRACKING_URI=file:./mlruns
ARCHIVE_BUCKET_URL=            # optional
API_CORS_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
```
No secrets in git. `pydantic-settings` validates at startup and fails fast.

### 18.4 Data retention

Raw live rows in Postgres: 30 days → nightly job exports to Parquet (partitioned by date) → archive bucket → delete from Postgres. 15-min table: keep all.

### 18.5 CI/CD (GitHub Actions)

- `ci.yml` on PR/push: ruff, mypy, pytest (unit, leakage, integration with Postgres service, api), web lint + vitest + build, Playwright smoke against preview.
- `retrain.yml` weekly (Mon 03:00 UTC): retrain champions, run E1 on latest folds, register model only if MAE not worse than current champion by > 2% (otherwise keep current and open an issue).
- `deploy.yml` on tag `v*`.

---

## 19. Testing and quality

### 19.1 Unit

Loaders (fixtures for format A, B, empty file, unknown header), cleaning rules, resampler (DST change days: last Sunday of March and October), metrics against hand-computed values, quantile ordering, clipping.

### 19.2 Leakage tests (`pytest -m leakage`) **[DECISION: required in CI]**

- For random `(station, t)`, rebuild features with all data after `t` deleted → features must be identical.
- Targets must never appear in features (column-name and value-correlation checks).
- Fold gap respected: no target timestamp of training rows ≥ test start − 120 min.
- Target encodings and cluster labels computed only from training rows of the fold.

### 19.3 Property tests (hypothesis)

`bikes + docks ≤ capacity` after post-processing; `p10 ≤ p50 ≤ p90`; resampled bucket count equals expected grid length.

### 19.4 Integration

Testcontainers Postgres: migrations up/down, backfill of fixture month, one forecast cycle end to end.

### 19.5 API and load

Contract tests against OpenAPI schema; `locust` or `k6` script: 50 users, 5 min, p95 < 300 ms on forecast endpoint.

### 19.6 Frontend

Vitest for components and data mapping; Playwright: map loads, horizon toggle changes colours, station panel opens, autopilot starts/stops, reduced-motion path.

### 19.7 Code standards

Type hints everywhere; docstrings on public functions (Google style); no notebook code imported by the package; functions ≤ ~50 lines where practical; conventional commits (`feat:`, `fix:`, `data:`, `exp:`, `docs:`, `test:`, `chore:`).

---

## 20. Observability and data health

- Structured JSON logs (`structlog`) with `job`, `city`, `run_id`.
- `collector_runs` + `/health` expose freshness.
- Daily data-health report (`reports/health/YYYY-MM-DD.md`): uptime, missing buckets per station, stale stations, rebalancing events detected.
- Alert (GitHub issue via workflow) if collector uptime < 90% in 24 h or forecasts older than 45 min.

---

## 21. Security, licensing and ethics

- Code licence: MIT. Data: credit Dublin City Council / Smart Dublin (CC BY 4.0) and Met Éireann per their licence, in README, `/about` and map attribution.
- No personal data collected. Geolocation used only client-side on request.
- Dependency scanning: Dependabot + `pip-audit` + `npm audit` in CI.
- API is read-only; DB credentials for the API use a read-only role.
- Be respectful of source servers: one poll per minute, `User-Agent: DockCast/<version> (<contact email>)`, honour HTTP caching headers.
- Limitations stated clearly in README and `/about`: forecasts are estimates; no trip data; rebalancing not observed directly.

---

## 22. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Historical files too coarse for event labels | Medium | Event model delayed | Start collector in M1; train event models on collector data |
| GBFS endpoint changes / downtime | Low–Med | Gaps | Retries, raw archive, freshness banner, gap flags |
| Leakage inflates results | Medium | Credibility destroyed | Leakage test suite in CI; fold gap; oracle weather labelled |
| Free-tier limits (DB size, sleep) | Medium | Outage | Retention policy; always-on worker option; uptime monitor |
| Globe rendering slow on mobile | Medium | Poor UX | Switch to mercator below zoom threshold; reduced detail |
| Scope creep | High | Never ships | Releases v1→v3; optional items marked |
| Model barely beats persistence at +30 | High | "Weak" headline | Report honestly; emphasise +60/+120 and events; it is a finding |

---

## 23. Open questions and verification list

Resolve during M1 (unless noted); write the answer and source link next to each item.

- [ ] Exact GBFS root URL and whether a key/registration is needed (D1).
- [ ] Historical file column names, snapshot interval, and the exact cut-over month between formats A and B (D2).
- [ ] Do the feeds include any trip-level data? (Expected: no → confirms NG1.)
- [ ] Historical hourly weather source and licence (D4).
- [ ] `holidays` package coverage for IE (D5).
- [ ] MapLibre GL JS minimum version with globe projection (M13).
- [ ] Basemap tile provider terms and attribution (M13).
- [ ] Free-tier limits of chosen hosting providers (M17).
- [ ] Station count and real storage estimate (M1).

---

## 24. Glossary

| Term | Meaning |
|---|---|
| GBFS | General Bikeshare Feed Specification, the standard JSON format for bike-share data |
| Horizon | How far ahead a forecast looks (30/60/120 min) |
| Persistence | Baseline that predicts "same as now" |
| Seasonal naive | Baseline that predicts "same as this time last week" |
| Rolling-origin backtest | Repeated train-on-past, test-on-next-week evaluation that moves forward in time |
| Leakage | Using information in training/features that would not be available at prediction time |
| Quantile (P10/P50/P90) | Values the outcome is expected to fall below 10%/50%/90% of the time |
| Coverage | Share of actual values inside the P10–P90 interval (ideal ≈ 80%) |
| MASE | MAE divided by persistence MAE; < 1 means better than persistence |
| PR-AUC | Area under precision-recall curve; suited to rare events like stockouts |
| Brier score | Mean squared error of predicted probabilities |
| Net flow | Change in bikes at a station over a window; not the same as trips |
| Champion | The model currently used in production for a horizon |

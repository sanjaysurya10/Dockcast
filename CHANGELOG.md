# Changelog

## M17 — Deploy (2026-11-01)

Live since 2026-11-04: frontend https://dockcast.pages.dev, API
https://143-47-249-111.sslip.io (hosted DB migrated 0006 → 0007), UptimeRobot keyword monitor
on `/health`. Backtests published to the hosted DB: 61,584 rows from E1 `e4819616`,
E2 `470f7279`, E4 `a9729858`, E7 `abd37ee6`. Setup steps are in `deploy/oracle/README.md` §7b–7e.

- **API on the Oracle VM**: new `api` (Uvicorn) and `caddy` services in
  `docker-compose.worker.yml`. Caddy (2.11.6) terminates HTTPS with an automatic Let's Encrypt
  certificate for `API_HOST`, an `<ip>.sslip.io` name, so no domain is needed. It adds HSTS and
  nosniff headers. The API sees client IPs via `X-Forwarded-For` for the per-IP limit.
  `reports/error_analysis.json` now ships in the image (`REPORTS_DIR=/app/reports`).
  Checked locally through Caddy: `/health`, CORS and `/v1/model/error-analysis`.
- **Forecast retention**: the nightly archive also exports forecasts issued more than 14 days
  ago (`retention.forecasts_days`) to R2 as Parquet, then prunes them with the same
  row-count check. The hosted `forecasts` table was 33 MB and growing about 5 MB/day; the
  hosted DB is at 250 of 500 MB.
- **Backtest publishing**: `make publish-backtest` copies each experiment's default run (E1
  `e4819616`, E2 `470f7279`, E4 `a9729858`, E7 `abd37ee6`) to the database in
  `PUBLISH_DATABASE_URL`, replacing earlier copies of the same run.
- **Basemap fallback**: if the OpenFreeMap style does not load within 8 s, or tiles fail 10
  times, the map switches once to a plain background and shows "Basemap unavailable".
  Stations, risk colours and net flow still draw.
- **Frontend**: Cloudflare Pages settings documented (root `web`, `npm run build`, `dist`,
  `VITE_API_BASE`). Added `web/.nvmrc` (Node 24) and `web/public/_headers` (nosniff,
  referrer policy, geolocation for this site only, no framing).
- **Uptime**: UptimeRobot keyword monitor on `/health` for `"status":"ok"`, every 5 min.
- **Tests**: forecast archive/prune integration test, backtest publish test, and a Playwright
  test with the basemap returning 503.

## M16 — Net flow, autopilot and mobile (2026-11-01)

- **API**: `GET /v1/cities/{city}/netflow?window=60` (15–120, multiples of 15). It gives the net
  change in bikes per station over the window, from `station_status_15m`. Stations are
  excluded when the window holds a rebalance-flagged or closed bucket, or when an end is
  missing. It returns 503 when the data is stale. This is net change, not trips.
- **Net flow layer** (PRD 16.3 item 8): a "Net flow" toggle draws deck.gl rings under the
  stations. Inflow pulses outward in the brand colour, outflow pulses inward in muted ink, and
  size grows with |net|. The legend counts inflow, outflow, unchanged and excluded stations and
  says the rings are net change, not trips. With reduced motion the rings are still.
- **Autopilot** (PRD 16.3 item 7): tours up to 10 stations with empty or full risk. Each stop
  flies in (zoom 16, pitch 45°, 2 s) and holds 4 s with the station panel open, then the tour
  wraps. Any pointer, wheel, touch or key input stops it. With reduced motion it jumps and
  holds. Progress is announced through `aria-live`.
- **Mobile** (PRD 16.6):
  - the map fills the screen, and stations sit in a bottom sheet that peeks or opens;
  - bottom nav: Nearby · Map · Accuracy, with ≥ 44 px targets;
  - map legends sit behind a "Map key" toggle.
- **Nearby page** (`/nearby`): "Use my location" asks for geolocation only after the tap and
  lists the 5 nearest stations with approximate walk distance and their current state. The
  location never leaves the browser.
- **Tests**:
  - API net flow test, including rebalance exclusion;
  - Vitest for net flow, autopilot stops, the autopilot timer and input stop, and nearby sort;
  - Playwright: net flow toggle, autopilot start/stop, reduced-motion autopilot, Nearby with
    mocked geolocation, phone bottom nav and sheet.
  - The net flow fixture is the hosted 11:15–12:15 UTC window on 2026-11-01. Station 5 there is
    rebalance-excluded (its 4 → 21 jump).

## M15 — Station detail and model pages (2026-11-01)

- **API**:
  - `GET /v1/stations/{key}/history?hours=1..48`: 15-min states from `station_status_15m`.
  - `GET /v1/stations/{key}/alternatives?horizon=`: the 2 nearest stations with P50 ≥ 3,
    with walk distance approximated as haversine × 1.3.
  - `GET /v1/stations/{key}/drivers?horizon=`: TreeSHAP feature-group contributions to P50,
    largest first.
  - `GET /v1/model/backtest?experiment=&slice_kind=&run_id=`: `backtest_results` averaged over
    folds. By default it uses the run with the most folds, newest first.
  - `GET /v1/model/error-analysis`: serves `reports/error_analysis.json`, now also written by
    `make error-analysis` (runs e4819616 and 470f7279).
  - `/v1/model/summary` gains `data_health`: 7-day collector uptime, stations modelled and the
    training end date.
- **Forecast job**: writes P50 TreeSHAP drivers per feature group to `forecast_drivers`
  (migration 0007, latest issue only). `LgbmQuantile.contributions` sums exactly to the raw P50
  (tested). New setting `REPORTS_DIR`.
- **Station page** (PRD 16.4):
  - header with an interim +60 risk badge;
  - tiles for now, +60 and +120;
  - Recharts chart of the last 6 h actual plus the 2 h forecast fan (P10–P90), with a "now"
    marker, an empty zone and a data-table alternative;
  - 2 backup stations with approximate walk distance;
  - "What drives this forecast" chips: the top 4 groups, in plain language.
- **Model page** (PRD 16.5):
  - served-model metrics;
  - backtest results for E1/E2/E4/E7 with the best value per column highlighted;
  - fold diagram;
  - station × hour MAE heatmap, single hue;
  - MAE vs horizon;
  - +60 coverage by hour against the 0.70–0.90 band;
  - data-health tiles.
  - Every number shows its MLflow run, in a caption or on hover. Event calibration waits for
    M10.
- **Charts**: series colours `--series-1/2` pass the dataviz palette validator in light and
  dark mode; baselines are muted and dashed. The station and model pages are lazy-loaded.
  Initial JS is 115 KB gzip; Recharts is a separate 102 KB chunk.
- **Fixes found in the visual check**:
  - the forecast fan now starts at the count the model saw at issue time;
  - the risk badge reads "Not at risk";
  - overlapping chart labels were replaced by a legend;
  - fold labels no longer wrap;
  - the heatmap caption is correct in dark mode.
- **Tests**:
  - pytest: drivers (SHAP sums, grouping, every forecast row explained) and 4 API contract
    tests.
  - Vitest: 31 tests on real fixtures (station 5's history, E1 backtest rows,
    `error_analysis.json`). The driver values in the fixture are illustrative and labelled
    test-only.
  - Playwright: 16 tests.
- **Not live yet**: hosted drivers need the VM update (`deploy/oracle/README.md` §7a), and the
  hosted DB has no `backtest_results` or error-analysis JSON until M17 publishes them.

## M14 — Globe map (2026-11-01)

- API: `GET /v1/cities/{city}/risk?window=30|60|120&kind=empty|full&limit=1..200&offset=`.
  - Stations are ranked by interim empty/full levels from the latest forecast range (owner
    decision, PRD §23). Each row carries P10/P50/P90 at the window, both levels and the ETA
    (the first horizon where P50 is empty or full).
  - The endpoint returns 503 when forecasts are stale, 404 for an unknown city and 422 for a
    bad window.
- Web map page (PRD 16.3, items 1-6, 9-11):
  - MapLibre globe that spins at 3°/s for 2.5 s or until the user interacts, then flies to
    Dublin over 4 s. With `prefers-reduced-motion` it jumps instead.
  - Level of detail: a city marker with the station count below zoom 9, deck.gl circles sized
    by capacity from zoom 9, and station names from zoom 15.
  - Horizon toggle (Now · +30 · +60 · +120). "Now" colours by the current state; forecast
    horizons use the interim levels: likely = solid fill, "may" = tint with a coloured ring.
  - Legend with a count per state, so meaning is never carried by colour alone.
  - At-risk panel: top 20 empty or full, with ETA and a level badge, labelled "from the
    forecast range, not a probability".
  - Station panel with now and +30/+60/+120 (P50 and range), opened from the list or the map,
    with a link to the details page.
  - Also: station search (the keyboard alternative), a city selector, and the OpenFreeMap
    basemap in light and dark. The map falls back to the current state when forecasts are
    unavailable, and to the lists when WebGL is missing.
- Fixes found in the visual check:
  - MapLibre's CSS set the map container to zero height.
  - maplibre-gl 6 breaks deck.gl 9.4, so it is pinned to 5.24.0 (PRD §23).
  - Markers were announced as "Map marker".
- Tests:
  - pytest: risk levels, ETA and ranking (`tests/unit/test_risk.py`), plus 2 API contract
    tests.
  - Vitest: 26 tests, including the real 2026-11-01 12:15 forecasts, where +30 and +60 give
    different colours.
  - Playwright: 12 tests on desktop and Pixel 7, covering globe load, spin and fly-in, the
    horizon toggle changing colours, the station panel, and the reduced-motion path. 24/24
    pass with `--repeat-each 2`.
- Bundle: initial JS is 116.8 KB gzip. The map chunk (MapLibre + deck.gl, 462 KB gzip) is
  lazy-loaded and outside the PRD 16.8 budget.
- Not done, for M15/M16: alternatives in the station panel (needs the alternatives endpoint),
  autopilot, net flow, and the mobile bottom sheet and nav. PRD 16.3's "mercator below
  zoom 6 on mobile" `[VERIFY performance]` is untested on real phones.

## M13 — Web scaffold (2026-11-01)

- `web/`: Vite 8, React 19 and TypeScript 5.9 (strict, `noUncheckedIndexedAccess`), Tailwind 4
  with the PRD 16.2 tokens as theme colours, plus DockCast's own dark-mode tokens. Fonts are
  self-hosted IBM Plex Sans and Mono, and `prefers-reduced-motion` is respected globally.
- Typed API client: `dockcast/api/openapi_export.py` writes `web/openapi.json` and
  openapi-typescript generates `web/src/api/schema.d.ts` (`make web-api`). `apiGet` is a small
  typed fetch that raises the PRD 15.3 error shape. A unit test fails when `openapi.json`
  drifts from the app. TanStack Query hooks refetch live data every 60 s and forecasts every
  15 min.
- PRD 16.1 routes:
  - `/`: station list with search and current state. This is the map's accessible alternative;
    the globe itself is M14.
  - `/station/:stationKey`: now, plus +30/+60/+120 forecasts with P10-P90. It tells "no
    forecast yet" apart from an unknown station.
  - `/model`: champion backtest metrics, with the MLflow run on hover.
  - `/about`: method, limitations and sources.
  - A 404 page, a freshness banner (status > 5 min old) and data attribution that is always
    visible.
- Tests:
  - Vitest: client, status helpers including a DST case, and every route. 17 tests.
  - Playwright smoke on desktop and Pixel 7: 6 tests.
  - Fixtures are real hosted-DB rows from 2026-11-01.
  - CI has a new `web` job (lint, typecheck, vitest, build, Playwright), and `make test` now
    includes `web-test`.
- Initial JS 112.7 KB gzip, against a 300 KB budget (PRD 16.8).
- `[VERIFY]` resolved (PRD §23): MapLibre globe needs v5.0.0 or later; OpenFreeMap terms and
  attribution.
- `npm audit`: 13 moderate advisories, all in dev-only tooling (minimatch via typescript-eslint,
  @redocly via openapi-typescript); nothing ships to the browser bundle.

## M12 — Full error analysis and v2.0.0 (2026-11-01)

- `make error-analysis` now joins E2 run `470f72791f044cd39a6a9afd2a061cfd` onto E1 run
  `e4819616d7034b90abcb3adc882313da` (same rows; it fails if E2's `lgbm_global` differs from
  E1's) and adds `lgbm_per_cluster` and the in-fold E3 cluster. `reports/error_analysis.md`
  (v2, code at `6d7393c`) still answers the six PRD 13.4 questions, with per-cluster alongside,
  and adds:
  - §7, PRD 13.3 metrics by slice (horizon, local hour, weekday/weekend, rush hour,
    capacity band, cluster, rebalance), with MAE, RMSE, MASE, bias and P10-P90 coverage for
    `lgbm_global` and `lgbm_per_cluster`. Per-cluster has lower MAE in almost every slice but
    lower coverage; the worst coverage is 05-09 local (per-cluster 0.716 at 05:00), and
    rebalance-flagged targets have MAE 11.3 and coverage 0.29.
  - §8, the PRD 12.5 champion rule on fold means: `lgbm_global` at +30 and +120 (per-cluster
    is within 1 %), `lgbm_per_cluster` at +60 (MAE 1.445 vs 1.461, coverage 0.798).
- Owner decisions (PRD §23): serving stays on `lgbm_global` at every horizon. `v2.0.0` is tagged
  without M10, and E5 follows as v2.1.
- README: status v2, a v2 experiments summary with run IDs, and updated limitations.
- Tests: `tests/unit/test_error_analysis.py` (E2 join and mismatch checks, slice metrics,
  champion rule, slice order).

## M11 — Uncertainty study (E6) and feature-group ablation (E7) (2026-11-01)

- Owner decisions (2026-10-31, PRD §23): M10 is deferred until there are at least 12 weeks of
  collector data; E7 uses **oracle weather** only, at +60, on all 8 folds. The
  forecast-vs-oracle weather gap is deferred to collector data, with M10.
- E6 (`make backtest E=E6`), MLflow run `9f9688d815da4c4298891cfdd044219f` (code at `de916bc`):
  calibration of the `lgbm_global` P10-P90 interval from E1 run
  `e4819616d7034b90abcb3adc882313da`, with no retraining. Coverage is 0.825 / 0.814 / 0.797
  at +30 / +60 / +120, width 3.10 / 4.59 / 6.44 bikes; tails (strict, because targets are whole
  bikes) are y < P10 0.085 / 0.092 / 0.101 and y > P90 0.090 / 0.095 / 0.102. All 115 stations
  are inside 0.70-0.90 at every horizon. Coverage is below 0.80 around 05-09 local time and
  above it at night (01-04).
- E7 (`make backtest E=E7`), MLflow run `abd37ee684b04b2ab419e4775f4ec512` (code at `4653479`,
  about 12.5 h): `lgbm_full` (every v1 group plus spatial at 600 m, the in-fold E3 cluster
  one-hot and **oracle weather**) against one model per removed group. MAE at +60: `lgbm_full`
  1.454, persistence 1.722. ΔMAE when a group is removed (bikes, positive = the group helps):
  lags +0.109 (8/8 folds), calendar +0.065 (8/8), seasonal +0.007 (7/8), spatial +0.007 (8/8),
  weather (oracle) +0.000 (6/8), cluster -0.001 (2/8), rolling -0.003 (0/8), station_static
  -0.007 (0/8). Even observed weather adds nothing measurable at +60 in these May-June test
  weeks. Removing rolling or station_static slightly improves MAE in every fold.
- New code: `dockcast/experiments/e6.py`, `dockcast/experiments/e7.py`,
  `dockcast/features/weather.py` (oracle weather, ceil-hour join on Met Éireann `ts`).
- Outputs: `reports/experiments.md` (E6, E7), `reports/figures/e6_coverage_by_hour.png`,
  `reports/figures/e7_ablation.png`.
- Tests: `tests/unit/test_e6.py`, `tests/unit/test_e7.py`,
  `tests/leakage/test_weather_oracle.py`.

## M9 — Global vs per-station vs per-cluster, and Prophet, E2 (2026-10-31)

- Models:
  - `dockcast/models/partitioned.py`: one quantile LightGBM per station or per E3 cluster,
    with the same features, defaults and early stopping as `lgbm_global`.
  - `dockcast/models/prophet_model.py`: Prophet per station with daily and weekly seasonality
    and public holidays from `calendar_days`. It is fitted once per fold on hourly observed
    states before the training end, in local time, and P10-P90 is its 80% interval.
  - New dependency: `prophet` 1.5.0 (owner approved 2026-10-31).
- E2 (`make backtest E=E2`), MLflow run `470f72791f044cd39a6a9afd2a061cfd` (code at `fa52bc1`,
  report re-rendered at `80cd9df` with `--render`). `lgbm_global` comes from E1 run
  `e4819616d7034b90abcb3adc882313da`; scoring uses rows common to E1 and E2; all 115 stations
  were run, about 5.5 h in total. MAE in bikes:
  - `lgbm_per_cluster`: 0.987 / 1.445 / 2.028 at +30 / +60 / +120, against `lgbm_global`
    0.995 / 1.461 / 2.047. It beats global in 7/8, 8/8 and 8/8 folds, but its P10-P90
    coverage is lower (0.807 / 0.798 / 0.785 vs 0.825 / 0.814 / 0.797).
  - `lgbm_per_station`: 1.025 / 1.480 / 2.074, worse than global in every fold, with coverage
    0.75-0.76.
  - `prophet_station`: 5.44 at every horizon, because it does not use the current state.
    It is worse than persistence.
- Low-data stations, using the PRD's bottom quarter by training rows: per-cluster is again
  best (8/8 folds at every horizon). **Needs owner review:** within each fold, the stations
  either side of the quartile boundary differ by only 1-10 training rows, so the PRD
  definition hardly separates low-data stations in Format B.
- E2b (`make backtest E=E2b`, owner decision 2026-10-31: simulate low-data stations by
  truncating histories), MLflow run `01131c8fc80b40b0abad2742db60f700` (code at `c0143af`,
  about 8 h). A seeded 29 of 115 stations keep only their last 28 days of training
  (588-672 training rows each, against at least 8193 for the others); their earlier states
  are removed, so lags, the station x hour encoding and Prophet also see the short history.
  Every model, `lgbm_global` included, is retrained. MAE in bikes on the short-history
  stations at +30 / +60 / +120:
  - `lgbm_global`: 0.995 / 1.476 / 2.100, almost the same as on full-history stations
    (1.004 / 1.470 / 2.051), so pooling across stations covers short histories well;
  - `lgbm_per_cluster`: 0.987 / 1.471 / 2.096, better than global in 8/8, 6/8 and 4/8 folds:
    its edge on short histories is small and gone by +120;
  - `lgbm_per_station`: 1.634 / 2.108 / 2.821, worse than global in every fold and worse
    than persistence at +30 and +60;
  - `prophet_station`: about 6.09 at every horizon.
  - Caveat: clusters are E3's labels, fitted on the full pre-fold history.
- Outputs:
  - the E2 section of `reports/experiments.md`;
  - `reports/figures/e2_low_data.png`;
  - the E2b section of `reports/experiments.md` and `reports/figures/e2b_short_history.png`;
  - `data/processed/e2_predictions_<run>.parquet` and `e2b_predictions_<run>.parquet`.
- `score_all` in E4 now takes the extra slice columns as a parameter.
- Tests (unit):
  - each group's model learns only from its own rows; the cluster model pools its stations;
  - Prophet's daily cycle and intervals, including across the DST change on 29 March;
  - low-data ties; fold labels;
  - report section and chart.
- Tests (unit): E2b station picking is seeded and order-free; truncation keeps only the short
  window; E2b report section.
- Tests (leakage): Prophet is unchanged when states after the cutoff are deleted or
  poisoned; E2b short stations are unchanged when states before their history start are
  poisoned.

## M8 — Spatial features, E4 (2026-10-31)

- Neighbour features (`dockcast/features/spatial.py`, PRD 10.5): the 5 nearest stations within
  the radius (haversine). Features are their mean occupancy ratio, mean change over the last
  hour, count at 0 bikes, total bikes within the radius, and the inverse-distance-weighted mean
  ratio. All are read at or before the issue time, and buckets inside a gap stay missing.
  Columns carry the radius (`nb600_*`) and are passed through `feature_matrix` /
  `prepare_fold`.
- E4 (`make backtest E=E4`), MLflow run `a972985884564e83aa5b120428bd5c74`: A = E1
  `lgbm_global` (run `e4819616d7034b90abcb3adc882313da`), B = A + neighbours, scored on rows
  common to both. Radii were 600 m at +30 and +120, and 400 / 600 / 800 m at +60 (owner decision
  2026-10-30). B beats A at every horizon, but by very little:
  - ΔMAE −0.004 at +30, −0.005 to −0.006 at +60, −0.006 at +120 (bikes). This is about 0.4%,
    well inside the fold spread (± 0.05–0.08).
  - B wins 7–8 of 8 folds.
  - The radius makes no practical difference: at +60 all three radii are within 0.001 MAE.
  - Rush hour gains the most among regular slices (−0.008 to −0.011).
  - No weather.
- Slice table per horizon, including in-fold E3 clusters (run
  `9f7a9d468a8a422b82b98fb0d2a64ffa`), in the E4 section of `reports/experiments.md`.
- Tests: hand-computed neighbour values and radius / k limits (unit). Spatial features are
  unchanged when data after the issue time is deleted or poisoned, and are missing inside gaps
  (leakage). Joining A and scoring mixed radii per horizon (unit).

## M7 — Station clustering, E3 (2026-10-30)

- Profiles (`dockcast/features/station.py`): mean occupancy (bikes / capacity in force) per local
  hour, weekdays and weekends, 48 values per station, from observed, open, non-imputed,
  non-flat-lined 15-min states with `state_ts < cutoff`; Format A + B (PRD 9.1a). Stations with
  any cell under 20 states are left out (`[clustering]` in `config/settings.toml`).
- Clustering (`dockcast/models/clustering.py`): k-means (n_init 20, seed 0) and Ward; cluster ids
  ordered by mean occupancy; silhouette; ARI on shared stations.
- E3 (`make backtest E=E3`), MLflow run `9f7a9d468a8a422b82b98fb0d2a64ffa`: k = 4 chosen by
  silhouette (0.367, k = 3-8). Fold ARI 0.992 (min 0.984) across labels fitted before each E1
  fold. Period ARI (Format A only vs Format B only, 114 stations) 0.530 — groups only partly
  persist across the two periods (owner decision 2026-10-30: report both). K-means vs Ward ARI
  0.433. 116 stations clustered (48 / 28 / 16 / 24); STATION118 (live only) left out.
- Outputs: E3 section of `reports/experiments.md`, `reports/figures/e3_profiles.png`,
  `reports/figures/e3_cluster_map.png`, per-fold labels
  `data/processed/e3_fold_labels_<run>.parquet` for M8/M9, `stations.cluster_id` (local DB).
- Tests: profile filters, capacity in force, DST-day local hours (integration); profiles and
  labels unchanged when data from the cutoff changes (leakage); clustering helpers (unit).

## M6 — v1 release (2026-10-30)

- README rewritten: E1 results with run IDs, limitations, architecture, reproduction steps, data
  credits.
- `make all`: setup, db-up, backfill, gaps, capacity, calendar, weather, resample, eda,
  `backtest E=E1`, error-analysis, results.
- E1 rerun at `ed13e96` on the existing local database, MLflow run
  `e4819616d7034b90abcb3adc882313da`: every E1 table value and every error-analysis value matches
  run `fb0d738826974ae9982cc4e96b96e5ba`. The download and load steps (`backfill` to `eda`) were
  not rerun from a fresh clone.

## M5 — Serving v1 (2026-10-27)

- Production training (`make train`, `dockcast/serving/train.py`): `lgbm_global` quantiles on
  Format B to 2026-06-30 with the E1 fold procedure (last week for early stopping); bundle
  `lgbm-q-2026-06-30-3c421b6`, MLflow run `5c34442ebc3a4b46aca09893377ab030`, 115 stations. Backtest
  metrics in `model_versions` come from E1 run `fb0d738826974ae9982cc4e96b96e5ba`. 8 of 9 boosters
  stop at or near the 2000-round cap (as in E1).
- Forecast job (`make forecast`, `--loop`; Oracle VM `forecast` service): every 15 min + 60 s,
  incremental resample of live rows, P10/P50/P90 at +30/+60/+120, upsert into `forecasts`; skips
  when live data is older than 30 min. Stations are matched by feed `source_id`, so local and
  hosted station keys may differ. First cycles on Supabase: 342 rows per cycle (114 stations x 3);
  station 118 is not in the training set and has no forecast until the next retrain.
- API (`make serve`, local only; public deploy is M17): `/health`, `/v1/cities`,
  `/v1/cities/{city}/stations`, `/v1/stations/{key}`, `/v1/stations/{key}/forecast`,
  `/v1/model/summary`; PRD 15.3 error body, 503 + `Retry-After` when data is older than 30 min,
  per-IP limit 60/min. slowapi's middleware cannot see routes inside FastAPI 0.162 included
  routers, so the limit is applied by an app middleware using slowapi's limiter backend.
- Results page (`make results`): `reports/site/index.html`, built from the generated reports.
- `calendar_days` populated on Supabase (2021-09-01 to 2027-08-31).
- Dependencies: `fastapi`, `uvicorn`, `slowapi`; `serve` group (`lightgbm`) in the worker image,
  which now installs `libgomp1`.
- Not yet verified: forecasts table filled every 15 min for 48 h (acceptance; m5 tag after).

## M4 — LightGBM + ridge (2026-10-26)

- Features PRD 10.2-10.4 (`dockcast/features/matrix.py`, groups in `features/registry.py`): lags
  (bikes and ratio, 1/2/3/4/8 buckets), seasonal (T-1 d, T-7 d), rolling mean/std (1 h, 3 h),
  change/acceleration, zero bikes/docks in 24 h, calendar of the target time (local), capacity at
  the time, lat/lon, in-fold station x hour occupancy encoding. Leakage tests for every feature.
- Models: `ridge` (imputed, standardised, one-hot hour/dow) and `lgbm_global` (quantiles
  0.1/0.5/0.9, station categorical, PRD 12.3 defaults, early stopping on the last training week);
  post-processing clips to [0, capacity] and sorts quantiles. Champion selection (PRD 12.5).
- E1 full, MLflow run `fb0d738826974ae9982cc4e96b96e5ba` (8 folds, ~600 k common rows per
  horizon, **no weather**): lgbm_global MAE +30/+60/+120 = 0.995 / 1.461 / 2.047 (MASE 0.933 /
  0.849 / 0.740), coverage P10-P90 = 0.825 / 0.814 / 0.797; persistence 1.066 / 1.721 / 2.768;
  ridge 1.179 / 1.869 / 2.874 (worse than persistence at every horizon). Champion: lgbm_global at
  all horizons. **S1 met by 0.002 bikes** (1.461 vs 1.463; fold std 0.061) — borderline.
- Error analysis v1 (`reports/error_analysis.md`, `make error-analysis`): worst stations are
  Docklands/canal commuter stations; errors peak 07-09 and 16-18; LightGBM slightly over-follows
  sharp changes while persistence lags them; rebalancing-flagged targets are 0.7 % of rows but
  9.5 % of LightGBM errors > 5 bikes; at +30 on weekends LightGBM (0.750) is slightly worse than
  persistence (0.732).
- 51 of 72 LightGBM boosters hit the 2000-round cap (not converged at PRD 12.3 defaults) — for
  v2 tuning (Optuna, PRD 12.3).
- Fixes: fold boundaries on the 15-min grid; DB timestamps normalised to UTC; E1 records the
  commit at run start. Dependencies: `lightgbm`, `scikit-learn` (`ml` group).

## M3 — Baselines + backtest framework (2026-10-26)

- Targets (`dockcast/targets/regression.py`): state at t + h = last observation of the bucket
  ending at t + h; closed, imputed and flat-lined targets excluded (owner decision).
- Baselines behind the `Forecaster` protocol: `persistence`, `seasonal_naive_7d`; inputs built
  with a cut-off and gap masking (`dockcast/features/build.py`).
- Metrics: MAE, RMSE, MASE, bias, pinball, coverage, interval width (hand-checked tests).
- Backtest runner: 8 gap-free weekly folds (boundaries snapped to the 15-min grid; fold dates
  in `reports/folds.json`), common-row scoring, slices (hour, weekday, rush hour, capacity band,
  rebalance, station) → `backtest_results`, MLflow, `reports/experiments.md`. `make backtest E=E1`.
- Leakage suite (`pytest -m leakage`, 89 tests): features unchanged when data after t is deleted,
  poisoned future values never reach features, target never a feature, fold gap ≥ max horizon.
- E1 baselines, MLflow run `2692ee7f49494167ba225ccc3c9c5303` (git `0c5b9de`): persistence MAE
  +30/+60/+120 = 1.066 / 1.721 / 2.768 bikes; seasonal naive 7 d = 6.355 / 6.354 / 6.354.
  Fold 8 +60 persistence MAE re-derived independently in SQL (1.8197 vs 1.8198).
- S1 reset by owner: +60 MAE ≤ 1.463 bikes (≥ 15 % below persistence 1.721).
- MLflow 3.17 (`ml` group); file store kept per PRD 6.3 via `MLFLOW_ALLOW_FILE_STORE=true`
  (`dockcast/tracking.py`).

## M2 — Clean + resample + EDA (2026-10-25)

- Resampler (`make resample`, `dockcast/transform/resample.py`): raw → `station_status_15m` in
  SQL, per station; UTC `date_bin` buckets, ≤ 2-bucket forward fill marked `is_imputed`, never
  across a data gap; DST-day and grid-length property tests. Full rebuild: 20,226,467 buckets.
- Cleaning (PRD 9.3, thresholds in `config/settings.toml [cleaning]`, owner decisions from
  `reports/eda.md`): spike removal (nightly 03:15 local Format B glitch), `rebalance_flag`
  (≥ 8 bikes within 10 min), `flatline_flag` (unchanged ≥ 24 h while renting), and
  `capacity_mismatch` against capacity in force at the time (`station_capacity`, migration
  `0006`, 120 change points; mismatches fell from 114,354 rows vs today's capacity to 5 buckets).
- Calendar (`make calendar`): `holidays` IE + `data/reference/terms.csv` (42 sourced rows:
  post-primary terms 2021/22–2026/27 from DoE circulars 0005/2020, 0072/2022, 0018/2026; TCD
  semesters 2021/22–2026/27). Unsourced days are NULL (migration `0005`).
- Weather (`make weather`): Met Éireann Dublin Airport hourly observations (43,849 h) and the
  point-forecast collector (new host `openaccess.pf.api.met.ie`), running on the VM since
  2026-10-25 (hourly at :20, HARMONIE window, `issued_at` = model run end).
- EDA (`make eda`): `reports/eda.md` + `reports/figures/` generated by `dockcast/quality/eda.py`.
- Dependencies: `holidays`; `matplotlib` in a `report` group kept out of the VM image.
- Old local Postgres 16 volume deleted (owner approval) — C: drive was at 99 %.

## M1 — Data foundation (2026-10-15 → 2026-10-25, tag `m1`)

Acceptance: cloud collector (Oracle VM → Supabase) stored **1440/1440** scheduled polls in the
first full 24 h window (2026-10-22 22:27 → 2026-10-23 22:27 UTC), 0 error runs; 4205/4205 from
start to 2026-10-25 20:31 UTC (query on `collector_runs`, PRD S5 definition).
`reports/data_profile.md` lists all 55 in-scope files; PRD §23 M1 items resolved.


- Live GBFS discovered (JCDecaux, GBFS 2.3) and wired into `config/cities/dublin.toml`.
- Schema per PRD §8 (migration `0002`); `weather_hourly` uses a surrogate key plus a
  `NULLS NOT DISTINCT` unique constraint because Postgres primary keys cannot contain the null
  `issued_at` of observed rows.
- `collector_runs.feed_last_updated` (migration `0003`) — feed-level staleness, replacing the
  per-row `last_reported` rule (owner decision; see PRD §23).
- Collector (`make collect`): 60 s polls on the minute, 3 retries (1/4/16 s), idempotent inserts,
  gzip raw archive under `data/raw/gbfs/`, every run logged in `collector_runs`.
- Historical backfill (`make backfill`): download from data.gov.ie, header-based format
  detection (unknown headers rejected), loaders A (local time → UTC incl. DST) and B (UTC),
  cleaning (bad times, negatives, duplicates), station ID reconciliation, `COPY` bulk load,
  `data_quality_files` + `reports/data_profile.md`.
- `make health`: collector uptime over the last 24 h (PRD S5).
- PRD §23: D1, D2, trip data, D4 and D5 resolved with sources.
- Owner decisions on M1 findings recorded (PRD 9.1a, 9.2, 9.8, 10.3, 13.1, 14, 17, 23):
  Format B + collector for main models, Format A only for E3/E8; M10 needs ≥ 12 weeks of
  collector data.
- Data gaps: `data_gaps` table (migration `0004`), `make gaps`, `reports/data_gaps.md`
  (38 gaps from the real data).
- Gap-aware lag/rolling helpers (`dockcast/features/lags.py`) with unit + leakage tests; gap-free
  rolling-origin folds ending at the last complete month of Format B
  (`dockcast/evaluation/splits.py`).
- Monthly backfill: `make backfill-new` loads only newly published months, merges into
  `reports/data_profile.json`/`.md` and refreshes gaps.
- Collector container: `Dockerfile`, compose service `collector` (`restart: unless-stopped`),
  `make collector-up/-down/-logs`. The first local 24 h run stopped after ~8 h when the
  terminal process was killed (2026-10-15 23:24 UTC); the 24 h check restarted 2026-10-20 18:41 UTC.
- Cloud collector building blocks (PRD 18.2, not deployed): `collector --once --if-stale-min`,
  fallback workflow `collector.yml` (every 5 min, no-op without `DATABASE_URL` secret),
  `dockcast.ingest.archive` export/prune (7-day retention, prune verifies Parquet row counts),
  `deploy/oracle/` (worker compose, nightly archive script + systemd timer, setup guide).
- PostgreSQL 17 everywhere (owner decision): compose `postgres:17` on new volume `pgdata17`,
  integration tests default to 17 (`DOCKCAST_TEST_PG_IMAGE` overrides); local DB moved by
  dump/restore with identical row counts.
- Supabase project `oyfrejzjkhjaohtknbvh` (eu-west-1, Postgres 17.11): schema applied from
  `alembic upgrade head --sql` (revision `0004`), Data API off, RLS on all 15 tables.
- Cloud collector deployed (2026-10-22): Oracle Cloud A1 VM (UK South) running the collector
  container → Supabase; nightly R2 archive timer (02:17 UTC); GitHub fallback verified with the
  `DATABASE_URL` secret (run 39870075582: polled only if the VM is stale; it skipped). rclone on
  the VM is the official v1.75.2 build (Ubuntu's v1.60 hit `501 NotImplemented` on R2).
- CI: removed the placeholder web job (job-level `hashFiles()` made the workflow invalid);
  it returns in M13.

## M0 — Scaffold (2026-10-15)

- Repo tree per PRD §7; `uv` project pinned to Python 3.12.
- `ruff` (line length 100) and `mypy --strict` on `dockcast/`; pre-commit hooks run both.
- Config: `config/settings.toml`, `config/cities/dublin.toml`, env via `pydantic-settings`.
- docker-compose Postgres 16; Alembic baseline revision `0001` (empty — schema lands in M1).
- pytest with `unit`/`leakage`/`integration`/`api` markers; integration test runs migrations
  up/down against a Postgres testcontainer.
- GitHub Actions `ci.yml` (Python job; web job is added in M13).

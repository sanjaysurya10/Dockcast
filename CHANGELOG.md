# Changelog

## M1 — Data foundation (in progress, 2026-10-15)

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

## M0 — Scaffold (2026-10-15)

- Repo tree per PRD §7; `uv` project pinned to Python 3.12.
- `ruff` (line length 100) and `mypy --strict` on `dockcast/`; pre-commit hooks run both.
- Config: `config/settings.toml`, `config/cities/dublin.toml`, env via `pydantic-settings`.
- docker-compose Postgres 16; Alembic baseline revision `0001` (empty — schema lands in M1).
- pytest with `unit`/`leakage`/`integration`/`api` markers; integration test runs migrations
  up/down against a Postgres testcontainer.
- GitHub Actions `ci.yml` (Python job; web job activates once `web/` exists in M13).

# Changelog

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

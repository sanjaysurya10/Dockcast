# Changelog

## M0 — Scaffold (2026-10-15)

- Repo tree per PRD §7; `uv` project pinned to Python 3.12.
- `ruff` (line length 100) and `mypy --strict` on `dockcast/`; pre-commit hooks run both.
- Config: `config/settings.toml`, `config/cities/dublin.toml`, env via `pydantic-settings`.
- docker-compose Postgres 16; Alembic baseline revision `0001` (empty — schema lands in M1).
- pytest with `unit`/`leakage`/`integration`/`api` markers; integration test runs migrations
  up/down against a Postgres testcontainer.
- GitHub Actions `ci.yml` (Python job; web job activates once `web/` exists in M13).

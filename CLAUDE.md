# CLAUDE.md — Working rules for DockCast

You are building **DockCast**, a station-level bike availability forecasting system for Dublin Bikes.
`PRD.md` is the single source of truth. Read the relevant PRD sections before starting any task.

## 1. How to work

1. **One milestone at a time**, in the order of PRD Section 17. Do not start a milestone until the previous one meets its acceptance criteria.
2. At the start of each milestone: restate its tasks and acceptance criteria in a short plan, then build.
3. At the end of each milestone: run `make test`, update `reports/` and `CHANGELOG.md`, commit with a conventional message, tag `m<number>`.
4. Small, reviewable commits. Prefixes: `feat:`, `fix:`, `data:`, `exp:`, `docs:`, `test:`, `chore:`, `refactor:`.
5. If something in the PRD is unclear or contradicts reality, **stop and ask** instead of guessing. Items marked `[DECISION]` must not change without the owner's approval.

## 2. Truth and data rules (non-negotiable)

- **Never invent data, numbers or results.** Every metric in README, UI, reports or commit messages must come from code output and include its MLflow run ID.
- **Verify before depending.** Anything marked `[VERIFY]` in the PRD must be checked against the real data or official docs first; record the answer and source link in PRD Section 23.
- **Inspect real files before writing a loader.** Print headers, dtypes, row counts and sample rows; write a fixture from real-shaped data.
- **No fake visuals.** No arcs or flow lines between stations or cities unless computed from real trip data (PRD NG1). Use net flow.
- Sample/placeholder values in UI must be visibly labelled as such.

## 3. Leakage rules (most important for the ML work)

- Every feature function takes a `cutoff` and may only read data with timestamps `< cutoff` (PRD 10.1).
- Target encodings, scalers, cluster labels and tuning happen **inside each training fold** only.
- Fold gap of 120 min between training end and test start.
- "Oracle weather" (observed weather at target time) must be labelled as such in every report.
- Any new feature needs a leakage test in `tests/leakage/` before it is used in an experiment.

## 4. Code standards

- Python 3.12, `uv` for dependencies. Ask before adding a new dependency; prefer the PRD stack.
- `ruff` (lint + format, line length 100) and `mypy --strict` on `dockcast/` must pass.
- Type hints and Google-style docstrings on public functions. Keep functions small and single-purpose.
- No logic in notebooks that the package depends on. Notebooks are for exploration only.
- Config in `config/*.toml` + env vars via `pydantic-settings`. No hard-coded URLs, paths or secrets.
- All timestamps UTC in storage; `Europe/Dublin` only for calendar features and display.
- SQL changes only through Alembic migrations.
- Frontend: TypeScript strict, design tokens from PRD 16.2, accessible markup (real buttons/links, labels, contrast), respect `prefers-reduced-motion`.

## 5. Testing

- Write or update tests with every change. Required suites: unit, leakage, integration (Postgres testcontainer), api; web: vitest + Playwright smoke.
- Test DST days (last Sunday of March and October) for anything time-based.
- Do not mark a task complete if tests fail; say what is failing and why.

## 6. Commands

```
make setup | db-up | backfill | weather | collect | resample | features
make backtest E=E1 | train | forecast | serve | web | test | all
```

## 7. Being a good citizen of the data sources

- Poll the live feed at most once per minute, with a descriptive `User-Agent`.
- Credit Dublin City Council / Smart Dublin (CC BY 4.0) and Met Éireann wherever data is shown.

## 8. When you finish a task

Report briefly: what changed, test results, any `[VERIFY]` item resolved (with source), and anything blocked or needing the owner's decision.

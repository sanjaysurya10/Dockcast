"""Copy backtest rows from the research database to the hosted one (M17).

The model page reads ``backtest_results`` through ``GET /v1/model/backtest``. Training and
backtests run locally, so the rows of each experiment's default run (most folds, newest; the
run the API picks) are copied to the hosted database. Rows are replaced per run, so re-running
is safe.

The target URL is read from ``PUBLISH_DATABASE_URL`` so the hosted password stays in the
owner's environment and never on the command line.
"""

import argparse
import os
from collections.abc import Sequence

import structlog
from sqlalchemy import Engine, delete, insert, select

from dockcast.api.queries import default_run
from dockcast.db.engine import make_engine
from dockcast.db.models import BacktestResult

log = structlog.get_logger(job="publish_backtest")

PUBLISHED_EXPERIMENTS = ("E1", "E2", "E4", "E7")
TARGET_ENV = "PUBLISH_DATABASE_URL"
CHUNK_ROWS = 5000


def runs_to_publish(source: Engine, experiments: Sequence[str]) -> dict[str, str]:
    """Each experiment's default run in the source database.

    Args:
        source: Research database.
        experiments: Experiment names.

    Returns:
        ``{experiment: run_id}`` for experiments that have rows.
    """
    with source.connect() as conn:
        runs = {experiment: default_run(conn, experiment) for experiment in experiments}
    return {experiment: run for experiment, run in runs.items() if run is not None}


def publish_run(source: Engine, target: Engine, run_id: str) -> int:
    """Replace one run's rows in the target with the source rows.

    Args:
        source: Research database.
        target: Hosted database.
        run_id: MLflow run ID.

    Returns:
        Rows written.
    """
    table = BacktestResult.__table__
    columns = [column for column in table.columns if column.name != "created_at"]
    with source.connect() as conn:
        rows = [dict(row) for row in conn.execute(
            select(*columns).where(table.c.run_id == run_id)
        ).mappings()]  # fmt: skip
    with target.begin() as conn:
        conn.execute(delete(BacktestResult).where(BacktestResult.run_id == run_id))
        for start in range(0, len(rows), CHUNK_ROWS):
            conn.execute(insert(BacktestResult), rows[start : start + CHUNK_ROWS])
    log.info("published", run_id=run_id, rows=len(rows))
    return len(rows)


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m dockcast.evaluation.publish``: copy default backtest runs to the hosted DB."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--experiments", nargs="+", default=list(PUBLISHED_EXPERIMENTS))
    parser.add_argument("--dry-run", action="store_true", help="list the runs, write nothing")
    args = parser.parse_args(argv)
    source = make_engine()
    runs = runs_to_publish(source, args.experiments)
    for experiment, run_id in runs.items():
        log.info("run", experiment=experiment, run_id=run_id)
    if args.dry_run:
        return
    target_url = os.environ.get(TARGET_ENV)
    if not target_url:
        parser.error(f"set {TARGET_ENV} to the hosted database URL")
    target = make_engine(target_url)
    total = sum(publish_run(source, target, run_id) for run_id in runs.values())
    log.info("done", runs=len(runs), rows=total)


if __name__ == "__main__":
    main()

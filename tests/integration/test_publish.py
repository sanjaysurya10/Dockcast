import pytest
from sqlalchemy import Engine, text

from dockcast.evaluation.publish import publish_run, runs_to_publish

pytestmark = pytest.mark.integration


def _seed(engine: Engine) -> None:
    with engine.begin() as conn:
        for run, folds in (("small", 1), ("full", 2)):
            for fold in range(1, folds + 1):
                conn.execute(
                    text(
                        "INSERT INTO backtest_results (run_id, experiment, model_name, fold, "
                        "horizon_min, slice_kind, slice_value, n, mae) "
                        "VALUES (:run, 'E1', 'lgbm_global', :fold, 60, 'overall', 'all', 10, 1.5)"
                    ),
                    {"run": run, "fold": fold},
                )


def _rows(engine: Engine, run: str) -> int:
    with engine.connect() as conn:
        sql = text("SELECT count(*) FROM backtest_results WHERE run_id = :run")
        return int(conn.execute(sql, {"run": run}).scalar_one())


def test_default_run_is_published_and_republishing_replaces_it(db_engine: Engine) -> None:
    _seed(db_engine)
    assert runs_to_publish(db_engine, ["E1", "E9"]) == {"E1": "full"}
    # Same database as source and target: the run is deleted and rewritten, not duplicated.
    assert publish_run(db_engine, db_engine, "full") == 2
    assert publish_run(db_engine, db_engine, "full") == 2
    assert _rows(db_engine, "full") == 2 and _rows(db_engine, "small") == 1

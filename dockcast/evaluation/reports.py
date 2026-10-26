"""Experiment outputs: ``reports/folds.json``, ``reports/experiments.md``, ``backtest_results``."""

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, delete
from sqlalchemy.dialects.postgresql import insert

from dockcast.config import PROJECT_ROOT
from dockcast.db.models import BacktestResult
from dockcast.evaluation.splits import Fold

REPORTS = PROJECT_ROOT / "reports"


def git_commit() -> str:
    """Short HEAD hash, ``-dirty`` when tracked files have uncommitted changes."""
    try:
        cmd = ["git", "rev-parse", "--short", "HEAD"]
        head = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT).stdout.strip()
        status = ["git", "status", "--porcelain", "--untracked-files=no"]
        dirty = subprocess.run(status, capture_output=True, text=True, cwd=PROJECT_ROOT).stdout
    except OSError:
        return "unknown"
    return f"{head}-dirty" if head and dirty.strip() else head or "unknown"


def folds_json(folds: Sequence[Fold]) -> str:
    """Folds as JSON (ISO timestamps).

    Args:
        folds: Folds.

    Returns:
        JSON text.
    """
    rows = [
        {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(f).items()}
        for f in folds
    ]
    return json.dumps(rows, indent=1)


def write_folds(folds: Sequence[Fold], path: Path = REPORTS / "folds.json") -> Path:
    """Save the fold definition (PRD 13.1: same folds for every model).

    Args:
        folds: Folds.
        path: Destination.

    Returns:
        The written path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(folds_json(folds), encoding="utf-8")
    return path


def store_results(engine: Engine, run_id: str, experiment: str, results: pd.DataFrame) -> int:
    """Write ``backtest_results`` rows for one run (replacing an earlier write of that run).

    Args:
        engine: Database engine.
        run_id: MLflow run id.
        experiment: Experiment id, e.g. ``E1``.
        results: Rows from :func:`dockcast.evaluation.backtest.score_slices`.

    Returns:
        Rows written.
    """
    columns = [
        "model_name",
        "fold",
        "horizon_min",
        "slice_kind",
        "slice_value",
        "n",
        "mae",
        "rmse",
        "mase",
    ]
    records: list[dict[str, object]] = [
        {"run_id": run_id, "experiment": experiment, **{str(k): v for k, v in row.items()}}
        for row in results[columns].to_dict("records")
    ]
    with engine.begin() as conn:
        conn.execute(delete(BacktestResult).where(BacktestResult.run_id == run_id))
        for start in range(0, len(records), 5000):
            conn.execute(insert(BacktestResult), records[start : start + 5000])
    return len(records)


def replace_section(path: Path, experiment: str, body: str) -> None:
    """Insert or replace the ``## <experiment>`` section of ``reports/experiments.md``.

    Args:
        path: Markdown file.
        experiment: Section id (e.g. ``E1``).
        body: Section text starting with its ``## E1 ...`` heading.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else "# Experiments\n"
    pattern = re.compile(rf"^## {re.escape(experiment)}\b.*?(?=^## |\Z)", re.S | re.M)
    if pattern.search(text):
        text = pattern.sub(body.rstrip() + "\n\n", text)
    else:
        text = text.rstrip() + "\n\n" + body.rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def generated_line(run_id: str, data_start: datetime, data_end: datetime) -> str:
    """Header line required on every report (PRD 13.5).

    Args:
        run_id: MLflow run id.
        data_start: First data used.
        data_end: Last data used.

    Returns:
        Markdown line.
    """
    return (
        f"MLflow run `{run_id}` · git `{git_commit()}` · generated "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC · data {data_start:%Y-%m-%d %H:%M} → "
        f"{data_end:%Y-%m-%d %H:%M} UTC"
    )

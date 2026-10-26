"""MLflow setup shared by experiments.

PRD 6.3 [DECISION] uses MLflow's local file store (``file:./mlruns``). MLflow 3.x refuses that
backend unless ``MLFLOW_ALLOW_FILE_STORE=true`` (it is in maintenance mode; MLflow recommends
SQLite). We set the documented opt-out for ``file:`` URIs only; moving to ``sqlite:`` is an owner
decision (lossless via ``mlflow migrate-filestore``).
"""

import os

import mlflow

from dockcast.config import get_env_settings


def setup_mlflow(experiment: str) -> str:
    """Point MLflow at the configured tracking URI and select the experiment.

    Args:
        experiment: Experiment name, e.g. ``E1``.

    Returns:
        The tracking URI in use.
    """
    uri = get_env_settings().mlflow_tracking_uri
    if uri.startswith("file:"):
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(experiment)
    return uri

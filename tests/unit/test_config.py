from pathlib import Path

import pytest

from dockcast.config import (
    EnvSettings,
    get_env_settings,
    load_city_config,
    load_project_config,
)

pytestmark = pytest.mark.unit


def test_project_config_matches_prd_decisions() -> None:
    config = load_project_config()
    assert config.forecast.horizons_min == [30, 60, 120]
    assert config.forecast.quantiles == [0.1, 0.5, 0.9]
    assert config.backtest.n_folds == 8
    assert config.backtest.gap_min == 120
    assert config.collector.poll_interval_s >= 60


def test_dublin_city_config_loads() -> None:
    city = load_city_config("dublin")
    assert city.city_code == "dublin"
    assert city.timezone == "Europe/Dublin"


def test_env_overrides_gbfs_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GBFS_ROOT_URL", "https://example.test/gbfs.json")
    get_env_settings.cache_clear()
    try:
        assert load_city_config("dublin").gbfs_root_url == "https://example.test/gbfs.json"
    finally:
        get_env_settings.cache_clear()


def test_cors_origins_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_CORS_ORIGINS", "http://a.test, http://b.test,")
    assert EnvSettings().cors_origins == ["http://a.test", "http://b.test"]


def test_missing_city_file_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_city_config("nowhere", config_dir=tmp_path)

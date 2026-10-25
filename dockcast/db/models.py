"""ORM models mirroring PRD Section 8. All timestamps are timezone-aware UTC."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dockcast.db.engine import Base

TZ = DateTime(timezone=True)


class CreatedAtMixin:
    """Adds ``created_at timestamptz default now()``."""

    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)


class City(CreatedAtMixin, Base):
    """A city served by DockCast."""

    __tablename__ = "cities"

    city_code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    gbfs_root_url: Mapped[str | None] = mapped_column(Text)
    centre_lat: Mapped[float] = mapped_column(Double)
    centre_lon: Mapped[float] = mapped_column(Double)
    default_zoom: Mapped[float] = mapped_column(REAL)


class Station(CreatedAtMixin, Base):
    """A docking station, keyed by an internal stable key."""

    __tablename__ = "stations"
    __table_args__ = (
        UniqueConstraint("city_code", "source_id"),
        CheckConstraint("capacity >= 0", name="capacity_non_negative"),
    )

    station_key: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(ForeignKey("cities.city_code"))
    source_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lon: Mapped[float] = mapped_column(Double)
    capacity: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(TZ)
    last_seen: Mapped[datetime] = mapped_column(TZ)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    cluster_id: Mapped[int | None] = mapped_column(Integer)


class StationIdMap(CreatedAtMixin, Base):
    """Maps historical station IDs to station keys."""

    __tablename__ = "station_id_map"

    city_code: Mapped[str] = mapped_column(Text, primary_key=True)
    legacy_id: Mapped[str] = mapped_column(Text, primary_key=True)
    station_key: Mapped[int] = mapped_column(ForeignKey("stations.station_key"))
    method: Mapped[str] = mapped_column(Text)


class StationStatusRaw(CreatedAtMixin, Base):
    """One observed status per station per poll/snapshot."""

    __tablename__ = "station_status_raw"
    __table_args__ = (
        CheckConstraint("bikes_available >= 0", name="bikes_non_negative"),
        CheckConstraint("docks_available >= 0", name="docks_non_negative"),
        Index("ix_station_status_raw_observed_at", "observed_at"),
    )

    station_key: Mapped[int] = mapped_column(ForeignKey("stations.station_key"), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    last_reported: Mapped[datetime | None] = mapped_column(TZ)
    bikes_available: Mapped[int] = mapped_column(Integer)
    docks_available: Mapped[int] = mapped_column(Integer)
    is_renting: Mapped[bool | None] = mapped_column(Boolean)
    is_returning: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(Text)


class StationStatus15m(CreatedAtMixin, Base):
    """Station status on the 15-minute grid."""

    __tablename__ = "station_status_15m"

    station_key: Mapped[int] = mapped_column(ForeignKey("stations.station_key"), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    bikes_last: Mapped[float | None] = mapped_column(REAL)
    bikes_min: Mapped[float | None] = mapped_column(REAL)
    bikes_max: Mapped[float | None] = mapped_column(REAL)
    docks_last: Mapped[float | None] = mapped_column(REAL)
    docks_min: Mapped[float | None] = mapped_column(REAL)
    n_obs: Mapped[int] = mapped_column(Integer)
    is_imputed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_closed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    rebalance_flag: Mapped[bool] = mapped_column(Boolean, server_default="false")
    capacity_mismatch: Mapped[bool] = mapped_column(Boolean, server_default="false")
    flatline_flag: Mapped[bool] = mapped_column(Boolean, server_default="false")


class WeatherHourly(CreatedAtMixin, Base):
    """Hourly observed or forecast weather.

    ``issued_at`` is part of the PRD primary key but null for observations; Postgres primary keys
    cannot contain nulls, so a surrogate id plus a NULLS NOT DISTINCT unique constraint is used.
    """

    __tablename__ = "weather_hourly"
    __table_args__ = (
        UniqueConstraint(
            "city_code", "ts", "kind", "issued_at", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(ForeignKey("cities.city_code"))
    ts: Mapped[datetime] = mapped_column(TZ)
    kind: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime | None] = mapped_column(TZ)
    temp_c: Mapped[float | None] = mapped_column(REAL)
    precip_mm: Mapped[float | None] = mapped_column(REAL)
    wind_speed_ms: Mapped[float | None] = mapped_column(REAL)
    humidity_pct: Mapped[float | None] = mapped_column(REAL)
    cloud_pct: Mapped[float | None] = mapped_column(REAL)


class CalendarDay(CreatedAtMixin, Base):
    """Local-date calendar flags."""

    __tablename__ = "calendar_days"

    city_code: Mapped[str] = mapped_column(ForeignKey("cities.city_code"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_public_holiday: Mapped[bool] = mapped_column(Boolean)
    holiday_name: Mapped[str | None] = mapped_column(Text)
    is_school_term: Mapped[bool | None] = mapped_column(Boolean)  # NULL = no sourced dates
    is_uni_term: Mapped[bool | None] = mapped_column(Boolean)


class ModelVersion(CreatedAtMixin, Base):
    """A trained model registered for serving."""

    __tablename__ = "model_versions"

    model_version: Mapped[str] = mapped_column(Text, primary_key=True)
    mlflow_run_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    horizon_min: Mapped[int | None] = mapped_column(Integer)
    trained_at: Mapped[datetime] = mapped_column(TZ)
    train_end: Mapped[datetime] = mapped_column(TZ)
    is_champion: Mapped[bool] = mapped_column(Boolean, server_default="false")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Forecast(CreatedAtMixin, Base):
    """Quantile forecast of bikes for one station, issue time and horizon."""

    __tablename__ = "forecasts"
    __table_args__ = (CheckConstraint("horizon_min IN (30, 60, 120)", name="valid_horizon"),)

    station_key: Mapped[int] = mapped_column(ForeignKey("stations.station_key"), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    horizon_min: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_ts: Mapped[datetime] = mapped_column(TZ)
    bikes_p10: Mapped[float] = mapped_column(REAL)
    bikes_p50: Mapped[float] = mapped_column(REAL)
    bikes_p90: Mapped[float] = mapped_column(REAL)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.model_version"))


class RiskScore(CreatedAtMixin, Base):
    """P(empty) / P(full) within a window."""

    __tablename__ = "risk_scores"
    __table_args__ = (
        CheckConstraint("p_empty BETWEEN 0 AND 1", name="p_empty_range"),
        CheckConstraint("p_full BETWEEN 0 AND 1", name="p_full_range"),
    )

    station_key: Mapped[int] = mapped_column(ForeignKey("stations.station_key"), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    window_min: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="60")
    p_empty: Mapped[float] = mapped_column(REAL)
    p_full: Mapped[float] = mapped_column(REAL)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.model_version"))


class BacktestResult(CreatedAtMixin, Base):
    """One row per model x fold x horizon x slice."""

    __tablename__ = "backtest_results"

    run_id: Mapped[str] = mapped_column(Text, primary_key=True)
    experiment: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text, primary_key=True)
    fold: Mapped[int] = mapped_column(Integer, primary_key=True)
    horizon_min: Mapped[int] = mapped_column(Integer, primary_key=True)
    slice_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    slice_value: Mapped[str] = mapped_column(Text, primary_key=True)
    n: Mapped[int] = mapped_column(Integer)
    mae: Mapped[float | None] = mapped_column(REAL)
    rmse: Mapped[float | None] = mapped_column(REAL)
    mase: Mapped[float | None] = mapped_column(REAL)
    pinball_p10: Mapped[float | None] = mapped_column(REAL)
    pinball_p50: Mapped[float | None] = mapped_column(REAL)
    pinball_p90: Mapped[float | None] = mapped_column(REAL)
    coverage_80: Mapped[float | None] = mapped_column(REAL)
    interval_width: Mapped[float | None] = mapped_column(REAL)
    pr_auc: Mapped[float | None] = mapped_column(REAL)
    brier: Mapped[float | None] = mapped_column(REAL)


class CollectorRun(CreatedAtMixin, Base):
    """One collector poll."""

    __tablename__ = "collector_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    city_code: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text)
    stations_seen: Mapped[int | None] = mapped_column(Integer)
    rows_written: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # Top-level last_updated of station_status; feed is stale if older than stale_after_min
    # (owner decision 2026-10-15, replaces the per-station last_reported rule of PRD 9.1).
    feed_last_updated: Mapped[datetime | None] = mapped_column(TZ)


class DataGap(CreatedAtMixin, Base):
    """A network-wide period without observations (PRD 9.8)."""

    __tablename__ = "data_gaps"

    gap_start: Mapped[datetime] = mapped_column(TZ, primary_key=True)  # last obs before
    gap_end: Mapped[datetime] = mapped_column(TZ)  # first obs after
    source_before: Mapped[str] = mapped_column(Text)
    source_after: Mapped[str] = mapped_column(Text)
    duration_s: Mapped[int] = mapped_column(BigInteger)


class DataQualityFile(CreatedAtMixin, Base):
    """Profile of one historical file."""

    __tablename__ = "data_quality_files"

    file_name: Mapped[str] = mapped_column(Text, primary_key=True)
    format: Mapped[str] = mapped_column(Text)
    rows: Mapped[int] = mapped_column(Integer)
    min_ts: Mapped[datetime | None] = mapped_column(TZ)
    max_ts: Mapped[datetime | None] = mapped_column(TZ)
    stations: Mapped[int | None] = mapped_column(Integer)
    median_interval_s: Mapped[int | None] = mapped_column(Integer)
    pct_missing: Mapped[float | None] = mapped_column(REAL)
    is_empty: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(TZ)

"""Exploratory data analysis → ``reports/eda.md`` + ``reports/figures/eda_*.png`` (PRD M2).

Every number in the report is computed here from the database or the raw weather file. The
main analysis window is Format B (training scope, PRD 9.1a); Format A and live data are
summarised separately. Local-time breakdowns use Europe/Dublin; storage stays UTC.
"""

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure
from sqlalchemy import Engine, text

from dockcast.config import PROJECT_ROOT, get_env_settings
from dockcast.db.engine import make_engine

REPORT = PROJECT_ROOT / "reports" / "eda.md"
FIGURES = PROJECT_ROOT / "reports" / "figures"
TZ = "Europe/Dublin"
LOCAL_HOUR = f"extract(hour FROM {{col}} AT TIME ZONE '{TZ}')::int"
LOCAL_DOW = f"extract(isodow FROM {{col}} AT TIME ZONE '{TZ}')::int"


@dataclass(frozen=True)
class Window:
    """Analysis window in UTC."""

    name: str
    start: str
    end: str


def q(engine: Engine, sql: str, **params: Any) -> pd.DataFrame:
    """Run a query into a DataFrame.

    Args:
        engine: Database engine.
        sql: SQL text.
        **params: Bind parameters.

    Returns:
        Result frame.
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        frame = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    for col in frame.columns:  # Postgres numeric -> Decimal; analysis needs floats
        if frame[col].map(lambda v: isinstance(v, Decimal)).any():
            frame[col] = frame[col].astype(float)
    return frame


def b_window(engine: Engine) -> Window:
    """Format B window: first to last B observation.

    Args:
        engine: Database engine.

    Returns:
        The window.
    """
    row = q(
        engine,
        "SELECT min(observed_at) AS lo, max(observed_at) AS hi "
        "FROM station_status_raw WHERE source = 'hist_b'",
    ).iloc[0]
    return Window("Format B", row.lo.isoformat(), row.hi.isoformat())


def coverage(engine: Engine) -> pd.DataFrame:
    """Rows, stations and span per source."""
    return q(
        engine,
        "SELECT source, count(*) AS rows, count(DISTINCT station_key) AS stations, "
        "min(observed_at) AS first, max(observed_at) AS last FROM station_status_raw "
        "GROUP BY source ORDER BY min(observed_at)",
    )


def hourly_profile(engine: Engine, w: Window) -> pd.DataFrame:
    """Occupancy, empty and full shares by local hour, weekday vs weekend."""
    return q(
        engine,
        f"""
        SELECT {LOCAL_HOUR.format(col="b.ts")} AS hour,
               ({LOCAL_DOW.format(col="b.ts")} >= 6) AS weekend,
               avg(b.bikes_last / NULLIF(s.capacity, 0)) AS occupancy,
               avg((b.bikes_last = 0)::int) AS empty_share,
               avg((b.docks_last = 0)::int) AS full_share,
               count(*) AS buckets
        FROM station_status_15m b JOIN stations s USING (station_key)
        WHERE b.n_obs > 0 AND NOT b.is_closed AND b.ts >= :start AND b.ts <= :end
        GROUP BY 1, 2 ORDER BY 2, 1
        """,
        start=w.start,
        end=w.end,
    )


TURNOVER_CTE = """
WITH d AS (
    SELECT b.station_key, b.ts,
           abs(b.bikes_last - lag(b.bikes_last) OVER w) AS dbikes,
           b.ts - lag(b.ts) OVER w AS step
    FROM station_status_15m b
    WHERE b.n_obs > 0 AND NOT b.is_closed AND b.ts >= :start AND b.ts <= :end
    WINDOW w AS (PARTITION BY b.station_key ORDER BY b.ts)
)
"""


def turnover_by_hour(engine: Engine, w: Window) -> pd.DataFrame:
    """Mean |Δbikes| between consecutive observed buckets (activity proxy; no trip data)."""
    return q(
        engine,
        TURNOVER_CTE
        + f"""
        SELECT {LOCAL_HOUR.format(col="ts")} AS hour, {LOCAL_DOW.format(col="ts")} AS dow,
               avg(dbikes) AS mean_abs_change, count(*) AS n
        FROM d WHERE step = INTERVAL '15 minutes'
        GROUP BY 1, 2 ORDER BY 2, 1
        """,
        start=w.start,
        end=w.end,
    )


def turnover_vs_weather(engine: Engine, w: Window) -> pd.DataFrame:
    """Network turnover per UTC hour (weekdays 07-20 local) joined to observed weather."""
    return q(
        engine,
        TURNOVER_CTE
        + f"""
        , hourly AS (
            SELECT date_trunc('hour', ts) AS hour_utc, avg(dbikes) AS turnover
            FROM d WHERE step = INTERVAL '15 minutes'
              AND {LOCAL_DOW.format(col="ts")} <= 5
              AND {LOCAL_HOUR.format(col="ts")} BETWEEN 7 AND 20
            GROUP BY 1
        )
        SELECT h.hour_utc, h.turnover, wx.precip_mm, wx.temp_c, wx.wind_speed_ms
        FROM hourly h JOIN weather_hourly wx
          ON wx.kind = 'observed' AND wx.ts = h.hour_utc + INTERVAL '1 hour'
        """,
        start=w.start,
        end=w.end,
    )


RAW_DIFF_CTE = """
WITH r AS (
    SELECT station_key, observed_at, bikes_available,
           bikes_available - lag(bikes_available) OVER w AS dbikes,
           extract(epoch FROM observed_at - lag(observed_at) OVER w) / 60 AS gap_min
    FROM station_status_raw
    WHERE source = :source
    WINDOW w AS (PARTITION BY station_key ORDER BY observed_at)
)
"""


def jump_distribution(engine: Engine, source: str, max_gap_min: float) -> pd.DataFrame:
    """|Δbikes| between consecutive raw observations at most ``max_gap_min`` apart."""
    return q(
        engine,
        RAW_DIFF_CTE
        + """
        SELECT least(abs(dbikes), 20)::int AS abs_change, count(*) AS n
        FROM r WHERE gap_min <= :max_gap AND dbikes IS NOT NULL GROUP BY 1 ORDER BY 1
        """,
        source=source,
        max_gap=max_gap_min,
    )


def big_jumps_by_hour(
    engine: Engine, source: str, max_gap_min: float, threshold: int
) -> pd.DataFrame:
    """Jumps of at least ``threshold`` bikes by local hour (rebalancing vs demand)."""
    return q(
        engine,
        RAW_DIFF_CTE
        + f"""
        SELECT {LOCAL_HOUR.format(col="observed_at")} AS hour,
               count(*) FILTER (WHERE dbikes >= :t) AS up,
               count(*) FILTER (WHERE dbikes <= -:t) AS down
        FROM r WHERE gap_min <= :max_gap GROUP BY 1 ORDER BY 1
        """,
        source=source,
        max_gap=max_gap_min,
        t=threshold,
    )


def flatline_runs(engine: Engine, source: str, break_gap_min: int = 30) -> pd.DataFrame:
    """Length (hours) of runs of identical bike counts per station while renting.

    A silence longer than ``break_gap_min`` ends a run (same rule as the flat-line flag).
    """
    return q(
        engine,
        """
        WITH r AS (
            SELECT station_key, observed_at,
                   (bikes_available IS DISTINCT FROM lag(bikes_available) OVER w
                    OR observed_at - lag(observed_at) OVER w
                       > make_interval(mins => :gap))::int AS changed
            FROM station_status_raw WHERE source = :source AND is_renting IS NOT FALSE
            WINDOW w AS (PARTITION BY station_key ORDER BY observed_at)
        ), g AS (
            SELECT station_key, observed_at,
                   sum(changed) OVER (PARTITION BY station_key ORDER BY observed_at) AS run
            FROM r
        )
        SELECT station_key, run, min(observed_at) AS run_start,
               extract(epoch FROM max(observed_at) - min(observed_at)) / 3600 AS hours
        FROM g GROUP BY 1, 2
        """,
        source=source,
        gap=break_gap_min,
    )


def capacity_check(engine: Engine, source: str) -> pd.DataFrame:
    """Bikes + docks compared with each station's current capacity."""
    return q(
        engine,
        """
        WITH t AS (
            SELECT r.bikes_available + r.docks_available AS total, s.capacity
            FROM station_status_raw r JOIN stations s USING (station_key)
            WHERE r.source = :source
        )
        SELECT CASE WHEN total > capacity + 2 THEN 'over capacity+2'
                    WHEN total = capacity THEN 'equal'
                    WHEN total < capacity THEN 'below (disabled docks?)'
                    ELSE 'over by 1-2' END AS relation,
               count(*) AS n
        FROM t GROUP BY 1 ORDER BY 2 DESC
        """,
        source=source,
    )


def closures(engine: Engine) -> pd.DataFrame:
    """Raw rows with ``is_renting = false`` per source."""
    return q(
        engine,
        "SELECT source, count(*) FILTER (WHERE is_renting IS FALSE) AS not_renting, "
        "count(*) AS rows FROM station_status_raw GROUP BY 1 ORDER BY 1",
    )


def weather_quality(raw_file: Path, start: str) -> tuple[int, int]:
    """Rows since ``start`` and how many carry indicator 111 in the Met Éireann file."""
    lines = raw_file.read_text(encoding="utf-8", errors="replace").splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("date,"))
    frame = pd.read_csv(raw_file, skiprows=header, dtype=str)
    when = pd.to_datetime(frame["date"], format="%d-%b-%Y %H:%M")
    frame = frame[when >= pd.Timestamp(start[:10])]
    return len(frame), int((frame["ind"].str.strip() == "111").sum())


def md_table(frame: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    """Render a frame as a markdown table.

    Args:
        frame: Data.
        floatfmt: Format for float cells.

    Returns:
        Markdown.
    """
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _save(fig: Figure, name: str) -> str:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIGURES / name, dpi=110)
    plt.close(fig)
    return f"![](figures/{name})"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
    except OSError:
        return "unknown"
    return out.stdout.strip() or "unknown"


def _section_profile(engine: Engine, w: Window) -> list[str]:
    prof = hourly_profile(engine, w)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.5))
    titles = ("mean occupancy (bikes/capacity)", "share empty", "share full")
    for weekend, label in ((False, "weekday"), (True, "weekend")):
        part = prof[prof.weekend == weekend]
        for ax, col in zip(axes, ("occupancy", "empty_share", "full_share"), strict=True):
            ax.plot(part.hour, part[col], label=label)
    for ax, title in zip(axes, titles, strict=True):
        ax.set_title(title)
        ax.set_xlabel("local hour")
        ax.legend()
    e = prof.loc[prof.empty_share.idxmax()]
    f = prof.loc[prof.full_share.idxmax()]
    return [
        "## 2. Occupancy, empty and full by hour",
        "",
        _save(fig, "eda_hourly_profile.png"),
        "",
        f"Highest empty share {e.empty_share:.3f} at {int(e.hour):02d}:00 "
        f"({'weekend' if e.weekend else 'weekday'}); highest full share {f.full_share:.3f} at "
        f"{int(f.hour):02d}:00 ({'weekend' if f.weekend else 'weekday'}).",
        "",
    ]


def _section_turnover(engine: Engine, w: Window) -> list[str]:
    pivot = turnover_by_hour(engine, w).pivot(index="dow", columns="hour", values="mean_abs_change")
    fig, ax = plt.subplots(figsize=(11, 3.2))
    image = ax.imshow(pivot.values, aspect="auto", cmap="viridis")
    ax.set_yticks(range(7), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    ax.set_xticks(range(0, 24, 2), [str(h) for h in range(0, 24, 2)])
    ax.set_xlabel("local hour")
    ax.set_title("mean |Δbikes| per station per 15 min (activity proxy, not trips)")
    fig.colorbar(image, ax=ax)
    return ["## 3. Activity by hour and weekday", "", _save(fig, "eda_turnover_heatmap.png"), ""]


def _section_weather(engine: Engine, w: Window) -> list[str]:
    tw = turnover_vs_weather(engine, w)
    tw["rain_mm"] = pd.cut(
        tw.precip_mm, [-0.01, 0.0, 0.5, 2.0, 100], labels=["0", "0-0.5", "0.5-2", ">2"]
    )
    tw["temp_c_bin"] = pd.cut(
        tw.temp_c, [-20, 5, 10, 15, 20, 40], labels=["<5", "5-10", "10-15", "15-20", ">20"]
    )
    names = {"mean": "mean_turnover", "count": "hours"}
    rain = tw.groupby("rain_mm", observed=True).turnover.agg(["mean", "count"]).reset_index()
    temp = tw.groupby("temp_c_bin", observed=True).turnover.agg(["mean", "count"]).reset_index()
    out = [
        "## 4. Activity vs weather (weekdays 07-20 local, Dublin Airport hourly observations)",
        "",
        "Hourly network-mean |Δbikes| joined to the observation for that hour (rain = mm in the "
        "hour ending at the observation). Not controlled for season or hour.",
        "",
        md_table(rain.rename(columns=names)),
        "",
        md_table(temp.rename(columns=names)),
        "",
    ]
    wx_file = get_env_settings().data_dir / "raw" / "weather" / "hly532.csv"
    if wx_file.exists():
        total, flagged = weather_quality(wx_file, w.start)
        out += [
            f"Weather QC: {flagged} of {total} hours since {w.start[:10]} "
            f'({100 * flagged / total:.1f}%) carry indicator 111 ("investigation required": '
            "not yet quality-controlled by Met Éireann).",
            "",
        ]
    return out


def _section_jumps(engine: Engine) -> list[str]:
    out = [
        "## 6. Large count jumps (rebalancing candidates, PRD 9.3)",
        "",
        "Raw consecutive observations, before spike removal (the 03:15 local Format B spikes "
        "are visible here; section 8 shows what the cleaning removed and flagged).",
        "",
    ]
    for source, max_gap in (("hist_b", 10.0), ("live", 5.0)):
        dist = jump_distribution(engine, source, max_gap)
        if dist.empty:
            continue
        total = int(dist.n.sum())
        tail = {t: int(dist[dist.abs_change >= t].n.sum()) for t in (4, 6, 8, 10, 12)}
        shares = ", ".join(f"|Δ| ≥ {t}: {n} ({100 * n / total:.3f}%)" for t, n in tail.items())
        out += [f"**{source}**, consecutive observations ≤ {max_gap:.0f} min apart "
                f"({total} pairs): {shares}", ""]  # fmt: skip
        hours = big_jumps_by_hour(engine, source, max_gap, 8)
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.bar(hours.hour - 0.2, hours.up, width=0.4, label="+8 or more")
        ax.bar(hours.hour + 0.2, hours.down, width=0.4, label="-8 or more")
        ax.set_xlabel("local hour")
        ax.set_title(f"{source}: jumps of >= 8 bikes between consecutive observations")
        ax.legend()
        out += [_save(fig, f"eda_jumps_{source}.png"), ""]
    return out


def _section_flatline(engine: Engine) -> list[str]:
    runs = flatline_runs(engine, "hist_b")
    levels = [0.5, 0.9, 0.99, 0.999]
    values = runs.hours.quantile(levels).round(2).tolist()
    q_text = ", ".join(f"p{100 * k:g} = {v}" for k, v in zip(levels, values, strict=True))
    over = ", ".join(f"> {h} h: {int((runs.hours > h).sum())}" for h in (6, 12, 24, 48))
    longest = runs.nlargest(10, "hours")[["station_key", "run_start", "hours"]]
    return [
        "## 7. Flat-lined counts (owner decision 2026-10-15: flag stations unchanged > N h)",
        "",
        f"Format B: {len(runs)} runs of identical bike counts while renting (a silence > 30 min "
        f"ends a run); run length (h) "
        f"{q_text}. Runs {over}.",
        "",
        md_table(longest, "{:.1f}"),
        "",
    ]


def cleaning_summary(engine: Engine) -> pd.DataFrame:
    """Per source period: raw rows, rows excluded as spikes, and flagged buckets (PRD 9.3)."""
    return q(
        engine,
        """
        WITH periods AS (
            SELECT source, min(observed_at) AS lo, max(observed_at) AS hi, count(*) AS raw_rows
            FROM station_status_raw GROUP BY 1
        )
        SELECT p.source, p.raw_rows,
               p.raw_rows - sum(b.n_obs) AS spikes_excluded,
               count(*) FILTER (WHERE b.n_obs > 0) AS observed_buckets,
               count(*) FILTER (WHERE b.is_imputed) AS imputed,
               count(*) FILTER (WHERE b.rebalance_flag) AS rebalance,
               count(*) FILTER (WHERE b.flatline_flag) AS flatline,
               count(*) FILTER (WHERE b.capacity_mismatch) AS capacity_mismatch,
               count(*) FILTER (WHERE b.is_closed) AS closed
        FROM periods p JOIN station_status_15m b
          ON b.ts >= date_bin('15 minutes', p.lo, TIMESTAMPTZ '2000-01-01 00:00+00')
         AND b.ts <= p.hi
        GROUP BY p.source, p.raw_rows ORDER BY min(p.lo)
        """,
    )


def build_report(engine: Engine) -> str:
    """Compute everything and render the markdown report (also writes the figures).

    Args:
        engine: Database engine.

    Returns:
        Markdown text.
    """
    w = b_window(engine)
    gaps = q(engine, "SELECT count(*) AS n, sum(duration_s) / 86400.0 AS days FROM data_gaps")
    parts = [
        "# Exploratory data analysis",
        "",
        f"Generated by `dockcast.quality.eda` at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, git "
        f"`{_git_commit()}`. Main window: **{w.name}** {w.start[:16]} → {w.end[:16]} UTC "
        "(training scope, PRD 9.1a). Descriptive statistics only; no model metrics, so no "
        "MLflow run (MLflow starts in M3).",
        "Data © Dublin City Council / Smart Dublin (CC BY 4.0); weather © Met Éireann (CC BY 4.0).",
        "",
        "## 1. Coverage",
        "",
        md_table(coverage(engine)),
        "",
        f"Data gaps (`reports/data_gaps.md`): {int(gaps.n[0])} gaps, "
        f"{float(gaps.days[0] or 0):.1f} days in total.",
        "",
        *_section_profile(engine, w),
        *_section_turnover(engine, w),
        *_section_weather(engine, w),
        "## 5. Closures (`is_renting = false`)",
        "",
        md_table(closures(engine)),
        "",
        *_section_jumps(engine),
        *_section_flatline(engine),
        "## 8. Cleaning applied (PRD 9.3; thresholds in config/settings.toml [cleaning])",
        "",
        "Spikes are single V-shaped readings removed before bucketing; flags mark 15-min buckets "
        "and are kept for error analysis. Capacity uses the capacity in force at the time.",
        "",
        md_table(cleaning_summary(engine)),
        "",
        "## 9. bikes + docks vs current capacity (before using capacity history)",
        "",
    ]
    for source in ("hist_b", "live"):
        parts += [f"**{source}**", "", md_table(capacity_check(engine, source)), ""]
    return "\n".join(parts)


def main() -> None:
    """Write ``reports/eda.md``."""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(make_engine()), encoding="utf-8")


if __name__ == "__main__":
    main()

"""``calendar_days`` from the ``holidays`` package (IE) and ``data/reference/terms.csv`` (PRD 9.6).

Dates are local (Europe/Dublin) calendar dates. ``is_school_term`` uses post-primary terms and
``is_uni_term`` uses TCD semesters (owner decisions 2026-10-25). A flag is ``None`` for dates
outside the span its institution's rows cover: unknown is never guessed as False.
"""

from datetime import date
from pathlib import Path

import holidays
import pandas as pd
import structlog
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from dockcast.config import PROJECT_ROOT, get_env_settings
from dockcast.db.engine import make_engine
from dockcast.db.models import CalendarDay

log = structlog.get_logger(job="calendar")

TERMS_PATH = PROJECT_ROOT / "data" / "reference" / "terms.csv"
TERMS_COLUMNS = ["institution", "kind", "start_date", "end_date", "source_url", "note"]
SCHOOL_INSTITUTION = "post_primary"
UNI_INSTITUTIONS = ("tcd",)


def load_terms(path: Path = TERMS_PATH) -> pd.DataFrame:
    """Read and validate the hand-maintained terms file.

    Args:
        path: CSV path.

    Returns:
        Terms with ``start_date``/``end_date`` as dates.

    Raises:
        ValueError: On missing columns, missing source URLs or reversed ranges.
    """
    terms = pd.read_csv(path, dtype=str)
    if list(terms.columns) != TERMS_COLUMNS:
        raise ValueError(f"terms.csv columns {list(terms.columns)} != {TERMS_COLUMNS}")
    if terms["source_url"].fillna("").str.strip().eq("").any():
        raise ValueError("every terms.csv row needs a source_url")
    terms["start_date"] = pd.to_datetime(terms["start_date"]).dt.date
    terms["end_date"] = pd.to_datetime(terms["end_date"]).dt.date
    if (terms["start_date"] > terms["end_date"]).any():
        raise ValueError("terms.csv has a row with start_date > end_date")
    return terms


def term_flags(
    days: pd.DatetimeIndex, terms: pd.DataFrame, institutions: tuple[str, ...]
) -> list[bool | None]:
    """In-term flag per day for the given institutions; None outside their covered span.

    Args:
        days: Calendar days.
        terms: Output of :func:`load_terms`.
        institutions: Institutions whose ``term`` rows count.

    Returns:
        One flag per day.
    """
    rows = terms[terms["institution"].isin(institutions) & terms["kind"].eq("term")]
    if rows.empty:
        return [None] * len(days)
    covered_from, covered_to = min(rows["start_date"]), max(rows["end_date"])
    flags: list[bool | None] = []
    for ts in days:
        day = ts.date()
        if day < covered_from or day > covered_to:
            flags.append(None)
        else:
            inside = ((rows["start_date"] <= day) & (rows["end_date"] >= day)).any()
            flags.append(bool(inside))
    return flags


def build_calendar(
    start: date, end: date, terms: pd.DataFrame, country: str = "IE"
) -> pd.DataFrame:
    """One row per local date with holiday and term flags.

    Args:
        start: First date.
        end: Last date (inclusive).
        terms: Output of :func:`load_terms`.
        country: ``holidays`` country code.

    Returns:
        Columns of ``calendar_days`` except ``city_code``.
    """
    days = pd.date_range(start, end, freq="D")
    public = holidays.country_holidays(country, years=range(start.year, end.year + 1))
    return pd.DataFrame(
        {
            "date": [d.date() for d in days],
            "is_public_holiday": [d.date() in public for d in days],
            "holiday_name": [public.get(d.date()) for d in days],
            "is_school_term": term_flags(days, terms, (SCHOOL_INSTITUTION,)),
            "is_uni_term": term_flags(days, terms, UNI_INSTITUTIONS),
        }
    )


def store_calendar(engine: Engine, city_code: str, frame: pd.DataFrame) -> int:
    """Upsert calendar rows.

    Args:
        engine: Database engine.
        city_code: City code.
        frame: Output of :func:`build_calendar`.

    Returns:
        Rows written.
    """
    records = [{"city_code": city_code, **row} for row in frame.to_dict("records")]
    base = insert(CalendarDay).values(records)
    upsert = base.on_conflict_do_update(
        index_elements=["city_code", "date"],
        set_={c: base.excluded[c] for c in frame.columns if c != "date"},
    ).returning(CalendarDay.date)
    with engine.begin() as conn:
        return len(conn.execute(upsert).all())


def main() -> None:
    """Entry point for ``make calendar``: 2021-09-01 to 2027-08-31."""
    settings = get_env_settings()
    frame = build_calendar(date(2021, 9, 1), date(2027, 8, 31), load_terms())
    written = store_calendar(make_engine(), settings.city, frame)
    log.info(
        "calendar_stored",
        days=written,
        public_holidays=int(frame["is_public_holiday"].sum()),
        school_unknown=int(frame["is_school_term"].isna().sum()),
        uni_unknown=int(frame["is_uni_term"].isna().sum()),
    )


if __name__ == "__main__":
    main()

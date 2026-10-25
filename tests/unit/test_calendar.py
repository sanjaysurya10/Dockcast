from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from dockcast.ingest.calendar import build_calendar, load_terms

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def cal() -> pd.DataFrame:
    frame = build_calendar(date(2021, 9, 1), date(2027, 8, 31), load_terms())
    return frame.set_index("date")


def test_real_terms_file_is_valid_and_sourced() -> None:
    terms = load_terms()
    assert set(terms["institution"]) == {"post_primary", "tcd"}
    assert terms["source_url"].str.startswith("https://").all()


def test_public_holidays_ie(cal: pd.DataFrame) -> None:
    assert cal.loc[date(2025, 3, 17), "is_public_holiday"]  # St Patrick's Day
    assert cal.loc[date(2022, 3, 18), "holiday_name"] == "Day of Remembrance and Recognition"
    assert cal.loc[date(2026, 2, 2), "is_public_holiday"]  # St Brigid's Day (first Monday Feb)
    assert not cal.loc[date(2025, 3, 18), "is_public_holiday"]


def test_school_breaks_from_circulars(cal: pd.DataFrame) -> None:
    # Circular 0072/2022: October 2025 mid-term Mon 27 - Fri 31 Oct; re-open Mon 3 Nov
    assert not cal.loc[date(2025, 10, 29), "is_school_term"]
    assert cal.loc[date(2025, 11, 3), "is_school_term"]
    # Christmas 2024: final day Fri 20 Dec, re-open Mon 6 Jan 2025
    assert cal.loc[date(2024, 12, 20), "is_school_term"]
    assert not cal.loc[date(2024, 12, 27), "is_school_term"]
    assert cal.loc[date(2025, 1, 6), "is_school_term"]
    # Summer: post-primary not open beyond the Friday before the June bank holiday
    assert cal.loc[date(2025, 5, 30), "is_school_term"]
    assert not cal.loc[date(2025, 6, 3), "is_school_term"]
    assert not cal.loc[date(2025, 7, 15), "is_school_term"]


def test_tcd_semesters(cal: pd.DataFrame) -> None:
    assert cal.loc[date(2025, 9, 15), "is_uni_term"]  # 2025/26 teaching begins
    assert not cal.loc[date(2025, 9, 8), "is_uni_term"]
    assert not cal.loc[date(2026, 1, 5), "is_uni_term"]  # between semesters
    assert not cal.loc[date(2026, 7, 1), "is_uni_term"]


def test_unknown_outside_coverage_is_none(cal: pd.DataFrame) -> None:
    assert cal.loc[date(2027, 7, 1), "is_school_term"] is None  # after 2026/27 rows
    assert cal.loc[date(2027, 6, 1), "is_uni_term"] is None  # TCD rows end 30 Apr 2027


def test_terms_validation(tmp_path: Path) -> None:
    bad = tmp_path / "terms.csv"
    bad.write_text(
        "institution,kind,start_date,end_date,source_url,note\ntcd,term,2025-09-15,2025-12-22,,x\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_terms(bad)

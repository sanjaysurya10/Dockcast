from datetime import UTC, datetime

import pandas as pd
import pytest

from dockcast.transform.capacity_points import change_points, merge_points, point_records

pytestmark = pytest.mark.unit


def _frame(rows: list[tuple[int, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_key": [r[0] for r in rows],
            "observed_at": pd.to_datetime([r[1] for r in rows], utc=True),
            "capacity": [r[2] for r in rows],
            "source": "hist_b",
        }
    )


def test_change_points_keep_first_of_each_value() -> None:
    frame = _frame(
        [
            (1, "2025-01-01 00:00", 20),
            (1, "2025-01-02 00:00", 20),
            (1, "2025-01-03 00:00", 30),
            (2, "2025-01-01 00:00", 40),
        ]
    )
    points = change_points(frame)
    assert list(points.capacity) == [20, 30, 40]
    assert points.valid_from.iloc[1] == pd.Timestamp("2025-01-03", tz="UTC")


def test_merge_drops_repeats_across_files() -> None:
    a = change_points(_frame([(1, "2025-01-01 00:00", 20)]))
    b = change_points(_frame([(1, "2025-02-01 00:00", 20), (1, "2025-03-01 00:00", 25)]))
    merged = merge_points([b, a])
    assert list(merged.capacity) == [20, 25]
    record = point_records(merged)[1]
    assert record == {
        "station_key": 1,
        "valid_from": datetime(2025, 3, 1, tzinfo=UTC),
        "capacity": 25,
        "source": "hist_b",
    }


def test_merge_of_nothing() -> None:
    assert merge_points([]).empty

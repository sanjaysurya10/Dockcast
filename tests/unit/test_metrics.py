import math

import pandas as pd
import pytest

from dockcast.evaluation import metrics

pytestmark = pytest.mark.unit
Y = pd.Series([10.0, 0.0, 5.0, 20.0])
P = pd.Series([12.0, 1.0, 5.0, 16.0])  # errors +2, +1, 0, -4


def test_mae_rmse_bias_by_hand() -> None:
    assert metrics.mae(Y, P) == pytest.approx((2 + 1 + 0 + 4) / 4)
    assert metrics.rmse(Y, P) == pytest.approx(math.sqrt((4 + 1 + 0 + 16) / 4))
    assert metrics.bias(Y, P) == pytest.approx((2 + 1 + 0 - 4) / 4)


def test_mase() -> None:
    assert metrics.mase(1.5, 2.0) == 0.75
    assert math.isnan(metrics.mase(1.0, 0.0))


def test_pinball_by_hand() -> None:
    # q = 0.9: under-prediction costs 0.9 per bike, over-prediction 0.1 per bike
    y = pd.Series([10.0, 10.0])
    q = pd.Series([8.0, 13.0])
    assert metrics.pinball(y, q, 0.9) == pytest.approx((0.9 * 2 + 0.1 * 3) / 2)
    assert metrics.pinball(y, q, 0.5) == pytest.approx((0.5 * 2 + 0.5 * 3) / 2)


def test_coverage_and_width() -> None:
    lower = pd.Series([8.0, 1.0, 6.0, 15.0])
    upper = pd.Series([12.0, 3.0, 9.0, 25.0])
    assert metrics.coverage(Y, lower, upper) == 0.5  # 10 in, 0 out, 5 out, 20 in
    assert metrics.interval_width(lower, upper) == pytest.approx((4 + 2 + 3 + 10) / 4)

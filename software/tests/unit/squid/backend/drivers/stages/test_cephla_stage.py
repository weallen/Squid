import pytest

from squid.backend.drivers.stages.cephla import CephlaStage


def test_calc_move_timeout_scales_with_axis_speed():
    """Regression: the divisor was min(0.1, speed) instead of max(0.1, speed), which pinned it at
    0.1 mm/s and made every timeout 38x (z) to 300x (x/y) longer than the intended 3x naive move time."""
    timeout = CephlaStage._calc_move_timeout

    assert timeout(60.0, 30.0) == pytest.approx(6.0)  # 3 * 60 mm / 30 mm/s
    assert timeout(-60.0, 30.0) == pytest.approx(6.0)  # direction does not matter
    assert timeout(0.5, 2.0) == 3.0  # short moves get the 3 s floor
    assert timeout(1.0, 0.0) == pytest.approx(30.0)  # zero speed falls back to 0.1 mm/s instead of dividing by zero

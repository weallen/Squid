"""Microscope.close() is idempotent (upstream #604)."""

from unittest.mock import patch

from squid.backend.microscope import Microscope


def test_second_close_is_a_noop():
    scope = Microscope.build_from_global_config(simulated=True)
    with patch.object(scope.camera, "close", wraps=scope.camera.close) as camera_close, patch.object(
        scope.low_level_drivers.microcontroller, "close", wraps=scope.low_level_drivers.microcontroller.close
    ) as mcu_close:
        scope.close()
        scope.close()

    assert camera_close.call_count == 1
    assert mcu_close.call_count == 1

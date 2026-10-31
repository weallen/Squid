"""LiveController must not fire triggers while the microcontroller is busy (upstream #639).

A trigger sent mid-move wedges the firmware's single command-status slot, see the guard in
LiveController.trigger_acquisition.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from _def import TriggerMode
from squid.backend.controllers.live_controller import LiveController, LiveControllerState
from squid.backend.services.peripheral_service import PeripheralService
from squid.core.events import EventBus


def _make(busy: bool = False):
    cam = MagicMock()
    cam.get_ready_for_trigger.return_value = True
    cam.get_is_streaming.return_value = False
    cam.read_frame.return_value = np.zeros((2, 2))
    periph = MagicMock()
    periph.is_mcu_busy.return_value = busy
    controller = LiveController(
        camera_service=cam, event_bus=EventBus(), illumination_service=MagicMock(), peripheral_service=periph
    )
    controller.trigger_mode = TriggerMode.SOFTWARE
    return controller, cam, periph


@pytest.mark.parametrize("busy,expected_triggers", [(True, 0), (False, 1)])
def test_trigger_is_held_while_the_microcontroller_is_busy(busy, expected_triggers):
    controller, cam, _ = _make(busy)
    assert controller.trigger_acquisition() is (not busy)
    assert cam.send_trigger.call_count == expected_triggers


def test_busy_hold_rechecks_at_frame_cadence_not_every_10ms():
    # Each re-check spins up a fresh Timer thread, and a stage move lasts hundreds of 10 ms ticks.
    controller, _, _ = _make(busy=True)
    controller.is_live = True
    controller._start_new_timer = MagicMock()
    controller._trigger_acquisition_timer_fn()
    controller._start_new_timer.assert_called_once_with()  # default interval = frame cadence


def test_camera_not_ready_still_retries_quickly():
    controller, cam, _ = _make(busy=False)
    cam.get_ready_for_trigger.return_value = False
    controller.is_live = True
    controller._start_new_timer = MagicMock()
    controller._trigger_acquisition_timer_fn()
    controller._start_new_timer.assert_called_once_with(maybe_custom_interval_ms=10)


def test_held_trigger_is_not_queued():
    controller, cam, periph = _make(busy=True)
    assert controller.trigger_acquisition() is False
    periph.is_mcu_busy.return_value = False
    assert controller.trigger_acquisition() is True
    assert cam.send_trigger.call_count == 1  # only the post-move trigger


def test_no_peripheral_service_means_not_busy():
    cam = MagicMock()
    cam.get_ready_for_trigger.return_value = True
    controller = LiveController(camera_service=cam, event_bus=EventBus(), illumination_service=MagicMock())
    assert controller.trigger_acquisition() is True


def test_snap_refuses_when_microcontroller_stays_busy():
    controller, cam, periph = _make(busy=True)
    periph.wait_till_operation_is_completed.side_effect = TimeoutError("busy")
    assert controller.snap() is False
    cam.send_trigger.assert_not_called()
    assert controller.is_snapping is False


def test_snap_waits_for_microcontroller_then_snaps():
    controller, cam, periph = _make(busy=True)
    periph.wait_till_operation_is_completed.side_effect = lambda *_a: setattr(
        periph.is_mcu_busy, "return_value", False
    )
    assert controller.snap() is True
    periph.wait_till_operation_is_completed.assert_called_once()
    cam.send_trigger.assert_called_once()


def test_stop_live_timeout_still_stops_live():
    # A wedged MCU makes the illumination-off wait time out; live must still end up stopped
    # (trigger timer cancelled) so multipoint start can recover.
    controller, cam, _ = _make()
    controller.start_live()
    assert controller.is_live
    controller.turn_off_illumination = MagicMock(side_effect=TimeoutError("mcu wedged"))
    controller.stop_live()  # must not raise
    assert controller.is_live is False
    assert controller.state == LiveControllerState.STOPPED
    assert controller.timer_trigger is None


def test_peripheral_service_reports_mcu_busy():
    micro = MagicMock()
    micro.is_busy.return_value = True
    service = PeripheralService(micro, EventBus())
    assert service.is_mcu_busy() is True
    micro.is_busy.return_value = False
    assert service.is_mcu_busy() is False

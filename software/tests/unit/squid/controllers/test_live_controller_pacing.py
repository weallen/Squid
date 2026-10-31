"""The live FPS is a trigger rate: the interval to the next trigger runs from the start of the last one, so a
trigger that blocks does not lower the rate (upstream #716)."""

import time
from unittest.mock import Mock, patch

import pytest

from squid.backend.controllers.live_controller import LiveController
from squid.core.events import EventBus


def _live_controller() -> LiveController:
    controller = LiveController(
        event_bus=EventBus(),
        camera_service=Mock(),
        control_illumination=False,
        use_internal_timer_for_hardware_trigger=False,
    )
    controller.is_live = True
    controller.timer_trigger_interval = 100.0  # ms (10 fps)
    return controller


def _run_timer_fn(controller, trigger):
    with patch.object(controller, "trigger_acquisition", side_effect=trigger), patch.object(
        controller, "_start_new_timer"
    ) as start_new_timer:
        controller._trigger_acquisition_timer_fn()
    return start_new_timer


def test_a_blocking_trigger_shortens_the_wait_to_the_next_one():
    controller = _live_controller()

    start_new_timer = _run_timer_fn(controller, lambda: time.sleep(0.06) or True)

    interval_ms = start_new_timer.call_args.kwargs["maybe_custom_interval_ms"]
    assert 20 <= interval_ms <= 41  # 100 ms - ~60 ms spent in the trigger


def test_a_trigger_longer_than_the_interval_triggers_again_at_once():
    controller = _live_controller()

    start_new_timer = _run_timer_fn(controller, lambda: time.sleep(0.12) or True)

    assert start_new_timer.call_args.kwargs["maybe_custom_interval_ms"] == 0


def test_a_zero_interval_starts_the_timer_at_once():
    controller = _live_controller()

    with patch("threading.Timer") as timer:
        controller._start_new_timer(maybe_custom_interval_ms=0)

    assert timer.call_args.args[0] == 0  # 0 is a real wait, not "unset"


def test_no_custom_interval_uses_the_fps_interval():
    controller = _live_controller()

    with patch("threading.Timer") as timer:
        controller._start_new_timer()

    assert timer.call_args.args[0] == pytest.approx(0.1)


def test_a_failed_trigger_rechecks_soon():
    controller = _live_controller()

    start_new_timer = _run_timer_fn(controller, lambda: False)

    assert start_new_timer.call_args.kwargs == {"maybe_custom_interval_ms": 10}

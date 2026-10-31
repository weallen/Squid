"""LiveController.snap(): single-frame capture with the live configuration (upstream #616)."""

import time
from unittest.mock import MagicMock

import numpy as np

from _def import TriggerMode
from squid.backend.controllers.live_controller import LiveController
from squid.core.events import EventBus, SnapFrameCommand, SnapStateChanged, StartLiveCommand


def _make(trigger_mode=TriggerMode.SOFTWARE, frame=np.zeros((4, 4))):
    bus = EventBus()
    cam = MagicMock()
    cam.get_is_streaming.return_value = False
    cam.get_callbacks_enabled.return_value = False
    callbacks = {}

    def add_cb(cb):
        callbacks["cb"] = cb
        return "cb-id"

    cam.add_frame_callback.side_effect = add_cb

    def read_frame():
        # Simulate the camera delivering the frame to its callbacks.
        if frame is not None:
            callbacks["cb"](frame)
        return frame

    cam.read_frame.side_effect = read_frame
    illum = MagicMock()
    controller = LiveController(camera_service=cam, event_bus=bus, illumination_service=illum)
    controller.trigger_mode = trigger_mode
    controller.currentConfiguration = MagicMock(illumination_source=1, illumination_intensity=10.0)
    stream_handler = MagicMock()
    controller.set_stream_handler(stream_handler)
    return controller, bus, cam, illum, stream_handler


def test_software_snap_triggers_once_and_restores_camera():
    controller, _, cam, illum, stream_handler = _make()
    seen_snapping = []
    cam.send_trigger.side_effect = lambda *a, **k: seen_snapping.append(controller.should_display_frames())

    assert controller.snap() is True

    cam.send_trigger.assert_called_once()
    assert seen_snapping == [True]  # frames are accepted while snapping
    stream_handler.force_next_display.assert_called_once()
    illum.turn_on_channel.assert_called_once_with(1)
    illum.turn_off_channel.assert_called_once_with(1)
    assert controller.illumination_on is False
    cam.start_streaming.assert_called_once()
    cam.stop_streaming.assert_called_once()
    cam.enable_callbacks.assert_called_with(False)  # restored
    cam.remove_frame_callback.assert_called_once_with("cb-id")
    assert controller.is_snapping is False
    assert controller.should_display_frames() is False


def test_hardware_snap_does_not_turn_on_software_illumination():
    controller, _, cam, illum, _ = _make(trigger_mode=TriggerMode.HARDWARE)
    assert controller.snap() is True
    cam.send_trigger.assert_called_once()
    illum.turn_on_channel.assert_not_called()


def test_continuous_snap_sends_no_trigger():
    controller, _, cam, illum, _ = _make(trigger_mode=TriggerMode.CONTINUOUS)
    assert controller.snap() is True
    cam.send_trigger.assert_not_called()
    illum.turn_on_channel.assert_called_once()
    illum.turn_off_channel.assert_called_once()


def test_snap_timeout_returns_false_and_cleans_up():
    controller, _, cam, illum, _ = _make(frame=None)
    assert controller.snap() is False
    illum.turn_off_channel.assert_called_once()
    cam.stop_streaming.assert_called_once()
    assert controller.is_snapping is False


def test_snap_does_not_stop_streaming_it_did_not_start():
    controller, _, cam, _, _ = _make()
    cam.get_is_streaming.return_value = True
    assert controller.snap() is True
    cam.start_streaming.assert_not_called()
    cam.stop_streaming.assert_not_called()


def test_snap_is_noop_while_live():
    controller, bus, cam, _, _ = _make()
    bus.publish(StartLiveCommand(configuration="BF"))
    bus.drain()
    assert controller.is_live
    cam.send_trigger.reset_mock()
    assert controller.snap() is False
    cam.read_frame.assert_not_called()
    controller.stop_live()


def test_start_live_refused_while_snapping():
    controller, _, cam, _, _ = _make()
    controller._is_snapping = True
    controller.start_live()
    assert controller.is_live is False
    cam.start_streaming.assert_not_called()


def test_snap_publishes_state_events():
    controller, bus, _, _, _ = _make()
    events = []
    bus.subscribe(SnapStateChanged, events.append)
    controller.snap()
    bus.drain()
    assert [(e.is_snapping, e.success) for e in events] == [(True, None), (False, True)]


def test_snap_command_runs_snap_off_the_bus_thread():
    controller, bus, cam, _, _ = _make()
    events = []
    bus.subscribe(SnapStateChanged, events.append)
    bus.publish(SnapFrameCommand())
    bus.drain()
    for _ in range(200):
        bus.drain()
        if any(not e.is_snapping for e in events):
            break
        time.sleep(0.01)
    assert any(e.is_snapping is False and e.success for e in events)
    cam.read_frame.assert_called_once()

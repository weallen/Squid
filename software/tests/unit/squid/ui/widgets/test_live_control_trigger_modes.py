"""Continuous Acquisition is only offered when ENABLE_RECORDING is set (upstream #561)."""

from unittest.mock import MagicMock

import pytest

from _def import TriggerMode
from squid.core.events import SetTriggerModeCommand
import squid.ui.widgets.camera.live_control as live_control


class _Flags:
    def __init__(self, recording: bool):
        self._recording = recording

    def is_enabled(self, name: str) -> bool:
        return self._recording if name == "ENABLE_RECORDING" else False


def _make_widget(qtbot, monkeypatch, *, recording: bool, initial_mode: str):
    monkeypatch.setattr(live_control, "get_feature_flags", lambda: _Flags(recording))
    bus = MagicMock()
    config = MagicMock()
    config.name = "BF LED matrix full"
    config.exposure_time = 10.0
    config.analog_gain = 0.0
    config.illumination_intensity = 50.0
    widget = live_control.LiveControlWidget(
        bus,
        MagicMock(),
        config,
        "10x",
        ["BF LED matrix full"],
        initial_trigger_mode=initial_mode,
    )
    qtbot.addWidget(widget)
    return widget, bus


def _items(widget):
    combo = widget.dropdown_triggerManu
    return [combo.itemText(i) for i in range(combo.count())]


def test_continuous_hidden_without_recording(qtbot, monkeypatch):
    widget, _ = _make_widget(qtbot, monkeypatch, recording=False, initial_mode=TriggerMode.HARDWARE)
    assert _items(widget) == [TriggerMode.SOFTWARE, TriggerMode.HARDWARE]
    assert widget.dropdown_triggerManu.currentText() == TriggerMode.HARDWARE


def test_continuous_shown_with_recording(qtbot, monkeypatch):
    widget, _ = _make_widget(qtbot, monkeypatch, recording=True, initial_mode=TriggerMode.CONTINUOUS)
    assert TriggerMode.CONTINUOUS in _items(widget)
    assert widget.dropdown_triggerManu.currentText() == TriggerMode.CONTINUOUS


def test_hidden_initial_continuous_falls_back_to_software(qtbot, monkeypatch):
    widget, bus = _make_widget(qtbot, monkeypatch, recording=False, initial_mode=TriggerMode.CONTINUOUS)
    assert widget.dropdown_triggerManu.currentText() == TriggerMode.SOFTWARE
    published = [c.args[0] for c in bus.publish.call_args_list]
    assert SetTriggerModeCommand(mode=TriggerMode.SOFTWARE) in published

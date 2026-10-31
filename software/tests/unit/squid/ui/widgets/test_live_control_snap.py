"""Live/Snap buttons on the main live panel (upstream #616, #620)."""

from unittest.mock import MagicMock

from squid.core.events import LiveStateChanged, SnapFrameCommand, SnapStateChanged, StartLiveCommand
import squid.ui.widgets.camera.live_control as live_control


class _Flags:
    def is_enabled(self, name: str) -> bool:
        return False


def _make_widget(qtbot, monkeypatch):
    monkeypatch.setattr(live_control, "get_feature_flags", lambda: _Flags())
    bus = MagicMock()
    config = MagicMock()
    config.name = "BF LED matrix full"
    config.exposure_time = 10.0
    config.analog_gain = 0.0
    config.illumination_intensity = 50.0
    widget = live_control.LiveControlWidget(bus, MagicMock(), config, "10x", ["BF LED matrix full"])
    qtbot.addWidget(widget)
    return widget, bus


def _published(bus):
    return [c.args[0] for c in bus.publish.call_args_list]


def test_buttons_labelled_live_and_snap(qtbot, monkeypatch):
    widget, _ = _make_widget(qtbot, monkeypatch)
    assert widget.btn_live.text() == "Live"
    assert widget.btn_snap.text() == "Snap"
    assert widget.btn_snap.isEnabled()


def test_snap_publishes_command_and_disables_until_finished(qtbot, monkeypatch):
    widget, bus = _make_widget(qtbot, monkeypatch)
    widget.btn_snap.click()
    assert any(isinstance(e, SnapFrameCommand) for e in _published(bus))
    assert not widget.btn_snap.isEnabled()

    widget._on_snap_state_changed(SnapStateChanged(is_snapping=True))
    assert not widget.btn_live.isEnabled()
    widget._on_snap_state_changed(SnapStateChanged(is_snapping=False, success=True))
    assert widget.btn_snap.isEnabled()
    assert widget.btn_live.isEnabled()


def test_snap_disabled_while_live(qtbot, monkeypatch):
    widget, bus = _make_widget(qtbot, monkeypatch)
    widget._on_live_state_changed(LiveStateChanged(is_live=True))
    assert widget.btn_live.text() == "Stop"
    assert widget.btn_live.isChecked()
    assert not widget.btn_snap.isEnabled()

    bus.publish.reset_mock()
    widget.snap()
    assert not any(isinstance(e, SnapFrameCommand) for e in _published(bus))

    widget._on_live_state_changed(LiveStateChanged(is_live=False))
    assert widget.btn_live.text() == "Live"
    assert widget.btn_snap.isEnabled()


def test_live_and_snap_share_one_button_slot(qtbot, monkeypatch):
    widget, _ = _make_widget(qtbot, monkeypatch)
    row = widget.live_snap_row
    widest = max(widget.btn_live.sizeHint().width(), widget.btn_snap.sizeHint().width())
    assert row.sizeHint().width() == widest
    assert row.minimumSizeHint().width() == widest


def test_live_click_publishes_start(qtbot, monkeypatch):
    widget, bus = _make_widget(qtbot, monkeypatch)
    widget.btn_live.click()
    assert any(isinstance(e, StartLiveCommand) for e in _published(bus))

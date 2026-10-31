"""Laser AF live button shows backend-reported state, not the click (upstream #639)."""

from unittest.mock import MagicMock

from squid.core.config.models.laser_af_config import LaserAFConfig
from squid.core.events import LiveStateChanged
from squid.ui.widgets.hardware.laser_autofocus import LaserAutofocusSettingWidget


def test_laser_af_live_button_follows_live_state(qtbot):
    widget = LaserAutofocusSettingWidget(MagicMock(), MagicMock(), initial_properties=LaserAFConfig().model_dump())
    qtbot.addWidget(widget)

    widget.btn_live.click()  # start requested, not yet confirmed
    assert not widget.btn_live.isChecked()

    widget._on_live_state_changed(LiveStateChanged(is_live=True, camera="focus"))
    assert widget.btn_live.isChecked()

    widget.btn_live.click()  # stop requested, not yet confirmed
    assert widget.btn_live.isChecked()
    widget._on_live_state_changed(LiveStateChanged(is_live=False, camera="focus"))
    assert not widget.btn_live.isChecked()

"""Per-channel max output caps the applied illumination intensity (upstream edc13253, #610)."""

from unittest.mock import MagicMock

import pytest

from squid.backend.controllers.live_controller import LiveController
from squid.backend.controllers.microscope_mode_controller import MicroscopeModeController
from squid.core.events import MicroscopeModeChanged, SetMicroscopeModeCommand


def _controller(intensity: float, cap):
    c = LiveController.__new__(LiveController)
    c._log = MagicMock()
    c.currentConfiguration = MagicMock()
    c.currentConfiguration.illumination_intensity = intensity
    c._channel_config_service = MagicMock()
    c._channel_config_service.get_intensity_cap_percent.return_value = cap
    return c


def test_intensity_above_cap_is_clamped_with_warning():
    c = _controller(80.0, 20.0)
    assert c._get_illumination_intensity() == 20.0
    c._log.warning.assert_called_once()


def test_intensity_below_cap_is_unchanged():
    c = _controller(15.0, 20.0)
    assert c._get_illumination_intensity() == 15.0
    c._log.warning.assert_not_called()


@pytest.mark.parametrize("service", [None, "no-method"])
def test_no_cap_without_service(service):
    c = _controller(80.0, 20.0)
    c._channel_config_service = None if service is None else object()
    assert c._get_illumination_intensity() == 80.0


def test_update_illumination_applies_clamped_power():
    c = _controller(90.0, 25.0)
    c._illumination_service = MagicMock()
    c._nl5_service = None
    c._filter_wheel_service = None
    c.currentConfiguration.illumination_source = 11
    c.update_illumination()
    c._illumination_service.set_channel_power.assert_called_once_with(11, 25.0)


def test_mode_changed_event_carries_intensity_cap():
    bus = MagicMock()
    capped = MagicMock(spec=["exposure_time", "analog_gain", "illumination_intensity", "max_illumination_intensity"])
    capped.exposure_time, capped.analog_gain, capped.illumination_intensity = 10.0, 0.0, 15.0
    capped.max_illumination_intensity = 20.0
    uncapped = MagicMock(spec=["exposure_time", "analog_gain", "illumination_intensity"])
    uncapped.exposure_time, uncapped.analog_gain, uncapped.illumination_intensity = 10.0, 0.0, 15.0
    controller = MicroscopeModeController(MagicMock(), {"BF": capped, "GFP": uncapped}, bus)

    controller._on_set_mode(SetMicroscopeModeCommand(configuration_name="BF", objective=None))
    controller._on_set_mode(SetMicroscopeModeCommand(configuration_name="GFP", objective=None))
    received = [c.args[0] for c in bus.publish.call_args_list if isinstance(c.args[0], MicroscopeModeChanged)]
    assert [e.max_illumination_intensity for e in received] == [20.0, None]


def test_channel_config_edits_refresh_mode_controller_configs():
    """After a config dialog save, the mode controller must pick up fresh configs (e.g. a new max output)."""
    from types import SimpleNamespace

    from squid.application import ApplicationContext
    from squid.core.events import ChannelConfigurationsChanged

    mode_controller = MagicMock()
    fake = SimpleNamespace(
        _controllers=SimpleNamespace(microscope_mode=mode_controller),
        _refresh_channel_configs=MagicMock(),
    )
    ApplicationContext._on_channel_configurations_changed(
        fake, ChannelConfigurationsChanged(objective_name="10x", configuration_names=["BF"])
    )
    fake._refresh_channel_configs.assert_called_once_with(mode_controller)

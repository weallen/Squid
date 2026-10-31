"""Live control intensity slider/spinbox are capped at the channel's max output (upstream edc13253, #610)."""

from unittest.mock import MagicMock

from squid.core.events import MicroscopeModeChanged, UpdateChannelConfigurationCommand
import squid.ui.widgets.camera.live_control as live_control


def _make_widget(qtbot):
    bus = MagicMock()
    config = MagicMock()
    config.name = "BF LED matrix full"
    config.exposure_time = 10.0
    config.analog_gain = 0.0
    config.illumination_intensity = 50.0
    widget = live_control.LiveControlWidget(bus, MagicMock(), config, "10x", ["BF LED matrix full", "GFP"])
    qtbot.addWidget(widget)
    return widget, bus


def test_mode_change_caps_intensity_controls_and_restores_full_range(qtbot):
    widget, bus = _make_widget(qtbot)
    bus.publish.reset_mock()

    widget._on_microscope_mode_changed(
        MicroscopeModeChanged(
            configuration_name="BF LED matrix full", illumination_intensity=15.0, max_illumination_intensity=20.0
        )
    )
    assert widget.slider_illuminationIntensity.maximum() == 20
    assert widget.entry_illuminationIntensity.maximum() == 20.0
    assert widget.entry_illuminationIntensity.value() == 15.0

    widget._on_microscope_mode_changed(MicroscopeModeChanged(configuration_name="GFP", illumination_intensity=80.0))
    assert widget.slider_illuminationIntensity.maximum() == 100
    assert widget.entry_illuminationIntensity.maximum() == 100.0
    assert widget.entry_illuminationIntensity.value() == 80.0


def test_narrowing_the_range_does_not_publish_a_config_edit(qtbot):
    widget, bus = _make_widget(qtbot)
    widget._on_microscope_mode_changed(MicroscopeModeChanged(configuration_name="GFP", illumination_intensity=80.0))
    bus.publish.reset_mock()

    # Saved intensity above the cap (e.g. set before the cap existed): the controls clamp, nothing is persisted
    widget._on_microscope_mode_changed(
        MicroscopeModeChanged(configuration_name="BF LED matrix full", max_illumination_intensity=20.0)
    )
    assert widget.entry_illuminationIntensity.value() == 20.0
    published = [c.args[0] for c in bus.publish.call_args_list]
    assert not any(isinstance(e, UpdateChannelConfigurationCommand) for e in published)

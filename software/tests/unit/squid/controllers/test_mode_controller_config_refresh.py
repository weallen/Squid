"""The ChannelConfigurationsChanged -> mode-controller refresh is an in-memory swap.

It runs on every intensity-slider tick and confocal toggle, so it must not re-read YAML from
disk, republish MicroscopeModeChanged, or touch hardware.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from squid.application import ApplicationContext
from squid.backend.controllers.microscope_mode_controller import MicroscopeModeController
from squid.backend.managers.channel_config_service import ChannelConfigService
from squid.core.config.models.acquisition_config import (
    AcquisitionChannel,
    CameraSettings,
    GeneralChannelConfig,
    IlluminationSettings,
)
from squid.core.config.models.illumination_config import (
    IlluminationChannel,
    IlluminationChannelConfig,
    IlluminationType,
)
from squid.core.config.repository import ConfigRepository
from squid.core.events import ChannelConfigurationsChanged, UpdateChannelConfigurationCommand


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "machine_configs").mkdir()
    (tmp_path / "user_profiles").mkdir()
    repo = ConfigRepository(base_path=tmp_path)
    repo.save_illumination_config(
        IlluminationChannelConfig(
            controller_port_mapping={"USB1": 0},
            channels=[
                IlluminationChannel(
                    name="BF", type=IlluminationType.TRANSILLUMINATION, controller_port="USB1", max_output=0.2
                )
            ],
        )
    )
    repo.create_profile("default")
    repo.set_profile("default")
    repo.save_general_config(
        "default",
        GeneralChannelConfig(
            channels=[
                AcquisitionChannel(
                    name="BF LED matrix full",
                    camera_settings=CameraSettings(exposure_time_ms=10.0, gain_mode=0.0),
                    illumination_settings=IlluminationSettings(illumination_channel="BF", intensity=10.0),
                )
            ]
        ),
    )
    service = ChannelConfigService(repo, MagicMock())
    camera, illumination, filter_wheel, bus = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    fake_app = SimpleNamespace(
        _microscope=SimpleNamespace(
            channel_config_service=service, objective_store=SimpleNamespace(current_objective="10x")
        ),
    )
    fake_app._get_channel_configs_for_current_objective = (
        lambda: ApplicationContext._get_channel_configs_for_current_objective(fake_app)
    )
    fake_app._refresh_channel_configs = lambda c: ApplicationContext._refresh_channel_configs(fake_app, c)
    controller = MicroscopeModeController(
        camera, fake_app._get_channel_configs_for_current_objective(), bus, filter_wheel, illumination
    )
    fake_app._controllers = SimpleNamespace(microscope_mode=controller)
    return SimpleNamespace(
        repo=repo,
        service=service,
        app=fake_app,
        controller=controller,
        hw=(camera, illumination, filter_wheel),
        bus=bus,
    )


def test_slider_tick_refresh_is_in_memory_and_hardware_free(setup, monkeypatch):
    loads = []
    original_load = setup.repo._load_yaml
    monkeypatch.setattr(setup.repo, "_load_yaml", lambda *a, **k: loads.append(a) or original_load(*a, **k))
    for mock in (*setup.hw, setup.bus):
        mock.reset_mock()

    # One slider tick: the service persists the value, then the refresh runs on ChannelConfigurationsChanged
    setup.service._on_update_configuration_command(
        UpdateChannelConfigurationCommand(
            objective_name="10x", config_name="BF LED matrix full", illumination_intensity=15.0
        )
    )
    ApplicationContext._on_channel_configurations_changed(
        setup.app, ChannelConfigurationsChanged(objective_name="10x", configuration_names=["BF LED matrix full"])
    )

    assert loads == []  # nothing re-read from disk
    for mock in (*setup.hw, setup.bus):
        assert mock.method_calls == []  # no hardware calls, no MicroscopeModeChanged republish
    refreshed = setup.controller._channel_configs["BF LED matrix full"]
    assert refreshed.illumination_intensity == 15.0
    assert refreshed.max_illumination_intensity == pytest.approx(20.0)


def test_refresh_after_max_output_edit_updates_the_cap(setup):
    edited = setup.repo.get_illumination_config(for_edit=True)
    edited.channels[0].max_output = 0.5
    setup.repo.save_illumination_config(edited)

    ApplicationContext._on_channel_configurations_changed(
        setup.app, ChannelConfigurationsChanged(objective_name="10x", configuration_names=["BF LED matrix full"])
    )
    assert setup.controller._channel_configs["BF LED matrix full"].max_illumination_intensity == pytest.approx(50.0)

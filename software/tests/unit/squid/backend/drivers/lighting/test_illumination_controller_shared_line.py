"""IlluminationController: shared software lines and idempotent close (generic parts of upstream #709)."""

from unittest.mock import MagicMock

import pytest

from squid.backend.drivers.lighting.led import (
    IlluminationController,
    IntensityControlMode,
    LightSourceType,
    ShutterControlMode,
)


class FakeLineLightSource:
    """Software-intensity light source where 470/488 share line 2 (like CELESTA, LDI and Andor)."""

    def __init__(self):
        self.channel_mappings = {405: 0, 470: 2, 488: 2, 730: None}
        self.line_power = {0: 0.0, 2: 0.0}
        self.calls = []
        self.shut_downs = 0

    def initialize(self):
        return True

    def set_intensity_control_mode(self, mode):
        pass

    def set_shutter_control_mode(self, mode):
        pass

    def get_intensity(self, line):
        return self.line_power.get(line, 0)

    def set_intensity(self, line, intensity):
        self.calls.append((line, intensity))
        if line is not None:
            self.line_power[line] = intensity

    def get_shutter_state(self, line):
        return False

    def shut_down(self):
        self.shut_downs += 1


@pytest.fixture
def controller_and_source():
    source = FakeLineLightSource()
    controller = IlluminationController(
        MagicMock(), IntensityControlMode.Software, ShutterControlMode.Software, LightSourceType.CELESTA, source
    )
    return controller, source


def test_switching_between_channels_on_one_line_sets_each_channels_power(controller_and_source):
    controller, source = controller_and_source

    controller.set_intensity(470, 20)
    controller.set_intensity(488, 50)
    controller.set_intensity(470, 20)

    assert source.line_power[2] == 20
    assert source.calls == [(2, 20), (2, 50), (2, 20)]


def test_unchanged_power_on_separate_lines_is_not_resent(controller_and_source):
    controller, source = controller_and_source

    controller.set_intensity(405, 30)
    controller.set_intensity(488, 50)
    controller.set_intensity(405, 30)
    controller.set_intensity(488, 50)

    assert source.calls == [(0, 30), (2, 50)]


def test_unmapped_channels_do_not_share_a_cache(controller_and_source):
    controller, source = controller_and_source

    controller.set_intensity(730, 40)

    assert controller.intensity_settings[730] == 40
    assert controller.intensity_settings[405] == 0  # 405 is mapped, so a None line must not touch it


def test_close_shuts_the_light_source_down_once(controller_and_source):
    controller, source = controller_and_source

    controller.close()
    controller.close()

    assert source.shut_downs == 1


def test_close_without_light_source_is_a_no_op():
    IlluminationController(MagicMock()).close()

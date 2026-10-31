"""Laser AF Initialize must use the machine config (.ini) crop sizes, not the ones a saved profile carries.

Ported (adapted) from upstream 2a550c86 (#674) with the d25a1b73 (#676) follow-up: the ROI height is tall enough
for spot detection's y window, and not the saved 256.
"""

import numpy as np

import _def
from squid.core.config.models import LaserAFConfig
from squid.core.events import EventBus
from squid.backend.controllers.autofocus.laser_auto_focus_controller import (
    LaserAutofocusController,
    LaserSpotCentroid,
)


class _Camera:
    def __init__(self) -> None:
        self.rois = []

    def set_region_of_interest(self, x: int, y: int, width: int, height: int) -> None:
        self.rois.append((x, y, width, height))

    def set_exposure_time(self, _ms: float) -> None:
        pass

    def set_analog_gain(self, _gain: float) -> None:
        pass


class _Peripheral:
    def turn_on_af_laser(self, wait_for_completion: bool = True) -> None:  # noqa: ARG002
        pass

    def turn_off_af_laser(self, wait_for_completion: bool = True) -> None:  # noqa: ARG002
        pass


class _Objectives:
    current_objective = "20x"


class _Settings:
    def __init__(self) -> None:
        self.saved = []

    def update_laser_af_settings(self, objective, updates, crop_image=None) -> None:  # noqa: ARG002
        pass

    def save_configurations(self, objective) -> None:
        self.saved.append(objective)

    def get_laser_af_settings(self) -> dict:
        return {}


def test_initialize_takes_the_crop_sizes_from_the_machine_config(monkeypatch):
    monkeypatch.setattr(_def, "LASER_AF_CROP_WIDTH", 1024)
    # tall enough for spot detection's y window (96 rows either side of the spot), and not the saved 256
    monkeypatch.setattr(_def, "LASER_AF_CROP_HEIGHT", 224)
    monkeypatch.setattr(_def, "LASER_AF_INITIALIZE_CROP_WIDTH", 2800)
    monkeypatch.setattr(_def, "LASER_AF_INITIALIZE_CROP_HEIGHT", 1800)

    camera = _Camera()
    controller = LaserAutofocusController(
        camera_service=camera,
        stage_service=object(),
        peripheral_service=_Peripheral(),
        event_bus=EventBus(),
        objectiveStore=_Objectives(),
        laserAFSettingManager=_Settings(),
    )
    # A loaded per-objective profile, saved with the old sizes.
    controller.laser_af_properties = LaserAFConfig(
        width=1536, height=256, initialize_crop_width=1200, initialize_crop_height=800
    )

    crops = []

    def fake_centroid(remove_background=False, use_center_crop=None):  # noqa: ARG001
        crops.append(use_center_crop)
        return LaserSpotCentroid(x_px=604.0, y_px=401.0, image=np.zeros((4, 4), dtype=np.uint8))

    monkeypatch.setattr(controller, "_get_laser_spot_centroid", fake_centroid)
    monkeypatch.setattr(controller, "_calibrate_pixel_to_um", lambda: True)

    assert controller.initialize_auto()

    assert crops == [(2800, 1800)]  # the search area is the .ini one
    assert camera.rois[-1] == (88, 288, 1024, 224)  # ROI around the spot, with the .ini size
    assert (controller.laser_af_properties.width, controller.laser_af_properties.height) == (1024, 224)

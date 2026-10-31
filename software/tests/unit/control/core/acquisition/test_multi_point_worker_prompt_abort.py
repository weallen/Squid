"""An abort stops a z-stack / channel loop at once and Z returns to the stack start (port of upstream 70f2afdd)."""

import dataclasses
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import _def

# Avoid spawning JobRunner processes in tests
_def.Acquisition.USE_MULTIPROCESSING = False

from squid.backend.controllers.multipoint.fov_task import FovStatus, FovTask, FovTaskList
from squid.backend.controllers.multipoint.multi_point_worker import MultiPointWorker
from squid.core.config.models import AcquisitionChannel, CameraSettings, IlluminationSettings
from squid.core.events import EventBus

from tests.unit.control.core.acquisition.test_multi_point_worker_services import _make_params

NZ = 5
DELTA_Z_UM = 1.5
START_UM = 100.0


class _FakePiezo:
    def __init__(self, position_um: float) -> None:
        self.position_um = position_um
        self.history = [position_um]

    def get_position(self) -> float:
        return self.position_um

    def move_to(self, position_um: float) -> None:
        self.position_um = position_um
        self.history.append(position_um)

    def move_relative(self, delta_um: float) -> None:
        self.move_to(self.position_um + delta_um)


def _channel(name: str) -> AcquisitionChannel:
    return AcquisitionChannel(
        name=name,
        camera_settings=CameraSettings(exposure_time_ms=10.0, gain_mode=1.0),
        illumination_settings=IlluminationSettings(illumination_channel="LED", intensity=50.0),
    )


def _make_worker(order: str, stacking: str, use_piezo: bool):
    params = dataclasses.replace(
        _make_params(),
        NZ=NZ,
        deltaZ=DELTA_Z_UM,
        use_piezo=use_piezo,
        z_stacking_config=stacking,
        acquisition_order=order,
        selected_configurations=[_channel("Fluorescence 488 nm Ex"), _channel("Fluorescence 561 nm Ex")],
    )
    camera_service = MagicMock()
    camera_service.get_pixel_size_binned_um.return_value = 1.0
    camera_service.get_total_frame_time.return_value = 10.0
    stage_service = MagicMock()
    stage_service.get_position.return_value = SimpleNamespace(x_mm=0.0, y_mm=0.0, z_mm=0.0)
    piezo = _FakePiezo(START_UM)
    worker = MultiPointWorker(
        auto_focus_controller=None,
        laser_auto_focus_controller=None,
        objective_store=SimpleNamespace(current_objective="10x", get_pixel_size_factor=lambda: None),
        channel_configuration_mananger=MagicMock(),
        acquisition_parameters=params,
        camera_service=camera_service,
        stage_service=stage_service,
        peripheral_service=MagicMock(),
        piezo_service=piezo,
        event_bus=EventBus(),
    )
    worker._zstack_executor._piezo_delay_s = 0.0
    worker.perform_autofocus = MagicMock(return_value=True)
    worker.update_coordinates_dataframe = MagicMock()
    worker.handle_acquisition_abort = MagicMock()
    if not use_piezo:
        worker.initialize_z_stack()  # run_single_time_point does this once per time point
    return worker, piezo


def _install_fake_capture(worker, piezo, abort_after):
    images = []

    def _capture(config, file_ID, current_path, k, **_kwargs):
        images.append((config.name, k, piezo.position_um))
        if abort_after is not None and len(images) >= abort_after:
            worker.request_abort()

    worker.acquire_camera_image = _capture
    return images


@pytest.mark.parametrize("use_piezo", [True, False])
@pytest.mark.parametrize("stacking", ["FROM BOTTOM", "FROM CENTER"])
@pytest.mark.parametrize("order", ["channel_first", "z_first"])
@pytest.mark.parametrize("abort_after", [1, 3, 7, NZ * 2, None])
def test_abort_stops_at_once_and_z_returns_to_start(order, stacking, use_piezo, abort_after):
    worker, piezo = _make_worker(order, stacking, use_piezo)
    images = _install_fake_capture(worker, piezo, abort_after)

    worker.acquire_at_position("A1", "/nonexistent", 0)

    total = NZ * 2
    expected = total if abort_after is None else min(abort_after, total)
    assert len(images) == expected  # no image after the abort
    assert piezo.position_um == pytest.approx(START_UM)  # Z back where the stack started
    assert worker._last_position_complete is (abort_after is None or abort_after >= total)
    # The abort is handled once, by run_coordinate_acquisition, not inside the loops.
    worker.handle_acquisition_abort.assert_not_called()
    # No plane is ever visited outside the stack.
    lowest = START_UM - DELTA_Z_UM * round((NZ - 1) / 2) if stacking == "FROM CENTER" and use_piezo else START_UM
    assert min(piezo.history) >= lowest - 1e-9
    assert max(piezo.history) <= lowest + DELTA_Z_UM * (NZ - 1) + 1e-9


def test_full_stack_order_and_planes():
    worker, piezo = _make_worker("channel_first", "FROM BOTTOM", True)
    images = _install_fake_capture(worker, piezo, None)
    worker.acquire_at_position("A1", "/nonexistent", 0)
    assert [k for _, k, _ in images] == [k for k in range(NZ) for _ in range(2)]
    assert [z for _, _, z in images[::2]] == pytest.approx([START_UM + DELTA_Z_UM * k for k in range(NZ)])
    assert worker._zstack_executor.steps_taken == 0  # reset by return_to_start


def test_aborted_position_is_not_marked_completed(tmp_path):
    worker, piezo = _make_worker("channel_first", "FROM BOTTOM", True)
    _install_fake_capture(worker, piezo, 3)
    worker.move_to_coordinate = MagicMock()
    worker._save_checkpoint = MagicMock()
    worker._summarize_runner_outputs = MagicMock()
    task = FovTask(fov_id="A1_0000", region_id="A1", fov_index=0, x_mm=0.0, y_mm=0.0, z_mm=0.0)
    worker._fov_task_list = FovTaskList(tasks=[task])
    worker.scan_region_fov_coords_mm = {"A1": [(0.0, 0.0, 0.0)]}

    worker.run_coordinate_acquisition(str(tmp_path))

    assert task.status == FovStatus.FAILED
    worker.handle_acquisition_abort.assert_called_once()

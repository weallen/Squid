"""The channel order chosen in the multipoint widgets reaches the worker unchanged (upstream #557)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from squid.core.events import AcquisitionWorkerFinished, EventBus, SetAcquisitionChannelsCommand
from squid.backend.controllers.multipoint import multi_point_controller
from squid.backend.controllers.multipoint.multi_point_controller import MultiPointController

from tests.unit.control.core.test_multi_point_controller_gen_focus_map import (
    _FakeAutoFocusController,
    _FakeCameraService,
    _FakeGlobalScanCoordinates,
    _FakeLiveController,
    _FakeObjectiveStore,
    _FakePeripheralService,
    _FakeStageService,
)


class _NamedChannelManager:
    def get_channel_configuration_by_name(self, _objective, name):
        return SimpleNamespace(name=name)

    def write_configuration_selected(self, *_args, **_kwargs) -> None:
        return None


def test_selected_channel_order_reaches_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list = []

    class _CapturingWorker:
        def __init__(self, *, acquisition_parameters, event_bus, **_kwargs) -> None:
            self._event_bus = event_bus
            self._params = acquisition_parameters
            captured.append(acquisition_parameters)

        def run(self) -> None:
            self._event_bus.publish(
                AcquisitionWorkerFinished(experiment_id=self._params.experiment_ID, success=True, final_fov_count=0)
            )

    monkeypatch.setattr(multi_point_controller, "MultiPointWorker", _CapturingWorker)

    bus = EventBus()
    bus.start()
    try:
        scan = _FakeGlobalScanCoordinates()
        scan.region_centers = {"A1": [1.0, 1.0]}
        scan.region_fov_coordinates = {"A1": [(1.0, 1.0)]}
        controller = MultiPointController(
            live_controller=_FakeLiveController(),
            autofocus_controller=_FakeAutoFocusController(),
            objective_store=_FakeObjectiveStore(),
            channel_configuration_manager=_NamedChannelManager(),
            camera_service=_FakeCameraService(),
            stage_service=_FakeStageService(),
            peripheral_service=_FakePeripheralService(),
            event_bus=bus,
            scan_coordinates=scan,
        )
        controller.set_base_path(str(tmp_path))
        controller.start_new_experiment("unit_test")

        order = ["Fluorescence 561 nm Ex", "BF LED matrix full", "Fluorescence 405 nm Ex"]
        bus.publish(SetAcquisitionChannelsCommand(channel_names=order))
        bus.drain(timeout_s=1.0)

        controller.run_acquisition()
        bus.drain(timeout_s=1.0)
        if controller.thread:
            controller.thread.join(timeout=1.0)

        assert captured, "worker was never constructed"
        assert [c.name for c in captured[0].selected_configurations] == order
    finally:
        bus.stop()

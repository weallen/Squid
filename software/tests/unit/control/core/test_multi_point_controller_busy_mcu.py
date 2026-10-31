"""Acquisition start survives a busy MCU (upstream #639).

After live is stopped, run_acquisition waits up to _MCU_IDLE_WAIT_S for the microcontroller to go
idle before the worker moves the stage, and aborts cleanly if it stays busy.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from squid.backend.controllers.multipoint import multi_point_controller
from squid.backend.controllers.multipoint.multi_point_controller import MultiPointController
from squid.core.events import EventBus
from tests.unit.control.core.test_multi_point_controller_cleanup import (
    _FakeAutoFocusController,
    _FakeCameraService,
    _FakeChannelConfigurationManager,
    _FakeLiveController,
    _FakeObjectiveStore,
    _FakeScanCoordinates,
    _FakeScanPositionInformation,
    _FakeStageService,
    _ImmediateWorker,
)


class _BusyPeripheralService:
    """Busy until wait_till_operation_is_completed is called; then idle unless ``stays_busy``."""

    def __init__(self, stays_busy: bool) -> None:
        self._busy = True
        self._stays_busy = stays_busy
        self.wait_timeouts: list[float] = []

    def is_mcu_busy(self) -> bool:
        return self._busy

    def wait_till_operation_is_completed(self, timeout_s: float = 10.0) -> None:
        self.wait_timeouts.append(timeout_s)
        if self._stays_busy:
            raise TimeoutError("still busy")
        self._busy = False


class _RecordingStageService(_FakeStageService):
    def __init__(self) -> None:
        super().__init__()
        self.moves = 0

    def move_x_to(self, x_mm: float) -> None:
        self.moves += 1
        super().move_x_to(x_mm)

    def move_y_to(self, y_mm: float) -> None:
        self.moves += 1
        super().move_y_to(y_mm)


def _build(tmp_path: Path, monkeypatch, bus: EventBus, peripheral, stage, live) -> MultiPointController:
    monkeypatch.setattr(multi_point_controller, "MultiPointWorker", _ImmediateWorker)
    monkeypatch.setattr(
        multi_point_controller.ScanPositionInformation,
        "from_scan_coordinates",
        lambda _scan: _FakeScanPositionInformation(),
    )
    monkeypatch.setattr(multi_point_controller, "save_acquisition_yaml", lambda **_kwargs: None)
    monkeypatch.setattr(
        multi_point_controller.AcquisitionDependencies,
        "create",
        staticmethod(lambda **_kwargs: object()),
    )
    controller = MultiPointController(
        live_controller=live,
        autofocus_controller=_FakeAutoFocusController(),
        objective_store=_FakeObjectiveStore(),
        channel_configuration_manager=_FakeChannelConfigurationManager(),
        camera_service=_FakeCameraService(),
        stage_service=stage,
        peripheral_service=peripheral,
        event_bus=bus,
        scan_coordinates=_FakeScanCoordinates(),
    )
    controller.set_base_path(str(tmp_path))
    controller.experiment_ID = "round_000"
    (tmp_path / controller.experiment_ID).mkdir()
    return controller


def _wait_idle(controller: MultiPointController, bus: EventBus) -> None:
    deadline = time.time() + 1.0
    while controller.state.name != "IDLE" and time.time() < deadline:
        bus.drain(timeout_s=0.05)
        threading.Event().wait(0.01)
    if controller.thread is not None:
        controller.thread.join(timeout=1.0)
    bus.drain(timeout_s=0.1)


def test_acquisition_waits_out_a_busy_mcu_after_stopping_live(tmp_path: Path, monkeypatch) -> None:
    bus = EventBus()
    bus.start()
    try:
        peripheral = _BusyPeripheralService(stays_busy=False)
        live = _FakeLiveController()
        live.is_live = True
        controller = _build(tmp_path, monkeypatch, bus, peripheral, _RecordingStageService(), live)

        assert controller.run_acquisition() is True
        assert live.is_live is False
        assert peripheral.wait_timeouts == [MultiPointController._MCU_IDLE_WAIT_S]
        _wait_idle(controller, bus)
        assert (tmp_path / controller.experiment_ID / ".done").exists()
    finally:
        bus.stop()


def test_acquisition_start_aborts_cleanly_when_mcu_stays_busy(tmp_path: Path, monkeypatch) -> None:
    bus = EventBus()
    bus.start()
    try:
        peripheral = _BusyPeripheralService(stays_busy=True)
        stage = _RecordingStageService()
        controller = _build(tmp_path, monkeypatch, bus, peripheral, stage, _FakeLiveController())

        assert controller.run_acquisition() is False
        assert controller.state.name == "IDLE"
        assert controller.thread is None or not controller.thread.is_alive()
        assert stage.moves == 0  # no restore moves sent into a wedged MCU
    finally:
        bus.stop()


def test_idle_mcu_does_not_wait(tmp_path: Path, monkeypatch) -> None:
    bus = EventBus()
    bus.start()
    try:
        peripheral = _BusyPeripheralService(stays_busy=False)
        peripheral._busy = False
        controller = _build(tmp_path, monkeypatch, bus, peripheral, _RecordingStageService(), _FakeLiveController())
        assert controller.run_acquisition() is True
        assert peripheral.wait_timeouts == []
        _wait_idle(controller, bus)
    finally:
        bus.stop()

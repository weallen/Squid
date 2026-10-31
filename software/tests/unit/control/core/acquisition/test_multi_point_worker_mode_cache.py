"""MultiPointWorker skips re-applying an unchanged channel mode within one position (port of upstream 55236d92)."""

from unittest.mock import MagicMock

import pytest

import _def
from _def import TriggerMode

# Avoid spawning JobRunner processes in tests
_def.Acquisition.USE_MULTIPROCESSING = False

from squid.core.config.models import AcquisitionChannel, CameraSettings, IlluminationSettings
from squid.core.events import (
    ExposureTimeChanged,
    FilterPositionChanged,
    IlluminationStateChanged,
    MicroscopeModeChanged,
    SetExposureTimeCommand,
    SetIlluminationCommand,
    UpdateChannelConfigurationCommand,
)

from tests.unit.control.core.acquisition.test_multi_point_worker_services import _make_worker


def _channel(name: str, exposure: float = 10.0, intensity: float = 50.0) -> AcquisitionChannel:
    return AcquisitionChannel(
        name=name,
        camera_settings=CameraSettings(exposure_time_ms=exposure, gain_mode=1.0),
        illumination_settings=IlluminationSettings(illumination_channel="LED", intensity=intensity),
    )


@pytest.fixture
def worker():
    w = _make_worker()
    w._trigger_mode = TriggerMode.HARDWARE
    w.frame_wait_timeout_override_s = 0.01
    w._camera_service.get_total_frame_time.return_value = 0.0
    w._camera_service.get_ready_for_trigger.return_value = True
    w._apply_channel_mode = MagicMock()
    return w


def _acquire(worker, config: AcquisitionChannel, k: int = 0) -> None:
    worker._ready_for_next_trigger.set()
    worker.acquire_camera_image(config, "id", "/nonexistent", k, region_id="A1", fov=0, config_idx=0)


def test_unchanged_channel_applied_once_per_position(worker):
    config = _channel("Fluorescence 488 nm Ex")
    for k in range(4):
        _acquire(worker, config, k)
    assert worker._apply_channel_mode.call_count == 1
    assert worker._camera_service.send_trigger.call_count == 4


def test_alternating_channels_applied_every_image(worker):
    a, b = _channel("Fluorescence 488 nm Ex"), _channel("Fluorescence 561 nm Ex")
    for config in (a, b, a, b):
        _acquire(worker, config)
    assert worker._apply_channel_mode.call_count == 4


def test_config_already_applied_false_cases(worker):
    config = _channel("Fluorescence 488 nm Ex")
    assert not worker._config_already_applied(config)  # nothing applied yet

    worker._select_config(config)
    assert worker._config_already_applied(config)

    worker._select_config(_channel("Fluorescence 561 nm Ex"))
    assert not worker._config_already_applied(config)  # another channel was set

    worker._select_config(config)
    config.exposure_time = 99.0  # edited in place mid-run
    assert not worker._config_already_applied(config)


def test_new_position_clears_applied_config(worker):
    config = _channel("Fluorescence 488 nm Ex")
    worker._select_config(config)
    seen = {}
    worker.perform_autofocus = MagicMock(side_effect=lambda *a: seen.setdefault("af", worker._applied_config) or True)
    worker._acquire_channel_first = MagicMock(
        side_effect=lambda *a, **k: seen.setdefault("acq", worker._applied_config)
    )
    worker.acquire_at_position("A1", "/nonexistent", 0)
    assert seen["af"] is None
    assert seen["acq"] is None


def test_applied_config_cleared_after_autofocus_applies_its_own_mode(worker):
    af_config = _channel("BF LED matrix full")
    seen = {}

    def _af(*_a):
        worker._select_config(af_config)  # e.g. contrast AF via the apply-config callback
        return True

    worker.perform_autofocus = MagicMock(side_effect=_af)
    worker._acquire_channel_first = MagicMock(
        side_effect=lambda *a, **k: seen.setdefault("acq", worker._applied_config)
    )
    worker.acquire_at_position("A1", "/nonexistent", 0)
    assert seen["acq"] is None


def test_z_offset_invalidates(worker):
    config = _channel("Fluorescence 488 nm Ex")
    worker._select_config(config)
    worker._piezo_service = MagicMock()
    offset_config = config.model_copy(deep=True)
    offset_config.z_offset_um = 2.0
    worker.handle_z_offset(offset_config, True)
    assert worker._applied_config is None


@pytest.mark.parametrize(
    "event",
    [
        SetExposureTimeCommand(exposure_time_ms=10.0),
        SetIlluminationCommand(channel=0, intensity=50.0, on=True),
        IlluminationStateChanged(channel=0, intensity=50.0, on=True),
        MicroscopeModeChanged(configuration_name="Fluorescence 561 nm Ex"),
        UpdateChannelConfigurationCommand(objective_name="10x", config_name="x", exposure_time_ms=5.0),
        ExposureTimeChanged(exposure_time_ms=123.0),
    ],
)
def test_out_of_band_events_invalidate(worker, event):
    config = _channel("Fluorescence 488 nm Ex")
    worker._subscribe_config_cache_invalidation()
    try:
        worker._select_config(config)
        worker._event_bus.publish(event)
        worker._event_bus.drain()
        assert worker._applied_config is None
    finally:
        worker._unsubscribe_config_cache_invalidation()


@pytest.mark.parametrize(
    "event",
    [ExposureTimeChanged(exposure_time_ms=10.0), FilterPositionChanged(position=None)],  # echoes of our own apply
)
def test_echo_of_own_apply_does_not_invalidate(worker, event):
    config = _channel("Fluorescence 488 nm Ex")
    worker._subscribe_config_cache_invalidation()
    try:
        worker._select_config(config)
        worker._event_bus.publish(event)
        worker._event_bus.drain()
        assert worker._config_already_applied(config)
    finally:
        worker._unsubscribe_config_cache_invalidation()


def test_unsubscribe_removes_handlers(worker):
    config = _channel("Fluorescence 488 nm Ex")
    worker._subscribe_config_cache_invalidation()
    worker._unsubscribe_config_cache_invalidation()
    worker._select_config(config)
    worker._event_bus.publish(SetExposureTimeCommand(exposure_time_ms=10.0))
    worker._event_bus.drain()
    assert worker._config_already_applied(config)

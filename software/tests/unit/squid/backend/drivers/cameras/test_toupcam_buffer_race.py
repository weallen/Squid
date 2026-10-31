"""Regression tests for the ToupcamCamera internal-read-buffer realloc race (upstream #585).

``_update_internal_settings`` runs on the acquisition thread on every ``set_exposure_time`` (i.e. every
channel switch) and used to replace ``self._internal_read_buffer`` with a fresh zero-filled buffer.
``_on_frame_callback`` read that attribute twice (``PullImageV2`` fills it, then ``np.frombuffer``
re-reads it), so a swap landing between the two reads produced an entirely zero frame.
"""

import threading
from typing import List

import numpy as np
import pytest

import squid.core.logging
import squid.backend.drivers.cameras.toupcam as camera_toupcam
from squid.core.abc import CameraAcquisitionMode, CameraFrameFormat
from squid.core.config import CameraConfig, CameraPixelFormat, CameraVariant

_W, _H = 8, 4
_ITEMSIZE = 2  # uint16
_SIZE = _W * _H * _ITEMSIZE
_FILL_BYTE = 0xAB  # a filled frame is never all-zero
_FILL_PIXEL = int.from_bytes(bytes([_FILL_BYTE]) * _ITEMSIZE, "little")


class _TrackingLock:
    """A lock that records how many times it has been entered."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enter_count = 0

    def __enter__(self):
        self._lock.acquire()
        self.enter_count += 1
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


def _make_camera(roi=(0, 0, _W, _H)) -> camera_toupcam.ToupcamCamera:
    """Build a minimal ToupcamCamera with only the hardware boundary faked (``__init__`` is skipped)."""
    cam = object.__new__(camera_toupcam.ToupcamCamera)
    cam._raw_frame_callback_lock = threading.Lock()
    cam._internal_read_buffer = bytes([_FILL_BYTE]) * _SIZE  # a "filled" frame
    cam._current_frame = None
    cam._trigger_sent = True
    cam._raw_camera_stream_started = False
    cam._config = CameraConfig(camera_type=CameraVariant.TOUPCAM, default_pixel_format=CameraPixelFormat.MONO16)
    cam._log = squid.core.logging.get_logger("test_toupcam_buffer_race")
    cam._get_pixel_size_in_bytes = lambda: _ITEMSIZE
    cam.get_frame_format = lambda: CameraFrameFormat.RAW
    cam.get_pixel_format = lambda: CameraPixelFormat.MONO16
    cam.get_region_of_interest = lambda: roi
    cam.get_binning = lambda: (1, 1)
    return cam


@pytest.mark.parametrize("reassign_buffer_during_pull", [False, True], ids=["no_realloc", "realloc_during_pull"])
def test_callback_frame_not_zeroed_by_concurrent_buffer_realloc(reassign_buffer_during_pull: bool) -> None:
    """The delivered frame must be the buffer PullImageV2 filled, realloc or not."""
    cam = _make_camera()

    class _FakeSDK:
        def PullImageV2(self, buffer, bits, info):
            # The real PullImageV2 fills `buffer`; ours leaves the pre-filled sentinel in place and
            # instead models the acquisition thread's realloc landing mid-pull.
            if reassign_buffer_during_pull:
                cam._internal_read_buffer = bytes(_SIZE)

    cam._camera = _FakeSDK()
    captured: List[np.ndarray] = []
    cam._propogate_frame = lambda frame: captured.append(np.array(frame.frame))

    cam._on_frame_callback()

    assert len(captured) == 1
    frame = captured[0]
    assert frame.shape == (_H, _W)
    assert np.all(frame == _FILL_PIXEL), "delivered frame is all zeros: buffer-realloc race corrupted it"


def _prepare_for_update_settings(cam: camera_toupcam.ToupcamCamera, roi_w: int, roi_h: int, monkeypatch) -> None:
    class _FakeSDK:
        def get_Roi(self):
            return 0, 0, roi_w, roi_h

    cam._camera = _FakeSDK()
    cam._capabilities = None
    cam._hw_set_strobe_delay_ms_fn = None
    cam.get_exposure_time = lambda: 10.0
    cam._calculate_camera_exposure_time = lambda ms: ms
    cam.get_acquisition_mode = lambda: CameraAcquisitionMode.SOFTWARE_TRIGGER
    cam.get_strobe_time = lambda: 0.0
    cam.get_total_frame_time = lambda: 10.0
    monkeypatch.setattr(camera_toupcam.ToupcamCamera, "_calculate_strobe_info", staticmethod(lambda **kwargs: None))


def test_update_internal_settings_keeps_buffer_when_size_unchanged(monkeypatch) -> None:
    cam = _make_camera()
    _prepare_for_update_settings(cam, _W, _H, monkeypatch)
    lock = _TrackingLock()
    cam._raw_frame_callback_lock = lock
    original = cam._internal_read_buffer

    cam._update_internal_settings(send_exposure=False)

    assert cam._internal_read_buffer is original
    assert lock.enter_count == 0


def test_update_internal_settings_reallocates_under_lock_when_size_changes(monkeypatch) -> None:
    cam = _make_camera()
    _prepare_for_update_settings(cam, 2 * _W, _H, monkeypatch)
    lock = _TrackingLock()
    cam._raw_frame_callback_lock = lock

    cam._update_internal_settings(send_exposure=False)

    assert len(cam._internal_read_buffer) == 2 * _SIZE
    assert lock.enter_count == 1


def test_update_internal_settings_allocates_when_buffer_missing(monkeypatch) -> None:
    """First call comes from __init__, before _internal_read_buffer exists."""
    cam = _make_camera()
    del cam._internal_read_buffer
    _prepare_for_update_settings(cam, _W, _H, monkeypatch)

    cam._update_internal_settings(send_exposure=False)

    assert len(cam._internal_read_buffer) == _SIZE

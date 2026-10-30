"""Tests for DefaultCamera.read_camera_frame's cached-frame fast path.

Ported semantically from upstream #599 / #603: in trigger->read workflows the fast path must never
return a frame captured before the most recent trigger.
"""

import sys
import threading
import time
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

import squid.core.logging
from squid.core.abc import CameraFrame, CameraFrameFormat
from squid.core.config import CameraPixelFormat

_GXIPY_MODULE = "squid.backend.drivers.gxipy"


def _import_default_camera():
    """Import DefaultCamera, stubbing gxipy if the vendor SDK can't load on this platform (e.g. no WinDLL)."""
    try:
        import squid.backend.drivers.gxipy  # noqa: F401
    except Exception:
        sys.modules.pop(_GXIPY_MODULE, None)
        stub = types.ModuleType(_GXIPY_MODULE)
        stub.__getattr__ = lambda name: MagicMock(name=f"gx.{name}")  # Class-level gx.* references resolve.
        sys.modules[_GXIPY_MODULE] = stub
        try:
            from squid.backend.drivers.cameras.base import DefaultCamera
        finally:
            sys.modules.pop(_GXIPY_MODULE, None)
        return DefaultCamera

    from squid.backend.drivers.cameras.base import DefaultCamera

    return DefaultCamera


DefaultCamera = _import_default_camera()


def _make_frame(frame_id: int, timestamp: float) -> CameraFrame:
    return CameraFrame(
        frame_id=frame_id,
        timestamp=timestamp,
        frame=np.zeros((4, 4), dtype=np.uint8),
        frame_format=CameraFrameFormat.RAW,
        frame_pixel_format=CameraPixelFormat.MONO8,
    )


@pytest.fixture
def camera() -> DefaultCamera:
    # Bypass __init__ (which opens real gxipy hardware) and set only what read_camera_frame needs.
    cam = DefaultCamera.__new__(DefaultCamera)
    cam._log = squid.core.logging.get_logger("test_default_camera")
    cam._frame_lock = threading.Lock()
    cam._exposure_time_ms = 1000.0  # Large window so a just-captured frame is "fresh".
    cam._strobe_delay_us = 0
    cam._last_trigger_timestamp = 0
    cam._current_frame = None
    cam.get_is_streaming = lambda: True
    return cam


def test_reuses_fresh_frame_when_no_trigger_since(camera):
    """Continuous mode: no per-read trigger, so a fresh cached frame is returned immediately."""
    frame = _make_frame(1, time.time())
    camera._current_frame = frame

    assert camera.read_camera_frame() is frame


def test_does_not_reuse_pre_trigger_frame(camera):
    """A fresh frame captured before the last trigger must not be returned by the fast path."""
    now = time.time()
    pre_trigger = _make_frame(1, now - 0.001)
    camera._current_frame = pre_trigger
    camera._last_trigger_timestamp = now
    camera._exposure_time_ms = 200.0  # pre_trigger is well within the freshness window.

    post_trigger = _make_frame(2, now + 0.02)

    def deliver():
        time.sleep(0.02)
        camera._current_frame = post_trigger

    t = threading.Thread(target=deliver)
    t.start()
    result = camera.read_camera_frame()
    t.join()

    assert result is post_trigger


def test_pre_trigger_frame_times_out_instead_of_being_reused(camera):
    """If no post-trigger frame arrives, the read times out rather than returning the stale frame."""
    now = time.time()
    camera._current_frame = _make_frame(1, now - 0.001)
    camera._last_trigger_timestamp = now
    camera._exposure_time_ms = 50.0  # Frame is "fresh"; only the trigger guard rejects it.

    assert camera.read_camera_frame() is None


def test_reuses_frame_captured_after_trigger(camera):
    trigger_time = time.time() - 0.01
    frame = _make_frame(3, trigger_time + 0.005)
    camera._current_frame = frame
    camera._last_trigger_timestamp = trigger_time

    assert camera.read_camera_frame() is frame

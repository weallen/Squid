import ctypes

import numpy as np
import pytest

# The TUCam SDK shared library is loaded at import time (tucam_sdk.py).
# Skip the whole module where it is not installed (e.g. CI / dev without the SDK).
try:
    from squid.backend.drivers.cameras.tucam_sdk import TUCAM_RAWIMG_HEADER
    from squid.backend.drivers.cameras.tucsen import TucsenCamera
    from squid.core.abc import CameraError
except OSError as e:  # libTUCam.so.1 / TUCam.dll not present
    pytest.skip(f"TUCam SDK not available: {e}", allow_module_level=True)


def _make_header(arr: np.ndarray):
    """Build a TUCAM_RAWIMG_HEADER pointing at a real ctypes buffer holding `arr`.

    Returns (header, backing_buffer). The caller MUST keep backing_buffer alive
    for as long as header.pImgData is used — pImgData is a raw pointer into it.
    """
    raw = arr.astype(np.uint16).tobytes()
    backing = ctypes.create_string_buffer(raw, len(raw))
    header = TUCAM_RAWIMG_HEADER()
    header.usWidth = arr.shape[1]
    header.usHeight = arr.shape[0]
    header.uiImgSize = len(raw)
    header.pImgData = ctypes.cast(backing, ctypes.c_void_p)
    return header, backing


def test_convert_header_to_numpy_roundtrips_pixels():
    arr = np.arange(2 * 3, dtype=np.uint16).reshape(2, 3)
    header, _backing = _make_header(arr)

    out = TucsenCamera._convert_header_to_numpy(header)

    assert out.shape == (2, 3)
    assert out.dtype == np.uint16
    np.testing.assert_array_equal(out, arr)


def test_convert_header_to_numpy_copies_data():
    # The returned array must own its data (copied from device memory), so it
    # stays valid after the source buffer is dropped — it must not alias pImgData.
    arr = np.array([[7, 8], [9, 10]], dtype=np.uint16)
    header, backing = _make_header(arr)

    out = TucsenCamera._convert_header_to_numpy(header)

    # Drop the source buffer and mutate its bytes; `out` must be unaffected.
    ctypes.memset(backing, 0, len(backing))
    del backing
    np.testing.assert_array_equal(out, [[7, 8], [9, 10]])


def test_convert_header_to_numpy_rejects_short_buffer():
    arr = np.arange(2 * 3, dtype=np.uint16).reshape(2, 3)
    header, _backing = _make_header(arr)
    header.uiImgSize = 4  # smaller than usWidth*usHeight*2 == 12

    with pytest.raises(CameraError):
        TucsenCamera._convert_header_to_numpy(header)


def test_convert_header_to_numpy_rejects_padding():
    arr = np.arange(2 * 3, dtype=np.uint16).reshape(2, 3)
    header, _backing = _make_header(arr)
    header.usXPadding = 1  # per-row padding would corrupt a flat reshape

    with pytest.raises(CameraError):
        TucsenCamera._convert_header_to_numpy(header)


def test_header_view_reads_device_memory_without_copying():
    arr = np.arange(2 * 3, dtype=np.uint16).reshape(2, 3)
    header, backing = _make_header(arr)

    view = TucsenCamera._header_to_numpy_view(header)

    np.testing.assert_array_equal(view, arr)
    ctypes.memset(backing, 0, len(backing))
    np.testing.assert_array_equal(view, np.zeros((2, 3)))  # a view: it follows the device buffer


@pytest.mark.parametrize("flip", [None, "Vertical"])
def test_frame_callback_copies_the_frame_out_of_device_memory(monkeypatch, flip):
    """The callback reads the driver's buffer directly; the frame it hands on must not alias that buffer,
    which the driver reuses for the next frame."""
    import threading
    import types

    import squid.backend.drivers.cameras.tucsen as tucsen
    import squid.core.logging
    from squid.core.utils.hardware_utils import FlipVariant, rotate_and_flip_image

    arr = np.arange(4 * 3, dtype=np.uint16).reshape(4, 3)
    source, backing = _make_header(arr)

    def get_data(handle, header_ptr):
        ctypes.memmove(header_ptr, ctypes.addressof(source), ctypes.sizeof(source))
        return tucsen.TUCAMRET.TUCAMRET_SUCCESS

    monkeypatch.setattr(tucsen, "TUCAM_Buf_GetData", get_data)
    frames = []
    flip_variant = FlipVariant(flip) if flip else None
    camera = types.SimpleNamespace(
        _is_streaming=threading.Event(),
        _frame_lock=threading.Lock(),
        _camera=None,
        _current_frame=None,
        _trigger_sent=threading.Event(),
        _log=squid.core.logging.get_logger("test"),
        _header_to_numpy_view=TucsenCamera._header_to_numpy_view,
        _process_raw_frame=lambda image: rotate_and_flip_image(image, None, flip_variant),
        get_frame_format=lambda: None,
        get_pixel_format=lambda: None,
        _propogate_frame=frames.append,
    )
    camera._is_streaming.set()

    TucsenCamera._on_frame_callback(camera)

    expected = arr[::-1] if flip else arr
    np.testing.assert_array_equal(frames[0].frame, expected)
    ctypes.memset(backing, 0, len(backing))  # the driver reuses its buffer
    np.testing.assert_array_equal(frames[0].frame, expected)


def test_frame_callback_copies_when_processing_returns_a_view(monkeypatch):
    """Guard: if processing ever hands back a view of the driver buffer, the callback copies it."""
    import threading
    import types

    import squid.backend.drivers.cameras.tucsen as tucsen
    import squid.core.logging

    arr = np.arange(4 * 3, dtype=np.uint16).reshape(4, 3)
    source, backing = _make_header(arr)

    def get_data(handle, header_ptr):
        ctypes.memmove(header_ptr, ctypes.addressof(source), ctypes.sizeof(source))
        return tucsen.TUCAMRET.TUCAMRET_SUCCESS

    monkeypatch.setattr(tucsen, "TUCAM_Buf_GetData", get_data)
    frames = []
    camera = types.SimpleNamespace(
        _is_streaming=threading.Event(),
        _frame_lock=threading.Lock(),
        _camera=None,
        _current_frame=None,
        _trigger_sent=threading.Event(),
        _log=squid.core.logging.get_logger("test"),
        _header_to_numpy_view=TucsenCamera._header_to_numpy_view,
        _process_raw_frame=lambda image: image[1:],  # a view, e.g. a crop
        get_frame_format=lambda: None,
        get_pixel_format=lambda: None,
        _propogate_frame=frames.append,
    )
    camera._is_streaming.set()

    TucsenCamera._on_frame_callback(camera)

    ctypes.memset(backing, 0, len(backing))
    np.testing.assert_array_equal(frames[0].frame, arr[1:])

"""StreamHandler.force_next_display(): a snapped frame is never swallowed by display throttling."""

import time
from unittest.mock import MagicMock

import numpy as np

from squid.backend.io.stream_handler import StreamHandler, StreamHandlerFunctions


def _handler():
    display = MagicMock()
    fns = StreamHandlerFunctions(
        image_to_display=display,
        packet_image_to_write=lambda *a: None,
        signal_new_frame_received=lambda: None,
        accept_new_frame=lambda: True,
    )
    handler = StreamHandler(handler_functions=fns)
    handler.set_display_fps(1)
    return handler, display


def _frame():
    frame = MagicMock()
    frame.frame = np.zeros((4, 4), dtype=np.uint16)
    frame.is_color.return_value = False
    return frame


def test_throttled_frame_is_dropped_without_force():
    handler, display = _handler()
    handler.timestamp_last_display = time.time()
    handler.on_new_frame(_frame())
    display.assert_not_called()


def test_force_next_display_bypasses_throttle_once():
    handler, display = _handler()
    handler.timestamp_last_display = time.time()
    handler.force_next_display()
    handler.on_new_frame(_frame())
    assert display.call_count == 1
    handler.on_new_frame(_frame())  # one-shot: next frame is throttled again
    assert display.call_count == 1


def test_force_next_display_applies_to_on_new_image():
    handler, display = _handler()
    handler.timestamp_last_display = time.time()
    handler.force_next_display()
    handler.on_new_image(np.zeros((4, 4), dtype=np.uint16))
    assert display.call_count == 1

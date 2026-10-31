from types import SimpleNamespace

import pytest

import numpy as np

from squid.core.events import AcquisitionStateChanged
from squid.ui.widgets.display.napari_multichannel import NapariMultiChannelWidget


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)


class _Layer:
    def __init__(self, name: str, data: np.ndarray, rgb: bool) -> None:
        self.name = name
        self.data = np.array(data, copy=True)
        self.rgb = rgb
        self.contrast_limits = (0.0, 1.0)
        self.events = SimpleNamespace(contrast_limits=_Signal())
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


class _LayerList:
    def __init__(self) -> None:
        self._layers: dict[str, _Layer] = {}

    def __contains__(self, name: str) -> bool:
        return name in self._layers

    def __getitem__(self, name: str) -> _Layer:
        return self._layers[name]

    def __iter__(self):
        return iter(self._layers.values())

    def add(self, layer: _Layer) -> None:
        self._layers[layer.name] = layer

    def remove(self, layer: _Layer) -> None:
        self._layers.pop(layer.name, None)

    def clear(self) -> None:
        self._layers.clear()


class _Dims:
    """Minimal stand-in for napari's Dims: point, set_point and an observable ndisplay."""

    def __init__(self) -> None:
        self.point = (0.0, 0.0, 0.0)
        self._ndisplay = 2
        self.set_point_calls = 0
        self.events = SimpleNamespace(ndisplay=_Signal())

    def set_point(self, axis: int, value: float) -> None:
        self.set_point_calls += 1
        point = list(self.point)
        point[axis] = value
        self.point = tuple(point)

    @property
    def ndisplay(self) -> int:
        return self._ndisplay

    @ndisplay.setter
    def ndisplay(self, value: int) -> None:
        changed = value != self._ndisplay
        self._ndisplay = value
        if changed:
            for callback in self.events.ndisplay._callbacks:
                callback(None)


class _Viewer:
    def __init__(self) -> None:
        self.layers = _LayerList()
        self.dims = _Dims()
        self.reset_view_calls = 0

    def add_image(
        self,
        data: np.ndarray,
        name: str,
        visible: bool,
        rgb: bool,
        colormap,
        contrast_limits,
        blending: str,
        scale,
    ) -> _Layer:
        layer = _Layer(name=name, data=data, rgb=rgb)
        self.layers.add(layer)
        return layer

    def reset_view(self) -> None:
        self.reset_view_calls += 1


class _ContrastManager:
    def get_limits(self, _channel_name: str):
        return (0.0, 255.0)

    def get_default_limits(self):
        return (0.0, 255.0)

    def scale_contrast_limits(self, _dtype) -> None:
        pass


def _make_widget() -> NapariMultiChannelWidget:
    widget = NapariMultiChannelWidget.__new__(NapariMultiChannelWidget)
    widget.contrastManager = _ContrastManager()
    widget.image_width = 0
    widget.image_height = 0
    widget.dtype = np.dtype(np.uint16)
    widget.channels = set()
    widget.pixel_size_um = 1.0
    widget.dz_um = 1.0
    widget.Nz = 1
    widget.layers_initialized = True
    widget.acquisition_initialized = True
    widget.viewer_scale_initialized = True
    widget.update_layer_count = 0
    widget.viewer = _Viewer()
    widget._ndisplay_before_acquisition = None
    widget._pending_z_index = None
    widget._next_refresh_time = 0.0
    widget._refresh_timer = _Timer(widget)
    widget.viewer.dims.events.ndisplay.connect(widget._onNdisplayChanged)
    return widget


class _Timer:
    """Single-shot timer stand-in: records start() and fires only when the test says so."""

    def __init__(self, widget) -> None:
        self._widget = widget
        self.active = False
        self.start_delays_ms: list[int] = []

    def isActive(self) -> bool:
        return self.active

    def start(self, delay_ms: int) -> None:
        self.active = True
        self.start_delays_ms.append(delay_ms)

    def stop(self) -> None:
        self.active = False

    def fire(self) -> None:
        self.active = False
        self._widget._refreshDisplay()


def test_update_layers_reinitializes_when_image_shape_changes():
    widget = _make_widget()
    channel = "10x BF LED matrix full"

    widget.image_height = 1032
    widget.image_width = 1500
    widget.channels = {channel}
    widget.viewer.add_image(
        np.zeros((1, 1032, 1500), dtype=np.uint16),
        name=channel,
        visible=True,
        rgb=False,
        colormap="gray",
        contrast_limits=(0.0, 1.0),
        blending="additive",
        scale=(1.0, 1.0, 1.0),
    )

    image = np.full((2064, 3000), 7, dtype=np.uint16)
    widget.updateLayers(image, 0, 0, 0, channel)

    layer = widget.viewer.layers[channel]
    assert layer.data.shape == (1, 2064, 3000)
    np.testing.assert_array_equal(layer.data[0], image)


def test_update_layers_grows_z_stack_when_k_exceeds_current_nz():
    widget = _make_widget()
    channel = "10x Fluorescence 488 nm Ex"

    image = np.full((64, 96), 3, dtype=np.uint16)
    widget.updateLayers(image, 0, 0, 2, channel)

    layer = widget.viewer.layers[channel]
    assert widget.Nz == 3
    assert layer.data.shape == (3, 64, 96)
    np.testing.assert_array_equal(layer.data[2], image)


def test_update_layers_recreates_layer_when_switching_mono_to_rgb():
    widget = _make_widget()
    channel = "10x BF LED matrix full"
    widget.image_height = 50
    widget.image_width = 60
    widget.channels = {channel}

    old_layer = widget.viewer.add_image(
        np.zeros((1, 50, 60), dtype=np.uint16),
        name=channel,
        visible=True,
        rgb=False,
        colormap="gray",
        contrast_limits=(0.0, 1.0),
        blending="additive",
        scale=(1.0, 1.0, 1.0),
    )

    image_rgb = np.full((50, 60, 3), 11, dtype=np.uint16)
    widget.updateLayers(image_rgb, 0, 0, 0, channel)

    new_layer = widget.viewer.layers[channel]
    assert new_layer is not old_layer
    assert new_layer.rgb is True
    assert new_layer.data.shape == (1, 50, 60, 3)
    np.testing.assert_array_equal(new_layer.data[0], image_rgb)


# --- Coalesced refreshes / 2D-while-acquiring (upstream c8f69125, #713) ---

CHANNEL = "20x Fluorescence 488 nm Ex"


def _start(widget, nz: int = 10) -> None:
    widget.Nz = nz
    widget.dz_um = 3.0
    widget.channels = {CHANNEL}
    widget.layers_initialized = False
    widget.acquisition_initialized = False


def _frame(k: int) -> np.ndarray:
    return np.full((8, 8), k + 1, dtype=np.uint16)


def test_frames_are_written_immediately_but_refresh_is_coalesced():
    widget = _make_widget()
    _start(widget, nz=50)
    for k in range(40):
        widget.updateLayers(_frame(k), 0, 0, k, CHANNEL)

    layer = widget.viewer.layers[CHANNEL]
    # All data is in the canvas, but no refresh/re-slice happened per frame (the one refresh
    # is from adding the layer).
    np.testing.assert_array_equal(layer.data[39], _frame(39))
    assert widget.viewer.dims.set_point_calls == 0
    assert layer.refresh_count == 1
    # One pending refresh, armed once.
    assert widget._refresh_timer.start_delays_ms == [0]

    widget._refresh_timer.fire()
    assert widget.viewer.dims.set_point_calls == 1
    assert widget.viewer.dims.point[0] == pytest.approx(39 * 3.0)
    # Moving to a new plane already re-slices, so no redundant refresh loop.
    assert layer.refresh_count == 1

    # The next refresh is delayed by at least MIN_REFRESH_INTERVAL_S.
    widget.updateLayers(_frame(40), 0, 0, 40, CHANNEL)
    assert widget._refresh_timer.start_delays_ms[-1] >= int(0.9 * widget.MIN_REFRESH_INTERVAL_S * 1000)


def test_single_plane_refreshes_layers_explicitly():
    widget = _make_widget()
    _start(widget, nz=1)
    widget.updateLayers(_frame(0), 0, 0, 0, CHANNEL)
    before = widget.viewer.layers[CHANNEL].refresh_count
    widget._refresh_timer.fire()
    assert widget.viewer.dims.set_point_calls == 0
    assert widget.viewer.layers[CHANNEL].refresh_count == before + 1


def test_contrast_limits_only_assigned_when_changed():
    widget = _make_widget()
    _start(widget)
    assigned = []

    widget.updateLayers(_frame(0), 0, 0, 0, CHANNEL)
    layer = widget.viewer.layers[CHANNEL]
    original_cls = type(layer)

    class _Counting(original_cls):
        @property
        def contrast_limits(self):
            return self._cl

        @contrast_limits.setter
        def contrast_limits(self, value):
            assigned.append(value)
            self._cl = value

    layer._cl = (0.0, 255.0)
    layer.__class__ = _Counting
    for k in range(1, 6):
        widget.updateLayers(_frame(k), 0, 0, k, CHANNEL)
    assert assigned == []


def test_acquisition_shows_2d_and_restores_3d():
    widget = _make_widget()
    widget.viewer.dims.ndisplay = 3
    _start(widget)

    widget._on_acquisition_state_changed(AcquisitionStateChanged(in_progress=True, experiment_id="e"))
    assert widget.viewer.dims.ndisplay == 2
    for k in range(5):
        widget.updateLayers(_frame(k), 0, 0, k, CHANNEL)
    assert widget.viewer.dims.ndisplay == 2

    widget._on_acquisition_state_changed(AcquisitionStateChanged(in_progress=False, experiment_id="e"))
    assert widget.viewer.dims.ndisplay == 3
    # The final plane is drawn immediately, without the event loop.
    assert widget.viewer.dims.point[0] == pytest.approx(4 * 3.0)
    assert widget._refresh_timer.isActive() is False

    # Second acquisition with identical geometry (initLayers not re-run) also goes 2D.
    widget._on_acquisition_state_changed(AcquisitionStateChanged(in_progress=True, experiment_id="f"))
    assert widget.viewer.dims.ndisplay == 2
    widget.finishAcquisition()
    assert widget.viewer.dims.ndisplay == 3


def test_first_frame_without_start_event_switches_to_2d():
    widget = _make_widget()
    widget.viewer.dims.ndisplay = 3
    _start(widget)
    widget.updateLayers(_frame(0), 0, 0, 0, CHANNEL)
    assert widget.viewer.dims.ndisplay == 2
    widget.finishAcquisition()
    assert widget.viewer.dims.ndisplay == 3


def test_started_in_2d_ends_in_2d_and_mid_run_switch_is_kept():
    widget = _make_widget()
    _start(widget)
    widget._on_acquisition_state_changed(AcquisitionStateChanged(in_progress=True, experiment_id="e"))
    widget.finishAcquisition()
    assert widget.viewer.dims.ndisplay == 2

    widget._on_acquisition_state_changed(AcquisitionStateChanged(in_progress=True, experiment_id="f"))
    widget.viewer.dims.ndisplay = 3  # user switches mid-run
    widget.finishAcquisition()
    assert widget.viewer.dims.ndisplay == 3


def test_finish_without_acquisition_is_noop():
    widget = _make_widget()
    widget.viewer.dims.ndisplay = 3
    widget.finishAcquisition()
    assert widget.viewer.dims.ndisplay == 3
    assert widget.viewer.dims.set_point_calls == 0


def test_acquisition_finished_event_reaches_finish_acquisition(qtbot, monkeypatch):
    """The real widget (napari stub) must receive the EventBus end-of-acquisition state event."""
    from squid.core.events import EventBus
    from squid.ui.qt_event_dispatcher import QtEventDispatcher
    from squid.ui.ui_event_bus import UIEventBus

    calls = []
    monkeypatch.setattr(NapariMultiChannelWidget, "finishAcquisition", lambda self: calls.append(self))
    core_bus = EventBus()
    core_bus.start()
    try:
        ui_bus = UIEventBus(core_bus, QtEventDispatcher())
        widget = NapariMultiChannelWidget(ui_bus, _ContrastManager())
        qtbot.addWidget(widget)
        widget._refresh_timer.stop()

        ui_bus.publish(AcquisitionStateChanged(in_progress=True, experiment_id="e"))
        ui_bus.publish(AcquisitionStateChanged(in_progress=False, experiment_id="e"))
        qtbot.waitUntil(lambda: calls == [widget], timeout=2000)
    finally:
        core_bus.stop()

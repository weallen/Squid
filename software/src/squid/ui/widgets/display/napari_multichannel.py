# Napari multi-channel Z-stack viewer widget
from __future__ import annotations

import time

import numpy as np
from numpy.typing import DTypeLike
from typing import Optional, Set, Tuple, TYPE_CHECKING

import napari
from napari.utils.colormaps import Colormap, AVAILABLE_COLORMAPS
from napari.utils.events import Event

from qtpy.QtCore import QTimer
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QWidget, QVBoxLayout

from _def import CHANNEL_COLORS_MAP, SQUID_ICON_PATH
from squid.core.config.feature_flags import get_feature_flags

from squid.backend.managers import ContrastManager
from squid.core.events import (
    handles,
    AcquisitionStateChanged,
    BinningChanged,
    ObjectiveChanged,
    SetAcquisitionChannelsCommand,
    SetAcquisitionParametersCommand,
)
from squid.ui.widgets.base import EventBusWidget

if TYPE_CHECKING:
    from squid.ui.ui_event_bus import UIEventBus


_FEATURE_FLAGS = get_feature_flags()


class NapariMultiChannelWidget(EventBusWidget):
    """Multi-channel Z-stack viewer using napari.

    Subscribes to BinningChanged and ObjectiveChanged events to update pixel size.
    No direct service or controller access - pure event-driven architecture.
    """

    # Writing a frame into its layer is a cheap copy, but refreshing the viewer re-slices
    # every layer and recomputes its thumbnail, so refreshes are coalesced to at most one
    # per interval. Without this, a large z-stack queues frames faster than the GUI thread
    # can draw them and the window stops responding.
    MIN_REFRESH_INTERVAL_S = 0.1

    contrastManager: ContrastManager
    image_width: int
    image_height: int
    dtype: np.dtype
    channels: Set[str]
    pixel_size_um: float
    dz_um: float
    Nz: int
    layers_initialized: bool
    acquisition_initialized: bool
    viewer_scale_initialized: bool
    update_layer_count: int
    grid_enabled: bool
    viewer: napari.Viewer
    viewerWidget: QWidget
    _layout: QVBoxLayout

    def __init__(
        self,
        event_bus: "UIEventBus",
        contrastManager: ContrastManager,
        initial_pixel_size_factor: float = 1.0,
        initial_pixel_size_binned_um: float = 1.0,
        grid_enabled: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(event_bus, parent)

        # Cached values from events (initialized with provided initial values)
        self._pixel_size_factor = initial_pixel_size_factor
        self._pixel_size_binned_um = initial_pixel_size_binned_um

        # Initialize placeholders for the acquisition parameters
        self.contrastManager = contrastManager
        self.image_width = 0
        self.image_height = 0
        self.dtype = np.dtype(np.uint8)
        self.channels = set()
        self.pixel_size_um = self._pixel_size_factor * self._pixel_size_binned_um
        self.dz_um = 1.0
        self.Nz = 1
        self.layers_initialized = False
        self.acquisition_initialized = False
        self.viewer_scale_initialized = False
        self.update_layer_count = 0
        self.grid_enabled = grid_enabled
        # The viewer's 2D/3D mode before the acquisition switched it to 2D; None when idle.
        self._ndisplay_before_acquisition: Optional[int] = None
        # Z index of the latest complete channel set, shown by the next coalesced refresh.
        self._pending_z_index: Optional[int] = None
        self._next_refresh_time = 0.0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refreshDisplay)

        # Initialize a napari Viewer without showing its standalone window.
        self.initNapariViewer()

    @handles(BinningChanged)
    def _on_binning_changed(self, event: BinningChanged) -> None:
        """Update cached pixel size when binning changes."""
        if event.pixel_size_binned_um is not None:
            self._pixel_size_binned_um = event.pixel_size_binned_um
            pixel_size_um = self._pixel_size_factor * self._pixel_size_binned_um
            if self.pixel_size_um != pixel_size_um:
                self.pixel_size_um = pixel_size_um
                self.acquisition_initialized = False

    @handles(ObjectiveChanged)
    def _on_objective_changed(self, event: ObjectiveChanged) -> None:
        """Update cached pixel size factor when objective changes."""
        if event.pixel_size_um is not None:
            self._pixel_size_factor = event.pixel_size_um
            pixel_size_um = self._pixel_size_factor * self._pixel_size_binned_um
            if self.pixel_size_um != pixel_size_um:
                self.pixel_size_um = pixel_size_um
                self.acquisition_initialized = False

    @handles(SetAcquisitionChannelsCommand)
    def _on_set_acquisition_channels(self, event: SetAcquisitionChannelsCommand) -> None:
        self.initChannels(set(event.channel_names))

    @handles(SetAcquisitionParametersCommand)
    def _on_set_acquisition_parameters(
        self, event: SetAcquisitionParametersCommand
    ) -> None:
        nz = int(event.n_z) if event.n_z is not None else int(self.Nz)
        dz = float(event.delta_z_um) if event.delta_z_um is not None else float(self.dz_um)
        self.initLayersShape(nz, dz)

    @handles(AcquisitionStateChanged)
    def _on_acquisition_state_changed(self, event: AcquisitionStateChanged) -> None:
        # Delivered via the EventBus (not a performance-mode-gated napari connection), so the
        # user's 2D/3D mode is restored even if performance mode was enabled mid-acquisition.
        if event.in_progress:
            # initLayers() only runs when the layer geometry changed, so a repeat acquisition
            # with the same geometry would otherwise stay in 3D.
            self._enterAcquisitionDisplay()
        else:
            self.finishAcquisition()

    def initNapariViewer(self) -> None:
        self.viewer = napari.Viewer(show=False)
        if self.grid_enabled:
            self.viewer.grid.enabled = True
        self.viewer.dims.axis_labels = ["Z-axis", "Y-axis", "X-axis"]
        self.viewer.dims.events.ndisplay.connect(self._onNdisplayChanged)
        self.viewerWidget = self.viewer.window._qt_window
        self._layout = QVBoxLayout()
        self._layout.addWidget(self.viewerWidget)
        self.setLayout(self._layout)
        self.customizeViewer()

    def customizeViewer(self) -> None:
        # Set Squid/Cephla branding on napari viewer
        self.viewer.window._qt_window.setWindowIcon(QIcon(str(SQUID_ICON_PATH)))
        self.viewer.window._qt_window.setWindowTitle("Squid Microscope")

        # Hide the napari menu bar (clear it for macOS global menu bar)
        self.viewer.window.main_menu.clear()

        # Hide the layer buttons
        if hasattr(self.viewer.window._qt_viewer, "layerButtons"):
            self.viewer.window._qt_viewer.layerButtons.hide()

    def initLayersShape(self, Nz: int, dz: float) -> None:
        # Use cached values from events
        pixel_size_um = self._pixel_size_factor * self._pixel_size_binned_um
        if self.Nz != Nz or self.dz_um != dz or self.pixel_size_um != pixel_size_um:
            self.acquisition_initialized = False
            self.Nz = Nz
            self.dz_um = dz if Nz > 1 and dz != 0 else 1.0
            self.pixel_size_um = pixel_size_um

    def initChannels(self, channels: Set[str]) -> None:
        self.channels = set(channels)

    def extractWavelength(self, name: str) -> Optional[str]:
        # Split the string and find the wavelength number immediately after "Fluorescence"
        parts = name.split()
        if "Fluorescence" in parts:
            index = parts.index("Fluorescence") + 1
            if index < len(parts):
                return parts[index].split()[0]  # Assuming '488 nm Ex' and taking '488'
        for color in ["R", "G", "B"]:
            if color in parts or f"full_{color}" in parts:
                return color
        return None

    def generateColormap(self, channel_info: dict) -> Colormap:
        """Convert a HEX value to a normalized RGB tuple."""
        c0 = (0, 0, 0)
        c1 = (
            ((channel_info["hex"] >> 16) & 0xFF) / 255,  # Normalize the Red component
            ((channel_info["hex"] >> 8) & 0xFF) / 255,  # Normalize the Green component
            (channel_info["hex"] & 0xFF) / 255,
        )  # Normalize the Blue component
        return Colormap(colors=[c0, c1], controls=[0, 1], name=channel_info["name"])

    def initLayers(
        self, image_height: int, image_width: int, image_dtype: DTypeLike
    ) -> None:
        """Initializes the full canvas for each channel based on the acquisition parameters."""
        if self.acquisition_initialized:
            for layer in list(self.viewer.layers):
                if layer.name not in self.channels:
                    self.viewer.layers.remove(layer)
        else:
            self.viewer.layers.clear()
            self.acquisition_initialized = True
            if self.dtype != np.dtype(image_dtype) and not _FEATURE_FLAGS.is_enabled("USE_NAPARI_FOR_LIVE_VIEW"):
                self.contrastManager.scale_contrast_limits(image_dtype)

        self.image_width = image_width
        self.image_height = image_height
        self.dtype = np.dtype(image_dtype)
        self.layers_initialized = True
        self.update_layer_count = 0

        self._enterAcquisitionDisplay()

    def _enterAcquisitionDisplay(self) -> None:
        # In 3D, every refresh max-projects the whole (Nz, H, W) canvas of every layer, which
        # takes seconds for a large z-stack. Show 2D while acquiring; finishAcquisition()
        # restores the user's mode.
        if self._ndisplay_before_acquisition is None:
            ndisplay = self.viewer.dims.ndisplay
            self.viewer.dims.ndisplay = 2  # before recording it, so _onNdisplayChanged ignores this switch
            self._ndisplay_before_acquisition = ndisplay

    def updateLayers(
        self, image: np.ndarray, x: int, y: int, k: int, channel_name: str
    ) -> None:
        """Updates the appropriate slice of the canvas with the new image data."""
        rgb = len(image.shape) == 3
        image_height, image_width = image.shape[0], image.shape[1]
        if k < 0:
            return

        # Reinitialize if dtype/shape changed (e.g., camera binning changed).
        if (
            self.dtype != np.dtype(image.dtype)
            or self.image_height != image_height
            or self.image_width != image_width
        ):
            self.layers_initialized = False
            self.acquisition_initialized = False

        # Be defensive when z-index arrives before acquisition parameters.
        if k >= self.Nz:
            self.Nz = k + 1
            self.acquisition_initialized = False

        # Reinitialize if an existing layer has incompatible channel shape (e.g., mono<->RGB).
        if channel_name in self.viewer.layers:
            layer = self.viewer.layers[channel_name]
            layer_is_rgb = bool(getattr(layer, "rgb", False))
            if layer_is_rgb != rgb:
                self.layers_initialized = False
                self.acquisition_initialized = False

        # Reinitialize when acquisition metadata changed (Nz/dz/pixel size).
        if not self.layers_initialized or not self.acquisition_initialized:
            self.initLayers(image_height, image_width, image.dtype)

        if channel_name not in self.viewer.layers:
            self.channels.add(channel_name)
            if rgb:
                color = None  # RGB images do not need a colormap
                canvas = np.zeros(
                    (self.Nz, self.image_height, self.image_width, 3), dtype=self.dtype
                )
            else:
                wavelength = self.extractWavelength(channel_name)
                channel_info = CHANNEL_COLORS_MAP.get(
                    wavelength if wavelength is not None else "",
                    {"hex": 0xFFFFFF, "name": "gray"},
                )
                if channel_info["name"] in AVAILABLE_COLORMAPS:
                    color = AVAILABLE_COLORMAPS[channel_info["name"]]
                else:
                    color = self.generateColormap(channel_info)
                canvas = np.zeros(
                    (self.Nz, self.image_height, self.image_width), dtype=self.dtype
                )

            limits = self.getContrastLimits(self.dtype)
            layer = self.viewer.add_image(
                canvas,
                name=channel_name,
                visible=True,
                rgb=rgb,
                colormap=color,
                contrast_limits=limits,
                blending="additive",
                scale=(self.dz_um, self.pixel_size_um, self.pixel_size_um),
            )

            layer.contrast_limits = self.contrastManager.get_limits(channel_name)
            layer.events.contrast_limits.connect(self.signalContrastLimits)

            if not self.viewer_scale_initialized:
                self.resetView()
                self.viewer_scale_initialized = True
            else:
                layer.refresh()

        layer = self.viewer.layers[channel_name]
        if k >= layer.data.shape[0]:
            self.Nz = k + 1
            self.acquisition_initialized = False
            self.initLayers(image_height, image_width, image.dtype)
            layer = self.viewer.layers[channel_name]
        layer.data[k] = image
        limits = self.contrastManager.get_limits(channel_name)
        # The setter recomputes the layer thumbnail even when the limits are unchanged.
        if list(layer.contrast_limits) != list(limits):
            layer.contrast_limits = limits
        self.update_layer_count += 1
        if self.update_layer_count % len(self.channels) == 0:
            self._pending_z_index = k
            if not self._refresh_timer.isActive():
                delay_s = max(0.0, self._next_refresh_time - time.monotonic())
                self._refresh_timer.start(int(delay_s * 1000))

    def _refreshDisplay(self) -> None:
        """Show the latest complete channel set; data written since the last refresh appears now."""
        start = time.monotonic()
        k, self._pending_z_index = self._pending_z_index, None
        point_before = tuple(self.viewer.dims.point)
        if k is not None and self.Nz > 1:
            self.viewer.dims.set_point(0, k * self.dz_um)
        # Moving to a new plane re-slices every layer; otherwise the new data went into the
        # plane already on screen, so the layers have to be refreshed explicitly.
        if tuple(self.viewer.dims.point) == point_before:
            for layer in self.viewer.layers:
                layer.refresh()
        # Give the event loop at least twice as long as the refresh took, so even a slow
        # refresh (e.g. the user switched to 3D mid-acquisition) can't starve the GUI.
        elapsed = time.monotonic() - start
        self._next_refresh_time = time.monotonic() + max(self.MIN_REFRESH_INTERVAL_S, 2 * elapsed)

    def finishAcquisition(self) -> None:
        """Draw the final state now and restore the 2D/3D mode the acquisition replaced."""
        self._refresh_timer.stop()
        if self._ndisplay_before_acquisition is None:
            if self._pending_z_index is not None:
                self._refreshDisplay()
            return  # no acquisition started in the viewer
        self._refreshDisplay()
        self.viewer.dims.ndisplay = self._ndisplay_before_acquisition
        self._ndisplay_before_acquisition = None

    def _onNdisplayChanged(self, event: Optional[Event] = None) -> None:
        # A 2D/3D switch the user makes mid-acquisition is the mode to end in, not the one from
        # before the run.
        if self._ndisplay_before_acquisition is not None:
            self._ndisplay_before_acquisition = self.viewer.dims.ndisplay

    def signalContrastLimits(self, event: Event) -> None:
        layer = event.source
        min_val, max_val = map(float, layer.contrast_limits)
        self.contrastManager.update_limits(layer.name, min_val, max_val)

    def getContrastLimits(self, dtype: np.dtype) -> Tuple[float, float]:
        return self.contrastManager.get_default_limits()

    def resetView(self) -> None:
        self.viewer.reset_view()
        for layer in self.viewer.layers:
            layer.refresh()

    def activate(self) -> None:
        self.viewer.window.activate()

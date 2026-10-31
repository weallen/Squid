"""Channel selection and ordering widget with drag-and-drop support.

This widget allows users to:
1. Select which channels to image (via checkboxes)
2. Reorder channels via drag-and-drop to set imaging order
3. View the current imaging order at a glance

The imaging order matters for multi-channel acquisitions, particularly when
optimizing for speed or minimizing photobleaching.

With ``ordered_selection=True`` (used by the multipoint widgets) the selection
follows the user's order: checking a channel appends it to an ordered block at
the top of the list, unchecked channels sit below in configuration order, and
dragging rows reorders the selected block.
"""

import os
from typing import List, Optional

import yaml
from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QFrame,
)

import squid.core.logging

_log = squid.core.logging.get_logger(__name__)

CHANNEL_SEQUENCE_CACHE_PATH = os.path.join("cache", "channel_sequence.yaml")


def _read_sequence_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        loaded = yaml.safe_load(f)
    return loaded if isinstance(loaded, dict) else {}


def load_cached_channel_order(cache_key: str, path: Optional[str] = None) -> Optional[List[str]]:
    """Return the cached ordered channel selection for ``cache_key``, or None if absent."""
    path = path or CHANNEL_SEQUENCE_CACHE_PATH
    try:
        value = _read_sequence_cache(path).get(cache_key)
        if isinstance(value, list):
            return [str(v) for v in value]
    except Exception as e:
        _log.warning(f"Failed to load channel sequence cache: {e}")
    return None


def save_cached_channel_order(cache_key: str, names: List[str], path: Optional[str] = None) -> None:
    """Persist the ordered channel selection for ``cache_key`` (other keys are kept)."""
    path = path or CHANNEL_SEQUENCE_CACHE_PATH
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        data = _read_sequence_cache(path)
        data[cache_key] = list(names)
        # Atomic write: the file is shared by several widgets.
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, path)
    except Exception as e:
        _log.warning(f"Failed to save channel sequence cache: {e}")


class ChannelOrderWidget(QWidget):
    """Widget for selecting and ordering imaging channels.

    Provides a drag-and-drop list where users can:
    - Check/uncheck channels to select them for imaging
    - Drag channels to reorder them (determines imaging order)
    - See the current imaging order displayed below the list

    Signals:
        selection_changed: Emitted when channels are selected/deselected or reordered.
            The signal carries the list of selected channel names in order.
    """

    selection_changed = Signal(list)  # List[str] of selected channel names in order

    def __init__(
        self,
        initial_channels: Optional[List[str]] = None,
        parent: Optional[QWidget] = None,
        ordered_selection: bool = False,
    ):
        """Initialize the channel order widget.

        Args:
            initial_channels: List of available channel names to display.
            parent: Parent widget.
            ordered_selection: If True, the selection order is the order in which the
                user checked channels (then refined by dragging); selected channels
                are kept as a block at the top of the list.
        """
        super().__init__(parent)
        self._channels: List[str] = list(initial_channels or [])
        self._ordered_selection = ordered_selection
        # Source of truth for the selection order in ordered mode (updated synchronously;
        # the visual rebuild is deferred so it never runs inside a Qt item/drag callback).
        self._included: List[str] = []
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self._rebuild_list)

        self._setup_ui()
        self._populate_channels()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Create and configure UI elements."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Channel list with drag-drop and checkboxes
        self.list_channels = QListWidget()
        self.list_channels.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_channels.setDefaultDropAction(Qt.MoveAction)
        self.list_channels.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_channels.setMinimumHeight(80)

        # Imaging order display
        self.order_frame = QFrame()
        order_layout = QHBoxLayout(self.order_frame)
        order_layout.setContentsMargins(2, 2, 2, 2)
        order_layout.setSpacing(4)

        self.order_label_prefix = QLabel("Order:")
        self.order_label_prefix.setStyleSheet("font-weight: bold; font-size: 10px;")
        self.order_label = QLabel("")
        self.order_label.setStyleSheet("font-size: 10px; color: #666;")
        self.order_label.setWordWrap(True)

        order_layout.addWidget(self.order_label_prefix)
        order_layout.addWidget(self.order_label, 1)

        layout.addWidget(self.list_channels)
        layout.addWidget(self.order_frame)

    def _populate_channels(self) -> None:
        """Populate the list with available channels."""
        self.list_channels.clear()
        for channel_name in self._channels:
            item = QListWidgetItem(channel_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Unchecked)
            self.list_channels.addItem(item)
        self._update_order_display()

    def _connect_signals(self) -> None:
        """Connect internal signals."""
        self.list_channels.itemChanged.connect(self._on_item_changed)
        self.list_channels.model().rowsMoved.connect(self._on_rows_moved)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """Handle checkbox state changes."""
        if self._ordered_selection:
            name = item.text()
            if item.checkState() == Qt.Checked:
                if name not in self._included:
                    self._included.append(name)
            elif name in self._included:
                self._included.remove(name)
            self._rebuild_timer.start(0)
        self._update_order_display()
        self.selection_changed.emit(self.get_selected_channels_ordered())

    def _on_rows_moved(self, *_args) -> None:
        """Handle drag-and-drop reordering."""
        if self._ordered_selection:
            self._included = self._checked_names_in_list_order()
            self._rebuild_timer.start(0)
        self._update_order_display()
        self.selection_changed.emit(self.get_selected_channels_ordered())

    def _checked_names_in_list_order(self) -> List[str]:
        names = []
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item and item.checkState() == Qt.Checked:
                names.append(item.text())
        return names

    def _display_order(self) -> List[str]:
        """Selected channels first (in selection order), then the rest in config order."""
        included = set(self._included)
        return list(self._included) + [name for name in self._channels if name not in included]

    def _rebuild_list(self) -> None:
        """Rebuild the list rows in display order (ordered mode only)."""
        self._rebuild_timer.stop()
        included = set(self._included)
        self.list_channels.blockSignals(True)
        try:
            self.list_channels.clear()
            for name in self._display_order():
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                item.setCheckState(Qt.Checked if name in included else Qt.Unchecked)
                self.list_channels.addItem(item)
        finally:
            self.list_channels.blockSignals(False)
        self._update_order_display()

    def _update_order_display(self) -> None:
        """Update the imaging order label."""
        selected = self.get_selected_channels_ordered()
        if not selected:
            self.order_label.setText("(none selected)")
        elif len(selected) == 1:
            self.order_label.setText(selected[0])
        else:
            self.order_label.setText(" → ".join(selected))

    def get_selected_channels_ordered(self) -> List[str]:
        """Get the list of selected channel names in drag-drop order.

        Returns:
            List of channel names that are checked, in the order they
            appear in the list (which can be modified via drag-drop).
        """
        if self._ordered_selection:
            return list(self._included)
        return self._checked_names_in_list_order()

    def set_channels(self, channel_names: List[str]) -> None:
        """Update the available channels.

        Args:
            channel_names: New list of available channel names.
        """
        if self._ordered_selection:
            # Keep the selection order; drop channels that no longer exist.
            self._channels = list(channel_names)
            available = set(self._channels)
            before = list(self._included)
            self._included = [name for name in self._included if name in available]
            self._rebuild_list()
            if self._included != before:
                self.selection_changed.emit(self.get_selected_channels_ordered())
            return
        # Save current selections
        previously_selected = set(self.get_selected_channels_ordered())

        self._channels = list(channel_names)
        self._populate_channels()

        # Restore selections for channels that still exist
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item and item.text() in previously_selected:
                item.setCheckState(Qt.Checked)

        self._update_order_display()

    def set_selected_channels(self, channel_names: List[str]) -> None:
        """Select specific channels and optionally reorder them.

        Args:
            channel_names: List of channel names to select, in the desired order.
                          Channels not in this list will be deselected.
        """
        if self._ordered_selection:
            available = set(self._channels)
            included: List[str] = []
            for name in channel_names:
                if name in available and name not in included:
                    included.append(name)
            self._included = included
            self._rebuild_list()
            self.selection_changed.emit(self.get_selected_channels_ordered())
            return
        # Block signals during bulk update
        self.list_channels.blockSignals(True)

        # First, uncheck all and build a mapping
        item_map = {}
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item:
                item.setCheckState(Qt.Unchecked)
                item_map[item.text()] = i

        # Reorder items to match the requested order for selected channels
        # Move selected channels to the top in the specified order
        new_order = []
        for name in channel_names:
            if name in item_map:
                new_order.append(name)

        # Add remaining channels in their current order
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item and item.text() not in new_order:
                new_order.append(item.text())

        # Rebuild the list in the new order
        self.list_channels.clear()
        for name in new_order:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            if name in channel_names:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.list_channels.addItem(item)

        self.list_channels.blockSignals(False)
        self._update_order_display()
        self.selection_changed.emit(self.get_selected_channels_ordered())

    def select_all(self) -> None:
        """Select all channels."""
        if self._ordered_selection:
            self.set_selected_channels(self._display_order())
            return
        self.list_channels.blockSignals(True)
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item:
                item.setCheckState(Qt.Checked)
        self.list_channels.blockSignals(False)
        self._update_order_display()
        self.selection_changed.emit(self.get_selected_channels_ordered())

    def clear_selection(self) -> None:
        """Deselect all channels."""
        if self._ordered_selection:
            self.set_selected_channels([])
            return
        self.list_channels.blockSignals(True)
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item:
                item.setCheckState(Qt.Unchecked)
        self.list_channels.blockSignals(False)
        self._update_order_display()
        self.selection_changed.emit(self.get_selected_channels_ordered())

    def get_all_channels(self) -> List[str]:
        """Get all available channel names in current order.

        Returns:
            List of all channel names in their current drag-drop order.
        """
        channels = []
        for i in range(self.list_channels.count()):
            item = self.list_channels.item(i)
            if item:
                channels.append(item.text())
        return channels

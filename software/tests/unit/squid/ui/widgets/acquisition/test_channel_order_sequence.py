"""Reorderable channel acquisition sequence in the multipoint widgets (upstream #557)."""

import os
from unittest.mock import MagicMock

import pytest
import yaml
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QWidget

from squid.core.events import ChannelConfigurationsChanged, SetAcquisitionChannelsCommand
from squid.backend.io.acquisition_yaml import AcquisitionYAMLData
from squid.ui.widgets.acquisition import channel_order_widget as cow
from squid.ui.widgets.acquisition.channel_order_widget import (
    ChannelOrderWidget,
    load_cached_channel_order,
    save_cached_channel_order,
)

CHANNELS = ["BF", "405", "488", "561"]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Keep every cache write (sequence cache and wellplate settings cache) in tmp_path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cow, "CHANNEL_SEQUENCE_CACHE_PATH", str(tmp_path / "cache" / "channel_sequence.yaml"))


def _check(widget: ChannelOrderWidget, name: str, checked: bool = True) -> None:
    for i in range(widget.list_channels.count()):
        item = widget.list_channels.item(i)
        if item.text() == name:
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            return
    raise AssertionError(f"{name} not in list")


def _rows(widget: ChannelOrderWidget):
    """Visible row order, after flushing the deferred rebuild."""
    if widget._rebuild_timer.isActive():
        widget._rebuild_list()
    return [widget.list_channels.item(i).text() for i in range(widget.list_channels.count())]


# ---------------------------------------------------------------------------
# ChannelOrderWidget ordered-selection mode
# ---------------------------------------------------------------------------


def test_ordered_selection_follows_click_order_and_floats_to_top(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS, ordered_selection=True)
    emitted = []
    w.selection_changed.connect(emitted.append)

    _check(w, "561")
    _check(w, "BF")

    assert w.get_selected_channels_ordered() == ["561", "BF"]
    assert emitted[-1] == ["561", "BF"]
    assert _rows(w) == ["561", "BF", "405", "488"]

    _check(w, "561", checked=False)
    assert w.get_selected_channels_ordered() == ["BF"]
    # Unchecked channels return to configuration order below the selected block.
    assert _rows(w) == ["BF", "405", "488", "561"]


def test_drag_reorder_updates_selected_order(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS, ordered_selection=True)
    w.set_selected_channels(["405", "488"])
    # Simulate a drag that moved "488" above "405".
    item = w.list_channels.takeItem(1)
    w.list_channels.insertItem(0, item)
    w._on_rows_moved()
    assert w.get_selected_channels_ordered() == ["488", "405"]
    assert _rows(w) == ["488", "405", "BF", "561"]


def test_set_selected_channels_orders_filters_and_dedupes(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS, ordered_selection=True)
    w.set_selected_channels(["488", "missing", "BF", "488"])
    assert w.get_selected_channels_ordered() == ["488", "BF"]
    assert _rows(w) == ["488", "BF", "405", "561"]


def test_set_channels_keeps_selection_order_and_drops_removed(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS, ordered_selection=True)
    w.set_selected_channels(["561", "405", "BF"])
    emitted = []
    w.selection_changed.connect(emitted.append)

    w.set_channels(["BF", "405", "561", "640"])
    assert w.get_selected_channels_ordered() == ["561", "405", "BF"]
    assert emitted == []  # selection unchanged -> no signal

    w.set_channels(["BF", "561", "640"])
    assert w.get_selected_channels_ordered() == ["561", "BF"]
    assert emitted == [["561", "BF"]]
    assert _rows(w) == ["561", "BF", "640"]


def test_select_all_and_clear(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS, ordered_selection=True)
    w.set_selected_channels(["488"])
    w.select_all()
    assert w.get_selected_channels_ordered() == ["488", "BF", "405", "561"]
    w.clear_selection()
    assert w.get_selected_channels_ordered() == []


def test_default_mode_unchanged_uses_list_order(qapp):
    w = ChannelOrderWidget(initial_channels=CHANNELS)
    _check(w, "561")
    _check(w, "BF")
    assert w.get_selected_channels_ordered() == ["BF", "561"]
    assert _rows(w) == CHANNELS


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_round_trip_merges_keys(tmp_path):
    path = str(tmp_path / "seq.yaml")
    assert load_cached_channel_order("flexible", path) is None
    save_cached_channel_order("flexible", ["488", "BF"], path)
    save_cached_channel_order("wellplate", ["405"], path)
    assert load_cached_channel_order("flexible", path) == ["488", "BF"]
    assert load_cached_channel_order("wellplate", path) == ["405"]
    assert not os.path.exists(path + ".tmp")


def test_cache_corrupt_file_is_ignored_and_overwritten(tmp_path):
    path = tmp_path / "seq.yaml"
    path.write_text("- just\n- a list\n")
    assert load_cached_channel_order("flexible", str(path)) is None
    save_cached_channel_order("flexible", ["BF"], str(path))
    assert yaml.safe_load(path.read_text()) == {"flexible": ["BF"]}


# ---------------------------------------------------------------------------
# Multipoint widgets
# ---------------------------------------------------------------------------


def _make_flexible(bus):
    from squid.ui.widgets.acquisition.flexible_multipoint import FlexibleMultiPointWidget

    return FlexibleMultiPointWidget(QWidget(), bus, initial_channel_configs=list(CHANNELS))


def _make_wellplate(bus):
    from squid.ui.widgets.acquisition.wellplate_multipoint import WellplateMultiPointWidget

    return WellplateMultiPointWidget(
        bus,
        initial_channel_configs=list(CHANNELS),
        initial_objective="10x",
        objective_pixel_size_factors={"10x": 1.0},
        camera_fov_size_mm=1.0,
        focusMapWidget=MagicMock(enabled=False, focus_points=[]),
    )


def _make_fluidics(bus):
    from squid.ui.widgets.acquisition.fluidics_multipoint import MultiPointWithFluidicsWidget

    return MultiPointWithFluidicsWidget(bus, initial_channel_configs=list(CHANNELS))


FACTORIES = {"flexible": _make_flexible, "wellplate": _make_wellplate, "fluidics": _make_fluidics}


def _published_channel_commands(bus):
    return [
        c.args[0].channel_names
        for c in bus.publish.call_args_list
        if c.args and isinstance(c.args[0], SetAcquisitionChannelsCommand)
    ]


@pytest.mark.parametrize("key", list(FACTORIES))
def test_widget_publishes_selection_in_user_order_and_persists(qapp, key):
    bus = MagicMock()
    widget = FACTORIES[key](bus)
    try:
        widget._is_active_tab = True
        _check(widget.channel_order_widget, "561")
        _check(widget.channel_order_widget, "405")

        assert widget._selected_channel_names() == ["561", "405"]
        assert _published_channel_commands(bus)[-1] == ["561", "405"]
        assert load_cached_channel_order(key) == ["561", "405"]

        # A new widget restores the order from the cache.
        widget2 = FACTORIES[key](MagicMock())
        try:
            assert widget2._selected_channel_names() == ["561", "405"]
        finally:
            widget2.deleteLater()
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("key", list(FACTORIES))
def test_widget_inactive_tab_does_not_publish_on_selection(qapp, key):
    bus = MagicMock()
    widget = FACTORIES[key](bus)
    try:
        widget._is_active_tab = False
        bus.publish.reset_mock()
        _check(widget.channel_order_widget, "488")
        assert _published_channel_commands(bus) == []
        assert load_cached_channel_order(key) == ["488"]
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("key", list(FACTORIES))
def test_widget_refreshes_on_channel_config_change_keeping_order(qapp, key):
    widget = FACTORIES[key](MagicMock())
    try:
        widget.channel_order_widget.set_selected_channels(["561", "BF"])
        widget._on_channel_configs_changed(
            ChannelConfigurationsChanged(objective_name="10x", configuration_names=["BF", "561", "640"])
        )
        assert widget._selected_channel_names() == ["561", "BF"]
        assert widget.list_configurations.count() == 3
    finally:
        widget.deleteLater()


@pytest.mark.parametrize("key", ["flexible", "wellplate"])
def test_yaml_apply_restores_channel_order(qapp, key):
    widget = FACTORIES[key](MagicMock())
    try:
        yaml_data = AcquisitionYAMLData(widget_type=key, channel_names=["488", "BF", "405"])
        apply = getattr(widget, "_apply_yaml_settings")
        apply(yaml_data)
        assert widget._selected_channel_names() == ["488", "BF", "405"]
    finally:
        widget.deleteLater()


def test_wellplate_legacy_settings_cache_selection_is_used_without_sequence_cache(qapp, tmp_path):
    os.makedirs("cache", exist_ok=True)
    with open("cache/multipoint_widget_config.yaml", "w") as f:
        yaml.dump({"selected_channels": ["488", "BF"]}, f)
    widget = _make_wellplate(MagicMock())
    try:
        assert set(widget._selected_channel_names()) == {"488", "BF"}
    finally:
        widget.deleteLater()

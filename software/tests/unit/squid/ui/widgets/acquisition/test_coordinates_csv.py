"""Tests for multipoint coordinate CSV z save/load (upstream #608)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import _def
from squid.core.events import ClearScanCoordinatesCommand, LoadScanCoordinatesCommand
from squid.ui.widgets.acquisition import coordinates_csv
from squid.ui.widgets.acquisition.coordinates_csv import (
    coordinate_rows_for_save,
    parfocal_adjusted_z_mm,
    regions_from_coordinates_dataframe,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_load_with_z_column_builds_3tuples():
    df = pd.DataFrame(
        {
            "region": ["A1", "A1", "B2"],
            "x (mm)": [10.0, 10.5, 20.0],
            "y (mm)": [10.0, 10.0, 20.0],
            "z (mm)": [3.0, 3.0, 3.5],
        }
    )
    fovs, centers, z_dropped = regions_from_coordinates_dataframe(df)

    assert z_dropped is False
    assert fovs["A1"] == ((10.0, 10.0, 3.0), (10.5, 10.0, 3.0))
    assert fovs["B2"] == ((20.0, 20.0, 3.5),)
    assert centers["A1"] == pytest.approx((10.25, 10.0))


def test_load_without_z_column_builds_2tuples():
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0]})
    fovs, _, z_dropped = regions_from_coordinates_dataframe(df)
    assert z_dropped is False
    assert fovs["A1"] == ((10.0, 10.0),)


def test_load_with_nan_z_drops_the_column():
    df = pd.DataFrame(
        {"region": ["A1", "A1"], "x (mm)": [10.0, 10.5], "y (mm)": [10.0, 10.0], "z (mm)": [3.0, float("nan")]}
    )
    fovs, _, z_dropped = regions_from_coordinates_dataframe(df)
    assert z_dropped is True
    assert fovs["A1"] == ((10.0, 10.0), (10.5, 10.0))


def test_load_with_numeric_string_z_loads():
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": ["3.0"]})
    fovs, _, z_dropped = regions_from_coordinates_dataframe(df)
    assert z_dropped is False
    assert fovs["A1"] == ((10.0, 10.0, 3.0),)


def test_load_with_unparseable_z_drops_the_column():
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": ["not-a-number"]})
    fovs, _, z_dropped = regions_from_coordinates_dataframe(df)
    assert z_dropped is True
    assert fovs["A1"] == ((10.0, 10.0),)


def test_load_with_out_of_range_z_raises():
    bad_z = _def.SOFTWARE_POS_LIMIT.Z_POSITIVE + 1.0
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [bad_z]})
    with pytest.raises(ValueError, match="z"):
        regions_from_coordinates_dataframe(df)


def test_load_missing_required_columns_raises():
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0]})
    with pytest.raises(ValueError, match="region"):
        regions_from_coordinates_dataframe(df)


def test_load_unparseable_xy_raises():
    df = pd.DataFrame({"region": ["B2"], "x (mm)": ["not-a-number"], "y (mm)": [20.0]})
    with pytest.raises(ValueError):
        regions_from_coordinates_dataframe(df)


def test_parfocal_adjusted_z_uses_xeryon_switcher_offset(monkeypatch):
    monkeypatch.setattr(_def, "USE_XERYON", True)
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_1", ["4x", "10x"])
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_2", ["20x", "40x"])
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_2_OFFSET_MM", 2)

    assert parfocal_adjusted_z_mm("10x", "20x", 3.0) == pytest.approx(1.0)
    assert parfocal_adjusted_z_mm("20x", "10x", 1.0) == pytest.approx(3.0)
    assert parfocal_adjusted_z_mm("20x", "40x", 1.0) == pytest.approx(1.0)
    assert parfocal_adjusted_z_mm("4x", "10x", 3.0) == pytest.approx(3.0)
    assert parfocal_adjusted_z_mm("20x", "20x", 1.0) == pytest.approx(1.0)


def test_parfocal_adjusted_z_is_noop_without_switcher(monkeypatch):
    monkeypatch.setattr(_def, "USE_XERYON", False)
    assert parfocal_adjusted_z_mm("10x", "20x", 3.0) == pytest.approx(3.0)


def test_xeryon_objective_position(monkeypatch):
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_1", ["4x"])
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_2", ["20x"])
    assert _def.xeryon_objective_position("4x") == 1
    assert _def.xeryon_objective_position("20x") == 2
    assert _def.xeryon_objective_position("100x") is None


def test_coordinate_rows_for_save_stamps_default_z_and_keeps_existing_z():
    fovs = {"A1": [(10.0, 10.0), (10.5, 10.0, 4.0)], "B2": [(20.0, 20.0)]}
    df = coordinate_rows_for_save(fovs, 3.0)
    assert list(df.columns) == ["region", "x (mm)", "y (mm)", "z (mm)"]
    assert df["region"].tolist() == ["A1", "A1", "B2"]
    assert df["z (mm)"].tolist() == [3.0, 4.0, 3.0]


def test_save_load_round_trip_preserves_z(tmp_path):
    path = tmp_path / "coords.csv"
    coordinate_rows_for_save({"A1": [(10.0, 10.0), (10.5, 10.0)]}, 3.25).to_csv(path, index=False)
    fovs, _, z_dropped = regions_from_coordinates_dataframe(pd.read_csv(path))
    assert z_dropped is False
    assert fovs["A1"] == ((10.0, 10.0, 3.25), (10.5, 10.0, 3.25))


# ---------------------------------------------------------------------------
# Wellplate widget Load <-> Clear toggle (methods called on a stand-in self)
# ---------------------------------------------------------------------------


def _wellplate_cls():
    from squid.ui.widgets.acquisition.wellplate_multipoint import WellplateMultiPointWidget

    return WellplateMultiPointWidget


def _fake_wellplate(loaded: bool, cached_df=None):
    cls = _wellplate_cls()
    published = []
    fake = SimpleNamespace(
        published=published,
        _publish=published.append,
        cached_loaded_coordinates_df=cached_df,
        cached_loaded_file_path="/data/coords.csv" if cached_df is not None else None,
        text_loaded_coordinates=MagicMock(),
        btn_load_scan_coordinates=MagicMock(),
        has_loaded_coordinates=loaded,
        _log=MagicMock(),
    )
    fake._set_has_loaded_coordinates = lambda v: cls._set_has_loaded_coordinates(fake, v)
    fake._publish_loaded_regions = lambda df: cls._publish_loaded_regions(fake, df)
    fake.clear_loaded_coordinates = lambda: cls.clear_loaded_coordinates(fake)
    return fake


def test_clear_loaded_coordinates_resets_state():
    fake = _fake_wellplate(loaded=True, cached_df=pd.DataFrame())

    _wellplate_cls().clear_loaded_coordinates(fake)

    assert any(isinstance(e, ClearScanCoordinatesCommand) for e in fake.published)
    assert fake.cached_loaded_coordinates_df is None
    assert fake.cached_loaded_file_path is None
    fake.text_loaded_coordinates.clear.assert_called_once()
    assert fake.has_loaded_coordinates is False
    fake.btn_load_scan_coordinates.setText.assert_called_with("Load New Coords")


def test_load_or_clear_click_clears_when_loaded():
    fake = _fake_wellplate(loaded=True)
    fake.clear_loaded_coordinates = MagicMock()
    _wellplate_cls().on_load_or_clear_coordinates_clicked(fake)
    fake.clear_loaded_coordinates.assert_called_once()


def test_load_or_clear_click_opens_dialog_when_not_loaded():
    fake = _fake_wellplate(loaded=False)
    fake.load_coordinates = MagicMock()
    module = "squid.ui.widgets.acquisition.wellplate_multipoint"
    with patch(f"{module}.QFileDialog.getOpenFileName", return_value=("/data/some.csv", "")):
        _wellplate_cls().on_load_or_clear_coordinates_clicked(fake)
    fake.load_coordinates.assert_called_once_with("/data/some.csv")


def test_load_or_clear_click_cancelled_dialog_loads_nothing():
    fake = _fake_wellplate(loaded=False)
    fake.load_coordinates = MagicMock()
    module = "squid.ui.widgets.acquisition.wellplate_multipoint"
    with patch(f"{module}.QFileDialog.getOpenFileName", return_value=("", "")):
        _wellplate_cls().on_load_or_clear_coordinates_clicked(fake)
    fake.load_coordinates.assert_not_called()


def test_wellplate_load_coordinates_publishes_z_and_flips_button(tmp_path):
    path = tmp_path / "coords.csv"
    pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [3.0]}).to_csv(path, index=False)
    fake = _fake_wellplate(loaded=False)

    _wellplate_cls().load_coordinates(fake, str(path))

    loads = [e for e in fake.published if isinstance(e, LoadScanCoordinatesCommand)]
    assert len(loads) == 1
    assert loads[0].region_fov_coordinates == {"A1": ((10.0, 10.0, 3.0),)}
    assert fake.has_loaded_coordinates is True
    fake.btn_load_scan_coordinates.setText.assert_called_with("Clear Coords")
    assert fake.cached_loaded_file_path == str(path)


def test_wellplate_load_bad_file_publishes_nothing_and_keeps_state(tmp_path):
    path = tmp_path / "bad.csv"
    bad_z = _def.SOFTWARE_POS_LIMIT.Z_POSITIVE + 1.0
    pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [bad_z]}).to_csv(path, index=False)
    fake = _fake_wellplate(loaded=False)

    with patch("squid.ui.widgets.acquisition.wellplate_multipoint.QMessageBox.warning") as warn:
        _wellplate_cls().load_coordinates(fake, str(path))

    warn.assert_called_once()
    assert fake.published == []
    assert fake.has_loaded_coordinates is False
    assert fake.cached_loaded_coordinates_df is None


def test_restore_cached_coordinates_invalid_cached_df_does_not_raise_and_warns():
    bad_z = _def.SOFTWARE_POS_LIMIT.Z_POSITIVE + 1.0
    bad_df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [bad_z]})
    fake = _fake_wellplate(loaded=False, cached_df=bad_df)

    with patch("squid.ui.widgets.acquisition.wellplate_multipoint.QMessageBox.warning") as warn:
        _wellplate_cls().restore_cached_coordinates(fake)

    warn.assert_called_once()
    fake._log.error.assert_called_once()
    assert fake.has_loaded_coordinates is False
    assert fake.published == []


def test_restore_cached_coordinates_republishes_with_z():
    df = pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [2.5]})
    fake = _fake_wellplate(loaded=False, cached_df=df)

    _wellplate_cls().restore_cached_coordinates(fake)

    loads = [e for e in fake.published if isinstance(e, LoadScanCoordinatesCommand)]
    assert loads[0].region_fov_coordinates == {"A1": ((10.0, 10.0, 2.5),)}
    assert fake.has_loaded_coordinates is True


def test_update_coordinates_leaves_loaded_plan_untouched():
    """Upstream #608 regression: update_coordinates must not regenerate over a loaded plan."""
    fake = SimpleNamespace(
        _is_active_tab=True,
        _log=MagicMock(),
        checkbox_xy=MagicMock(isChecked=MagicMock(return_value=True)),
        combobox_xy_mode=MagicMock(currentText=MagicMock(return_value="Load Coordinates")),
        _publish=MagicMock(),
        has_loaded_coordinates=True,
    )
    _wellplate_cls().update_coordinates(fake, force=True)
    fake._publish.assert_not_called()


def test_dead_save_clear_toggle_machinery_removed():
    cls = _wellplate_cls()
    assert not hasattr(cls, "toggle_coordinate_controls")
    assert not hasattr(cls, "on_save_or_clear_coordinates_clicked")


def test_wellplate_save_coordinates_writes_z_per_objective(tmp_path, monkeypatch):
    monkeypatch.setattr(_def, "USE_XERYON", True)
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_1", ["10x"])
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_2", ["20x"])
    monkeypatch.setattr(_def, "XERYON_OBJECTIVE_SWITCHER_POS_2_OFFSET_MM", 2)
    folder = tmp_path / "plan"
    snapshot = SimpleNamespace(region_fov_coordinates={"A1": ((10.0, 10.0),)})
    fake = SimpleNamespace(
        _current_objective="10x",
        _objective_names=["10x", "20x"],
        _objective_pixel_size_factors={},
        _pixel_size_factor=1.0,
        _cached_z_mm=3.0,
        _log=MagicMock(),
        update_coordinates=MagicMock(),
        _request_scan_coordinates_snapshot=MagicMock(return_value=snapshot),
    )
    module = "squid.ui.widgets.acquisition.wellplate_multipoint"
    with patch(f"{module}.QFileDialog.getSaveFileName", return_value=(str(folder), "")):
        _wellplate_cls().save_coordinates(fake)

    df10 = pd.read_csv(folder / "plan_10x.csv")
    df20 = pd.read_csv(folder / "plan_20x.csv")
    assert df10["z (mm)"].tolist() == [3.0]
    assert df20["z (mm)"].tolist() == [1.0]


# ---------------------------------------------------------------------------
# Fluidics widget loader
# ---------------------------------------------------------------------------


def test_fluidics_widget_load_coordinates_loads_z(tmp_path):
    from squid.ui.widgets.acquisition.fluidics_multipoint import MultiPointWithFluidicsWidget

    path = tmp_path / "coords.csv"
    pd.DataFrame({"region": ["A1"], "x (mm)": [10.0], "y (mm)": [10.0], "z (mm)": [3.0]}).to_csv(path, index=False)
    bus = MagicMock()
    fake = SimpleNamespace(_event_bus=bus, _log=MagicMock())

    MultiPointWithFluidicsWidget.load_coordinates(fake, str(path))

    cmd = bus.publish.call_args[0][0]
    assert isinstance(cmd, LoadScanCoordinatesCommand)
    assert cmd.region_fov_coordinates == {"A1": ((10.0, 10.0, 3.0),)}
    assert cmd.region_centers == {"A1": (10.0, 10.0)}

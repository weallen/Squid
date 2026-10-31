"""PreferencesDialog: file-format menu default and the TIFF compression row (port of upstream aa9107d9).

Kept separate from test_preferences_dialog.py, whose save-and-close tests open modal dialogs. These tests call
the dialog's helpers directly and never open one.
"""

from configparser import ConfigParser

import pytest

import _def
from squid.ui.widgets.config import PreferencesDialog


def _dialog(qtbot, tmp_path, general=None):
    config = ConfigParser()
    config.add_section("GENERAL")
    for key, value in (general or {}).items():
        config.set("GENERAL", key, value)
    path = tmp_path / "machine.ini"
    with open(path, "w") as f:
        config.write(f)
    dialog = PreferencesDialog(config, str(path))
    qtbot.addWidget(dialog)
    return dialog, path


@pytest.fixture(autouse=True)
def _restore_def(monkeypatch):
    # The dialog updates _def live; keep that from leaking into other tests.
    monkeypatch.setattr(_def, "FILE_SAVING_OPTION", _def.FILE_SAVING_OPTION)
    monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", _def.TIFF_COMPRESSION_LEVEL)
    monkeypatch.setattr(_def, "ZARR_COMPRESSION", _def.ZARR_COMPRESSION)
    monkeypatch.setattr(_def, "ZARR_CHUNK_MODE", _def.ZARR_CHUNK_MODE)
    monkeypatch.setattr(_def, "ZARR_USE_6D_FOV_DIMENSION", _def.ZARR_USE_6D_FOV_DIMENSION)
    monkeypatch.setattr(_def, "DEFAULT_SAVING_PATH", _def.DEFAULT_SAVING_PATH)


class TestFileFormatMenu:
    def test_shows_the_running_format_when_config_has_no_key(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", _def.FileSavingOption.INDIVIDUAL_IMAGES)
        dialog, _ = _dialog(qtbot, tmp_path)
        assert dialog.file_saving_combo.currentText() == "INDIVIDUAL_IMAGES"
        assert not any(c[0] == "File Saving Format" for c in dialog._get_changes())

    def test_follows_a_live_change_made_earlier(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", _def.FileSavingOption.ZARR_V3)
        dialog, _ = _dialog(qtbot, tmp_path)
        assert dialog.file_saving_combo.currentText() == "ZARR_V3"

    def test_config_value_wins_over_running_value(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", _def.FileSavingOption.INDIVIDUAL_IMAGES)
        dialog, _ = _dialog(qtbot, tmp_path, {"file_saving_option": "MULTI_PAGE_TIFF"})
        assert dialog.file_saving_combo.currentText() == "MULTI_PAGE_TIFF"

    def test_change_away_from_the_running_default_is_detected(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", _def.FileSavingOption.INDIVIDUAL_IMAGES)
        dialog, _ = _dialog(qtbot, tmp_path)
        dialog.file_saving_combo.setCurrentText("OME_TIFF")
        assert ("File Saving Format", "INDIVIDUAL_IMAGES", "OME_TIFF", False) in dialog._get_changes()


class TestTiffCompressionRow:
    def test_initialized_from_running_value(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 3)
        dialog, _ = _dialog(qtbot, tmp_path)
        assert dialog.tiff_compression_spinbox.value() == 3
        assert dialog.tiff_compression_spinbox.minimum() == 0
        assert dialog.tiff_compression_spinbox.maximum() == 9
        assert not any(c[0] == "TIFF Compression Level" for c in dialog._get_changes())

    def test_out_of_range_config_value_is_not_a_change(self, qtbot, tmp_path):
        dialog, _ = _dialog(qtbot, tmp_path, {"tiff_compression_level": "15"})
        assert dialog.tiff_compression_spinbox.value() == 9
        assert not any(c[0] == "TIFF Compression Level" for c in dialog._get_changes())

    @pytest.mark.parametrize(
        "fmt, visible",
        [("INDIVIDUAL_IMAGES", True), ("MULTI_PAGE_TIFF", True), ("OME_TIFF", False), ("ZARR_V3", False)],
    )
    def test_visible_only_for_formats_that_support_it(self, qtbot, tmp_path, fmt, visible):
        dialog, _ = _dialog(qtbot, tmp_path)
        dialog.file_saving_combo.setCurrentText(fmt)
        assert dialog.tiff_compression_spinbox.isVisibleTo(dialog) is visible
        assert dialog.tiff_compression_label.isVisibleTo(dialog) is visible
        assert dialog.zarr_compression_combo.isVisibleTo(dialog) is (fmt == "ZARR_V3")

    def test_change_is_detected_saved_and_applied_live(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 0)
        dialog, path = _dialog(qtbot, tmp_path)
        dialog.tiff_compression_spinbox.setValue(6)

        assert ("TIFF Compression Level", "0", "6", False) in dialog._get_changes()

        dialog._apply_settings()
        saved = ConfigParser()
        saved.read(path)
        assert saved.get("GENERAL", "tiff_compression_level") == "6"
        assert _def.TIFF_COMPRESSION_LEVEL == 6

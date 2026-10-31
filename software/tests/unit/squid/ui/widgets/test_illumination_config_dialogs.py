"""Illumination configurator dialogs edit a copy; Save publishes, Cancel leaks nothing (upstream edc13253, #610)."""

import pytest
from qtpy.QtWidgets import QDoubleSpinBox, QMessageBox

from squid.core.config.models.illumination_config import (
    IlluminationChannel,
    IlluminationChannelConfig,
    IlluminationType,
)
from squid.core.config.repository import ConfigRepository
from squid.ui.widgets.channel_config_dialogs import (
    AddIlluminationChannelDialog,
    ControllerPortMappingDialog,
    IlluminationChannelConfiguratorDialog,
    SourceCodeWidget,
)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "machine_configs").mkdir()
    (tmp_path / "user_profiles").mkdir()
    repo = ConfigRepository(base_path=tmp_path)
    repo.save_illumination_config(
        IlluminationChannelConfig(
            controller_port_mapping={"D1": 11, "USB1": 0},
            channels=[
                IlluminationChannel(
                    name="405", type=IlluminationType.EPI_ILLUMINATION, controller_port="D1", wavelength_nm=405
                ),
                IlluminationChannel(name="BF", type=IlluminationType.TRANSILLUMINATION, controller_port="USB1"),
            ],
        )
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    return repo


def _max_output_widget(dialog, row) -> QDoubleSpinBox:
    return dialog.table.cellWidget(row, dialog.COL_MAX_OUTPUT)


def test_cancel_leaves_shared_config_untouched(qtbot, repo):
    dialog = IlluminationChannelConfiguratorDialog(repo)
    qtbot.addWidget(dialog)
    dialog.illumination_config.channels.pop()  # e.g. Remove Channel
    dialog.illumination_config.channels[0].name = "renamed"
    dialog.reject()

    shared = repo.get_illumination_config()
    assert [ch.name for ch in shared.channels] == ["405", "BF"]


def test_save_publishes_max_output_and_edits(qtbot, repo, tmp_path):
    dialog = IlluminationChannelConfiguratorDialog(repo)
    qtbot.addWidget(dialog)
    assert _max_output_widget(dialog, 1).value() == 1.0  # missing in YAML -> full output
    _max_output_widget(dialog, 1).setValue(0.25)
    dialog._save_changes()

    assert repo.get_illumination_config().channels[1].max_output == 0.25
    assert ConfigRepository(base_path=tmp_path).get_illumination_config().channels[1].max_output == 0.25


def test_type_change_applies_default_max_output(qtbot, repo):
    dialog = IlluminationChannelConfiguratorDialog(repo)
    qtbot.addWidget(dialog)
    dialog.table.cellWidget(0, dialog.COL_TYPE).setCurrentText("transillumination")
    assert _max_output_widget(dialog, 0).value() == pytest.approx(0.2)


def test_add_channel_dialog_defaults_max_output_by_type(qtbot, repo):
    dialog = AddIlluminationChannelDialog(repo.get_illumination_config())
    qtbot.addWidget(dialog)
    assert dialog.max_output_spin.value() == 1.0  # epi first
    dialog.type_combo.setCurrentText("transillumination")
    assert dialog.get_channel_data()["max_output"] == pytest.approx(0.2)


def test_port_mapping_save_keeps_unsaved_channel_edits_in_configurator(qtbot, repo):
    dialog = IlluminationChannelConfiguratorDialog(repo)
    qtbot.addWidget(dialog)
    dialog.illumination_config.channels[0].wavelength_nm = 410  # unsaved edit in the working copy

    mapping = ControllerPortMappingDialog(repo)
    qtbot.addWidget(mapping)
    mapping.signal_mappings_updated.connect(dialog._on_port_mappings_updated)
    for row in range(mapping.table.rowCount()):
        if mapping.table.item(row, 0).text() == "D2":
            widget: SourceCodeWidget = mapping.table.cellWidget(row, 1)
            widget.set_source_code(12)
    mapping._save_changes()

    # Saved mapping is visible through the shared repository, channels untouched
    shared = repo.get_illumination_config()
    assert shared.controller_port_mapping["D2"] == 12
    assert shared.channels[0].wavelength_nm == 405
    # The configurator's working copy picks up the mapping and keeps its unsaved edit
    assert dialog.illumination_config.controller_port_mapping["D2"] == 12
    assert dialog.illumination_config.channels[0].wavelength_nm == 410


def test_port_mapping_cancel_leaves_shared_config_untouched(qtbot, repo):
    mapping = ControllerPortMappingDialog(repo)
    qtbot.addWidget(mapping)
    mapping.illumination_config.controller_port_mapping["D1"] = 99
    mapping.reject()
    assert repo.get_illumination_config().controller_port_mapping["D1"] == 11

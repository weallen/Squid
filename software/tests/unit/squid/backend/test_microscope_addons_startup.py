"""Startup must survive a filter-wheel homing failure (upstream 72bdd2fc, #559, startup part)."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import squid.core.config

from squid.backend.microscope import MicroscopeAddons


def test_prepare_for_use_continues_when_filter_wheel_homing_fails(caplog, monkeypatch):
    monkeypatch.setattr(squid.core.config, "get_filter_wheel_config", lambda: SimpleNamespace(indices=[1]))
    wheel = MagicMock()
    wheel.home.side_effect = RuntimeError("CMD_EXECUTION_ERROR after homing")
    piezo = MagicMock()
    addons = MicroscopeAddons(emission_filter_wheel=wheel, piezo_stage=piezo)

    with caplog.at_level(logging.ERROR):
        addons.prepare_for_use()

    wheel.initialize.assert_called_once()
    wheel.home.assert_called_once()
    piezo.home.assert_called_once()  # the rest of startup still ran
    assert any("Filter wheel homing failed" in r.getMessage() for r in caplog.records)

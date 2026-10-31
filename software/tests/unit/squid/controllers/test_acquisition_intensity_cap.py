"""Acquisition paths clamp illumination intensity to the channel's max output (upstream edc13253, #610)."""

from unittest.mock import MagicMock

import pytest

from squid.backend.controllers.multipoint.multi_point_worker import MultiPointWorker
from squid.backend.services.acquisition_service import AcquisitionService


def _config(intensity: float, source: int = 11):
    config = MagicMock()
    config.name = "BF LED matrix full"
    config.illumination_source = source
    config.illumination_intensity = intensity
    config.exposure_time = 10.0
    config.analog_gain = 0.0
    config.emission_filter_position = None
    return config


def _ccm(cap):
    ccm = MagicMock()
    ccm.get_intensity_cap_percent.return_value = cap
    return ccm


def _worker(ccm):
    worker = MultiPointWorker.__new__(MultiPointWorker)
    worker._log = MagicMock()
    worker._camera_service = MagicMock()
    worker._illumination_service = MagicMock()
    worker._filter_wheel_service = None
    worker.channelConfigurationManager = ccm
    return worker


@pytest.mark.parametrize("intensity, cap, expected", [(80.0, 20.0, 20.0), (15.0, 20.0, 15.0)])
def test_worker_applies_capped_power(intensity, cap, expected):
    worker = _worker(_ccm(cap))
    worker._apply_channel_mode(_config(intensity))
    worker._illumination_service.set_channel_power.assert_called_once_with(11, expected)
    assert worker._log.warning.called == (intensity > cap)


def test_worker_without_cap_source_is_unchanged():
    worker = _worker(object())  # no get_intensity_cap_percent
    worker._apply_channel_mode(_config(80.0))
    worker._illumination_service.set_channel_power.assert_called_once_with(11, 80.0)


def _service(ccm=None):
    return AcquisitionService(MagicMock(), MagicMock(), illumination_service=MagicMock(), channel_config_service=ccm)


def test_acquisition_service_turn_on_clamps(caplog):
    service = _service(_ccm(20.0))
    with caplog.at_level("WARNING"):
        assert service.turn_on_illumination(_config(80.0)) is True
    service._illumination.set_channel_power.assert_called_once_with(11, 20.0)
    assert any("Clamping" in r.getMessage() for r in caplog.records)


def test_acquisition_service_set_power_clamps():
    service = _service(_ccm(25.0))
    service._set_illumination_power(_config(90.0))
    service._illumination.set_channel_power.assert_called_once_with(11, 25.0)


def test_acquisition_service_without_config_service_is_unchanged():
    service = _service(None)
    service._set_illumination_power(_config(90.0))
    service._illumination.set_channel_power.assert_called_once_with(11, 90.0)

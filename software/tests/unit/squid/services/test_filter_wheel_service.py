"""FilterWheelService sends a channel's emission position to the first configured wheel (upstream #738)."""

from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from squid.backend.services.filter_wheel_service import FilterWheelService


class _RecordingWheel:
    """An emission filter wheel on the given indices that records the positions it is sent."""

    def __init__(self, indices: List[int]):
        self._indices = indices
        self.positions: List[Dict[int, int]] = []

    @property
    def available_filter_wheels(self) -> List[int]:
        return self._indices

    def set_filter_wheel_position(self, positions: Dict[int, int]) -> None:
        missing = [i for i in positions if i not in self._indices]
        if missing:
            raise ValueError(f"Filter wheel index {missing[0]} not found")
        self.positions.append(positions)

    def get_filter_wheel_position(self, *_args):
        raise RuntimeError("not needed")


def _service(wheel) -> FilterWheelService:
    return FilterWheelService(wheel, MagicMock())


@pytest.mark.parametrize("indices", [[1], [2], [2, 3]])
def test_emission_position_goes_to_first_configured_wheel(indices):
    wheel = _RecordingWheel(indices)
    svc = _service(wheel)

    assert svc.set_emission_filter_position(3) is True
    assert wheel.positions == [{indices[0]: 3}]


def test_no_configured_wheel_sends_nothing():
    wheel = _RecordingWheel([])
    svc = _service(wheel)

    assert svc.set_emission_filter_position(3) is False
    assert wheel.positions == []


def test_no_hardware_is_noop():
    svc = _service(None)
    assert svc.available_filter_wheels() == []
    assert svc.set_emission_filter_position(1) is False

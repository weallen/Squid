"""X-Light skips the emission wheel command when already at the target position (upstream #602)."""

from unittest.mock import MagicMock, patch

import pytest

from squid.backend.drivers.lighting.xlight import XLight


def _xlight() -> XLight:
    """An XLight with a mocked serial port, bypassing connection/protocol detection."""
    with patch.object(XLight, "_connect_and_detect", return_value="V2"), patch.object(XLight, "print_config"):
        xl = XLight("SN", sleep_time_for_wheel=0, disable_emission_filter_wheel=False)
    xl.serial_connection = MagicMock()
    xl.serial_connection.write_and_check.side_effect = lambda cmd, expected, **_: expected
    return xl


def _writes(xl):
    return [c.args[0] for c in xl.serial_connection.write_and_check.call_args_list] + [
        c.args[0] for c in xl.serial_connection.write.call_args_list
    ]


def test_unknown_position_always_sends():
    xl = _xlight()
    assert xl.emission_wheel_pos is None
    xl.set_emission_filter(1)
    assert _writes(xl) == ["B1\r"]


def test_same_position_is_skipped_int_and_str():
    xl = _xlight()
    xl.set_emission_filter(2)
    xl.set_emission_filter(2)
    xl.set_emission_filter("2")
    assert _writes(xl) == ["B2\r"]


def test_different_position_is_sent():
    xl = _xlight()
    xl.set_emission_filter(2)
    xl.set_emission_filter(3)
    assert _writes(xl) == ["B2\r", "B3\r"]


def test_extraction_always_sends_and_next_plain_call_is_not_skipped():
    xl = _xlight()
    xl.set_emission_filter(2)
    xl.set_emission_filter(2, extraction=True)
    xl.set_emission_filter(2)
    xl.set_emission_filter(2)
    assert _writes(xl) == ["B2\r", "B2m\r", "B2\r"]


def test_failed_write_leaves_position_unknown_so_it_is_retried():
    xl = _xlight()
    xl.set_emission_filter(2)
    xl.serial_connection.write_and_check.side_effect = RuntimeError("serial timeout")
    with pytest.raises(RuntimeError):
        xl.set_emission_filter(3)
    assert xl.emission_wheel_pos is None
    xl.serial_connection.write_and_check.side_effect = lambda cmd, expected, **_: expected
    xl.set_emission_filter(2)
    assert _writes(xl)[-1] == "B2\r"


def test_non_validated_write_also_skips():
    xl = _xlight()
    with patch("squid.backend.drivers.lighting.xlight.time.sleep"):
        xl.set_emission_filter(4, validate=False)
        xl.set_emission_filter(4, validate=False)
    assert xl.serial_connection.write.call_count == 1

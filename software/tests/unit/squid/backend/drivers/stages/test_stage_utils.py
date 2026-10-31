import builtins
import logging
from unittest.mock import MagicMock, call

import pytest

import squid.core.config
from squid.core.abc import Pos
from squid.backend.drivers.stages import stage_utils


def test_get_cached_position_returns_none_when_cache_file_is_missing(tmp_path):
    assert stage_utils.get_cached_position(cache_path=str(tmp_path / "missing.txt")) is None


@pytest.mark.parametrize(
    "contents",
    [
        pytest.param(b"garbage", id="garbage"),
        pytest.param(b"1.0,2.0", id="too-few-fields"),
        pytest.param(b"1.0,2.0,3.0,4.0", id="too-many-fields"),
        pytest.param(b"1.0,abc,3.0", id="bad-field"),
        pytest.param(b"", id="empty"),
        pytest.param(b"nan,2.0,3.0", id="nan"),
        pytest.param(b"1.0,inf,3.0", id="inf"),
        pytest.param(b"\xff\xfe\x00\x80 not text", id="undecodable"),
    ],
)
def test_get_cached_position_treats_corrupted_file_as_no_cache(tmp_path, caplog, contents):
    """A corrupted cache must not raise (it would abort startup); it warns and behaves like a missing cache."""
    cache_path = tmp_path / "last_coords.txt"
    cache_path.write_bytes(contents)

    with caplog.at_level(logging.WARNING):
        assert stage_utils.get_cached_position(cache_path=str(cache_path)) is None

    assert any(
        r.levelno == logging.WARNING and str(cache_path) in r.getMessage() for r in caplog.records
    ), "expected a warning naming the corrupted cache file"


def test_get_cached_position_rejects_a_file_larger_than_the_read_cap(tmp_path, caplog):
    """A valid prefix padded past the read cap must be rejected, not parsed from the truncated prefix."""
    cache_path = tmp_path / "last_coords.txt"
    valid_prefix = "11.0,22.0,1.0"
    padding = " " * (stage_utils._MAX_CACHE_BYTES - len(valid_prefix))
    cache_path.write_text(valid_prefix + padding + "garbage past the cap")

    with caplog.at_level(logging.WARNING):
        assert stage_utils.get_cached_position(cache_path=str(cache_path)) is None

    assert any(r.levelno == logging.WARNING and str(cache_path) in r.getMessage() for r in caplog.records)


def test_get_cached_position_rejects_a_second_line(tmp_path):
    """Only a single coordinate triple is a valid cache; extra lines mean the file is not ours."""
    cache_path = tmp_path / "last_coords.txt"
    cache_path.write_text("11.0,22.0,1.0\n44.0,55.0,2.0\n")

    assert stage_utils.get_cached_position(cache_path=str(cache_path)) is None


def test_get_cached_position_warning_shows_the_corrupt_contents(tmp_path, caplog):
    """The warning must quote what was in the file, so a bad cache can be diagnosed from a log alone."""
    cache_path = tmp_path / "last_coords.txt"
    cache_path.write_text("1.0,not-a-number,3.0")

    with caplog.at_level(logging.WARNING):
        stage_utils.get_cached_position(cache_path=str(cache_path))

    assert any("contents='1.0,not-a-number,3.0'" in r.getMessage() for r in caplog.records)


def test_cache_position_round_trips_and_leaves_no_tmp_file(tmp_path):
    cache_path = tmp_path / "last_coords.txt"
    pos = Pos(x_mm=11.111111, y_mm=22.222222, z_mm=1.333333, theta_rad=None)

    stage_utils.cache_position(pos=pos, stage_config=squid.core.config.get_stage_config(), cache_path=str(cache_path))

    assert stage_utils.get_cached_position(cache_path=str(cache_path)) == pos
    assert [p.name for p in tmp_path.iterdir()] == ["last_coords.txt"]


class _WriteFailsFile:
    """Wraps a real file object so opening (and truncating) succeeds but writing fails."""

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def __enter__(self):
        self._wrapped.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._wrapped.__exit__(*exc_info)

    def write(self, _data):
        raise OSError("simulated disk full")


def test_cache_position_keeps_the_previous_position_when_the_write_fails(tmp_path, monkeypatch):
    """An interrupted write must not leave a truncated cache behind - that is what corrupts the file."""
    cache_path = str(tmp_path / "last_coords.txt")
    stage_config = squid.core.config.get_stage_config()
    already_cached = Pos(x_mm=11.0, y_mm=22.0, z_mm=1.0, theta_rad=None)
    stage_utils.cache_position(pos=already_cached, stage_config=stage_config, cache_path=cache_path)

    real_open = builtins.open
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: _WriteFailsFile(real_open(*args, **kwargs)))
    with pytest.raises(OSError):
        stage_utils.cache_position(
            pos=Pos(x_mm=33.0, y_mm=44.0, z_mm=2.0, theta_rad=None),
            stage_config=stage_config,
            cache_path=cache_path,
        )
    monkeypatch.undo()

    assert stage_utils.get_cached_position(cache_path=cache_path) == already_cached


# --- f453dc18 (#692): X/Y-only Cephla stage (homing_enabled_z = False) ------------------------------------------


def _pos_within_limits(stage_config, **overrides):
    """A Pos in the middle of every axis' travel, with any coordinate overridden."""
    mid = {
        f"{axis}_mm": (cfg.MIN_POSITION + cfg.MAX_POSITION) / 2
        for axis, cfg in (("x", stage_config.X_AXIS), ("y", stage_config.Y_AXIS), ("z", stage_config.Z_AXIS))
    }
    return Pos(theta_rad=None, **{**mid, **overrides})


def test_cache_position_skips_the_z_soft_limits_when_z_is_not_validated(tmp_path):
    """An XY-only Cephla stage reports the raw firmware Z (0 at boot, below the Z soft floor); with
    validate_z=False that must not block caching X/Y."""
    cache_path = str(tmp_path / "last_coords.txt")
    stage_config = squid.core.config.get_stage_config()
    pos = _pos_within_limits(stage_config, z_mm=stage_config.Z_AXIS.MIN_POSITION - 1.0)

    with pytest.raises(ValueError, match="z="):
        stage_utils.cache_position(pos=pos, stage_config=stage_config, cache_path=cache_path)
    stage_utils.cache_position(pos=pos, stage_config=stage_config, cache_path=cache_path, validate_z=False)

    assert stage_utils.get_cached_position(cache_path=cache_path) == pos


def test_cache_position_still_validates_x_and_y_when_z_is_not(tmp_path):
    cache_path = str(tmp_path / "last_coords.txt")
    stage_config = squid.core.config.get_stage_config()
    pos = _pos_within_limits(stage_config, x_mm=stage_config.X_AXIS.MIN_POSITION - 1.0)

    with pytest.raises(ValueError, match="not cacheable.*x="):
        stage_utils.cache_position(pos=pos, stage_config=stage_config, cache_path=cache_path, validate_z=False)

    assert stage_utils.get_cached_position(cache_path=cache_path) is None


@pytest.mark.parametrize("homing_enabled_z", [True, False])
def test_z_is_referenced_follows_homing_enabled_z(monkeypatch, homing_enabled_z):
    monkeypatch.setattr(stage_utils._def, "HOMING_ENABLED_Z", homing_enabled_z)
    assert stage_utils.z_is_referenced() is homing_enabled_z


def _run_startup_restore(monkeypatch, *, homing_enabled_z, cached):
    """Drive ApplicationContext._initialize_hardware with a mocked stage service and return its calls."""
    import _def
    from squid.application import ApplicationContext

    monkeypatch.setattr(_def, "HOMING_ENABLED_X", True)
    monkeypatch.setattr(_def, "HOMING_ENABLED_Y", True)
    monkeypatch.setattr(_def, "HOMING_ENABLED_Z", homing_enabled_z)
    monkeypatch.setattr(stage_utils, "get_cached_position", lambda *args, **kwargs: cached)

    ctx = object.__new__(ApplicationContext)
    ctx._microscope = MagicMock()
    ctx._controllers = MagicMock()
    ctx._skip_init = False
    ctx._log = logging.getLogger("test_startup_restore")
    ctx._camera_frame_callback_id = None
    stage_service = MagicMock()
    ctx._services = {"stage": stage_service}

    ctx._initialize_hardware()
    return [c for c in stage_service.mock_calls if c[0] == "move_to"]


def test_startup_restores_cached_xy_but_not_z_when_z_is_not_referenced(monkeypatch):
    cached = Pos(x_mm=23.0, y_mm=31.0, z_mm=1.5, theta_rad=None)

    moves = _run_startup_restore(monkeypatch, homing_enabled_z=False, cached=cached)

    assert moves == [call.move_to(x_mm=23.0, y_mm=31.0, blocking=True)]


def test_startup_restores_cached_xyz_when_z_is_referenced(monkeypatch):
    import _def

    cached = Pos(x_mm=23.0, y_mm=31.0, z_mm=50.0, theta_rad=None)  # above any Z_HOME_SAFETY_POINT

    moves = _run_startup_restore(monkeypatch, homing_enabled_z=True, cached=cached)

    assert moves == [
        call.move_to(x_mm=23.0, y_mm=31.0, blocking=True),
        call.move_to(z_mm=50.0, blocking=True),
    ]
    assert float(_def.Z_HOME_SAFETY_POINT) / 1000.0 < 50.0


def test_startup_without_cache_moves_z_to_safety_only_when_referenced(monkeypatch):
    assert _run_startup_restore(monkeypatch, homing_enabled_z=False, cached=None) == []
    moves = _run_startup_restore(monkeypatch, homing_enabled_z=True, cached=None)
    assert len(moves) == 1 and set(moves[0].kwargs) == {"z_mm", "blocking"}

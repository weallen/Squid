"""Tests for optional zlib compression of saved TIFFs (_def.TIFF_COMPRESSION_LEVEL), ported from upstream aa9107d9."""

import os
import time

import imageio.v2 as imageio
import numpy as np
import pytest
import tifffile

import _def
from _def import FileSavingOption, tiff_compression_level_from_config
from squid.backend.controllers.multipoint.job_processing import (
    CaptureInfo,
    JobImage,
    SaveImageJob,
    SaveOMETiffJob,
    SaveSettings,
    SaveZarrJob,
)
from squid.backend.controllers.multipoint.multi_point_worker import save_job_classes_for_format
from squid.backend.io import utils_acquisition
from squid.core.config.models import AcquisitionChannel, CameraSettings, IlluminationSettings
import squid.core.abc


@pytest.fixture(autouse=True)
def _real_disk_io(monkeypatch):
    # SaveImageJob short-circuits to a simulated write when simulated disk I/O is on.
    monkeypatch.setattr(_def, "SIMULATED_DISK_IO_ENABLED", False)


@pytest.fixture
def channel():
    return AcquisitionChannel(
        name="BF LED matrix full",
        display_color="#FFFFFF",
        camera=1,
        illumination_settings=IlluminationSettings(illumination_channel="BF LED matrix full", intensity=5.0),
        camera_settings=CameraSettings(exposure_time_ms=10.0, gain_mode=1.0),
        z_offset_um=0.0,
    )


@pytest.fixture
def compressible_image():
    """A frame with the smooth structure of a real image, so compression can do something."""
    y, x = np.mgrid[0:256, 0:256]
    return ((np.sin(x / 16) * np.cos(y / 24) + 1) * 8000).astype(np.uint16)


def capture_info(save_directory, channel, file_id="0_0_0"):
    return CaptureInfo(
        position=squid.core.abc.Pos(x_mm=1.0, y_mm=2.0, z_mm=3.0, theta_rad=None),
        z_index=0,
        capture_time=time.time(),
        configuration=channel,
        save_directory=str(save_directory),
        file_id=file_id,
        region_id=1,
        fov=0,
        configuration_idx=0,
        z_piezo_um=None,
        time_point=0,
    )


def save_individual_image(image, save_directory, channel, level, file_id="0_0_0"):
    utils_acquisition.save_image(
        image=image,
        file_id=file_id,
        save_directory=str(save_directory),
        config=channel,
        is_color=False,
        tiff_compression_level=level,
    )
    return utils_acquisition.get_image_filepath(str(save_directory), file_id, channel.name, image.dtype)


def save_stack_page(image, save_directory, channel, level):
    info = capture_info(save_directory, channel)
    job = SaveImageJob(
        capture_info=info,
        capture_image=JobImage(image_array=image),
        save_settings=SaveSettings(file_saving_option=FileSavingOption.MULTI_PAGE_TIFF, tiff_compression_level=level),
    )
    assert job.run()
    return save_directory / f"{info.region_id}_{info.fov:0{_def.FILE_ID_PADDING}}_stack.tiff"


class TestTiffCompressionLevelFromConfig:
    @pytest.mark.parametrize("value, expected", [(0, 0), (6, 6), (6.5, 6), (12, 9), (-1, 0)])
    def test_limited_to_the_zlib_levels(self, value, expected):
        assert tiff_compression_level_from_config(value) == expected

    @pytest.mark.parametrize("value", ["fast", "", None])
    def test_not_a_number_means_uncompressed(self, value):
        """A bad value in the machine config must not keep the software from starting."""
        assert tiff_compression_level_from_config(value) == 0

    def test_default_is_uncompressed(self):
        assert _def.TIFF_COMPRESSION_LEVEL == 0


class TestCompressionKwargs:
    def test_level_zero_writes_no_compression_arguments(self):
        assert utils_acquisition.tiff_compression_kwargs(0) == {}

    def test_level_selects_zlib_with_the_predictor(self):
        assert utils_acquisition.tiff_compression_kwargs(6) == {
            "compression": "zlib",
            "compressionargs": {"level": 6},
            "predictor": True,
        }


class TestIndividualImages:
    def test_uncompressed_by_default(self, tmp_path, channel, compressible_image):
        path = save_individual_image(compressible_image, tmp_path, channel, level=0)

        with tifffile.TiffFile(path) as tif:
            assert tif.pages[0].compression == tifffile.COMPRESSION.NONE

    def test_compressed_and_lossless(self, tmp_path, channel, compressible_image):
        path = save_individual_image(compressible_image, tmp_path, channel, level=6)

        with tifffile.TiffFile(path) as tif:
            page = tif.pages[0]
            assert page.compression == tifffile.COMPRESSION.ADOBE_DEFLATE
            assert page.predictor == tifffile.PREDICTOR.HORIZONTAL
        np.testing.assert_array_equal(tifffile.imread(path), compressible_image)

    def test_smaller_than_uncompressed(self, tmp_path, channel, compressible_image):
        off_dir = tmp_path / "off"
        on_dir = tmp_path / "on"
        off_dir.mkdir()
        on_dir.mkdir()

        uncompressed = save_individual_image(compressible_image, off_dir, channel, level=0)
        compressed = save_individual_image(compressible_image, on_dir, channel, level=6)

        assert os.path.getsize(compressed) < os.path.getsize(uncompressed)

    def test_non_tiff_format_is_unaffected(self, tmp_path, channel, monkeypatch):
        """8 bit images go to IMAGE_FORMAT (bmp by default), whose plugin rejects these arguments."""
        monkeypatch.setattr(_def.Acquisition, "IMAGE_FORMAT", "bmp")
        image = np.full((32, 32), 42, dtype=np.uint8)

        path = save_individual_image(image, tmp_path, channel, level=6)

        assert path.endswith(".bmp")
        np.testing.assert_array_equal(imageio.imread(path), image)


class TestMultiPageTiff:
    def test_uncompressed_by_default(self, tmp_path, channel, compressible_image):
        path = save_stack_page(compressible_image, tmp_path, channel, level=0)

        with tifffile.TiffFile(path) as tif:
            assert tif.pages[0].compression == tifffile.COMPRESSION.NONE

    def test_compressed_and_lossless(self, tmp_path, channel, compressible_image):
        path = save_stack_page(compressible_image, tmp_path, channel, level=6)

        with tifffile.TiffFile(path) as tif:
            page = tif.pages[0]
            assert page.compression == tifffile.COMPRESSION.ADOBE_DEFLATE
            assert page.predictor == tifffile.PREDICTOR.HORIZONTAL
            # The channel name in PageName (285) and the JSON metadata must survive compression.
            assert page.tags[285].value.rstrip("\x00") == channel.name
        np.testing.assert_array_equal(tifffile.imread(path), compressible_image)


class TestSaveSettings:
    def test_job_uses_the_settings_it_carries_not_def(self, tmp_path, channel, compressible_image, monkeypatch):
        """The job runs in a subprocess whose _def can predate a change made in Preferences."""
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", FileSavingOption.INDIVIDUAL_IMAGES)
        monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 0)
        path = save_stack_page(compressible_image, tmp_path, channel, level=6)
        with tifffile.TiffFile(path) as tif:
            assert tif.pages[0].compression == tifffile.COMPRESSION.ADOBE_DEFLATE

    def test_snapshot_reads_def_at_creation(self, monkeypatch):
        monkeypatch.setattr(_def, "FILE_SAVING_OPTION", FileSavingOption.MULTI_PAGE_TIFF)
        monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 4)
        settings = SaveSettings()
        monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 9)
        assert settings.file_saving_option == FileSavingOption.MULTI_PAGE_TIFF
        assert settings.tiff_compression_level == 4
        with pytest.raises(Exception):
            settings.tiff_compression_level = 1  # frozen

    @pytest.mark.parametrize(
        "file_saving_option, expected",
        [
            (FileSavingOption.INDIVIDUAL_IMAGES, [SaveImageJob]),
            (FileSavingOption.MULTI_PAGE_TIFF, [SaveImageJob]),
            (FileSavingOption.OME_TIFF, [SaveOMETiffJob]),
            (FileSavingOption.ZARR_V3, [SaveZarrJob]),
        ],
    )
    def test_save_job_classes_for_format(self, file_saving_option, expected):
        assert save_job_classes_for_format(file_saving_option) == expected


@pytest.mark.parametrize(
    "fmt, job_class",
    [
        (FileSavingOption.MULTI_PAGE_TIFF, SaveImageJob),
        (FileSavingOption.OME_TIFF, SaveOMETiffJob),
        (FileSavingOption.ZARR_V3, SaveZarrJob),
    ],
)
def test_worker_uses_settings_changed_after_import(monkeypatch, fmt, job_class):
    """A Preferences change made after startup applies to the next acquisition (the worker used to read
    FILE_SAVING_OPTION from an import-time `from _def import ...`)."""
    from tests.unit.control.core.acquisition.test_multi_point_worker_services import _make_worker

    monkeypatch.setattr(_def.Acquisition, "USE_MULTIPROCESSING", False)
    monkeypatch.setattr(_def, "FILE_SAVING_OPTION", fmt)
    monkeypatch.setattr(_def, "TIFF_COMPRESSION_LEVEL", 5)
    worker = _make_worker()
    assert worker._save_settings == SaveSettings(file_saving_option=fmt, tiff_compression_level=5)
    save_classes = [cls for cls, _ in worker._job_runners if cls in (SaveImageJob, SaveOMETiffJob, SaveZarrJob)]
    assert save_classes == [job_class]

"""Focus-measure regression tests (ported from upstream #679).

LAPE used a CV_16S Laplacian for 8-bit images; squaring int16 wrapped around, so sharp 8-bit images
could score lower than blurred ones (and even negative).
"""

import cv2
import numpy as np
import pytest

from _def import FocusMeasureOperator
from squid.core.utils import hardware_utils, image_processing


def _binary_amplitude_image(dtype, shape=(256, 256), seed=0) -> np.ndarray:
    """Random (non-periodic) 0/dtype-max image: every pixel edge at full contrast, so maximally sharp."""
    rng = np.random.default_rng(seed)
    return ((rng.random(shape) > 0.5) * np.iinfo(dtype).max).astype(dtype)


@pytest.mark.parametrize("sigma", [1, 2])
@pytest.mark.parametrize("method", list(FocusMeasureOperator))
@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_focus_measure_sharp_scores_higher_than_blurred(dtype, method, sigma) -> None:
    sharp = _binary_amplitude_image(dtype)
    blurred = cv2.GaussianBlur(sharp, (0, 0), sigma)

    assert hardware_utils.calculate_focus_measure(sharp, method) > hardware_utils.calculate_focus_measure(
        blurred, method
    )


def test_focus_measure_lape_non_negative_for_uint8() -> None:
    sharp = _binary_amplitude_image(np.uint8)
    blurred = cv2.GaussianBlur(sharp, (0, 0), 1)

    assert hardware_utils.calculate_focus_measure(sharp, FocusMeasureOperator.LAPE) >= 0
    assert hardware_utils.calculate_focus_measure(blurred, FocusMeasureOperator.LAPE) >= 0


def test_focus_measure_lape_independent_of_dtype_for_identical_values() -> None:
    as_uint8 = _binary_amplitude_image(np.uint8)
    as_uint16 = as_uint8.astype(np.uint16)

    assert hardware_utils.calculate_focus_measure(as_uint8, FocusMeasureOperator.LAPE) == pytest.approx(
        hardware_utils.calculate_focus_measure(as_uint16, FocusMeasureOperator.LAPE), rel=1e-9
    )


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_image_processing_focus_measure_sharp_scores_higher_than_blurred(dtype) -> None:
    """image_processing.calculate_focus_measure (tracking) uses the same LAPE operator."""
    sharp = _binary_amplitude_image(dtype)
    blurred = cv2.GaussianBlur(sharp, (0, 0), 1)

    assert image_processing.calculate_focus_measure(sharp) > image_processing.calculate_focus_measure(blurred)


def test_image_processing_focus_measure_matches_hardware_utils_lape() -> None:
    image = _binary_amplitude_image(np.uint8)

    assert image_processing.calculate_focus_measure(image) == pytest.approx(
        hardware_utils.calculate_focus_measure(image, FocusMeasureOperator.LAPE), rel=1e-9
    )

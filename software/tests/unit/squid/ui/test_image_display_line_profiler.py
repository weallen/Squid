"""Line profiler in ImageDisplayWindow: multiple lines, H / V / Full / Fill FOV shortcuts, and profile accuracy.

Ports upstream 9a8a7afd (#732).
"""

import numpy as np
import pyqtgraph as pg
import pytest
from qtpy.QtCore import QPoint, Qt
from qtpy.QtWidgets import QApplication

from squid.ui.widgets.display.image_display import ImageDisplayWindow


@pytest.fixture
def image_display_window(qtbot):
    win = ImageDisplayWindow()
    qtbot.addWidget(win)
    return win


def _endpoints(roi):
    start, end = ImageDisplayWindow._line_roi_endpoints(roi)
    return (start.x(), start.y()), (end.x(), end.y())


def _draw_line(win, start, end):
    win.line_start_pos, win.line_end_pos = start, end
    return win.create_line_roi()


def _profiles(win):
    """{curve name: y data} of the line profile plot."""
    return {item.name(): item.getData()[1] for item in win.line_profiler_plot.listDataItems()}


@pytest.fixture
def profiling_window(qtbot):
    """A window showing a 101x51 frame whose pixel value is its row index, with the line profiler on."""
    win = ImageDisplayWindow()
    qtbot.addWidget(win)
    frame = np.repeat(np.arange(51, dtype=np.uint16)[:, None], 101, axis=1)
    win.display_image(frame)
    win.btn_line_profiler.click()
    return win


def test_line_shortcuts_show_only_while_the_profiler_is_on(image_display_window):
    win = image_display_window
    win.display_image(np.zeros((4, 4), dtype=np.uint8))
    assert all(b.isHidden() for b in win.line_shortcut_buttons)

    win.btn_line_profiler.click()
    assert not any(b.isHidden() for b in win.line_shortcut_buttons)

    win.btn_line_profiler.click()
    assert all(b.isHidden() for b in win.line_shortcut_buttons)


@pytest.mark.parametrize("show_lut", [False, True])
def test_horizontal_line_spans_the_fov_through_the_image_center(qtbot, show_lut):
    win = ImageDisplayWindow(show_LUT=show_lut)
    qtbot.addWidget(win)
    win.display_image(np.zeros((51, 101), dtype=np.uint16))
    win.btn_line_profiler.click()

    win.btn_line_horizontal.click()

    start, end = _endpoints(win.selected_line_roi)
    assert start == pytest.approx((0, 25), abs=1e-6)
    assert end == pytest.approx((100, 25), abs=1e-6)
    assert win.selected_line_roi in win._active_view().addedItems


def test_vertical_line_spans_the_fov_through_the_image_center(profiling_window):
    profiling_window.btn_line_vertical.click()

    start, end = _endpoints(profiling_window.selected_line_roi)
    assert start == pytest.approx((50, 0), abs=1e-6)
    assert end == pytest.approx((50, 50), abs=1e-6)


def test_profile_samples_the_line_itself_not_the_roi_edge(profiling_window):
    """Each pixel holds its row index, so a horizontal line's profile is the row it is drawn on."""
    win = profiling_window
    win.btn_line_horizontal.click()

    (profile,) = _profiles(win).values()
    assert profile == pytest.approx(np.full(len(profile), 25.0))


def test_lines_accumulate_with_one_colored_profile_each(profiling_window):
    win = profiling_window
    win.btn_line_horizontal.click()
    win.btn_line_vertical.click()
    _draw_line(win, (10, 40), (90, 40))

    assert len(win.line_rois) == 3
    assert all(roi in win._active_view().addedItems for roi in win.line_rois)
    profiles = _profiles(win)
    assert list(profiles) == ["Line 1", "Line 2", "Line 3"]
    assert profiles["Line 1"] == pytest.approx(np.full(len(profiles["Line 1"]), 25.0))
    assert profiles["Line 2"] == pytest.approx(np.linspace(0, 50, len(profiles["Line 2"])), abs=0.5)
    assert profiles["Line 3"] == pytest.approx(np.full(len(profiles["Line 3"]), 40.0))
    colors = [win._line_roi_labels[roi][0] for roi in win.line_rois]
    assert len(set(colors)) == 3


def test_newest_line_is_selected_and_drawn_thicker(profiling_window):
    win = profiling_window
    first = _draw_line(win, (10, 10), (20, 10))
    second = _draw_line(win, (10, 20), (20, 20))

    assert win.selected_line_roi is second
    assert second.pen.width() > first.pen.width()

    win.select_line_roi(first)
    assert first.pen.width() > second.pen.width()


@pytest.mark.parametrize("offset_px, selects", [(0, True), (6, True), (20, False)])
def test_clicking_near_a_line_selects_it_on_a_zoomed_out_frame(qtbot, offset_px, selects):
    """On a camera-sized frame a 5 px line is 1-2 screen pixels thick, so a click selects it within a tolerance."""
    win = ImageDisplayWindow(show_LUT=True, autoLevels=True)
    qtbot.addWidget(win)
    win.resize(1000, 800)
    win.show()
    win.display_image(np.zeros((2000, 3000), dtype=np.uint16))
    win.btn_line_profiler.click()
    drawn = _draw_line(win, (500, 500), (1500, 500))
    win.btn_line_horizontal.click()
    QApplication.processEvents()
    view, graphics_view = win._active_view(), win.graphics_widget.view.ui.graphicsView
    assert view.viewPixelSize()[0] > 2  # zoomed out: several image pixels per screen pixel

    target = graphics_view.mapFromScene(view.mapViewToScene(pg.Point(1000, 500))) + QPoint(0, offset_px)
    qtbot.mouseMove(graphics_view.viewport(), target)
    qtbot.mouseClick(graphics_view.viewport(), Qt.LeftButton, pos=target)

    assert (win.selected_line_roi is drawn) == selects


def test_dragging_a_line_selects_it(profiling_window):
    win = profiling_window
    first = _draw_line(win, (10, 10), (20, 10))
    _draw_line(win, (10, 20), (20, 20))

    first.sigRegionChangeStarted.emit(first)

    assert win.selected_line_roi is first


@pytest.mark.parametrize("widen", ["btn_line_fill", None])
def test_new_lines_are_5px_wide_whatever_the_selected_line_is(profiling_window, widen):
    win = profiling_window
    win.btn_line_horizontal.click()
    first = win.selected_line_roi
    if widen:
        getattr(win, widen).click()  # a just-filled band must not pass its width on
    else:
        first.setSize((first.size()[0], 9))
    assert first.size()[1] > 5

    win.btn_line_vertical.click()
    _draw_line(win, (10, 10), (20, 20))

    assert first in win.line_rois
    assert [roi.size()[1] for roi in win.line_rois[1:]] == pytest.approx([5, 5])


def test_draw_button_starts_drawing_another_line(profiling_window):
    win = profiling_window
    win.btn_line_horizontal.click()
    assert not win.is_drawing_line

    win.btn_line_draw.click()

    assert win.is_drawing_line
    assert len(win.line_rois) == 1


def test_shortcut_cancels_a_line_being_drawn(profiling_window):
    win = profiling_window
    assert win.is_drawing_line  # opening the profiler without a line starts drawing mode
    win.line_start_pos = (3, 3)

    win.btn_line_horizontal.click()

    assert not win.is_drawing_line
    assert len(win.line_rois) == 1


def test_remove_requested_removes_only_that_line_and_reselects(profiling_window):
    win = profiling_window
    first = _draw_line(win, (10, 10), (20, 10))
    second = _draw_line(win, (10, 20), (20, 20))

    second.sigRemoveRequested.emit(second)

    assert win.line_rois == [first]
    assert second not in win._active_view().addedItems
    assert win.selected_line_roi is first
    assert list(_profiles(win)) == ["Line 1"]


def test_clear_removes_every_line_and_profile(profiling_window):
    win = profiling_window
    win.btn_line_horizontal.click()
    win.btn_line_vertical.click()
    rois = list(win.line_rois)

    win.btn_line_clear.click()

    assert win.line_rois == []
    assert win.selected_line_roi is None
    assert not any(roi in win._active_view().addedItems for roi in rois)
    assert _profiles(win) == {}


def test_toggling_the_profiler_hides_and_restores_all_lines(profiling_window):
    win = profiling_window
    win.btn_line_horizontal.click()
    win.btn_line_vertical.click()

    win.btn_line_profiler.click()
    assert not any(roi.isVisible() for roi in win.line_rois)

    win.btn_line_profiler.click()
    assert all(roi.isVisible() for roi in win.line_rois)
    assert not win.is_drawing_line


@pytest.mark.parametrize(
    "drawn, expected",
    [
        (((40, 20), (60, 30)), ((0, 0), (100, 50))),  # diagonal through the corners
        (((10, 10), (20, 10)), ((0, 10), (100, 10))),  # off-center horizontal keeps its row
        (((70, 40), (70, 30)), ((70, 50), (70, 0))),  # keeps its direction
    ],
)
def test_full_extends_the_selected_line_to_the_fov_edges(profiling_window, drawn, expected):
    win = profiling_window
    roi = _draw_line(win, *drawn)
    roi.setSize((roi.size()[0], 7), center=(0.5, 0.5))  # widen about the centerline

    win.btn_line_full.click()

    assert win.selected_line_roi is roi
    start, end = _endpoints(roi)
    assert start == pytest.approx(expected[0], abs=1e-6)
    assert end == pytest.approx(expected[1], abs=1e-6)
    assert roi.size()[1] == pytest.approx(7)


def test_full_only_changes_the_selected_line(profiling_window):
    win = profiling_window
    first = _draw_line(win, (10, 10), (20, 10))
    second = _draw_line(win, (10, 20), (20, 20))
    win.select_line_roi(first)

    win.btn_line_full.click()

    assert _endpoints(first) == (pytest.approx((0, 10)), pytest.approx((100, 10)))
    assert _endpoints(second) == (pytest.approx((10, 20)), pytest.approx((20, 20)))


def test_full_without_a_line_does_nothing(profiling_window):
    profiling_window.btn_line_full.click()
    assert profiling_window.line_rois == []


def test_full_leaves_a_line_outside_the_image_alone(profiling_window):
    win = profiling_window
    roi = _draw_line(win, (10, -20), (60, -20))

    win.btn_line_full.click()

    assert _endpoints(roi) == (pytest.approx((10, -20)), pytest.approx((60, -20)))


def test_shortcut_fits_the_profile_plot_to_the_new_line(profiling_window):
    win = profiling_window
    _draw_line(win, (10, 10), (30, 10))
    assert win.line_profiler_plot.viewRange()[0][1] < 50

    win.btn_line_full.click()

    assert win.line_profiler_plot.viewRange()[0][1] >= 100


@pytest.mark.parametrize("shortcut, axis", [("btn_line_horizontal", 0), ("btn_line_vertical", 1)])
def test_fill_fov_averages_the_whole_image_across_an_axis_line(qtbot, shortcut, axis):
    """A filled horizontal line's profile is the mean of every row; a vertical one's, of every column."""
    win = ImageDisplayWindow(show_LUT=True, autoLevels=True)
    qtbot.addWidget(win)
    frame = np.random.default_rng(0).integers(0, 4000, (60, 90), dtype=np.uint16)
    win.display_image(frame)
    win.btn_line_profiler.click()
    getattr(win, shortcut).click()

    win.btn_line_fill.click()

    assert win.selected_line_roi.size()[1] == pytest.approx(frame.shape[axis])
    (profile,) = _profiles(win).values()
    assert profile == pytest.approx(frame.mean(axis=axis))


def test_fill_fov_centers_a_tilted_line_and_averages_only_pixels_on_the_image(profiling_window):
    win = profiling_window
    win.display_image(np.full((51, 101), 100, dtype=np.uint16))
    roi = _draw_line(win, (10, 10), (30, 20))  # slope 1/2, off-center

    win.btn_line_fill.click()

    start, end = _endpoints(roi)
    assert ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2) == pytest.approx((50, 25))
    assert (end[1] - start[1]) / (end[0] - start[0]) == pytest.approx(0.5)
    # The band reaches past the image on a tilted line; samples there must not be counted as zeros
    (profile,) = _profiles(win).values()
    assert np.isfinite(profile).sum() > 0.9 * len(profile)
    assert profile[np.isfinite(profile)] == pytest.approx(100.0)


def test_fill_fov_without_a_line_does_nothing(profiling_window):
    profiling_window.btn_line_fill.click()
    assert profiling_window.line_rois == []


def test_axis_line_off_the_image_reads_nan_there(profiling_window):
    win = profiling_window
    _draw_line(win, (-20, 10), (20, 10))

    (profile,) = _profiles(win).values()
    assert np.isnan(profile[:20]).all()
    assert profile[20:] == pytest.approx(10.0)

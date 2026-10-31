from unittest.mock import MagicMock

from squid.core.events import MoveStageToCommand
from squid.ui.widgets.display.focus_map import FocusMapWidget


def test_goto_next_point_moves_once(qtbot):
    """setCurrentIndex used to fire currentIndexChanged -> goto_selected_point, so every
    'next point' click ran two full X/Y/Z moves (upstream #618)."""
    event_bus = MagicMock()
    widget = FocusMapWidget(focusMap=MagicMock(), event_bus=event_bus)
    qtbot.addWidget(widget)
    widget.focus_points = [("R1", 1.0, 2.0, 3.0), ("R1", 4.0, 5.0, 6.0)]
    widget.update_point_list()
    widget.enabled = True
    widget.point_combo.setCurrentIndex(0)
    event_bus.publish.reset_mock()

    widget.goto_next_point()

    moves = [c.args[0] for c in event_bus.publish.call_args_list if isinstance(c.args[0], MoveStageToCommand)]
    assert moves == [MoveStageToCommand(x_mm=4.0, y_mm=5.0, z_mm=6.0)]
    assert widget.point_combo.currentIndex() == 1

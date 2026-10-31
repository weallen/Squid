"""FlexibleMultiPointWidget must not share one QSpacerItem across layouts (upstream #750).

Each layout owns and frees its items, so a shared spacer is freed once per layout on teardown.
"""

from qtpy.QtCore import QCoreApplication, QEvent
from qtpy.QtWidgets import QLayout, QWidget

from squid.core.events import EventBus
from squid.ui.widgets.acquisition.flexible_multipoint import FlexibleMultiPointWidget


def _spacer_items(layout: QLayout, out: list) -> None:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.spacerItem() is not None:
            out.append(item.spacerItem())
        if item.layout() is not None:
            _spacer_items(item.layout(), out)


def test_no_spacer_item_is_shared_and_teardown_is_clean(qtbot):
    bus = EventBus()
    try:
        widget = FlexibleMultiPointWidget(QWidget(), bus, initial_channel_configs=["BF LED matrix full"])
        spacers: list = []
        _spacer_items(widget.layout(), spacers)
        # sip returns the same Python wrapper for the same C++ object, so duplicates show up by identity.
        assert len({id(s) for s in spacers}) == len(spacers)

        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    finally:
        bus.stop()

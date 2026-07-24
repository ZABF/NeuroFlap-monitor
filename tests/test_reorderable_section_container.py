import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QHoverEvent
from PyQt5.QtWidgets import QApplication, QGroupBox

from ui.reorderable_section_container import ReorderableSectionContainer


class ReorderableSectionContainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_move_section_reorders_and_emits(self):
        container = ReorderableSectionContainer()
        widgets = {key: QGroupBox(key) for key in ("A", "B", "C")}
        container.set_sections(["A", "B", "C"], widgets)
        changes = []
        container.order_changed.connect(changes.append)

        self.assertTrue(container.move_section("C", 0))

        self.assertEqual(container.section_order(), ["C", "A", "B"])
        self.assertEqual(changes, [["C", "A", "B"]])

    def test_only_group_title_is_a_drag_handle(self):
        group = QGroupBox("Dataflow")
        group.resize(180, 80)
        group.show()
        self.app.processEvents()

        self.assertTrue(ReorderableSectionContainer._is_title_press(group, QPoint(12, 2)))
        self.assertFalse(ReorderableSectionContainer._is_title_press(group, QPoint(20, 50)))

    def test_drag_cursor_only_appears_over_group_title(self):
        container = ReorderableSectionContainer()
        group = QGroupBox("Dataflow")
        group.resize(180, 80)
        container.set_sections(["Dataflow"], {"Dataflow": group})

        title_hover = QHoverEvent(QEvent.HoverMove, QPointF(12, 2), QPointF(20, 50))
        container.eventFilter(group, title_hover)
        self.assertEqual(group.cursor().shape(), Qt.OpenHandCursor)

        content_hover = QHoverEvent(QEvent.HoverMove, QPointF(20, 50), QPointF(12, 2))
        container.eventFilter(group, content_hover)
        self.assertEqual(group.cursor().shape(), Qt.ArrowCursor)

    def test_drop_indicator_tracks_candidate_section(self):
        container = ReorderableSectionContainer()
        widgets = {key: QGroupBox(key) for key in ("A", "B")}
        for widget in widgets.values():
            widget.setFixedSize(100, 60)
        container.set_sections(["A", "B"], widgets)
        container.resize(container.sizeHint())
        container.show()
        self.app.processEvents()

        container._show_drop_indicator("B")
        self.assertFalse(container._drop_indicator.isHidden())
        self.assertTrue(container._drop_indicator.geometry().contains(widgets["B"].geometry()))

        container._hide_drop_indicator()
        self.assertTrue(container._drop_indicator.isHidden())


if __name__ == "__main__":
    unittest.main()

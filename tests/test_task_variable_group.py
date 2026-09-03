import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QLabel, QStyle, QStyleOptionGroupBox

from ui.task_variable_group import TaskVariableGroup, task_display_order, task_section_kind
from ui.theme import TEXT_HEX, readable_curve_text_color
from ui.variable_control import VariableControlItem


class TaskVariableGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_latency_label_text_selection_and_color_are_independent(self):
        group = TaskVariableGroup(5, "MadgwickTask", "MadgwickTask.latency_us")
        selected = []
        group.latency_selected.connect(selected.append)

        group.update_latency(86)
        self.assertEqual(group.latency_label.text(), "86 us")
        self.assertIn(TEXT_HEX, group.latency_label.styleSheet())
        self.assertFalse(group.latency_label.font().bold())

        event = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            group.latency_label.rect().center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        group.latency_label.mousePressEvent(event)
        self.assertEqual(selected, ["MadgwickTask.latency_us"])

        group.set_latency_selected(True)
        self.assertTrue(group.latency_label.font().bold())
        self.assertIn(TEXT_HEX, group.latency_label.styleSheet())

        group.set_latency_selected(False)
        self.assertFalse(group.latency_label.font().bold())

        group.reset_latency()
        self.assertEqual(group.latency_label.text(), "-- us")

    def test_ports_are_split_into_input_and_output_columns(self):
        group = TaskVariableGroup(5, "MadgwickTask", "MadgwickTask.latency_us")
        input_control = QLabel("roll")
        output_control = QLabel("yaw")

        group.set_port_controls([input_control], [output_control])

        self.assertIs(group.input_layout.itemAt(0).widget(), input_control)
        self.assertIs(group.output_layout.itemAt(0).widget(), output_control)
        self.assertTrue(group.divider.isVisibleTo(group))
        self.assertEqual(group.title(), "MadgwickTask")

    def test_latency_is_positioned_immediately_after_native_group_title(self):
        group = TaskVariableGroup(5, "MadgwickTask", "MadgwickTask.latency_us")
        group.update_latency(86)
        group.resize(group.sizeHint())
        group.show()
        self.app.processEvents()

        option = QStyleOptionGroupBox()
        group.initStyleOption(option)
        title_rect = group.style().subControlRect(
            QStyle.CC_GroupBox,
            option,
            QStyle.SC_GroupBoxLabel,
            group,
        )
        self.assertGreaterEqual(group.latency_label.x(), title_rect.right())
        self.assertLessEqual(group.latency_label.x() - title_rect.right(), 8)
        self.assertLessEqual(group.latency_label.geometry().right(), group.rect().right())

    def test_latency_changes_do_not_change_group_width(self):
        group = TaskVariableGroup(5, "MadgwickTask", "MadgwickTask.latency_us")
        initial_width = group.minimumWidth()
        group.update_latency(1)
        short_width = group.minimumWidth()
        group.update_latency(16447)
        long_width = group.minimumWidth()

        self.assertEqual(short_width, initial_width)
        self.assertEqual(long_width, initial_width)

    def test_variable_control_displays_short_name_but_emits_full_name(self):
        control = VariableControlItem(
            "MadgwickTask.input.roll",
            (10, 20, 30),
            (10, 20, 30),
            checked=False,
            display_name="roll",
            unit="deg",
        )
        selected = []
        control.selected.connect(selected.append)

        self.assertEqual(control.label.text(), "roll")
        self.assertEqual(control.label.toolTip(), "MadgwickTask.input.roll [deg]")
        self.assertGreaterEqual(
            control.label.minimumWidth(),
            control.label.fontMetrics().horizontalAdvance("roll"),
        )
        self.assertFalse(hasattr(control, "color_strip"))
        self.assertIn(
            f"rgb{readable_curve_text_color((10, 20, 30))}",
            control.label.styleSheet(),
        )

        event = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            control.rect().center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        control.mousePressEvent(event)
        self.assertEqual(selected, ["MadgwickTask.input.roll"])

    def test_task_display_order_is_business_device_system(self):
        task_ids = [0x1001, 0x2001, 0x3001]
        self.assertEqual(
            sorted(task_ids, key=task_display_order),
            [0x3001, 0x2001, 0x1001],
        )
        self.assertEqual(task_section_kind(0x2001), "device")
        self.assertEqual(task_section_kind(0x3001), "business")
        self.assertEqual(task_section_kind(0x1001), "system")

    def test_task_group_exposes_category_for_theme_accent(self):
        self.assertEqual(
            TaskVariableGroup(0x3001, "BusinessTask", "latency").property("sectionKind"),
            "business",
        )
        self.assertEqual(
            TaskVariableGroup(0x2001, "DeviceTask", "latency").property("sectionKind"),
            "device",
        )
        self.assertEqual(
            TaskVariableGroup(0x1001, "SystemTask", "latency").property("sectionKind"),
            "system",
        )


if __name__ == "__main__":
    unittest.main()

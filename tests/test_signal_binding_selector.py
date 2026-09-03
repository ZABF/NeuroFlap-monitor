import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from ui.signal_binding_selector import (
    SignalBindingSelector,
    build_signal_choices,
)


DESCRIPTORS = {
    "MadgwickTask.input.acc_x": {
        "descriptor_kind": "task_port",
        "category": "task",
        "task_id": 0x3001,
        "task_order": 1,
        "direction": 0,
        "slot": 0,
        "owner": "MadgwickTask",
        "display_name": "acc_x",
    },
    "MadgwickTask.output.roll": {
        "descriptor_kind": "task_port",
        "category": "task",
        "task_id": 0x3001,
        "task_order": 1,
        "direction": 1,
        "slot": 0,
        "owner": "MadgwickTask",
        "display_name": "roll",
    },
    "SensorTask.output.acc_x": {
        "descriptor_kind": "task_port",
        "category": "task",
        "task_id": 0x2001,
        "task_order": 0,
        "direction": 1,
        "slot": 0,
        "owner": "SensorTask",
        "display_name": "acc_x",
    },
    "SysDataflowExportTask.output.ready": {
        "descriptor_kind": "task_port",
        "category": "task",
        "task_id": 0x1001,
        "task_order": 0,
        "direction": 1,
        "slot": 0,
        "owner": "SysDataflowExportTask",
        "display_name": "ready",
    },
    "Dataflow.armed": {
        "descriptor_kind": "data_node",
        "category": "dataflow",
        "group": "control",
        "group_order": 0,
        "node_no": 2,
        "display_name": "armed",
    },
}


class SignalBindingSelectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.choices = build_signal_choices(DESCRIPTORS, DESCRIPTORS)
        self.selector = SignalBindingSelector()

    def tearDown(self):
        self.selector.close()

    def test_schema_builds_domain_owner_and_port_hierarchy(self):
        by_variable = {choice.variable: choice for choice in self.choices}

        madgwick = by_variable["MadgwickTask.output.roll"]
        self.assertEqual(madgwick.category_label, "Business")
        self.assertEqual(madgwick.owner_label, "MadgwickTask")
        self.assertEqual(madgwick.signal_label, "Output / roll")
        self.assertEqual(
            by_variable["SensorTask.output.acc_x"].category_label,
            "Device",
        )
        self.assertEqual(
            by_variable["SysDataflowExportTask.output.ready"].category_label,
            "System",
        )
        self.assertEqual(by_variable["Dataflow.armed"].category_label, "Node")
        self.assertEqual(by_variable["Dataflow.armed"].owner_label, "control")

    def test_saved_variable_selects_all_three_levels(self):
        self.selector.set_choices(self.choices, "MadgwickTask.output.roll")

        self.assertEqual(self.selector.category_combo.currentText(), "Business")
        self.assertEqual(self.selector.owner_combo.currentText(), "MadgwickTask")
        self.assertEqual(self.selector.signal_combo.currentText(), "Output / roll")
        self.assertEqual(
            self.selector.currentData(),
            "MadgwickTask.output.roll",
        )

    def test_category_change_repopulates_owner_and_signal(self):
        self.selector.set_choices(self.choices, "MadgwickTask.output.roll")

        self.selector.category_combo.setCurrentIndex(
            self.selector.category_combo.findData("node")
        )

        self.assertEqual(self.selector.owner_combo.currentText(), "control")
        self.assertEqual(self.selector.signal_combo.currentText(), "armed")
        self.assertEqual(self.selector.currentData(), "Dataflow.armed")


if __name__ == "__main__":
    unittest.main()

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
        "category": "business",
        "task_id": 0x3001,
        "task_order": 1,
        "direction": 0,
        "slot": 0,
        "owner": "MadgwickTask",
        "display_name": "acc_x",
    },
    "MadgwickTask.output.roll": {
        "descriptor_kind": "task_port",
        "category": "business",
        "task_id": 0x3001,
        "task_order": 1,
        "direction": 1,
        "slot": 0,
        "owner": "MadgwickTask",
        "display_name": "roll",
    },
    "SensorTask.output.acc_x": {
        "descriptor_kind": "task_port",
        "category": "device",
        "task_id": 0x2001,
        "task_order": 0,
        "direction": 1,
        "slot": 0,
        "owner": "SensorTask",
        "display_name": "acc_x",
    },
    "SysDataflowExportTask.output.ready": {
        "descriptor_kind": "task_port",
        "category": "system",
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

    def test_custom_categories_use_section_groups_instead_of_producer(self):
        descriptors = {
            "Processed.UWB.pos_x_lowpass_zero": {
                "category": "processed",
                "section": "Processed/Trajectory",
                "descriptor_kind": "processed_signal",
                "owner": "clean_ch3_segments",
                "display_name": "UWB X low-pass zero",
            },
            "Analysis.output.residual": {
                "category": "analysis",
                "section": "Analysis/Validation/Residuals",
                "owner": "offline_tool",
                "display_name": "Residual",
            },
        }
        choices = build_signal_choices(descriptors, descriptors)
        by_variable = {choice.variable: choice for choice in choices}

        processed = by_variable["Processed.UWB.pos_x_lowpass_zero"]
        self.assertEqual(processed.category, "processed")
        self.assertEqual(processed.category_label, "Processed")
        self.assertEqual(processed.owner_label, "Trajectory")
        analysis = by_variable["Analysis.output.residual"]
        self.assertEqual(analysis.category, "analysis")
        self.assertEqual(analysis.owner_label, "Validation/Residuals")
        self.assertEqual(analysis.signal_label, "Residual")

        self.selector.set_choices(choices, processed.variable)
        self.assertEqual(self.selector.category_combo.currentText(), "Processed")
        self.assertEqual(self.selector.owner_combo.currentText(), "Trajectory")
        self.assertEqual(self.selector.currentData(), processed.variable)
        self.selector.category_combo.setCurrentIndex(
            self.selector.category_combo.findData("analysis")
        )
        self.assertEqual(self.selector.owner_combo.currentText(), "Validation/Residuals")
        self.assertEqual(self.selector.currentData(), analysis.variable)

    def test_section_can_declare_category_without_category_metadata(self):
        descriptors = {
            "opaque_signal": {
                "section": "Experiment/Run A",
                "owner": "tool",
                "display_name": "Altitude",
            },
        }
        choice = build_signal_choices(descriptors, descriptors)[0]

        self.assertEqual(choice.category, "experiment")
        self.assertEqual(choice.category_label, "Experiment")
        self.assertEqual(choice.owner_label, "Run A")

    def test_explicit_group_overrides_section_and_owner(self):
        descriptors = {
            "Estimate.x": {
                "category": "estimation",
                "group": "Filtered pose",
                "section": "Estimation/Raw pose",
                "owner": "algorithm",
            },
        }
        choice = build_signal_choices(descriptors, descriptors)[0]

        self.assertEqual(choice.category, "estimation")
        self.assertEqual(choice.owner_label, "Filtered pose")

    def test_custom_task_categories_and_generic_signals_sort_together(self):
        descriptors = {
            "Recorder.output.x": {
                "descriptor_kind": "task_port",
                "category": "experiment",
                "owner": "Recorder",
                "direction": 1,
                "display_name": "x",
            },
            "custom_signal": {
                "category": "experiment",
                "section": "Experiment/Estimated",
            },
        }
        choices = build_signal_choices(descriptors, descriptors)

        self.assertEqual({choice.category for choice in choices}, {"experiment"})
        self.assertEqual(len(choices), len(descriptors))
        self.assertEqual(
            choices, build_signal_choices(reversed(list(descriptors)), descriptors)
        )

    def test_metadata_free_external_signals_keep_legacy_groups(self):
        choices = build_signal_choices(("Mocap_X", "F_X", "unclassified"))
        by_variable = {choice.variable: choice for choice in choices}

        self.assertEqual(by_variable["Mocap_X"].owner_label, "MoCap")
        self.assertEqual(by_variable["F_X"].owner_label, "Bota FT")
        self.assertEqual(by_variable["unclassified"].owner_label, "Other")


if __name__ == "__main__":
    unittest.main()

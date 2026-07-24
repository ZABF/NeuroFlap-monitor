import os
import sys
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _DummyBotaSerialSensor:
    def __init__(self, _port):
        pass

    def setup(self):
        return False

    def close(self):
        pass


class _DummyConfiguration:
    def __init__(self, *args, **kwargs):
        pass


class _DummyCalculator:
    def __init__(self, *args, **kwargs):
        pass

    def checksum(self, _data):
        return 0


class _DummyDataTransporter:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


_bota_mod = types.ModuleType("bota_lite")
_bota_mod.BotaSerialSensor = _DummyBotaSerialSensor
sys.modules.setdefault("bota_lite", _bota_mod)

_mocap_pkg = types.ModuleType("MoCap")
_mocap_lumo_pkg = types.ModuleType("MoCap.LuMo")
_mocap_sdk_mod = types.ModuleType("MoCap.LuMo.LuMoSDKClient")
_mocap_sdk_mod.Init = lambda: None
_mocap_sdk_mod.Connnect = lambda _ip: None
_mocap_sdk_mod.ReceiveData = lambda _timeout: None
_mocap_sdk_mod.Close = lambda: None
sys.modules.setdefault("MoCap", _mocap_pkg)
sys.modules.setdefault("MoCap.LuMo", _mocap_lumo_pkg)
sys.modules.setdefault("MoCap.LuMo.LuMoSDKClient", _mocap_sdk_mod)

_crc_mod = types.ModuleType("crc")
_crc_mod.Calculator = _DummyCalculator
_crc_mod.Configuration = _DummyConfiguration
sys.modules.setdefault("crc", _crc_mod)

_data_transporter_mod = types.ModuleType("data_transporter")
_data_transporter_mod.DataTransporter = _DummyDataTransporter
sys.modules.setdefault("data_transporter", _data_transporter_mod)

from PyQt5.QtWidgets import QApplication, QLabel, QAbstractSpinBox

from data_receiver import DataReceiver
from ui.curve_expression import CurveExpressionParser
from ui.main_window import PlotWindow


def _series(var_name, values, section="Test"):
    return {
        var_name: {
            "timestamps": [1000.0 + 10.0 * i for i in range(len(values))],
            "values": list(values),
            "section": section,
            "unit": "",
        }
    }


def _task_descriptors():
    return [
        {
            "var_name": "Dataflow.armed",
            "section": "Dataflow/control",
            "category": "dataflow",
            "descriptor_kind": "data_node",
            "display_name": "armed",
            "group_order": 0,
        },
        {
            "var_name": "MadgwickTask.latency_us",
            "section": "Task/5",
            "category": "task",
            "descriptor_kind": "task_latency",
            "task_id": 5,
            "task_order": 0,
            "owner": "MadgwickTask",
            "display_name": "latency_us",
            "hidden_control": True,
            "unit": "us",
        },
        {
            "var_name": "MadgwickTask.input.roll",
            "section": "Task/5",
            "category": "task",
            "descriptor_kind": "task_port",
            "task_id": 5,
            "task_order": 0,
            "direction": 0,
            "slot": 0,
            "owner": "MadgwickTask",
            "display_name": "roll",
            "unit": "deg",
        },
        {
            "var_name": "MadgwickTask.output.yaw",
            "section": "Task/5",
            "category": "task",
            "descriptor_kind": "task_port",
            "task_id": 5,
            "task_order": 0,
            "direction": 1,
            "slot": 0,
            "owner": "MadgwickTask",
            "display_name": "yaw",
            "unit": "deg",
        },
    ]


class PlotSourceSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_start = DataReceiver.start
        DataReceiver.start = lambda _self: None
        self.window = PlotWindow(persist_layout=False)
        self.window.data_receiver.disconnect_nfv3 = lambda: None
        self.window.data_receiver.stop = lambda: None

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        DataReceiver.start = self.original_start

    def test_replay_switch_preserves_workspace_and_auto_recovers_derived(self):
        self.window._load_imported_series("/tmp/first.csv", _series("a", [1.0, 2.0]))
        ast = CurveExpressionParser("[a] * 2").parse()
        self.window.create_derived_curve("twice", "[a] * 2", ast)
        self.window.curve_transforms["a"] = {"phase_ms": 25.0, "scale": 3.0, "offset": 4.0}
        self.window.set_curve_visibility("a", True)
        self.window.set_curve_color("a", (12, 34, 56))
        original_spec = self.window.curve_specs["twice"]

        self.window._load_imported_series("/tmp/second.csv", _series("a", [3.0, 4.0]))

        self.assertIs(self.window.curve_specs["twice"], original_spec)
        self.assertEqual(self.window.curve_transforms["a"]["phase_ms"], 25.0)
        self.assertEqual(self.window.colors["a"], (12, 34, 56))
        self.assertTrue(self.window.curves["a"].isVisible())
        self.assertTrue(self.window.derived_health["twice"].valid)
        self.assertEqual(self.window.active_source_label.text(), "Source: Replay second.csv")

        self.window._load_imported_series("/tmp/missing.csv", _series("b", [5.0, 6.0]))

        self.assertIn("twice", self.window.curve_specs)
        self.assertEqual(self.window.derived_health["twice"].missing_refs, ("a",))
        self.assertFalse(self.window.var_controls["twice"].health_indicator.isHidden())
        x_data = self.window.curves["twice"].xData
        self.assertEqual(0 if x_data is None else x_data.size, 0)

        self.window._load_imported_series("/tmp/restored.csv", _series("a", [7.0, 8.0]))

        self.assertTrue(self.window.derived_health["twice"].valid)
        self.assertTrue(self.window.var_controls["twice"].health_indicator.isHidden())
        self.assertEqual(self.window.curve_transforms["a"]["phase_ms"], 25.0)
        self.assertEqual(self.window.colors["a"], (12, 34, 56))
        self.assertTrue(self.window.curves["a"].isVisible())

    def test_replay_changes_to_live_only_after_requested_schema_activation(self):
        self.window._load_imported_series("/tmp/replay.csv", _series("a", [1.0]))
        descriptors = [{"var_name": "a", "section": "Test"}]

        self.assertFalse(
            self.window.activate_live_dataflow_export_descriptors(descriptors, "192.168.4.1", 28080)
        )
        self.assertEqual(self.window.active_data_source.kind, "replay")

        self.window._live_activation_requested = True
        self.assertTrue(
            self.window.activate_live_dataflow_export_descriptors(descriptors, "192.168.4.1", 28080)
        )
        self.assertEqual(self.window.active_data_source.kind, "live")
        self.assertEqual(self.window.active_source_label.text(), "Source: Live 192.168.4.1:28080")

        self.assertTrue(
            self.window.activate_live_dataflow_export_descriptors(descriptors, "192.168.4.1", 28080)
        )

    def test_initial_live_activation_also_requires_explicit_connect(self):
        descriptors = [{"var_name": "a", "section": "Test"}]

        self.assertFalse(
            self.window.activate_live_dataflow_export_descriptors(descriptors, "192.168.4.1", 28080)
        )
        self.assertEqual(self.window.active_data_source.kind, "none")

    def test_source_and_reset_layout_share_connection_row(self):
        row_widgets = [
            self.window.nfv3_ctrl_layout.itemAt(index).widget()
            for index in range(self.window.nfv3_ctrl_layout.count())
        ]
        self.assertIn(self.window.active_source_label, row_widgets)
        self.assertIs(row_widgets[-1], self.window.reset_section_layout_btn)
        self.assertNotIn(
            "ESP32 Dataflow Export (Dynamic):",
            [label.text() for label in self.window.findChildren(QLabel)],
        )

    def test_dynamic_layout_orders_categories_and_groups_task_ports(self):
        ast = CurveExpressionParser("1").parse()
        self.window.create_derived_curve("calc", "1", ast)
        self.window.register_dataflow_export_descriptors(_task_descriptors())

        self.assertEqual(
            self.window.dataflow_export_section_order,
            ["Derived", "Dataflow/control", "Task/5"],
        )
        self.assertEqual(
            self.window.dataflow_export_sections["Derived"]["box"].property("sectionKind"),
            "derived",
        )
        self.assertEqual(
            self.window.dataflow_export_sections["Dataflow/control"]["box"].property("sectionKind"),
            "dataflow",
        )
        self.assertNotIn("MadgwickTask.latency_us", self.window.var_controls)
        self.assertFalse(self.window.curves["MadgwickTask.latency_us"].isVisible())
        self.assertEqual(self.window.var_controls["MadgwickTask.input.roll"].label.text(), "roll")
        self.assertEqual(self.window.var_controls["MadgwickTask.output.yaw"].label.text(), "yaw")

        group = self.window.task_variable_groups[5]
        self.assertIs(
            group.input_layout.itemAt(0).widget(),
            self.window.var_controls["MadgwickTask.input.roll"],
        )
        self.assertIs(
            group.output_layout.itemAt(0).widget(),
            self.window.var_controls["MadgwickTask.output.yaw"],
        )

    def test_task_groups_sort_business_then_device_then_system(self):
        descriptors = []
        for task_id, name in (
            (0x1001, "SystemTask"),
            (0x3001, "DeviceTask"),
            (0x2001, "BusinessTask"),
        ):
            descriptors.append({
                "var_name": f"{name}.latency_us",
                "section": f"Task/{task_id}",
                "category": "task",
                "descriptor_kind": "task_latency",
                "task_id": task_id,
                "task_order": 0,
                "owner": name,
                "display_name": "latency_us",
                "hidden_control": True,
                "unit": "us",
            })

        self.window.register_dataflow_export_descriptors(descriptors)

        self.assertEqual(
            self.window.dataflow_export_section_order,
            ["Task/8193", "Task/12289", "Task/4097"],
        )

    def test_custom_section_order_survives_schema_refresh_and_can_reset(self):
        descriptors = [_task_descriptors()[0]]
        for task_id, name in (
            (0x1001, "SystemTask"),
            (0x3001, "DeviceTask"),
            (0x2001, "BusinessTask"),
        ):
            descriptors.append({
                "var_name": f"{name}.latency_us",
                "section": f"Task/{task_id}",
                "category": "task",
                "descriptor_kind": "task_latency",
                "task_id": task_id,
                "owner": name,
                "display_name": "latency_us",
                "hidden_control": True,
                "unit": "us",
            })
        self.window.register_dataflow_export_descriptors(descriptors)

        custom = ["Task/4097", "Dataflow/control", "Task/8193", "Task/12289"]
        self.window._set_custom_section_order(custom)
        self.assertEqual(self.window.dataflow_export_section_order, custom)

        self.window.register_dataflow_export_descriptors(descriptors)
        self.assertEqual(self.window.dataflow_export_section_order, custom)

        self.window.reset_section_layout()
        self.assertEqual(
            self.window.dataflow_export_section_order,
            ["Dataflow/control", "Task/8193", "Task/12289", "Task/4097"],
        )

    def test_latency_selection_uses_header_and_keeps_theme_color_after_curve_change(self):
        self.window.register_dataflow_export_descriptors(_task_descriptors())
        group = self.window.task_variable_groups[5]

        self.window.update_task_latency(5, 86)
        self.assertEqual(group.latency_label.text(), "86 us")
        self.assertFalse(group.latency_label.font().bold())

        self.window.select_curve("MadgwickTask.latency_us")
        self.assertTrue(group.latency_label.font().bold())
        before = group.latency_label.styleSheet()
        self.window.set_curve_color("MadgwickTask.latency_us", (220, 10, 30))
        self.assertEqual(group.latency_label.styleSheet(), before)

        self.window._set_selected_curve_focus_active(False)
        self.assertFalse(group.latency_label.font().bold())

    def test_curve_outline_is_only_used_for_low_contrast_colors(self):
        self.window._load_imported_series("/tmp/contrast.csv", _series("a", [1.0, 2.0]))
        curve = self.window.curves["a"]

        self.window.set_curve_color("a", (5, 7, 9))
        self.assertIsNotNone(curve.opts["shadowPen"])

        self.window.set_curve_color("a", (255, 240, 0))
        self.assertIsNone(curve.opts["shadowPen"])

    def test_transform_inputs_use_compact_buttonless_spinboxes(self):
        self.assertEqual(
            self.window.selected_phase_spin.buttonSymbols(),
            QAbstractSpinBox.NoButtons,
        )
        self.assertEqual(
            self.window.selected_offset_spin.buttonSymbols(),
            QAbstractSpinBox.NoButtons,
        )
        self.assertEqual(
            self.window.selected_scale_spin.buttonSymbols(),
            QAbstractSpinBox.NoButtons,
        )

    def test_waveform_capture_uses_current_signal_registry(self):
        self.window.open_waveform_capture()
        capture = self.window.waveform_capture_window
        self.assertEqual(capture.signal_names, self.window.signal_variables)
        capture.close()

    def test_schema_change_removes_stale_task_group_and_latency_curve(self):
        self.window.register_dataflow_export_descriptors(_task_descriptors())
        self.window.register_dataflow_export_descriptors([_task_descriptors()[0]])

        self.assertNotIn("Task/5", self.window.dataflow_export_sections)
        self.assertNotIn(5, self.window.task_variable_groups)
        self.assertNotIn("MadgwickTask.latency_us", self.window.curves)


if __name__ == "__main__":
    unittest.main()

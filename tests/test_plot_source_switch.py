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

from PyQt5.QtWidgets import QApplication

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


class PlotSourceSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_start = DataReceiver.start
        DataReceiver.start = lambda _self: None
        self.window = PlotWindow()
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


if __name__ == "__main__":
    unittest.main()

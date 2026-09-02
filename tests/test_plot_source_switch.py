import os
import math
import sys
import tempfile
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
from monitor_csv import read_monitor_csv
from timeline_controller import TimelineState
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

    def test_window_title_tracks_monitor_release(self):
        self.assertEqual(self.window.windowTitle(), "Monitor v3.4.0")

    def test_auto_x_off_refreshes_new_source_revisions(self):
        self.window.plot_state = self.window.plot_state.RUNNING
        self.window.auto_scroll_enabled = False
        visible_name = next(iter(self.window.curves))
        for name, curve in self.window.curves.items():
            curve.setVisible(name == visible_name)
        self.window._curve_render_signatures[visible_name] = ("old",)

        calls = []
        original = self.window._curve_plot_data
        self.window._curve_plot_data = lambda name: (
            calls.append(name) or ([1000.0, 1020.0], [1.0, 2.0])
        )
        try:
            self.window.update_plot()
        finally:
            self.window._curve_plot_data = original

        self.assertEqual(calls, [visible_name])
        self.assertEqual(self.window.curves[visible_name].xData.tolist(), [1000.0, 1020.0])

    def test_auto_x_on_skips_curves_without_new_source_revision(self):
        self.window.plot_state = self.window.plot_state.RUNNING
        self.window.auto_scroll_enabled = True
        for name, curve in self.window.curves.items():
            if curve.isVisible():
                self.window._curve_render_signatures[name] = (
                    self.window._curve_revision_signature(name)
                )
        original = self.window._curve_plot_data
        self.window._curve_plot_data = lambda _name: self.fail(
            "Unchanged curves must not be queried again"
        )
        try:
            self.window.update_plot()
        finally:
            self.window._curve_plot_data = original

    def test_auto_x_off_uses_current_view_box_range(self):
        self.window.reception_start_time = 0.0
        self.window.window_now = 10000.0
        self.window.auto_scroll_enabled = False
        self.window.plot_widget.setXRange(2000.0, 3000.0, padding=0)

        start, end = self.window._clip_window_range()

        self.assertAlmostEqual(start, 2000.0)
        self.assertAlmostEqual(end, 3000.0)

    def test_derived_curve_queries_only_viewport_and_context(self):
        timestamps = [float(index * 10) for index in range(10001)]
        values = [float(index) for index in range(10001)]
        self.window.data_model.add_series("F_X", "test", timestamps, values)
        ast = CurveExpressionParser("smooth([F_X], 100)").parse()
        self.window.create_derived_curve("smooth_test", "smooth([F_X], 100)", ast)
        self.window.reception_start_time = 0.0
        self.window.window_now = 100000.0
        self.window.auto_scroll_enabled = False
        self.window.plot_widget.setXRange(90000.0, 91000.0, padding=0)
        self.window._invalidate_curve_render_state()

        calls = []
        original = self.window.data_model.get_series_between

        def recording_query(var_name, start_ms, end_ms, **kwargs):
            calls.append((var_name, start_ms, end_ms, kwargs))
            return original(var_name, start_ms, end_ms, **kwargs)

        self.window.data_model.get_series_between = recording_query
        try:
            self.window._curve_plot_data("smooth_test")
            self.window._curve_plot_data("smooth_test")
        finally:
            self.window.data_model.get_series_between = original

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "F_X")
        self.assertGreaterEqual(calls[0][1], 89800.0)
        self.assertLessEqual(calls[0][2], 91200.0)
        full_ts, _full_vs = self.window._curve_view_data["smooth_test"]
        self.assertTrue(full_ts)
        self.assertGreaterEqual(full_ts[0], 90000.0)
        self.assertLessEqual(full_ts[-1], 91000.0)
        expected_ts, expected_vs = self.window._smooth_curve_data(
            timestamps,
            values,
            100.0,
        )
        expected = [
            (timestamp, value)
            for timestamp, value in zip(expected_ts, expected_vs)
            if 90000.0 <= timestamp <= 91000.0
        ]
        actual = list(zip(*self.window._curve_view_data["smooth_test"]))
        self.assertEqual(actual, expected)
        raw_ts, raw_vs = self.window._curve_source_data("F_X")
        self.assertEqual(len(raw_ts), 10001)
        self.assertEqual(len(raw_vs), 10001)

    def test_windowed_derivatives_match_full_history_results(self):
        timestamps = [float(index * 10) for index in range(2001)]
        values = [math.sin(index * 0.02) for index in range(2001)]
        self.window.data_model.add_series("F_X", "test", timestamps, values)
        self.window.reception_start_time = 0.0
        self.window.window_now = 20000.0
        self.window.auto_scroll_enabled = False
        self.window.plot_widget.setXRange(8000.0, 10000.0, padding=0)

        cases = [
            (
                "d_test",
                "d([F_X])",
                lambda: self.window._differentiate_curve_data(timestamps, values),
            ),
            (
                "sg_test",
                "sg([F_X], 150, 3, 1)",
                lambda: self.window._savgol_curve_data(timestamps, values, 150, 3, 1),
            ),
            (
                "tau_test",
                "joint_tau([F_X], 150, 3, 1, 0.1, 0.2, 0.01)",
                lambda: self.window._joint_tau_curve_data(
                    timestamps,
                    values,
                    150,
                    3,
                    1,
                    0.1,
                    0.2,
                    0.01,
                ),
            ),
        ]

        for name, expression, full_evaluator in cases:
            ast = CurveExpressionParser(expression).parse()
            self.window.create_derived_curve(name, expression, ast)
            self.window._curve_plot_data(name)
            actual_ts, actual_vs = self.window._curve_view_data[name]
            expected_ts, expected_vs = full_evaluator()
            expected = [
                (timestamp, value)
                for timestamp, value in zip(expected_ts, expected_vs)
                if 8000.0 <= timestamp <= 10000.0
            ]
            self.assertEqual(actual_ts, [item[0] for item in expected])
            self.assertEqual(len(actual_vs), len(expected))
            for actual, (_timestamp, expected_value) in zip(actual_vs, expected):
                self.assertAlmostEqual(actual, expected_value, places=9)

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

    def test_imported_replay_starts_paused_at_first_sample(self):
        self.window._load_imported_series(
            "/tmp/replay.csv",
            _series("a", [1.0, 2.0, 3.0]),
        )

        self.assertEqual(self.window.timeline.state, TimelineState.PAUSED)
        self.assertEqual(self.window.timeline.playhead_ms, 1000.0)
        self.assertEqual(self.window.timeline.latest_ms, 1020.0)
        self.assertEqual(self.window.now_line.value(), 1000.0)
        self.assertEqual(self.window.toggle_reception_btn.text(), "Play")

        self.window.set_curve_visibility("a", True)
        self.assertEqual(self.window.curves["a"].xData.tolist(), [1000.0, 1010.0, 1020.0])

        self.window.now_line.setValue(1010.0)

        self.assertEqual(self.window.timeline.playhead_ms, 1010.0)

        self.window.timeline_bar.slider.setValue(750000)

        self.assertEqual(self.window.timeline.playhead_ms, 1015.0)

    def test_live_pause_keeps_receiving_bounds_without_moving_playhead(self):
        self.window.timeline.begin_live()
        self.window.data_model.add_series(
            "a",
            "source-a",
            [1000.0, 1010.0],
            [1.0, 2.0],
        )
        self.window.available_raw_variables = {"a"}
        self.window._refresh_timeline_bounds(force=True)
        self.window.timeline.pause()

        self.window.data_model.add_data(
            "source-a",
            1020.0,
            1020.0,
            {"a": 3.0},
        )
        self.window._refresh_timeline_bounds(force=True)

        self.assertEqual(self.window.timeline.playhead_ms, 1010.0)
        self.assertEqual(self.window.timeline.latest_ms, 1020.0)
        self.assertEqual(self.window.timeline.state, TimelineState.PAUSED)
        self.assertEqual(self.window.toggle_reception_btn.text(), "Resume")
        self.assertEqual(self.window.timeline_bar.live_button.text(), "Live")

        self.window.toggle_reception()

        self.assertEqual(self.window.timeline.state, TimelineState.FOLLOW_LIVE)
        self.assertEqual(self.window.timeline.playhead_ms, 1020.0)

    def test_main_and_flight_windows_share_playhead(self):
        self.window._load_imported_series(
            "/tmp/replay.csv",
            _series("MadgwickTask.output.roll", [1.0, 2.0, 3.0]),
        )
        self.window.open_flight_visualization()
        visualization = self.window.flight_visualization_window
        visualization.timer.stop()

        self.window.timeline.seek(1010.0)

        self.assertIs(visualization.timeline, self.window.timeline)
        self.assertEqual(self.window.now_line.value(), 1010.0)
        self.assertEqual(visualization.timeline.playhead_ms, 1010.0)
        self.assertEqual(
            self.window.timeline_bar.slider.value(),
            visualization.timeline_bar.slider.value(),
        )
        visualization.close()

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
        self.assertIn(self.window.nf_clock_strategy_combo, row_widgets)
        self.assertIn(self.window.nf_clock_label, row_widgets)
        self.assertIs(row_widgets[-1], self.window.reset_section_layout_btn)
        self.assertNotIn(
            "ESP32 Dataflow Export (Dynamic):",
            [label.text() for label in self.window.findChildren(QLabel)],
        )

    def test_clock_alignment_status_is_compact_and_has_detailed_tooltip(self):
        self.window.data_receiver.get_nfv3_status = lambda: {
            "state": "connected",
            "local_ip": "192.168.4.2",
            "clock": {
                "state": "Locked",
                "uncertainty_us": 180.0,
                "drift_ppb": 72_400.0,
                "drift_uncertainty_ppb": 350.0,
                "sample_count": 400,
                "representative_count": 10,
                "sample_span_us": 20_000_000.0,
                "representative_span_us": 18_000_000.0,
                "rejected_count": 0,
                "minimum_rtt_us": 900.0,
            },
        }

        self.window.update_nfv3_status()

        self.assertEqual(
            self.window.nf_clock_label.text(),
            "Sync: Locked +/-0.18 ms | +72.4 ppm",
        )
        self.assertIn("minimum RTT: 900.0 us", self.window.nf_clock_label.toolTip())

    def test_clock_candidate_status_shows_diagnostic_not_applied_drift(self):
        self.window.data_receiver.get_nfv3_status = lambda: {
            "state": "connected",
            "clock": {
                "state": "Provisional",
                "offset_state": "Usable",
                "drift_state": "Candidate",
                "uncertainty_us": 300.0,
                "drift_ppb": 0.0,
                "candidate_drift_ppb": 81_500.0,
                "sample_count": 70,
                "representative_count": 35,
                "representative_span_us": 69_000_000.0,
            },
        }

        self.window.update_nfv3_status()

        self.assertEqual(
            self.window.nf_clock_label.text(),
            "Sync: Offset Usable | Drift Candidate +81.5 ppm 69 s",
        )
        tooltip = self.window.nf_clock_label.toolTip()
        self.assertIn("applied drift: +0.000 ppm", tooltip)
        self.assertIn("selected candidate: +81.500 ppm", tooltip)

    def test_clock_strategy_combo_switches_estimator_online(self):
        self.window.data_receiver.nf_connected = True
        epoch = self.window.data_receiver.nf_clock_estimator.epoch

        self.window.nf_clock_strategy_combo.setCurrentIndex(
            self.window.nf_clock_strategy_combo.findData("v3")
        )

        estimator = self.window.data_receiver.nf_clock_estimator
        self.assertEqual(estimator.strategy.value, "v3")
        self.assertEqual(estimator.epoch, epoch)
        self.assertTrue(
            self.window.data_receiver._clock_strategy_switch_pending
        )

    def test_clock_acquiring_status_exposes_transport_progress(self):
        self.window.data_receiver.get_nfv3_status = lambda: {
            "state": "connected",
            "clock": {
                "state": "Acquiring",
                "sample_count": 0,
                "representative_count": 0,
                "lock_required_representatives": 8,
                "blocker": "no clock response from 192.168.0.119:28081",
                "transport": {
                    "active": True,
                    "service_thread_alive": True,
                    "socket_ready": True,
                    "local_ip": "192.168.0.2",
                    "local_port": 41234,
                    "target_ip": "192.168.0.119",
                    "target_port": 28081,
                    "requests_due": 42,
                    "requests_sent": 42,
                    "request_send_failures": 0,
                    "responses_seen": 0,
                    "responses_matched": 0,
                    "outstanding": 42,
                    "samples_accepted": 0,
                    "samples_rejected": 0,
                    "last_send_age_ms": 25.0,
                    "last_response_age_ms": None,
                },
            },
        }

        self.window.update_nfv3_status()

        self.assertEqual(
            self.window.nf_clock_label.text(),
            "Sync: Acquiring | TX 42 RX 0",
        )
        tooltip = self.window.nf_clock_label.toolTip()
        self.assertIn(
            "blocked by: no clock response from 192.168.0.119:28081",
            tooltip,
        )
        self.assertIn("requests: due 42, sent 42, failed 0", tooltip)
        self.assertIn("target: 192.168.0.119:28081", tooltip)

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

    def test_transform_inputs_trim_zeroes_and_accept_large_offsets(self):
        self.window.selected_offset_spin.setValue(0.0)
        self.window.selected_scale_spin.setValue(1.0)
        self.assertEqual(self.window.selected_offset_spin.text(), "0")
        self.assertEqual(self.window.selected_scale_spin.text(), "1")

        self.window.selected_offset_spin.setValue(-4294967295.0)
        self.window.selected_scale_spin.setValue(1.25)
        self.assertEqual(
            self.window.selected_offset_spin.value(),
            -4294967295.0,
        )
        self.assertEqual(self.window.selected_offset_spin.text(), "-4294967295")
        self.assertEqual(self.window.selected_scale_spin.text(), "1.25")

    def test_waveform_capture_uses_current_signal_registry(self):
        self.window.open_waveform_capture()
        capture = self.window.waveform_capture_window
        self.assertEqual(capture.signal_names, self.window.signal_variables)
        capture.close()

    def test_flight_visualization_uses_current_signal_registry(self):
        self.window.available_raw_variables.add("FlightTask.output.pos_x")
        self.window.open_flight_visualization()
        visualization = self.window.flight_visualization_window
        visualization.timer.stop()
        visualization.refresh_variables(force=True)

        self.assertIs(visualization.data_model, self.window.data_model)
        self.assertGreaterEqual(
            visualization.binding_combos["position_x"].findData(
                "FlightTask.output.pos_x"
            ),
            0,
        )
        visualization.close()

    def test_v3_export_round_trip_restores_task_port_and_latency_metadata(self):
        self.window.register_dataflow_export_descriptors(_task_descriptors())
        for index, desc in enumerate(_task_descriptors()):
            name = desc["var_name"]
            self.window.data_model.add_series(
                name,
                f"test:{index}",
                [1000.0 + index, 1010.0 + index],
                [10.0 + index, 20.0 + index],
            )

        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        handle.close()
        try:
            self.assertEqual(self.window._write_monitor_csv(handle.name), 4)
            document = read_monitor_csv(handle.name)
        finally:
            os.unlink(handle.name)

        input_desc = document.series["MadgwickTask.input.roll"]
        self.assertEqual(input_desc["descriptor_kind"], "task_port")
        self.assertEqual(input_desc["direction"], 0)
        self.assertEqual(input_desc["slot"], 0)
        latency_desc = document.series["MadgwickTask.latency_us"]
        self.assertEqual(latency_desc["descriptor_kind"], "task_latency")
        self.assertTrue(latency_desc["hidden_control"])
        self.assertEqual(latency_desc["unit"], "us")

    def test_live_v3_export_includes_final_clock_snapshot_metadata(self):
        self.window._live_activation_requested = True
        self.assertTrue(
            self.window.activate_live_dataflow_export_descriptors(
                [{"var_name": "DataNode1", "section": "Dataflow/Default"}],
                "192.168.4.1",
                28080,
            )
        )
        self.window.data_model.add_series(
            "DataNode1",
            "test:clock",
            [1000.0],
            [1.0],
        )
        self.window.data_receiver.get_nfv3_clock_metadata = lambda: {
            "clock_model": "rolling_affine_interval_v2",
            "clock_state": "Locked",
            "clock_uncertainty_us": 180.0,
        }

        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        handle.close()
        try:
            self.assertEqual(self.window._write_monitor_csv(handle.name), 1)
            document = read_monitor_csv(handle.name)
        finally:
            os.unlink(handle.name)

        self.assertEqual(
            document.metadata["clock_model"],
            "rolling_affine_interval_v2",
        )
        self.assertEqual(document.metadata["clock_state"], "Locked")
        self.assertEqual(document.metadata["clock_uncertainty_us"], "180.0")

    def test_schema_change_removes_stale_task_group_and_latency_curve(self):
        self.window.register_dataflow_export_descriptors(_task_descriptors())
        self.window.register_dataflow_export_descriptors([_task_descriptors()[0]])

        self.assertNotIn("Task/5", self.window.dataflow_export_sections)
        self.assertNotIn(5, self.window.task_variable_groups)
        self.assertNotIn("MadgwickTask.latency_us", self.window.curves)


if __name__ == "__main__":
    unittest.main()

import struct
import sys
import types
import unittest
import queue
import socket
import threading
from unittest.mock import Mock, patch

from clock_alignment import AlignmentMode
from host_clock import ALIGNMENT_CLOCK, HostClockSample
from data_model import DataModel
from nfv3_parser import NFv3Parser


class _DummyBotaSerialSensor:
    def __init__(self, _port):
        return None

    def setup(self):
        return False

    def close(self):
        return None


_bota_mod = types.ModuleType("bota_lite")
_bota_mod.BotaSerialSensor = _DummyBotaSerialSensor
sys.modules["bota_lite"] = _bota_mod

_mocap_pkg = types.ModuleType("MoCap")
_mocap_lumo_pkg = types.ModuleType("MoCap.LuMo")
_mocap_sdk_mod = types.ModuleType("MoCap.LuMo.LuMoSDKClient")
_mocap_sdk_mod.Init = lambda: None
_mocap_sdk_mod.Connnect = lambda _ip: None
_mocap_sdk_mod.ReceiveData = lambda _timeout: None
_mocap_sdk_mod.Close = lambda: None
sys.modules["MoCap"] = _mocap_pkg
sys.modules["MoCap.LuMo"] = _mocap_lumo_pkg
sys.modules["MoCap.LuMo.LuMoSDKClient"] = _mocap_sdk_mod

_crc_mod = types.ModuleType("crc")


class _DummyConfiguration:
    def __init__(self, *args, **kwargs):
        return None


class _DummyCalculator:
    def __init__(self, *args, **kwargs):
        return None

    def checksum(self, _data):
        return 0


_crc_mod.Calculator = _DummyCalculator
_crc_mod.Configuration = _DummyConfiguration
sys.modules["crc"] = _crc_mod

from data_receiver import DataReceiver
from network_clock import ClockEstimatorStrategy, ClockTransform


class _DummyTransporter:
    def udp_send_mocap_message(self, _rigid):
        return None


class _DummyMainWindow:
    def __init__(self):
        self.data_transporter = _DummyTransporter()
        self.esp32_ip = "127.0.0.1"
        self.activate_live = True
        self.live_descriptors = []
        self.latency_updates = []
        self.clock_calibration_updates = 0

    def register_dataflow_export_variables(self, _names):
        return None

    def activate_live_dataflow_export_descriptors(self, descriptors, _host, _port):
        self.live_descriptors = list(descriptors)
        return self.activate_live

    def update_task_latency(self, task_id, latency_us):
        self.latency_updates.append((int(task_id), int(latency_us)))

    def clock_calibration_updated(self):
        self.clock_calibration_updates += 1


class _DummyDataModel:
    def __init__(self):
        self.records = []
        self.clock_transforms = {}
        self.clock_epochs = {}
        self.alignment_mode = AlignmentMode.REALTIME

    def add_data(self, src, unix_timestamp, src_timestamp, data, **kwargs):
        self.records.append((src, unix_timestamp, src_timestamp, dict(data), dict(kwargs)))

    def set_clock_transform(self, src, transform):
        if transform is None:
            self.clock_transforms.pop(src, None)
        else:
            self.clock_transforms[src] = transform

    def begin_clock_epoch(self, src, epoch):
        self.clock_epochs[src] = int(epoch)


class DataReceiverNFv3DecodeTest(unittest.TestCase):
    def setUp(self):
        self.model = _DummyDataModel()
        self.window = _DummyMainWindow()
        self.receiver = DataReceiver(
            self.model,
            self.window,
            udp_target_ip="127.0.0.1",
            udp_target_port=19001,
        )
        self.parser = self.receiver.nf_parser
        self.receiver.nf_connected = True
        self.receiver.nf_protocol = self.parser.VERSION

    def _entries(self):
        return [
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK,
                "task_id": 5,
                "category": self.parser.CATEGORY_DEVICE,
                "input_count": 1,
                "output_count": 1,
                "input_timestamp_group_count": 0,
                "output_timestamp_group_count": 1,
                "name": "MadgwickTask",
            },
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK_PORT,
                "task_id": 5,
                "direction": self.parser.PORT_INPUT,
                "slot": 0,
                "scalar_type": self.parser.TYPE_F32,
                "timestamp_group": self.parser.DEFAULT_TIMESTAMP_GROUP,
                "name": "roll",
                "unit": "deg",
            },
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK_PORT,
                "task_id": 5,
                "direction": self.parser.PORT_OUTPUT,
                "slot": 0,
                "scalar_type": self.parser.TYPE_F32,
                "timestamp_group": 0,
                "name": "yaw",
                "unit": "deg",
            },
        ]

    def _build_session_accept(self, client_nonce, session_id=0x11223344):
        codec = self.receiver.nf_v4_codec
        return struct.pack(
            codec.SESSION_ACCEPT_FMT,
            codec.MAGIC,
            codec.VERSION,
            codec.TYPE_SESSION_ACCEPT,
            client_nonce,
            session_id,
            codec.FEATURE_CLOCK_SYNC,
            28081,
            28082,
            6000,
        )

    def test_new_user_connection_uses_a_new_client_nonce(self):
        generated = iter((0x11111111, 0x22222222))
        self.receiver._new_nf_client_nonce_ = lambda: next(generated)
        self.receiver.running = True
        self.receiver._start_connect_attempt_ = lambda _now_ms: None

        self.receiver.connect_nfv3()
        first_nonce = self.receiver.nf_client_nonce
        self.receiver.disconnect_nfv3()
        self.receiver.connect_nfv3()

        self.assertEqual(first_nonce, 0x11111111)
        self.assertEqual(self.receiver.nf_client_nonce, 0x22222222)

    def test_stale_session_accept_is_ignored_during_reconnect(self):
        self.receiver.nf_want_connected = True
        self.receiver.nf_connecting = True
        self.receiver.nf_connected = False
        self.receiver.nf_client_nonce = 0x22222222

        self.receiver._process_udp_packet(
            self._build_session_accept(0x11111111),
            unix_ts=1000.0,
            meta={"remote_addr": ("127.0.0.1", 19001)},
        )

        self.assertTrue(self.receiver.nf_connecting)
        self.assertFalse(self.receiver.nf_connected)
        self.assertEqual(self.receiver.nf_session_id, 0)

    def test_session_accept_is_ignored_after_explicit_disconnect(self):
        self.receiver.nf_want_connected = False
        self.receiver.nf_connecting = False
        self.receiver.nf_connected = False
        self.receiver.nf_client_nonce = 0x22222222

        self.receiver._process_udp_packet(
            self._build_session_accept(0x22222222),
            unix_ts=1000.0,
            meta={"remote_addr": ("127.0.0.1", 19001)},
        )

        self.assertFalse(self.receiver.nf_connected)
        self.assertEqual(self.receiver.nf_session_id, 0)

    def test_current_session_accept_starts_clock_sync(self):
        self.receiver.nf_want_connected = True
        self.receiver.nf_connecting = True
        self.receiver.nf_connected = False
        self.receiver.nf_client_nonce = 0x22222222

        self.receiver._process_udp_packet(
            self._build_session_accept(0x22222222),
            unix_ts=1000.0,
            meta={"remote_addr": ("127.0.0.1", 19001)},
        )

        self.assertFalse(self.receiver.nf_connecting)
        self.assertTrue(self.receiver.nf_connected)
        self.assertEqual(self.receiver.nf_session_id, 0x11223344)
        self.assertTrue(self.receiver.nf_v4_clock.active)

    def test_export_fits_all_observations_and_omits_realtime_model(self):
        for session, start in ((1, 10_000_000), (2, 30_000_000)):
            for index in range(20):
                t1 = start + index * 1_000_000
                t2 = t1 - 500_000 + 1_000
                t3 = t2 + 100
                t4 = t1 + 1_600
                self.receiver.clock_observations.add_neuroflap(
                    session, index, t1, t2, t3, t4
                )

        clock_data = self.receiver.get_clock_export_data()

        self.assertEqual(clock_data["active_mode"], "calibrated")
        self.assertEqual(clock_data["clock_fit_status"], "complete")
        self.assertEqual(clock_data["clock_fit_model_count"], 2)
        self.assertEqual(clock_data["clock_fit_error_count"], 0)
        self.assertEqual(
            {(row["domain"], row["session"]) for row in clock_data["models"]},
            {("neuroflap", 1), ("neuroflap", 2)},
        )
        self.assertTrue(
            all(row["mode"] == "calibrated" for row in clock_data["models"])
        )
        self.assertTrue(
            all(row["fit_scope"] == "all_capture_observations" for row in clock_data["models"])
        )
        self.assertEqual(len(clock_data["observations"]), 40)

    def test_realtime_clock_strategy_is_not_switchable(self):
        epoch = self.receiver.nf_clock_estimator.epoch
        self.model.clock_transforms[self.receiver.NF_CLOCK_SOURCE] = ClockTransform(
            usable=True, epoch=epoch
        )

        changed = self.receiver.set_clock_estimator_strategy(
            ClockEstimatorStrategy.V3
        )

        self.assertFalse(changed)
        self.assertEqual(self.receiver.nf_clock_estimator.epoch, epoch)
        self.assertIn(self.receiver.NF_CLOCK_SOURCE, self.model.clock_transforms)
        self.assertFalse(self.receiver._clock_strategy_switch_pending)
        self.assertFalse(self.receiver._clock_strategy_holdover)

    def test_background_calibration_is_installed_atomically(self):
        model = DataModel([])
        window = _DummyMainWindow()
        receiver = DataReceiver(
            model,
            window,
            udp_target_ip="127.0.0.1",
            udp_target_port=19001,
        )
        scale = 1.0 + 60.0e-6
        offset_us = 400_000.0
        for index in range(40):
            t1 = 10_000_000 + index * 1_000_000
            t2 = int((t1 + 1_000 - offset_us) / scale)
            t3 = t2 + 100
            t4 = int(t3 * scale + offset_us + 1_200)
            receiver.clock_observations.add_neuroflap(
                1, index, t1, t2, t3, t4
            )

        self.assertTrue(receiver.request_clock_calibration())
        receiver._clock_calibration_thread.join(timeout=2.0)
        receiver._apply_clock_calibration_results()

        self.assertEqual(model.alignment_mode, AlignmentMode.CALIBRATED)
        self.assertTrue(
            model.has_calibrated_clock_transform(receiver.NF_CLOCK_SOURCE, 1)
        )
        self.assertEqual(window.clock_calibration_updates, 1)
        self.assertEqual(
            receiver.calibrated_clock_models[("neuroflap", 1)].host_clock,
            ALIGNMENT_CLOCK,
        )
        plot_data = receiver.get_clock_offset_plot_data("neuroflap")
        self.assertEqual(plot_data["count"], 40)
        self.assertEqual(len(plot_data["lower_delta_ms"]), 40)
        self.assertEqual(len(plot_data["realtime_delta_ms"]), 40)
        self.assertEqual(len(plot_data["calibrated_delta_ms"]), 40)

    def _install_schema(self, generation=1, chunks=1):
        entries = self._entries()
        if chunks == 1:
            self.receiver._handle_nfv3_schema_response(
                {
                    "schema_generation": generation,
                    "chunk_index": 0,
                    "chunk_total": 1,
                    "total_entries": len(entries),
                    "entries": entries,
                }
            )
            return
        split = len(entries) // 2
        self.receiver._handle_nfv3_schema_response(
            {
                "schema_generation": generation,
                "chunk_index": 1,
                "chunk_total": 2,
                "total_entries": len(entries),
                "entries": entries[split:],
            }
        )
        self.receiver._handle_nfv3_schema_response(
            {
                "schema_generation": generation,
                "chunk_index": 0,
                "chunk_total": 2,
                "total_entries": len(entries),
                "entries": entries[:split],
            }
        )

    def _build_data_packet(
        self, packet_seq=10, generation=1, snapshot_contention_count=0
    ):
        packet_time_us = 1_000_000
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            generation,
            packet_seq,
            packet_time_us,
            1,
            0,
        )
        task = struct.pack(
            self.parser.TASK_FRAME_HEADER_FMT,
            5,
            self.parser.TASK_FLAG_EXECUTABLE_ENABLED
            | self.parser.TASK_FLAG_INPUTS_VALID
            | self.parser.TASK_FLAG_OUTPUTS_VALID
            | (
                (snapshot_contention_count & self.parser.TASK_CONTENTION_MASK)
                << self.parser.TASK_CONTENTION_SHIFT
            ),
            100,
            50,
        )
        task += struct.pack("<II", 0x3F800000, 0x40000000)
        task += struct.pack("<I", 25)
        return self.parser.parse_packet(header + task)

    def test_schema_response_builds_task_port_keys(self):
        self._install_schema(generation=2, chunks=2)

        self.assertEqual(self.receiver.nf_schema_generation, 2)
        output_key = ("task", 5, self.parser.PORT_OUTPUT, 0)
        latency_key = ("task_latency", 5)
        self.assertEqual(self.receiver.nf_schema_by_key[output_key]["var_name"], "MadgwickTask.output.yaw")
        self.assertEqual(self.receiver.nf_schema_by_key[latency_key]["var_name"], "MadgwickTask.latency_us")
        self.assertTrue(self.receiver.nf_schema_by_key[latency_key]["hidden_control"])
        self.assertEqual(self.receiver.nf_schema_by_key[output_key]["category"], "device")
        self.assertEqual(len(self.window.live_descriptors), 3)

    def test_compact_frames_publish_default_and_custom_timestamps(self):
        self._install_schema()
        packet = self._build_data_packet()

        self.receiver._process_nfv3_data(packet, unix_ts=2000.0)

        records = {next(iter(record[3])): record for record in self.model.records}
        self.assertEqual(records["MadgwickTask.latency_us"][2], 999.9)
        self.assertEqual(records["MadgwickTask.latency_us"][3], {"MadgwickTask.latency_us": 50.0})
        self.assertEqual(records["MadgwickTask.input.roll"][2], 999.9)
        self.assertEqual(records["MadgwickTask.output.yaw"][2], 999.975)
        self.assertEqual(records["MadgwickTask.output.yaw"][3], {"MadgwickTask.output.yaw": 2.0})
        self.assertEqual(records["MadgwickTask.output.yaw"][4]["offset_timestamp"], 1000.0)
        self.assertEqual(self.window.latency_updates, [(5, 50)])

    def test_first_nfv4_data_after_capture_clear_uses_active_clock_epoch(self):
        self.receiver.data_model = model = DataModel([])
        self.receiver.nf_protocol = self.receiver.nf_v4_codec.VERSION
        self.receiver.nf_clock_estimator.reset("new_connection")
        epoch = self.receiver.nf_clock_estimator.epoch
        self.assertGreater(epoch, 1)
        self._install_schema()

        for packet_seq in (10, 11):
            with self.subTest(packet_seq=packet_seq):
                model.begin_clock_epoch(self.receiver.NF_CLOCK_SOURCE, epoch)
                model.clear()
                self.receiver._process_nfv3_data(
                    self._build_data_packet(packet_seq=packet_seq), unix_ts=2000.0
                )

                self.assertEqual(
                    model.ensure_source(self.receiver.NF_CLOCK_SOURCE).current_session,
                    epoch,
                )
                for name in (
                    "MadgwickTask.latency_us",
                    "MadgwickTask.input.roll",
                    "MadgwickTask.output.yaw",
                ):
                    self.assertEqual(model.get_raw_series(name)[1], [epoch])

    def test_invalid_or_reversed_task_times_do_not_publish_latency(self):
        self._install_schema()
        invalid = self._build_data_packet()
        invalid["task_frames"][0]["input_age_us"] = self.parser.INVALID_AGE_US
        self.receiver._process_nfv3_data(invalid, unix_ts=2000.0)

        reversed_times = self._build_data_packet(packet_seq=11)
        reversed_times["task_frames"][0]["input_age_us"] = 25
        reversed_times["task_frames"][0]["output_age_us"] = 50
        self.receiver._process_nfv3_data(reversed_times, unix_ts=2001.0)

        names = [next(iter(record[3])) for record in self.model.records]
        self.assertNotIn("MadgwickTask.latency_us", names)
        self.assertEqual(self.window.latency_updates, [])

    def test_function_uses_task_frame_and_shared_finish_timestamp(self):
        entries = [
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK,
                "task_id": 0x7000,
                "category": self.parser.CATEGORY_FUNCTION,
                "input_count": 0,
                "output_count": 2,
                "input_timestamp_group_count": 0,
                "output_timestamp_group_count": 0,
                "name": "offset_mixer",
            },
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK_PORT,
                "task_id": 0x7000,
                "direction": self.parser.PORT_OUTPUT,
                "slot": 0,
                "scalar_type": self.parser.TYPE_F32,
                "timestamp_group": self.parser.DEFAULT_TIMESTAMP_GROUP,
                "name": "left",
                "unit": "deg",
            },
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK_PORT,
                "task_id": 0x7000,
                "direction": self.parser.PORT_OUTPUT,
                "slot": 1,
                "scalar_type": self.parser.TYPE_F32,
                "timestamp_group": self.parser.DEFAULT_TIMESTAMP_GROUP,
                "name": "right",
                "unit": "deg",
            },
        ]
        self.receiver._handle_nfv3_schema_response(
            {
                "schema_generation": 3,
                "chunk_index": 0,
                "chunk_total": 1,
                "total_entries": len(entries),
                "entries": entries,
            }
        )
        packet_time_us = 1_000_000
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            3,
            1,
            packet_time_us,
            1,
            0,
        )
        frame = struct.pack(
            self.parser.TASK_FRAME_HEADER_FMT,
            0x7000,
            self.parser.TASK_FLAG_OUTPUTS_VALID,
            120,
            20,
        ) + struct.pack("<II", 0x3F800000, 0x40000000)
        packet = self.parser.parse_packet(header + frame)
        self.receiver._process_nfv3_data(packet, unix_ts=2000.0)

        left = self.model.records[-2]
        right = self.model.records[-1]
        self.assertEqual(left[3], {"offset_mixer.output.left": 1.0})
        self.assertEqual(right[3], {"offset_mixer.output.right": 2.0})
        self.assertEqual(left[2], 999.98)
        self.assertEqual(right[2], 999.98)
        self.assertEqual(
            self.receiver.nf_schema_by_key[("task", 0x7000, self.parser.PORT_OUTPUT, 0)]["category"],
            "function",
        )
        self.assertEqual(
            self.receiver.nf_schema_by_key[("task", 0x7000, self.parser.PORT_OUTPUT, 0)]["section"],
            "Function/offset_mixer",
        )

    def test_zero_port_task_still_exposes_and_publishes_latency(self):
        entry = {
            "entry_kind": self.parser.SCHEMA_KIND_TASK,
            "task_id": 9,
            "input_count": 0,
            "output_count": 0,
            "input_timestamp_group_count": 0,
            "output_timestamp_group_count": 0,
            "name": "EmptyTask",
        }
        self.receiver._handle_nfv3_schema_response(
            {
                "schema_generation": 3,
                "chunk_index": 0,
                "chunk_total": 1,
                "total_entries": 1,
                "entries": [entry],
            }
        )
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            3,
            1,
            1_000_000,
            1,
            0,
        )
        task = struct.pack(
            self.parser.TASK_FRAME_HEADER_FMT,
            9,
            self.parser.TASK_FLAG_EXECUTABLE_ENABLED,
            40,
            10,
        )

        self.receiver._process_nfv3_data(self.parser.parse_packet(header + task), unix_ts=2000.0)

        self.assertEqual(len(self.window.live_descriptors), 1)
        self.assertEqual(self.window.live_descriptors[0]["var_name"], "EmptyTask.latency_us")
        self.assertEqual(self.model.records[0][2], 999.96)
        self.assertEqual(self.model.records[0][3], {"EmptyTask.latency_us": 30.0})

    def test_replay_gate_drops_data_but_keeps_schema(self):
        self._install_schema()
        self.receiver.set_data_ingestion_enabled(False)

        self.receiver._process_nfv3_data(self._build_data_packet(), unix_ts=1000.0)

        self.assertEqual(self.model.records, [])
        self.assertEqual(self.receiver.nf_schema_generation, 1)

    def test_snapshot_contention_is_counted_while_ingestion_is_paused(self):
        self._install_schema()
        self.receiver.set_data_ingestion_enabled(False)

        packet = self._build_data_packet(snapshot_contention_count=3)
        self.receiver._process_nfv3_data(packet, unix_ts=1000.0)

        diagnostics = self.receiver.get_nfv3_status()["snapshot_contention"]
        self.assertEqual(diagnostics["total"], 3)
        self.assertEqual(diagnostics["tasks"][0]["task_name"], "MadgwickTask")
        self.assertEqual(diagnostics["tasks"][0]["recent_2s"], 3)
        self.assertEqual(self.model.records, [])

    def test_snapshot_contention_resets_for_a_new_connection(self):
        self._install_schema()
        packet = self._build_data_packet(snapshot_contention_count=2)
        self.receiver._process_nfv3_data(packet, unix_ts=1000.0)
        self.assertEqual(
            self.receiver.get_nfv3_status()["snapshot_contention"]["total"],
            2,
        )

        self.receiver.running = True
        self.receiver._start_connect_attempt_ = lambda _now_ms: None
        self.receiver.connect_nfv3()

        diagnostics = self.receiver.get_nfv3_status()["snapshot_contention"]
        self.assertEqual(diagnostics, {"total": 0, "tasks": []})

    def test_schema_activation_reenables_live_ingestion(self):
        self.receiver.set_data_ingestion_enabled(False)
        self._install_schema()
        self.assertTrue(self.receiver.data_ingestion_enabled)

    def test_unknown_generation_requests_schema(self):
        self._install_schema()
        packet = self._build_data_packet(generation=9)
        self.receiver.nf_schema_retry_active = False

        self.receiver._process_nfv3_data(packet, unix_ts=1000.0)

        self.assertEqual(self.model.records, [])
        self.assertTrue(self.receiver.nf_schema_retry_active)

    def test_diagnostic_sequence_counter_counts_missing_packets(self):
        last, missing = self.receiver._advance_sequence_counter(10, None)
        self.assertEqual((last, missing), (10, 0))
        last, missing = self.receiver._advance_sequence_counter(13, last)
        self.assertEqual((last, missing), (13, 2))
        last, missing = self.receiver._advance_sequence_counter(13, last)
        self.assertEqual((last, missing), (13, 0))

    def test_probe_is_counted_and_feedback_does_not_enter_data_model(self):
        sent = []
        self.receiver._send_diag_udp_packet_ = (
            lambda packet, target=None: sent.append((packet, target)) or True
        )
        packet_size = 1200
        header = struct.pack(
            self.parser.DIAG_PROBE_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_PROBE,
            11,
            0,
            self.parser.DIAG_PROBE_STAGE_START
            | self.parser.DIAG_PROBE_STAGE_END,
            packet_size,
            5,
            123456,
            100,
            0,
        )

        handled = self.receiver._handle_nfv3_diag_datagram_(
            header + bytes(packet_size - len(header)),
            ("127.0.0.1", 19002),
        )

        self.assertTrue(handled)
        self.assertEqual(self.receiver.nf_diag_probe_packets_rx, 1)
        self.assertEqual(self.receiver.nf_diag_probe_last_seq, 5)
        self.assertEqual(self.model.records, [])
        self.assertEqual(len(sent), 1)
        feedback = struct.unpack(self.parser.DIAG_FEEDBACK_FMT, sent[0][0])
        self.assertEqual(feedback[2], self.parser.TYPE_DIAG_FEEDBACK)
        self.assertEqual(feedback[3], 11)
        self.assertEqual(
            feedback[5] & self.parser.DIAG_FEEDBACK_STAGE_COMPLETE,
            self.parser.DIAG_FEEDBACK_STAGE_COMPLETE,
        )
        self.assertEqual(feedback[9], 1)

    def test_echo_request_is_answered_in_receive_fast_path(self):
        sent = []
        self.receiver._send_diag_udp_packet_ = (
            lambda packet, target=None: sent.append((packet, target)) or True
        )
        request = struct.pack(
            self.parser.DIAG_ECHO_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_ECHO_REQUEST,
            5,
            23,
            123456,
            0,
            0,
            0xFF,
        )

        handled = self.receiver._handle_nfv3_diag_datagram_(
            request,
            ("127.0.0.1", 19002),
        )

        self.assertTrue(handled)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], ("127.0.0.1", 19002))
        response = self.parser.parse_packet(sent[0][0])
        self.assertEqual(response["type"], "diag_echo_response")
        self.assertEqual(response["sequence"], 23)
        self.assertEqual(response["t1_us"], 123456)
        self.assertGreater(response["t2_us"], 0)
        self.assertGreaterEqual(response["t3_us"], response["t2_us"])
        self.assertEqual(response["flags"], 0xFF)
        self.assertEqual(len(self.receiver.pending_queue), 0)

    def test_control_actions_route_to_workers_without_gui_queue(self):
        actions = []
        self.receiver._start_nfv3_udp_upload_ = (
            lambda packet, remote: actions.append(("udp", packet["stage"], remote))
        )
        control = struct.pack(
            self.parser.DIAG_CONTROL_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_CONTROL,
            44,
            self.parser.DIAG_CONTROL_UDP_UPLOAD_START,
            self.parser.DIAG_MODE_UDP_CAPACITY,
            2,
            0,
            250,
            1200,
            3000,
            28081,
            0,
        )

        handled = self.receiver._handle_nfv3_diag_datagram_(
            control,
            ("127.0.0.1", 19002),
        )

        self.assertTrue(handled)
        self.assertEqual(actions, [("udp", 2, ("127.0.0.1", 19002))])
        self.assertEqual(len(self.receiver.pending_queue), 0)


class _DiagnosticSocket:
    """Blocking in-memory socket for diagnostic worker lifecycle tests."""

    def __init__(self):
        self.incoming = queue.Queue()
        self.closed = threading.Event()
        self.sent = []

    def bind(self, _endpoint):
        pass

    def settimeout(self, _timeout):
        pass

    def getsockname(self):
        return ("127.0.0.1", 30000)

    def recvfrom(self, _size):
        if self.closed.is_set():
            raise OSError("socket closed")
        try:
            item = self.incoming.get(timeout=0.01)
        except queue.Empty:
            raise socket.timeout() from None
        if isinstance(item, Exception):
            raise item
        return item

    def sendto(self, packet, endpoint):
        self.sent.append((packet, endpoint))
        return len(packet)

    def close(self):
        self.closed.set()


class DataReceiverSessionLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.receiver = DataReceiver(
            DataModel([]), _DummyMainWindow(),
            udp_target_ip="127.0.0.1", udp_target_port=19001,
        )
        self.parser = self.receiver.nf_parser
        self.codec = self.receiver.nf_v4_codec
        self.peer = ("127.0.0.1", 19002)
        self.receiver._resolve_local_ip = Mock()
        self.receiver._send_udp_packet = Mock(return_value=True)
        self.addCleanup(self.receiver._stop_nfv3_diag_service_)

    def _connected_v4(self):
        r = self.receiver
        r.nf_protocol = self.codec.VERSION
        r.nf_connected = True
        r.nf_connecting = False
        r.nf_want_connected = True
        r.nf_session_id = 123
        r.nf_last_pong_ms = 1_000_000.0

    def _accept(self):
        r = self.receiver
        packet = struct.pack(
            self.codec.SESSION_ACCEPT_FMT,
            self.codec.MAGIC, self.codec.VERSION, self.codec.TYPE_SESSION_ACCEPT,
            r.nf_client_nonce, 123, self.codec.FEATURE_CLOCK_SYNC,
            19002, 19003, 6000,
        )
        r._process_udp_packet(packet, 1.0, {"remote_addr": self.peer})

    def test_wall_clock_steps_cannot_expire_live_v4_session(self):
        self._connected_v4()
        for wall_seconds in (1.0, 1_000_000_000.0):
            with self.subTest(wall_seconds=wall_seconds), patch(
                "data_receiver.time.time", return_value=wall_seconds
            ), patch("data_receiver.time.monotonic", return_value=1001.0):
                self.receiver._tick_nfv3_connection()
                self.assertTrue(self.receiver.nf_connected)

    def test_real_monotonic_timeout_still_reconnects(self):
        self._connected_v4()
        with patch("data_receiver.time.time", return_value=1.0), patch(
            "data_receiver.time.monotonic", return_value=1006.0
        ):
            self.receiver._tick_nfv3_connection()
        self.assertFalse(self.receiver.nf_connected)
        self.assertEqual(self.receiver.nf_last_error, "link timeout")
        self.assertEqual(self.receiver.nf_next_reconnect_ms, 1_006_500.0)

    def test_connect_request_and_accept_share_monotonic_deadlines(self):
        r = self.receiver
        with patch("data_receiver.time.time", side_effect=AssertionError("wall clock used")), patch(
            "data_receiver.time.monotonic", return_value=1000.0
        ), patch.object(r, "start"):
            r.connect_nfv3()
            self.assertEqual(r.nf_connect_start_ms, 1_000_000.0)
            self.assertEqual(r.nf_last_connect_req_ms, 1_000_000.0)
            self._accept()
        self.assertTrue(r.nf_connected)
        self.assertEqual(r.nf_last_pong_ms, 1_000_000.0)
        self.assertEqual(r.nf_last_schema_request_ms, 1_000_000.0)

    def test_connect_timeout_and_backoff_use_monotonic_clock(self):
        r = self.receiver
        r.nf_want_connected = True
        with patch("data_receiver.time.time", side_effect=AssertionError("wall clock used")), patch(
            "data_receiver.time.monotonic", return_value=1000.0
        ) as clock:
            r._start_connect_attempt_(1_000_000.0)
            clock.return_value = 1004.999
            r._tick_nfv3_connection()
            self.assertTrue(r.nf_connecting)
            clock.return_value = 1005.0
            r._tick_nfv3_connection()
            self.assertFalse(r.nf_connecting)
            self.assertEqual(r.nf_last_error, "connect timeout")
            with patch.object(r, "_start_connect_attempt_") as start:
                clock.return_value = 1005.499
                r._tick_nfv3_connection()
                start.assert_not_called()
                clock.return_value = 1005.5
                r._tick_nfv3_connection()
                start.assert_called_once_with(1_005_500.0)

    def test_schema_retry_and_request_throttle_use_monotonic_clock(self):
        r = self.receiver
        self._connected_v4()
        with patch("data_receiver.time.time", side_effect=AssertionError("wall clock used")), patch(
            "data_receiver.time.monotonic", return_value=1000.0
        ) as clock:
            self.assertTrue(r._request_nfv3_schema())
            clock.return_value = 1000.999
            self.assertFalse(r._request_nfv3_schema())
            clock.return_value = 1001.0
            self.assertTrue(r._request_nfv3_schema())
            r.nf_schema_retry_active = True
            r.nf_next_schema_retry_ms = 1_002_000.0
            with patch.object(r, "_request_nfv3_schema") as request:
                r._tick_nfv3_schema_retry()
                request.assert_not_called()
                clock.return_value = 1002.0
                r._tick_nfv3_schema_retry()
                request.assert_called_once_with(force=True)
                self.assertEqual(r.nf_next_schema_retry_ms, 1_003_000.0)

    def test_legacy_ping_and_disconnect_burst_use_monotonic_clock(self):
        r = self.receiver
        r.nf_protocol = self.parser.VERSION
        r.nf_connected = True
        pong = struct.pack(
            "<HBB", self.parser.MAGIC, self.parser.VERSION, self.parser.TYPE_LINK_PONG
        )
        with patch("data_receiver.time.time", side_effect=AssertionError("wall clock used")), patch(
            "data_receiver.time.monotonic", return_value=1000.0
        ) as clock:
            r._process_udp_packet(pong, 1.0, {})
            self.assertEqual(r.nf_last_pong_ms, 1_000_000.0)
            self.assertEqual(r.nf_next_ping_due_ms, 1_002_000.0)
            r.disconnect_nfv3()
            self.assertEqual(r.nf_next_disconnect_burst_ms, 1_000_120.0)
            with patch.object(r, "_send_disconnect_request") as send:
                clock.return_value = 1000.119
                r._tick_nfv3_connection()
                send.assert_not_called()
                clock.return_value = 1000.121
                r._tick_nfv3_connection()
                send.assert_called_once()

    def test_matched_v4_response_refreshes_monotonic_liveness_not_raw_time(self):
        r = self.receiver
        self._connected_v4()
        r.nf_v4_clock.start_session(r.nf_session_id)
        sent = []
        r.nf_v4_clock.tick(
            lambda data: sent.append(data) or HostClockSample(10_000_000, 20_000_000),
            now_us=20_000_000,
        )
        request = struct.unpack(self.codec.SYNC_REQUEST_FMT, sent[0])
        for expected_session, expected_sequence, expected_pong in (
            (999, request[4], 1_000_000.0),
            (123, request[4] + 1, 1_000_000.0),
            (123, request[4], 20_002.0),
        ):
            packet = struct.pack(
                self.codec.SYNC_RESPONSE_FMT,
                self.codec.MAGIC, self.codec.VERSION, self.codec.TYPE_SYNC_RESPONSE,
                expected_session, expected_sequence, 9_500_700, 9_500_740,
                request[5], request[6], request[7], 0,
            )
            with patch("data_receiver.time.time", side_effect=AssertionError("wall clock used")), patch(
                "data_receiver.time.monotonic", return_value=20.002
            ):
                r._handle_nfv4_aux_datagram_(
                    packet, self.peer, HostClockSample(10_001_600, 20_001_600)
                )
            self.assertEqual(r.nf_last_pong_ms, expected_pong)
        observations = r.clock_observations.neuroflap_snapshot(r.nf_clock_estimator.epoch)
        self.assertEqual(observations[0].t1_us, 10_000_000)

    def test_legacy_clock_sample_is_ignored_in_v4_session(self):
        self._connected_v4()
        packet = struct.pack(
            self.parser.DIAG_CLOCK_SAMPLE_FMT,
            self.parser.MAGIC, self.parser.VERSION, self.parser.TYPE_DIAG_CLOCK_SAMPLE,
            0, 1, 1_000_000, 2_001_000, 2_001_100, 1_002_100, 0,
        )
        with patch.object(self.receiver, "_process_nfv3_clock_sample_") as handle:
            self.assertTrue(self.receiver._handle_nfv3_diag_datagram_(packet, self.peer))
            handle.assert_not_called()
        self.assertEqual(self.receiver.nf_clock_estimator.snapshot().sample_count, 0)

    def test_legacy_sample_and_metadata_use_scheduler_anchor(self):
        r = self.receiver
        r.nf_protocol = self.parser.VERSION
        r.nf_connected = True
        r._clock_wall_anchor_us = 100_000_000
        r._clock_monotonic_anchor_us = 2_000_000
        r._clock_alignment_anchor_us = 1_500_000
        with patch.object(r, "_send_diag_udp_packet_", return_value=True) as send:
            r._process_nfv3_clock_sample_(
                dict(test_id=0, t1_us=1_000_000, t2_us=2_001_000,
                     t3_us=2_001_100, t4_us=1_002_100), self.peer,
            )
        send.assert_called_once()
        transform = r.nf_clock_estimator.transform
        expected = int(transform.target_anchor_us + 98_000_000)
        metadata = r.get_nfv3_clock_metadata()
        self.assertEqual(metadata["clock_target_anchor_unix_us"], expected)
        self.assertEqual(r.data_model.clock_transforms[r.NF_CLOCK_SOURCE].target_anchor_us, expected)

    def test_legacy_clock_path_initializes_its_anchor_without_manual_setup(self):
        r = self.receiver
        r.nf_protocol = self.parser.VERSION
        with patch.object(r, "_send_diag_udp_packet_", return_value=True):
            r._process_nfv3_clock_sample_(
                dict(test_id=0, t1_us=1_000_000, t2_us=2_001_000,
                     t3_us=2_001_100, t4_us=1_002_100), self.peer,
            )
        self.assertEqual(r.get_nfv3_clock_metadata()["clock_sample_count"], 1)

    def test_v4_metadata_uses_alignment_anchor(self):
        r = self.receiver
        self._connected_v4()
        r._clock_capture_epoch_offset_us = 88_000_000
        r.nf_clock_estimator.add_monitor_initiated(
            2_000_000, 1_500_700, 1_500_740, 2_001_600
        )
        metadata = r.get_nfv3_clock_metadata()
        self.assertEqual(
            metadata["clock_target_anchor_unix_us"],
            int(r.nf_clock_estimator.transform.target_anchor_us + 88_000_000),
        )

    def _run_scripted_worker(self, events, handler=None):
        r = self.receiver
        diag_socket = Mock()
        diag_socket.recvfrom.side_effect = events
        r.running = True
        r._nf_diag_socket = diag_socket
        if handler:
            r._handle_nfv3_diag_datagram_ = handler
        with self.assertLogs("data_receiver", level="WARNING"):
            r._run_nfv3_diag_service_(diag_socket)
        self.assertIsNone(r._nf_diag_socket)
        diag_socket.close.assert_called_once()
        return diag_socket

    def test_bad_packet_does_not_kill_worker_or_skip_clock_tick(self):
        self._connected_v4()
        r = self.receiver
        handler = Mock(side_effect=[ValueError("bad packet"), None])
        with patch.object(r.nf_v4_clock, "tick") as tick:
            self._run_scripted_worker(
                [(b"bad", self.peer), (b"good", self.peer), OSError("broken socket")], handler
            )
        self.assertEqual(handler.call_count, 2)
        self.assertEqual(tick.call_count, 2)
        self.assertEqual(r._nf_diag_service_error_count, 2)

    def test_maintenance_failure_is_reported_and_socket_released(self):
        self._connected_v4()
        r = self.receiver
        with patch.object(r.nf_v4_clock, "tick", side_effect=RuntimeError("tick failed")):
            self._run_scripted_worker([socket.timeout()])
        self.assertIn("tick failed", r.nf_last_error)
        status = r.get_nfv3_clock_status()["transport"]
        self.assertFalse(status["socket_ready"])
        self.assertEqual(status["service_error_count"], 1)
        self.assertIn("tick failed", status["service_last_error"])

    def test_error_logging_is_rate_limited_but_all_errors_count(self):
        r = self.receiver
        handler = Mock(side_effect=ValueError("bad packet"))
        with patch("data_receiver.time.monotonic", return_value=1000.0), patch(
            "data_receiver.logging.getLogger"
        ) as logger:
            diag_socket = Mock()
            diag_socket.recvfrom.side_effect = [
                (b"bad", self.peer), (b"bad", self.peer), OSError("broken socket")
            ]
            r.running = True
            r._nf_diag_socket = diag_socket
            r._handle_nfv3_diag_datagram_ = handler
            r._run_nfv3_diag_service_(diag_socket)
        self.assertEqual(r._nf_diag_service_error_count, 3)
        logger.return_value.warning.assert_called_once()

    def test_socket_failure_reconnects_with_new_worker_without_stopping_receiver(self):
        r = self.receiver
        first, second = _DiagnosticSocket(), _DiagnosticSocket()
        first.incoming.put(OSError("first socket failed"))
        r.running = True
        r.nf_want_connected = True
        with patch("data_receiver.socket.socket", side_effect=[first, second]), self.assertLogs(
            "data_receiver", level="WARNING"
        ), patch("data_receiver.time.monotonic", return_value=1000.0) as clock:
            r._start_connect_attempt_(1_000_000.0)
            old_thread = r._nf_diag_service_thread
            old_thread.join(timeout=1.0)
            self.assertFalse(old_thread.is_alive())
            self._connected_v4()
            r._tick_nfv3_connection()
            self.assertFalse(r.nf_connected)
            self.assertIn("first socket failed", r.nf_last_error)
            clock.return_value = 1000.5
            r._tick_nfv3_connection()
            self.assertTrue(r.nf_connecting)
            self.assertTrue(r._nf_diag_service_thread.is_alive())
            self.assertIsNot(r._nf_diag_service_thread, old_thread)
            self.assertIs(r._nf_diag_socket, second)
            self._accept()
            self.assertTrue(r.nf_connected)
            self.assertTrue(r.running)
            status = r.get_nfv3_clock_status()["transport"]
            self.assertEqual(status["service_error_count"], 1)

    def test_start_failure_uses_backoff_and_does_not_open_session(self):
        r = self.receiver
        r.running = True
        r.nf_want_connected = True
        diag_socket = Mock()
        diag_socket.bind.side_effect = OSError("bind failed")
        with patch("data_receiver.socket.socket", return_value=diag_socket), self.assertLogs(
            "data_receiver", level="WARNING"
        ):
            r._start_connect_attempt_(1_000_000.0)
        self.assertFalse(r.nf_connecting)
        self.assertIsNone(r._nf_diag_socket)
        self.assertIsNone(r._nf_diag_service_thread)
        self.assertEqual(r.nf_next_reconnect_ms, 1_000_500.0)
        self.assertIn("bind failed", r.nf_last_error)
        r._send_udp_packet.assert_not_called()
        diag_socket.close.assert_called_once()

    def test_start_is_idempotent_and_stop_closes_and_joins_worker(self):
        r = self.receiver
        r.running = True
        diag_socket = _DiagnosticSocket()
        with patch("data_receiver.socket.socket", return_value=diag_socket) as factory:
            self.assertTrue(r._start_nfv3_diag_service_())
            thread = r._nf_diag_service_thread
            self.assertTrue(r._start_nfv3_diag_service_())
            factory.assert_called_once()
        r._stop_nfv3_diag_service_()
        self.assertFalse(thread.is_alive())
        self.assertTrue(diag_socket.closed.is_set())
        self.assertIsNone(r._nf_diag_service_thread)
        self.assertIsNone(r._nf_diag_socket)
        self.assertEqual(r._nf_diag_service_error_count, 0)

    def test_thread_start_failure_closes_socket_and_uses_backoff(self):
        r = self.receiver
        r.running = True
        r.nf_want_connected = True
        diag_socket = Mock()
        with patch("data_receiver.socket.socket", return_value=diag_socket), patch(
            "data_receiver.threading.Thread.start", side_effect=RuntimeError("thread unavailable")
        ), self.assertLogs("data_receiver", level="WARNING"):
            r._start_connect_attempt_(1_000_000.0)
        self.assertFalse(r.nf_connecting)
        self.assertIsNone(r._nf_diag_socket)
        self.assertIsNone(r._nf_diag_service_thread)
        self.assertEqual(r.nf_next_reconnect_ms, 1_000_500.0)
        self.assertIn("thread unavailable", r.nf_last_error)
        diag_socket.close.assert_called_once()
        r._send_udp_packet.assert_not_called()

    def test_start_cannot_duplicate_a_still_exiting_worker(self):
        r = self.receiver
        r.running = True
        thread = Mock()
        thread.is_alive.return_value = True
        r._nf_diag_service_thread = thread
        r._nf_diag_socket = None
        with patch("data_receiver.socket.socket") as factory:
            self.assertFalse(r._start_nfv3_diag_service_())
        factory.assert_not_called()
        self.assertIs(r._nf_diag_service_thread, thread)

    def test_late_worker_cleanup_cannot_clear_replacement_socket(self):
        r = self.receiver
        old, replacement = Mock(), Mock()
        r.running = True
        r._nf_diag_socket = replacement
        r._run_nfv3_diag_service_(old)
        self.assertIs(r._nf_diag_socket, replacement)
        old.close.assert_called_once()
        replacement.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()

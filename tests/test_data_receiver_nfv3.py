import struct
import sys
import types
import unittest

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

    def register_dataflow_export_variables(self, _names):
        return None

    def activate_live_dataflow_export_descriptors(self, descriptors, _host, _port):
        self.live_descriptors = list(descriptors)
        return self.activate_live

    def update_task_latency(self, task_id, latency_us):
        self.latency_updates.append((int(task_id), int(latency_us)))


class _DummyDataModel:
    def __init__(self):
        self.records = []
        self.clock_transforms = {}

    def add_data(self, src, unix_timestamp, src_timestamp, data, **kwargs):
        self.records.append((src, unix_timestamp, src_timestamp, dict(data), dict(kwargs)))

    def set_clock_transform(self, src, transform):
        if transform is None:
            self.clock_transforms.pop(src, None)
        else:
            self.clock_transforms[src] = transform


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

    def _entries(self):
        return [
            {
                "entry_kind": self.parser.SCHEMA_KIND_TASK,
                "task_id": 5,
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
            {
                "entry_kind": self.parser.SCHEMA_KIND_DATA_NODE,
                "node_no": 2,
                "node_id": 41,
                "scalar_type": self.parser.TYPE_BOOL,
                "group": "control",
                "name": "armed",
                "unit": "",
            },
        ]

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
            1,
        )
        task = struct.pack(
            self.parser.TASK_FRAME_HEADER_FMT,
            5,
            self.parser.TASK_FLAG_BUSINESS_ENABLED
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
        node = struct.pack(self.parser.NODE_FRAME_FMT, 2, 1, 10, 1)
        return self.parser.parse_packet(header + task + node)

    def test_schema_response_builds_task_port_and_node_keys(self):
        self._install_schema(generation=2, chunks=2)

        self.assertEqual(self.receiver.nf_schema_generation, 2)
        output_key = ("task", 5, self.parser.PORT_OUTPUT, 0)
        node_key = ("node", 2)
        latency_key = ("task_latency", 5)
        self.assertEqual(self.receiver.nf_schema_by_key[output_key]["var_name"], "MadgwickTask.output.yaw")
        self.assertEqual(self.receiver.nf_schema_by_key[node_key]["var_name"], "Dataflow.armed")
        self.assertEqual(self.receiver.nf_schema_by_key[node_key]["section"], "Dataflow/control")
        self.assertEqual(self.receiver.nf_schema_by_key[latency_key]["var_name"], "MadgwickTask.latency_us")
        self.assertTrue(self.receiver.nf_schema_by_key[latency_key]["hidden_control"])
        self.assertEqual(self.receiver.nf_schema_by_key[output_key]["category"], "task")
        self.assertEqual(self.receiver.nf_schema_by_key[node_key]["category"], "dataflow")
        self.assertEqual(len(self.window.live_descriptors), 4)

    def test_compact_frames_publish_default_custom_and_node_timestamps(self):
        self._install_schema()
        packet = self._build_data_packet()

        self.receiver._process_nfv3_data(packet, unix_ts=2000.0)

        records = {next(iter(record[3])): record for record in self.model.records}
        self.assertEqual(records["MadgwickTask.latency_us"][2], 999.9)
        self.assertEqual(records["MadgwickTask.latency_us"][3], {"MadgwickTask.latency_us": 50.0})
        self.assertEqual(records["MadgwickTask.input.roll"][2], 999.9)
        self.assertEqual(records["MadgwickTask.output.yaw"][2], 999.975)
        self.assertEqual(records["Dataflow.armed"][2], 999.99)
        self.assertEqual(records["MadgwickTask.output.yaw"][3], {"MadgwickTask.output.yaw": 2.0})
        self.assertEqual(records["MadgwickTask.output.yaw"][4]["offset_timestamp"], 1000.0)
        self.assertEqual(self.window.latency_updates, [(5, 50)])

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
            self.parser.TASK_FLAG_BUSINESS_ENABLED,
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


if __name__ == "__main__":
    unittest.main()

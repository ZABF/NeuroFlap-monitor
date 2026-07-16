import struct
import time
import unittest
import sys
import types

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

    def register_dataflow_export_variables(self, _names):
        return None


class _DummyDataModel:
    def __init__(self):
        self.records = []

    def add_data(self, src, unix_timestamp, src_timestamp, data, **_kwargs):
        self.records.append((src, unix_timestamp, src_timestamp, dict(data)))


class DataReceiverNFv3DecodeTest(unittest.TestCase):
    def setUp(self):
        self.model = _DummyDataModel()
        self.window = _DummyMainWindow()
        self.receiver = DataReceiver(self.model, self.window, udp_target_ip="127.0.0.1", udp_target_port=19001)
        self.parser = NFv3Parser()
        self.receiver.nf_connected = True

        self.receiver.nf_schema_order = [
            {"endpoint_no": 1, "scalar_type": self.parser.TYPE_U32, "var_name": "a"},
            {"endpoint_no": 2, "scalar_type": self.parser.TYPE_U32, "var_name": "b"},
            {"endpoint_no": 3, "scalar_type": self.parser.TYPE_U32, "var_name": "c"},
            {"endpoint_no": 4, "scalar_type": self.parser.TYPE_U32, "var_name": "d"},
        ]
        self.receiver.nf_schema_by_endpoint_no = {
            0: self.receiver.nf_schema_order[0],
            1: self.receiver.nf_schema_order[1],
            2: self.receiver.nf_schema_order[2],
            3: self.receiver.nf_schema_order[3],
        }
        self.receiver.nf_schema_generation = 1

    def _build_data_packet(self, packet_seq, endpoint_raw_pairs):
        build_us = int(time.monotonic_ns() // 1000)
        send_us = int(time.monotonic_ns() // 1000)
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            1,
            packet_seq,
            build_us,
            send_us,
            len(endpoint_raw_pairs),
        )
        items = b"".join(
            struct.pack(
                self.parser.DATA_ITEM_FMT,
                int(endpoint_no) & 0xFFFF,
                1,
                0,
                0,
                packet_seq,
                int(raw) & 0xFFFFFFFF,
            )
            for endpoint_no, raw in endpoint_raw_pairs
        )
        return self.parser.parse_packet(header + items)

    def test_multi_packet_snapshot_decode(self):
        p0 = self._build_data_packet(10, [(0, 11), (1, 22)])
        p1 = self._build_data_packet(11, [(2, 33), (3, 44)])

        self.receiver._process_nfv3_data(p1, unix_ts=1000.0)
        self.receiver._process_nfv3_data(p0, unix_ts=1000.0)

        values = {}
        for _src, _unix_ts, _src_ts, data in self.model.records:
            values.update(data)

        self.assertEqual(values.get("a"), 11.0)
        self.assertEqual(values.get("b"), 22.0)
        self.assertEqual(values.get("c"), 33.0)
        self.assertEqual(values.get("d"), 44.0)

    def test_schema_response_maps_endpoint_numbers(self):
        packet = {
            "schema_generation": 2,
            "chunk_index": 0,
            "chunk_total": 1,
            "entries": [
                {"endpoint_no": 12, "endpoint_kind": 2, "scalar_type": self.parser.TYPE_F32, "task_id": 5, "owner": "MadgwickTask", "name": "yaw", "unit": "deg"},
                {"endpoint_no": 7, "endpoint_kind": 1, "scalar_type": self.parser.TYPE_F32, "task_id": 1, "owner": "AttRlsTask", "name": "roll", "unit": "deg"},
                {"endpoint_no": 31, "endpoint_kind": 3, "scalar_type": self.parser.TYPE_BOOL, "task_id": 0, "owner": "Dataflow", "name": "armed", "unit": ""},
            ],
        }

        self.receiver.nf_schema_retry_active = True
        self.receiver._handle_nfv3_schema_response(packet)

        self.assertEqual(self.receiver.nf_schema_generation, 2)
        self.assertEqual(self.receiver.nf_schema_by_endpoint_no[12]["var_name"], "MadgwickTask.output.yaw")
        self.assertEqual(self.receiver.nf_schema_by_endpoint_no[7]["var_name"], "AttRlsTask.input.roll")
        self.assertEqual(self.receiver.nf_schema_by_endpoint_no[31]["var_name"], "Dataflow.armed")

    def test_data_with_unknown_schema_generation_is_dropped_and_requests_schema(self):
        packet = self._build_data_packet(20, [(0, 99)])
        packet["schema_generation"] = 9

        self.receiver.nf_schema_retry_active = False
        self.receiver._process_nfv3_data(packet, unix_ts=1000.0)

        self.assertEqual(len(self.model.records), 0)
        self.assertTrue(self.receiver.nf_schema_retry_active)


if __name__ == "__main__":
    unittest.main()

import struct
import time
import unittest
import sys
import types

from nfv1_parser import NFv1Parser


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

    def register_signal_export_variables(self, _names):
        return None


class _DummyDataModel:
    def __init__(self):
        self.records = []

    def add_data(self, src, unix_timestamp, src_timestamp, data):
        self.records.append((src, unix_timestamp, src_timestamp, dict(data)))


class DataReceiverNFv1DecodeTest(unittest.TestCase):
    def setUp(self):
        self.model = _DummyDataModel()
        self.window = _DummyMainWindow()
        self.receiver = DataReceiver(self.model, self.window, udp_target_ip="127.0.0.1", udp_target_port=19001)
        self.parser = NFv1Parser()
        self.receiver.nf_connected = True

        self.receiver.nf_schema_order = [
            {"gid": 1, "scalar_type": self.parser.TYPE_U32, "var_name": "a"},
            {"gid": 2, "scalar_type": self.parser.TYPE_U32, "var_name": "b"},
            {"gid": 3, "scalar_type": self.parser.TYPE_U32, "var_name": "c"},
            {"gid": 4, "scalar_type": self.parser.TYPE_U32, "var_name": "d"},
        ]
        self.receiver.nf_schema_by_signal_no = {
            0: self.receiver.nf_schema_order[0],
            1: self.receiver.nf_schema_order[1],
            2: self.receiver.nf_schema_order[2],
            3: self.receiver.nf_schema_order[3],
        }
        self.receiver.nf_schema_generation = 1

    def _build_data_packet(self, packet_seq, signal_raw_pairs):
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
            len(signal_raw_pairs),
        )
        items = b"".join(
            struct.pack(
                self.parser.DATA_ITEM_FMT,
                int(sig_no) & 0xFF,
                0,
                int(raw) & 0xFFFFFFFF,
            )
            for sig_no, raw in signal_raw_pairs
        )
        return self.parser.parse_packet(header + items)

    def test_multi_packet_snapshot_decode(self):
        p0 = self._build_data_packet(10, [(0, 11), (1, 22)])
        p1 = self._build_data_packet(11, [(2, 33), (3, 44)])

        self.receiver._process_nfv1_data(p1, unix_ts=1000.0)
        self.receiver._process_nfv1_data(p0, unix_ts=1000.0)

        values = {}
        for _src, _unix_ts, _src_ts, data in self.model.records:
            values.update(data)

        self.assertEqual(values.get("a"), 11.0)
        self.assertEqual(values.get("b"), 22.0)
        self.assertEqual(values.get("c"), 33.0)
        self.assertEqual(values.get("d"), 44.0)

    def test_schema_response_maps_signal_numbers_by_schema_order(self):
        packet = {
            "schema_generation": 2,
            "section_mask": 0x00007FFF,
            "chunk_index": 0,
            "chunk_total": 1,
            "entries": [
                {"gid": (5 << 16) | 12, "scalar_type": self.parser.TYPE_F32, "name": "yaw", "unit": "deg", "section": "IMU"},
                {"gid": (1 << 16) | 7, "scalar_type": self.parser.TYPE_F32, "name": "roll", "unit": "deg", "section": "Att"},
                {"gid": (4 << 16) | 31, "scalar_type": self.parser.TYPE_BOOL, "name": "armed", "unit": "", "section": "Control"},
            ],
        }

        self.receiver.nf_schema_retry_active = True
        self.receiver._handle_nfv1_schema_response(packet)

        self.assertEqual(self.receiver.nf_schema_generation, 2)
        self.assertEqual(self.receiver.nf_schema_section_mask, 0x00007FFF)
        self.assertEqual(self.receiver.nf_schema_by_signal_no[0]["gid"], (5 << 16) | 12)
        self.assertEqual(self.receiver.nf_schema_by_signal_no[1]["gid"], (1 << 16) | 7)
        self.assertEqual(self.receiver.nf_schema_by_signal_no[2]["gid"], (4 << 16) | 31)

    def test_data_with_unknown_schema_generation_is_dropped_and_requests_schema(self):
        packet = self._build_data_packet(20, [(0, 99)])
        packet["schema_generation"] = 9

        self.receiver.nf_schema_retry_active = False
        self.receiver._process_nfv1_data(packet, unix_ts=1000.0)

        self.assertEqual(len(self.model.records), 0)
        self.assertTrue(self.receiver.nf_schema_retry_active)


if __name__ == "__main__":
    unittest.main()

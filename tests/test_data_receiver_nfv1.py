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

        self.receiver.nf_schema_order = [
            {"gid": 1, "scalar_type": self.parser.TYPE_U32, "var_name": "a"},
            {"gid": 2, "scalar_type": self.parser.TYPE_U32, "var_name": "b"},
            {"gid": 3, "scalar_type": self.parser.TYPE_U32, "var_name": "c"},
            {"gid": 4, "scalar_type": self.parser.TYPE_U32, "var_name": "d"},
        ]
        self.receiver.nf_schema_by_signal_no = {
            1: self.receiver.nf_schema_order[0],
            2: self.receiver.nf_schema_order[1],
            3: self.receiver.nf_schema_order[2],
            4: self.receiver.nf_schema_order[3],
        }

    def _build_data_packet(self, packet_seq, signal_raw_pairs):
        build_us = int(time.monotonic_ns() // 1000)
        send_us = int(time.monotonic_ns() // 1000)
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
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
        p0 = self._build_data_packet(10, [(1, 11), (2, 22)])
        p1 = self._build_data_packet(11, [(3, 33), (4, 44)])

        self.receiver._process_nfv1_data(p1, unix_ts=1000.0)
        self.receiver._process_nfv1_data(p0, unix_ts=1000.0)

        values = {}
        for _src, _unix_ts, _src_ts, data in self.model.records:
            values.update(data)

        self.assertEqual(values.get("a"), 11.0)
        self.assertEqual(values.get("b"), 22.0)
        self.assertEqual(values.get("c"), 33.0)
        self.assertEqual(values.get("d"), 44.0)


if __name__ == "__main__":
    unittest.main()

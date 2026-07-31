import struct
import unittest
from types import SimpleNamespace

from nfv3_parser import NFv3Parser


def schema_entry(kind, payload):
    return struct.pack("<BH", kind, len(payload)) + payload


def task_entry(parser, task_id=5, input_count=2, output_count=1, input_groups=1, output_groups=1):
    name = b"MadgwickTask"
    payload = struct.pack(
        "<HBBBBB",
        task_id,
        input_count,
        output_count,
        input_groups,
        output_groups,
        len(name),
    ) + name
    return schema_entry(parser.SCHEMA_KIND_TASK, payload)


def port_entry(parser, direction, slot, scalar_type, timestamp_group, name, unit=b""):
    name = name.encode() if isinstance(name, str) else name
    payload = struct.pack(
        "<HBBBBBB",
        5,
        direction,
        slot,
        scalar_type,
        timestamp_group,
        len(name),
        len(unit),
    ) + name + unit
    return schema_entry(parser.SCHEMA_KIND_TASK_PORT, payload)


def node_entry(parser):
    group = b"control"
    name = b"mix"
    unit = b"deg"
    payload = struct.pack(
        "<HHBBBB",
        2,
        41,
        parser.TYPE_F32,
        len(group),
        len(name),
        len(unit),
    ) + group + name + unit
    return schema_entry(parser.SCHEMA_KIND_DATA_NODE, payload)


class NFv3ParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = NFv3Parser()

    def _schema_packet(self):
        entries = [
            task_entry(self.parser),
            port_entry(
                self.parser,
                self.parser.PORT_INPUT,
                0,
                self.parser.TYPE_F32,
                self.parser.DEFAULT_TIMESTAMP_GROUP,
                "roll",
                b"deg",
            ),
            port_entry(
                self.parser,
                self.parser.PORT_INPUT,
                1,
                self.parser.TYPE_U16,
                0,
                "speed",
            ),
            port_entry(
                self.parser,
                self.parser.PORT_OUTPUT,
                0,
                self.parser.TYPE_F32,
                0,
                "angle",
                b"deg",
            ),
            node_entry(self.parser),
        ]
        header = struct.pack(
            self.parser.SCHEMA_RESP_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_SCHEMA_RESP,
            7,
            0,
            1,
            len(entries),
            len(entries),
        )
        return self.parser.parse_packet(header + b"".join(entries))

    def test_parse_and_install_schema(self):
        packet = self._schema_packet()

        self.assertIsNotNone(packet)
        self.assertEqual(packet["schema_generation"], 7)
        self.assertEqual(packet["total_entries"], 5)
        self.assertTrue(self.parser.install_schema(7, packet["entries"]))
        task = self.parser.schema_tasks[5]
        self.assertEqual(task["name"], "MadgwickTask")
        self.assertEqual([item["name"] for item in task["inputs"]], ["roll", "speed"])
        self.assertEqual(task["outputs"][0]["unit"], "deg")
        self.assertEqual(self.parser.schema_nodes[2]["name"], "mix")

    def test_parse_compact_task_and_node_frames(self):
        schema = self._schema_packet()
        self.assertTrue(self.parser.install_schema(7, schema["entries"]))
        packet_time_us = 1_000_000
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            7,
            12,
            packet_time_us,
            1,
            1,
        )
        task_frame = struct.pack(
            self.parser.TASK_FRAME_HEADER_FMT,
            5,
            self.parser.TASK_FLAG_BUSINESS_ENABLED
            | self.parser.TASK_FLAG_INPUTS_VALID
            | self.parser.TASK_FLAG_OUTPUTS_VALID,
            100,
            50,
        )
        task_frame += struct.pack("<III", 0x3F800000, 1200, 0x40000000)
        task_frame += struct.pack("<II", 80, 30)
        node_frame = struct.pack(self.parser.NODE_FRAME_FMT, 2, 1, 25, 0x40400000)

        packet = self.parser.parse_packet(header + task_frame + node_frame)

        self.assertTrue(packet["schema_available"])
        self.assertEqual(packet["packet_time_us"], packet_time_us)
        self.assertEqual(len(packet["task_frames"]), 1)
        frame = packet["task_frames"][0]
        self.assertEqual(frame["inputs"][0]["capture_age_us"], 100)
        self.assertEqual(frame["inputs"][1]["capture_age_us"], 80)
        self.assertEqual(frame["outputs"][0]["capture_age_us"], 30)
        self.assertEqual(self.parser.raw_to_value(frame["outputs"][0]["scalar_type"], frame["outputs"][0]["raw"]), 2.0)
        self.assertEqual(packet["node_frames"][0]["publish_age_us"], 25)

    def test_unknown_generation_returns_header_for_schema_resync(self):
        schema = self._schema_packet()
        self.assertTrue(self.parser.install_schema(7, schema["entries"]))
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            8,
            1,
            1000,
            1,
            0,
        )

        packet = self.parser.parse_packet(header)

        self.assertIsNotNone(packet)
        self.assertFalse(packet["schema_available"])
        self.assertEqual(packet["task_frames"], [])

    def test_zero_io_task_schema_is_valid(self):
        raw = task_entry(self.parser, task_id=9, input_count=0, output_count=0, input_groups=0, output_groups=0)
        header = struct.pack(
            self.parser.SCHEMA_RESP_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_SCHEMA_RESP,
            0xFF,
            0,
            1,
            1,
            1,
        )
        packet = self.parser.parse_packet(header + raw)
        self.assertTrue(self.parser.install_schema(3, packet["entries"]))
        self.assertEqual(self.parser.schema_tasks[9]["inputs"], [])

    def test_parse_network_diagnostic_probe(self):
        packet_size = 1200
        header = struct.pack(
            self.parser.DIAG_PROBE_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_PROBE,
            42,
            2,
            self.parser.DIAG_PROBE_STAGE_END,
            packet_size,
            99,
            123456,
            500,
            0,
        )

        packet = self.parser.parse_packet(header + bytes(packet_size - len(header)))

        self.assertEqual(packet["type"], "diag_probe")
        self.assertEqual(packet["test_id"], 42)
        self.assertEqual(packet["stage"], 2)
        self.assertEqual(packet["probe_seq"], 99)
        self.assertEqual(packet["target_pps"], 500)

    def test_build_network_diagnostic_feedback(self):
        packet = self.parser.build_diag_feedback(
            test_id=7,
            stage=1,
            flags=self.parser.DIAG_FEEDBACK_STAGE_COMPLETE,
            normal_packets_rx=100,
            normal_packet_gaps=2,
            probe_packets_rx=200,
            probe_packet_gaps=3,
            last_probe_seq=88,
            max_probe_gap=4,
            receiver_errors=5,
        )

        self.assertEqual(len(packet), self.parser.DIAG_FEEDBACK_SIZE)
        values = struct.unpack(self.parser.DIAG_FEEDBACK_FMT, packet)
        self.assertEqual(values[2], self.parser.TYPE_DIAG_FEEDBACK)
        self.assertEqual(values[3], 7)
        self.assertEqual(values[7:12], (100, 2, 200, 3, 88))
        self.assertEqual(values[12:14], (4, 5))
        parsed = self.parser.parse_packet(packet)
        self.assertEqual(parsed["max_probe_gap"], 4)
        self.assertEqual(parsed["receiver_errors"], 5)

    def test_network_diagnostic_capability_echo_and_control_layouts(self):
        capabilities = self.parser.build_diag_capabilities(
            self.parser.DIAG_CAPABILITY_ALL,
            1200,
            256,
            0x12345678,
        )
        self.assertEqual(len(capabilities), 16)
        parsed_capabilities = self.parser.parse_packet(capabilities)
        self.assertEqual(parsed_capabilities["features"], self.parser.DIAG_CAPABILITY_ALL)
        self.assertEqual(parsed_capabilities["max_udp_payload"], 1200)

        echo_request = struct.pack(
            self.parser.DIAG_ECHO_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_ECHO_REQUEST,
            9,
            17,
            123456789,
            123456800,
            123456810,
            0xFF,
        )
        self.assertEqual(len(echo_request), 40)
        parsed_echo = self.parser.parse_packet(echo_request)
        self.assertEqual(parsed_echo["type"], "diag_echo_request")
        self.assertEqual(parsed_echo["flags"], 0xFF)
        echo_response = self.parser.build_diag_echo_response(
            parsed_echo["test_id"],
            parsed_echo["sequence"],
            parsed_echo["t1_us"],
            parsed_echo["t2_us"],
            parsed_echo["t3_us"],
            parsed_echo["flags"],
        )
        parsed_response = self.parser.parse_packet(echo_response)
        self.assertEqual(parsed_response["type"], "diag_echo_response")
        self.assertEqual(parsed_response["flags"], 0xFF)

        control = struct.pack(
            self.parser.DIAG_CONTROL_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_CONTROL,
            9,
            self.parser.DIAG_CONTROL_UDP_UPLOAD_START,
            self.parser.DIAG_MODE_UDP_CAPACITY,
            4,
            0,
            500,
            1200,
            3000,
            28081,
            0,
        )
        self.assertEqual(len(control), 24)
        parsed_control = self.parser.parse_packet(control)
        self.assertEqual(parsed_control["target_pps"], 500)
        self.assertEqual(parsed_control["tcp_port"], 28081)

    def test_network_diagnostic_tcp_frame_layout(self):
        frame = self.parser.build_diag_tcp_frame(
            11,
            self.parser.DIAG_TCP_PING,
            3,
            99,
            987654321,
            987654400,
            987654500,
        )
        self.assertEqual(len(frame), 1200)
        parsed = self.parser.parse_diag_tcp_frame(frame)
        self.assertEqual(
            parsed,
            {
                "test_id": 11,
                "kind": self.parser.DIAG_TCP_PING,
                "stage": 3,
                "sequence": 99,
                "t1_us": 987654321,
                "t2_us": 987654400,
                "t3_us": 987654500,
            },
        )

    def test_network_diagnostic_clock_sample_and_model_layouts(self):
        sample = struct.pack(
            self.parser.DIAG_CLOCK_SAMPLE_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DIAG_CLOCK_SAMPLE,
            0,
            19,
            1_000_000,
            2_001_100,
            2_001_140,
            1_002_100,
            0xFF,
        )
        parsed = self.parser.parse_packet(sample)
        self.assertEqual(parsed["type"], "diag_clock_sample")
        self.assertEqual(parsed["sequence"], 19)
        self.assertEqual(parsed["t4_us"], 1_002_100)

        transform = SimpleNamespace(
            revision=7,
            source_anchor_us=1_000_000,
            target_anchor_us=2_000_000,
            drift_ppb=80_000,
            uncertainty_us=450,
            locked=True,
        )
        stats = {
            "upload": {"samples": 10, "latest": 800, "min": 700, "p50": 810, "p95": 950},
            "download": {"samples": 10, "latest": 900, "min": 750, "p50": 920, "p95": 1100},
            "rtt": {"samples": 10, "latest": 1700, "min": 1500, "p50": 1730, "p95": 2000},
        }
        model = self.parser.build_diag_clock_model(transform, stats)
        self.assertEqual(len(model), self.parser.DIAG_CLOCK_MODEL_SIZE)
        fields = struct.unpack(self.parser.DIAG_CLOCK_MODEL_FMT, model)
        self.assertEqual(fields[2], self.parser.TYPE_DIAG_CLOCK_MODEL)
        self.assertEqual(fields[3:9], (7, 1_000_000, 2_000_000, 80_000, 450, 1))
        self.assertEqual(fields[9:14], (10, 800, 700, 810, 950))


if __name__ == "__main__":
    unittest.main()

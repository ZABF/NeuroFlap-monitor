import struct
import unittest

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
            3,
            0,
            1,
            1,
            1,
        )
        packet = self.parser.parse_packet(header + raw)
        self.assertTrue(self.parser.install_schema(3, packet["entries"]))
        self.assertEqual(self.parser.schema_tasks[9]["inputs"], [])


if __name__ == "__main__":
    unittest.main()

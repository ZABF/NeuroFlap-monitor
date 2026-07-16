import struct
import unittest

from nfv3_parser import NFv3Parser


class NFv3ParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = NFv3Parser()

    def test_parse_data_packet(self):
        header = struct.pack(
            self.parser.DATA_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_DATA,
            3,
            7,
            123450000,
            123456789,
            2,
        )
        items = b"".join(
            [
                struct.pack(self.parser.DATA_ITEM_FMT, 4, 1, 123, 45, 9, 0x3F800000),
                struct.pack(self.parser.DATA_ITEM_FMT, 5, 2, 456, 78, 10, 123),
            ]
        )

        packet = self.parser.parse_packet(header + items)
        self.assertIsNotNone(packet)
        self.assertEqual(packet["type"], "data")
        self.assertEqual(packet["schema_generation"], 3)
        self.assertEqual(packet["packet_seq"], 7)
        self.assertEqual(packet["build_us"], 123450000)
        self.assertEqual(packet["send_us"], 123456789)
        self.assertEqual(packet["item_count"], 2)
        self.assertEqual(len(packet["items"]), 2)
        self.assertEqual(packet["items"][0]["endpoint_no"], 4)
        self.assertEqual(packet["items"][0]["status"], 1)
        self.assertEqual(packet["items"][0]["publish_age_us"], 123)
        self.assertEqual(packet["items"][0]["capture_age_us"], 45)
        self.assertEqual(packet["items"][0]["endpoint_seq"], 9)
        self.assertEqual(packet["items"][0]["raw"], 0x3F800000)
        self.assertEqual(self.parser.raw_to_value(self.parser.TYPE_F32, 0x3F800000), 1.0)

    def test_parse_schema_response_packet(self):
        entries = []
        for endpoint_no, kind, scalar_type, task_id, owner, name, unit in (
            (2, 1, self.parser.TYPE_F32, 10, b"MadgwickTask", b"pitch", b"deg"),
            (3, 3, self.parser.TYPE_F32, 0, b"Dataflow", b"clipped", b"deg"),
        ):
            entries.append(
                struct.pack(
                    self.parser.SCHEMA_ENTRY_PREFIX_FMT,
                    endpoint_no,
                    kind,
                    scalar_type,
                    task_id,
                    len(owner),
                    len(name),
                    len(unit),
                )
                + owner
                + name
                + unit
            )

        header = struct.pack(
            self.parser.SCHEMA_RESP_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_SCHEMA_RESP,
            5,
            0,
            1,
            len(entries),
        )

        packet = self.parser.parse_packet(header + b"".join(entries))
        self.assertIsNotNone(packet)
        self.assertEqual(packet["type"], "schema_resp")
        self.assertEqual(packet["schema_generation"], 5)
        self.assertEqual(packet["chunk_total"], 1)
        self.assertEqual(len(packet["entries"]), 2)
        self.assertEqual(packet["entries"][0]["endpoint_no"], 2)
        self.assertEqual(packet["entries"][0]["endpoint_kind"], 1)
        self.assertEqual(packet["entries"][0]["owner"], "MadgwickTask")
        self.assertEqual(packet["entries"][0]["name"], "pitch")
        self.assertEqual(packet["entries"][0]["unit"], "deg")


if __name__ == "__main__":
    unittest.main()

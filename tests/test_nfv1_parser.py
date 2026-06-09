import struct
import unittest

from nfv1_parser import NFv1Parser


class NFv1ParserTest(unittest.TestCase):
    def setUp(self):
        self.parser = NFv1Parser()

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
                struct.pack(self.parser.DATA_ITEM_FMT, 4, 123, 0x3F800000),
                struct.pack(self.parser.DATA_ITEM_FMT, 5, 456, 123),
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
        self.assertEqual(packet["items"][0]["signal_no"], 4)
        self.assertEqual(packet["items"][0]["dt_us"], 123)
        self.assertEqual(packet["items"][0]["raw"], 0x3F800000)
        self.assertEqual(self.parser.raw_to_value(self.parser.TYPE_F32, 0x3F800000), 1.0)

    def test_parse_schema_response_packet(self):
        entries = []
        for gid, scalar_type, name, unit in (
            (0x00010002, self.parser.TYPE_F32, b"pitch", b"deg"),
            (0x00010003, self.parser.TYPE_U16, b"servo", b"us"),
        ):
            entries.append(
                struct.pack(
                    "<IBBBB",
                    gid,
                    scalar_type,
                    len(name),
                    len(unit),
                    0,
                )
                + name
                + unit
            )

        header = struct.pack(
            self.parser.SCHEMA_RESP_HEADER_FMT,
            self.parser.MAGIC,
            self.parser.VERSION,
            self.parser.TYPE_SCHEMA_RESP,
            5,
            0x00007FFF,
            0,
            1,
            len(entries),
        )

        packet = self.parser.parse_packet(header + b"".join(entries))
        self.assertIsNotNone(packet)
        self.assertEqual(packet["type"], "schema_resp")
        self.assertEqual(packet["schema_generation"], 5)
        self.assertEqual(packet["section_mask"], 0x00007FFF)
        self.assertEqual(packet["chunk_total"], 1)
        self.assertEqual(len(packet["entries"]), 2)
        self.assertEqual(packet["entries"][0]["gid"], 0x00010002)
        self.assertEqual(packet["entries"][0]["name"], "pitch")
        self.assertEqual(packet["entries"][0]["unit"], "deg")


if __name__ == "__main__":
    unittest.main()

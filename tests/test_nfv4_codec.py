import struct
import unittest

from network_clock import ClockTransform
from nfv4_codec import NFv4Codec


class NFv4CodecTest(unittest.TestCase):
    def setUp(self):
        self.codec = NFv4Codec()

    def test_session_open_layout(self):
        packet = self.codec.build_session_open(
            0x12345678,
            self.codec.FEATURE_CLOCK_SYNC | self.codec.FEATURE_DIAGNOSTICS,
            max_udp_payload=1180,
            preferred_tcp_frame=1024,
        )

        self.assertEqual(len(packet), self.codec.SESSION_OPEN_SIZE)
        self.assertEqual(
            struct.unpack(self.codec.SESSION_OPEN_FMT, packet),
            (
                self.codec.MAGIC,
                self.codec.VERSION,
                self.codec.TYPE_SESSION_OPEN,
                0x12345678,
                3,
                1180,
                1024,
            ),
        )

    def test_session_accept_layout(self):
        packet = struct.pack(
            self.codec.SESSION_ACCEPT_FMT,
            self.codec.MAGIC,
            self.codec.VERSION,
            self.codec.TYPE_SESSION_ACCEPT,
            0x10203040,
            0x50607080,
            self.codec.FEATURE_CLOCK_SYNC,
            28081,
            28082,
            6000,
        )

        parsed = self.codec.parse_base_packet(packet)
        self.assertEqual(parsed["type"], "session_accept")
        self.assertEqual(parsed["client_nonce"], 0x10203040)
        self.assertEqual(parsed["session_id"], 0x50607080)
        self.assertEqual(parsed["aux_port"], 28081)
        self.assertEqual(parsed["tcp_port"], 28082)
        self.assertEqual(parsed["timeout_ms"], 6000)

    def test_sync_response_layout(self):
        packet = struct.pack(
            self.codec.SYNC_RESPONSE_FMT,
            self.codec.MAGIC,
            self.codec.VERSION,
            self.codec.TYPE_SYNC_RESPONSE,
            7,
            11,
            1_000_100,
            1_000_140,
            9,
            2,
            1,
            0,
        )

        parsed = self.codec.parse_sync_response(packet)
        self.assertEqual(parsed["session_id"], 7)
        self.assertEqual(parsed["sequence"], 11)
        self.assertEqual(parsed["t2_us"], 1_000_100)
        self.assertEqual(parsed["t3_us"], 1_000_140)
        self.assertEqual(parsed["context"], 9)
        self.assertEqual(parsed["stage"], 2)

    def test_rejects_wrong_wire_version(self):
        packet = bytearray(
            self.codec.build_session_open(
                1,
                self.codec.FEATURE_CLOCK_SYNC,
            )
        )
        packet[2] = 3
        self.assertIsNone(self.codec.peek_header(packet))

    def test_diag_command_layout(self):
        packet = struct.pack(
            self.codec.DIAG_COMMAND_FMT,
            self.codec.MAGIC,
            self.codec.VERSION,
            self.codec.TYPE_DIAG_COMMAND,
            0x11223344,
            17,
            self.codec.DIAG_CONTROL_UDP_UPLOAD_START,
            2,
            3,
            0,
            500,
            1200,
            3000,
            28082,
            0,
        )

        parsed = self.codec.parse_aux_packet(packet)
        self.assertEqual(parsed["session_id"], 0x11223344)
        self.assertEqual(parsed["test_id"], 17)
        self.assertEqual(
            parsed["action"],
            self.codec.DIAG_CONTROL_UDP_UPLOAD_START,
        )
        self.assertEqual(parsed["stage"], 3)
        self.assertEqual(parsed["target_pps"], 500)
        self.assertEqual(parsed["payload_bytes"], 1200)
        self.assertEqual(parsed["duration_ms"], 3000)
        self.assertEqual(parsed["tcp_port"], 28082)

    def test_diag_probe_round_trip(self):
        packet = self.codec.build_diag_probe(
            0x11223344,
            19,
            4,
            self.codec.DIAG_PROBE_MONITOR_TO_FIRMWARE
            | self.codec.DIAG_PROBE_STAGE_START,
            256,
            23,
            1_234_567,
            750,
        )

        parsed = self.codec.parse_aux_packet(packet)
        self.assertEqual(len(packet), 256)
        self.assertEqual(parsed["session_id"], 0x11223344)
        self.assertEqual(parsed["test_id"], 19)
        self.assertEqual(parsed["stage"], 4)
        self.assertEqual(parsed["packet_size"], 256)
        self.assertEqual(parsed["probe_seq"], 23)
        self.assertEqual(parsed["sender_us"], 1_234_567)
        self.assertEqual(parsed["target_pps"], 750)

    def test_diag_reports_match_fixed_wire_sizes(self):
        capabilities = self.codec.build_diag_capabilities_report(
            7,
            self.codec.DIAG_CAPABILITY_ALL,
            1200,
            1200,
            0x55667788,
        )
        feedback = self.codec.build_diag_feedback_report(
            7,
            22,
            3,
            self.codec.DIAG_FEEDBACK_STAGE_COMPLETE,
            100,
            2,
            90,
            3,
            95,
            2,
            0,
        )
        path = self.codec.build_diag_path_report(
            7,
            ClockTransform(
                source_anchor_us=1_000_000,
                target_anchor_us=2_000_000,
                drift_ppb=125,
                uncertainty_us=80,
                usable=True,
                locked=True,
            ),
            {
                "upload": {
                    "samples": 4,
                    "latest": 700,
                    "min": 500,
                    "p50": 600,
                    "p95": 750,
                },
                "download": {
                    "samples": 4,
                    "latest": 800,
                    "min": 600,
                    "p50": 700,
                    "p95": 850,
                },
                "rtt": {
                    "samples": 4,
                    "latest": 1500,
                    "min": 1100,
                    "p50": 1300,
                    "p95": 1600,
                },
            },
        )

        self.assertEqual(
            len(capabilities), self.codec.DIAG_CAPABILITIES_REPORT_SIZE
        )
        self.assertEqual(
            len(feedback), self.codec.DIAG_FEEDBACK_REPORT_SIZE
        )
        self.assertEqual(len(path), self.codec.DIAG_PATH_REPORT_SIZE)
        self.assertEqual(struct.unpack_from("<H", capabilities, 10)[0], 24)
        self.assertEqual(struct.unpack_from("<H", feedback, 10)[0], 48)
        self.assertEqual(struct.unpack_from("<H", path, 10)[0], 104)


if __name__ == "__main__":
    unittest.main()

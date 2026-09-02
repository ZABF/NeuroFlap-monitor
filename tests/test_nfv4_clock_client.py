import struct
import unittest

from network_clock import (
    ClockAlignmentState,
    ClockEstimatorStrategy,
    SelectableClockEstimator,
)
from nfv4_clock_client import NFv4ClockClient
from nfv4_codec import NFv4Codec


class NFv4ClockClientTest(unittest.TestCase):
    def setUp(self):
        self.codec = NFv4Codec()
        self.client = NFv4ClockClient(codec=self.codec)
        self.client.start_session(0x11223344)

    def response(self, request, *, t2_us, t3_us):
        (
            _magic,
            _version,
            _type,
            session_id,
            sequence,
            context,
            stage,
            flags,
            _reserved,
        ) = struct.unpack(self.codec.SYNC_REQUEST_FMT, request)
        return struct.pack(
            self.codec.SYNC_RESPONSE_FMT,
            self.codec.MAGIC,
            self.codec.VERSION,
            self.codec.TYPE_SYNC_RESPONSE,
            session_id,
            sequence,
            t2_us,
            t3_us,
            context,
            stage,
            flags,
            0,
        )

    def test_four_monitor_initiated_samples_make_clock_provisional(self):
        target_start_us = 2_000_000
        source_offset_us = 500_000
        for index in range(4):
            target_t1_us = target_start_us + index * 100_000
            sent = []

            def send_packet(packet, t1_us=target_t1_us):
                sent.append(packet)
                return t1_us

            self.assertTrue(
                self.client.tick(
                    send_packet,
                    now_us=target_t1_us,
                )
            )
            response = self.response(
                sent[0],
                t2_us=target_t1_us - source_offset_us + 700,
                t3_us=target_t1_us - source_offset_us + 740,
            )
            self.assertTrue(
                self.client.handle_response(
                    response,
                    t4_us=target_t1_us + 1_600,
                )
            )

        snapshot = self.client.estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.PROVISIONAL)
        self.assertTrue(snapshot.usable)
        self.assertFalse(self.client.estimator.transform.locked)

    def test_loaded_probe_response_does_not_update_clock_model(self):
        sent = []
        self.client.tick(
            lambda packet: sent.append(packet) or 2_000_000,
            now_us=2_000_000,
            context=12,
            stage=3,
        )
        response = self.response(
            sent[0],
            t2_us=1_500_700,
            t3_us=1_500_740,
        )

        self.assertTrue(
            self.client.handle_response(response, t4_us=2_001_600)
        )
        self.assertEqual(self.client.estimator.snapshot().sample_count, 0)
        self.assertEqual(self.client.last_response_us, 2_001_600)

    def test_loaded_scheduler_does_not_delay_baseline_scheduler(self):
        loaded = []
        baseline = []
        self.assertTrue(
            self.client.tick(
                lambda packet: loaded.append(packet) or 2_000_000,
                now_us=2_000_000,
                context=12,
                stage=3,
            )
        )
        self.assertTrue(
            self.client.tick(
                lambda packet: baseline.append(packet) or 2_000_001,
                now_us=2_000_001,
                context=0,
            )
        )
        self.assertEqual(len(loaded), 1)
        self.assertEqual(len(baseline), 1)

    def test_baseline_interval_is_fixed_at_ten_hz(self):
        sent = []
        self.assertTrue(
            self.client.tick(
                lambda packet: sent.append(packet) or 2_000_000,
                now_us=2_000_000,
            )
        )
        self.assertFalse(
            self.client.tick(
                lambda packet: sent.append(packet) or 2_050_000,
                now_us=2_050_000,
            )
        )
        self.assertTrue(
            self.client.tick(
                lambda packet: sent.append(packet) or 2_100_000,
                now_us=2_100_000,
            )
        )
        self.assertEqual(len(sent), 2)

    def test_expired_request_rejects_late_response_without_liveness(self):
        sent = []
        self.client.tick(
            lambda packet: sent.append(packet) or 2_000_000,
            now_us=2_000_000,
        )
        response = self.response(
            sent[0],
            t2_us=1_500_700,
            t3_us=1_500_740,
        )

        self.assertFalse(
            self.client.handle_response(
                response,
                t4_us=2_000_000 + self.client.RESPONSE_TIMEOUT_US + 1,
            )
        )
        diagnostics = self.client.diagnostics(
            now_us=2_000_000 + self.client.RESPONSE_TIMEOUT_US + 1
        )
        self.assertEqual(diagnostics["requests_expired"], 1)
        self.assertEqual(diagnostics["responses_matched"], 0)
        self.assertIsNone(diagnostics["last_response_age_ms"])

    def test_rejects_response_for_unknown_sequence(self):
        request = self.codec.build_sync_request(
            0x11223344,
            99,
        )
        response = self.response(
            request,
            t2_us=1_500_700,
            t3_us=1_500_740,
        )
        self.assertFalse(
            self.client.handle_response(response, t4_us=2_001_600)
        )

    def test_matching_response_proves_liveness_when_estimator_rejects_sample(self):
        sent = []
        self.client.tick(
            lambda packet: sent.append(packet) or 2_000_000,
            now_us=2_000_000,
        )
        response = self.response(
            sent[0],
            t2_us=1_500_740,
            t3_us=1_500_700,
        )

        self.assertTrue(
            self.client.handle_response(response, t4_us=2_001_600)
        )
        measurement = self.client.take_measurement()
        self.assertIsNotNone(measurement)
        self.assertFalse(measurement["accepted"])
        self.assertEqual(self.client.last_response_us, 2_001_600)

        diagnostics = self.client.diagnostics(now_us=2_001_600)
        self.assertEqual(diagnostics["requests_sent"], 1)
        self.assertEqual(diagnostics["responses_seen"], 1)
        self.assertEqual(diagnostics["responses_matched"], 1)
        self.assertEqual(diagnostics["samples_accepted"], 0)
        self.assertEqual(diagnostics["samples_rejected"], 1)
        self.assertEqual(diagnostics["outstanding"], 0)

    def test_diagnostics_distinguish_send_failure_from_no_response(self):
        self.assertFalse(
            self.client.tick(
                lambda _packet: 0,
                now_us=2_000_000,
            )
        )
        diagnostics = self.client.diagnostics(now_us=2_010_000)
        self.assertEqual(diagnostics["requests_due"], 1)
        self.assertEqual(diagnostics["requests_sent"], 0)
        self.assertEqual(diagnostics["request_send_failures"], 1)
        self.assertEqual(diagnostics["last_failure"], "sync request send failed")

        self.client.start_session(0x11223344)
        self.assertTrue(
            self.client.tick(
                lambda _packet: 3_000_000,
                now_us=3_000_000,
            )
        )
        diagnostics = self.client.diagnostics(now_us=3_025_000)
        self.assertEqual(diagnostics["requests_sent"], 1)
        self.assertEqual(diagnostics["responses_matched"], 0)
        self.assertEqual(diagnostics["outstanding"], 1)
        self.assertEqual(diagnostics["last_send_age_ms"], 25.0)

    def test_selectable_estimator_reconnect_keeps_physical_epoch(self):
        estimator = SelectableClockEstimator(
            ClockEstimatorStrategy.V4_V3, background_drift=False
        )
        client = NFv4ClockClient(estimator=estimator, codec=self.codec)
        epoch = estimator.epoch

        client.start_session(7)
        client.stop_session()

        self.assertEqual(estimator.epoch, epoch)


if __name__ == "__main__":
    unittest.main()

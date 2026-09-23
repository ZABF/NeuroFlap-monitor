import unittest

from clock_alignment import (
    AlignmentMode,
    ClockObservationStore,
    FtObservation,
    NeuroFlapObservation,
    OffsetOnlyClockEstimator,
    RealtimeOffsetTracker,
    fit_ft,
    fit_neuroflap,
)


class ClockAlignmentTest(unittest.TestCase):
    def test_neuroflap_batch_fit_recovers_affine_clock(self):
        scale = 1.0 + 80.0e-6
        offset_us = 500_000.0
        observations = []
        for index in range(200):
            t1 = 10_000_000 + index * 1_000_000
            downlink = 1_000 + (index % 7) * 30
            uplink = 1_200 + (index % 5) * 40
            t2 = int((t1 + downlink - offset_us) / scale)
            t3 = t2 + 100
            t4 = int(t3 * scale + offset_us + uplink)
            observations.append(
                NeuroFlapObservation(3, index, t1, t2, t3, t4)
            )

        model = fit_neuroflap(3, observations)

        self.assertEqual(model.mode, AlignmentMode.CALIBRATED)
        self.assertAlmostEqual(model.transform.drift_ppb / 1000.0, 80.0, delta=1.0)
        self.assertEqual(model.quality.rating, "Good")
        self.assertEqual(model.quality.sample_count, 200)

    def test_ft_batch_fit_uses_low_delay_envelope(self):
        scale = 1.0 - 45.0e-6
        offset_us = 700_000.0
        observations = []
        for index in range(180):
            source_us = 1_000_000 + index * 1_000_000
            queue_delay = 800 + (index % 9) * 120
            receive_us = int(source_us * scale + offset_us + queue_delay)
            observations.append(FtObservation(2, source_us, receive_us))

        model = fit_ft(2, observations)

        self.assertAlmostEqual(model.transform.drift_ppb / 1000.0, -45.0, delta=1.0)
        self.assertEqual(model.quality.representative_count, 180)
        self.assertEqual(model.quality.rating, "Good")

    def test_observation_store_keeps_sessions_separate(self):
        store = ClockObservationStore()
        store.add_neuroflap(1, 1, 10, 20, 30, 40)
        store.add_neuroflap(2, 2, 50, 60, 70, 80)
        store.add_ft(1, 100, 200)
        store.add_ft(2, 300, 400)

        self.assertEqual(len(store.neuroflap_snapshot(1)), 1)
        self.assertEqual(store.neuroflap_snapshot(2)[0].sequence, 2)
        self.assertEqual(store.ft_snapshot(1)[0].source_us, 100)
        self.assertEqual(store.ft_snapshot(2)[0].receive_us, 400)

    def test_realtime_tracker_is_offset_only_and_rate_limited(self):
        tracker = RealtimeOffsetTracker()
        first = tracker.add(1_000, 2_100, 100, 4, now_us=1_000_000)
        skipped = tracker.add(2_000, 3_080, 80, 4, now_us=1_500_000)
        updated = tracker.add(3_000, 4_070, 70, 4, now_us=2_000_000)

        self.assertIsNotNone(first)
        self.assertIsNone(skipped)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.drift_ppb, 0.0)
        self.assertEqual(updated.source_anchor_us, 3_000.0)
        self.assertEqual(updated.target_anchor_us, 4_070.0)

    def test_offset_only_estimator_never_runs_a_drift_fit(self):
        estimator = OffsetOnlyClockEstimator()

        self.assertTrue(
            estimator.add_monitor_initiated(1_000_000, 900_000, 900_100, 1_000_300)
        )

        self.assertTrue(estimator.transform.usable)
        self.assertEqual(estimator.transform.drift_ppb, 0.0)
        self.assertEqual(estimator.snapshot().model_name, "rolling_min_rtt_offset_v1")
        self.assertEqual(estimator.path_stats()["rtt"]["samples"], 1)


if __name__ == "__main__":
    unittest.main()

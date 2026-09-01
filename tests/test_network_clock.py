import random
import unittest
from unittest.mock import patch

from network_clock import (
    AffineClockEstimator,
    ClockAlignmentState,
)


class AffineClockEstimatorTest(unittest.TestCase):
    @staticmethod
    def add_series(
        estimator,
        count,
        *,
        start_us=1_000_000,
        period_us=50_000,
        offset_us=2_000_000.0,
        drift_ppb=80_000.0,
    ):
        scale = 1.0 + drift_ppb * 1.0e-9
        for index in range(count):
            source_us = start_us + index * period_us
            upload_us = 700 + (index % 5) * 80
            download_us = 850 + (index % 7) * 70
            t1_us = source_us
            t2_us = int(offset_us + (t1_us + upload_us) * scale)
            t3_us = t2_us + 40
            t4_us = int((t3_us - offset_us) / scale + download_us)
            if not estimator.add(t1_us, t2_us, t3_us, t4_us):
                raise AssertionError(f"sample {index} was rejected")

    def test_recovers_offset_and_drift_from_bucket_minima(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)

        transform = estimator.transform
        snapshot = estimator.snapshot()
        self.assertTrue(transform.locked)
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertLess(abs(transform.drift_ppb - 80_000.0), 20_000)
        mapped = transform.map_us(10_000_000)
        expected = 2_000_000.0 + 10_000_000 * (1.0 + 80_000.0e-9)
        self.assertLess(abs(mapped - expected), 400)
        self.assertGreater(transform.uncertainty_us, 0)

    def test_20_hz_startup_keeps_enough_history_to_lock(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 360)

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertGreater(snapshot.sample_count, 120)
        self.assertGreaterEqual(snapshot.representative_span_us, 15_000_000)

    def test_raw_window_expires_samples_older_than_120_seconds(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 141, period_us=1_000_000)

        snapshot = estimator.snapshot()
        self.assertLessEqual(snapshot.sample_span_us, estimator.WINDOW_US)
        self.assertEqual(snapshot.sample_count, 121)

    def test_single_incompatible_sample_is_rtt_only_and_keeps_lock(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)
        previous = estimator.transform
        last_source_us = 1_000_000 + 400 * 50_000
        self.add_series(
            estimator,
            1,
            start_us=last_source_us,
            offset_us=2_100_000.0,
        )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertTrue(snapshot.usable)
        self.assertEqual(snapshot.rejected_count, 1)
        self.assertEqual(estimator.last_sample_result, "rtt_only")
        self.assertEqual(estimator.transform, previous)

    def test_five_new_incompatible_samples_reset_clock_epoch(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)
        last_source_us = 1_000_000 + 400 * 50_000
        self.add_series(
            estimator,
            5,
            start_us=last_source_us,
            offset_us=2_100_000.0,
        )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.PROVISIONAL)
        self.assertEqual(snapshot.sample_count, 5)
        self.assertTrue(snapshot.usable)
        self.assertFalse(estimator.transform.locked)

    def test_snapshot_reports_stale_without_mutating_transform(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)
        updated = estimator.snapshot().updated_monotonic
        with patch("network_clock.time.monotonic", return_value=updated + 6.0):
            snapshot = estimator.snapshot(stale_after_s=5.0)

        self.assertEqual(snapshot.state, ClockAlignmentState.STALE)
        self.assertTrue(estimator.transform.locked)
        self.assertEqual(snapshot.drift_ppb, estimator.transform.drift_ppb)
        self.assertGreater(snapshot.uncertainty_us, estimator.transform.uncertainty_us)

    def test_empty_estimator_remains_acquiring_instead_of_stale(self):
        estimator = AffineClockEstimator()
        self.assertEqual(
            estimator.snapshot(stale_after_s=5.0).state,
            ClockAlignmentState.ACQUIRING,
        )

    def test_high_delay_samples_affect_rtt_but_not_clock_fit(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)
        previous = estimator.transform
        start_us = 1_000_000 + 400 * 50_000

        for index in range(10):
            t1_us = start_us + index * 100_000
            self.assertTrue(
                estimator.add(
                    t1_us,
                    t1_us + 2_000_000 + 25_000,
                    t1_us + 2_000_000 + 25_040,
                    t1_us + 50_040,
                )
            )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertLess(
            abs(
                estimator.transform.map_us(estimator.transform.source_anchor_us)
                - previous.map_us(estimator.transform.source_anchor_us)
            ),
            estimator.MAX_MAPPING_STEP_US,
        )
        self.assertLess(
            abs(estimator.transform.drift_ppb - previous.drift_ppb),
            estimator.MAX_DRIFT_CHANGE_PPB_PER_S,
        )
        self.assertGreater(snapshot.rtt_p95_us, snapshot.delay_floor_us)

    def test_one_way_stats_are_not_synthesized_before_provisional_model(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 1)

        stats = estimator.path_stats()
        self.assertEqual(stats["rtt"]["samples"], 1)
        self.assertEqual(stats["upload"]["samples"], 0)
        self.assertEqual(stats["download"]["samples"], 0)

    def test_rtt_and_one_way_identity_is_preserved_after_lock(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)

        stats = estimator.path_stats()
        self.assertGreater(stats["upload"]["samples"], 0)
        self.assertGreater(stats["download"]["samples"], 0)
        self.assertLessEqual(
            abs(
                stats["upload"]["latest"]
                + stats["download"]["latest"]
                - stats["rtt"]["latest"]
            ),
            2,
        )

    def test_heavy_tail_wifi_jitter_does_not_destabilize_locked_model(self):
        estimator = AffineClockEstimator()
        random_source = random.Random(0x4E46)
        offset_us = 2_000_000.0
        drift_ppb = 60_000.0
        scale = 1.0 + drift_ppb * 1.0e-9
        locked_states = []
        published = []

        for index in range(600):
            t1_us = 10_000_000 + index * 100_000
            download_us = 3_000 + random_source.randrange(2_000)
            upload_us = 4_000 + random_source.randrange(2_000)
            if index % 23 == 0:
                download_us += 50_000
            if index % 37 == 0:
                upload_us += 100_000
            t2_us = int((t1_us + download_us - offset_us) / scale)
            t3_us = t2_us + 50
            t4_us = int(offset_us + t3_us * scale + upload_us)
            self.assertTrue(
                estimator.add_monitor_initiated(t1_us, t2_us, t3_us, t4_us)
            )

            snapshot = estimator.snapshot()
            if snapshot.state == ClockAlignmentState.LOCKED:
                locked_states.append(index)
            transform = estimator.transform
            if transform.locked and (
                not published or transform.revision != published[-1].revision
            ):
                published.append(transform)

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertTrue(locked_states)
        first_lock = locked_states[0]
        self.assertLessEqual(first_lock, 250)
        self.assertEqual(
            locked_states,
            list(range(first_lock, 600)),
        )
        self.assertLess(abs(estimator.transform.drift_ppb - drift_ppb), 20_000)
        self.assertLessEqual(
            estimator.transform.uncertainty_us,
            estimator.MAX_MODEL_UNCERTAINTY_US,
        )
        for previous, current in zip(published, published[1:]):
            self.assertLessEqual(
                abs(current.drift_ppb - previous.drift_ppb),
                estimator.MAX_DRIFT_CHANGE_PPB_PER_S + 1.0,
            )
            self.assertLessEqual(
                abs(
                    current.map_us(current.source_anchor_us)
                    - previous.map_us(current.source_anchor_us)
                ),
                estimator.MAX_MAPPING_STEP_US + 1.0,
            )

    def test_rejects_invalid_sample(self):
        estimator = AffineClockEstimator()
        self.assertFalse(estimator.add(10, 20, 15, 5))
        self.assertEqual(len(estimator.samples), 0)


if __name__ == "__main__":
    unittest.main()

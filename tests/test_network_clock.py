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

    def test_single_incompatible_sample_degrades_but_keeps_model(self):
        estimator = AffineClockEstimator()
        self.add_series(estimator, 400)
        last_source_us = 1_000_000 + 400 * 50_000
        self.add_series(
            estimator,
            1,
            start_us=last_source_us,
            offset_us=2_100_000.0,
        )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.DEGRADED)
        self.assertTrue(snapshot.usable)
        self.assertEqual(snapshot.rejected_count, 1)

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

    def test_rejects_invalid_sample(self):
        estimator = AffineClockEstimator()
        self.assertFalse(estimator.add(10, 20, 15, 5))
        self.assertEqual(len(estimator.samples), 0)


if __name__ == "__main__":
    unittest.main()

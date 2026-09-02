import random
import threading
import time
import unittest
from unittest.mock import patch

from network_clock import (
    AffineClockEstimator,
    ClockAlignmentState,
    ClockEstimatorStrategy,
    DriftAlignmentState,
    FourTimestampSample,
    OffsetAlignmentState,
    SelectableClockEstimator,
    create_clock_estimator,
)


class AffineClockEstimatorTest(unittest.TestCase):
    @staticmethod
    def new_estimator():
        return AffineClockEstimator(background_drift=False)

    @staticmethod
    def add_series(
        estimator,
        count,
        *,
        start_us=1_000_000,
        period_us=1_000_000,
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

    @staticmethod
    def add_monitor_series(
        estimator,
        count,
        *,
        random_source,
        start_us=10_000_000,
        period_us=1_000_000,
        offset_us=2_000_000.0,
        drift_ppb=60_000.0,
        changing_asymmetry=False,
    ):
        scale = 1.0 + drift_ppb * 1.0e-9
        for index in range(count):
            t1_us = start_us + index * period_us
            if changing_asymmetry:
                fraction = index / max(1, count - 1)
                download_us = int(800 + 3_000 * fraction)
                upload_us = int(4_000 - 3_000 * fraction)
            else:
                download_us = 3_000 + random_source.randrange(2_000)
                upload_us = 4_000 + random_source.randrange(2_000)
                if index % 23 == 0:
                    download_us += 50_000
                if index % 37 == 0:
                    upload_us += 100_000
            t2_us = int((t1_us + download_us - offset_us) / scale)
            t3_us = t2_us + 50
            t4_us = int(offset_us + t3_us * scale + upload_us)
            if not estimator.add_monitor_initiated(t1_us, t2_us, t3_us, t4_us):
                raise AssertionError(f"sample {index} was rejected")

    def test_four_timestamps_form_bounds_instead_of_midpoint_observation(self):
        offset_us = 2_000_000.0
        drift_ppb = 80_000.0
        scale = 1.0 + drift_ppb * 1.0e-9
        t1_us = 10_000_000
        t2_us = int((t1_us + 1_500 - offset_us) / scale)
        t3_us = t2_us + 40
        t4_us = int(offset_us + t3_us * scale + 4_500)
        sample = FourTimestampSample.target_initiated(t1_us, t2_us, t3_us, t4_us)
        anchor_us = sample.source_mid_us
        lower_us, upper_us = sample.offset_interval_at(anchor_us, drift_ppb)
        true_offset_at_anchor_us = offset_us + anchor_us * drift_ppb * 1.0e-9

        self.assertLessEqual(lower_us, true_offset_at_anchor_us)
        self.assertGreaterEqual(upper_us, true_offset_at_anchor_us)
        self.assertGreater(upper_us - lower_us, 5_900)

    def test_offset_becomes_usable_before_drift_is_known(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 4)

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.PROVISIONAL)
        self.assertEqual(snapshot.offset_state, OffsetAlignmentState.USABLE)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.UNKNOWN)
        self.assertTrue(estimator.transform.usable)
        self.assertFalse(estimator.transform.locked)

    def test_drift_progresses_on_a_longer_time_scale(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 70)
        self.assertEqual(estimator.snapshot().drift_state, DriftAlignmentState.CANDIDATE)
        self.assertNotEqual(estimator.snapshot().candidate_drift_ppb, 0.0)
        self.assertEqual(estimator.transform.drift_ppb, 0.0)

        self.add_series(estimator, 70, start_us=71_000_000)
        self.assertEqual(estimator.snapshot().drift_state, DriftAlignmentState.STABLE)
        self.assertNotEqual(estimator.transform.drift_ppb, 0.0)

        self.add_series(estimator, 100, start_us=141_000_000)
        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.LOCKED)

    def test_published_drift_only_changes_on_slow_estimator_updates(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 101, period_us=100_000)
        drift_ppb = estimator.transform.drift_ppb

        self.add_series(
            estimator,
            50,
            start_us=11_100_000,
            period_us=100_000,
        )
        self.assertEqual(estimator.transform.drift_ppb, drift_ppb)

    def test_long_window_recovers_offset_and_drift_interval(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)

        transform = estimator.transform
        snapshot = estimator.snapshot()
        self.assertTrue(transform.locked)
        self.assertLess(abs(transform.drift_ppb - 80_000.0), 20_000)
        self.assertLessEqual(snapshot.drift_lower_ppb, 80_000.0)
        self.assertGreaterEqual(snapshot.drift_upper_ppb, 80_000.0)
        mapped = transform.map_us(250_000_000)
        expected = 2_000_000.0 + 250_000_000 * (1.0 + 80_000.0e-9)
        self.assertLess(abs(mapped - expected), 2_000)

    def test_raw_model_window_expires_samples_older_than_300_seconds(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 321)

        snapshot = estimator.snapshot()
        self.assertLessEqual(snapshot.sample_span_us, estimator.WINDOW_US)
        self.assertLessEqual(snapshot.sample_count, 301)

    def test_single_incompatible_sample_is_rtt_only_and_keeps_lock(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)
        previous = estimator.transform
        self.add_series(estimator, 1, start_us=241_000_000, offset_us=2_100_000.0)

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertEqual(snapshot.rejected_count, 1)
        self.assertEqual(estimator.last_sample_result, "rtt_only")
        self.assertEqual(estimator.transform, previous)

    def test_five_new_incompatible_samples_reset_clock_epoch(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)
        previous_epoch = estimator.epoch
        self.add_series(estimator, 5, start_us=241_000_000, offset_us=2_100_000.0)

        snapshot = estimator.snapshot()
        self.assertEqual(estimator.epoch, previous_epoch + 1)
        self.assertEqual(snapshot.state, ClockAlignmentState.PROVISIONAL)
        self.assertEqual(snapshot.sample_count, 5)
        self.assertFalse(estimator.transform.locked)

    def test_snapshot_reports_stale_without_mutating_transform(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)
        updated = estimator.snapshot().updated_monotonic
        with patch("clock_estimator.time.monotonic", return_value=updated + 6.0):
            snapshot = estimator.snapshot(stale_after_s=5.0)

        self.assertEqual(snapshot.state, ClockAlignmentState.STALE)
        self.assertEqual(snapshot.offset_state, OffsetAlignmentState.HOLDOVER)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.HOLDOVER)
        self.assertTrue(estimator.transform.locked)
        self.assertGreater(snapshot.uncertainty_us, estimator.transform.uncertainty_us)

    def test_empty_estimator_remains_acquiring_instead_of_stale(self):
        estimator = self.new_estimator()
        self.assertEqual(
            estimator.snapshot(stale_after_s=5.0).state,
            ClockAlignmentState.ACQUIRING,
        )

    def test_wider_drift_interval_enters_holdover_without_replacing_model(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)
        previous = estimator.transform
        estimator.MAX_LOCK_DRIFT_UNCERTAINTY_PPB = 0.0

        self.add_series(estimator, 1, start_us=241_000_000)
        snapshot = estimator.snapshot()

        self.assertEqual(snapshot.state, ClockAlignmentState.DEGRADED)
        self.assertEqual(snapshot.offset_state, OffsetAlignmentState.HOLDOVER)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.HOLDOVER)
        self.assertEqual(estimator.transform, previous)

    def test_high_delay_samples_affect_rtt_but_not_clock_fit(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)
        previous = estimator.transform
        for index in range(10):
            t1_us = 241_000_000 + index * 1_000_000
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
            estimator.MAX_MAPPING_STEP_US + 1,
        )
        self.assertGreater(snapshot.rtt_p95_us, snapshot.delay_floor_us)

    def test_one_way_stats_are_not_synthesized_before_usable_offset(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 1)

        stats = estimator.path_stats()
        self.assertEqual(stats["rtt"]["samples"], 1)
        self.assertEqual(stats["upload"]["samples"], 0)
        self.assertEqual(stats["download"]["samples"], 0)

    def test_rtt_and_one_way_identity_is_preserved_after_lock(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 240)

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

    def test_snapshot_metadata_distinguishes_candidate_and_applied_drift(self):
        estimator = self.new_estimator()
        self.add_series(estimator, 70)

        metadata = estimator.snapshot().to_metadata()
        self.assertEqual(metadata["clock_drift_ppb"], 0.0)
        self.assertNotEqual(metadata["clock_candidate_drift_ppb"], 0.0)
        self.assertEqual(metadata["clock_drift_fit_pending"], 0)
        self.assertGreaterEqual(metadata["clock_drift_fit_runtime_ms"], 0.0)

    def test_heavy_tail_wifi_jitter_keeps_true_drift_in_confidence_set(self):
        estimator = self.new_estimator()
        self.add_monitor_series(
            estimator,
            260,
            random_source=random.Random(0x4E46),
        )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.PROVISIONAL)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.STABLE)
        self.assertGreater(
            snapshot.drift_uncertainty_ppb,
            estimator.MAX_LOCK_DRIFT_UNCERTAINTY_PPB,
        )
        self.assertLessEqual(snapshot.drift_lower_ppb, 60_000.0)
        self.assertGreaterEqual(snapshot.drift_upper_ppb, 60_000.0)
        self.assertLess(abs(estimator.transform.drift_ppb - 60_000.0), 30_000)

    def test_changing_path_asymmetry_does_not_become_clock_drift(self):
        estimator = self.new_estimator()
        self.add_monitor_series(
            estimator,
            260,
            random_source=random.Random(1),
            drift_ppb=0.0,
            changing_asymmetry=True,
        )

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertLessEqual(snapshot.drift_lower_ppb, 0.0)
        self.assertGreaterEqual(snapshot.drift_upper_ppb, 0.0)
        self.assertLess(abs(estimator.transform.drift_ppb), 30_000)

    def test_rejects_invalid_sample(self):
        estimator = self.new_estimator()
        self.assertFalse(estimator.add(10, 20, 15, 5))
        self.assertEqual(len(estimator.samples), 0)

    def test_background_drift_fit_does_not_block_sample_hot_path(self):
        class SlowEstimator(AffineClockEstimator):
            def _fit_joint_snapshot(self, representatives, delay_floor_us):
                time.sleep(0.15)
                return super()._fit_joint_snapshot(
                    representatives, delay_floor_us
                )

        estimator = SlowEstimator()
        self.addCleanup(estimator.close)
        started = time.perf_counter()
        self.add_series(estimator, 4, period_us=100_000)
        elapsed_s = time.perf_counter() - started

        self.assertLess(elapsed_s, 0.05)
        self.assertTrue(estimator.snapshot().drift_fit_pending)

    def test_background_fit_from_previous_epoch_is_discarded(self):
        class PausedEstimator(AffineClockEstimator):
            DRIFT_UPDATE_US = 0

            def __init__(self):
                self.fit_started = threading.Event()
                self.fit_release = threading.Event()
                super().__init__()

            def _fit_joint_snapshot(self, representatives, delay_floor_us):
                self.fit_started.set()
                self.fit_release.wait(timeout=1.0)
                return super()._fit_joint_snapshot(
                    representatives, delay_floor_us
                )

        estimator = PausedEstimator()
        self.addCleanup(estimator.close)
        self.add_series(estimator, 4, period_us=100_000)
        self.assertTrue(estimator.fit_started.wait(timeout=0.5))
        previous_epoch = estimator.epoch
        estimator.reset("test epoch rollover")
        estimator.fit_release.set()
        deadline = time.monotonic() + 1.0
        while estimator._drift_worker.pending and time.monotonic() < deadline:
            time.sleep(0.01)

        with estimator._lock:
            self.assertFalse(estimator._consume_drift_results_locked())
            self.assertIsNone(estimator._joint_fit)
            self.assertIsNone(estimator._last_drift_fit_source_us)
        self.assertEqual(estimator.epoch, previous_epoch + 1)


class ClockEstimatorStrategyTest(unittest.TestCase):
    def test_v3_preserves_fast_lock_and_identifies_metadata(self):
        estimator = create_clock_estimator(
            ClockEstimatorStrategy.V3, background_drift=False
        )
        AffineClockEstimatorTest.add_series(estimator, 25)

        snapshot = estimator.snapshot()
        self.assertEqual(snapshot.strategy, ClockEstimatorStrategy.V3)
        self.assertEqual(snapshot.state, ClockAlignmentState.LOCKED)
        self.assertEqual(snapshot.drift_state, DriftAlignmentState.LOCKED)
        self.assertLess(abs(snapshot.drift_ppb - 80_000.0), 20_000.0)
        self.assertEqual(
            snapshot.to_metadata()["clock_model"],
            "robust_affine_interval_v3",
        )

    def test_hybrid_gates_v3_point_with_v4_state_and_bounds(self):
        estimator = create_clock_estimator(
            ClockEstimatorStrategy.V4_V3, background_drift=False
        )
        AffineClockEstimatorTest.add_series(estimator, 70)

        candidate = estimator.snapshot()
        self.assertEqual(candidate.drift_state, DriftAlignmentState.CANDIDATE)
        self.assertEqual(estimator.transform.drift_ppb, 0.0)
        self.assertNotEqual(candidate.statistical_candidate_drift_ppb, 0.0)

        AffineClockEstimatorTest.add_series(
            estimator, 70, start_us=71_000_000
        )
        stable = estimator.snapshot()
        self.assertEqual(stable.strategy, ClockEstimatorStrategy.V4_V3)
        self.assertEqual(stable.drift_state, DriftAlignmentState.STABLE)
        self.assertLessEqual(
            stable.drift_lower_ppb, stable.candidate_drift_ppb
        )
        self.assertGreaterEqual(
            stable.drift_upper_ppb, stable.candidate_drift_ppb
        )
        self.assertAlmostEqual(
            estimator.transform.drift_ppb,
            stable.candidate_drift_ppb,
        )
        self.assertEqual(
            stable.to_metadata()["clock_model"],
            "constrained_affine_hybrid_v4_v3",
        )

    def test_switching_strategy_resets_fit_without_advancing_epoch(self):
        estimator = SelectableClockEstimator(
            ClockEstimatorStrategy.V4_V3, background_drift=False
        )
        AffineClockEstimatorTest.add_series(estimator, 20)
        epoch = estimator.epoch
        revision = estimator.transform.revision

        self.assertTrue(estimator.switch_strategy(ClockEstimatorStrategy.V3))
        self.assertEqual(estimator.strategy, ClockEstimatorStrategy.V3)
        self.assertEqual(estimator.epoch, epoch)
        self.assertEqual(estimator.snapshot().sample_count, 0)
        self.assertFalse(estimator.transform.usable)
        self.assertGreater(estimator.transform.revision, revision)

        estimator.reset("physical clock restart")
        self.assertEqual(estimator.epoch, epoch + 1)

    def test_restarting_estimation_keeps_strategy_and_physical_epoch(self):
        estimator = SelectableClockEstimator(
            ClockEstimatorStrategy.V4_V3, background_drift=False
        )
        AffineClockEstimatorTest.add_series(estimator, 20)
        epoch = estimator.epoch
        revision = estimator.transform.revision

        estimator.restart_estimation("NFv4 reconnect")

        self.assertEqual(estimator.strategy, ClockEstimatorStrategy.V4_V3)
        self.assertEqual(estimator.epoch, epoch)
        self.assertEqual(estimator.snapshot().sample_count, 0)
        self.assertFalse(estimator.transform.usable)
        self.assertGreater(estimator.transform.revision, revision)


if __name__ == "__main__":
    unittest.main()

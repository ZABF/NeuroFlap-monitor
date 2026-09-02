from collections import deque
from dataclasses import dataclass, replace
import math
import threading
import time

from clock_delay_filter import ClockObservationWindow
from clock_drift_worker import (
    BackgroundDriftFitWorker,
    DriftFitRequest,
    InlineDriftFitWorker,
)
from clock_observation import FourTimestampSample
from clock_types import (
    ClockAlignmentSnapshot,
    ClockAlignmentState,
    ClockEstimatorStrategy,
    ClockTransform,
    DriftAlignmentState,
    OffsetAlignmentState,
)


@dataclass(frozen=True)
class _IntervalSupport:
    drift_ppb: float
    lower_offset_us: float
    upper_offset_us: float
    compatible_count: int
    quality: float
    strict: bool


@dataclass(frozen=True)
class _JointFit:
    source_anchor_us: float
    offset_lower_us: float
    offset_upper_us: float
    drift_ppb: float
    drift_lower_ppb: float
    drift_upper_ppb: float
    compatible_count: int
    required_count: int
    strict: bool
    accepted: bool
    physical_drift_ppb: float = math.nan
    statistical_drift_ppb: float = math.nan
    statistical_uncertainty_ppb: float = math.inf

    @property
    def offset_us(self):
        return (self.offset_lower_us + self.offset_upper_us) * 0.5

    @property
    def uncertainty_us(self):
        return max(0.5, (self.offset_upper_us - self.offset_lower_us) * 0.5)

    @property
    def drift_uncertainty_ppb(self):
        return max(0.0, (self.drift_upper_ppb - self.drift_lower_ppb) * 0.5)


class AffineClockEstimator:
    STRATEGY = ClockEstimatorStrategy.V4
    MODEL_NAME = "robust_affine_set_membership_v4"
    WINDOW_SECONDS = 300
    WINDOW_US = ClockObservationWindow.MODEL_WINDOW_US
    PATH_WINDOW_US = ClockObservationWindow.PATH_WINDOW_US
    OFFSET_WINDOW_US = ClockObservationWindow.OFFSET_WINDOW_US
    DELAY_FLOOR_WINDOW_US = ClockObservationWindow.DELAY_FLOOR_WINDOW_US
    HARD_MAX_RAW_SAMPLES = ClockObservationWindow.HARD_MAX_RAW_SAMPLES
    BUCKET_US = ClockObservationWindow.BUCKET_US
    REPRESENTATIVES_PER_BUCKET = ClockObservationWindow.REPRESENTATIVES_PER_BUCKET
    MAX_REPRESENTATIVES = ClockObservationWindow.MAX_REPRESENTATIVES

    DRIFT_UPDATE_US = 10_000_000
    MIN_OFFSET_SAMPLES = 4
    MIN_LOCK_REPRESENTATIVES = 8
    MIN_DRIFT_ESTIMATE_SPAN_US = 10_000_000
    MIN_DRIFT_EVIDENCE_SPAN_US = 60_000_000
    MIN_DRIFT_STABLE_SPAN_US = 120_000_000
    MIN_LOCK_SPAN_US = 180_000_000
    LOCK_CONFIRM_UPDATES = 3
    MAX_DRIFT_PPB = 500_000.0
    COARSE_DRIFT_STEP_PPB = 5_000.0
    MIN_CONSENSUS_SAMPLES = 4
    MIN_CONSENSUS_RATIO = 0.80
    MAX_STABLE_DRIFT_UNCERTAINTY_PPB = 40_000.0
    MAX_LOCK_DRIFT_UNCERTAINTY_PPB = 25_000.0
    CLOCK_JUMP_CONSECUTIVE_SAMPLES = 5
    CLOCK_ROLLBACK_RESET_US = 1_000_000
    MAX_SAMPLE_RTT_US = 60_000_000
    MAX_MODEL_UNCERTAINTY_US = 5_000.0
    MAX_DRIFT_CHANGE_PPB_PER_S = 5_000.0
    MAX_MAPPING_STEP_US = 500.0
    DRIFT_SMOOTHING_TIME_S = 30.0
    OFFSET_SMOOTHING_TIME_S = 4.0
    HOLDOVER_MIN_GROWTH_US_PER_S = 50.0

    def __init__(self, *, background_drift=True, initial_epoch=1):
        self._lock = threading.RLock()
        self._window = ClockObservationWindow()
        self._epoch = max(1, int(initial_epoch))
        self._revision = 0
        self._transform = ClockTransform(epoch=self._epoch)
        self._snapshot = ClockAlignmentSnapshot(
            strategy=self.STRATEGY,
            model_name=self.MODEL_NAME,
            window_s=self.WINDOW_SECONDS,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            epoch=self._epoch,
        )
        self._joint_fit = None
        self._representatives_cache = ()
        self._last_drift_request_source_us = None
        self._last_drift_fit_source_us = None
        self._drift_fit_runtime_ms = 0.0
        self._drift_fit_error = ""
        self._stable_drift_admitted = False
        self._last_conditioned_drift_source_us = None
        self._healthy_fit_streak = 0
        self._consecutive_incompatible = 0
        self._incompatible_tail = deque(maxlen=self.CLOCK_JUMP_CONSECUTIVE_SAMPLES)
        self._last_source_mid_us = None
        self._last_target_mid_us = None
        self._last_reliable_sample_monotonic = 0.0
        self._last_good_monotonic = 0.0
        self._model_outlier_count = 0
        self._reset_count = 0
        self._last_reset_reason = "initial"
        self._last_sample_result = "none"
        worker_type = BackgroundDriftFitWorker if background_drift else InlineDriftFitWorker
        self._drift_worker = worker_type(self._fit_joint_snapshot)

    @property
    def epoch(self):
        with self._lock:
            return self._epoch

    @property
    def strategy(self):
        return self.STRATEGY

    @property
    def samples(self):
        with self._lock:
            return self._window.samples

    @property
    def transform(self):
        with self._lock:
            return self._transform

    @property
    def last_sample_result(self):
        with self._lock:
            return self._last_sample_result

    def representatives(self):
        with self._lock:
            return tuple(self._window.representatives())

    def close(self):
        self._drift_worker.close()

    @staticmethod
    def _valid(sample):
        return (
            sample.source_lower_us > 0
            and sample.target_lower_us > 0
            and sample.source_upper_us > 0
            and sample.target_upper_us > 0
            and 0 <= sample.rtt_us <= AffineClockEstimator.MAX_SAMPLE_RTT_US
        )

    def _reset_locked(self, reason="reset"):
        self._window.clear()
        self._epoch += 1
        self._revision += 1
        self._transform = ClockTransform(epoch=self._epoch, revision=self._revision)
        self._reset_count += 1
        self._last_reset_reason = str(reason or "reset")
        self._snapshot = ClockAlignmentSnapshot(
            strategy=self.STRATEGY,
            model_name=self.MODEL_NAME,
            window_s=self.WINDOW_SECONDS,
            reset_count=self._reset_count,
            last_reset_reason=self._last_reset_reason,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            epoch=self._epoch,
            revision=self._revision,
        )
        self._joint_fit = None
        self._representatives_cache = ()
        self._last_drift_request_source_us = None
        self._last_drift_fit_source_us = None
        self._drift_fit_runtime_ms = 0.0
        self._drift_fit_error = ""
        self._stable_drift_admitted = False
        self._last_conditioned_drift_source_us = None
        self._healthy_fit_streak = 0
        self._consecutive_incompatible = 0
        self._incompatible_tail.clear()
        self._last_source_mid_us = None
        self._last_target_mid_us = None
        self._last_reliable_sample_monotonic = 0.0
        self._last_good_monotonic = 0.0
        self._model_outlier_count = 0
        self._last_sample_result = "epoch_reset"

    def reset(self, reason="reset"):
        with self._lock:
            self._reset_locked(reason)

    def add(self, t1_us, t2_us, t3_us, t4_us):
        if int(t4_us) < int(t1_us) or int(t3_us) < int(t2_us):
            with self._lock:
                self._last_sample_result = "invalid"
            return False
        return self._add_sample(
            FourTimestampSample.source_initiated(t1_us, t2_us, t3_us, t4_us)
        )

    def add_monitor_initiated(self, t1_us, t2_us, t3_us, t4_us):
        if int(t4_us) < int(t1_us) or int(t3_us) < int(t2_us):
            with self._lock:
                self._last_sample_result = "invalid"
            return False
        return self._add_sample(
            FourTimestampSample.target_initiated(t1_us, t2_us, t3_us, t4_us)
        )

    def _append_model_sample_locked(self, sample):
        self._window.append_model(sample)
        samples = self._window.samples
        self._last_source_mid_us = max(item.source_mid_us for item in samples)
        self._last_target_mid_us = max(item.target_mid_us for item in samples)
        self._last_reliable_sample_monotonic = sample.received_monotonic

    def _add_sample(self, sample):
        if not self._valid(sample):
            with self._lock:
                self._last_sample_result = "invalid"
            return False

        with self._lock:
            source_rollback = (
                self._last_source_mid_us is not None
                and sample.source_mid_us
                < self._last_source_mid_us - self.CLOCK_ROLLBACK_RESET_US
            )
            target_rollback = (
                self._last_target_mid_us is not None
                and sample.target_mid_us
                < self._last_target_mid_us - self.CLOCK_ROLLBACK_RESET_US
            )
            if source_rollback or target_rollback:
                self._reset_locked(
                    "source clock rollback" if source_rollback else "target clock rollback"
                )

            if self._transform.locked and not self._sample_matches_transform_locked(sample):
                self._consecutive_incompatible += 1
                self._incompatible_tail.append(sample)
                self._model_outlier_count += 1
                self._window.append_path(sample)
                if self._consecutive_incompatible < self.CLOCK_JUMP_CONSECUTIVE_SAMPLES:
                    self._refresh_snapshot_path_stats_locked(sample.received_monotonic)
                    self._last_sample_result = "rtt_only"
                    return True
                restart_samples = tuple(self._incompatible_tail)
                self._reset_locked("five consecutive incompatible samples")
                for restart_sample in restart_samples:
                    self._window.append_path(restart_sample)
                    self._append_model_sample_locked(restart_sample)
            else:
                self._consecutive_incompatible = 0
                self._incompatible_tail.clear()
                self._window.append_path(sample)
                self._append_model_sample_locked(sample)

            drift_updated = self._consume_drift_results_locked()
            newest_source_us = max(item.source_mid_us for item in self._window.samples)
            drift_due = (
                self._last_drift_request_source_us is None
                or newest_source_us - self._last_drift_request_source_us
                >= self.DRIFT_UPDATE_US
            )
            if drift_due:
                representatives = tuple(self._window.representatives())
                self._representatives_cache = representatives
                self._drift_worker.submit(
                    DriftFitRequest(
                        epoch=self._epoch,
                        source_watermark_us=newest_source_us,
                        representatives=representatives,
                        delay_floor_us=self._window.delay_floor(),
                    )
                )
                self._last_drift_request_source_us = newest_source_us
                drift_updated = self._consume_drift_results_locked() or drift_updated
            model_updated = self._fit_offset_locked(drift_updated)
            self._last_sample_result = "model_updated" if model_updated else "clock_candidate"
        return True

    def _consume_drift_results_locked(self):
        updated = False
        for result in self._drift_worker.poll_results():
            if result.epoch != self._epoch:
                continue
            if (
                self._last_drift_fit_source_us is not None
                and result.source_watermark_us < self._last_drift_fit_source_us
            ):
                continue
            self._joint_fit = result.fit
            self._representatives_cache = result.representatives
            self._last_drift_fit_source_us = result.source_watermark_us
            self._drift_fit_runtime_ms = result.runtime_ms
            self._drift_fit_error = result.error
            updated = True
        return updated

    def _support_at_drift_locked(
        self, samples, source_anchor_us, drift_ppb, delay_floor_us
    ):
        intervals = []
        for sample in samples:
            lower_us, upper_us = sample.offset_interval_at(source_anchor_us, drift_ppb)
            if lower_us <= upper_us:
                floor = max(1.0, delay_floor_us)
                weight = (floor / max(floor, float(sample.rtt_us))) ** 2
                intervals.append((lower_us, upper_us, weight))
        if not intervals:
            return _IntervalSupport(drift_ppb, 0.0, 0.0, 0, 0.0, False)

        events = []
        for index, (lower_us, upper_us, _weight) in enumerate(intervals):
            events.append((lower_us, 0, index))
            events.append((upper_us, 1, index))
        active = set()
        active_quality = 0.0
        best_active = set()
        best_quality = -1.0
        for _coordinate, event_type, index in sorted(events):
            if event_type == 0:
                active.add(index)
                active_quality += intervals[index][2]
                if len(active) > len(best_active) or (
                    len(active) == len(best_active) and active_quality > best_quality
                ):
                    best_active = set(active)
                    best_quality = active_quality
            elif index in active:
                active.remove(index)
                active_quality -= intervals[index][2]
        lower_us = max(intervals[index][0] for index in best_active)
        upper_us = min(intervals[index][1] for index in best_active)
        return _IntervalSupport(
            float(drift_ppb),
            lower_us,
            upper_us,
            len(best_active),
            max(0.0, best_quality),
            len(best_active) == len(intervals),
        )

    def _refine_drift_boundary_locked(
        self,
        samples,
        anchor_us,
        delay_floor_us,
        accepted_ppb,
        rejected_ppb,
        threshold,
    ):
        accepted = float(accepted_ppb)
        rejected = float(rejected_ppb)
        for _iteration in range(18):
            middle = (accepted + rejected) * 0.5
            support = self._support_at_drift_locked(
                samples, anchor_us, middle, delay_floor_us
            )
            if support.compatible_count >= threshold:
                accepted = middle
            else:
                rejected = middle
        return accepted

    def _fit_joint_snapshot(self, representatives, delay_floor_us):
        if len(representatives) < self.MIN_OFFSET_SAMPLES:
            return None
        source_anchor_us = representatives[-1].source_mid_us
        required = max(
            self.MIN_CONSENSUS_SAMPLES,
            int(math.ceil(len(representatives) * self.MIN_CONSENSUS_RATIO)),
        )
        span_us = representatives[-1].source_mid_us - representatives[0].source_mid_us
        if span_us < self.MIN_DRIFT_ESTIMATE_SPAN_US:
            support = self._support_at_drift_locked(
                representatives, source_anchor_us, 0.0, delay_floor_us
            )
            return _JointFit(
                source_anchor_us,
                support.lower_offset_us,
                support.upper_offset_us,
                0.0,
                -self.MAX_DRIFT_PPB,
                self.MAX_DRIFT_PPB,
                support.compatible_count,
                required,
                support.strict,
                support.compatible_count >= required,
                physical_drift_ppb=0.0,
            )

        grid = []
        drift_ppb = -self.MAX_DRIFT_PPB
        while drift_ppb <= self.MAX_DRIFT_PPB + 0.5:
            grid.append(
                self._support_at_drift_locked(
                    representatives, source_anchor_us, drift_ppb, delay_floor_us
                )
            )
            drift_ppb += self.COARSE_DRIFT_STEP_PPB
        best = max(grid, key=lambda item: (item.compatible_count, item.quality))
        tolerance = max(1, int(len(representatives) * 0.02))
        support_threshold = max(required, best.compatible_count - tolerance)
        best_index = grid.index(best)
        left_index = best_index
        while (
            left_index > 0
            and grid[left_index - 1].compatible_count >= support_threshold
        ):
            left_index -= 1
        right_index = best_index
        while (
            right_index + 1 < len(grid)
            and grid[right_index + 1].compatible_count >= support_threshold
        ):
            right_index += 1

        drift_lower_ppb = grid[left_index].drift_ppb
        if left_index > 0:
            drift_lower_ppb = self._refine_drift_boundary_locked(
                representatives,
                source_anchor_us,
                delay_floor_us,
                grid[left_index].drift_ppb,
                grid[left_index - 1].drift_ppb,
                support_threshold,
            )
        drift_upper_ppb = grid[right_index].drift_ppb
        if right_index + 1 < len(grid):
            drift_upper_ppb = self._refine_drift_boundary_locked(
                representatives,
                source_anchor_us,
                delay_floor_us,
                grid[right_index].drift_ppb,
                grid[right_index + 1].drift_ppb,
                support_threshold,
            )
        candidate_drift_ppb = (drift_lower_ppb + drift_upper_ppb) * 0.5
        candidate = self._support_at_drift_locked(
            representatives, source_anchor_us, candidate_drift_ppb, delay_floor_us
        )
        if candidate.compatible_count < support_threshold:
            candidate = best
            candidate_drift_ppb = best.drift_ppb

        boundary_support = [
            candidate,
            self._support_at_drift_locked(
                representatives, source_anchor_us, drift_lower_ppb, delay_floor_us
            ),
            self._support_at_drift_locked(
                representatives, source_anchor_us, drift_upper_ppb, delay_floor_us
            ),
        ]
        valid_bounds = [
            item
            for item in boundary_support
            if item.compatible_count >= support_threshold
        ]
        return _JointFit(
            source_anchor_us=source_anchor_us,
            offset_lower_us=min(item.lower_offset_us for item in valid_bounds),
            offset_upper_us=max(item.upper_offset_us for item in valid_bounds),
            drift_ppb=candidate_drift_ppb,
            drift_lower_ppb=drift_lower_ppb,
            drift_upper_ppb=drift_upper_ppb,
            compatible_count=candidate.compatible_count,
            required_count=required,
            strict=candidate.strict,
            accepted=candidate.compatible_count >= required,
            physical_drift_ppb=candidate_drift_ppb,
        )

    def _fit_offset_at_drift_locked(self, drift_ppb):
        candidates, delay_floor_us = self._window.offset_candidates()
        if len(candidates) < self.MIN_OFFSET_SAMPLES:
            return None
        source_anchor_us = max(item.source_mid_us for item in candidates)
        required = max(
            self.MIN_CONSENSUS_SAMPLES,
            int(math.ceil(len(candidates) * self.MIN_CONSENSUS_RATIO)),
        )
        support = self._support_at_drift_locked(
            candidates, source_anchor_us, drift_ppb, delay_floor_us
        )
        return _JointFit(
            source_anchor_us,
            support.lower_offset_us,
            support.upper_offset_us,
            drift_ppb,
            drift_ppb,
            drift_ppb,
            support.compatible_count,
            required,
            support.strict,
            support.compatible_count >= required,
        )

    def _drift_state_locked(self, fit, representative_span_us, drift_updated):
        if fit is None or not fit.accepted:
            if drift_updated:
                self._healthy_fit_streak = 0
            return DriftAlignmentState.UNKNOWN
        uncertainty_ppb = fit.drift_uncertainty_ppb
        stable = (
            representative_span_us >= self.MIN_DRIFT_STABLE_SPAN_US
            and uncertainty_ppb <= self.MAX_STABLE_DRIFT_UNCERTAINTY_PPB
        )
        lock_eligible = (
            representative_span_us >= self.MIN_LOCK_SPAN_US
            and uncertainty_ppb <= self.MAX_LOCK_DRIFT_UNCERTAINTY_PPB
        )
        if drift_updated:
            self._healthy_fit_streak = self._healthy_fit_streak + 1 if lock_eligible else 0
        if lock_eligible and self._healthy_fit_streak >= self.LOCK_CONFIRM_UPDATES:
            return DriftAlignmentState.LOCKED
        if stable:
            return DriftAlignmentState.STABLE
        if representative_span_us >= self.MIN_DRIFT_EVIDENCE_SPAN_US:
            return DriftAlignmentState.CANDIDATE
        return DriftAlignmentState.UNKNOWN

    def _condition_candidate_locked(self, candidate, now_monotonic, drift_updated):
        if not self._transform.locked:
            return candidate
        elapsed_s = max(1.0, now_monotonic - self._transform.updated_monotonic)
        raw_mapping_delta_us = (
            candidate.map_us(candidate.source_anchor_us)
            - self._transform.map_us(candidate.source_anchor_us)
        )
        offset_alpha = min(1.0, elapsed_s / self.OFFSET_SMOOTHING_TIME_S)
        conditioned_drift_ppb = self._transform.drift_ppb
        if drift_updated:
            drift_elapsed_s = (
                self.DRIFT_UPDATE_US / 1.0e6
                if self._last_conditioned_drift_source_us is None
                else max(
                    self.DRIFT_UPDATE_US / 1.0e6,
                    (
                        candidate.source_anchor_us
                        - self._last_conditioned_drift_source_us
                    )
                    / 1.0e6,
                )
            )
            drift_limit_ppb = self.MAX_DRIFT_CHANGE_PPB_PER_S * drift_elapsed_s
            drift_alpha = min(1.0, drift_elapsed_s / self.DRIFT_SMOOTHING_TIME_S)
            raw_drift_delta_ppb = candidate.drift_ppb - self._transform.drift_ppb
            conditioned_drift_ppb += max(
                -drift_limit_ppb,
                min(drift_limit_ppb, raw_drift_delta_ppb * drift_alpha),
            )
            self._last_conditioned_drift_source_us = candidate.source_anchor_us
        conditioned_target_us = self._transform.map_us(
            candidate.source_anchor_us
        ) + max(
            -self.MAX_MAPPING_STEP_US,
            min(self.MAX_MAPPING_STEP_US, raw_mapping_delta_us * offset_alpha),
        )
        return replace(
            candidate,
            target_anchor_us=conditioned_target_us,
            drift_ppb=conditioned_drift_ppb,
            uncertainty_us=max(
                candidate.uncertainty_us,
                abs(candidate.target_anchor_us - conditioned_target_us),
            ),
        )

    def _publish_transform_locked(self, candidate, now_monotonic):
        self._revision += 1
        self._transform = replace(
            candidate,
            epoch=self._epoch,
            revision=self._revision,
            updated_monotonic=now_monotonic,
        )
        self._last_good_monotonic = now_monotonic

    def _fit_offset_locked(self, drift_updated):
        samples = self._window.samples
        if not samples:
            return False
        representatives = self._representatives_cache
        representative_span_us = (
            0.0
            if len(representatives) < 2
            else representatives[-1].source_mid_us
            - representatives[0].source_mid_us
        )
        joint_fit = self._joint_fit
        drift_state = self._drift_state_locked(
            joint_fit, representative_span_us, drift_updated
        )
        candidate_drift_ppb = (
            joint_fit.drift_ppb if joint_fit is not None else 0.0
        )
        drift_is_admissible = (
            joint_fit is not None
            and joint_fit.accepted
            and drift_state
            in (DriftAlignmentState.STABLE, DriftAlignmentState.LOCKED)
        )
        if drift_is_admissible:
            applied_drift_ppb = joint_fit.drift_ppb
            self._stable_drift_admitted = True
        elif self._stable_drift_admitted and self._transform.usable:
            applied_drift_ppb = self._transform.drift_ppb
        else:
            applied_drift_ppb = 0.0
        offset_fit = self._fit_offset_at_drift_locked(applied_drift_ppb)
        if offset_fit is None:
            self._refresh_snapshot_path_stats_locked(time.monotonic())
            return False

        if (
            offset_fit.accepted
            and offset_fit.uncertainty_us <= self.MAX_MODEL_UNCERTAINTY_US
        ):
            offset_state = OffsetAlignmentState.USABLE
        elif offset_fit.accepted:
            offset_state = OffsetAlignmentState.PROVISIONAL
        else:
            offset_state = OffsetAlignmentState.ACQUIRING
        now_monotonic = time.monotonic()
        locked = (
            offset_state == OffsetAlignmentState.USABLE
            and drift_state == DriftAlignmentState.LOCKED
        )
        holding = self._transform.locked and not locked
        candidate_transform = ClockTransform(
            source_anchor_us=offset_fit.source_anchor_us,
            target_anchor_us=offset_fit.source_anchor_us + offset_fit.offset_us,
            drift_ppb=applied_drift_ppb,
            uncertainty_us=offset_fit.uncertainty_us,
            usable=offset_state == OffsetAlignmentState.USABLE,
            locked=locked,
            epoch=self._epoch,
        )
        if not holding:
            candidate_transform = self._condition_candidate_locked(
                candidate_transform, now_monotonic, drift_updated
            )
        model_updated = False
        if candidate_transform.usable and not holding:
            self._publish_transform_locked(candidate_transform, now_monotonic)
            model_updated = True

        if holding:
            state = ClockAlignmentState.DEGRADED
            offset_state = OffsetAlignmentState.HOLDOVER
            drift_state = DriftAlignmentState.HOLDOVER
        elif locked:
            state = ClockAlignmentState.LOCKED
        elif candidate_transform.usable:
            state = ClockAlignmentState.PROVISIONAL
        else:
            state = ClockAlignmentState.ACQUIRING
        display_transform = (
            self._transform if self._transform.usable else candidate_transform
        )
        if holding:
            display_offset_us = (
                display_transform.target_anchor_us - display_transform.source_anchor_us
            )
            display_offset_lower_us = (
                display_offset_us - display_transform.uncertainty_us
            )
            display_offset_upper_us = (
                display_offset_us + display_transform.uncertainty_us
            )
        else:
            display_offset_lower_us = offset_fit.offset_lower_us
            display_offset_upper_us = offset_fit.offset_upper_us
        drift_lower_ppb = (
            joint_fit.drift_lower_ppb if joint_fit is not None else -math.inf
        )
        drift_upper_ppb = (
            joint_fit.drift_upper_ppb if joint_fit is not None else math.inf
        )
        drift_uncertainty_ppb = (
            joint_fit.drift_uncertainty_ppb if joint_fit is not None else math.inf
        )
        sample_span_us = max(item.source_mid_us for item in samples) - min(
            item.source_mid_us for item in samples
        )
        candidates, delay_floor_us = self._window.offset_candidates()
        path_rtts = [float(item.rtt_us) for item in self._window.path_samples]
        self._snapshot = ClockAlignmentSnapshot(
            strategy=self.STRATEGY,
            model_name=self.MODEL_NAME,
            window_s=self.WINDOW_SECONDS,
            state=state,
            offset_state=offset_state,
            drift_state=drift_state,
            source_anchor_us=display_transform.source_anchor_us,
            target_anchor_us=display_transform.target_anchor_us,
            offset_us=display_transform.target_anchor_us
            - display_transform.source_anchor_us,
            offset_lower_us=display_offset_lower_us,
            offset_upper_us=display_offset_upper_us,
            uncertainty_us=display_transform.uncertainty_us,
            drift_ppb=display_transform.drift_ppb,
            candidate_drift_ppb=candidate_drift_ppb,
            physical_candidate_drift_ppb=(
                joint_fit.physical_drift_ppb if joint_fit is not None else math.nan
            ),
            statistical_candidate_drift_ppb=(
                joint_fit.statistical_drift_ppb
                if joint_fit is not None
                else math.nan
            ),
            statistical_drift_uncertainty_ppb=(
                joint_fit.statistical_uncertainty_ppb
                if joint_fit is not None
                else math.inf
            ),
            drift_lower_ppb=drift_lower_ppb,
            drift_upper_ppb=drift_upper_ppb,
            drift_uncertainty_ppb=drift_uncertainty_ppb,
            sample_count=len(samples),
            candidate_count=len(candidates),
            representative_count=len(representatives),
            sample_span_us=sample_span_us,
            representative_span_us=representative_span_us,
            rejected_count=self._model_outlier_count
            + max(0, len(candidates) - offset_fit.compatible_count),
            minimum_rtt_us=min(path_rtts) if path_rtts else math.inf,
            latest_rtt_us=path_rtts[-1] if path_rtts else math.inf,
            rtt_p50_us=ClockObservationWindow.percentile(path_rtts, 50.0),
            rtt_p95_us=ClockObservationWindow.percentile(path_rtts, 95.0),
            delay_floor_us=delay_floor_us,
            strict_intersection=offset_fit.strict,
            consensus_accepted=offset_fit.accepted,
            compatible_count=offset_fit.compatible_count,
            consensus_required_count=offset_fit.required_count,
            drift_fit_valid=joint_fit is not None and joint_fit.accepted,
            drift_fit_pending=self._drift_worker.pending,
            drift_fit_runtime_ms=self._drift_fit_runtime_ms,
            drift_fit_error=self._drift_fit_error,
            healthy_fit_streak=self._healthy_fit_streak,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            model_age_s=(
                0.0
                if model_updated
                else math.inf
                if self._last_good_monotonic <= 0.0
                else max(0.0, now_monotonic - self._last_good_monotonic)
            ),
            holdover_age_s=(
                max(0.0, now_monotonic - self._last_good_monotonic)
                if holding and self._last_good_monotonic > 0.0
                else 0.0
            ),
            reset_count=self._reset_count,
            last_reset_reason=self._last_reset_reason,
            epoch=self._epoch,
            revision=self._transform.revision,
            updated_monotonic=now_monotonic,
        )
        return model_updated

    def _sample_matches_transform_locked(self, sample):
        transform = self._transform
        lower_us, upper_us = sample.offset_interval_at(
            transform.source_anchor_us, transform.drift_ppb
        )
        offset_us = transform.target_anchor_us - transform.source_anchor_us
        margin_us = max(transform.uncertainty_us, 1.0)
        return not (
            upper_us < offset_us - margin_us
            or lower_us > offset_us + margin_us
        )

    def _refresh_snapshot_path_stats_locked(self, now_monotonic):
        path_rtts = [float(item.rtt_us) for item in self._window.path_samples]
        self._snapshot = replace(
            self._snapshot,
            rejected_count=max(
                self._snapshot.rejected_count, self._model_outlier_count
            ),
            minimum_rtt_us=min(path_rtts) if path_rtts else math.inf,
            latest_rtt_us=path_rtts[-1] if path_rtts else math.inf,
            rtt_p50_us=ClockObservationWindow.percentile(path_rtts, 50.0),
            rtt_p95_us=ClockObservationWindow.percentile(path_rtts, 95.0),
            updated_monotonic=now_monotonic,
        )

    def _holdover_uncertainty_locked(self, now_monotonic):
        if not self._transform.usable or self._last_good_monotonic <= 0.0:
            return self._transform.uncertainty_us
        age_s = max(0.0, now_monotonic - self._last_good_monotonic)
        drift_uncertainty_ppb = self._snapshot.drift_uncertainty_ppb
        if not math.isfinite(drift_uncertainty_ppb):
            drift_uncertainty_ppb = self.MAX_DRIFT_PPB
        growth_us_per_s = max(
            self.HOLDOVER_MIN_GROWTH_US_PER_S,
            drift_uncertainty_ppb * 1.0e-3,
        )
        return self._transform.uncertainty_us + age_s * growth_us_per_s

    def snapshot(self, stale_after_s=None):
        with self._lock:
            snapshot = self._snapshot
            now_monotonic = time.monotonic()
            sample_age_s = (
                math.inf
                if self._last_reliable_sample_monotonic <= 0.0
                else max(0.0, now_monotonic - self._last_reliable_sample_monotonic)
            )
            model_age_s = (
                math.inf
                if self._last_good_monotonic <= 0.0
                else max(0.0, now_monotonic - self._last_good_monotonic)
            )
            state = snapshot.state
            offset_state = snapshot.offset_state
            drift_state = snapshot.drift_state
            if (
                stale_after_s is not None
                and self._last_reliable_sample_monotonic > 0.0
                and sample_age_s >= stale_after_s
            ):
                state = ClockAlignmentState.STALE
                if self._transform.usable:
                    offset_state = OffsetAlignmentState.HOLDOVER
                    drift_state = DriftAlignmentState.HOLDOVER
            holdover = state in (
                ClockAlignmentState.DEGRADED,
                ClockAlignmentState.STALE,
            )
            return replace(
                snapshot,
                state=state,
                offset_state=offset_state,
                drift_state=drift_state,
                uncertainty_us=(
                    self._holdover_uncertainty_locked(now_monotonic)
                    if holdover
                    else snapshot.uncertainty_us
                ),
                model_age_s=model_age_s,
                holdover_age_s=model_age_s if holdover else 0.0,
                drift_fit_pending=self._drift_worker.pending,
            )

    def path_stats(self):
        with self._lock:
            transform = self._transform
            samples = self._window.path_samples
            uncertainty_us = self._holdover_uncertainty_locked(time.monotonic())
        rtts = [float(sample.rtt_us) for sample in samples]
        device_to_monitor = []
        monitor_to_device = []
        one_way_times = []
        if transform.usable and uncertainty_us <= self.MAX_MODEL_UNCERTAINTY_US:
            for sample in samples:
                upload_us = sample.target_upper_us - transform.map_us(
                    sample.source_upper_us
                )
                download_us = transform.map_us(
                    sample.source_lower_us
                ) - sample.target_lower_us
                if (
                    upload_us >= -2.0
                    and download_us >= -2.0
                    and abs((upload_us + download_us) - sample.rtt_us) <= 2.0
                ):
                    device_to_monitor.append(max(0.0, upload_us))
                    monitor_to_device.append(max(0.0, download_us))
                    one_way_times.append(sample.received_monotonic)

        def stats(values, sample_times):
            if not values:
                return {
                    "samples": 0,
                    "latest": 0,
                    "min": 0,
                    "p50": 0,
                    "p95": 0,
                    "age_ms": None,
                }
            return {
                "samples": len(values),
                "latest": int(values[-1]),
                "min": int(min(values)),
                "p50": int(ClockObservationWindow.percentile(values, 50.0)),
                "p95": int(ClockObservationWindow.percentile(values, 95.0)),
                "age_ms": max(0.0, (time.monotonic() - sample_times[-1]) * 1000.0),
            }

        path_times = [sample.received_monotonic for sample in samples]
        return {
            "upload": stats(device_to_monitor, one_way_times),
            "download": stats(monitor_to_device, one_way_times),
            "rtt": stats(rtts, path_times),
        }

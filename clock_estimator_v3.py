from collections import deque
from dataclasses import dataclass, replace
import math
import threading
import time

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
class _ProjectedInterval:
    lower_us: float
    upper_us: float
    rtt_us: float
    source_mid_us: float


class AffineClockEstimator:
    STRATEGY = ClockEstimatorStrategy.V3
    MODEL_NAME = "robust_affine_interval_v3"
    WINDOW_SECONDS = 120
    WINDOW_US = 120_000_000
    DELAY_FLOOR_WINDOW_US = 30_000_000
    HARD_MAX_RAW_SAMPLES = 4096
    BUCKET_US = 2_000_000
    REPRESENTATIVES_PER_BUCKET = 3
    MAX_REPRESENTATIVES = 180
    DRIFT_UPDATE_US = 1_000_000
    MIN_LOCK_REPRESENTATIVES = 8
    MIN_LOCK_SPAN_US = 15_000_000
    LOCK_CONFIRM_UPDATES = 3
    MAX_DRIFT_PPB = 500_000.0
    MIN_DRIFT_UNCERTAINTY_PPB = 50.0
    MIN_CONSENSUS_SAMPLES = 4
    MIN_CONSENSUS_RATIO = 0.80
    CLOCK_JUMP_CONSECUTIVE_SAMPLES = 5
    CLOCK_ROLLBACK_RESET_US = 1_000_000
    MAX_SAMPLE_RTT_US = 60_000_000
    MAX_MODEL_UNCERTAINTY_US = 5_000.0
    MAX_DRIFT_CHANGE_PPB_PER_S = 5_000.0
    MAX_MAPPING_STEP_US = 500.0
    DRIFT_SMOOTHING_TIME_S = 10.0
    OFFSET_SMOOTHING_TIME_S = 4.0
    HOLDOVER_MIN_GROWTH_US_PER_S = 50.0

    def __init__(self, *, initial_epoch=1, background_drift=True):
        del background_drift
        self._lock = threading.RLock()
        self._samples = deque()
        self._path_samples = deque()
        self._epoch = max(1, int(initial_epoch))
        self._revision = 0
        self._transform = ClockTransform(epoch=self._epoch)
        self._snapshot = ClockAlignmentSnapshot(
            strategy=self.STRATEGY,
            model_name=self.MODEL_NAME,
            window_s=self.WINDOW_SECONDS,
            epoch=self._epoch,
        )
        self._candidate_drift_ppb = 0.0
        self._drift_uncertainty_ppb = self.MAX_DRIFT_PPB
        self._drift_fit_valid = False
        self._last_drift_fit_source_us = None
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
            return tuple(self._samples)

    @property
    def transform(self):
        with self._lock:
            return self._transform

    @property
    def last_sample_result(self):
        with self._lock:
            return self._last_sample_result

    def close(self):
        pass

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return math.inf
        ordered = sorted(values)
        index = max(
            0,
            min(
                len(ordered) - 1,
                int(math.ceil(len(ordered) * float(percentile) / 100.0) - 1),
            ),
        )
        return float(ordered[index])

    @staticmethod
    def _median(values):
        if not values:
            return 0.0
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[middle])
        return (float(ordered[middle - 1]) + float(ordered[middle])) * 0.5

    @classmethod
    def _valid(cls, sample):
        return (
            sample.source_lower_us > 0
            and sample.target_lower_us > 0
            and sample.source_upper_us > 0
            and sample.target_upper_us > 0
            and 0 <= sample.rtt_us <= cls.MAX_SAMPLE_RTT_US
        )

    def _reset_locked(self, reason="reset"):
        self._samples.clear()
        self._path_samples.clear()
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
        self._candidate_drift_ppb = 0.0
        self._drift_uncertainty_ppb = self.MAX_DRIFT_PPB
        self._drift_fit_valid = False
        self._last_drift_fit_source_us = None
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

    def _append_path_sample_locked(self, sample):
        self._path_samples.append(sample)
        cutoff_us = sample.source_mid_us - self.WINDOW_US
        retained = [
            item for item in self._path_samples if item.source_mid_us >= cutoff_us
        ]
        self._path_samples = deque(retained[-self.HARD_MAX_RAW_SAMPLES :])

    def _append_model_sample_locked(self, sample):
        self._samples.append(sample)
        cutoff_us = sample.source_mid_us - self.WINDOW_US
        retained = [
            item for item in self._samples if item.source_mid_us >= cutoff_us
        ]
        self._samples = deque(retained[-self.HARD_MAX_RAW_SAMPLES :])
        self._last_source_mid_us = max(item.source_mid_us for item in self._samples)
        self._last_target_mid_us = max(item.target_mid_us for item in self._samples)
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

            if self._transform.usable and not self._sample_matches_transform_locked(
                sample
            ):
                self._consecutive_incompatible += 1
                self._incompatible_tail.append(sample)
                self._model_outlier_count += 1
                if (
                    self._consecutive_incompatible
                    < self.CLOCK_JUMP_CONSECUTIVE_SAMPLES
                ):
                    self._append_path_sample_locked(sample)
                    path_rtts = [float(item.rtt_us) for item in self._path_samples]
                    self._snapshot = replace(
                        self._snapshot,
                        rejected_count=max(
                            self._snapshot.rejected_count,
                            self._model_outlier_count,
                        ),
                        minimum_rtt_us=min(path_rtts),
                        latest_rtt_us=path_rtts[-1],
                        rtt_p50_us=self._percentile(path_rtts, 50.0),
                        rtt_p95_us=self._percentile(path_rtts, 95.0),
                        updated_monotonic=sample.received_monotonic,
                    )
                    self._last_sample_result = "rtt_only"
                    return True

                restart_samples = tuple(self._incompatible_tail)
                self._reset_locked("five consecutive incompatible samples")
                for restart_sample in restart_samples:
                    self._append_path_sample_locked(restart_sample)
                    self._append_model_sample_locked(restart_sample)
            else:
                self._consecutive_incompatible = 0
                self._incompatible_tail.clear()
                self._append_path_sample_locked(sample)
                self._append_model_sample_locked(sample)

            newest_source_us = max(item.source_mid_us for item in self._samples)
            drift_due = (
                self._last_drift_fit_source_us is None
                or newest_source_us - self._last_drift_fit_source_us >= self.DRIFT_UPDATE_US
            )
            if drift_due:
                self._fit_drift_locked()
                self._last_drift_fit_source_us = newest_source_us
            model_updated = self._fit_offset_locked(drift_due)
            self._last_sample_result = (
                "model_updated" if model_updated else "clock_candidate"
            )
        return True

    def _delay_floor_locked(self):
        if not self._samples:
            return math.inf
        newest_source_us = self._samples[-1].source_mid_us
        recent_rtts = [
            float(item.rtt_us)
            for item in self._samples
            if item.source_mid_us >= newest_source_us - self.DELAY_FLOOR_WINDOW_US
        ]
        return self._percentile(recent_rtts, 10.0)

    def _candidate_samples_locked(self):
        delay_floor_us = self._delay_floor_locked()
        if not math.isfinite(delay_floor_us):
            return [], delay_floor_us
        limit_us = max(3.0 * delay_floor_us, delay_floor_us + 10_000.0)
        return (
            [item for item in self._samples if item.rtt_us <= limit_us],
            delay_floor_us,
        )

    def representatives(self):
        with self._lock:
            return tuple(self._representatives_locked())

    def _representatives_locked(self):
        candidates, _delay_floor_us = self._candidate_samples_locked()
        buckets = {}
        for sample in candidates:
            bucket = int(sample.source_mid_us // self.BUCKET_US)
            bucket_samples = buckets.setdefault(bucket, [])
            bucket_samples.append(sample)
            bucket_samples.sort(key=lambda item: item.rtt_us)
            del bucket_samples[self.REPRESENTATIVES_PER_BUCKET :]
        representatives = [
            sample
            for bucket_samples in buckets.values()
            for sample in bucket_samples
        ]
        return sorted(representatives, key=lambda item: item.source_mid_us)[
            -self.MAX_REPRESENTATIVES :
        ]

    @staticmethod
    def _weighted_group_fit(observations, weights):
        group_stats = {}
        for (x_value, y_value, group), weight in zip(observations, weights):
            sum_w, sum_x, sum_y = group_stats.get(group, (0.0, 0.0, 0.0))
            group_stats[group] = (
                sum_w + weight,
                sum_x + weight * x_value,
                sum_y + weight * y_value,
            )
        means = {}
        for group, (sum_w, sum_x, sum_y) in group_stats.items():
            if sum_w <= 0.0:
                return 0.0, {}
            means[group] = (sum_x / sum_w, sum_y / sum_w)
        numerator = 0.0
        denominator = 0.0
        for (x_value, y_value, group), weight in zip(observations, weights):
            mean_x, mean_y = means[group]
            dx = x_value - mean_x
            numerator += weight * dx * (y_value - mean_y)
            denominator += weight * dx * dx
        slope = 0.0 if denominator <= 0.0 else numerator / denominator
        intercepts = {
            group: mean_y - slope * mean_x
            for group, (mean_x, mean_y) in means.items()
        }
        return slope, intercepts

    def _fit_drift_locked(self):
        reps = self._representatives_locked()
        if len(reps) < 2:
            self._drift_fit_valid = False
            self._drift_uncertainty_ppb = self.MAX_DRIFT_PPB
            return
        delay_floor_us = max(1.0, self._delay_floor_locked())
        anchor_us = reps[0].source_mid_us
        observations = []
        base_weights = []
        for sample in reps:
            x_seconds = (sample.source_mid_us - anchor_us) / 1_000_000.0
            observations.append((x_seconds, sample.upper_offset_us, 0))
            observations.append((x_seconds, sample.lower_offset_us, 1))
            delay_weight = (delay_floor_us / max(delay_floor_us, sample.rtt_us)) ** 2
            base_weights.extend((delay_weight, delay_weight))
        weights = list(base_weights)
        slope_us_per_s = 0.0
        robust_sigma_us = 1.0
        for _iteration in range(8):
            slope_us_per_s, intercepts = self._weighted_group_fit(
                observations, weights
            )
            residuals = [
                y_value - (intercepts[group] + slope_us_per_s * x_value)
                for x_value, y_value, group in observations
            ]
            residual_median = self._median(residuals)
            robust_sigma_us = max(
                1.0,
                1.4826
                * self._median([abs(value - residual_median) for value in residuals]),
            )
            threshold_us = 1.5 * robust_sigma_us
            new_weights = []
            for residual, base_weight in zip(residuals, base_weights):
                huber_weight = (
                    1.0
                    if abs(residual) <= threshold_us
                    else threshold_us / abs(residual)
                )
                new_weights.append(base_weight * huber_weight)
            if (
                max(abs(new - old) for new, old in zip(new_weights, weights))
                < 1.0e-3
            ):
                weights = new_weights
                break
            weights = new_weights
        raw_drift_ppb = slope_us_per_s * 1000.0
        self._drift_fit_valid = abs(raw_drift_ppb) < self.MAX_DRIFT_PPB
        self._candidate_drift_ppb = max(
            -self.MAX_DRIFT_PPB,
            min(self.MAX_DRIFT_PPB, raw_drift_ppb),
        )
        group_means = {}
        for group in (0, 1):
            values = [
                (x_value, weight)
                for (x_value, _y_value, item_group), weight in zip(
                    observations, weights
                )
                if item_group == group
            ]
            sum_w = sum(weight for _x_value, weight in values)
            group_means[group] = (
                0.0
                if sum_w <= 0.0
                else sum(x * weight for x, weight in values) / sum_w
            )
        slope_information = sum(
            weight * (x_value - group_means[group]) ** 2
            for (x_value, _y_value, group), weight in zip(observations, weights)
        )
        standard_error_us_per_s = (
            self.MAX_DRIFT_PPB / 1000.0
            if slope_information <= 0.0
            else robust_sigma_us / math.sqrt(slope_information)
        )
        self._drift_uncertainty_ppb = min(
            self.MAX_DRIFT_PPB,
            max(
                self.MIN_DRIFT_UNCERTAINTY_PPB,
                1.96 * standard_error_us_per_s * 1000.0,
            ),
        )

    def _project_intervals_locked(self, samples, source_anchor_us):
        scale = 1.0 + self._candidate_drift_ppb * 1.0e-9
        intervals = []
        for sample in samples:
            drift_margin_us = (
                abs(source_anchor_us - sample.source_mid_us)
                * self._drift_uncertainty_ppb
                * 1.0e-9
            )
            lower_us = (
                sample.target_lower_us
                + (source_anchor_us - sample.source_lower_us) * scale
                - drift_margin_us
            )
            upper_us = (
                sample.target_upper_us
                + (source_anchor_us - sample.source_upper_us) * scale
                + drift_margin_us
            )
            if lower_us <= upper_us:
                intervals.append(
                    _ProjectedInterval(
                        lower_us, upper_us, float(sample.rtt_us), sample.source_mid_us
                    )
                )
        return intervals

    @staticmethod
    def _strict_intersection(intervals):
        if not intervals:
            return None
        lower_us = max(item.lower_us for item in intervals)
        upper_us = min(item.upper_us for item in intervals)
        return None if lower_us > upper_us else (lower_us, upper_us)

    @staticmethod
    def _maximum_compatible_intervals(intervals):
        if not intervals:
            return []
        events = []
        for index, interval in enumerate(intervals):
            events.append((interval.lower_us, 0, index))
            events.append((interval.upper_us, 1, index))
        active = set()
        best_active = set()
        best_quality = -1.0
        for _coordinate, event_type, index in sorted(events):
            if event_type == 0:
                active.add(index)
                quality = sum(
                    1.0 / (1.0 + intervals[item].rtt_us) for item in active
                )
                if len(active) > len(best_active) or (
                    len(active) == len(best_active) and quality > best_quality
                ):
                    best_active = set(active)
                    best_quality = quality
            else:
                active.discard(index)
        return [intervals[index] for index in sorted(best_active)]

    def _sample_matches_transform_locked(self, sample):
        transform = self._transform
        margin_us = max(transform.uncertainty_us, 1.0)
        lower_offset_us = (
            transform.target_anchor_us - transform.source_anchor_us - margin_us
        )
        upper_offset_us = (
            transform.target_anchor_us - transform.source_anchor_us + margin_us
        )
        scale = 1.0 + transform.drift_ppb * 1.0e-9
        projected_lower_us = (
            sample.target_lower_us
            + (transform.source_anchor_us - sample.source_lower_us) * scale
            - transform.source_anchor_us
        )
        projected_upper_us = (
            sample.target_upper_us
            + (transform.source_anchor_us - sample.source_upper_us) * scale
            - transform.source_anchor_us
        )
        return not (
            projected_upper_us < lower_offset_us
            or projected_lower_us > upper_offset_us
        )

    def _candidate_admitted_locked(self, candidate, now_monotonic):
        if candidate.uncertainty_us > self.MAX_MODEL_UNCERTAINTY_US:
            return False
        if not self._transform.locked:
            return True
        elapsed_s = max(1.0, now_monotonic - self._transform.updated_monotonic)
        if abs(candidate.drift_ppb - self._transform.drift_ppb) > (
            self.MAX_DRIFT_CHANGE_PPB_PER_S * elapsed_s
        ):
            return False
        mapping_step_us = abs(
            candidate.map_us(candidate.source_anchor_us)
            - self._transform.map_us(candidate.source_anchor_us)
        )
        return mapping_step_us <= self.MAX_MAPPING_STEP_US

    def _condition_candidate_locked(self, candidate, now_monotonic):
        if not self._transform.locked:
            return candidate
        elapsed_s = max(1.0, now_monotonic - self._transform.updated_monotonic)
        drift_limit_ppb = self.MAX_DRIFT_CHANGE_PPB_PER_S * elapsed_s
        raw_drift_delta_ppb = candidate.drift_ppb - self._transform.drift_ppb
        raw_mapping_delta_us = (
            candidate.map_us(candidate.source_anchor_us)
            - self._transform.map_us(candidate.source_anchor_us)
        )
        drift_alpha = min(1.0, elapsed_s / self.DRIFT_SMOOTHING_TIME_S)
        offset_alpha = min(1.0, elapsed_s / self.OFFSET_SMOOTHING_TIME_S)
        conditioned_drift_ppb = self._transform.drift_ppb + max(
            -drift_limit_ppb,
            min(drift_limit_ppb, raw_drift_delta_ppb * drift_alpha),
        )
        conditioned_target_us = self._transform.map_us(
            candidate.source_anchor_us
        ) + max(
            -self.MAX_MAPPING_STEP_US,
            min(self.MAX_MAPPING_STEP_US, raw_mapping_delta_us * offset_alpha),
        )
        conditioned_uncertainty_us = max(
            candidate.uncertainty_us,
            abs(candidate.target_anchor_us - conditioned_target_us),
        )
        return replace(
            candidate,
            target_anchor_us=conditioned_target_us,
            drift_ppb=conditioned_drift_ppb,
            uncertainty_us=conditioned_uncertainty_us,
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
        samples = list(self._samples)
        if not samples:
            return False
        candidates, delay_floor_us = self._candidate_samples_locked()
        if not candidates:
            return False
        source_anchor_us = max(item.source_mid_us for item in candidates)
        intervals = self._project_intervals_locked(candidates, source_anchor_us)
        strict_bound = self._strict_intersection(intervals)
        strict = strict_bound is not None
        required = max(
            self.MIN_CONSENSUS_SAMPLES,
            int(math.ceil(len(intervals) * self.MIN_CONSENSUS_RATIO)),
        )
        selected = (
            intervals if strict else self._maximum_compatible_intervals(intervals)
        )
        accepted = len(selected) >= required
        selected_bound = self._strict_intersection(selected) if accepted else None
        if selected_bound is None:
            best = min(candidates, key=lambda item: item.rtt_us)
            scale = 1.0 + self._candidate_drift_ppb * 1.0e-9
            target_anchor_us = best.target_mid_us + (
                source_anchor_us - best.source_mid_us
            ) * scale
            lower_us = target_anchor_us - best.rtt_us * 0.5
            upper_us = target_anchor_us + best.rtt_us * 0.5
        else:
            lower_us, upper_us = selected_bound
            target_anchor_us = (lower_us + upper_us) * 0.5
        uncertainty_us = max(0.5, (upper_us - lower_us) * 0.5)
        reps = self._representatives_locked()
        sample_span_us = max(item.source_mid_us for item in samples) - min(
            item.source_mid_us for item in samples
        )
        representative_span_us = (
            0.0
            if len(reps) < 2
            else reps[-1].source_mid_us - reps[0].source_mid_us
        )
        base_lock_eligible = (
            accepted
            and self._drift_fit_valid
            and len(reps) >= self.MIN_LOCK_REPRESENTATIVES
            and representative_span_us >= self.MIN_LOCK_SPAN_US
            and uncertainty_us <= self.MAX_MODEL_UNCERTAINTY_US
        )
        now_monotonic = time.monotonic()
        candidate_transform = ClockTransform(
            source_anchor_us=source_anchor_us,
            target_anchor_us=target_anchor_us,
            drift_ppb=self._candidate_drift_ppb,
            uncertainty_us=uncertainty_us,
            usable=True,
            locked=True,
            epoch=self._epoch,
        )
        conditioned_candidate = self._condition_candidate_locked(
            candidate_transform, now_monotonic
        )
        admitted = (
            base_lock_eligible
            and conditioned_candidate is not None
            and self._candidate_admitted_locked(
                conditioned_candidate, now_monotonic
            )
        )
        if conditioned_candidate is not None:
            candidate_transform = conditioned_candidate
        previous_state = self._snapshot.state
        model_updated = False
        if drift_updated:
            self._healthy_fit_streak = self._healthy_fit_streak + 1 if admitted else 0
        if previous_state in (
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        ):
            if not drift_updated:
                state = previous_state
            elif not admitted:
                state = ClockAlignmentState.DEGRADED
            elif previous_state == ClockAlignmentState.DEGRADED and (
                self._healthy_fit_streak < self.LOCK_CONFIRM_UPDATES
            ):
                state = ClockAlignmentState.DEGRADED
            else:
                state = ClockAlignmentState.LOCKED
                self._publish_transform_locked(candidate_transform, now_monotonic)
                model_updated = True
        elif base_lock_eligible and admitted and (
            self._healthy_fit_streak >= self.LOCK_CONFIRM_UPDATES
        ):
            state = ClockAlignmentState.LOCKED
            self._publish_transform_locked(candidate_transform, now_monotonic)
            model_updated = True
        elif accepted and len(candidates) >= self.MIN_CONSENSUS_SAMPLES:
            state = ClockAlignmentState.PROVISIONAL
            provisional = replace(candidate_transform, drift_ppb=0.0, locked=False)
            self._publish_transform_locked(provisional, now_monotonic)
            model_updated = True
        else:
            state = ClockAlignmentState.ACQUIRING
        if (
            state in (ClockAlignmentState.DEGRADED, ClockAlignmentState.LOCKED)
            and self._transform.locked
        ):
            display_transform = self._transform
            display_lower_us = (
                display_transform.target_anchor_us - display_transform.uncertainty_us
            )
            display_upper_us = (
                display_transform.target_anchor_us + display_transform.uncertainty_us
            )
        else:
            display_transform = (
                self._transform if self._transform.usable else candidate_transform
            )
            display_lower_us = lower_us
            display_upper_us = upper_us
        path_rtts = [float(item.rtt_us) for item in self._path_samples]
        rejected_count = self._model_outlier_count + max(
            0, len(intervals) - len(selected)
        )
        model_age_s = (
            math.inf
            if self._last_good_monotonic <= 0.0
            else max(0.0, now_monotonic - self._last_good_monotonic)
        )
        holdover_age_s = (
            model_age_s if state == ClockAlignmentState.DEGRADED else 0.0
        )
        offset_state = (
            OffsetAlignmentState.HOLDOVER
            if state == ClockAlignmentState.DEGRADED
            else OffsetAlignmentState.USABLE
            if state in (
                ClockAlignmentState.PROVISIONAL,
                ClockAlignmentState.LOCKED,
            )
            else OffsetAlignmentState.ACQUIRING
        )
        drift_state = (
            DriftAlignmentState.HOLDOVER
            if state == ClockAlignmentState.DEGRADED
            else DriftAlignmentState.LOCKED
            if state == ClockAlignmentState.LOCKED
            else DriftAlignmentState.CANDIDATE
            if self._drift_fit_valid
            else DriftAlignmentState.UNKNOWN
        )
        self._snapshot = ClockAlignmentSnapshot(
            strategy=self.STRATEGY,
            model_name=self.MODEL_NAME,
            window_s=self.WINDOW_SECONDS,
            state=state,
            offset_state=offset_state,
            drift_state=drift_state,
            source_anchor_us=display_transform.source_anchor_us,
            target_anchor_us=display_transform.target_anchor_us,
            offset_us=(
                display_transform.target_anchor_us - display_transform.source_anchor_us
            ),
            offset_lower_us=display_lower_us - display_transform.source_anchor_us,
            offset_upper_us=display_upper_us - display_transform.source_anchor_us,
            uncertainty_us=display_transform.uncertainty_us,
            drift_ppb=display_transform.drift_ppb,
            candidate_drift_ppb=self._candidate_drift_ppb,
            statistical_candidate_drift_ppb=self._candidate_drift_ppb,
            statistical_drift_uncertainty_ppb=self._drift_uncertainty_ppb,
            drift_uncertainty_ppb=self._drift_uncertainty_ppb,
            sample_count=len(samples),
            candidate_count=len(candidates),
            representative_count=len(reps),
            sample_span_us=sample_span_us,
            representative_span_us=representative_span_us,
            rejected_count=rejected_count,
            minimum_rtt_us=min(path_rtts) if path_rtts else math.inf,
            latest_rtt_us=path_rtts[-1] if path_rtts else math.inf,
            rtt_p50_us=self._percentile(path_rtts, 50.0),
            rtt_p95_us=self._percentile(path_rtts, 95.0),
            delay_floor_us=delay_floor_us,
            strict_intersection=strict,
            consensus_accepted=accepted,
            compatible_count=len(selected),
            consensus_required_count=required,
            drift_fit_valid=self._drift_fit_valid,
            healthy_fit_streak=self._healthy_fit_streak,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            model_age_s=model_age_s,
            holdover_age_s=holdover_age_s,
            reset_count=self._reset_count,
            last_reset_reason=self._last_reset_reason,
            epoch=self._epoch,
            revision=self._transform.revision,
            updated_monotonic=now_monotonic,
        )
        return model_updated

    def _holdover_uncertainty_locked(self, now_monotonic):
        if not self._transform.usable or self._last_good_monotonic <= 0.0:
            return self._transform.uncertainty_us
        age_s = max(0.0, now_monotonic - self._last_good_monotonic)
        growth_us_per_s = max(
            self.HOLDOVER_MIN_GROWTH_US_PER_S,
            self._drift_uncertainty_ppb * 1.0e-3,
        )
        return self._transform.uncertainty_us + age_s * growth_us_per_s

    def snapshot(self, stale_after_s=None):
        with self._lock:
            snapshot = self._snapshot
            now_monotonic = time.monotonic()
            sample_age_s = (
                math.inf
                if self._last_reliable_sample_monotonic <= 0.0
                else max(
                    0.0,
                    now_monotonic - self._last_reliable_sample_monotonic,
                )
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
            )

    def path_stats(self):
        with self._lock:
            transform = self._transform
            samples = tuple(self._path_samples)
            uncertainty_us = self._holdover_uncertainty_locked(time.monotonic())
        rtts = [float(sample.rtt_us) for sample in samples]
        device_to_monitor = []
        monitor_to_device = []
        one_way_times = []
        if transform.usable and uncertainty_us <= self.MAX_MODEL_UNCERTAINTY_US:
            for sample in samples:
                upload_us = (
                    sample.target_upper_us - transform.map_us(sample.source_upper_us)
                )
                download_us = (
                    transform.map_us(sample.source_lower_us) - sample.target_lower_us
                )
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
                "p50": int(self._percentile(values, 50.0)),
                "p95": int(self._percentile(values, 95.0)),
                "age_ms": max(
                    0.0,
                    (time.monotonic() - sample_times[-1]) * 1000.0,
                ),
            }

        path_times = [sample.received_monotonic for sample in samples]
        return {
            "upload": stats(device_to_monitor, one_way_times),
            "download": stats(monitor_to_device, one_way_times),
            "rtt": stats(rtts, path_times),
        }

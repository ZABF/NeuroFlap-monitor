from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
import math
import threading
import time


class ClockAlignmentState(str, Enum):
    ACQUIRING = "Acquiring"
    PROVISIONAL = "Provisional"
    LOCKED = "Locked"
    DEGRADED = "Degraded"
    STALE = "Stale"


@dataclass(frozen=True)
class ClockTransform:
    source_anchor_us: float = 0.0
    target_anchor_us: float = 0.0
    drift_ppb: float = 0.0
    uncertainty_us: float = math.inf
    usable: bool = False
    locked: bool = False
    revision: int = 0
    updated_monotonic: float = 0.0

    def map_us(self, source_us):
        scale = 1.0 + self.drift_ppb * 1.0e-9
        return self.target_anchor_us + (float(source_us) - self.source_anchor_us) * scale

    def map_ms(self, source_ms):
        return self.map_us(float(source_ms) * 1000.0) / 1000.0


@dataclass(frozen=True)
class FourTimestampSample:
    source_lower_us: int
    target_lower_us: int
    source_upper_us: int
    target_upper_us: int

    @classmethod
    def source_initiated(cls, t1_us, t2_us, t3_us, t4_us):
        # source t1 -> target t2/t3 -> source t4
        return cls(
            source_lower_us=int(t4_us),
            target_lower_us=int(t3_us),
            source_upper_us=int(t1_us),
            target_upper_us=int(t2_us),
        )

    @classmethod
    def target_initiated(cls, t1_us, t2_us, t3_us, t4_us):
        # target t1 -> source t2/t3 -> target t4
        return cls(
            source_lower_us=int(t2_us),
            target_lower_us=int(t1_us),
            source_upper_us=int(t3_us),
            target_upper_us=int(t4_us),
        )

    @property
    def rtt_us(self):
        return (self.target_upper_us - self.target_lower_us) - (
            self.source_upper_us - self.source_lower_us
        )

    @property
    def source_mid_us(self):
        return (self.source_lower_us + self.source_upper_us) * 0.5

    @property
    def target_mid_us(self):
        return (self.target_lower_us + self.target_upper_us) * 0.5

    @property
    def upper_offset_us(self):
        return float(self.target_upper_us - self.source_upper_us)

    @property
    def lower_offset_us(self):
        return float(self.target_lower_us - self.source_lower_us)


@dataclass(frozen=True)
class ClockAlignmentSnapshot:
    state: ClockAlignmentState = ClockAlignmentState.ACQUIRING
    source_anchor_us: float = 0.0
    target_anchor_us: float = 0.0
    offset_us: float = 0.0
    offset_lower_us: float = 0.0
    offset_upper_us: float = 0.0
    uncertainty_us: float = math.inf
    drift_ppb: float = 0.0
    drift_uncertainty_ppb: float = math.inf
    sample_count: int = 0
    representative_count: int = 0
    sample_span_us: float = 0.0
    representative_span_us: float = 0.0
    rejected_count: int = 0
    minimum_rtt_us: float = math.inf
    strict_intersection: bool = False
    consensus_accepted: bool = False
    compatible_count: int = 0
    consensus_required_count: int = 0
    drift_fit_valid: bool = False
    healthy_fit_streak: int = 0
    lock_confirm_updates: int = 0
    reset_count: int = 0
    last_reset_reason: str = ""
    revision: int = 0
    updated_monotonic: float = 0.0

    @property
    def usable(self):
        return self.state in (
            ClockAlignmentState.PROVISIONAL,
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        )

    def to_metadata(self, target_epoch_offset_us=0.0, updated_unix_us=""):
        finite = lambda value: "" if not math.isfinite(value) else value
        has_samples = self.sample_count > 0
        return {
            "clock_model": "rolling_affine_interval_v2",
            "clock_state": self.state.value,
            "clock_source_anchor_us": (
                int(self.source_anchor_us) if has_samples else ""
            ),
            "clock_target_anchor_unix_us": (
                int(self.target_anchor_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_offset_us": (
                finite(self.offset_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_offset_lower_us": (
                finite(self.offset_lower_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_offset_upper_us": (
                finite(self.offset_upper_us + target_epoch_offset_us)
                if has_samples
                else ""
            ),
            "clock_uncertainty_us": finite(self.uncertainty_us),
            "clock_drift_ppb": finite(self.drift_ppb),
            "clock_drift_uncertainty_ppb": finite(self.drift_uncertainty_ppb),
            "clock_window_s": 120,
            "clock_sample_count": self.sample_count,
            "clock_representative_count": self.representative_count,
            "clock_rejected_count": self.rejected_count,
            "clock_updated_unix_us": updated_unix_us,
        }


@dataclass(frozen=True)
class _ProjectedInterval:
    lower_us: float
    upper_us: float
    rtt_us: float
    source_mid_us: float


class AffineClockEstimator:
    WINDOW_US = 120_000_000
    HARD_MAX_RAW_SAMPLES = 4096
    BUCKET_US = 2_000_000
    MAX_REPRESENTATIVES = 60
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

    def __init__(self):
        self._lock = threading.RLock()
        self._samples = deque()
        self._transform = ClockTransform()
        self._snapshot = ClockAlignmentSnapshot()
        self._revision = 0
        self._drift_ppb = 0.0
        self._drift_uncertainty_ppb = self.MAX_DRIFT_PPB
        self._drift_fit_valid = False
        self._last_drift_fit_source_us = None
        self._healthy_fit_streak = 0
        self._consecutive_incompatible = 0
        self._incompatible_tail = deque(maxlen=self.CLOCK_JUMP_CONSECUTIVE_SAMPLES)
        self._last_source_mid_us = None
        self._last_target_mid_us = None
        self._reset_count = 0
        self._last_reset_reason = "initial"

    @property
    def samples(self):
        with self._lock:
            return tuple(self._samples)

    @property
    def transform(self):
        with self._lock:
            return self._transform

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return 0.0
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
        self._revision += 1
        self._transform = ClockTransform(revision=self._revision)
        self._reset_count += 1
        self._last_reset_reason = str(reason or "reset")
        self._snapshot = ClockAlignmentSnapshot(
            reset_count=self._reset_count,
            last_reset_reason=self._last_reset_reason,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            revision=self._revision,
        )
        self._drift_ppb = 0.0
        self._drift_uncertainty_ppb = self.MAX_DRIFT_PPB
        self._drift_fit_valid = False
        self._last_drift_fit_source_us = None
        self._healthy_fit_streak = 0
        self._consecutive_incompatible = 0
        self._incompatible_tail.clear()
        self._last_source_mid_us = None
        self._last_target_mid_us = None

    def reset(self, reason="reset"):
        with self._lock:
            self._reset_locked(reason)

    def add(self, t1_us, t2_us, t3_us, t4_us):
        if int(t4_us) < int(t1_us) or int(t3_us) < int(t2_us):
            return False
        sample = FourTimestampSample.source_initiated(
            t1_us, t2_us, t3_us, t4_us
        )
        return self._add_sample(sample)

    def add_monitor_initiated(self, t1_us, t2_us, t3_us, t4_us):
        if int(t4_us) < int(t1_us) or int(t3_us) < int(t2_us):
            return False
        sample = FourTimestampSample.target_initiated(
            t1_us, t2_us, t3_us, t4_us
        )
        return self._add_sample(sample)

    def _add_sample(self, sample):
        if not self._valid(sample):
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
                reason = (
                    "source clock rollback"
                    if source_rollback
                    else "target clock rollback"
                )
                self._reset_locked(reason)

            if self._snapshot.usable and not self._sample_matches_snapshot_locked(sample):
                self._consecutive_incompatible += 1
                self._incompatible_tail.append(sample)
            else:
                self._consecutive_incompatible = 0
                self._incompatible_tail.clear()

            if (
                self._consecutive_incompatible
                >= self.CLOCK_JUMP_CONSECUTIVE_SAMPLES
            ):
                restart_samples = tuple(self._incompatible_tail)
                self._reset_locked("five consecutive incompatible samples")
                self._samples.extend(restart_samples)
            else:
                self._samples.append(sample)

            newest_source_us = max(item.source_mid_us for item in self._samples)
            cutoff_us = newest_source_us - self.WINDOW_US
            retained = [
                item for item in self._samples if item.source_mid_us >= cutoff_us
            ]
            if len(retained) > self.HARD_MAX_RAW_SAMPLES:
                retained = retained[-self.HARD_MAX_RAW_SAMPLES :]
            self._samples = deque(retained)
            self._last_source_mid_us = max(
                item.source_mid_us for item in self._samples
            )
            self._last_target_mid_us = max(
                item.target_mid_us for item in self._samples
            )

            drift_due = (
                self._last_drift_fit_source_us is None
                or newest_source_us - self._last_drift_fit_source_us
                >= self.DRIFT_UPDATE_US
            )
            if drift_due:
                self._fit_drift_locked()
                self._last_drift_fit_source_us = newest_source_us
            self._fit_offset_locked(drift_due)
        return True

    def representatives(self):
        with self._lock:
            return tuple(self._representatives_locked())

    def _representatives_locked(self):
        buckets = {}
        for sample in self._samples:
            bucket = int(sample.source_mid_us // self.BUCKET_US)
            previous = buckets.get(bucket)
            if previous is None or sample.rtt_us < previous.rtt_us:
                buckets[bucket] = sample
        return sorted(buckets.values(), key=lambda item: item.source_mid_us)[
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

        anchor_us = reps[0].source_mid_us
        observations = []
        for sample in reps:
            x_seconds = (sample.source_mid_us - anchor_us) / 1_000_000.0
            observations.append((x_seconds, sample.upper_offset_us, 0))
            observations.append((x_seconds, sample.lower_offset_us, 1))

        weights = [1.0] * len(observations)
        slope_us_per_s = 0.0
        intercepts = {}
        residuals = []
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
                * self._median(
                    [abs(value - residual_median) for value in residuals]
                ),
            )
            threshold_us = 1.5 * robust_sigma_us
            new_weights = [
                1.0
                if abs(value) <= threshold_us
                else threshold_us / abs(value)
                for value in residuals
            ]
            if max(
                abs(new - old) for new, old in zip(new_weights, weights)
            ) < 1.0e-3:
                weights = new_weights
                break
            weights = new_weights

        raw_drift_ppb = slope_us_per_s * 1000.0
        self._drift_fit_valid = abs(raw_drift_ppb) < self.MAX_DRIFT_PPB
        self._drift_ppb = max(
            -self.MAX_DRIFT_PPB,
            min(self.MAX_DRIFT_PPB, raw_drift_ppb),
        )

        group_means = {}
        for group in (0, 1):
            group_values = [
                (x_value, weight)
                for (x_value, _y_value, item_group), weight in zip(
                    observations, weights
                )
                if item_group == group
            ]
            sum_w = sum(weight for _x_value, weight in group_values)
            mean_x = (
                0.0
                if sum_w <= 0.0
                else sum(x_value * weight for x_value, weight in group_values)
                / sum_w
            )
            group_means[group] = mean_x
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

    def _project_intervals_locked(self, source_anchor_us):
        scale = 1.0 + self._drift_ppb * 1.0e-9
        intervals = []
        for sample in self._samples:
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
                        lower_us=lower_us,
                        upper_us=upper_us,
                        rtt_us=float(sample.rtt_us),
                        source_mid_us=sample.source_mid_us,
                    )
                )
        return intervals

    @staticmethod
    def _strict_intersection(intervals):
        if not intervals:
            return None
        lower_us = max(item.lower_us for item in intervals)
        upper_us = min(item.upper_us for item in intervals)
        if lower_us > upper_us:
            return None
        return lower_us, upper_us

    @staticmethod
    def _maximum_compatible_intervals(intervals):
        if not intervals:
            return []
        starts = {}
        ends = {}
        for index, interval in enumerate(intervals):
            starts.setdefault(interval.lower_us, []).append(index)
            ends.setdefault(interval.upper_us, []).append(index)

        active = set()
        active_quality = 0.0
        best_point = None
        best_score = (-1, -1.0)
        for coordinate in sorted(set(starts) | set(ends)):
            for index in starts.get(coordinate, ()):
                active.add(index)
                active_quality += 1.0 / (1.0 + intervals[index].rtt_us)
            score = (len(active), active_quality)
            if score > best_score:
                best_score = score
                best_point = coordinate
            for index in ends.get(coordinate, ()):
                if index in active:
                    active.remove(index)
                    active_quality -= 1.0 / (1.0 + intervals[index].rtt_us)

        if best_point is None:
            return []
        return [
            item
            for item in intervals
            if item.lower_us <= best_point <= item.upper_us
        ]

    def _sample_matches_snapshot_locked(self, sample):
        snapshot = self._snapshot
        if not snapshot.usable:
            return True
        scale = 1.0 + snapshot.drift_ppb * 1.0e-9
        margin_us = (
            abs(snapshot.source_anchor_us - sample.source_mid_us)
            * snapshot.drift_uncertainty_ppb
            * 1.0e-9
        )
        lower_us = (
            sample.target_lower_us
            + (snapshot.source_anchor_us - sample.source_lower_us) * scale
            - margin_us
        ) - snapshot.source_anchor_us
        upper_us = (
            sample.target_upper_us
            + (snapshot.source_anchor_us - sample.source_upper_us) * scale
            + margin_us
        ) - snapshot.source_anchor_us
        return not (
            upper_us < snapshot.offset_lower_us
            or lower_us > snapshot.offset_upper_us
        )

    def _fit_offset_locked(self, drift_updated):
        samples = list(self._samples)
        if not samples:
            return
        source_anchor_us = max(item.source_mid_us for item in samples)
        intervals = self._project_intervals_locked(source_anchor_us)
        strict_bound = self._strict_intersection(intervals)
        strict = strict_bound is not None
        accepted = bool(strict_bound)
        selected = intervals
        required = max(
            self.MIN_CONSENSUS_SAMPLES,
            int(math.ceil(len(intervals) * self.MIN_CONSENSUS_RATIO)),
        )
        if not strict:
            selected = self._maximum_compatible_intervals(intervals)
            accepted = len(selected) >= required

        selected_bound = self._strict_intersection(selected)
        if selected_bound is None:
            best = min(samples, key=lambda item: item.rtt_us)
            target_anchor_us = best.target_mid_us + (
                source_anchor_us - best.source_mid_us
            ) * (1.0 + self._drift_ppb * 1.0e-9)
            lower_us = target_anchor_us - best.rtt_us * 0.5
            upper_us = target_anchor_us + best.rtt_us * 0.5
        else:
            lower_us, upper_us = selected_bound
            target_anchor_us = (lower_us + upper_us) * 0.5

        uncertainty_us = max(0.5, (upper_us - lower_us) * 0.5)
        reps = self._representatives_locked()
        sample_span_us = (
            max(item.source_mid_us for item in samples)
            - min(item.source_mid_us for item in samples)
        )
        representative_span_us = (
            0.0
            if len(reps) < 2
            else reps[-1].source_mid_us - reps[0].source_mid_us
        )
        lock_eligible = (
            accepted
            and strict
            and self._drift_fit_valid
            and len(reps) >= self.MIN_LOCK_REPRESENTATIVES
            and representative_span_us >= self.MIN_LOCK_SPAN_US
            and abs(self._drift_ppb) < self.MAX_DRIFT_PPB
        )

        previous_state = self._snapshot.state
        if drift_updated:
            self._healthy_fit_streak = (
                self._healthy_fit_streak + 1 if lock_eligible else 0
            )
        if not accepted:
            state = ClockAlignmentState.ACQUIRING
        elif not strict and previous_state in (
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        ):
            state = ClockAlignmentState.DEGRADED
        elif not strict:
            state = ClockAlignmentState.ACQUIRING
        elif (
            previous_state == ClockAlignmentState.LOCKED
            and lock_eligible
        ):
            state = ClockAlignmentState.LOCKED
        elif (
            lock_eligible
            and self._healthy_fit_streak >= self.LOCK_CONFIRM_UPDATES
        ):
            state = ClockAlignmentState.LOCKED
        elif strict and len(samples) >= self.MIN_CONSENSUS_SAMPLES:
            state = ClockAlignmentState.PROVISIONAL
        else:
            state = ClockAlignmentState.ACQUIRING

        now_monotonic = time.monotonic()
        self._revision += 1
        rejected_count = max(0, len(intervals) - len(selected))
        minimum_rtt_us = min(float(item.rtt_us) for item in samples)
        locked = state in (
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        )
        usable = state in (
            ClockAlignmentState.PROVISIONAL,
            ClockAlignmentState.LOCKED,
            ClockAlignmentState.DEGRADED,
        )
        published_drift_ppb = self._drift_ppb if locked else 0.0
        self._transform = ClockTransform(
            source_anchor_us=source_anchor_us,
            target_anchor_us=target_anchor_us,
            drift_ppb=published_drift_ppb,
            uncertainty_us=uncertainty_us,
            usable=usable,
            locked=locked,
            revision=self._revision,
            updated_monotonic=now_monotonic,
        )
        self._snapshot = ClockAlignmentSnapshot(
            state=state,
            source_anchor_us=source_anchor_us,
            target_anchor_us=target_anchor_us,
            offset_us=target_anchor_us - source_anchor_us,
            offset_lower_us=lower_us - source_anchor_us,
            offset_upper_us=upper_us - source_anchor_us,
            uncertainty_us=uncertainty_us,
            drift_ppb=published_drift_ppb,
            drift_uncertainty_ppb=self._drift_uncertainty_ppb,
            sample_count=len(samples),
            representative_count=len(reps),
            sample_span_us=sample_span_us,
            representative_span_us=representative_span_us,
            rejected_count=rejected_count,
            minimum_rtt_us=minimum_rtt_us,
            strict_intersection=strict,
            consensus_accepted=accepted,
            compatible_count=len(selected),
            consensus_required_count=required,
            drift_fit_valid=self._drift_fit_valid,
            healthy_fit_streak=self._healthy_fit_streak,
            lock_confirm_updates=self.LOCK_CONFIRM_UPDATES,
            reset_count=self._reset_count,
            last_reset_reason=self._last_reset_reason,
            revision=self._revision,
            updated_monotonic=now_monotonic,
        )

    def snapshot(self, stale_after_s=None):
        with self._lock:
            snapshot = self._snapshot
        if (
            stale_after_s is not None
            and snapshot.updated_monotonic > 0.0
            and time.monotonic() - snapshot.updated_monotonic >= stale_after_s
        ):
            return replace(snapshot, state=ClockAlignmentState.STALE)
        return snapshot

    def path_stats(self):
        with self._lock:
            transform = self._transform
            samples = tuple(self._samples)
        uploads = []
        downloads = []
        rtts = []
        for sample in samples:
            uploads.append(
                sample.target_upper_us
                - transform.map_us(sample.source_upper_us)
            )
            downloads.append(
                transform.map_us(sample.source_lower_us)
                - sample.target_lower_us
            )
            rtts.append(float(sample.rtt_us))

        def stats(values):
            nonnegative = [max(0.0, value) for value in values]
            if not nonnegative:
                return {"samples": 0, "latest": 0, "min": 0, "p50": 0, "p95": 0}
            return {
                "samples": len(nonnegative),
                "latest": int(nonnegative[-1]),
                "min": int(min(nonnegative)),
                "p50": int(self._percentile(nonnegative, 50.0)),
                "p95": int(self._percentile(nonnegative, 95.0)),
            }

        return {
            "upload": stats(uploads),
            "download": stats(downloads),
            "rtt": stats(rtts),
        }

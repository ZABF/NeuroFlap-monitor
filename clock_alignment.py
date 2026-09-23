from array import array
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
import math
import statistics
import threading
import time

from clock_observation import FourTimestampSample
from clock_types import ClockTransform
from clock_types import (
    ClockAlignmentSnapshot,
    ClockAlignmentState,
    ClockEstimatorStrategy,
    DriftAlignmentState,
    OffsetAlignmentState,
)
from clock_v3_fit import fit_v3_statistical_drift
from host_clock import (
    HOST_CLOCK_MONOTONIC,
    HOST_CLOCK_RAW,
    normalize_host_clock,
)


NEUROFLAP_CLOCK_DOMAIN = "neuroflap"
FT_CLOCK_DOMAIN = "ft"


class AlignmentMode(str, Enum):
    REALTIME = "realtime"
    CALIBRATED = "calibrated"

    @classmethod
    def parse(cls, value):
        if isinstance(value, cls):
            return value
        return cls.CALIBRATED if str(value).lower() == cls.CALIBRATED.value else cls.REALTIME


@dataclass(frozen=True)
class AlignmentQuality:
    sample_count: int = 0
    representative_count: int = 0
    span_us: int = 0
    residual_us: float = math.inf
    uncertainty_us: float = math.inf
    drift_uncertainty_ppb: float = math.inf
    rating: str = "Unavailable"
    message: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AlignmentModel:
    domain: str
    session: int
    mode: AlignmentMode
    transform: ClockTransform
    quality: AlignmentQuality
    fitted_monotonic_us: int = 0
    host_clock: str = HOST_CLOCK_RAW

    def to_dict(self, target_epoch_offset_us=0):
        target_anchor_us = self.transform.target_anchor_us + float(target_epoch_offset_us)
        return {
            "domain": self.domain,
            "session": self.session,
            "mode": self.mode.value,
            "host_clock": self.host_clock,
            "source_anchor_us": int(round(self.transform.source_anchor_us)),
            "target_anchor_unix_us": int(round(target_anchor_us)),
            "offset_us": target_anchor_us - self.transform.source_anchor_us,
            "drift_ppm": self.transform.drift_ppb / 1000.0,
            "uncertainty_us": self.transform.uncertainty_us,
            "usable": bool(self.transform.usable),
            "locked": bool(self.transform.locked),
            "revision": int(self.transform.revision),
            "fitted_monotonic_us": int(self.fitted_monotonic_us),
            **self.quality.to_dict(),
        }


@dataclass(frozen=True)
class NeuroFlapObservation:
    session: int
    sequence: int
    t1_us: int
    t2_us: int
    t3_us: int
    t4_us: int
    t1_monotonic_us: int = 0
    t4_monotonic_us: int = 0


@dataclass(frozen=True)
class FtObservation:
    session: int
    source_us: int
    receive_us: int
    receive_monotonic_us: int = 0


class ClockObservationStore:
    """Packed clock evidence retained for the lifetime of one capture."""

    def __init__(self):
        self._lock = threading.RLock()
        self._nf_revision = 0
        self._ft_revision = 0
        self._nf_session = array("I")
        self._nf_sequence = array("I")
        self._nf_t1 = array("Q")
        self._nf_t2 = array("Q")
        self._nf_t3 = array("Q")
        self._nf_t4 = array("Q")
        self._nf_t1_monotonic = array("Q")
        self._nf_t4_monotonic = array("Q")
        self._ft_session = array("I")
        self._ft_source = array("Q")
        self._ft_receive = array("Q")
        self._ft_receive_monotonic = array("Q")

    def clear(self):
        with self._lock:
            for values in (
                self._nf_session,
                self._nf_sequence,
                self._nf_t1,
                self._nf_t2,
                self._nf_t3,
                self._nf_t4,
                self._nf_t1_monotonic,
                self._nf_t4_monotonic,
                self._ft_session,
                self._ft_source,
                self._ft_receive,
                self._ft_receive_monotonic,
            ):
                del values[:]
            self._nf_revision += 1
            self._ft_revision += 1

    def revision(self, domain):
        with self._lock:
            return (
                self._nf_revision
                if domain == NEUROFLAP_CLOCK_DOMAIN
                else self._ft_revision
            )

    def add_neuroflap(
        self,
        session,
        sequence,
        t1_us,
        t2_us,
        t3_us,
        t4_us,
        t1_monotonic_us=None,
        t4_monotonic_us=None,
    ):
        values = tuple(int(value) for value in (t1_us, t2_us, t3_us, t4_us))
        if min(values) <= 0 or values[3] < values[0] or values[2] < values[1]:
            return False
        t1_monotonic_us = int(t1_monotonic_us or values[0])
        t4_monotonic_us = int(t4_monotonic_us or values[3])
        if t1_monotonic_us <= 0 or t4_monotonic_us < t1_monotonic_us:
            return False
        with self._lock:
            self._nf_session.append(int(session) & 0xFFFFFFFF)
            self._nf_sequence.append(int(sequence) & 0xFFFFFFFF)
            self._nf_t1.append(values[0])
            self._nf_t2.append(values[1])
            self._nf_t3.append(values[2])
            self._nf_t4.append(values[3])
            self._nf_t1_monotonic.append(t1_monotonic_us)
            self._nf_t4_monotonic.append(t4_monotonic_us)
            self._nf_revision += 1
        return True

    def add_ft(self, session, source_us, receive_us, receive_monotonic_us=None):
        source_us = int(source_us)
        receive_us = int(receive_us)
        if source_us < 0 or receive_us <= 0:
            return False
        receive_monotonic_us = int(receive_monotonic_us or receive_us)
        if receive_monotonic_us <= 0:
            return False
        with self._lock:
            self._ft_session.append(int(session) & 0xFFFFFFFF)
            self._ft_source.append(source_us)
            self._ft_receive.append(receive_us)
            self._ft_receive_monotonic.append(receive_monotonic_us)
            self._ft_revision += 1
        return True

    def neuroflap_snapshot(self, session):
        session = int(session)
        with self._lock:
            return tuple(
                NeuroFlapObservation(
                    int(self._nf_session[index]),
                    int(self._nf_sequence[index]),
                    int(self._nf_t1[index]),
                    int(self._nf_t2[index]),
                    int(self._nf_t3[index]),
                    int(self._nf_t4[index]),
                    int(self._nf_t1_monotonic[index]),
                    int(self._nf_t4_monotonic[index]),
                )
                for index in range(len(self._nf_session))
                if int(self._nf_session[index]) == session
            )

    def ft_snapshot(self, session):
        session = int(session)
        with self._lock:
            return tuple(
                FtObservation(
                    int(self._ft_session[index]),
                    int(self._ft_source[index]),
                    int(self._ft_receive[index]),
                    int(self._ft_receive_monotonic[index]),
                )
                for index in range(len(self._ft_session))
                if int(self._ft_session[index]) == session
            )

    def export(self):
        with self._lock:
            neuroflap = [
                {
                    "domain": NEUROFLAP_CLOCK_DOMAIN,
                    "session": int(self._nf_session[index]),
                    "sequence": int(self._nf_sequence[index]),
                    "t1_us": int(self._nf_t1[index]),
                    "t2_us": int(self._nf_t2[index]),
                    "t3_us": int(self._nf_t3[index]),
                    "t4_us": int(self._nf_t4[index]),
                    "t1_monotonic_us": int(self._nf_t1_monotonic[index]),
                    "t4_monotonic_us": int(self._nf_t4_monotonic[index]),
                }
                for index in range(len(self._nf_session))
            ]
            ft = [
                {
                    "domain": FT_CLOCK_DOMAIN,
                    "session": int(self._ft_session[index]),
                    "source_us": int(self._ft_source[index]),
                    "receive_us": int(self._ft_receive[index]),
                    "receive_monotonic_us": int(
                        self._ft_receive_monotonic[index]
                    ),
                }
                for index in range(len(self._ft_session))
            ]
        return neuroflap + ft


class RealtimeOffsetTracker:
    """Bounded offset-only tracker using the lowest-delay recent observation."""

    WINDOW_US = 5_000_000
    PUBLISH_INTERVAL_US = 1_000_000

    def __init__(self):
        self._samples = deque()
        self._last_publish_us = 0
        self._revision = 0
        self._session = None

    def clear(self):
        self._samples.clear()
        self._last_publish_us = 0
        self._session = None

    def add(self, source_us, target_us, delay_us, session, now_us=None):
        source_us = float(source_us)
        target_us = float(target_us)
        delay_us = max(0.0, float(delay_us))
        now_us = int(now_us or time.monotonic_ns() // 1000)
        session = int(session)
        if self._session != session:
            self.clear()
            self._session = session
        self._samples.append((source_us, target_us, delay_us))
        cutoff = source_us - self.WINDOW_US
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if now_us - self._last_publish_us < self.PUBLISH_INTERVAL_US:
            return None
        self._last_publish_us = now_us
        best = min(self._samples, key=lambda item: item[2])
        self._revision += 1
        return ClockTransform(
            source_anchor_us=best[0],
            target_anchor_us=best[1],
            drift_ppb=0.0,
            uncertainty_us=max(1.0, min(5_000.0, best[2] * 0.5)),
            usable=True,
            locked=False,
            epoch=session,
            revision=self._revision,
            updated_monotonic=time.monotonic(),
        )


class OffsetOnlyClockEstimator:
    """NFv4 estimator facade with O(1) ingestion and no online drift fit."""

    MIN_LOCK_REPRESENTATIVES = 1
    MIN_LOCK_SPAN_US = 0
    LOCK_CONFIRM_UPDATES = 1
    MAX_MODEL_UNCERTAINTY_US = 5_000.0
    MAX_SAMPLE_RTT_US = 60_000_000
    WINDOW_US = RealtimeOffsetTracker.WINDOW_US

    def __init__(self, initial_epoch=1):
        self._lock = threading.RLock()
        self._epoch = max(1, int(initial_epoch))
        self._samples = deque()
        self._transform = ClockTransform(epoch=self._epoch)
        self._revision = 0
        self._last_sample_result = "none"
        self._last_source_mid_us = None
        self._last_reset_reason = "initial"
        self._reset_count = 0

    @property
    def strategy(self):
        return ClockEstimatorStrategy.V4

    @property
    def epoch(self):
        with self._lock:
            return self._epoch

    @property
    def transform(self):
        with self._lock:
            return self._transform

    @property
    def last_sample_result(self):
        with self._lock:
            return self._last_sample_result

    @property
    def samples(self):
        with self._lock:
            return tuple(self._samples)

    def switch_strategy(self, _strategy):
        return False

    def restart_estimation(self, reason="estimation restarted"):
        self.reset(reason)

    def reset(self, reason="reset"):
        with self._lock:
            self._epoch += 1
            self._samples.clear()
            self._revision += 1
            self._transform = ClockTransform(
                epoch=self._epoch,
                revision=self._revision,
            )
            self._last_source_mid_us = None
            self._last_sample_result = "epoch_reset"
            self._last_reset_reason = str(reason or "reset")
            self._reset_count += 1

    def add(self, t1_us, t2_us, t3_us, t4_us):
        return self._add_sample(
            FourTimestampSample.source_initiated(t1_us, t2_us, t3_us, t4_us)
        )

    def add_monitor_initiated(self, t1_us, t2_us, t3_us, t4_us):
        return self._add_sample(
            FourTimestampSample.target_initiated(t1_us, t2_us, t3_us, t4_us)
        )

    def _add_sample(self, sample):
        if (
            sample.source_lower_us <= 0
            or sample.target_lower_us <= 0
            or sample.source_upper_us <= 0
            or sample.target_upper_us <= 0
            or sample.rtt_us < 0
            or sample.rtt_us > self.MAX_SAMPLE_RTT_US
        ):
            with self._lock:
                self._last_sample_result = "invalid"
            return False
        with self._lock:
            if (
                self._last_source_mid_us is not None
                and sample.source_mid_us < self._last_source_mid_us - 200_000
            ):
                self.reset("source clock rollback")
            self._last_source_mid_us = sample.source_mid_us
            self._samples.append(sample)
            cutoff = sample.source_mid_us - self.WINDOW_US
            while self._samples and self._samples[0].source_mid_us < cutoff:
                self._samples.popleft()
            best = min(self._samples, key=lambda item: item.rtt_us)
            self._revision += 1
            self._transform = ClockTransform(
                source_anchor_us=best.source_mid_us,
                target_anchor_us=best.target_mid_us,
                drift_ppb=0.0,
                uncertainty_us=max(1.0, best.rtt_us * 0.5),
                usable=True,
                locked=False,
                epoch=self._epoch,
                revision=self._revision,
                updated_monotonic=time.monotonic(),
            )
            self._last_sample_result = "model_updated"
        return True

    def snapshot(self, stale_after_s=None):
        with self._lock:
            samples = tuple(self._samples)
            transform = self._transform
            reset_count = self._reset_count
            reset_reason = self._last_reset_reason
        if not samples:
            return ClockAlignmentSnapshot(
                strategy=self.strategy,
                model_name="rolling_min_rtt_offset_v1",
                window_s=5,
                epoch=self._epoch,
                revision=transform.revision,
                reset_count=reset_count,
                last_reset_reason=reset_reason,
            )
        age_s = max(0.0, time.monotonic() - transform.updated_monotonic)
        stale = stale_after_s is not None and age_s >= float(stale_after_s)
        rtts = [float(sample.rtt_us) for sample in samples]
        source_times = [sample.source_mid_us for sample in samples]
        offset_us = transform.target_anchor_us - transform.source_anchor_us
        return ClockAlignmentSnapshot(
            strategy=self.strategy,
            model_name="rolling_min_rtt_offset_v1",
            window_s=5,
            state=(
                ClockAlignmentState.STALE
                if stale
                else ClockAlignmentState.PROVISIONAL
            ),
            offset_state=(
                OffsetAlignmentState.HOLDOVER
                if stale
                else OffsetAlignmentState.USABLE
            ),
            drift_state=DriftAlignmentState.UNKNOWN,
            source_anchor_us=transform.source_anchor_us,
            target_anchor_us=transform.target_anchor_us,
            offset_us=offset_us,
            offset_lower_us=offset_us - transform.uncertainty_us,
            offset_upper_us=offset_us + transform.uncertainty_us,
            uncertainty_us=transform.uncertainty_us,
            drift_ppb=0.0,
            sample_count=len(samples),
            candidate_count=len(samples),
            representative_count=1,
            sample_span_us=max(source_times) - min(source_times),
            representative_span_us=0.0,
            minimum_rtt_us=min(rtts),
            latest_rtt_us=rtts[-1],
            rtt_p50_us=_percentile(rtts, 0.50),
            rtt_p95_us=_percentile(rtts, 0.95),
            delay_floor_us=min(rtts),
            compatible_count=len(samples),
            consensus_required_count=1,
            model_age_s=age_s,
            reset_count=reset_count,
            last_reset_reason=reset_reason,
            epoch=self._epoch,
            revision=transform.revision,
            updated_monotonic=transform.updated_monotonic,
        )

    @staticmethod
    def _stats(values, sample_time):
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
            "p50": int(_percentile(values, 0.50)),
            "p95": int(_percentile(values, 0.95)),
            "age_ms": max(0.0, (time.monotonic() - sample_time) * 1000.0),
        }

    def path_stats(self):
        with self._lock:
            samples = tuple(self._samples)
        rtts = [float(sample.rtt_us) for sample in samples]
        sample_time = samples[-1].received_monotonic if samples else 0.0
        empty = self._stats([], sample_time)
        return {
            "upload": dict(empty),
            "download": dict(empty),
            "rtt": self._stats(rtts, sample_time),
        }

    def close(self):
        pass


def _percentile(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return math.inf
    position = (len(ordered) - 1) * float(percentile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] * (1.0 - ratio) + ordered[upper] * ratio


def _quality(sample_count, representative_count, span_us, residuals, drift_uncertainty_ppb):
    residual_us = _percentile([abs(value) for value in residuals], 0.5)
    uncertainty_us = _percentile([abs(value) for value in residuals], 0.95)
    if sample_count < 3 or representative_count < 2:
        rating = "Unavailable"
    elif span_us < 10_000_000 or not math.isfinite(drift_uncertainty_ppb):
        rating = "Low"
    elif uncertainty_us <= 2_000.0 and drift_uncertainty_ppb <= 50_000.0:
        rating = "Good"
    else:
        rating = "Fair"
    return AlignmentQuality(
        sample_count=int(sample_count),
        representative_count=int(representative_count),
        span_us=max(0, int(span_us)),
        residual_us=float(residual_us),
        uncertainty_us=float(uncertainty_us),
        drift_uncertainty_ppb=float(drift_uncertainty_ppb),
        rating=rating,
    )


def fit_neuroflap(session, observations, host_clock=HOST_CLOCK_RAW):
    host_clock = normalize_host_clock(host_clock)
    samples = tuple(
        FourTimestampSample.target_initiated(
            (
                item.t1_monotonic_us
                if host_clock == HOST_CLOCK_MONOTONIC
                else item.t1_us
            ),
            item.t2_us,
            item.t3_us,
            (
                item.t4_monotonic_us
                if host_clock == HOST_CLOCK_MONOTONIC
                else item.t4_us
            ),
        )
        for item in observations
    )
    samples = tuple(sample for sample in samples if sample.rtt_us >= 0)
    if len(samples) < 2:
        raise ValueError("NeuroFlap calibration requires at least two valid sync frames")

    minimum_rtt = min(float(sample.rtt_us) for sample in samples)
    rtt_limit = max(minimum_rtt + 500.0, _percentile([sample.rtt_us for sample in samples], 0.20))
    representatives = tuple(sample for sample in samples if sample.rtt_us <= rtt_limit)
    if len(representatives) < 2:
        representatives = tuple(sorted(samples, key=lambda sample: sample.rtt_us)[:2])
    drift_fit = fit_v3_statistical_drift(
        representatives,
        max(1.0, minimum_rtt),
    )
    if not drift_fit.valid:
        raise ValueError("NeuroFlap affine drift fit is not numerically valid")

    source_anchor = statistics.median(sample.source_mid_us for sample in representatives)
    offset_midpoints = []
    for sample in representatives:
        lower, upper = sample.offset_interval_at(source_anchor, drift_fit.drift_ppb)
        offset_midpoints.append((lower + upper) * 0.5)
    offset_us = statistics.median(offset_midpoints)
    target_anchor = source_anchor + offset_us
    residuals = [value - offset_us for value in offset_midpoints]
    span_us = max(sample.source_mid_us for sample in samples) - min(
        sample.source_mid_us for sample in samples
    )
    quality = _quality(
        len(samples),
        len(representatives),
        span_us,
        residuals,
        drift_fit.uncertainty_ppb,
    )
    transform = ClockTransform(
        source_anchor_us=source_anchor,
        target_anchor_us=target_anchor,
        drift_ppb=drift_fit.drift_ppb,
        uncertainty_us=quality.uncertainty_us,
        usable=True,
        locked=quality.rating in ("Good", "Fair"),
        epoch=int(session),
        revision=1,
        updated_monotonic=time.monotonic(),
    )
    return AlignmentModel(
        NEUROFLAP_CLOCK_DOMAIN,
        int(session),
        AlignmentMode.CALIBRATED,
        transform,
        quality,
        time.monotonic_ns() // 1000,
        host_clock,
    )


def _robust_line(points):
    if len(points) < 2:
        raise ValueError("affine fit requires at least two representatives")
    anchor_x = statistics.median(point[0] for point in points)
    slopes = []
    for left in range(len(points)):
        for right in range(left + 1, len(points)):
            dx = points[right][0] - points[left][0]
            if dx:
                slopes.append((points[right][1] - points[left][1]) / dx)
    if not slopes:
        raise ValueError("clock observations do not span time")
    slope = statistics.median(slopes)
    intercept = statistics.median(y - slope * (x - anchor_x) for x, y in points)
    residuals = [y - (intercept + slope * (x - anchor_x)) for x, y in points]
    median = statistics.median(residuals)
    sigma = max(1.0, 1.4826 * statistics.median(abs(value - median) for value in residuals))
    retained = [point for point, residual in zip(points, residuals) if abs(residual - median) <= 3.0 * sigma]
    if len(retained) >= 2 and len(retained) != len(points):
        return _robust_line(retained)
    return anchor_x, intercept, slope, residuals


def fit_ft(session, observations, host_clock=HOST_CLOCK_RAW):
    host_clock = normalize_host_clock(host_clock)
    if len(observations) < 3:
        raise ValueError("FT calibration requires at least three timestamp pairs")
    buckets = {}
    for item in observations:
        bucket = int(item.source_us // 1_000_000)
        receive_us = (
            item.receive_monotonic_us
            if host_clock == HOST_CLOCK_MONOTONIC
            else item.receive_us
        )
        delay = int(receive_us - item.source_us)
        previous = buckets.get(bucket)
        if previous is None or delay < previous[1]:
            buckets[bucket] = (item.source_us, delay)
    representatives = [buckets[key] for key in sorted(buckets)]
    if len(representatives) < 2:
        raise ValueError("FT calibration requires observations spanning multiple seconds")

    anchor, offset_us, slope, residuals = _robust_line(representatives)
    drift_ppb = slope * 1.0e9
    if not math.isfinite(drift_ppb) or abs(drift_ppb) > 500_000.0:
        raise ValueError("FT drift estimate exceeds the supported +/-500 ppm range")
    span_us = max(item.source_us for item in observations) - min(
        item.source_us for item in observations
    )
    sigma = max(1.0, 1.4826 * statistics.median(abs(value) for value in residuals))
    drift_uncertainty_ppb = min(
        500_000.0,
        sigma / max(1.0, span_us) * 1.0e9 * 1.96,
    )
    quality = _quality(
        len(observations),
        len(representatives),
        span_us,
        residuals,
        drift_uncertainty_ppb,
    )
    transform = ClockTransform(
        source_anchor_us=anchor,
        target_anchor_us=anchor + offset_us,
        drift_ppb=drift_ppb,
        uncertainty_us=quality.uncertainty_us,
        usable=True,
        locked=quality.rating in ("Good", "Fair"),
        epoch=int(session),
        revision=1,
        updated_monotonic=time.monotonic(),
    )
    return AlignmentModel(
        FT_CLOCK_DOMAIN,
        int(session),
        AlignmentMode.CALIBRATED,
        transform,
        quality,
        time.monotonic_ns() // 1000,
        host_clock,
    )

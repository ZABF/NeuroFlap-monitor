from dataclasses import replace
import threading

from clock_estimator import AffineClockEstimator as V4AffineClockEstimator
from clock_estimator_hybrid import HybridAffineClockEstimator
from clock_estimator_v3 import AffineClockEstimator as V3AffineClockEstimator
from clock_types import ClockEstimatorStrategy


def create_clock_estimator(
    strategy=ClockEstimatorStrategy.V4_V3,
    *,
    initial_epoch=1,
    background_drift=True,
):
    strategy = ClockEstimatorStrategy.parse(strategy)
    estimator_type = {
        ClockEstimatorStrategy.V3: V3AffineClockEstimator,
        ClockEstimatorStrategy.V4: V4AffineClockEstimator,
        ClockEstimatorStrategy.V4_V3: HybridAffineClockEstimator,
    }[strategy]
    return estimator_type(
        initial_epoch=initial_epoch,
        background_drift=background_drift,
    )


class SelectableClockEstimator:
    """Thread-safe stable facade for switching estimator implementations."""

    def __init__(
        self,
        strategy=ClockEstimatorStrategy.V4_V3,
        *,
        initial_epoch=1,
        background_drift=True,
    ):
        self._lock = threading.RLock()
        self._background_drift = bool(background_drift)
        self._revision_base = 0
        self._estimator = create_clock_estimator(
            strategy,
            initial_epoch=initial_epoch,
            background_drift=self._background_drift,
        )

    @property
    def strategy(self):
        with self._lock:
            return self._estimator.strategy

    @property
    def epoch(self):
        with self._lock:
            return self._estimator.epoch

    @property
    def transform(self):
        with self._lock:
            transform = self._estimator.transform
            return replace(
                transform,
                revision=self._revision_base + transform.revision,
            )

    @property
    def last_sample_result(self):
        with self._lock:
            return self._estimator.last_sample_result

    @property
    def MIN_LOCK_REPRESENTATIVES(self):
        with self._lock:
            return self._estimator.MIN_LOCK_REPRESENTATIVES

    @property
    def MIN_LOCK_SPAN_US(self):
        with self._lock:
            return self._estimator.MIN_LOCK_SPAN_US

    @property
    def LOCK_CONFIRM_UPDATES(self):
        with self._lock:
            return self._estimator.LOCK_CONFIRM_UPDATES

    @property
    def MAX_MODEL_UNCERTAINTY_US(self):
        with self._lock:
            return self._estimator.MAX_MODEL_UNCERTAINTY_US

    def switch_strategy(self, strategy):
        strategy = ClockEstimatorStrategy.parse(strategy)
        with self._lock:
            if strategy == self._estimator.strategy:
                return False
            previous = self._estimator
            self._revision_base += previous.transform.revision + 1
            self._estimator = create_clock_estimator(
                strategy,
                initial_epoch=previous.epoch,
                background_drift=self._background_drift,
            )
            previous.close()
            return True

    def restart_estimation(self, reason="estimation restarted"):
        del reason
        with self._lock:
            previous = self._estimator
            self._revision_base += previous.transform.revision + 1
            self._estimator = create_clock_estimator(
                previous.strategy,
                initial_epoch=previous.epoch,
                background_drift=self._background_drift,
            )
            previous.close()

    def reset(self, reason="reset"):
        with self._lock:
            self._estimator.reset(reason)

    def add(self, t1_us, t2_us, t3_us, t4_us):
        with self._lock:
            return self._estimator.add(t1_us, t2_us, t3_us, t4_us)

    def add_monitor_initiated(self, t1_us, t2_us, t3_us, t4_us):
        with self._lock:
            return self._estimator.add_monitor_initiated(
                t1_us, t2_us, t3_us, t4_us
            )

    def snapshot(self, stale_after_s=None):
        with self._lock:
            snapshot = self._estimator.snapshot(stale_after_s=stale_after_s)
            return replace(
                snapshot,
                revision=self._revision_base + snapshot.revision,
            )

    def path_stats(self):
        with self._lock:
            return self._estimator.path_stats()

    def close(self):
        with self._lock:
            self._estimator.close()

from collections import deque
import math


class ClockObservationWindow:
    MODEL_WINDOW_US = 300_000_000
    PATH_WINDOW_US = 120_000_000
    OFFSET_WINDOW_US = 30_000_000
    DELAY_FLOOR_WINDOW_US = 30_000_000
    HARD_MAX_RAW_SAMPLES = 4096
    BUCKET_US = 2_000_000
    REPRESENTATIVES_PER_BUCKET = 3
    MAX_REPRESENTATIVES = 450

    def __init__(self):
        self._samples = deque()
        self._path_samples = deque()

    @staticmethod
    def percentile(values, percentile):
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

    def clear(self):
        self._samples.clear()
        self._path_samples.clear()

    @property
    def samples(self):
        return tuple(self._samples)

    @property
    def path_samples(self):
        return tuple(self._path_samples)

    def append_path(self, sample):
        self._path_samples.append(sample)
        cutoff_us = sample.source_mid_us - self.PATH_WINDOW_US
        retained = [
            item for item in self._path_samples if item.source_mid_us >= cutoff_us
        ]
        self._path_samples = deque(retained[-self.HARD_MAX_RAW_SAMPLES :])

    def append_model(self, sample):
        self._samples.append(sample)
        cutoff_us = sample.source_mid_us - self.MODEL_WINDOW_US
        retained = [item for item in self._samples if item.source_mid_us >= cutoff_us]
        self._samples = deque(retained[-self.HARD_MAX_RAW_SAMPLES :])

    def delay_floor(self):
        if not self._samples:
            return math.inf
        newest_source_us = self._samples[-1].source_mid_us
        recent_rtts = [
            float(item.rtt_us)
            for item in self._samples
            if item.source_mid_us
            >= newest_source_us - self.DELAY_FLOOR_WINDOW_US
        ]
        return self.percentile(recent_rtts, 10.0)

    def candidates(self):
        delay_floor_us = self.delay_floor()
        if not math.isfinite(delay_floor_us):
            return [], delay_floor_us
        limit_us = max(3.0 * delay_floor_us, delay_floor_us + 10_000.0)
        return (
            [item for item in self._samples if item.rtt_us <= limit_us],
            delay_floor_us,
        )

    def offset_candidates(self):
        candidates, delay_floor_us = self.candidates()
        if not candidates:
            return candidates, delay_floor_us
        cutoff_us = candidates[-1].source_mid_us - self.OFFSET_WINDOW_US
        return (
            [item for item in candidates if item.source_mid_us >= cutoff_us],
            delay_floor_us,
        )

    def representatives(self):
        candidates, _delay_floor_us = self.candidates()
        buckets = {}
        for sample in candidates:
            bucket = int(sample.source_mid_us // self.BUCKET_US)
            bucket_samples = buckets.setdefault(bucket, [])
            bucket_samples.append(sample)
            bucket_samples.sort(key=lambda item: item.rtt_us)
            del bucket_samples[self.REPRESENTATIVES_PER_BUCKET :]
        representatives = [
            sample for bucket_samples in buckets.values() for sample in bucket_samples
        ]
        return sorted(representatives, key=lambda item: item.source_mid_us)[
            -self.MAX_REPRESENTATIVES :
        ]

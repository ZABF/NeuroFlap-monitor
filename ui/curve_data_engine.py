"""Bounded display helpers for full-history monitor data."""

import math
from array import array
from bisect import bisect_left, bisect_right


class UnwrappedSeries:
    """Accumulate angle turns once, retaining compact data for arbitrary views."""

    def __init__(self, period=360.0):
        self.period = float(period)
        if not math.isfinite(self.period) or self.period <= 0.0:
            raise ValueError("unwrap() period must be finite and positive")
        self.timestamps = array("d")
        self.values = array("d")
        self._spans = []
        self._previous = None
        self._previous_time = None
        self._session = None
        self._correction = 0.0

    def extend(self, timestamps, values, sessions=None):
        """Append samples; invalid data, new sessions and time rollback reset turns."""
        half = self.period * 0.5
        for index, (timestamp, value) in enumerate(zip(timestamps, values)):
            try:
                timestamp, value = float(timestamp), float(value)
            except (TypeError, ValueError):
                timestamp, value = math.nan, math.nan
            if not math.isfinite(timestamp) or not math.isfinite(value):
                self._previous = None
                continue
            session = None if sessions is None else sessions[index]
            reset = (
                self._previous is None or session != self._session
                or timestamp < self._previous_time
            )
            if reset:
                self._correction = 0.0
                self._spans.append([len(self.values), len(self.values)])
            else:
                delta = value - self._previous
                if abs(delta) > half:
                    step = (delta + half) % self.period - half
                    # An exactly half-period change has no preferred direction.
                    if step == -half and delta > 0.0:
                        step = half
                    self._correction += step - delta
            self.timestamps.append(timestamp)
            self.values.append(value + self._correction)
            self._spans[-1][1] = len(self.values)
            self._previous = value
            self._previous_time = timestamp
            self._session = session

    def between(self, start=None, end=None, context=2):
        """Slice already unwrapped data without changing its accumulated turns."""
        if start is None and end is None:
            return self.timestamps.tolist(), self.values.tolist()
        timestamps, values = [], []
        for lo, hi in self._spans:
            left = lo if start is None else bisect_left(self.timestamps, start, lo, hi)
            right = hi if end is None else bisect_right(self.timestamps, end, lo, hi)
            left = max(lo, left - context)
            right = min(hi, right + context)
            timestamps.extend(self.timestamps[left:right])
            values.extend(self.values[left:right])
        return timestamps, values


def min_max_downsample(timestamps, values, max_points):
    """Preserve endpoints and bucket extrema while bounding rendered points."""
    count = min(len(timestamps), len(values))
    max_points = max(4, int(max_points))
    if count <= max_points:
        return list(timestamps)[:count], list(values)[:count]

    interior_count = count - 2
    bucket_count = max(1, (max_points - 2) // 2)
    bucket_size = interior_count / float(bucket_count)
    selected = [0]

    for bucket in range(bucket_count):
        start = 1 + int(math.floor(bucket * bucket_size))
        end = 1 + int(math.floor((bucket + 1) * bucket_size))
        if bucket == bucket_count - 1:
            end = count - 1
        end = max(start + 1, min(end, count - 1))

        valid = []
        for index in range(start, end):
            try:
                value = float(values[index])
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                valid.append((index, value))
        if not valid:
            continue

        min_index = min(valid, key=lambda item: item[1])[0]
        max_index = max(valid, key=lambda item: item[1])[0]
        selected.extend(sorted({min_index, max_index}))

    selected.append(count - 1)
    selected = sorted(set(selected))
    return (
        [timestamps[index] for index in selected],
        [values[index] for index in selected],
    )


def _finite_series(timestamps, values):
    """Return finite numeric samples while keeping their original order."""
    count = min(len(timestamps), len(values))
    result = []
    for index in range(count):
        try:
            timestamp = float(timestamps[index])
            value = float(values[index])
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp) and math.isfinite(value):
            result.append((timestamp, value))
    return result


def _time_window_samples(samples, center_time, half_window, start_index):
    """Find the samples in a centered time window using a monotonic left edge."""
    left = start_index
    while left < len(samples) and samples[left][0] < center_time - half_window:
        left += 1
    right = left
    while right < len(samples) and samples[right][0] <= center_time + half_window:
        right += 1
    return left, right


def moving_average(timestamps, values, window_ms):
    """Apply a centered time-window arithmetic mean.

    ``window_ms`` is the complete window width in milliseconds. The function
    is intentionally non-causal because derived curves are an offline/display
    analysis feature. Invalid samples are omitted, and output timestamps are
    the timestamps of the retained center samples.
    """
    count = min(len(timestamps), len(values))
    if count == 0:
        return [], []
    try:
        window_ms = max(float(window_ms), 0.0)
    except (TypeError, ValueError):
        return [], []
    if window_ms <= 0.0:
        return list(timestamps)[:count], list(values)[:count]

    samples = _finite_series(timestamps, values)
    half_window = window_ms * 0.5
    out_timestamps = []
    out_values = []
    left = 0
    right = 0
    running_sum = 0.0
    for timestamp, _value in samples:
        while right < len(samples) and samples[right][0] <= timestamp + half_window:
            running_sum += samples[right][1]
            right += 1
        while left < right and samples[left][0] < timestamp - half_window:
            running_sum -= samples[left][1]
            left += 1
        sample_count = right - left
        if sample_count > 0:
            out_timestamps.append(timestamp)
            out_values.append(running_sum / sample_count)
    return out_timestamps, out_values


def moving_median(timestamps, values, window_ms):
    """Apply a centered time-window median filter."""
    count = min(len(timestamps), len(values))
    if count == 0:
        return [], []
    try:
        window_ms = max(float(window_ms), 0.0)
    except (TypeError, ValueError):
        return [], []
    if window_ms <= 0.0:
        return list(timestamps)[:count], list(values)[:count]

    samples = _finite_series(timestamps, values)
    half_window = window_ms * 0.5
    out_timestamps = []
    out_values = []
    left = 0
    right = 0
    for timestamp, _value in samples:
        left, right = _time_window_samples(samples, timestamp, half_window, left)
        window_values = sorted(value for _time, value in samples[left:right])
        if not window_values:
            continue
        middle = len(window_values) // 2
        if len(window_values) % 2:
            median = window_values[middle]
        else:
            median = (window_values[middle - 1] + window_values[middle]) * 0.5
        out_timestamps.append(timestamp)
        out_values.append(median)
    return out_timestamps, out_values


def hampel_filter(timestamps, values, window_ms, sigma=3.0):
    """Replace centered-window outliers with the local median.

    The robust scale estimate is ``1.4826 * MAD``. If the local MAD is zero,
    any value different from the local median is treated as an outlier. This
    handles isolated spikes in otherwise constant telemetry.
    """
    count = min(len(timestamps), len(values))
    if count == 0:
        return [], []
    try:
        window_ms = max(float(window_ms), 0.0)
        sigma = float(sigma)
    except (TypeError, ValueError):
        return [], []
    if not math.isfinite(sigma) or sigma < 0.0:
        return [], []
    if window_ms <= 0.0:
        return list(timestamps)[:count], list(values)[:count]

    samples = _finite_series(timestamps, values)
    half_window = window_ms * 0.5
    out_timestamps = []
    out_values = []
    left = 0
    right = 0
    scale_factor = 1.4826
    for timestamp, value in samples:
        left, right = _time_window_samples(samples, timestamp, half_window, left)
        window_values = sorted(sample_value for _time, sample_value in samples[left:right])
        if not window_values:
            continue
        middle = len(window_values) // 2
        if len(window_values) % 2:
            center = window_values[middle]
        else:
            center = (window_values[middle - 1] + window_values[middle]) * 0.5
        deviations = sorted(abs(sample_value - center) for sample_value in window_values)
        middle = len(deviations) // 2
        if len(deviations) % 2:
            mad = deviations[middle]
        else:
            mad = (deviations[middle - 1] + deviations[middle]) * 0.5
        threshold = sigma * scale_factor * mad
        filtered = center if (mad == 0.0 and value != center) or abs(value - center) > threshold else value
        out_timestamps.append(timestamp)
        out_values.append(filtered)
    return out_timestamps, out_values

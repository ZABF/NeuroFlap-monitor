"""Host clock sources used by synchronization measurements."""

from dataclasses import dataclass
import time


HOST_CLOCK_RAW = "monotonic_raw"
HOST_CLOCK_MONOTONIC = "monotonic"
HOST_CLOCKS = (HOST_CLOCK_RAW, HOST_CLOCK_MONOTONIC)


def raw_clock_available():
    return hasattr(time, "CLOCK_MONOTONIC_RAW") and hasattr(
        time, "clock_gettime_ns"
    )


def normalize_host_clock(value):
    return (
        HOST_CLOCK_MONOTONIC
        if str(value).strip().lower() == HOST_CLOCK_MONOTONIC
        else HOST_CLOCK_RAW
    )


@dataclass(frozen=True)
class HostClockSample:
    raw_us: int
    monotonic_us: int


def capture_host_clocks_us():
    """Capture RAW between two MONOTONIC reads to minimize comparison skew."""
    monotonic_before_ns = time.monotonic_ns()
    if raw_clock_available():
        raw_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    else:
        raw_ns = monotonic_before_ns
    monotonic_after_ns = time.monotonic_ns()
    monotonic_ns = (monotonic_before_ns + monotonic_after_ns) // 2
    if not raw_clock_available():
        raw_ns = monotonic_ns
    return HostClockSample(raw_ns // 1000, monotonic_ns // 1000)


def raw_time_us():
    if raw_clock_available():
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000
    return time.monotonic_ns() // 1000

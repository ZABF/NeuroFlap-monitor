"""Host clock sources used by synchronization measurements."""

from dataclasses import dataclass
import sys
import time


LINUX_MONOTONIC_RAW = "monotonic_raw"
WINDOWS_QPC = "performance_counter"


def raw_clock_available():
    return hasattr(time, "CLOCK_MONOTONIC_RAW") and hasattr(
        time, "clock_gettime_ns"
    )


ALIGNMENT_CLOCK = (
    LINUX_MONOTONIC_RAW
    if raw_clock_available()
    else WINDOWS_QPC
)


def alignment_clock_label(clock_name=None):
    clock_name = str(clock_name or ALIGNMENT_CLOCK)
    if clock_name == LINUX_MONOTONIC_RAW:
        return "CLOCK_MONOTONIC_RAW"
    if clock_name == WINDOWS_QPC:
        return "Windows QPC" if sys.platform == "win32" else "Performance counter"
    return clock_name


@dataclass(frozen=True)
class HostClockSample:
    alignment_us: int
    monotonic_us: int


def capture_host_clocks_us():
    """Capture the alignment clock between scheduler-clock reads."""
    monotonic_before_ns = time.monotonic_ns()
    if raw_clock_available():
        alignment_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    else:
        alignment_ns = time.perf_counter_ns()
    monotonic_after_ns = time.monotonic_ns()
    monotonic_ns = (monotonic_before_ns + monotonic_after_ns) // 2
    return HostClockSample(alignment_ns // 1000, monotonic_ns // 1000)


def alignment_time_us():
    if raw_clock_available():
        return time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW) // 1000
    return time.perf_counter_ns() // 1000

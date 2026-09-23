import time
import unittest
from unittest.mock import patch

import host_clock


class HostClockTest(unittest.TestCase):
    def test_fallback_uses_performance_counter_for_alignment(self):
        with (
            patch.object(host_clock, "raw_clock_available", return_value=False),
            patch.object(time, "perf_counter_ns", return_value=9_000_000),
            patch.object(
                time,
                "monotonic_ns",
                side_effect=(4_000_000, 4_002_000),
            ),
        ):
            sample = host_clock.capture_host_clocks_us()

        self.assertEqual(sample.alignment_us, 9_000)
        self.assertEqual(sample.monotonic_us, 4_001)

    def test_linux_raw_clock_is_used_when_available(self):
        with (
            patch.object(host_clock, "raw_clock_available", return_value=True),
            patch.object(
                time,
                "clock_gettime_ns",
                return_value=12_000_000,
            ),
            patch.object(
                time,
                "monotonic_ns",
                side_effect=(5_000_000, 5_002_000),
            ),
        ):
            sample = host_clock.capture_host_clocks_us()

        self.assertEqual(sample.alignment_us, 12_000)
        self.assertEqual(sample.monotonic_us, 5_001)


if __name__ == "__main__":
    unittest.main()

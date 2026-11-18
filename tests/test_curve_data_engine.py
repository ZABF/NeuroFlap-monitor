import unittest
import math

import numpy as np

from ui.curve_data_engine import (
    UnwrappedSeries,
    hampel_filter,
    min_max_downsample,
    moving_average,
    moving_median,
)


class CurveDataEngineTest(unittest.TestCase):
    def test_unwrap_crosses_angle_boundaries_in_both_directions(self):
        for wrapped, expected in (
            ([170, 179, -179, -170], [170, 179, 181, 190]),
            ([-170, -179, 179, 170], [-170, -179, -181, -190]),
            ([350, 359, 1, 10], [350, 359, 361, 370]),
            ([0, 180, 0, -180], [0, 180, 0, -180]),
        ):
            with self.subTest(wrapped=wrapped):
                series = UnwrappedSeries()
                series.extend(range(len(wrapped)), wrapped)
                self.assertEqual(series.between(), ([float(i) for i in range(len(wrapped))], expected))

    def test_incremental_unwrap_matches_numpy_over_many_turns(self):
        continuous = np.linspace(-5.0, 35.0, 2000) + 0.25 * np.sin(np.linspace(0.0, 70.0, 2000))
        wrapped = (continuous + math.pi) % (2.0 * math.pi) - math.pi
        series = UnwrappedSeries(2.0 * math.pi)
        for start in range(0, len(wrapped), 17):
            series.extend(range(start, min(start + 17, len(wrapped))), wrapped[start:start + 17])
        np.testing.assert_allclose(series.values, np.unwrap(wrapped), atol=1.0e-12)
        ts, vs = series.between(1200, 1205, context=0)
        self.assertEqual(ts, [1200, 1201, 1202, 1203, 1204, 1205])
        np.testing.assert_allclose(vs, np.unwrap(wrapped)[1200:1206], atol=1.0e-12)

    def test_unwrap_resets_at_invalid_samples_new_sessions_and_time_rollback(self):
        series = UnwrappedSeries()
        series.extend([0, 1, 2, 3, 4, 5, 6, 0, 1], [170, -170, math.nan, -160, 170, -170, -160, 170, -170], [1, 1, 1, 1, 2, 2, 2, 3, 3])
        self.assertEqual(series.between()[1], [170, 190, -160, 170, 190, 200, 170, 190])
        ts, values = series.between(4, 6, context=0)
        self.assertEqual(ts, [4, 5, 6])
        self.assertEqual(values, [170, 190, 200])

    def test_unwrap_rejects_invalid_periods(self):
        for period in (0, -360, math.inf, math.nan):
            with self.subTest(period=period):
                with self.assertRaises(ValueError):
                    UnwrappedSeries(period)

    def test_small_series_is_not_changed(self):
        timestamps = [0.0, 1.0, 2.0]
        values = [3.0, 4.0, 5.0]

        self.assertEqual(
            min_max_downsample(timestamps, values, 8),
            (timestamps, values),
        )

    def test_downsampling_is_bounded_and_preserves_spikes(self):
        timestamps = list(range(1000))
        values = [0.0] * 1000
        values[333] = 100.0
        values[667] = -80.0

        out_ts, out_values = min_max_downsample(timestamps, values, 80)

        self.assertLessEqual(len(out_ts), 80)
        self.assertEqual(out_ts[0], 0)
        self.assertEqual(out_ts[-1], 999)
        self.assertIn(100.0, out_values)
        self.assertIn(-80.0, out_values)

    def test_moving_average_uses_centered_time_window_and_keeps_timestamps(self):
        timestamps = [0.0, 10.0, 30.0]
        values = [0.0, 10.0, 30.0]

        out_ts, out_values = moving_average(timestamps, values, 20.0)

        self.assertEqual(out_ts, timestamps)
        self.assertEqual(out_values, [5.0, 5.0, 30.0])

    def test_moving_median_removes_an_isolated_spike(self):
        timestamps = [0.0, 10.0, 20.0, 30.0, 40.0]
        values = [1.0, 1.0, 100.0, 1.0, 1.0]

        out_ts, out_values = moving_median(timestamps, values, 20.0)

        self.assertEqual(out_ts, timestamps)
        self.assertEqual(out_values, [1.0] * 5)

    def test_hampel_replaces_an_isolated_spike(self):
        timestamps = [0.0, 10.0, 20.0, 30.0, 40.0]
        values = [1.0, 1.0, 100.0, 1.0, 1.0]

        out_ts, out_values = hampel_filter(timestamps, values, 20.0, 3.0)

        self.assertEqual(out_ts, timestamps)
        self.assertEqual(out_values, [1.0] * 5)

    def test_hampel_handles_zero_mad_background(self):
        timestamps = [0.0, 10.0, 20.0]
        values = [5.0, 8.0, 5.0]

        _out_ts, out_values = hampel_filter(timestamps, values, 20.0, 3.0)

        self.assertEqual(out_values, [5.0, 5.0, 5.0])

    def test_filters_drop_non_finite_samples(self):
        timestamps = [0.0, 10.0, float("nan"), 30.0]
        values = [1.0, 2.0, 3.0, float("inf")]

        out_ts, out_values = moving_median(timestamps, values, 20.0)

        self.assertEqual(out_ts, [0.0, 10.0])
        self.assertEqual(out_values, [1.5, 1.5])


if __name__ == "__main__":
    unittest.main()

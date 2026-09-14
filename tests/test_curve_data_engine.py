import unittest

from ui.curve_data_engine import (
    hampel_filter,
    min_max_downsample,
    moving_average,
    moving_median,
)


class CurveDataEngineTest(unittest.TestCase):
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

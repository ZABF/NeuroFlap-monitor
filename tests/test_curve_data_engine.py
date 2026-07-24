import unittest

from ui.curve_data_engine import min_max_downsample


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


if __name__ == "__main__":
    unittest.main()

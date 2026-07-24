import unittest
from array import array

from data_model import DataModel


class DataModelTest(unittest.TestCase):
    def test_history_uses_compact_numeric_arrays(self):
        model = DataModel([])
        model.add_data("source", 1000.0, 10.0, {"value": 3.0})

        self.assertIsInstance(model.sources["source"].src_timestamp, array)
        self.assertIsInstance(model.sources["source"].recon_timestamp, array)
        self.assertIsInstance(model.sources["source"].session, array)
        self.assertIsInstance(model.vars["value"].value, array)

    def test_time_range_returns_only_requested_samples(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0, 30.0, 40.0],
            values=[0.0, 1.0, 2.0, 3.0, 4.0],
        )

        timestamps, values = model.get_series_between("value", 10.0, 30.0)

        self.assertEqual(timestamps, [10.0, 20.0, 30.0])
        self.assertEqual(values, [1.0, 2.0, 3.0])

    def test_improved_clock_offset_reconstructs_existing_history(self):
        model = DataModel([])
        model.add_data(
            "source",
            1100.0,
            1000.0,
            {"value": 1.0},
            offset_src="clock",
            offset_timestamp=1000.0,
        )
        self.assertEqual(model.get_series("value"), ([1100.0], [1.0]))

        model.add_data(
            "source",
            1190.0,
            1100.0,
            {"value": 2.0},
            offset_src="clock",
            offset_timestamp=1100.0,
        )

        self.assertEqual(
            model.get_series("value"),
            ([1090.0, 1190.0], [1.0, 2.0]),
        )

    def test_recent_series_keeps_existing_window_semantics(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0, 30.0, 40.0],
            values=[0.0, 1.0, 2.0, 3.0, 4.0],
        )

        self.assertEqual(
            model.get_series("value", 20.0),
            ([20.0, 30.0, 40.0], [2.0, 3.0, 4.0]),
        )

    def test_tail_returns_only_newest_samples(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0, 30.0, 40.0],
            values=[0.0, 1.0, 2.0, 3.0, 4.0],
        )

        self.assertEqual(
            model.get_series_tail("value", 3),
            ([20.0, 30.0, 40.0], [2.0, 3.0, 4.0]),
        )
        self.assertEqual(model.get_series_tail("value", 0), ([], []))


if __name__ == "__main__":
    unittest.main()

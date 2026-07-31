import unittest
from array import array

from data_model import DataModel
from network_clock import ClockTransform


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

    def test_locked_affine_clock_reconstructs_existing_history_lazily(self):
        model = DataModel([])
        model.add_data(
            "source",
            2100.0,
            1000.0,
            {"value": 1.0},
            offset_src="clock",
            offset_timestamp=1000.0,
        )
        model.add_data(
            "source",
            3100.0,
            2000.0,
            {"value": 2.0},
            offset_src="clock",
            offset_timestamp=2000.0,
        )

        model.set_clock_transform(
            "clock",
            ClockTransform(
                source_anchor_us=1_000_000,
                target_anchor_us=2_000_000,
                drift_ppb=100_000,
                uncertainty_us=500,
                locked=True,
                revision=1,
            ),
        )

        timestamps, values = model.get_series("value")
        self.assertAlmostEqual(timestamps[0], 2000.0, places=6)
        self.assertAlmostEqual(timestamps[1], 3000.1, places=6)
        self.assertEqual(values, [1.0, 2.0])

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

    def test_range_query_can_include_filter_context_samples(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0, 30.0, 40.0],
            values=[0.0, 1.0, 2.0, 3.0, 4.0],
        )

        self.assertEqual(
            model.get_series_between(
                "value",
                20.0,
                20.0,
                before_samples=1,
                after_samples=1,
            ),
            ([10.0, 20.0, 30.0], [1.0, 2.0, 3.0]),
        )

    def test_series_revision_changes_when_samples_change(self):
        model = DataModel([])
        initial = model.get_series_revision("value")
        model.add_series("value", "source", [0.0], [1.0])
        loaded = model.get_series_revision("value")
        model.add_data("source", 10.0, 10.0, {"value": 2.0})
        appended = model.get_series_revision("value")

        self.assertNotEqual(initial, loaded)
        self.assertNotEqual(loaded, appended)

    def test_nearest_sample_uses_complete_raw_series(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0],
            values=[1.0, 2.0, 3.0],
        )

        self.assertEqual(model.get_nearest_sample("value", 14.0), (10.0, 2.0))


if __name__ == "__main__":
    unittest.main()

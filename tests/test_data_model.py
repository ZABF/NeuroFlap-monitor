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

    def test_live_query_keeps_committed_timestamps_after_alignment_changes(self):
        model = DataModel([])
        model.add_data(
            "source",
            2100.0,
            1000.0,
            {"value": 1.0},
            offset_src="clock",
            offset_timestamp=1000.0,
        )

        model.set_clock_transform(
            "clock",
            ClockTransform(
                source_anchor_us=1_000_000,
                target_anchor_us=3_000_000,
                uncertainty_us=100,
                usable=True,
                revision=1,
            ),
        )

        self.assertEqual(
            model.get_series("value", align_history=False),
            ([2100.0], [1.0]),
        )
        self.assertEqual(
            model.get_series("value", align_history=True),
            ([3000.0], [1.0]),
        )

    def test_aligned_range_maps_only_samples_in_requested_window(self):
        model = DataModel([])
        timestamps = [float(index) for index in range(1000)]
        model.add_series("value", "source", timestamps, timestamps)
        model.set_clock_transform(
            "source",
            ClockTransform(
                source_anchor_us=0,
                target_anchor_us=0,
                drift_ppb=100_000,
                uncertainty_us=100,
                usable=True,
                revision=1,
            ),
        )

        map_calls = 0
        original_map = model._map_timestamp

        def recording_map(*args, **kwargs):
            nonlocal map_calls
            map_calls += 1
            return original_map(*args, **kwargs)

        model._map_timestamp = recording_map
        result_timestamps, values = model.get_series_between(
            "value",
            400.0,
            410.0,
            align_history=True,
        )

        self.assertEqual(len(result_timestamps), len(values))
        self.assertGreaterEqual(len(result_timestamps), 10)
        self.assertLess(map_calls, 30)

    def test_time_bounds_maps_only_source_endpoints(self):
        model = DataModel([])
        timestamps = [float(index) for index in range(1000)]
        model.add_series("a", "source-a", timestamps, timestamps)
        model.add_series("b", "source-b", timestamps, timestamps)

        map_calls = 0
        original_map = model._map_timestamp

        def recording_map(*args, **kwargs):
            nonlocal map_calls
            map_calls += 1
            return original_map(*args, **kwargs)

        model._map_timestamp = recording_map
        self.assertEqual(model.get_time_bounds(), (0.0, 999.0))
        self.assertEqual(map_calls, 4)

    def test_forward_data_gap_does_not_create_a_new_clock_epoch(self):
        model = DataModel([])
        model.begin_clock_epoch("clock", 3)
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
            5100.0,
            4000.0,
            {"value": 2.0},
            offset_src="clock",
            offset_timestamp=4000.0,
        )

        self.assertEqual(model.sources["clock"].current_session, 3)
        self.assertEqual(model.sources["source"].session.tolist(), [3, 3])

    def test_new_clock_epoch_does_not_remap_previous_epoch(self):
        model = DataModel([])
        model.begin_clock_epoch("clock", 1)
        model.add_data(
            "source",
            2100.0,
            1000.0,
            {"value": 1.0},
            offset_src="clock",
            offset_timestamp=1000.0,
        )
        model.set_clock_transform(
            "clock",
            ClockTransform(
                source_anchor_us=1_000_000,
                target_anchor_us=2_000_000,
                uncertainty_us=100,
                usable=True,
                epoch=1,
                revision=1,
            ),
        )
        model.begin_clock_epoch("clock", 2)
        model.add_data(
            "source",
            5300.0,
            300.0,
            {"value": 2.0},
            offset_src="clock",
            offset_timestamp=300.0,
        )
        model.set_clock_transform(
            "clock",
            ClockTransform(
                source_anchor_us=300_000,
                target_anchor_us=5_000_000,
                uncertainty_us=100,
                usable=True,
                epoch=2,
                revision=2,
            ),
        )

        timestamps, values = model.get_series("value")
        self.assertEqual(timestamps, [2000.0, 5000.0])
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

    def test_bracketing_samples_do_not_expose_future_as_previous(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0],
            values=[1.0, 2.0, 3.0],
        )

        self.assertEqual(
            model.get_bracketing_samples("value", 14.0),
            ((10.0, 2.0), (20.0, 3.0)),
        )
        self.assertEqual(
            model.get_bracketing_samples("value", -1.0),
            (None, (0.0, 1.0)),
        )

    def test_series_window_ending_at_is_bounded_by_time_and_count(self):
        model = DataModel([])
        model.add_series(
            "value",
            "source",
            timestamps=[0.0, 10.0, 20.0, 30.0],
            values=[1.0, 2.0, 3.0, 4.0],
        )

        self.assertEqual(
            model.get_series_window_ending_at("value", 25.0, 2),
            ([10.0, 20.0], [2.0, 3.0]),
        )

    def test_time_bounds_span_selected_variable_sources(self):
        model = DataModel([])
        model.add_series("a", "source-a", [10.0, 20.0], [1.0, 2.0])
        model.add_series("b", "source-b", [5.0, 30.0], [3.0, 4.0])

        self.assertEqual(model.get_time_bounds(), (5.0, 30.0))
        self.assertEqual(model.get_time_bounds(["a"]), (10.0, 20.0))


if __name__ == "__main__":
    unittest.main()

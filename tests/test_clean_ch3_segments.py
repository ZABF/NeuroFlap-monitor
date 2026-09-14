import csv
from pathlib import Path
import tempfile
import unittest

from monitor_csv import read_monitor_csv, write_monitor_csv
from tools.clean_ch3_segments import (
    DEFAULT_CH3_SIGNAL,
    FILTER_TARGETS,
    FilterConfig,
    Segment,
    deduplicate_segments,
    filtered_zeroed_series,
    find_high_segments,
    process_directory,
)


class CleanCh3SegmentsTest(unittest.TestCase):
    def test_default_filter_matches_runtime_choice(self):
        self.assertEqual(FilterConfig().sample_rate_hz, 50.0)
        self.assertEqual(FilterConfig().cutoff_hz, 3.0)
        self.assertEqual(FilterConfig().order, 2)
        self.assertEqual(FilterConfig().mode, "causal")

    def test_high_segments_use_first_low_sample_as_exclusive_end(self):
        points = [
            (0, 0.0),
            (1_000_000, 2.8),
            (6_000_000, 2.8),
            (7_000_000, 0.0),
        ]
        self.assertEqual(
            find_high_segments(points, 2.5, 5.0, maximum_gap_ms=6_000.0),
            [(1_000_000, 7_000_000)],
        )
        self.assertEqual(
            find_high_segments(points, 2.5, 6.1, maximum_gap_ms=6_000.0), []
        )

    def test_missing_ch3_samples_break_a_high_segment(self):
        points = [(0, 0.0)]
        points.extend((value, 2.8) for value in range(20_000, 5_060_000, 20_000))
        points.append((15_040_000, 0.0))
        self.assertEqual(
            find_high_segments(points, 2.5, 5.0, maximum_gap_ms=250.0),
            [(20_000, 5_060_000)],
        )

    def test_high_signal_after_a_gap_starts_a_new_segment(self):
        points = [(value, 2.8) for value in range(0, 5_100_000, 100_000)]
        points.extend((value, 2.8) for value in range(7_000_000, 12_100_000, 100_000))
        points.append((12_100_000, 0.0))
        self.assertEqual(
            find_high_segments(points, 2.5, 5.0, maximum_gap_ms=250.0),
            [(0, 5_100_000), (7_000_000, 12_100_000)],
        )

    def test_causal_filter_does_not_change_past_output_when_future_is_added(self):
        config = FilterConfig()
        prefix = {
            "timestamps": [index * 20.0 for index in range(80)],
            "values": [0.0] * 20 + [1.0] * 60,
        }
        full = {
            "timestamps": [index * 20.0 for index in range(120)],
            "values": [0.0] * 20 + [1.0] * 60 + [-5.0] * 40,
        }
        _prefix_t, prefix_y, _ = filtered_zeroed_series(prefix, 0, 10_000_000, config)
        _full_t, full_y, _ = filtered_zeroed_series(full, 0, 10_000_000, config)
        self.assertEqual(prefix_y, full_y[: len(prefix_y)])

    def test_filter_resets_after_long_gap(self):
        item = {
            "timestamps": [0.0, 20.0, 40.0, 400.0, 420.0],
            "values": [1.0, 1.0, 1.0, 10.0, 10.0],
        }
        timestamps, values, reset_count = filtered_zeroed_series(
            item, 0, 1_000_000, FilterConfig(max_gap_ms=250.0)
        )
        self.assertEqual(reset_count, 1)
        second_block = timestamps.index(400.0)
        self.assertAlmostEqual(values[0], 0.0)
        self.assertAlmostEqual(values[second_block], 9.0)

    def test_deduplication_keeps_capture_with_larger_source_span(self):
        short = Segment(Path("short.csv"), 1, 1_000_000, 7_000_000, 8_000_000)
        long = Segment(Path("long.csv"), 1, 1_008_000, 7_008_000, 12_000_000)
        kept, duplicates = deduplicate_segments([short, long])
        self.assertEqual(kept, [long])
        self.assertEqual(duplicates[short.key], long)

    def test_directory_processing_writes_importable_and_plain_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            self._write_capture(input_dir / "short.csv", end_ms=7_000.0)
            self._write_capture(input_dir / "long.csv", end_ms=8_000.0)

            result = process_directory(input_dir, output_dir, minimum_seconds=5.0)

            self.assertEqual(result["discovered"], 2)
            self.assertEqual(result["processed"], 1)
            self.assertEqual(result["duplicates"], 1)
            monitor_files = list((output_dir / "nfmonitor").glob("*.csv"))
            plain_files = list((output_dir / "plain").glob("*.csv"))
            self.assertEqual([path.name for path in monitor_files], ["long_segment_001.csv"])
            self.assertEqual([path.name for path in plain_files], ["long_segment_001.csv"])

            document = read_monitor_csv(monitor_files[0])
            self.assertEqual(document.metadata["source_file"], "long.csv")
            for _source_name, output_name, _display_name in FILTER_TARGETS:
                self.assertIn(output_name, document.series)
                self.assertAlmostEqual(document.series[output_name]["values"][0], 0.0)

            with plain_files[0].open(newline="", encoding="utf-8") as fp:
                first_row = next(csv.reader(fp))
            self.assertFalse(first_row[0].startswith("#"))
            self.assertIn(
                "Processed.UWB.pos_x_lowpass_zero_time_us",
                first_row,
            )

            with (output_dir / "manifest.csv").open(newline="", encoding="utf-8") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual({row["status"] for row in rows}, {"processed", "duplicate"})
            self.assertTrue((output_dir / "filter_reference.csv").exists())

    @staticmethod
    def _write_capture(path, end_ms):
        timestamps = [index * 20.0 for index in range(int(end_ms / 20.0) + 1)]
        ch3_values = [2.8 if 1_000.0 <= value < 7_000.0 else 0.0 for value in timestamps]
        series = [
            {
                "name": DEFAULT_CH3_SIGNAL,
                "timestamps": timestamps,
                "values": ch3_values,
                "section": "Task/RC",
            },
            {
                "name": "UwbTask.output.pos_x",
                "timestamps": timestamps,
                "values": [value / 1000.0 for value in timestamps],
                "section": "Task/UWB",
                "unit": "m",
            },
            {
                "name": "UwbTask.output.pos_y",
                "timestamps": timestamps,
                "values": [2.0 * value / 1000.0 for value in timestamps],
                "section": "Task/UWB",
                "unit": "m",
            },
            {
                "name": "SensorTask.output.height",
                "timestamps": timestamps,
                "values": [3.0 * value / 1000.0 for value in timestamps],
                "section": "Task/Sensor",
                "unit": "m",
            },
            {
                "name": "Other.signal",
                "timestamps": timestamps[::5],
                "values": [42.0] * len(timestamps[::5]),
                "section": "Other",
            },
        ]
        write_monitor_csv(path, series, {"protocol": "test"})


if __name__ == "__main__":
    unittest.main()

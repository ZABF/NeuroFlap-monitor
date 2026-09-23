import csv
import os
import tempfile
import unittest

from monitor_csv import read_monitor_csv, write_monitor_csv


class MonitorCsvTest(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        handle.close()
        self.path = handle.name

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_v4_round_trip_preserves_raw_time_axes_and_task_metadata(self):
        series = [
            {
                "name": "MadgwickTask.input.pitch",
                "timestamps": [1784700000000.0, 1784700000010.0],
                "values": [1.25, 1.30],
                "category": "task",
                "section": "Task/5",
                "unit": "deg",
                "descriptor_kind": "task_port",
                "owner": "MadgwickTask",
                "display_name": "pitch",
                "task_id": 5,
                "direction": 0,
                "slot": 0,
                "scalar_type": 6,
                "hidden_control": False,
                "task_order": 2,
            },
            {
                "name": "MadgwickTask.latency_us",
                "timestamps": [1784700000000.08],
                "values": [86],
                "category": "task",
                "section": "Task/5",
                "unit": "us",
                "descriptor_kind": "task_latency",
                "owner": "MadgwickTask",
                "display_name": "latency_us",
                "task_id": 5,
                "scalar_type": 4,
                "hidden_control": True,
                "task_order": 2,
            },
        ]

        count = write_monitor_csv(
            self.path,
            series,
            {"protocol": "NFv3", "schema_generation": 12},
        )

        self.assertEqual(count, 2)
        with open(self.path, "r", newline="", encoding="utf-8") as fp:
            rows = list(csv.reader(fp))
        self.assertEqual(rows[0], ["#NFMonitorCSV", "4"])
        header = next(row for row in rows if row and not row[0].startswith("#"))
        self.assertEqual(
            header,
            [
                "MadgwickTask.input.pitch_time_raw_us",
                "MadgwickTask.input.pitch_session",
                "MadgwickTask.input.pitch_value",
                "MadgwickTask.latency_us_time_raw_us",
                "MadgwickTask.latency_us_session",
                "MadgwickTask.latency_us_value",
            ],
        )
        first_data_index = rows.index(header) + 1
        self.assertEqual(rows[first_data_index][0], "1784700000000000")
        self.assertEqual(rows[first_data_index][1], "1")
        self.assertEqual(rows[first_data_index][3], "1784700000000080")

        document = read_monitor_csv(self.path)
        self.assertEqual(document.metadata["protocol"], "NFv3")
        self.assertEqual(document.metadata["schema_generation"], "12")
        pitch = document.series["MadgwickTask.input.pitch"]
        self.assertEqual(pitch["timestamps"], [1784700000000.0, 1784700000010.0])
        self.assertEqual(pitch["values"], [1.25, 1.3])
        self.assertEqual(pitch["direction"], 0)
        self.assertEqual(pitch["scalar_type"], 6)
        self.assertEqual(pitch["task_id"], 5)
        latency = document.series["MadgwickTask.latency_us"]
        self.assertTrue(latency["hidden_control"])
        self.assertEqual(latency["descriptor_kind"], "task_latency")

    def test_v3_name_with_comma_is_used_directly_as_column_prefix(self):
        name = "Dataflow.force,left"
        write_monitor_csv(
            self.path,
            [{
                "name": name,
                "timestamps": [1000.0],
                "values": [2.5],
                "section": "Dataflow/force",
            }],
        )

        document = read_monitor_csv(self.path)
        self.assertIn(name, document.series)
        self.assertEqual(document.series[name]["values"], [2.5])

    def test_v2_metadata_and_xy_columns_remain_supported(self):
        with open(self.path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["#NFMonitorCSV", "2"])
            writer.writerow([
                "#var", "Task.output.yaw", "Task/7", "deg", "task", "task_port",
                "7", "1", "Task", "yaw", "3", "0", "", "0",
            ])
            writer.writerow(["Task.output.yaw_x", "Task.output.yaw_y"])
            writer.writerow(["1000.5", "12.25"])

        data = read_monitor_csv(self.path).series["Task.output.yaw"]
        self.assertEqual(data["timestamps"], [1000.5])
        self.assertEqual(data["values"], [12.25])
        self.assertEqual(data["task_id"], 7)
        self.assertEqual(data["direction"], 1)
        self.assertEqual(data["section"], "Task/7")

    def test_legacy_csv_without_metadata_uses_ungrouped_section(self):
        with open(self.path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["pitch_time_ms", "pitch_value", "roll_x", "roll_y"])
            writer.writerow(["10", "1.5", "12", "-2.0"])

        document = read_monitor_csv(self.path)
        self.assertEqual(document.series["pitch"]["section"], "Ungrouped")
        self.assertEqual(document.series["pitch"]["timestamps"], [10.0])
        self.assertEqual(document.series["roll"]["values"], [-2.0])

    def test_v3_reader_skips_comma_padded_empty_separator_row(self):
        with open(self.path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["#NFMonitorCSV", "3"])
            writer.writerow(["#meta", "time_unit", "us"])
            writer.writerow(["", "", "", ""])
            writer.writerow(["pitch_time_us", "pitch_value"])
            writer.writerow(["0", "1.5"])

        document = read_monitor_csv(self.path)
        self.assertEqual(document.series["pitch"]["values"], [1.5])

    def test_duplicate_variable_names_are_rejected(self):
        item = {"name": "pitch", "timestamps": [0.0], "values": [1.0]}
        with self.assertRaisesRegex(ValueError, "Duplicate CSV variable name"):
            write_monitor_csv(self.path, [item, item])

    def test_comment_prefixed_name_is_rejected(self):
        item = {"name": "#pitch", "timestamps": [0.0], "values": [1.0]}
        with self.assertRaisesRegex(ValueError, "must not start"):
            write_monitor_csv(self.path, [item])

    def test_newer_format_version_is_rejected(self):
        with open(self.path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(["#NFMonitorCSV", "5"])
            writer.writerow(["pitch_time_us", "pitch_value"])
            writer.writerow(["0", "1"])
        with self.assertRaisesRegex(ValueError, "Unsupported NFMonitorCSV version"):
            read_monitor_csv(self.path)

    def test_v4_clock_models_and_observations_round_trip(self):
        write_monitor_csv(
            self.path,
            [{
                "name": "F_X",
                "raw_timestamps": [1000.0, 1001.0],
                "sessions": [2, 2],
                "values": [1.0, 2.0],
                "clock_domain": "ft",
            }],
            clock_data={
                "active_mode": "calibrated",
                "monitor_monotonic_anchor_us": 100,
                "monitor_unix_anchor_us": 1_000_100,
                "models": [{
                    "domain": "ft",
                    "session": 2,
                    "mode": "calibrated",
                    "source_anchor_us": 1_000_000,
                    "target_anchor_unix_us": 2_000_000,
                    "offset_us": 1_000_000,
                    "drift_ppm": 100.0,
                    "uncertainty_us": 20.0,
                    "rating": "Good",
                    "sample_count": 10,
                    "representative_count": 5,
                    "span_us": 10_000_000,
                    "residual_us": 10.0,
                    "drift_uncertainty_ppb": 500.0,
                }],
                "observations": [{
                    "domain": "ft",
                    "session": 2,
                    "source_us": 1_000_000,
                    "receive_us": 1_500_000,
                }],
            },
        )

        document = read_monitor_csv(self.path)

        self.assertEqual(document.metadata["active_alignment_mode"], "calibrated")
        self.assertEqual(document.series["F_X"]["raw_timestamps"], [1000.0, 1001.0])
        self.assertEqual(document.series["F_X"]["sessions"], [2, 2])
        self.assertEqual(document.series["F_X"]["timestamps"][0], 2000.0)
        self.assertAlmostEqual(
            document.series["F_X"]["timestamps"][1], 2001.0001
        )
        self.assertEqual(document.clock_models[0]["domain"], "ft")
        self.assertEqual(document.clock_observations[0]["receive_us"], "1500000")

    def test_v4_clock_evidence_survives_without_data_columns(self):
        write_monitor_csv(
            self.path,
            [],
            clock_data={
                "models": [{
                    "domain": "neuroflap",
                    "session": 3,
                    "mode": "realtime",
                }],
                "observations": [{
                    "domain": "neuroflap",
                    "session": 3,
                    "sequence": 9,
                    "t1_us": 10,
                    "t2_us": 20,
                    "t3_us": 30,
                    "t4_us": 40,
                }],
            },
        )

        document = read_monitor_csv(self.path)

        self.assertEqual(document.series, {})
        self.assertEqual(document.clock_models[0]["session"], "3")
        self.assertEqual(document.clock_observations[0]["sequence"], "9")


if __name__ == "__main__":
    unittest.main()

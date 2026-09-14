import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt5.QtCore import QEvent, QPointF, QSettings, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from data_model import DataModel
from flight_visualization import (
    aligned_pose,
    axis_rotation,
    downsample_trajectory,
    euler_rotation,
    interpolate_sample,
    wing_vertices,
)
from timeline_controller import TimelineController
from ui.flight_visualization_window import FlightVisualizationWindow
from ui.theme import apply_dark_theme


VARIABLES = {
    "UwbPositionFusionTask.output.pos_x": 1.0,
    "UwbPositionFusionTask.output.pos_y": 2.0,
    "UwbPositionFusionTask.output.pos_z": 3.0,
    "MadgwickTask.output.roll": 10.0,
    "MadgwickTask.output.pitch": 20.0,
    "MadgwickTask.output.yaw": 30.0,
    "BusServoTask.input.left_deg_in": 15.0,
    "BusServoTask.output.left_deg": 14.0,
    "BusServoTask.input.right_deg_in": -12.0,
    "BusServoTask.output.right_deg": -11.0,
}


class FlightGeometryTest(unittest.TestCase):
    def test_yxz_matches_firmware_euler_order_312(self):
        rotation = euler_rotation(12.0, -7.0, 33.0, "YXZ")
        expected = (
            axis_rotation("Z", 33.0)
            @ axis_rotation("X", 12.0)
            @ axis_rotation("Y", -7.0)
        )
        np.testing.assert_allclose(rotation, expected, atol=1.0e-12)

    def test_yaw_reference_aligns_position_and_attitude(self):
        position, rotation = aligned_pose(
            (0.0, 2.0, 0.0),
            0.0,
            0.0,
            90.0,
            90.0,
            "YXZ",
        )
        np.testing.assert_allclose(position, (2.0, 0.0, 0.0), atol=1.0e-12)
        np.testing.assert_allclose(rotation, np.identity(3), atol=1.0e-12)

    def test_positive_servo_angle_lifts_both_wings(self):
        left = wing_vertices(1, 30.0, 20.0)
        right = wing_vertices(-1, 30.0, 20.0)
        self.assertGreater(float(np.mean(left[:, 2])), 0.0)
        self.assertGreater(float(np.mean(right[:, 2])), 0.0)

    def test_negative_servo_angle_lowers_both_wings(self):
        left = wing_vertices(1, -30.0, 20.0)
        right = wing_vertices(-1, -30.0, 20.0)
        self.assertLess(float(np.mean(left[:, 2])), 0.0)
        self.assertLess(float(np.mean(right[:, 2])), 0.0)

    def test_scalar_interpolation_and_long_gap_hold_previous(self):
        self.assertEqual(
            interpolate_sample((0.0, 2.0), (100.0, 6.0), 25.0),
            3.0,
        )
        self.assertEqual(
            interpolate_sample(
                (0.0, 2.0),
                (500.0, 6.0),
                250.0,
                max_gap_ms=250.0,
            ),
            2.0,
        )

    def test_angular_interpolation_takes_short_path(self):
        value = interpolate_sample(
            (0.0, 179.0),
            (100.0, -179.0),
            50.0,
            angular=True,
        )
        self.assertAlmostEqual(value, 180.0)

    def test_trajectory_downsampling_preserves_endpoints_and_budget(self):
        points = np.column_stack(
            (
                np.arange(3000, dtype=float),
                np.arange(3000, dtype=float) * 2.0,
                np.arange(3000, dtype=float) * -1.0,
            )
        )

        sampled = downsample_trajectory(points, 1000)

        self.assertEqual(sampled.shape, (1000, 3))
        np.testing.assert_array_equal(sampled[0], points[0])
        np.testing.assert_array_equal(sampled[-1], points[-1])


class FlightVisualizationWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_dark_theme(cls.app)

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings = QSettings(
            os.path.join(self.temp_dir.name, "flight.ini"),
            QSettings.IniFormat,
        )
        self.model = DataModel([])
        for index, (name, value) in enumerate(VARIABLES.items()):
            self.model.add_series(
                name,
                f"source-{index}",
                timestamps=[1000.0, 1010.0],
                values=[value - 1.0, value],
            )
        self.window = FlightVisualizationWindow(
            self.model,
            available_variables=lambda: VARIABLES.keys(),
            settings=self.settings,
        )
        self.window.timer.stop()

    def tearDown(self):
        self.window.close()
        self.temp_dir.cleanup()

    def test_known_firmware_variables_are_bound_without_duplicates(self):
        selected = {
            key: combo.currentData()
            for key, combo in self.window.binding_combos.items()
        }
        self.assertEqual(set(selected.values()), set(VARIABLES.keys()))

    def test_update_builds_sample_and_position_history(self):
        self.window.update_scene()
        self.window.update_scene()

        self.assertIsNotNone(self.window.canvas.sample)
        self.assertEqual(len(self.window.canvas.trail), 2)
        self.assertEqual(self.window.canvas.sample.left_actual_deg, 14.0)
        self.assertEqual(self.window.canvas.sample.right_command_deg, -12.0)

    def test_unchanged_scene_does_not_query_samples_again(self):
        self.window.update_scene()
        calls = 0
        refresh_calls = 0
        original = self.window._current_sample
        original_refresh = self.window.refresh_variables

        def recording_sample(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        def recording_refresh(*args, **kwargs):
            nonlocal refresh_calls
            refresh_calls += 1
            return original_refresh(*args, **kwargs)

        self.window._current_sample = recording_sample
        self.window.refresh_variables = recording_refresh
        self.window.update_scene()

        self.assertEqual(calls, 0)
        self.assertEqual(refresh_calls, 0)

    def test_live_trajectory_appends_without_rebuilding_history(self):
        self.window.update_scene()
        self.assertEqual(len(self.window._trajectory_cache), 2)

        for index, (name, value) in enumerate(VARIABLES.items()):
            self.model.add_data(
                f"source-{index}",
                1020.0,
                1020.0,
                {name: value + 1.0},
            )

        original = self.model.get_series_window_ending_at
        self.model.get_series_window_ending_at = lambda *_args, **_kwargs: self.fail(
            "Live trajectory updates must append instead of rebuilding history"
        )
        try:
            self.window.update_scene()
        finally:
            self.model.get_series_window_ending_at = original

        self.assertEqual(len(self.window._trajectory_cache), 3)

    def test_timer_runs_only_while_window_is_visible(self):
        self.assertFalse(self.window.timer.isActive())

        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.timer.isActive())

        self.window.hide()
        self.app.processEvents()
        self.assertFalse(self.window.timer.isActive())

    def test_shared_timeline_selects_historical_interpolated_sample(self):
        timeline = TimelineController()
        timeline.begin_replay(1000.0, 1010.0)
        timeline.seek(1005.0)
        self.window.close()
        self.window = FlightVisualizationWindow(
            self.model,
            available_variables=lambda: VARIABLES.keys(),
            settings=self.settings,
            timeline=timeline,
        )
        self.window.timer.stop()

        self.window.update_scene()

        self.assertAlmostEqual(self.window.canvas.sample.roll_deg, 9.5)
        self.assertAlmostEqual(self.window.canvas.sample.position[0], 0.5)
        self.assertEqual(len(self.window.canvas.trail), 2)

    def test_yaw_reference_realigns_existing_trail(self):
        self.window.canvas.trail = ((0.0, 2.0, 0.0),)
        self.window.canvas.yaw_reference_deg = 90.0

        np.testing.assert_allclose(
            self.window.canvas._aligned_trail()[0],
            (2.0, 0.0, 0.0),
            atol=1.0e-12,
        )

    def test_saved_binding_survives_window_initialization(self):
        saved_name = "MadgwickTask.output.roll"
        self.settings.setValue(
            "flight_visualization/v1/binding/position_x",
            saved_name,
        )
        self.window.close()
        self.window = FlightVisualizationWindow(
            self.model,
            available_variables=lambda: VARIABLES.keys(),
            settings=self.settings,
        )
        self.window.timer.stop()

        self.assertEqual(
            self.window.binding_combos["position_x"].currentData(),
            saved_name,
        )

    def test_canvas_renders_nonblank_combined_scene(self):
        self.window.update_scene()
        self.window.resize(1180, 760)
        self.window.show()
        self.app.processEvents()

        image = self.window.canvas.grab().toImage()
        colors = {
            image.pixelColor(x, y).rgba()
            for x in range(0, image.width(), 16)
            for y in range(0, image.height(), 16)
        }
        self.assertGreater(len(colors), 8)

    def test_right_drag_pans_camera_target_without_rotating_view(self):
        canvas = self.window.canvas
        canvas.resize(800, 600)
        original_target = canvas.target.copy()
        original_angles = (canvas.azimuth_deg, canvas.elevation_deg)
        press = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(200.0, 200.0),
            Qt.RightButton,
            Qt.RightButton,
            Qt.NoModifier,
        )
        move = QMouseEvent(
            QEvent.MouseMove,
            QPointF(260.0, 230.0),
            Qt.NoButton,
            Qt.RightButton,
            Qt.NoModifier,
        )
        release = QMouseEvent(
            QEvent.MouseButtonRelease,
            QPointF(260.0, 230.0),
            Qt.RightButton,
            Qt.NoButton,
            Qt.NoModifier,
        )

        canvas.mousePressEvent(press)
        canvas.mouseMoveEvent(move)
        canvas.mouseReleaseEvent(release)

        self.assertFalse(np.allclose(canvas.target, original_target))
        self.assertEqual(
            (canvas.azimuth_deg, canvas.elevation_deg),
            original_angles,
        )
        self.assertIsNone(canvas._drag_button)


if __name__ == "__main__":
    unittest.main()

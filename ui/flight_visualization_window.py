"""Live trajectory, attitude, and actuator visualization window."""

import math

import numpy as np
from PyQt5.QtCore import QPointF, QSettings, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flight_visualization import (
    EULER_ORDERS,
    FlightSample,
    aligned_pose,
    axis_rotation,
    box_faces,
    interpolate_sample,
    wing_vertices,
)
from timeline_controller import TimelineController, TimelineState
from ui.theme import (
    ACCENT,
    BORDER,
    PLOT_BG,
    SUCCESS,
    TEXT,
    TEXT_MUTED,
    set_semantic_state,
)
from ui.timeline_bar import TimelineBar


BINDINGS = (
    (
        "position_x",
        "Position X",
        ("uwbpositionfusiontask.output.pos_x", ".output.pos_x", "mocap_x", "pos_x"),
    ),
    (
        "position_y",
        "Position Y",
        ("uwbpositionfusiontask.output.pos_y", ".output.pos_y", "mocap_y", "pos_y"),
    ),
    (
        "position_z",
        "Position Z",
        ("uwbpositionfusiontask.output.pos_z", ".output.pos_z", "mocap_z", "pos_z"),
    ),
    ("roll", "Roll", ("madgwicktask.output.roll", ".output.roll", "mocap_roll")),
    ("pitch", "Pitch", ("madgwicktask.output.pitch", ".output.pitch", "mocap_pitch")),
    ("yaw", "Yaw", ("madgwicktask.output.yaw", ".output.yaw", "mocap_yaw")),
    (
        "left_command",
        "Left command",
        (
            "busservotask.input.left_deg_in",
            "pwmservotask.input.sl_deg_in",
            "left_deg_in",
            "sl_deg_in",
        ),
    ),
    (
        "left_actual",
        "Left actual",
        ("busservotask.output.left_deg", "pwmservotask.output.left_deg", ".output.left_deg"),
    ),
    (
        "right_command",
        "Right command",
        (
            "busservotask.input.right_deg_in",
            "pwmservotask.input.sr_deg_in",
            "right_deg_in",
            "sr_deg_in",
        ),
    ),
    (
        "right_actual",
        "Right actual",
        ("busservotask.output.right_deg", "pwmservotask.output.right_deg", ".output.right_deg"),
    ),
)


def _qcolor(rgb, alpha=255):
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(alpha))


class FlightSceneCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)
        self.mode = "combined"
        self.sample = None
        self.trail = ()
        self.euler_order = "YXZ"
        self.yaw_reference_deg = 0.0
        self.servo_included_angle_deg = 20.0
        self.model_scale = 0.35
        self.azimuth_deg = -55.0
        self.elevation_deg = 28.0
        self.distance = 5.0
        self.target = np.zeros(3)
        self._last_mouse_pos = None
        self._drag_button = None

    def set_mode(self, mode):
        self.mode = str(mode)
        if self.mode == "attitude":
            self.target = np.zeros(3)
            self.distance = 2.8
        elif self.trail:
            self.fit_view()
        self.update()

    def set_view(self, name):
        if name == "top":
            self.azimuth_deg = -90.0
            self.elevation_deg = 89.0
        elif name == "front":
            self.azimuth_deg = -90.0
            self.elevation_deg = 0.0
        else:
            self.azimuth_deg = -55.0
            self.elevation_deg = 28.0
        self.update()

    def fit_view(self):
        if self.mode == "attitude" or not self.trail:
            self.target = np.zeros(3)
            self.distance = 2.8
        else:
            points = self._aligned_trail()
            minimum = np.min(points, axis=0)
            maximum = np.max(points, axis=0)
            self.target = (minimum + maximum) * 0.5
            self.distance = max(2.8, np.linalg.norm(maximum - minimum) * 1.7)
        self.update()

    def _aligned_trail(self):
        points = np.asarray(self.trail, dtype=float)
        if not len(points):
            return np.empty((0, 3))
        alignment = axis_rotation("Z", -self.yaw_reference_deg)
        return points @ alignment.T

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._last_mouse_pos = event.pos()
            self._drag_button = event.button()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._last_mouse_pos is None or self._drag_button is None:
            return
        delta = event.pos() - self._last_mouse_pos
        self._last_mouse_pos = event.pos()
        if self._drag_button == Qt.LeftButton and event.buttons() & Qt.LeftButton:
            self.azimuth_deg += delta.x() * 0.45
            self.elevation_deg = max(
                -85.0,
                min(89.0, self.elevation_deg + delta.y() * 0.35),
            )
        elif self._drag_button == Qt.RightButton and event.buttons() & Qt.RightButton:
            _camera, right, up, _forward = self._camera_basis()
            focal = max(1.0, min(self.width(), self.height()) * 0.95)
            world_per_pixel = self.distance / focal
            self.target += (
                -float(delta.x()) * right + float(delta.y()) * up
            ) * world_per_pixel
        else:
            return
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == self._drag_button:
            self._last_mouse_pos = None
            self._drag_button = None
            event.accept()

    def wheelEvent(self, event):
        factor = math.exp(-event.angleDelta().y() / 1200.0)
        self.distance = max(0.35, min(1000000.0, self.distance * factor))
        self.update()

    def _camera_basis(self):
        azimuth = math.radians(self.azimuth_deg)
        elevation = math.radians(self.elevation_deg)
        direction = np.array(
            (
                math.cos(elevation) * math.cos(azimuth),
                math.cos(elevation) * math.sin(azimuth),
                math.sin(elevation),
            )
        )
        camera = self.target + direction * self.distance
        forward = self.target - camera
        forward /= max(np.linalg.norm(forward), 1.0e-9)
        right = np.cross(forward, np.array((0.0, 0.0, 1.0)))
        if np.linalg.norm(right) < 1.0e-6:
            right = np.array((1.0, 0.0, 0.0))
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return camera, right, up, forward

    def _project(self, points):
        points = np.asarray(points, dtype=float)
        camera, right, up, forward = self._camera_basis()
        relative = points - camera
        x = relative @ right
        y = relative @ up
        depth = relative @ forward
        focal = min(self.width(), self.height()) * 0.95
        safe_depth = np.maximum(depth, 0.05)
        screen_x = self.width() * 0.5 + focal * x / safe_depth
        screen_y = self.height() * 0.5 - focal * y / safe_depth
        return np.column_stack((screen_x, screen_y)), depth

    def _draw_line(self, painter, start, end, color, width=1.0, style=Qt.SolidLine):
        projected, depth = self._project((start, end))
        if min(depth) <= 0.0:
            return
        painter.setPen(QPen(color, width, style))
        painter.drawLine(QPointF(*projected[0]), QPointF(*projected[1]))

    def _draw_grid(self, painter, center, radius):
        radius = max(1.0, float(radius))
        exponent = math.floor(math.log10(radius))
        step = 10.0 ** exponent
        if radius / step < 2.5:
            step *= 0.5
        center_x = round(float(center[0]) / step) * step
        center_y = round(float(center[1]) / step) * step
        extent = step * 8.0
        grid_color = _qcolor(BORDER, 105)
        for index in range(-8, 9):
            offset = index * step
            self._draw_line(
                painter,
                (center_x - extent, center_y + offset, 0.0),
                (center_x + extent, center_y + offset, 0.0),
                grid_color,
            )
            self._draw_line(
                painter,
                (center_x + offset, center_y - extent, 0.0),
                (center_x + offset, center_y + extent, 0.0),
                grid_color,
            )

    def _draw_axes(self, painter, origin, scale):
        colors = (QColor(255, 92, 92), QColor(94, 220, 148), QColor(92, 166, 255))
        labels = ("X", "Y", "Z")
        endpoints = []
        for axis in range(3):
            endpoint = np.asarray(origin, dtype=float).copy()
            endpoint[axis] += scale
            endpoints.append(endpoint)
            self._draw_line(painter, origin, endpoint, colors[axis], 2.2)
        painter.setPen(_qcolor(TEXT))
        for endpoint, label in zip(endpoints, labels):
            projected, depth = self._project((endpoint,))
            if depth[0] > 0.0:
                painter.drawText(QPointF(*projected[0]) + QPointF(4.0, -4.0), label)

    def _draw_polyline(self, painter, points, color, width=2.0, style=Qt.SolidLine):
        if len(points) < 2:
            return
        projected, depth = self._project(points)
        path = QPainterPath()
        active = False
        for point, point_depth in zip(projected, depth):
            if point_depth <= 0.0:
                active = False
                continue
            if not active:
                path.moveTo(QPointF(*point))
                active = True
            else:
                path.lineTo(QPointF(*point))
        painter.setPen(QPen(color, width, style))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_polygon(self, painter, points, color, outline=None):
        projected, depth = self._project(points)
        if np.any(depth <= 0.0):
            return
        polygon = QPolygonF([QPointF(*point) for point in projected])
        painter.setBrush(color)
        painter.setPen(QPen(outline or color.lighter(135), 1.0))
        painter.drawPolygon(polygon)

    def _body_geometry(self, position, rotation, scale):
        faces = []
        for face in box_faces((0.0, 0.0, 0.0), (0.62, 0.30, 0.20)):
            faces.append((face @ rotation.T) * scale + position)
        nose = np.array(
            ((0.52, 0.0, 0.0), (0.28, -0.18, -0.11), (0.28, 0.18, -0.11), (0.28, 0.0, 0.14))
        )
        for indexes in ((0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)):
            face = nose[list(indexes)]
            faces.append((face @ rotation.T) * scale + position)
        return faces

    def _draw_vehicle(self, painter, position, rotation):
        scale = self.model_scale
        actual_color = QColor(83, 211, 219, 175)
        body_color = QColor(218, 225, 235, 235)
        body_outline = QColor(114, 130, 150, 220)
        polygons = [
            (face, body_color, body_outline)
            for face in self._body_geometry(position, rotation, scale)
        ]

        sample = self.sample
        if sample is None:
            return
        for side, actual in (
            (1, sample.left_actual_deg),
            (-1, sample.right_actual_deg),
        ):
            actual_wing = wing_vertices(side, actual, self.servo_included_angle_deg)
            actual_world = (actual_wing @ rotation.T) * scale + position
            polygons.append(
                (actual_world, actual_color, QColor(115, 247, 251, 225))
            )

        # QPainter has no depth buffer, so paint farther polygons first.
        depth_sorted = []
        for points, color, outline in polygons:
            _projected, depths = self._project(points)
            depth_sorted.append((float(np.mean(depths)), points, color, outline))
        for _depth, points, color, outline in sorted(
            depth_sorted,
            reverse=True,
            key=lambda item: item[0],
        ):
            self._draw_polygon(painter, points, color, outline)

        for side, command in (
            (1, sample.left_command_deg),
            (-1, sample.right_command_deg),
        ):
            command_wing = wing_vertices(side, command, self.servo_included_angle_deg)
            command_world = (command_wing @ rotation.T) * scale + position
            self._draw_polyline(
                painter,
                np.vstack((command_world, command_world[0])),
                QColor(245, 185, 66, 220),
                2.0,
                Qt.DashLine,
            )

        axis_scale = scale * 0.62
        for axis, color in zip(
            np.identity(3),
            (QColor(255, 92, 92), QColor(94, 220, 148), QColor(92, 166, 255)),
        ):
            endpoint = position + rotation @ axis * axis_scale
            self._draw_line(painter, position, endpoint, color, 2.0)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), _qcolor(PLOT_BG))

        trail = self._aligned_trail()
        scene_center = self.target
        scene_radius = self.distance * 0.35
        if self.mode != "attitude" and len(trail):
            extent = np.ptp(trail, axis=0)
            scene_radius = max(1.0, float(np.linalg.norm(extent)))
        self._draw_grid(painter, scene_center, scene_radius)
        self._draw_axes(painter, np.zeros(3), max(0.4, scene_radius * 0.25))

        if self.mode in ("trajectory", "combined") and len(trail):
            self._draw_polyline(painter, trail, _qcolor(ACCENT), 2.2)
            projected, depth = self._project((trail[-1],))
            if depth[0] > 0.0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(_qcolor(SUCCESS))
                painter.drawEllipse(QPointF(*projected[0]), 4.5, 4.5)

        if self.sample is not None and self.mode in ("attitude", "combined"):
            aligned_position, rotation = aligned_pose(
                self.sample.position,
                self.sample.roll_deg,
                self.sample.pitch_deg,
                self.sample.yaw_deg,
                self.yaw_reference_deg,
                self.euler_order,
            )
            vehicle_position = np.zeros(3) if self.mode == "attitude" else aligned_position
            self._draw_vehicle(painter, vehicle_position, rotation)

        painter.setPen(_qcolor(TEXT_MUTED))
        painter.drawText(12, 22, "X forward   Y left   Z up")
        if self.mode in ("attitude", "combined"):
            painter.setPen(QPen(QColor(115, 247, 251), 5.0))
            painter.drawLine(20, 42, 42, 42)
            painter.setPen(_qcolor(TEXT_MUTED))
            painter.drawText(48, 47, "Actual")
            painter.setPen(QPen(QColor(245, 185, 66), 2.0, Qt.DashLine))
            painter.drawLine(105, 42, 127, 42)
            painter.setPen(_qcolor(TEXT_MUTED))
            painter.drawText(133, 47, "Command")


class FlightVisualizationWindow(QWidget):
    SETTINGS_PREFIX = "flight_visualization/v1"

    def __init__(
        self,
        data_model,
        available_variables=None,
        settings=None,
        timeline=None,
        parent=None,
    ):
        super().__init__(parent, Qt.Window)
        self.data_model = data_model
        self.available_variables = available_variables or (lambda: self.data_model.vars.keys())
        self.settings = settings or QSettings("NeuroFlap", "Monitor")
        self._owns_timeline = timeline is None
        self.timeline = timeline or TimelineController(parent=self)
        self.binding_combos = {}
        self.mode_buttons = {}
        self._loading_settings = True
        self._last_variable_signature = None
        self._trail_start_ms = None
        self._timeline_source_signature = None
        self._build_ui()
        self._load_settings()
        self._loading_settings = False
        self.refresh_variables(force=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_scene)
        self.timer.start(33)

    def _build_ui(self):
        self.setWindowTitle("Flight Visualization")
        self.resize(1180, 760)

        self.canvas = FlightSceneCanvas(self)
        modes = QButtonGroup(self)
        modes.setExclusive(True)
        mode_layout = QHBoxLayout()
        for label, mode in (
            ("Trajectory", "trajectory"),
            ("Attitude", "attitude"),
            ("Combined", "combined"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(mode == "combined")
            button.clicked.connect(lambda _checked, value=mode: self._set_mode(value))
            modes.addButton(button)
            self.mode_buttons[mode] = button
            mode_layout.addWidget(button)
        mode_layout.addStretch()
        for label, view in (("Perspective", "perspective"), ("Top", "top"), ("Front", "front")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked, value=view: self.canvas.set_view(value))
            mode_layout.addWidget(button)
        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.canvas.fit_view)
        mode_layout.addWidget(fit_button)
        clear_button = QPushButton("Clear Trail")
        clear_button.clicked.connect(self.clear_trail)
        mode_layout.addWidget(clear_button)

        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.setContentsMargins(6, 6, 6, 6)

        inputs_group = QGroupBox("Inputs")
        inputs_form = QFormLayout(inputs_group)
        for key, label, _hints in BINDINGS:
            combo = QComboBox()
            combo.setMinimumContentsLength(14)
            combo.setMaximumWidth(230)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.currentTextChanged.connect(combo.setToolTip)
            combo.currentIndexChanged.connect(self._settings_changed)
            self.binding_combos[key] = combo
            inputs_form.addRow(label, combo)
        settings_layout.addWidget(inputs_group)

        pose_group = QGroupBox("Pose")
        pose_form = QFormLayout(pose_group)
        self.euler_order_combo = QComboBox()
        self.euler_order_combo.addItems(EULER_ORDERS)
        self.euler_order_combo.setToolTip(
            "Intrinsic Body-axis application order. YXZ matches firmware Euler order 312."
        )
        self.euler_order_combo.currentTextChanged.connect(self._settings_changed)
        pose_form.addRow("Euler order", self.euler_order_combo)
        self.yaw_reference_spin = QDoubleSpinBox()
        self.yaw_reference_spin.setRange(-360.0, 360.0)
        self.yaw_reference_spin.setDecimals(2)
        self.yaw_reference_spin.setSuffix(" deg")
        self.yaw_reference_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.yaw_reference_spin.valueChanged.connect(self._yaw_reference_changed)
        pose_form.addRow("Initial yaw", self.yaw_reference_spin)
        capture_yaw_button = QPushButton("Use Current Yaw")
        capture_yaw_button.clicked.connect(self.capture_current_yaw)
        pose_form.addRow("", capture_yaw_button)
        settings_layout.addWidget(pose_group)

        mechanics_group = QGroupBox("Mechanics")
        mechanics_form = QFormLayout(mechanics_group)
        self.servo_angle_spin = QDoubleSpinBox()
        self.servo_angle_spin.setRange(0.0, 180.0)
        self.servo_angle_spin.setValue(20.0)
        self.servo_angle_spin.setSuffix(" deg")
        self.servo_angle_spin.valueChanged.connect(self._settings_changed)
        mechanics_form.addRow("Servo included angle", self.servo_angle_spin)
        self.model_scale_spin = QDoubleSpinBox()
        self.model_scale_spin.setRange(0.001, 10000.0)
        self.model_scale_spin.setDecimals(3)
        self.model_scale_spin.setValue(0.35)
        self.model_scale_spin.valueChanged.connect(self._settings_changed)
        mechanics_form.addRow("Model scale", self.model_scale_spin)
        self.interpolation_gap_spin = QSpinBox()
        self.interpolation_gap_spin.setRange(10, 5000)
        self.interpolation_gap_spin.setValue(250)
        self.interpolation_gap_spin.setSuffix(" ms")
        self.interpolation_gap_spin.valueChanged.connect(self._settings_changed)
        mechanics_form.addRow("Interpolation gap", self.interpolation_gap_spin)
        settings_layout.addWidget(mechanics_group)

        trail_group = QGroupBox("Trail")
        trail_form = QFormLayout(trail_group)
        self.trail_points_spin = QSpinBox()
        self.trail_points_spin.setRange(10, 20000)
        self.trail_points_spin.setValue(3000)
        self.trail_points_spin.valueChanged.connect(self._trail_capacity_changed)
        trail_form.addRow("Points", self.trail_points_spin)
        settings_layout.addWidget(trail_group)
        settings_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(380)
        scroll.setWidget(settings_widget)

        scene_layout = QVBoxLayout()
        scene_layout.addLayout(mode_layout)
        scene_layout.addWidget(self.canvas, 1)
        self.timeline_bar = TimelineBar(self.timeline, compact=True, parent=self)
        scene_layout.addWidget(self.timeline_bar)
        self.status_label = QLabel("Waiting for inputs")
        self.status_label.setProperty("semanticState", "muted")
        scene_layout.addWidget(self.status_label)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addLayout(scene_layout, 1)
        root.addWidget(scroll)

    def _setting_key(self, name):
        return f"{self.SETTINGS_PREFIX}/{name}"

    def _load_settings(self):
        self.euler_order_combo.setCurrentText(
            str(self.settings.value(self._setting_key("euler_order"), "YXZ"))
        )
        self.yaw_reference_spin.setValue(
            float(self.settings.value(self._setting_key("yaw_reference_deg"), 0.0))
        )
        self.servo_angle_spin.setValue(
            float(self.settings.value(self._setting_key("servo_included_angle_deg"), 20.0))
        )
        self.model_scale_spin.setValue(
            float(self.settings.value(self._setting_key("model_scale"), 0.35))
        )
        self.interpolation_gap_spin.setValue(
            int(self.settings.value(self._setting_key("interpolation_gap_ms"), 250))
        )
        self.trail_points_spin.setValue(
            int(self.settings.value(self._setting_key("trail_points"), 3000))
        )

    def _settings_changed(self, *_args):
        if self._loading_settings:
            return
        self.canvas.euler_order = self.euler_order_combo.currentText()
        self.canvas.yaw_reference_deg = self.yaw_reference_spin.value()
        self.canvas.servo_included_angle_deg = self.servo_angle_spin.value()
        self.canvas.model_scale = self.model_scale_spin.value()
        self.settings.setValue(self._setting_key("euler_order"), self.canvas.euler_order)
        self.settings.setValue(
            self._setting_key("yaw_reference_deg"),
            self.canvas.yaw_reference_deg,
        )
        self.settings.setValue(
            self._setting_key("servo_included_angle_deg"),
            self.canvas.servo_included_angle_deg,
        )
        self.settings.setValue(self._setting_key("model_scale"), self.canvas.model_scale)
        self.settings.setValue(
            self._setting_key("interpolation_gap_ms"),
            self.interpolation_gap_spin.value(),
        )
        for key, combo in self.binding_combos.items():
            self.settings.setValue(self._setting_key(f"binding/{key}"), combo.currentData() or "")
        self.canvas.update()

    def _set_mode(self, mode):
        self.canvas.set_mode(mode)
        self.settings.setValue(self._setting_key("mode"), mode)

    def _yaw_reference_changed(self, *_args):
        self._settings_changed()
        self.canvas.fit_view()

    @staticmethod
    def _binding_score(name, hints):
        lower = name.lower()
        score = 0
        for priority, hint in enumerate(hints):
            hint = hint.lower()
            if lower.endswith(hint):
                score = max(score, 1000 - priority * 20 + len(hint))
            elif hint in lower:
                score = max(score, 500 - priority * 20 + len(hint))
        return score

    def refresh_variables(self, force=False):
        variables = sorted(set(self.available_variables()) | set(self.data_model.vars.keys()))
        signature = tuple(variables)
        if not force and signature == self._last_variable_signature:
            return
        self._last_variable_signature = signature
        selected_names = set()
        for key, _label, hints in BINDINGS:
            combo = self.binding_combos[key]
            saved = str(self.settings.value(self._setting_key(f"binding/{key}"), ""))
            current = combo.currentData() or saved
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Not bound", "")
            for name in variables:
                combo.addItem(name, name)
            selected = combo.findData(current)
            if selected < 0 or not current:
                ranked = sorted(
                    (
                        (self._binding_score(name, hints), name)
                        for name in variables
                        if name not in selected_names
                    ),
                    reverse=True,
                )
                if ranked and ranked[0][0] >= 900:
                    selected = combo.findData(ranked[0][1])
            combo.setCurrentIndex(max(0, selected))
            if combo.currentData():
                selected_names.add(combo.currentData())
            combo.blockSignals(False)
        self._settings_changed()

    def _sample_at(self, key, timestamp_ms, default=0.0):
        name = self.binding_combos[key].currentData()
        if not name:
            return None, float(default)
        previous, following = self.data_model.get_bracketing_samples(
            name,
            timestamp_ms,
        )
        value = interpolate_sample(
            previous,
            following,
            timestamp_ms,
            angular=key in ("roll", "pitch", "yaw"),
            max_gap_ms=self.interpolation_gap_spin.value(),
        )
        if value is None:
            return None, float(default)
        return previous[0], value

    def _current_sample(self):
        if not self.timeline.has_range:
            return None, list(key for key, _label, _hints in BINDINGS)
        playhead_ms = self.timeline.playhead_ms
        values = {}
        timestamps = {}
        missing = []
        for key, _label, _hints in BINDINGS:
            timestamp, value = self._sample_at(key, playhead_ms)
            values[key] = value
            if timestamp is None:
                missing.append(key)
            else:
                timestamps[key] = timestamp
        if not timestamps:
            return None, missing
        if "left_actual" not in timestamps and "left_command" in timestamps:
            values["left_actual"] = values["left_command"]
        if "right_actual" not in timestamps and "right_command" in timestamps:
            values["right_actual"] = values["right_command"]
        return FlightSample(
            timestamp_ms=playhead_ms,
            position=(values["position_x"], values["position_y"], values["position_z"]),
            roll_deg=values["roll"],
            pitch_deg=values["pitch"],
            yaw_deg=values["yaw"],
            left_command_deg=values["left_command"],
            left_actual_deg=values["left_actual"],
            right_command_deg=values["right_command"],
            right_actual_deg=values["right_actual"],
        ), missing

    def _series_values_at(self, name, target_times):
        if not len(target_times):
            return np.empty(0)
        timestamps, values = self.data_model.get_series_between(
            name,
            float(target_times[0]),
            float(target_times[-1]),
            before_samples=1,
            after_samples=1,
        )
        if not timestamps:
            return np.full(len(target_times), np.nan)
        source_times = np.asarray(timestamps, dtype=float)
        source_values = np.asarray(values, dtype=float)
        targets = np.asarray(target_times, dtype=float)
        next_indexes = np.searchsorted(source_times, targets, side="right")
        result = np.full(len(targets), np.nan)
        has_previous = next_indexes > 0
        previous_indexes = np.maximum(0, next_indexes - 1)
        result[has_previous] = source_values[previous_indexes[has_previous]]

        has_following = next_indexes < len(source_times)
        interpolated = has_previous & has_following
        if np.any(interpolated):
            rows = np.flatnonzero(interpolated)
            previous = previous_indexes[rows]
            following = next_indexes[rows]
            gaps = source_times[following] - source_times[previous]
            valid_gap = (gaps > 0.0) & (
                gaps <= float(self.interpolation_gap_spin.value())
            )
            rows = rows[valid_gap]
            previous = previous[valid_gap]
            following = following[valid_gap]
            gaps = gaps[valid_gap]
            ratios = (targets[rows] - source_times[previous]) / gaps
            result[rows] = source_values[previous] + ratios * (
                source_values[following] - source_values[previous]
            )
        return result

    def _trajectory_at(self, playhead_ms):
        names = {
            axis: self.binding_combos[f"position_{axis}"].currentData()
            for axis in ("x", "y", "z")
        }
        if not all(names.values()):
            return ()
        timestamps, x_values = self.data_model.get_series_window_ending_at(
            names["x"],
            playhead_ms,
            self.trail_points_spin.value(),
        )
        if not timestamps:
            return ()
        times = np.asarray(timestamps, dtype=float)
        x_values = np.asarray(x_values, dtype=float)
        if self._trail_start_ms is not None:
            keep = times >= self._trail_start_ms
            times = times[keep]
            x_values = x_values[keep]
        if not len(times):
            return ()
        y_values = self._series_values_at(names["y"], times)
        z_values = self._series_values_at(names["z"], times)
        valid = np.isfinite(x_values) & np.isfinite(y_values) & np.isfinite(z_values)
        return tuple(
            tuple(point)
            for point in np.column_stack(
                (x_values[valid], y_values[valid], z_values[valid])
            )
        )

    def update_scene(self):
        self.refresh_variables()
        if self._owns_timeline:
            start_ms, latest_ms = self.data_model.get_time_bounds(
                self.available_variables()
            )
            if self.timeline.state == TimelineState.EMPTY:
                self.timeline.begin_live()
            self.timeline.update_bounds(start_ms, latest_ms)
        source_signature = (
            self.timeline.source_kind,
            self.timeline.start_ms,
            self.timeline.latest_ms if self.timeline.source_kind == "replay" else None,
        )
        if source_signature != self._timeline_source_signature:
            self._timeline_source_signature = source_signature
            self._trail_start_ms = None

        sample, missing = self._current_sample()
        if sample is None:
            self.canvas.sample = None
            self.canvas.trail = ()
            self.canvas.update()
            self.status_label.setText("Waiting for inputs")
            set_semantic_state(self.status_label, "muted")
            return
        self.canvas.sample = sample
        if self.canvas.mode in ("trajectory", "combined"):
            trail = list(self._trajectory_at(self.timeline.playhead_ms))
            position_keys = {"position_x", "position_y", "position_z"}
            if not position_keys.intersection(missing):
                if not trail or not np.allclose(trail[-1], sample.position):
                    trail.append(tuple(sample.position))
            self.canvas.trail = tuple(trail[-self.trail_points_spin.value():])
        else:
            self.canvas.trail = ()
        self.canvas.update()
        if missing:
            self.status_label.setText(f"Partial data | missing {len(missing)} inputs")
            set_semantic_state(self.status_label, "warning")
        else:
            self.status_label.setText(
                f"Roll {sample.roll_deg:+.1f} deg   Pitch {sample.pitch_deg:+.1f} deg   "
                f"Yaw {sample.yaw_deg:+.1f} deg"
            )
            set_semantic_state(self.status_label, "success")

    def capture_current_yaw(self):
        sample, _missing = self._current_sample()
        if sample is not None:
            self.yaw_reference_spin.setValue(sample.yaw_deg)

    def clear_trail(self):
        self._trail_start_ms = self.timeline.playhead_ms
        self.canvas.trail = ()
        self.canvas.update()

    def _trail_capacity_changed(self, capacity):
        self.settings.setValue(self._setting_key("trail_points"), int(capacity))

    def showEvent(self, event):
        super().showEvent(event)
        mode = str(self.settings.value(self._setting_key("mode"), "combined"))
        self.canvas.set_mode(mode)
        button = self.mode_buttons.get(mode, self.mode_buttons["combined"])
        button.setChecked(True)
        self.refresh_variables(force=True)

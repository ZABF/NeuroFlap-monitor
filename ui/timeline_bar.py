"""Reusable transport controls for the shared Monitor timeline."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QWidget,
)

from timeline_controller import TimelineState
from ui.theme import set_semantic_state


def _format_duration(milliseconds):
    milliseconds = max(0, int(round(float(milliseconds))))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


class TimelineBar(QWidget):
    SLIDER_STEPS = 1_000_000

    def __init__(self, controller, compact=False, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.compact = bool(compact)

        self.play_button = QPushButton()
        self.play_button.setFixedSize(32, 28)
        self.play_button.clicked.connect(self.controller.toggle_playback)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self.SLIDER_STEPS)
        self.slider.setMinimumWidth(150 if compact else 260)
        self.slider.sliderPressed.connect(self.controller.pause)
        self.slider.valueChanged.connect(self._slider_moved)

        self.time_label = QLabel("--:--.--- / --:--.---")
        self.time_label.setMinimumWidth(145)

        self.speed_combo = QComboBox()
        for speed in (0.25, 0.5, 1.0, 2.0, 4.0):
            self.speed_combo.addItem(f"{speed:g}x", speed)
        self.speed_combo.setFixedWidth(62)
        self.speed_combo.currentIndexChanged.connect(self._speed_changed)

        self.live_button = QPushButton("Live")
        self.live_button.setToolTip("Jump to the newest sample and follow live data")
        self.live_button.setFixedWidth(52)
        self.live_button.clicked.connect(self.controller.go_live)

        self.delay_label = QLabel("")
        self.delay_label.setMinimumWidth(70)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.play_button)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.speed_combo)
        layout.addWidget(self.delay_label)
        layout.addWidget(self.live_button)

        self.controller.changed.connect(self.refresh)
        self.refresh()

    def _slider_moved(self, value):
        if not self.controller.has_range:
            return
        duration = self.controller.latest_ms - self.controller.start_ms
        if duration <= 0.0:
            timestamp = self.controller.start_ms
        else:
            timestamp = (
                self.controller.start_ms
                + duration * float(value) / self.SLIDER_STEPS
            )
        self.controller.seek(timestamp)

    def _speed_changed(self, index):
        speed = self.speed_combo.itemData(index)
        if speed is not None:
            self.controller.set_speed(float(speed))

    def refresh(self):
        running = self.controller.is_running
        icon = self.style().standardIcon(
            QStyle.SP_MediaPause if running else QStyle.SP_MediaPlay
        )
        self.play_button.setIcon(icon)
        if running:
            tooltip = "Pause"
        else:
            tooltip = "Play from the current position at the selected speed"
        self.play_button.setToolTip(tooltip)
        self.play_button.setEnabled(self.controller.has_range)
        self.slider.setEnabled(self.controller.has_range)

        self.slider.blockSignals(True)
        if self.controller.has_range:
            duration = self.controller.latest_ms - self.controller.start_ms
            offset = self.controller.playhead_ms - self.controller.start_ms
            value = 0 if duration <= 0.0 else round(
                self.SLIDER_STEPS * offset / duration
            )
            self.slider.setValue(max(0, min(self.SLIDER_STEPS, value)))
            self.time_label.setText(
                f"{_format_duration(offset)} / {_format_duration(duration)}"
            )
        else:
            self.slider.setValue(0)
            self.time_label.setText("--:--.--- / --:--.---")
        self.slider.blockSignals(False)

        speed_index = self.speed_combo.findData(self.controller.speed)
        if speed_index >= 0 and speed_index != self.speed_combo.currentIndex():
            self.speed_combo.blockSignals(True)
            self.speed_combo.setCurrentIndex(speed_index)
            self.speed_combo.blockSignals(False)

        is_live = self.controller.source_kind == "live"
        self.live_button.setVisible(is_live)
        self.delay_label.setVisible(is_live)
        if is_live and self.controller.has_range:
            if self.controller.is_live_edge:
                self.delay_label.setText("Live")
                set_semantic_state(self.delay_label, "success")
            else:
                self.delay_label.setText(
                    f"-{self.controller.live_delay_ms / 1000.0:.1f} s"
                )
                set_semantic_state(self.delay_label, "warning")
            self.live_button.setEnabled(not self.controller.is_live_edge)
        else:
            self.delay_label.setText("")

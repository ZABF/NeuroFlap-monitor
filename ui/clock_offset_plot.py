from bisect import bisect_left

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.theme import ACCENT, PLOT_BG_HEX, SUCCESS, TEXT_MUTED, WARNING


class ClockOffsetPlot(QWidget):
    """Render raw clock observations and the two alignment models."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._payload = None
        self._series_identity = None

        self.summary_label = QLabel("No offset observations")
        self.sample_label = QLabel("Sample: --")

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(PLOT_BG_HEX)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setLabel("bottom", "Elapsed time", units="s")
        self.plot_widget.setLabel("left", "Offset delta", units="ms")
        self.plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot_widget.getAxis("left").enableAutoSIPrefix(False)
        self.plot_widget.addLegend(offset=(8, 8))
        self.plot_widget.setMinimumSize(760, 330)

        self.lower_curve = self._curve(
            "Lower bound", (90, 152, 220, 150), width=1
        )
        self.upper_curve = self._curve(
            "Upper bound", (204, 124, 206, 150), width=1
        )
        self.observed_curve = self._curve(
            "Observed midpoint", WARNING, width=1
        )
        self.realtime_curve = self._curve(
            "Realtime", ACCENT, width=2, style=Qt.DashLine
        )
        self.calibrated_curve = self._curve(
            "Calibrated", SUCCESS, width=2
        )

        self.cursor_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(TEXT_MUTED, width=1, style=Qt.DotLine),
        )
        self.cursor_line.hide()
        self.plot_widget.addItem(self.cursor_line, ignoreBounds=True)
        self._mouse_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._mouse_moved,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.plot_widget, 1)
        layout.addWidget(self.sample_label)

    def _curve(self, name, color, *, width, style=Qt.SolidLine):
        curve = self.plot_widget.plot(
            name=name,
            pen=pg.mkPen(color=color, width=width, style=style),
        )
        curve.setClipToView(True)
        curve.setDownsampling(auto=True, method="peak")
        return curve

    def set_data(self, payload):
        self._payload = payload
        count = int(payload.get("count", 0))
        identity = (
            payload.get("domain"),
            payload.get("session"),
            payload.get("host_clock"),
        )
        identity_changed = identity != self._series_identity
        self._series_identity = identity

        if count <= 0:
            self.summary_label.setText("No offset observations")
            self.sample_label.setText("Sample: --")
            self.cursor_line.hide()
            for curve in self._curves():
                curve.setData([], [])
            return

        domain = str(payload["domain"])
        domain_name = "NeuroFlap" if domain == "neuroflap" else "FT"
        host_clock = str(payload.get("host_clock", "monotonic_raw"))
        clock_name = (
            "CLOCK_MONOTONIC"
            if host_clock == "monotonic"
            else "CLOCK_MONOTONIC_RAW"
        )
        baseline_ms = float(payload["baseline_offset_ms"])
        fitted_ppm = payload.get("calibrated_ppm")
        fit_text = (
            "" if fitted_ppm is None else f" | fit {float(fitted_ppm):+.2f} ppm"
        )
        self.summary_label.setText(
            f"{domain_name} | {clock_name} | session {int(payload['session'])} | "
            f"{count} observations | reference {baseline_ms:.3f} ms{fit_text}"
        )

        x_values = payload["elapsed_s"]
        self.observed_curve.setData(x_values, payload["midpoint_delta_ms"])
        self.realtime_curve.setData(x_values, payload["realtime_delta_ms"])
        calibrated = payload.get("calibrated_delta_ms", ())
        self.calibrated_curve.setData(
            x_values if calibrated else [], calibrated
        )

        has_interval = bool(payload.get("has_interval"))
        self.lower_curve.setVisible(has_interval)
        self.upper_curve.setVisible(has_interval)
        self.lower_curve.setData(
            x_values if has_interval else [], payload["lower_delta_ms"] if has_interval else []
        )
        self.upper_curve.setData(
            x_values if has_interval else [], payload["upper_delta_ms"] if has_interval else []
        )
        if identity_changed:
            self.plot_widget.autoRange()

    def _curves(self):
        return (
            self.lower_curve,
            self.upper_curve,
            self.observed_curve,
            self.realtime_curve,
            self.calibrated_curve,
        )

    def _mouse_moved(self, event):
        if self._payload is None or not self._payload.get("elapsed_s"):
            return
        position = event[0]
        if not self.plot_widget.sceneBoundingRect().contains(position):
            self.cursor_line.hide()
            return
        view_position = self.plot_widget.getViewBox().mapSceneToView(position)
        x_values = self._payload["elapsed_s"]
        index = bisect_left(x_values, view_position.x())
        if index >= len(x_values):
            index = len(x_values) - 1
        elif index > 0 and abs(x_values[index - 1] - view_position.x()) < abs(
            x_values[index] - view_position.x()
        ):
            index -= 1

        elapsed_s = float(x_values[index])
        absolute_ms = float(self._payload["absolute_midpoint_ms"][index])
        delta_ms = float(self._payload["midpoint_delta_ms"][index])
        rtt_ms = float(self._payload["rtt_ms"][index])
        self.cursor_line.setPos(elapsed_s)
        self.cursor_line.show()
        if self._payload.get("has_interval"):
            lower_ms = absolute_ms + (
                float(self._payload["lower_delta_ms"][index]) - delta_ms
            )
            upper_ms = absolute_ms + (
                float(self._payload["upper_delta_ms"][index]) - delta_ms
            )
            detail = (
                f"bounds [{lower_ms:.3f}, {upper_ms:.3f}] ms | "
                f"RTT {rtt_ms:.3f} ms"
            )
        else:
            detail = f"receive-source {rtt_ms:.3f} ms"
        self.sample_label.setText(
            f"t {elapsed_s:.3f} s | offset {absolute_ms:.3f} ms | "
            f"delta {delta_ms:+.3f} ms | {detail}"
        )

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QGridLayout, QSpinBox, QDoubleSpinBox
)
from PyQt5.QtCore import QTimer
import pyqtgraph as pg


# ------------------------- peak helpers -------------------------
def parabolic_peak(ts, vs, i):
    """Three-point parabolic interpolation (assumes near-uniform spacing).
    Returns refined peak time around center index i.
    """
    if i <= 0 or i >= len(vs) - 1:
        return ts[i]
    t1, t2, t3 = ts[i - 1], ts[i], ts[i + 1]
    v1, v2, v3 = vs[i - 1], vs[i], vs[i + 1]
    denom = (v1 - 2 * v2 + v3)
    if denom == 0:
        return t2
    # note: (t3 - t1)/2 ~ sample interval (if uniform)
    t_peak = t2 + 0.5 * ((v1 - v3) / denom) * (t3 - t1) / 2.0
    return t_peak


def _quad_vertex(ts, vs, idxs):
    """Quadratic least-squares fit on points idxs, return vertex time t*.
    Uses centering/scaling for numerical stability and clamps inside range.
    """
    t = np.asarray(ts, float)[idxs]
    v = np.asarray(vs, float)[idxs]
    n = t.size
    if n < 3:
        return t[np.argmax(v)]

    # 3-point exact fit (stable by centering)
    if n == 3:
        t0 = t[1]
        u = t - t0
        A = np.c_[u * u, u, np.ones_like(u)]
        a, b, c = np.linalg.solve(A, v)
        if abs(a) < 1e-15:
            return t[np.argmax(v)]
        u_peak = -b / (2.0 * a)
        t_peak = t0 + u_peak
        return float(np.clip(t_peak, t.min(), t.max()))

    # multi-point least squares with centering & scaling
    t0 = t.mean()
    u = t - t0
    s = np.max(np.abs(u))
    if s == 0:
        return float(t0)
    u /= s
    A = np.c_[u * u, u, np.ones_like(u)]
    a, b, c = np.linalg.lstsq(A, v, rcond=None)[0]
    if abs(a) < 1e-12:
        return t[np.argmax(v)]
    u_peak = -b / (2.0 * a)
    t_peak = t0 + u_peak * s
    return float(np.clip(t_peak, t.min(), t.max()))


def find_parabolic_peaks(ts, vs, eps=None, extra=1, min_sep=1, last_span=None, last_n=None):
    """
    Detect local peaks (supports flat-top peaks). Return list of t_peak.
    Params:
      - ts, vs: arrays (can be non-uniform time)
      - eps: tolerance for equality in diff; default auto by range
      - extra: include +/- extra points around candidate for LS quad fit
      - min_sep: minimal index separation between two accepted peaks
      - last_span: only search in [ts[-1]-last_span, ts[-1]] window (same unit as ts)
      - last_n: return only latest N peaks (after time-windowing)
    """
    ts = np.asarray(ts, float)
    vs = np.asarray(vs, float)
    if ts.size < 3:
        return []

    # drop NaN
    good = np.isfinite(ts) & np.isfinite(vs)
    ts, vs = ts[good], vs[good]
    if ts.size < 3:
        return []

    # time window
    if last_span is not None and ts.size >= 2:
        cutoff = ts[-1] - float(last_span)
        m = ts >= cutoff
        if np.count_nonzero(m) >= 3:
            ts, vs = ts[m], vs[m]

    n = len(vs)
    if n < 3:
        return []

    dv = np.diff(vs)
    rng = np.nanmax(vs) - np.nanmin(vs)
    if eps is None:
        eps = 1e-6 * (rng if rng > 0 else (np.nanmax(np.abs(vs)) + 1.0))

    # slope sign: +1 up, -1 down, 0 flat
    sign = np.where(dv > eps, 1, np.where(dv < -eps, -1, 0))

    peaks = []
    i = 1
    last_taken = -min_sep - 1
    while i < n - 1:
        # sharp peak: +1 -> -1
        if sign[i - 1] > 0 and sign[i] < 0:
            L = max(i - 1 - extra, 0)
            R = min(i + 1 + extra, n - 1)
            idxs = np.arange(L, R + 1)
            if i - last_taken >= min_sep:
                peaks.append(_quad_vertex(ts, vs, idxs))
                last_taken = i
            i += 1
            continue

        # flat-top peak: +1 -> 0...0 -> -1
        if sign[i - 1] > 0 and sign[i] == 0:
            j = i
            while j < n - 1 and sign[j] == 0:
                j += 1
            if j < n - 1 and sign[j] < 0:
                s = i
                e = (j - 1) + 1  # sample index end of plateau
                L = max(s - extra, 0)
                R = min(e + extra, n - 1)
                idxs = np.arange(L, R + 1)
                if s - last_taken >= min_sep:
                    peaks.append(_quad_vertex(ts, vs, idxs))
                    last_taken = e
                i = e + 1
                continue
            else:
                i = j + 1
                continue

        i += 1

    if last_n is not None and len(peaks) > last_n:
        peaks = peaks[-int(last_n):]

    return peaks


# ------------------------- main widget -------------------------
class WaveformCaptureWindow(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.signal_names = list(main_window.fixed_variables)

        # Reference Signal default: 'pwm1' if present (case-insensitive), else first
        self.reference_signal = self._default_ref_name(self.signal_names)
        self.normalize_enabled = False
        self.show_avg_enabled = False

        # Period list & drawing budget
        self.period_list = []               # list of (start_t, end_t)
        self.overlay_count = 6              # UI-controlled (cycles to draw)

        # Process time window (seconds) for peak/period extraction
        self.process_time_s = 2.0           # default 2s

        # UI state
        self.target_checks = {}
        self.curves = []
        self.avg_curve = None
        self.avg_text_item = None
        self.last_ref_ts = None

        self._init_ui()

        # periodic refresh from reference signal
        self.period_timer = QTimer(self)
        self.period_timer.timeout.connect(self.update_reference_periods)
        self.period_timer.start(200)

    # ---------- UI ----------
    def _init_ui(self):
        layout = QVBoxLayout()
        layout.addLayout(self._create_control_panel())
        layout.addLayout(self._create_signal_checkboxes())

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel('left', 'magnitude')
        self.plot_widget.setLabel('bottom', 'Time', units='ms')
        layout.addWidget(self.plot_widget)

        self.setLayout(layout)

    def _create_control_panel(self):
        layout = QHBoxLayout()

        # Reference selector
        layout.addWidget(QLabel("Reference Signal:"))
        self.signal_box = QComboBox()
        self.signal_box.addItems(self.signal_names)
        if self.reference_signal:
            # set current to the chosen default (exact name)
            self.signal_box.setCurrentText(self.reference_signal)
        self.signal_box.currentTextChanged.connect(self.set_reference_signal)
        layout.addWidget(self.signal_box)

        # Normalize
        self.norm_check = QCheckBox("Normalize")
        self.norm_check.stateChanged.connect(lambda s: self.set_normalize(s == 2))
        layout.addWidget(self.norm_check)

        # Show Avg
        self.avg_check = QCheckBox("Show Avg Curve")
        self.avg_check.stateChanged.connect(lambda s: self.set_show_avg(s == 2))
        layout.addWidget(self.avg_check)

        # Overlay cycles (budget)
        layout.addWidget(QLabel("Overlay Cycles:"))
        self.overlay_spin = QSpinBox()
        self.overlay_spin.setRange(1, 30)
        self.overlay_spin.setValue(self.overlay_count)
        self.overlay_spin.valueChanged.connect(self.set_overlay_count)
        layout.addWidget(self.overlay_spin)

        # Process time (seconds) next to overlay cycles
        layout.addWidget(QLabel("Process Time (s):"))
        self.process_time_spin = QDoubleSpinBox()
        self.process_time_spin.setDecimals(1)
        self.process_time_spin.setRange(0.1, 3600.0)
        self.process_time_spin.setSingleStep(0.5)
        self.process_time_spin.setValue(self.process_time_s)
        self.process_time_spin.valueChanged.connect(self.set_process_time)
        layout.addWidget(self.process_time_spin)

        layout.addStretch()
        return layout

    def _create_signal_checkboxes(self):
        layout = QGridLayout()
        columns = 6
        for i, name in enumerate(self.signal_names):
            box = QCheckBox(name)
            box.setChecked(False)
            rgb = self.main_window.get_default_color(name)  # (r,g,b)
            box.setStyleSheet(f"color: rgb{rgb};")
            self.target_checks[name] = box
            layout.addWidget(box, i // columns, i % columns)
        return layout

    # ---------- UI handlers ----------
    def _default_ref_name(self, names):
        if not names:
            return None
        # prefer exact 'pwm1'
        if 'pwm1' in names:
            return 'pwm1'
        # case-insensitive match
        for n in names:
            if isinstance(n, str) and n.lower() == 'pwm1':
                return n
        return names[0]

    def set_reference_signal(self, name):
        self.reference_signal = name
        self.period_list.clear()
        self.clear_plot()
    def set_normalize(self, enabled):
        self.normalize_enabled = enabled
        axis = self.plot_widget.getAxis('bottom')
        if enabled:
            self.plot_widget.setLabel('bottom', 'Phase', units='rad')
            axis.setTicks([[(0, '0'), (np.pi, 'π'), (2 * np.pi, '2π')]])
        else:
            self.plot_widget.setLabel('bottom', 'Time', units='ms')
            axis.setTicks(None)
        self.clear_plot()

    def set_show_avg(self, enabled):
        self.show_avg_enabled = enabled
        self.update_from_main()

    def set_overlay_count(self, count):
        self.overlay_count = int(count)
        self.update_from_main()

    def set_process_time(self, seconds):
        self.process_time_s = float(seconds)
        # Recompute periods immediately on slider change
        self.update_reference_periods(force=True)

    # ---------- data updates ----------
    def update_reference_periods(self, force=False):
        if not self.isVisible():
            return
        ts, vs = self.main_window.data_model.get_series(self.reference_signal)
        if len(ts) < 10:
            return
        # Light downsampling of incoming history
        ts = ts[-5000:]
        vs = vs[-5000:]
        if not force and self.last_ref_ts == ts[-1]:
            return
        self.last_ref_ts = ts[-1]

        # process_time in same unit as ts
        proc_span = self._seconds_to_ts_units(ts, self.process_time_s)
        self.update_period_list(np.array(ts, dtype=float), np.array(vs, dtype=float),
                                process_time=proc_span, max_pairs=self.overlay_count)

        # auto-refresh the plot when reference periods change
        self.update_from_main()

    def update_period_list(self, ts, vs, process_time=None, max_pairs=None):
        """Update self.period_list using **Peak Capture** only.
        - process_time: only process the last span (same unit as ts)
        - max_pairs: keep at most this many (start, end) pairs
        """
        if len(ts) < 10:
            return

        ts = np.asarray(ts, float)
        vs = np.asarray(vs, float)

        # time-window limit
        if process_time is not None:
            cutoff = ts[-1] - float(process_time)
            m = ts >= cutoff
            if np.count_nonzero(m) >= 3:
                ts, vs = ts[m], vs[m]

        # Peak Capture: find peaks within time window; need N+1 peaks for N periods
        last_n = None if max_pairs is None else int(max_pairs) + 1
        peak_times = find_parabolic_peaks(
            ts, vs, eps=None, extra=1, min_sep=4,
            last_span=process_time, last_n=last_n
        )
        new_periods = [(peak_times[i - 1], peak_times[i]) for i in range(1, len(peak_times))]

        # Trim by max_pairs budget
        if max_pairs is not None and len(new_periods) > max_pairs:
            new_periods = new_periods[-int(max_pairs):]

        if new_periods:
            self.period_list = new_periods
        else:
            # No fresh periods detected in this window; avoid using stale ones
            self.period_list = []

    def update_from_main(self):
        if not self.isVisible() or not self.period_list:
            return

        # Gather selected target signals
        targets = [name for name, cb in self.target_checks.items() if cb.isChecked()]
        if not targets:
            self.clear_plot()
            return

        # Load only recent process_time_s window (converted to ts units), then cap to 5000 pts
        data = {}
        for name in targets:
            ts, vs = self.main_window.data_model.get_series(name)
            ts = np.asarray(ts, dtype=float); vs = np.asarray(vs, dtype=float)
            if ts.size:
                span = self._seconds_to_ts_units(ts, self.process_time_s)
                cutoff = ts[-1] - span
                m = ts >= cutoff
                if np.count_nonzero(m) >= 3:
                    ts, vs = ts[m], vs[m]
            # cap for plotting
            if ts.size > 5000:
                ts = ts[-5000:]; vs = vs[-5000:]
            data[name] = (ts, vs)

        self.process_and_plot(data)

    def process_and_plot(self, data):
        if not self.period_list:
            return

        targets = [name for name, cb in self.target_checks.items() if cb.isChecked()]
        if not targets:
            self.clear_plot()
            return

        # Determine the time window covered by current data across selected targets
        tmins, tmaxs = [], []
        for name in targets:
            ts_all, _ = data.get(name, (np.array([]), np.array([])))
            if ts_all.size:
                tmins.append(ts_all.min()); tmaxs.append(ts_all.max())
        if not tmins:
            self.clear_plot(); return
        tmin = max(tmins); tmax = min(tmaxs)
        # Keep only periods overlapping current data window
        valid_periods = [(a,b) for (a,b) in self.period_list if (b > tmin and a < tmax)]
        if not valid_periods:
            self.clear_plot(); return
        periods_to_draw = valid_periods[-min(self.overlay_count, len(valid_periods)):]
        total_curves = len(periods_to_draw) * len(targets)

        # prepare curve objects
        if len(self.curves) != total_curves:
            self.clear_plot()
            for _ in range(total_curves):
                curve = self.plot_widget.plot([], [], pen=None)
                self.curves.append(curve)

        curve_idx = 0
        for signal in targets:
            ts_all, vs_all = data.get(signal, (np.array([]), np.array([])))
            if ts_all.size < 5:
                # consume reserved curve slots with empty data
                for _ in periods_to_draw:
                    if curve_idx < len(self.curves):
                        self.curves[curve_idx].setData([], [])
                        curve_idx += 1
                continue

            base_color = self.main_window.get_default_color(signal)
            all_segments = []

            for i, (start_t, end_t) in enumerate(periods_to_draw):
                if end_t <= start_t:
                    if curve_idx < len(self.curves):
                        self.curves[curve_idx].setData([], [])
                        curve_idx += 1
                    continue

                mask = (ts_all >= start_t) & (ts_all <= end_t)
                ts = ts_all[mask]
                vs = vs_all[mask]
                if ts.size < 5:
                    if curve_idx < len(self.curves):
                        self.curves[curve_idx].setData([], [])
                        curve_idx += 1
                    continue

                # X-axis: time-zeroed or phase-normalized
                x = ts - start_t
                if self.normalize_enabled:
                    x = x / (end_t - start_t) * (2.0 * np.pi)

                # downsample each curve to at most 200 points
                if x.size > 200:
                    step = max(1, x.size // 200)
                    x = x[::step]
                    vs = vs[::step]

                alpha = int(255 * (0.3 + 0.7 * (1 - i / max(1, len(periods_to_draw)))))
                pen = pg.mkPen(color=base_color + (alpha,), width=1)
                self.curves[curve_idx].setData(x, vs, pen=pen)
                curve_idx += 1
                all_segments.append((x, vs))

            # average curve overlay (optional)
            if self.show_avg_enabled and all_segments:
                x_common = all_segments[0][0]
                y_stack = np.vstack([np.interp(x_common, x, y) for x, y in all_segments])
                y_avg = np.mean(y_stack, axis=0)

                if self.avg_curve is None:
                    self.avg_curve = self.plot_widget.plot(x_common, y_avg,
                                                           pen=pg.mkPen(color=base_color, width=4))
                else:
                    self.avg_curve.setData(x_common, y_avg)

                avg_val = float(np.mean(y_avg))
                if self.avg_text_item is None:
                    self.avg_text_item = pg.TextItem(f"{signal} Avg: {avg_val:.2f}", anchor=(0, 1))
                    self.avg_text_item.setColor(base_color)
                    self.plot_widget.addItem(self.avg_text_item)
                else:
                    self.avg_text_item.setText(f"{signal} Avg: {avg_val:.2f}")
                self.avg_text_item.setPos(x_common[-1], y_avg[-1])
            else:
                if self.avg_curve is not None:
                    self.plot_widget.removeItem(self.avg_curve)
                    self.avg_curve = None
                if self.avg_text_item is not None:
                    self.plot_widget.removeItem(self.avg_text_item)
                    self.avg_text_item = None

    # ---------- helpers ----------
    def _seconds_to_ts_units(self, ts, seconds):
        """Convert seconds to the same unit as the ts array, using median dt heuristic."""
        ts = np.asarray(ts, dtype=float)
        if ts.size < 2:
            return seconds  # fallback
        dt = float(np.median(np.diff(ts)))
        if not np.isfinite(dt) or dt == 0:
            return seconds
        # heuristic on ts unit: ms/us/ns/seconds
        if 5.0 < dt < 5000.0:
            # ts likely in ms
            return seconds * 1000.0
        elif 5000.0 <= dt < 5e6:
            # ts likely in us
            return seconds * 1e6
        elif dt >= 5e6:
            # ts likely in ns
            return seconds * 1e9
        else:
            # ts in seconds
            return seconds

    # ---------- cleanup ----------
    def clear_plot(self):
        for c in self.curves:
            self.plot_widget.removeItem(c)
        self.curves.clear()
        if self.avg_curve is not None:
            self.plot_widget.removeItem(self.avg_curve)
            self.avg_curve = None
        if self.avg_text_item is not None:
            self.plot_widget.removeItem(self.avg_text_item)
            self.avg_text_item = None

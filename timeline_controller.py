"""Shared transport clock for live history and imported replay data."""

from enum import Enum
import time

from PyQt5.QtCore import QObject, pyqtSignal


class TimelineState(Enum):
    EMPTY = "empty"
    FOLLOW_LIVE = "follow_live"
    PAUSED = "paused"
    PLAYING = "playing"


class TimelineController(QObject):
    changed = pyqtSignal()

    def __init__(self, clock=None, parent=None):
        super().__init__(parent)
        self._clock = clock or time.monotonic
        self.source_kind = "none"
        self.state = TimelineState.EMPTY
        self.start_ms = None
        self.latest_ms = None
        self.playhead_ms = None
        self.speed = 1.0
        self._last_tick_s = self._clock()

    @property
    def has_range(self):
        return (
            self.start_ms is not None
            and self.latest_ms is not None
            and self.latest_ms >= self.start_ms
        )

    @property
    def is_running(self):
        return self.state in (TimelineState.FOLLOW_LIVE, TimelineState.PLAYING)

    @property
    def is_live_edge(self):
        if self.source_kind != "live" or not self.has_range:
            return False
        return (
            self.state == TimelineState.FOLLOW_LIVE
            or self.latest_ms - self.playhead_ms <= 1.0
        )

    @property
    def live_delay_ms(self):
        if self.source_kind != "live" or not self.has_range:
            return 0.0
        return max(0.0, self.latest_ms - self.playhead_ms)

    def _emit_changed(self):
        self.changed.emit()

    def reset(self):
        self.source_kind = "none"
        self.state = TimelineState.EMPTY
        self.start_ms = None
        self.latest_ms = None
        self.playhead_ms = None
        self.speed = 1.0
        self._last_tick_s = self._clock()
        self._emit_changed()

    def begin_live(self):
        self.source_kind = "live"
        self.state = TimelineState.FOLLOW_LIVE
        self.start_ms = None
        self.latest_ms = None
        self.playhead_ms = None
        self.speed = 1.0
        self._last_tick_s = self._clock()
        self._emit_changed()

    def begin_replay(self, start_ms, latest_ms):
        start_ms = float(start_ms)
        latest_ms = max(start_ms, float(latest_ms))
        self.source_kind = "replay"
        self.state = TimelineState.PAUSED
        self.start_ms = start_ms
        self.latest_ms = latest_ms
        self.playhead_ms = start_ms
        self.speed = 1.0
        self._last_tick_s = self._clock()
        self._emit_changed()

    def update_bounds(self, start_ms, latest_ms):
        if start_ms is None or latest_ms is None:
            return
        start_ms = float(start_ms)
        latest_ms = max(start_ms, float(latest_ms))
        changed = self.start_ms != start_ms or self.latest_ms != latest_ms
        self.start_ms = start_ms
        self.latest_ms = latest_ms
        if self.state == TimelineState.FOLLOW_LIVE:
            changed = changed or self.playhead_ms != latest_ms
            self.playhead_ms = latest_ms
        elif self.playhead_ms is None:
            self.playhead_ms = start_ms
            changed = True
        else:
            clamped = min(latest_ms, max(start_ms, self.playhead_ms))
            changed = changed or clamped != self.playhead_ms
            self.playhead_ms = clamped
        if changed:
            self._emit_changed()

    def pause(self):
        if self.state not in (TimelineState.FOLLOW_LIVE, TimelineState.PLAYING):
            return
        self.state = TimelineState.PAUSED
        self._last_tick_s = self._clock()
        self._emit_changed()

    def play(self):
        if not self.has_range:
            return
        if self.source_kind == "live" and self.latest_ms - self.playhead_ms <= 1.0:
            self.go_live()
            return
        if self.source_kind == "replay" and self.playhead_ms >= self.latest_ms:
            self.playhead_ms = self.start_ms
        self.state = TimelineState.PLAYING
        self._last_tick_s = self._clock()
        self._emit_changed()

    def toggle_playback(self):
        if self.is_running:
            self.pause()
        else:
            self.play()

    def seek(self, timestamp_ms):
        if not self.has_range:
            return
        clamped = min(self.latest_ms, max(self.start_ms, float(timestamp_ms)))
        changed = clamped != self.playhead_ms or self.state != TimelineState.PAUSED
        self.playhead_ms = clamped
        self.state = TimelineState.PAUSED
        self._last_tick_s = self._clock()
        if changed:
            self._emit_changed()

    def go_live(self):
        if self.source_kind != "live":
            return
        self.state = TimelineState.FOLLOW_LIVE
        if self.latest_ms is not None:
            self.playhead_ms = self.latest_ms
        self._last_tick_s = self._clock()
        self._emit_changed()

    def set_speed(self, speed):
        speed = float(speed)
        if speed <= 0.0 or speed == self.speed:
            return
        self.speed = speed
        self._last_tick_s = self._clock()
        self._emit_changed()

    def tick(self):
        now_s = self._clock()
        elapsed_ms = max(0.0, (now_s - self._last_tick_s) * 1000.0)
        self._last_tick_s = now_s
        if self.state != TimelineState.PLAYING or not self.has_range:
            return
        next_playhead = self.playhead_ms + elapsed_ms * self.speed
        if next_playhead < self.latest_ms:
            self.playhead_ms = next_playhead
        elif self.source_kind == "live":
            self.playhead_ms = self.latest_ms
            self.state = TimelineState.FOLLOW_LIVE
        else:
            self.playhead_ms = self.latest_ms
            self.state = TimelineState.PAUSED
        self._emit_changed()

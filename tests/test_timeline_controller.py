import unittest

from timeline_controller import TimelineController, TimelineState


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class TimelineControllerTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.timeline = TimelineController(clock=self.clock)

    def test_live_follows_latest_until_paused(self):
        self.timeline.begin_live()
        self.timeline.update_bounds(1000.0, 2000.0)
        self.assertEqual(self.timeline.playhead_ms, 2000.0)

        self.timeline.pause()
        self.timeline.update_bounds(1000.0, 2600.0)

        self.assertEqual(self.timeline.playhead_ms, 2000.0)
        self.assertEqual(self.timeline.live_delay_ms, 600.0)

    def test_live_history_plays_then_returns_to_live_edge(self):
        self.timeline.begin_live()
        self.timeline.update_bounds(0.0, 2000.0)
        self.timeline.seek(500.0)
        self.timeline.set_speed(2.0)
        self.timeline.play()
        self.clock.advance(0.5)
        self.timeline.tick()
        self.assertEqual(self.timeline.playhead_ms, 1500.0)
        self.assertEqual(self.timeline.state, TimelineState.PLAYING)

        self.clock.advance(0.5)
        self.timeline.tick()
        self.assertEqual(self.timeline.playhead_ms, 2000.0)
        self.assertEqual(self.timeline.state, TimelineState.FOLLOW_LIVE)

    def test_replay_starts_paused_and_stops_at_end(self):
        self.timeline.begin_replay(1000.0, 3000.0)
        self.assertEqual(self.timeline.state, TimelineState.PAUSED)
        self.assertEqual(self.timeline.playhead_ms, 1000.0)

        self.timeline.play()
        self.clock.advance(3.0)
        self.timeline.tick()

        self.assertEqual(self.timeline.playhead_ms, 3000.0)
        self.assertEqual(self.timeline.state, TimelineState.PAUSED)

    def test_replay_at_end_restarts_from_beginning(self):
        self.timeline.begin_replay(1000.0, 3000.0)
        self.timeline.seek(3000.0)
        self.timeline.play()

        self.assertEqual(self.timeline.playhead_ms, 1000.0)
        self.assertEqual(self.timeline.state, TimelineState.PLAYING)

    def test_seek_clamps_and_pauses(self):
        self.timeline.begin_replay(1000.0, 3000.0)
        self.timeline.play()
        self.timeline.seek(5000.0)

        self.assertEqual(self.timeline.playhead_ms, 3000.0)
        self.assertEqual(self.timeline.state, TimelineState.PAUSED)


if __name__ == "__main__":
    unittest.main()

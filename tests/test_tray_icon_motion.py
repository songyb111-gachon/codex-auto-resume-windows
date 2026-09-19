"""The notification-area icon's motion (v0.6.5).

The icon speaks a smaller language than the windows' status light: watching breathes and now and
then turns once, recovering keeps turning, paused is grey and still, a problem is its colour with
one pulse. Everything that decides a frame is a pure function of the state and a clock, tested
here as tables; the frames are pure pixels, pinned by a digest; and the icon's own timer, its
swaps and its HICONs are exercised on Windows against a fake shell, where a leak would show.
"""
from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import unittest.mock

from codex_auto_resume import brand, control, tray, tray_popup as popup

ROOT = Path(__file__).resolve().parents[1]
MOTION = tray.ICON_MOTION
TOP = MOTION["levels"] - 1
EVERY, TURN = MOTION["turn_every_ms"], MOTION["turn_ms"]


# ------------------------------------------------------------------------------ the states
class StateTests(unittest.TestCase):
    def test_the_icon_has_five_states_each_a_brand_status_light_state(self):
        self.assertEqual(tray.ICON_STATES, ("watching", "recovering", "idle", "attention", "failed"))
        self.assertEqual(set(tray.ICON_BRAND_STATE), set(tray.ICON_STATES))
        self.assertEqual(tray.ICON_BRAND_STATE, {"watching": "monitoring", "recovering": "recovering",
                                                 "idle": "idle", "attention": "attention", "failed": "failed"})
        for state, light in tray.ICON_BRAND_STATE.items():
            with self.subTest(state):
                self.assertIn(light, brand.STATUS_FILL)
        # 'watching' is not a brand state, which is why the map exists: brand alone would draw it grey.
        self.assertNotIn("watching", brand.STATUS_FILL)
        self.assertEqual(brand.status_fill("watching"), "idle")
        self.assertIn("monitoring", brand.GLOW_BREATHES)
        self.assertIn("recovering", brand.GLOW_BREATHES)
        self.assertEqual(set(brand.GLOW_PULSES), {"attention", "failed"})

    def test_anything_unknown_is_idle_grey(self):
        for unknown in ("", None, "stopped", "monitoring", "paused"):
            with self.subTest(unknown):
                self.assertEqual(tray.icon_brand_state(unknown), "idle")
                self.assertEqual(tray.icon_head_colour(unknown), brand.rgb(brand.LIGHT["idle"]))

    def test_every_snapshot_the_tick_can_produce(self):
        cases = [
            ({}, {}, "watching"), (None, {}, "watching"),
            ({"enabled": True, "waiting": 0, "running": 0, "next_at": None}, {}, "watching"),
            ({"enabled": True, "waiting": 3, "running": 0, "next_at": 100.0}, {}, "watching"),   # waiting
            ({"enabled": True, "waiting": 3, "running": 0, "next_at": 0.0}, {}, "watching"),     # checking
            ({"enabled": True, "waiting": 0, "running": 1}, {}, "recovering"),
            ({"enabled": True, "waiting": 2, "running": 1}, {}, "recovering"),
            ({"enabled": False, "waiting": 2, "running": 0}, {}, "idle"),
            ({"enabled": False, "running": 1}, {}, "idle"),                  # paused outranks what runs
            ({"enabled": True, "running": 1}, {"attention": True}, "attention"),
            ({"enabled": False}, {"attention": True}, "attention"),
            ({}, {"attention": True}, "attention"),
            ({"enabled": True}, {"failed": True}, "failed"),
            ({"enabled": True}, {"failed": True, "attention": True}, "failed"),
        ]
        for snapshot, options, expected in cases:
            with self.subTest(snapshot=snapshot, options=options):
                self.assertEqual(tray.icon_state(snapshot, **options), expected)

    def test_the_rule_read_from_a_status_light_is_the_tick_s_rule(self):
        """The window's taskbar button knows its header light's state, not the tick's snapshot: ICON_FOR_LIGHT is
        icon_state read from that side, for every snapshot the tick can produce and every light there is."""
        self.assertEqual(tray.ICON_FOR_LIGHT, {
            "monitoring": "watching", "waiting": "watching", "checking": "watching", "recovering": "recovering",
            "paused": "idle", "idle": "idle", "attention": "attention", "failed": "failed"})
        self.assertEqual(set(tray.ICON_FOR_LIGHT), set(brand.STATUS_FILL))
        self.assertEqual(set(tray.ICON_FOR_LIGHT.values()), set(tray.ICON_STATES))
        for state, light in tray.ICON_BRAND_STATE.items():
            with self.subTest(state=state):
                self.assertEqual(tray.icon_state_for_light(light), state)
        for unknown in ("", None, "stopped", "watching", "Monitoring"):
            with self.subTest(unknown=unknown):
                self.assertEqual(tray.icon_state_for_light(unknown), "idle")
        now = 1000.0
        snapshots = [{}, None, {"enabled": True, "waiting": 0, "running": 0, "next_at": None},
                     {"enabled": True, "waiting": 3, "running": 0, "next_at": now + 100},
                     {"enabled": True, "waiting": 3, "running": 0, "next_at": now - 1},
                     {"enabled": True, "waiting": 0, "running": 1}, {"enabled": True, "waiting": 2, "running": 1},
                     {"enabled": False, "waiting": 2, "running": 0}, {"enabled": False, "running": 1}, {"enabled": False}]
        for snapshot in snapshots:
            for attention in (False, True):
                for failed in (False, True):
                    light = "failed" if failed else popup.snapshot_activity(snapshot, now, attention=attention)
                    with self.subTest(snapshot=snapshot, attention=attention, failed=failed, light=light):
                        self.assertEqual(tray.icon_state_for_light(light),
                                         tray.icon_state(snapshot, attention=attention, failed=failed))

    def test_the_head_is_the_mark_s_accent_while_running_and_the_state_s_colour_otherwise(self):
        accent = brand.rgb(brand.ICON_ACCENT)
        self.assertEqual(tray.icon_head_colour("watching"), accent)
        self.assertEqual(tray.icon_head_colour("recovering"), accent)
        # On the badge's deep blue: idle's light grey, and the dark palette's amber and red, which
        # are the ones made to read on a dark ground.
        self.assertEqual(tray.icon_head_colour("idle"), brand.rgb(brand.LIGHT["idle"]))
        self.assertEqual(tray.icon_head_colour("attention"), brand.rgb(brand.DARK["attention"]))
        self.assertEqual(tray.icon_head_colour("failed"), brand.rgb(brand.DARK["danger"]))
        # Idle's colour is brand's `idle`, never `paused`.
        self.assertEqual(brand.status_fill(tray.icon_brand_state("idle")), "idle")
        ground = brand.mix(brand.ICON_TOP, brand.ICON_BOTTOM, 0.3)       # the badge round the head
        for state in ("idle", "attention", "failed"):
            with self.subTest(state):
                colour = "#%02X%02X%02X" % tray.icon_head_colour(state)
                self.assertGreaterEqual(brand.contrast(colour, ground), 2.5)

    def test_the_icon_s_numbers_are_its_own_and_not_in_brand_glow(self):
        """Every GLOW key is generated into the window's status light (Brand.cs), which draws none of these. Since
        v0.6.5 the window's taskbar button wears this icon's motion, and reads them from Brand.Mark alone."""
        self.assertFalse(set(MOTION) & set(brand.GLOW))
        source = (ROOT / "gui" / "Brand.cs").read_text(encoding="utf-8")
        light, _, mark = source.partition("        internal static class Mark\n")
        self.assertTrue(mark, "Brand.cs declares no Brand.Mark")
        for name in ("TurnEvery", "TurnMs", "BreatheFrame", "TurnFrame", "IconMotion"):
            self.assertNotIn(name, light)
        for declared in ("internal const double TurnEveryMs = 30000;", "internal const double TurnMs = 2400;",
                         "internal const int BreatheFrameMs = 300;", "internal const int TurnFrameMs = 200;",
                         "internal const int Positions = 24;", "internal const int Levels = 9;",
                         "internal const double Dim = 0.6;"):
            self.assertIn(declared, mark)
        self.assertEqual((EVERY, TURN), (30000, 2400))
        self.assertEqual((MOTION["breathe_frame_ms"], MOTION["turn_frame_ms"]), (300, 200))


# ------------------------------------------------------------------------------ the phases
class PhaseTests(unittest.TestCase):
    def test_watching_breathes_on_the_monitoring_rhythm_from_full_colour(self):
        cycle = brand.GLOW["monitoring_ms"]
        self.assertEqual(tray.icon_frame("watching", 0), (0, TOP))
        self.assertEqual(tray.icon_frame("watching", cycle / 2.0), (0, 0))
        self.assertEqual(tray.icon_frame("watching", cycle), (0, TOP))
        levels = [tray.icon_frame("watching", elapsed)[1] for elapsed in range(0, cycle // 2, 50)]
        self.assertEqual(levels, sorted(levels, reverse=True))
        self.assertEqual(set(range(TOP + 1)), {tray.icon_frame("watching", elapsed)[1]
                                               for elapsed in range(0, cycle, 10)})

    def test_watching_turns_once_about_every_thirty_seconds_and_breathes_under_it(self):
        start = EVERY - TURN
        for elapsed in (0, 1000, 10000, start - 1):
            self.assertIsNone(tray.icon_turn("watching", elapsed))
            self.assertEqual(tray.icon_frame("watching", elapsed)[0], 0)
        self.assertAlmostEqual(tray.icon_turn("watching", start), 0.0)
        self.assertAlmostEqual(tray.icon_turn("watching", start + TURN / 2.0), 180.0)
        self.assertIsNone(tray.icon_turn("watching", EVERY))                 # home again, and resting
        turn = [tray.icon_turn("watching", start + ms) for ms in range(0, TURN, 20)]
        self.assertEqual(turn, sorted(turn))
        # Eased in and out: slow at both ends, fastest halfway.
        self.assertLess(turn[1] - turn[0], turn[len(turn) // 2 + 1] - turn[len(turn) // 2])
        positions = [tray.icon_frame("watching", start + ms)[0] for ms in range(0, TURN, 100)]
        self.assertEqual(positions[0], 0)
        self.assertGreaterEqual(len(set(positions)), MOTION["positions"] // 2)
        # The breath carries on under the turn.
        self.assertEqual(tray.icon_frame("watching", start + 700)[1],
                         tray._breath_level(start + 700, brand.GLOW["monitoring_ms"]))
        # And the next one comes a period later.
        self.assertIsNotNone(tray.icon_turn("watching", 2 * EVERY - TURN + 1))

    def test_recovering_turns_all_the_time_on_the_arc_rhythm_with_the_quicker_breath(self):
        arc = brand.GLOW["arc_ms"]
        self.assertAlmostEqual(tray.icon_turn("recovering", arc / 4.0), 90.0)
        self.assertAlmostEqual(tray.icon_turn("recovering", arc), 0.0)
        for elapsed in (0, 5000, 31234):
            self.assertIsNotNone(tray.icon_turn("recovering", elapsed))
        self.assertEqual(tray.icon_frame("recovering", arc / 2.0)[0], MOTION["positions"] // 2)
        breath = brand.GLOW["recovering_ms"]
        self.assertEqual(tray.icon_frame("recovering", breath / 2.0)[1], 0)
        self.assertLess(breath, brand.GLOW["monitoring_ms"])

    def test_paused_is_still_and_a_problem_pulses_once_then_holds(self):
        for elapsed in (0, 777, 15000, 29000):
            self.assertEqual(tray.icon_frame("idle", elapsed, 0), (0, TOP))
        pulse = brand.GLOW["attention_ms"]
        for state in ("attention", "failed"):
            with self.subTest(state):
                self.assertEqual(tray.icon_frame(state, 12345, 0), (0, TOP))
                self.assertEqual(tray.icon_frame(state, 12345, pulse / 2.0), (0, 0))
                for settled in (pulse, pulse + 1, 99999, None, -5):
                    self.assertEqual(tray.icon_frame(state, 12345, settled), (0, TOP))
                self.assertIsNotNone(tray.icon_frame_ms(state, 0, pulse / 2.0))
                self.assertIsNone(tray.icon_frame_ms(state, 0, pulse))
                self.assertIsNone(tray.icon_frame_ms(state, 0, None))

    def test_reduced_motion_holds_every_state_at_its_rest(self):
        for state in tray.ICON_STATES + ("unknown",):
            for elapsed in (0, 1600, EVERY - TURN + 400, 99999):
                with self.subTest(state=state, elapsed=elapsed):
                    self.assertEqual(tray.icon_frame(state, elapsed, 100, reduced=True), (0, TOP))
                    self.assertIsNone(tray.icon_frame_ms(state, elapsed, 100, reduced=True))

    def test_frames_come_about_three_a_second_while_breathing_and_five_while_turning(self):
        self.assertEqual(tray.icon_frame_ms("watching", 0), 300)
        self.assertEqual(tray.icon_frame_ms("watching", EVERY - TURN + 10), 200)
        self.assertEqual(tray.icon_frame_ms("watching", EVERY + 10), 300)
        self.assertEqual(tray.icon_frame_ms("recovering", 0), 200)
        self.assertIsNone(tray.icon_frame_ms("idle", 0, 0))

    def test_the_breath_s_levels_run_from_the_colour_toward_the_badge(self):
        colour = brand.rgb(brand.ICON_ACCENT)
        self.assertEqual(tray.icon_level_colour(colour, TOP), colour)
        self.assertEqual(tray.icon_level_colour(colour, TOP + 5), colour)
        dim = tray.icon_level_colour(colour, 0)
        self.assertEqual(dim, tuple(int(round(a + (b - a) * MOTION["dim"]))
                                    for a, b in zip(colour, brand.rgb(brand.ICON_BOTTOM))))
        lums = [brand.luminance("#%02X%02X%02X" % tray.icon_level_colour(colour, level)) for level in range(TOP + 1)]
        self.assertEqual(lums, sorted(lums))


class MotionRuleTests(unittest.TestCase):
    def test_any_one_reason_holds_it_still(self):
        self.assertTrue(tray.icon_motion_allowed())
        reasons = ("reduced", "contrast", "battery_saver", "locked", "hidden")
        for reason in reasons:
            with self.subTest(reason):
                self.assertFalse(tray.icon_motion_allowed(**{reason: True}))
        self.assertFalse(tray.icon_motion_allowed(frames=False))
        self.assertFalse(tray.icon_motion_allowed(frames=None))
        for first in reasons:
            for second in reasons:
                self.assertFalse(tray.icon_motion_allowed(**{first: True, second: True}))


# ------------------------------------------------------------------------------ the frames
def bgra(rgba):
    out = bytearray(rgba)
    out[0::4], out[2::4] = rgba[2::4], rgba[0::4]
    return bytes(out)


class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = {size: tray.IconFrames(size) for size in (16, 20, 24, 32)}

    def test_the_head_in_its_place_in_the_accent_is_the_ico_s_own_image(self):
        accent = brand.rgb(brand.ICON_ACCENT)
        for size, frames in self.frames.items():
            with self.subTest(size=size):
                self.assertEqual(frames.compose(0, accent), bgra(brand.icon_render(size)))

    def test_every_position_moves_only_the_head_and_goes_once_round(self):
        accent = brand.rgb(brand.ICON_ACCENT)
        frames = self.frames[32]
        home = frames.compose(0, accent)
        seen = set()
        angles = []
        for position in range(MOTION["positions"]):
            frame = frames.compose(position, accent)
            self.assertEqual(len(frame), 32 * 32 * 4)
            seen.add(frame)
            # Where the head is: the pixels closest to its colour, weighted.
            total = sx = sy = 0.0
            for index in range(0, len(frame), 4):
                b, g, r, a = frame[index:index + 4]
                weight = max(0, 90 - (abs(r - accent[0]) + abs(g - accent[1]) + abs(b - accent[2])))
                x, y = (index // 4) % 32 + 0.5, (index // 4) // 32 + 0.5
                total += weight
                sx += weight * x
                sy += weight * y
            angle = math.degrees(math.atan2(-(sy / total - 16), sx / total - 16)) % 360
            angles.append(angle)
        self.assertEqual(len(seen), MOTION["positions"])
        for position, angle in enumerate(angles):
            expected = (brand.ICON_SHAPE["arc_end"] + 360.0 * position / MOTION["positions"]) % 360
            difference = (angle - expected + 180) % 360 - 180
            self.assertLess(abs(difference), 8.0, (position, angle, expected))
        self.assertEqual(frames.compose(0, accent), home)

    def test_the_badge_is_composited_last_exactly_as_the_badge_icon_does(self):
        for size, frames in self.frames.items():
            for token in ("waiting", "active", "paused", "attention"):
                with self.subTest(size=size, token=token):
                    colour = brand.rgb(brand.LIGHT[token])
                    expected = bytearray(frames.compose(5, (10, 200, 30)))
                    popup.composite_badge(expected, size, size, colour)
                    self.assertEqual(frames.compose(5, (10, 200, 30), colour), bytes(expected))

    def test_a_colour_touches_the_head_and_nothing_else(self):
        frames = self.frames[24]
        one, other = frames.compose(7, (255, 0, 0)), frames.compose(7, (0, 0, 255))
        box = brand.icon_head_box(24, brand.ICON_SHAPE["arc_end"] + 360.0 * 7 / MOTION["positions"])
        for index in range(0, len(one), 4):
            x, y = (index // 4) % 24, (index // 4) // 24
            if not (box[0] <= x < box[2] and box[1] <= y < box[3]):
                self.assertEqual(one[index:index + 4], other[index:index + 4])
        self.assertNotEqual(one, other)

    def test_the_frame_table_is_pinned(self):
        """A change to the mark, its colours or the breath's steps shows up in review."""
        frames = self.frames[16]
        digest = hashlib.sha256()
        for state in tray.ICON_STATES:
            colour = tray.icon_head_colour(state)
            for position in range(MOTION["positions"]):
                digest.update(frames.compose(position, colour))
            for level in range(TOP + 1):
                digest.update(frames.compose(0, tray.icon_level_colour(colour, level),
                                             brand.rgb(brand.LIGHT["waiting"])))
        self.assertEqual(digest.hexdigest(), "f5f352ebfee0b20959e7d5755b345334d7a1edc176a0dc93d2ab257e9d2473f8")

    def test_composed_frames_are_kept_and_the_store_is_bounded(self):
        frames = tray.IconFrames(16)
        first = frames.compose(3, (1, 2, 3))
        self.assertIs(frames.compose(3, (1, 2, 3)), first)
        for value in range(MOTION["cache"] + 40):
            frames.compose(value % MOTION["positions"], (value % 256, 0, 0))
        self.assertLessEqual(len(frames._cache), MOTION["cache"])


class BudgetTests(unittest.TestCase):
    def test_every_icon_size_is_built_well_inside_its_budget(self):
        for size in (16, 20, 24, 28, 32, 40):
            with self.subTest(size=size):
                started = time.perf_counter()
                self.assertIsNotNone(tray.build_icon_frames(size))
                self.assertLess((time.perf_counter() - started) * 1000.0, MOTION["build_budget_ms"] / 4.0)

    def test_over_budget_is_no_motion_rather_than_an_exception(self):
        ticks = iter((0.0, MOTION["build_budget_ms"] / 1000.0 + 1.0))
        self.assertIsNone(tray.build_icon_frames(16, clock=lambda: next(ticks)))

    def test_a_nonsense_size_raises_where_the_building_thread_catches_it(self):
        with self.assertRaises(ValueError):
            tray.IconFrames(0)


# ------------------------------------------------------------------------ the icon, on Windows
class FakeUser32:
    """Timers on a window that does not exist, recorded instead of set."""

    def __init__(self):
        self.timers = {}
        self.calls = []

    def SetTimer(self, hwnd, ident, interval, proc):
        self.calls.append(("set", ident, interval))
        self.timers[ident] = interval
        return ident

    def KillTimer(self, hwnd, ident):
        self.calls.append(("kill", ident))
        self.timers.pop(ident, None)
        return True


class TimerTests(unittest.TestCase):
    """The frame timer runs only while something moves, at the interval the moment wants."""

    def make(self, state="watching", allowed=True):
        icon = tray.Tray(strings={})
        icon._hwnd = 12345
        icon._frames = object.__new__(tray.IconFrames)
        icon._icon_state = state
        icon._motion_allowed = allowed
        return icon

    def sync(self, icon, now):
        fake = FakeUser32()
        with unittest.mock.patch.object(tray, "_dll", lambda name: fake), \
                unittest.mock.patch.object(tray.time, "monotonic", lambda: now):
            icon._sync_motion()
        return fake

    def test_the_timers_are_the_tick_and_the_frame_and_the_tick_is_unchanged(self):
        self.assertEqual((tray.TIMER_TICK, tray.TIMER_FRAME), (1, 2))

    def test_breathing_then_turning_then_breathing(self):
        icon = self.make()
        base = icon._epoch
        fake = self.sync(icon, base + 1.0)
        self.assertEqual(fake.timers, {2: 300})
        fake = self.sync(icon, base + (EVERY - TURN + 100) / 1000.0)
        self.assertEqual(fake.timers, {2: 200})
        fake = self.sync(icon, base + (EVERY + 100) / 1000.0)
        self.assertEqual(fake.timers, {2: 300})
        # Unchanged intervals ask Windows for nothing.
        fake = self.sync(icon, base + (EVERY + 400) / 1000.0)
        self.assertEqual(fake.calls, [])

    def test_nothing_moving_means_no_timer_at_all(self):
        for state, allowed in (("idle", True), ("watching", False), ("recovering", False)):
            with self.subTest(state=state, allowed=allowed):
                icon = self.make(state, allowed)
                icon._motion_ms = 300                      # as if it had been running
                fake = self.sync(icon, icon._epoch + 5.0)
                self.assertEqual(fake.calls, [("kill", 2)])
                self.assertIsNone(icon._motion_ms)
        icon = self.make()
        icon._frames = False                                # the table could not be built
        icon._motion_ms = 200
        self.assertEqual(self.sync(icon, icon._epoch + 1.0).calls, [("kill", 2)])

    def test_a_pulse_runs_the_timer_until_it_is_over(self):
        icon = self.make("attention")
        icon._state_since = icon._epoch
        self.assertEqual(self.sync(icon, icon._epoch + 0.5).timers, {2: 300})
        self.assertEqual(self.sync(icon, icon._epoch + 2.0).calls, [("kill", 2)])


class ObserveTests(unittest.TestCase):
    """What the one-second tick asks Windows, and when it asks at all."""

    def observe(self, snapshot, *, reduced=False, contrast=False, saver=False, rect=(0, 0, 16, 16),
                locked=False):
        icon = tray.Tray(strings={})
        icon._hwnd = 12345
        icon._frames = object.__new__(tray.IconFrames)
        icon._session_locked = locked
        asked = []

        def rect_of(hwnd, uid=1):
            asked.append("rect")
            return rect
        with unittest.mock.patch.object(popup, "reduced_motion", lambda: asked.append("reduced") or reduced), \
                unittest.mock.patch.object(popup, "high_contrast", lambda: asked.append("contrast") or contrast), \
                unittest.mock.patch.object(tray, "battery_saver", lambda: asked.append("saver") or saver), \
                unittest.mock.patch.object(popup, "icon_rect", rect_of):
            icon._observe(snapshot)
        return icon, asked

    def test_a_watching_icon_may_move_when_nothing_holds_it(self):
        icon, asked = self.observe({"enabled": True})
        self.assertEqual(icon._icon_state, "watching")
        self.assertTrue(icon._motion_allowed)
        self.assertIn("rect", asked)

    def test_each_reason_holds_it_still(self):
        for options in ({"reduced": True}, {"contrast": True}, {"saver": True}, {"locked": True}, {"rect": None}):
            with self.subTest(options):
                icon, asked = self.observe({"enabled": True}, **options)
                self.assertFalse(icon._motion_allowed)
                if "rect" not in options:
                    self.assertNotIn("rect", asked)        # the shell is not asked once something holds it

    def test_a_still_state_asks_windows_nothing(self):
        icon, asked = self.observe({"enabled": False})
        self.assertEqual(icon._icon_state, "idle")
        self.assertFalse(icon._motion_allowed)
        self.assertEqual(asked, [])

    def test_the_badge_token_is_the_one_the_badge_always_had(self):
        icon, _ = self.observe({"enabled": True, "waiting": 2, "next_at": time.time() + 60})
        self.assertEqual(icon._badge_token, "waiting")
        icon, _ = self.observe({"enabled": True, "running": 1})
        self.assertEqual((icon._icon_state, icon._badge_token), ("recovering", "active"))

    def test_a_locked_or_disconnected_session_stops_it_and_unlocking_lets_it_go(self):
        icon = tray.Tray(strings={})
        with unittest.mock.patch.object(icon, "_refresh", lambda: None):
            icon._session_changed(tray.WTS_SESSION_LOCK)
            self.assertTrue(icon._session_locked)
            icon._session_changed(tray.WTS_SESSION_UNLOCK)
            self.assertFalse(icon._session_locked)
            icon._session_changed(tray.WTS_CONSOLE_DISCONNECT)
            self.assertTrue(icon._session_away)
            icon._session_changed(tray.WTS_REMOTE_CONNECT)
            self.assertFalse(icon._session_away)


class StoredReduceMotionTests(unittest.TestCase):
    """Reduce motion saved from the window holds the icon at its next one-second tick.

    The watcher takes up a changed settings file only at its own tick, poll_seconds away - 30 s
    by default and up to an hour - and a Save from the window wakes nothing. The icon learned of
    the setting only there, or when its popup or menu opened, so somebody who had just turned
    Reduce motion on watched it breathe and turn for up to that long. It looks for itself now,
    on the tick that decides whether it may move: one look at the file's stamp while there is
    something to move, a read only when the file changed.
    """

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.control = control.Control(Path(folder.name))       # a scratch home, never the real one
        self.control.update_settings({"reduce_motion": False})
        self.reads = 0
        read = self.control.get_settings

        def counted():
            self.reads += 1
            return read()
        self.control.get_settings = counted
        self.addCleanup(popup.set_reduce_motion, popup._reduce_motion_setting)
        popup.set_reduce_motion(False)
        self.logged = []
        self.icon = tray.Tray(strings={}, control=self.control, log=self.logged.append)
        self.icon._hwnd = 12345
        self.icon._frames = object.__new__(tray.IconFrames)

    def tick(self, snapshot=None):
        """The motion half of one tick. Windows' animations on, no High Contrast, no battery saver
        and the icon on the taskbar: the product's own Reduce motion is all that can hold it."""
        with unittest.mock.patch.object(popup, "reduced_motion", lambda: popup._reduce_motion_setting), \
                unittest.mock.patch.object(popup, "high_contrast", lambda: False), \
                unittest.mock.patch.object(tray, "battery_saver", lambda: False), \
                unittest.mock.patch.object(popup, "icon_rect", lambda hwnd, uid=1: (0, 0, 16, 16)):
            self.icon._observe(snapshot or {"enabled": True})
        return self.icon._motion_allowed

    def store(self, **changes):
        """What the window's Save does: the control layer writes the file, and nothing is woken."""
        path = self.control.settings_path()
        before = path.stat().st_mtime_ns
        self.control.update_settings(changes)
        while path.stat().st_mtime_ns == before:                # never two writes inside one stamp
            time.sleep(0.01)
            self.control.update_settings(changes)

    def test_a_reduce_motion_saved_from_the_window_holds_the_icon_at_the_next_tick(self):
        self.assertTrue(self.tick())
        self.store(reduce_motion=True)
        self.assertFalse(self.tick(), "the icon kept moving until the watcher's own tick")
        self.store(reduce_motion=False)
        self.assertTrue(self.tick())
        self.assertEqual(self.logged, [])

    def test_a_watcher_tick_that_read_the_file_just_before_the_save_is_overruled_a_second_later(self):
        self.store(reduce_motion=True)
        self.assertFalse(self.tick())
        popup.set_reduce_motion(False)                          # the watcher, with what it read a moment before
        self.assertFalse(self.tick())

    def test_the_file_is_read_again_only_when_it_changed(self):
        self.tick()
        reads = self.reads
        for _ in range(5):
            self.tick()
        self.assertEqual(self.reads, reads)
        self.store(reduce_motion=True)
        self.tick()
        self.assertEqual(self.reads, reads + 1)

    def test_an_icon_with_nothing_to_move_reads_nothing(self):
        self.store(reduce_motion=True)
        self.assertFalse(self.tick({"enabled": False}))          # paused: grey and still already
        self.assertEqual(self.reads, 0)

    def test_an_unreadable_file_keeps_the_setting_there_is_and_says_so_once(self):
        popup.set_reduce_motion(True)
        read = self.control.get_settings
        with unittest.mock.patch.object(self.control, "get_settings", side_effect=OSError("locked")):
            for _ in range(3):
                self.assertFalse(self.tick())
        self.assertEqual(self.logged, ["tray settings read failed (OSError)"])
        self.control.get_settings = read
        self.assertTrue(self.tick(), "the file, readable again, says motion is allowed")
        self.assertEqual(len(self.logged), 1)


@unittest.skipUnless(os.name == "nt", "icon handles are Windows'")
class SwapTests(unittest.TestCase):
    """Frames swapped on a fake shell: the real HICONs, made and destroyed."""

    def make(self):
        icon = tray.Tray(strings={}, log=lambda message: self.logged.append(message))
        icon._hwnd = 12345
        icon._icon = 1                                     # a base icon exists; never drawn here
        icon._frames = tray.IconFrames(16)
        icon._icon_state = "recovering"
        icon._motion_allowed = True
        icon._badge_token = "active"
        icon._notify_icon = lambda: True                   # the shell is not told
        icon._sync_motion = lambda: None
        return icon

    def setUp(self):
        self.logged = []

    def test_five_hundred_frames_hold_two_icons_at_most_and_leak_nothing(self):
        original = tray._dll
        real = original("user32")
        popup._declare()
        alive = set()
        most = [0]
        made = popup._icon_from_pixels

        def making(pixels, width, height):
            handle = made(pixels, width, height)
            alive.add(handle)
            most[0] = max(most[0], len(alive))
            return handle

        class Spy:
            def __getattr__(self, name):
                return getattr(real, name)

            def DestroyIcon(self, handle):
                alive.discard(handle)
                return real.DestroyIcon(handle)

        spy = Spy()
        icon = self.make()
        clock = [icon._epoch]
        with unittest.mock.patch.object(popup, "_icon_from_pixels", making), \
                unittest.mock.patch.object(tray, "_dll", lambda name: spy if name == "user32" else original(name)), \
                unittest.mock.patch.object(tray.time, "monotonic", lambda: clock[0]):
            for _ in range(20):                                    # warm the cache and the GDI heaps
                clock[0] += 0.2
                icon._animate()
            before = popup.gui_resources()
            for _ in range(500):
                clock[0] += 0.2
                icon._animate()
            after = popup.gui_resources()
            self.assertLessEqual(most[0], 2)
            self.assertEqual(len(alive), 1)                       # the one on show
            self.assertLessEqual(after[0] - before[0], 2, "GDI objects grew from %d to %d" % (before[0], after[0]))
            self.assertLessEqual(after[1] - before[1], 2, "USER objects grew from %d to %d" % (before[1], after[1]))
            spy.DestroyIcon(icon._frame_icon)
        self.assertEqual(self.logged, [])

    def test_an_unchanged_frame_is_not_swapped(self):
        icon = self.make()
        icon._icon_state = "idle"
        icon._motion_allowed = False
        swaps = []
        icon._notify_icon = lambda: swaps.append(1) or True
        try:
            icon._animate()
            icon._animate()
            icon._animate()
            self.assertEqual(len(swaps), 1)
        finally:
            tray._dll("user32").DestroyIcon(icon._frame_icon)

    def test_the_old_path_s_badged_copy_goes_with_the_first_frame(self):
        icon = self.make()
        icon._icon_state = "watching"
        badge = popup._icon_from_pixels(bytes(16 * 16 * 4), 16, 16)
        icon._badge = icon._shown_icon = badge
        changed, replaced = icon._frame_for(time.monotonic())
        try:
            self.assertTrue(changed)
            self.assertIn(badge, replaced)
            self.assertIsNone(icon._badge)
            self.assertIs(icon._shown_icon, icon._frame_icon)
        finally:
            user32 = tray._dll("user32")
            for handle in replaced + [icon._frame_icon]:
                if handle:
                    user32.DestroyIcon(handle)


@unittest.skipUnless(sys.platform == "win32", "Windows notification area")
class LiveMotionTests(unittest.TestCase):
    def test_a_paused_icon_is_its_grey_frame_and_everything_goes_when_it_stops(self):
        icon = tray.Tray(icon_path=ROOT / "assets" / "codex-auto-resume.ico", strings={})
        self.assertTrue(icon.start())
        try:
            icon.update({"enabled": False})
            deadline = time.monotonic() + 5
            while (not icon._frame_key or icon._icon_state != "idle") and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(icon._frames)
            self.assertEqual(icon._icon_state, "idle")
            self.assertEqual(icon._frame_key[1], tray.icon_head_colour("idle"))
            self.assertEqual(icon._frame_key[2], "paused")
            self.assertIsNone(icon._motion_ms)                   # grey and still: no frame timer
        finally:
            icon.stop()
        self.assertFalse(icon._thread.is_alive())
        self.assertIsNone(icon._frame_icon)
        self.assertIsNone(icon._badge)

    def test_without_its_own_ico_the_icon_builds_no_frames(self):
        icon = tray.Tray(icon_path=ROOT / "no-such.ico", strings={})
        self.assertTrue(icon.start())
        try:
            time.sleep(0.3)
            self.assertIsNone(icon._frames)
            self.assertIsNone(icon._frame_icon)
        finally:
            icon.stop()


if __name__ == "__main__":
    unittest.main()

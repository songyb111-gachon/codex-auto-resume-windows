"""v0.6.23 (second round, F3): the popup opens with the brand's fade and a small rise, and its buttons' faces glide.

The window's controls have glided since the first round (gui/SoftFields.cs: hover in brand's transition, a press and its
release in brand's press time; gui/SoftMenu.cs: a menu fades in and rises SPACING xs into place). The popup, the surface
opened most, was simply there in one frame and its buttons changed in one frame. Now:

- it opens on a layered window that fades in over brand's transition and rises into place (motion.opening), an ordinary
  window again once it has arrived, on the card's quicker frames (motion.GLIDE_FRAME_MS) and on brand's curve;
- each button's face glides from what it showed to what its state now says (motion.face_*), mixed by the renderer
  (Renderer.face_colours, draw's `faces`), its shadow swapped at once as the window's is;
- all of it is held by Reduce motion, Windows' animation effects, High Contrast, battery saver and a locked session.

Part window test (WindowTests opens a real popup far off every screen, without activating it): run on its own, through
gui_lock.sh. Nothing is captured: the frames are counted, and the renderer's pixels read from memory.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import brand  # noqa: E402
from codex_auto_resume.ui import popup as tray_popup  # noqa: E402
from codex_auto_resume.ui.popup import messages as popup_messages, motion  # noqa: E402

TRANSITION, PRESS = brand.MOTION["transition_ms"], brand.MOTION["press_ms"]


class ArithmeticTests(unittest.TestCase):
    def test_an_opening_fades_in_and_rises_on_brand_s_curve_over_its_transition(self):
        self.assertEqual(motion.opening(0, 6), (0, 6, False))
        steps = [motion.opening(at, 6) for at in range(0, TRANSITION, motion.GLIDE_FRAME_MS)]
        alphas, belows = [step[0] for step in steps], [step[1] for step in steps]
        self.assertEqual(alphas, sorted(alphas))
        self.assertEqual(belows, sorted(belows, reverse=True))
        self.assertGreaterEqual(len(set(alphas)), 8, "frames, not a jump")
        half = motion.opening(TRANSITION / 2, 6)
        self.assertEqual(half[0], int(round(255 * brand.ease(0.5))))
        self.assertEqual(motion.opening(TRANSITION, 6), (255, 0, True))

    def test_a_fade_out_takes_brand_s_press_time_from_where_it_was(self):
        self.assertEqual(motion.closing(0, 200), (200, False))
        self.assertLess(motion.closing(PRESS / 2, 200)[0], 200)
        self.assertEqual(motion.closing(PRESS, 200), (0, True))

    def test_a_press_and_its_release_take_the_press_time_and_the_rest_the_transition(self):
        self.assertEqual(motion.face_length("rest", "hover"), TRANSITION)
        self.assertEqual(motion.face_length("hover", "pressed"), PRESS)
        self.assertEqual(motion.face_length("pressed", "hover"), PRESS)
        self.assertEqual(motion.face_length("rest", "busy"), TRANSITION)
        item = {"target": ("pause",), "busy": False}
        self.assertEqual(motion.face_state(item, None, None), "rest")
        self.assertEqual(motion.face_state(item, ("pause",), None), "hover")
        self.assertEqual(motion.face_state(item, ("pause",), ("pause",)), "pressed")
        self.assertEqual(motion.face_state(dict(item, busy=True), ("pause",), ("pause",)), "busy")
        self.assertEqual(motion.face_amount((0.0, None, 160), 80.0), (brand.ease(0.5), False))
        self.assertEqual(motion.face_amount((0.0, None, 160), 160.0), (1.0, True))


class FaceDrawnTests(unittest.TestCase):
    """The renderer's half: a face part way is that far between the colours it left and its state's."""

    def setUp(self):
        self.renderer = tray_popup.Renderer()
        self.addCleanup(self.renderer.close)
        self.vm = tray_popup.view_model([], {"enabled": True, "watcher_running": True,
                                             "watcher": {"running": True, "ticking": True}}, {}, 1800000000.0)
        self.plan = self.renderer.layout(self.vm, 1.0, "en")
        self.button = next(item for item in self.plan["items"] if item["kind"] == "button")
        self.width = self.plan["size"][0]

    def pixel(self, **draw):
        pixels = self.renderer.draw(self.vm, self.plan, frame=None, **draw).pixels()
        left, top, right, bottom = (int(value) for value in self.button["rect"])
        index = (((top + bottom) // 2) * self.width + left + 6) * 4
        return pixels[index + 2], pixels[index + 1], pixels[index]

    def test_without_faces_a_button_is_drawn_as_it_always_was(self):
        target = self.button["target"]
        self.assertEqual(self.pixel(hover=target), self.renderer.face_colours(self.button, "hover")[0])
        self.assertEqual(self.pixel(), self.renderer.face_colours(self.button, "rest")[0])

    def test_a_face_part_way_is_between_the_colours_it_left_and_its_state_s(self):
        target = self.button["target"]
        rest, hover = self.renderer.face_colours(self.button, "rest"), self.renderer.face_colours(self.button, "hover")
        self.assertNotEqual(rest[0], hover[0])
        self.assertEqual(self.pixel(hover=target, faces={target: (rest, 0.0)}), rest[0], "where it left from")
        half = self.pixel(hover=target, faces={target: (rest, 0.5)})
        self.assertEqual(half, motion.mixed(rest[0], hover[0], 0.5))
        self.assertEqual(self.pixel(hover=target, faces={target: (rest, 1.0)}), hover[0])


class WindowTests(unittest.TestCase):
    """A real popup far off every screen. Nothing here counts on this machine's speed or display: Windows' animation
    setting is the test's own (GitHub's runners have it off, which holds every motion), a window off the screen is never
    painted so each frame of a face is drawn by hand as WM_PAINT would draw it, and where a motion stands is checked
    against the clock read around it - a stalled runner moves a read along the curve, never the curve."""

    def setUp(self):
        patcher = mock.patch.object(tray_popup.theme, "reduced_motion", lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pump(self, seconds):
        from test_tray_popup import WindowsTests
        WindowsTests.pump(self, seconds)

    def until(self, done, seconds=5.0, step=0.016, each=None):
        """Pump until `done()` or the time is up: a bound by the clock, never by a count of frames."""
        deadline = time.monotonic() + seconds
        while not done() and time.monotonic() < deadline:
            self.pump(step)
            if each is not None:
                each()
        return done()

    def make(self, **extra):
        from test_tray_popup import EN, FakeControl, WindowsTests
        window = tray_popup.Popup(control=FakeControl(WindowsTests.ROWS), strings=EN, **extra)
        window.create()
        self.addCleanup(window.destroy)
        window.model.apply_outcome(("read",), tray_popup.perform(("read",), window.control), time.time())
        return window

    def layered(self, window):
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowLongW.argtypes, user32.GetWindowLongW.restype = [ctypes.c_void_p, ctypes.c_int], ctypes.c_long
        return bool(user32.GetWindowLongW(window.hwnd, -20) & 0x00080000)

    def record_openings(self):
        seen = []
        real = popup_messages.opening

        def recorded(elapsed, rise):
            answer = real(elapsed, rise)
            seen.append((elapsed,) + answer)
            return answer
        patcher = mock.patch.object(popup_messages, "opening", recorded)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def test_it_fades_in_and_rises_frame_by_frame_and_ends_an_ordinary_window(self):
        seen = self.record_openings()
        window = self.make()
        window.show(activate=False, origin=(-32000, -32000))
        self.assertIsNotNone(window._opening, "on its way in")
        self.assertTrue(self.layered(window))
        rise = window._below
        self.assertGreater(rise, 0, "below its place")
        self.assertEqual(window._frame_ms, motion.GLIDE_FRAME_MS)
        self.assertTrue(self.until(lambda: window._opening is None), "it arrives")
        self.assertFalse(self.layered(window), "an ordinary window once it has arrived")
        self.assertEqual(window._below, 0)
        on_the_way = [step for step in seen if not step[3]]
        self.assertTrue(on_the_way, "its first frame is faded out and below its place, whatever the runner's speed")
        self.assertEqual(on_the_way[0][1:3], (0, rise))
        for elapsed, alpha, below, _ in on_the_way:
            self.assertLess(elapsed, TRANSITION, "on its way only while its time is not up")
            # Where the curve stands at the clock it was read at (its last steps round to 255 just before the end).
            self.assertEqual(alpha, int(round(255 * brand.ease(elapsed / TRANSITION))))
        self.assertTrue(seen[-1][3], "and it arrived")
        self.assertGreaterEqual(seen[-1][0], TRANSITION, "no sooner than brand's transition, by the clock")
        alphas = [step[1] for step in seen]
        self.assertEqual(alphas, sorted(alphas), "only ever more opaque")
        self.assertEqual(window._frame_ms, tray_popup.FRAME_MS, "the light's own frames again")

    def test_held_or_reduced_it_is_simply_there(self):
        for kind in ("held", "reduced"):
            with self.subTest(kind):
                if kind == "held":
                    window = self.make(held=lambda: True)
                    window.show(activate=False, origin=(-32000, -32000))
                else:
                    window = self.make()
                    with mock.patch.object(tray_popup.theme, "reduced_motion", return_value=True):
                        window.show(activate=False, origin=(-32000, -32000))
                self.assertIsNone(window._opening)
                self.assertFalse(self.layered(window))
                self.assertEqual(window._below, 0)

    def test_closed_while_it_opens_it_leaves_nothing_behind(self):
        window = self.make()
        window.show(activate=False, origin=(-32000, -32000))
        self.assertIsNotNone(window._opening)
        window.hide()
        self.assertIsNone(window._opening)
        self.assertFalse(self.layered(window))
        self.assertEqual(window._below, 0)
        self.assertFalse(window._frame_running)

    def glide(self, window, target, change, length):
        """Make `change`, draw each frame by hand until the face is let go, and check every frame against the clock."""
        reads = []
        real = window._renderer.draw

        def recording(*args, **kwargs):
            reads.append((kwargs.get("faces") or {}).get(target))
            return real(*args, **kwargs)
        window._renderer.draw = recording
        self.addCleanup(setattr, window._renderer, "draw", real)
        change()
        window._invalidate()
        window.render()
        self.assertIn(target, window._faces, "the change starts a glide")
        started, _, took = window._faces[target]
        self.assertEqual(took, length)
        self.assertEqual(window._frame_ms, motion.GLIDE_FRAME_MS, "on the quicker frames")
        bracketed = []

        def frame():
            before = time.monotonic() * 1000.0
            reads.clear()
            window._static_dirty = True
            window.render()
            after = time.monotonic() * 1000.0
            if reads:
                bracketed.append((before - started, after - started, reads[-1]))
        self.assertTrue(self.until(lambda: target not in window._faces, each=frame), "let go once its time is up")
        window._renderer.draw = real
        self.assertTrue(bracketed)
        for least, most, read in bracketed:
            if read is None:
                self.assertGreaterEqual(most, length, "let go only once its time is up")
                continue
            amount = read[1]
            self.assertLessEqual(amount, brand.ease(min(1.0, most / length)) + 1e-6, "ahead of its curve")
            self.assertGreaterEqual(amount, brand.ease(max(0.0, least / length)) - 1e-6, "behind its curve")
            self.assertLess(least, length, "still on its way while its time is not up")

    def test_a_button_s_face_glides_to_the_pointer_and_to_a_press(self):
        window = self.make()
        window.show(activate=False, origin=(-32000, -32000))
        self.assertTrue(self.until(lambda: window._opening is None))
        target = next(item["target"] for item in window._plan["items"] if item["kind"] == "button")
        window.render()                              # the face at rest, drawn once, as the first paint draws it
        self.glide(window, target, lambda: setattr(window, "hover", target), TRANSITION)
        self.glide(window, target, lambda: setattr(window, "pressed", target), PRESS)

    def test_a_popup_is_kept_alive_while_its_window_exists(self):
        from codex_auto_resume.ui.popup import window as popup_window
        window = self.make()
        self.assertIn(window, popup_window._LIVING, "Windows may still call its window procedure")
        window.destroy()
        self.assertNotIn(window, popup_window._LIVING, "and let go with its window")

    def test_held_a_face_changes_at_once(self):
        window = self.make(held=lambda: True)
        window.show(activate=False, origin=(-32000, -32000))
        target = next(item["target"] for item in window._plan["items"] if item["kind"] == "button")
        window.render()
        window.hover = target
        window._invalidate()
        window.render()
        self.assertEqual(window._face_states.get(target), "hover", "the change was drawn")
        self.assertEqual(window._faces, {}, "and simply there")
        self.assertFalse(window._frame_running)


if __name__ == "__main__":
    unittest.main()

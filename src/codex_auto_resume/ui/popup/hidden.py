"""The popup's seventh press: seven presses of its title, the light's sweep, and one sentence in the state line for a moment."""
from __future__ import annotations

import ctypes as C
import time

from ... import brand


class PopupHidden:
    """A mixin of the window, and only ever about what it shows; a press of the title does what it always did: nothing else."""

    _presses = None
    _sweep_since = None     # monotonic ms, or None
    _aside_from = None      # monotonic ms the sentence shows from, or None
    _aside_shown = False
    _scene_since = 0.0      # where the day's scene counts from

    def day_view(self, vm, now):
        """The view as today has it: the day's scene, and the sentence in the state line while it is its moment."""
        vm["scene"] = brand.day_look_at(now) if self.days and not self._contrast and self._design != "classic" else None
        vm["state_text"] = self.aside_words(vm["state_text"])

    def title_pressed(self, lparam, now_ms):
        plan = self._painted_plan
        if plan is None:
            return
        x = C.c_short(lparam & 0xFFFF).value
        y = C.c_short((lparam >> 16) & 0xFFFF).value
        for item in plan["items"]:
            if item["kind"] == "title_press":
                left, top, right, bottom = item["rect"]
                if left <= x < right and top <= y < bottom:
                    self._title_press(now_ms)
                return

    def _title_press(self, now_ms):
        if self._presses is None:
            self._presses = brand.PressRun()
        if not self._presses.press(now_ms):
            return
        numbers = brand.SWEEP
        moves = not self._holds() and not self._contrast
        self._sweep_since = now_ms if moves else None
        self._aside_from = now_ms + (numbers["aside_after_ms"] if moves else 0)
        self._sync_frames()
        self._update()

    def sweeping(self):
        return self._sweep_since is not None

    def aside_words(self, state_text):
        """The state line, or the sentence while it is its moment."""
        if self._aside_from is None:
            return state_text
        now = time.monotonic() * 1000.0
        if now < self._aside_from:
            return state_text
        if now >= self._aside_from + brand.SWEEP["aside_ms"]:
            self._aside_from = None
            return state_text
        return self.model.strings.get("status.aside", state_text)

    def step_hidden(self):
        """A frame or a paint: where the sweep has got to, and the state line changed when its moment comes or goes."""
        renderer = self._renderer
        if self._sweep_since is not None:
            elapsed = time.monotonic() * 1000.0 - self._sweep_since
            numbers = brand.SWEEP
            if elapsed >= numbers["second_ring_ms"] + numbers["ring_ms"] or self._holds() or not self.visible:
                self._sweep_since = None
                renderer.sweep_ms = None
            else:
                renderer.sweep_ms = elapsed
        else:
            renderer.sweep_ms = None
        due = self._aside_from is not None and time.monotonic() * 1000.0 >= self._aside_from
        ended = due and time.monotonic() * 1000.0 >= self._aside_from + brand.SWEEP["aside_ms"]
        if (due and not self._aside_shown) or ended:
            self._aside_shown = due and not ended
            self._plan = None
            self._rebuild(time.time())
            self._static_dirty = True

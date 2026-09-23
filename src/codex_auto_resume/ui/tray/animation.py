"""The frame table's life, and the timer that draws from it.

Built off the icon's thread, because composing sixteen-pixel frames costs more than a tick
has and every frame after that is a table lookup. This is also where the icon asks whether it
may move at all - battery saver, the overflow flyout, a locked session - which is why those
questions are imported here and nowhere else in the package.
"""
from __future__ import annotations

import ctypes as C
import threading
import time

from ...tray_place import IconPlacement, battery_saver
from .motion import (build_icon_frames,
                     icon_frame,
                     icon_frame_ms,
                     icon_head_colour,
                     icon_level_colour,
                     icon_motion_allowed,
                     icon_state)
from .model import popup_attention
from .win32 import NIF_ICON, NIM_MODIFY, NOTIFYICONDATAW, TIMER_FRAME, WM_TRAY_FRAMES, _dll


class AnimationMixin:
    """The frame table, and what may move."""

    # --------------------------------------------------------------- the icon's motion
    def _build_frames_later(self, size):
        """Build the frame table on a thread of its own; the icon's thread hears when it is done."""
        def build():
            try:
                frames = build_icon_frames(size)
                result = (frames, None if frames else "over its time budget")
            except Exception as exc:
                result = (None, type(exc).__name__)
            with self._lock:
                self._frames_result = result
            hwnd = self._hwnd
            if hwnd:
                _dll("user32").PostMessageW(hwnd, WM_TRAY_FRAMES, 0, 0)

        threading.Thread(target=build, name="tray-frames", daemon=True).start()

    def _frames_built(self):
        with self._lock:
            result, self._frames_result = self._frames_result, None
        if result is None or not self._icon:
            return
        frames, reason = result
        if frames is None:
            self._frames = False
            self.log("tray motion unavailable (%s)" % reason)   # once: the table is never built again
            return
        self._frames = frames
        self._refresh()

    def _observe(self, snapshot):
        """What the one-second tick decides for the motion: the state and whether it may move.

        Windows is asked what may move only when the state has something to move, and whether
        the icon is in the overflow flyout only when nothing else already holds it still. The
        product's own Reduce motion is taken from the stored settings on the same tick
        (`_adopt_reduce_motion`), so a Save in the window holds the icon within a second.
        """
        attention = popup_attention(self._popup)
        state = icon_state(snapshot, attention=attention, failed=snapshot.get("failed") is True)
        now = time.monotonic()
        if state != self._icon_state:
            self._icon_state, self._state_since = state, now
        since = (now - self._state_since) * 1000.0
        allowed = False
        if icon_frame_ms(state, (now - self._epoch) * 1000.0, since) is not None:
            from .. import popup as tray_popup
            self._adopt_reduce_motion(tray_popup)
            allowed = icon_motion_allowed(reduced=tray_popup.reduced_motion(), contrast=tray_popup.high_contrast(),
                                          battery_saver=battery_saver(),
                                          locked=self._session_locked or self._session_away,
                                          frames=bool(self._frames))
            if allowed:
                allowed = not self._overflowed() and tray_popup.icon_rect(self._hwnd, 1) is not None
        self._motion_allowed = allowed

    def _overflowed(self) -> bool:
        """Whether Windows says the icon is in the overflow flyout, where nobody would see it move. Its own setting
        for the icon, because Windows 11 gives an icon there the overflow button's rectangle and `icon_rect` cannot
        tell (IconPlacement); where Windows does not say, the rectangle decides as it did before."""
        if self._placement is None:
            self._placement = IconPlacement()
        return self._placement.overflowed() is True

    def _frame_for(self, now):
        """Show the frame this moment wants. Returns (changed, [icons to destroy once shown])."""
        frames = self._frames
        if not frames:
            return False, []
        state = self._icon_state or "watching"
        elapsed = (now - self._epoch) * 1000.0
        since = (now - self._state_since) * 1000.0
        position, level = icon_frame(state, elapsed, since, reduced=not self._motion_allowed)
        head = icon_level_colour(icon_head_colour(state), level)
        key = (position, head)
        if key == self._frame_key and self._frame_icon:
            return False, []
        try:
            from .. import popup as tray_popup
            pixels = frames.compose(position, head)
            tray_popup._declare()                  # the GDI calls' types
            made = tray_popup._icon_from_pixels(pixels, frames.size, frames.size)
            if not made:
                raise OSError("CreateIconIndirect")
        except Exception as exc:
            # Back to the icon as it was before v0.6.5, for the rest of this icon's life.
            self.log("tray motion failed (%s)" % type(exc).__name__)
            self._frames, self._frame_key = False, None
            replaced, self._frame_icon = self._frame_icon, None
            self._shown_icon = self._icon
            return True, [replaced]
        replaced = [self._frame_icon]
        self._frame_icon, self._frame_key = made, key
        self._shown_icon = made
        return True, replaced

    def _animate(self):
        """One frame-timer tick: only the icon, only when its frame changed."""
        changed, replaced = self._frame_for(time.monotonic())
        if changed:
            self._notify_icon()
        for handle in replaced:
            if handle:
                _dll("user32").DestroyIcon(handle)
        self._sync_motion()

    def _notify_icon(self):
        """NIM_MODIFY with the icon alone: a frame changes nothing else the shell holds."""
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = NIF_ICON
        data.hIcon = self._shown_icon or self._icon
        return _dll("shell32").Shell_NotifyIconW(NIM_MODIFY, C.byref(data))

    def _sync_motion(self):
        """Run the frame timer at the interval this moment wants, and not at all when nothing moves."""
        interval = None
        if self._frames and self._motion_allowed and self._icon_state is not None:
            now = time.monotonic()
            interval = icon_frame_ms(self._icon_state, (now - self._epoch) * 1000.0,
                                     (now - self._state_since) * 1000.0)
        if interval == self._motion_ms:
            return
        user32 = _dll("user32")
        if interval is None:
            user32.KillTimer(self._hwnd, TIMER_FRAME)
        else:
            user32.SetTimer(self._hwnd, TIMER_FRAME, interval, None)   # the same id replaces it
        self._motion_ms = interval

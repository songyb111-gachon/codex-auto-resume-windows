"""The cards on screen together: shown, stacked, hovered, clicked, and closed - and the
window procedure that runs them on the icon's thread.
"""
from __future__ import annotations

import ctypes as C
import os
import time

from ... import brand
from ... import notice_card
from ... import notice_presence
from .. import popup
from . import win32
from .win32 import HWND_MESSAGE, IDC_ARROW, MA_NOACTIVATE, TIMER_FRAME, TIMER_WAIT, TME_LEAVE, TRACKMOUSEEVENT, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEACTIVATE, WM_MOUSELEAVE, WM_MOUSEMOVE, WM_NOTICE, WM_RBUTTONUP, WM_TIMER, WNDCLASSW, WNDPROC, _declare, _on_a_worker_thread, look, screen  # noqa: F401
from .card import Card  # noqa: F401

class CardStack:
    """Every card on screen, on the icon's thread. `wake` is the one method another thread calls.

    `on_action(uri)` is called on a worker thread when a card's button is clicked; `anchor()`
    returns the icon's rectangle or None (`popup.icon_rect`); `inbox` is the notifier's
    Inbox, which this stack attaches itself to once its window exists; `on_complete(notice,
    shown)` ends each notice it took, once, on a worker thread (see the module's docstring).
    `worker(target, *args)` runs a callback off the icon's thread (a short daemon thread unless
    given). `locate()` and `appearance()` stand in for `screen` and `look` (the tests put cards
    somewhere no screen shows them).
    """

    def __init__(self, *, on_action=None, log=None, anchor=None, inbox=None, on_complete=None,
                 clock=None, locate=None, appearance=None, worker=None):
        self.on_action = on_action
        self.log = log or (lambda *unused: None)
        self.anchor = anchor
        self.inbox = inbox
        self.on_complete = on_complete
        self.worker = worker or _on_a_worker_thread
        self.clock = clock or (lambda: time.monotonic() * 1000.0)
        self.locate = locate or (lambda: screen(self.anchor))
        self.appearance = appearance or look
        self.hwnd = None
        self.class_name = None
        self.instance = None
        self.cards = []                 # newest first
        self.windows = {}               # hwnd -> Card
        self._proc = None
        self._frame_running = False
        self._hovered = False
        self._gdiplus = False

    # ---- lifecycle
    def create(self):
        _declare()
        user32 = win32._dll("user32")
        self.instance = win32._dll("kernel32").GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = self.instance
        klass.hCursor = user32.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        self.class_name = "CodexAutoResumeCard-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self.class_name
        if not user32.RegisterClassW(C.byref(klass)):
            self.class_name = None
            raise OSError("RegisterClassW")
        self.hwnd = user32.CreateWindowExW(0, self.class_name, "", 0, 0, 0, 0, 0,
                                           C.c_void_p(HWND_MESSAGE), None, self.instance, None)
        if not self.hwnd:
            self.destroy()
            raise OSError("CreateWindowExW")
        if self.inbox is not None:
            self.inbox.attach(self.wake)
        return self

    def wake(self) -> bool:
        """Any thread: ask this stack's thread to take what the inbox holds."""
        hwnd = self.hwnd
        return bool(hwnd) and bool(win32._dll("user32").PostMessageW(hwnd, WM_NOTICE, 0, 0))

    def destroy(self):
        """Take every card down and let go of the inbox. Every notice this stack was given and
        has not ended yet ends now: shown if it was seen (or had already left by design),
        today's toast if it was still arriving or never taken from the inbox."""
        waiting = self.inbox.detach() if self.inbox is not None else []
        user32 = win32._dll("user32")
        for card in list(self.cards):
            self._end(card, card.seen or card.superseded)
            self._drop(card)
        for notice in waiting:
            self._complete(notice, False)
        hwnd, self.hwnd = self.hwnd, None
        if hwnd:
            for timer in (TIMER_FRAME, TIMER_WAIT):
                user32.KillTimer(hwnd, timer)
            user32.DestroyWindow(hwnd)
        self._frame_running = False
        if self.class_name:
            user32.UnregisterClassW(self.class_name, self.instance)
            self.class_name = None
        self._release_gdiplus()

    def hold(self) -> float:
        return notice_card.hold_ms(notice_presence.message_duration_ms())

    def _acquire_gdiplus(self):
        if not self._gdiplus:
            popup._gdiplus_acquire()
            self._gdiplus = True

    def _release_gdiplus(self):
        if self._gdiplus:
            popup._gdiplus_release()
            self._gdiplus = False

    # ---- showing
    def show(self, notice, *, where=None, drawn=None):
        """Put one notice on screen as the newest card. Returns the Card, or None if it failed."""
        try:
            self._acquire_gdiplus()
            where = where or self.locate()
            drawn = drawn or self.appearance()
            card = Card(self, notice, now_ms=self.clock(), where=where, drawn=drawn)
        except Exception as exc:
            self.log("notification card unavailable (%s)" % type(exc).__name__)
            if not self.cards:
                self._release_gdiplus()
            self._complete(notice, False)
            return None
        # Its life starts now that it is drawn: its first frame is the first frame of its entrance.
        now = self.clock()
        card.motion.restart(now)
        try:
            self.admit(card, now, where)
        except Exception as exc:
            self.log("notification card unavailable (%s)" % type(exc).__name__)
            self._end(card, False)
            self._drop(card)
            return None
        self._tick()
        return card

    def admit(self, card, now, where):
        """A new card joins the stack: what it replaces or pushes out leaves.

        A newer notice about a conversation that already has a card takes that card's place: the
        old one fades out quickly where it is and the new one rises into the same slot as it goes,
        so a task's card reads as one card moving through its states. Anything else arrives as
        the newest, nearest the corner, once the stack has begun to make room for it.
        """
        key = getattr(card.notice, "key", None)
        living = [entry for entry in self.cards if entry.motion.phase not in ("exit", "gone")]
        replaced = next((entry for entry in living if key and getattr(entry.notice, "key", None) == key), None)
        if replaced is not None:
            replaced.motion.retire(now, quick=True)
            replaced.superseded = True
            self.cards.insert(self.cards.index(replaced), card)
            card.motion.delay(notice_card.SWAP_MS)
            settle = notice_card.SWAP_MS               # the others make room once it has gone
        else:
            self.cards.insert(0, card)
            settle = 0
            if living:
                card.motion.delay(notice_card.STACK_DELAY_MS)
        living = [entry for entry in self.cards if entry.motion.phase not in ("exit", "gone")]
        for extra in living[notice_card.MAX_CARDS:]:
            extra.motion.retire(now)                     # the oldest leaves early,
            extra.pushed_out = True                      # moving on with the stack as it fades
        self._restack(now, where, settle)
        if self._hovered:
            card.motion.pause(now, True)

    def _restack(self, now, where, delay=0):
        """Give every card its place, newest nearest the corner. A card the work area has no room
        for retires, as a fourth one does. A card leaving because a new one came moves away from
        the corner by the new card's height while it fades, as the stack does, so a leaving card
        and an arriving one never cross."""
        living = [card for card in self.cards if card.motion.phase not in ("exit", "gone")]
        scale = where["dpi"] / 96.0
        gap = int(round(brand.SPACING["m"] * scale))
        spacing = int(round(brand.SPACING["m"] * scale))
        positions, edge = notice_card.stack_positions([card.size for card in living], where["work"],
                                                      where["monitor"], where["anchor"], gap=gap,
                                                      spacing=spacing)
        for extra in living[len(positions):]:
            extra.motion.retire(now)                     # no room: it leaves with the older ones,
            extra.pushed_out = True                      # never laid over a newer card
        living = living[:len(positions)]
        for card, position in zip(living, positions):
            if card.motion.position is None:
                card.edge = edge
            card.motion.move_to(now, position, delay)
        if not living or not positions:
            return
        newest = living[0]
        away = notice_card.stack_direction(edge, positions[0][1], newest.size[1], where["work"])
        step = away * (newest.size[1] + spacing)
        for card in self.cards:
            if (card.pushed_out and not card.moved_out and card.motion.phase == "exit"
                    and card.motion.position is not None):
                x, y = card.motion.position
                card.motion.move_to(now, (x, y + step))
                card.moved_out = True

    def _complete(self, notice, shown):
        """End one notice, off this thread: the host raises its history copy or its toast."""
        callback = self.on_complete
        if callback is None:
            return
        self.worker(self._quietly, callback, notice, shown is True)

    def _end(self, card, shown):
        """End a card's notice, the first time only: whatever happens to the card afterwards,
        its notice has gone out by one route."""
        if card.ended:
            return
        card.ended = True
        self._complete(card.notice, shown)

    def _quietly(self, callback, *values):
        try:
            callback(*values)
        except Exception as exc:
            self.log("notification card callback failed (%s)" % type(exc).__name__)

    def _drop(self, card):
        if card in self.cards:
            self.cards.remove(card)
        card.close()
        if not self.cards:
            self._release_gdiplus()

    # ---- time
    def _tick(self):
        now = self.clock()
        for card in list(self.cards):
            card.motion.frame(now)
            if card.motion.gone:
                # Seen, or replaced by a newer card about the same conversation: its silent copy.
                # Pushed out of the stack before it was ever seen whole: today's toast instead.
                self._end(card, card.seen or card.superseded)
                self._drop(card)
                continue
            try:
                card.present(now)
            except Exception as exc:
                self.log("notification card frame failed (%s)" % type(exc).__name__)
                self._end(card, False)               # never seen whole: today's toast instead
                self._drop(card)
                continue
            if card.seen:
                self._end(card, True)                # seen: now its silent copy for the history
        self._sync_hover(now)
        self._schedule(now)

    def _sync_hover(self, now):
        """Hold every card while the pointer is over any of them, and only then. A card that
        goes away under the pointer (it was clicked) never hears the pointer leave, so this is
        asked again whenever the stack changes, not only when a card says so."""
        hovered = any(card.tracking for card in self.cards)
        if hovered != self._hovered:
            self._hovered = hovered
            for card in self.cards:
                card.motion.pause(now, hovered)

    def _schedule(self, now):
        if not self.hwnd:
            return
        user32 = win32._dll("user32")
        moving = any([card.motion.moving(now) or card.breathe(now) for card in self.cards])
        if moving and not self._frame_running:
            user32.SetTimer(self.hwnd, TIMER_FRAME, notice_card.FRAME_MS, None)
            self._frame_running = True
        elif not moving and self._frame_running:
            user32.KillTimer(self.hwnd, TIMER_FRAME)
            self._frame_running = False
        user32.KillTimer(self.hwnd, TIMER_WAIT)
        if not moving:
            waits = [wait for wait in (card.motion.wait_ms(now) for card in self.cards) if wait is not None]
            if waits:
                user32.SetTimer(self.hwnd, TIMER_WAIT, max(1, int(min(waits)) + 1), None)

    # ---- the pointer
    def _hover(self, card, target):
        if target != card.hover:
            card.hover = target
            card.redraw()
        self._sync_hover(self.clock())
        self._tick()

    def _click(self, card, target):
        now = self.clock()
        if target is not None:
            index = target[1]
            actions = card.vm["actions"]
            if 0 <= index < len(actions) and self.on_action is not None:
                self.worker(self._quietly, self.on_action, actions[index]["uri"])
        card.seen = True                                 # somebody pointed at it and clicked
        card.motion.retire(now)
        self._tick()

    # ---- messages
    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            handled = self._handle(hwnd, message, wparam, lparam)
            if handled is not None:
                return handled
        except Exception as exc:                  # a card must never take the watcher down
            self.log("notification card message failed (%s)" % type(exc).__name__)
        return win32._dll("user32").DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle(self, hwnd, message, wparam, lparam):
        user32 = win32._dll("user32")
        if hwnd == self.hwnd:
            if message == WM_NOTICE:
                for notice in (self.inbox.take() if self.inbox is not None else []):
                    try:
                        self.show(notice)               # ends the notice itself if it cannot draw it
                    except Exception as exc:            # admitted by then: its card ends it later
                        self.log("notification card failed (%s)" % type(exc).__name__)
                return 0
            if message == WM_TIMER:
                if wparam == TIMER_WAIT:
                    user32.KillTimer(hwnd, TIMER_WAIT)
                self._tick()
                return 0
            return None
        card = self.windows.get(hwnd)
        if card is None or hwnd != (card.body.hwnd if card.body else None):
            if message == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            return None
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE                  # clicking a card never activates it
        if message == WM_MOUSEMOVE:
            if not card.tracking:
                track = TRACKMOUSEEVENT()
                track.cbSize = C.sizeof(TRACKMOUSEEVENT)
                track.dwFlags = TME_LEAVE
                track.hwndTrack = hwnd
                card.tracking = bool(user32.TrackMouseEvent(C.byref(track)))
            self._hover(card, card.hit(lparam))
            return 0
        if message == WM_MOUSELEAVE:
            card.tracking = False
            card.pressed = None
            self._hover(card, None)
            return 0
        if message == WM_LBUTTONDOWN:
            card.pressed = card.hit(lparam)
            if card.pressed is not None:
                card.redraw()
                self._tick()
            return 0
        if message == WM_LBUTTONUP:
            target, pressed = card.hit(lparam), card.pressed
            card.pressed = None
            if target is not None and target == pressed:
                self._click(card, target)
            elif target is None and pressed is None:
                self._click(card, None)           # a click on the card itself puts it away
            else:
                card.redraw()
                self._tick()
            return 0
        if message == WM_RBUTTONUP:
            self._click(card, None)
            return 0
        return None

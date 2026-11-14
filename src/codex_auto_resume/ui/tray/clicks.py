"""What a click does: making the popup, showing it, and marking what it showed as seen.

Never sending anything. Every method here either opens a window or tells the control layer
that a person has now seen a failure, which is the whole of what a click is allowed to mean.
"""
from __future__ import annotations

from .menu import MENU_OPEN


class ClicksMixin:
    """What a click on the icon does."""

    # ----------------------------------------------------------------- popup
    def _popup_for_click(self):
        if self.control is None or self._popup_failed:
            return None
        if self._popup is None:
            from .. import popup as tray_popup
            with self._lock:
                strings = dict(self.strings)
            self._popup = tray_popup.Popup(control=self.control, source=self.pending_source,
                                           strings=strings, on_dashboard=self.on_dashboard,
                                           log=self.log,
                                           anchor=lambda: tray_popup.icon_rect(self._hwnd, 1),
                                           theme_menu=self._theme_menu,
                                           make_menu=lambda: tray_popup.Menu(log=self.log), days=self.days,
                                           held=self._popup_held)
        return self._popup

    def _popup_broke(self, exc):
        self.log("tray popup unavailable (%s)" % type(exc).__name__)
        self._popup_failed = True
        popup, self._popup = self._popup, None
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    def _select(self, keyboard=False):
        self._adopt_settings()
        popup = self._popup_for_click()
        if popup is None:
            return
        try:
            popup.on_select(keyboard=keyboard)
        except Exception as exc:
            self._popup_broke(exc)
            return
        self._failure_seen()

    def _popup_can_open(self) -> bool:
        """Whether the icon has a popup to open: what the menu's Open the popup is offered by (v0.6.23). The left click's
        own condition (_popup_for_click): a control layer, and a popup that has not broken."""
        return self.control is not None and not self._popup_failed

    def _open_popup(self):
        """The menu's Open the popup (v0.6.23, the owner, 2026-11-11): the popup a left click opens, made and placed the
        way the click makes and places it, and what it shows marked seen as the click marks it. The right click that
        opened the menu closed the popup (icon.py), so here it opens - never the click's toggle, whose closing would
        undo the choice; one already open, or about to be, is shown and brought forward."""
        self._adopt_settings()
        popup = self._popup_for_click()
        if popup is None:
            return
        try:
            popup.show()
        except Exception as exc:
            self._popup_broke(exc)
            return
        self._failure_seen()

    def _failure_unseen(self, snapshot) -> bool:
        """Whether the icon shows a certain failure: one the watcher found (snapshot_from) that nobody has seen since
        and no recovery has followed (control.unseen_failure). Without a control layer, or when it cannot say, no."""
        if self.control is None or not snapshot.get("failures"):
            return False
        try:
            return self.control.failure_unseen(snapshot["failures"]) is True
        except Exception:
            return False

    def _unconfirmed_unseen(self, snapshot) -> bool:
        """Whether the icon asks for attention for a sending nobody has confirmed (v0.6.20, control.unseen_unconfirmed):
        the same rule as a failure's, in amber and not in red."""
        if self.control is None or not snapshot.get("failures"):
            return False
        try:
            return self.control.unconfirmed_unseen(snapshot["failures"]) is True
        except Exception:
            return False

    def _failure_seen(self):
        """A click that opens the popup has seen the failure the icon shows: say so, and let the icon go back now
        rather than at the next second."""
        if not (self._failed or self._unconfirmed) or self.control is None:
            return
        try:
            self.control.acknowledge_failure()
        except Exception as exc:
            self.log("tray failure acknowledgement failed (%s)" % type(exc).__name__)
            return
        self._refresh()

    def _double_click(self):
        self._adopt_settings()
        popup = self._popup_for_click()
        if popup is None:
            if self.on_open:
                self._act(MENU_OPEN, False)
            return
        try:
            popup.on_double_click()
        except Exception as exc:
            self._popup_broke(exc)

    def _hide_popup(self):
        if self._popup is not None:
            try:
                self._popup.hide()
            except Exception as exc:
                self._popup_broke(exc)

"""The right-click menu: what it offers, and asking Windows to draw it dark.

Kept together on purpose. The menu is the one surface this icon draws through Windows itself
rather than through the popup, so the ordinals, the command ids and the two methods that use
them are one thing to read - and one place to replace when a test needs Windows not to answer.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import sys
import time

from .win32 import (MF_GRAYED,
                    MF_SEPARATOR,
                    MF_STRING,
                    TPM_NONOTIFY,
                    TPM_RETURNCMD,
                    TPM_RIGHTBUTTON,
                    WM_NULL,
                    _dll)
from .words import tooltip



# The menu's command ids. Deliberately not one per pending recovery: a context menu
# built from a list that the watcher is still changing would act on whichever row the id
# happened to mean when the menu was drawn, and there is no room beside a menu item to
# name the conversation an action is about - which is how the window's confirmations stop
# somebody cancelling the wrong task. The safe half of the same need is a route: Pending
# opens the window on the page where those actions live, with their identities and their
# confirmations intact. (The popup's per-task switch is the other half: it names the
# conversation beside the switch, and it is bound to that row's exact identities.)
MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 4

# How the menu looks. Windows draws a popup menu itself, and draws it light unless the process has
# asked for dark through uxtheme's preferred app mode - a call Windows exports by ordinal only, with
# no documented name, stable since Windows 10 1903 (build 18362). On an older build that ordinal is
# a different function, so nothing is asked there and the menu stays light. It is asked for
# ForceDark exactly when the popup beside it is dark, and back to Default otherwise; High Contrast
# needs no request, because Windows draws every menu in the contrast theme's colours.
APP_MODE_DEFAULT, APP_MODE_FORCE_DARK = 0, 2
UXTHEME_SET_PREFERRED_APP_MODE, UXTHEME_FLUSH_MENU_THEMES = 135, 136
DARK_MENU_BUILD = 18362



def menu_app_mode(look) -> int:
    """The app mode the menu is asked for, by what the popup draws with: dark only in dark."""
    return APP_MODE_FORCE_DARK if look == "dark" else APP_MODE_DEFAULT


def prefer_app_mode(mode) -> bool:
    """Ask Windows to draw this process's menus in `mode`. False where Windows cannot be asked."""
    if os.name != "nt" or sys.getwindowsversion().build < DARK_MENU_BUILD:
        return False
    uxtheme = _dll("uxtheme")
    # By ordinal each time: an export looked up this way is a fresh function object, so the types
    # declared on it reach no other caller.
    prefer = uxtheme[UXTHEME_SET_PREFERRED_APP_MODE]
    prefer.argtypes, prefer.restype = (C.c_int,), C.c_int
    flush = uxtheme[UXTHEME_FLUSH_MENU_THEMES]
    flush.argtypes, flush.restype = (), None
    prefer(mode)
    flush()                                     # menus already themed in this process take it up
    return True


class MenuMixin:
    """The menu: building it, acting on what was chosen, and its colour."""


    def _menu(self):
        user32 = _dll("user32")
        self._adopt_settings()                  # the menu speaks the language stored now
        self._theme_menu()                      # and is drawn in the theme the popup is
        snapshot = self._shown()
        menu = user32.CreatePopupMenu()
        try:
            status = tooltip(snapshot, self.strings, time.time()).split("\n", 1)[-1]
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, status)
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_OPEN,
                               self.strings.get("menu.open", "Open Codex Auto Resume"))
            # Only while there is something to look at. An item that opens a page saying
            # nothing is waiting is an item that teaches people not to use the menu.
            waiting = int(snapshot.get("waiting", 0) or 0) + int(snapshot.get("running", 0) or 0)
            if waiting and self.on_pending:
                user32.AppendMenuW(menu, MF_STRING, MENU_PENDING,
                                   self.strings.get("menu.pending", "Show what is waiting")
                                   .replace("{n}", str(waiting)))
            paused = not snapshot.get("enabled", True)
            user32.AppendMenuW(menu, MF_STRING, MENU_TOGGLE,
                               self.strings.get("menu.resume", "Resume recovery") if paused
                               else self.strings.get("menu.pause", "Pause recovery"))
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_STOP, self.strings.get("menu.stop", "Stop the watcher"))
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            # Without this the menu does not close when the user clicks elsewhere.
            user32.SetForegroundWindow(self._hwnd)
            chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                           point.x, point.y, 0, self._hwnd, None)
            user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        self._act(chosen, paused)

    def _act(self, chosen, paused):
        action = {MENU_OPEN: self.on_open, MENU_STOP: self.on_stop,
                  MENU_PENDING: self.on_pending}.get(chosen)
        try:
            if chosen == MENU_TOGGLE and self.on_toggle:
                self.on_toggle(paused)          # paused -> resume; running -> pause
            elif action:
                action()
        except Exception as exc:
            self.log("tray action failed (%s)" % type(exc).__name__)



    def _theme_menu(self):
        """Ask for a dark menu when the popup beside it is dark, and for Windows' own look otherwise.

        Resolved when the menu opens, the way the popup resolves it: the stored Theme, Windows' app
        mode for Use system setting, and High Contrast over both. Asked only when that changes. If
        Windows cannot be asked, or the request fails, the menu keeps the look it always had and
        nothing is asked again; the failure is logged once.
        """
        if not self._menu_theming:
            return
        try:
            from .. import tray_popup
            look = tray_popup.appearance(tray_popup.theme_setting(), tray_popup.apps_use_light_theme(),
                                         tray_popup.high_contrast())
            mode = menu_app_mode(look)
            if mode == self._menu_mode:
                return
            if prefer_app_mode(mode):
                self._menu_mode = mode
            else:
                self._menu_theming = False
        except Exception as exc:
            self._menu_theming = False
            self.log("tray menu theme failed (%s)" % type(exc).__name__)

"""The icon with the shell's words about hovering as the Python tests drive it, answered by the C# host's TrayIcon (S6.4d3,
P6-DESIGN 3.4 "window").

`HostTipTray` takes the reference `ui.tray.Tray`'s arguments a test hands it (strings, edition) and answers what
tests/test_tray_tip_messages.py's IconCase does to it - `_wndproc`, `_notify`, `_set_version`, `_show_tip`, `_open_popup`,
`update`, `_tip_shows`, `_shown` - by `tip_icon` questions of tests/rustdiff/HostProbe.cs: a TrayIcon whose window is the
test's number and whose every call of Windows is recorded, run through every step so far again from the start (the probe
keeps nothing between calls). What the test assigns is a step of that history: `_version4`, `_tip` (None, False, or a card
of the test's), `_popup` and `_menu_drawn` (their `visible`), `_taskbar_created`, `_session_locked`/`_session_away`. A
message carries the moment's clock (the test's patched `icon.time.monotonic`) and whether the pointer is on the icon (the
test's `_pointer_on_icon`, asked then).

What the host did is delivered to the test's own objects as the reference would have made it:

* the shell's Shell_NotifyIconW (its action, flags and szTip as NOTIFYICONDATAW holds it) and the timers, to the test's patched
  `icon._dll` - the shell's answer to NIM_SETVERSION is asked of it (the ask-back), once per question;
* each card's show (with the icon's box its reader gave, as a reader), hide and destroy, to the test's card in order;
* a card the host makes is asked of the test's `tipcard.TipCard` (what the test patched there): what it returns is the card,
  what it raises the host's making raising. What the host hands its own card (content, held, days) is not seen here: the
  probe's MakeTip replaces the making whole.

`_tip`, `_version4` are read back after each question: None, False (broken) or the test's card object.
"""
from __future__ import annotations

import ctypes
import time
import unittest.mock

import surfacehost
from codex_auto_resume.ui.tray import icon as icon_module, tipcard
from codex_auto_resume.ui.tray.win32 import NIM_SETVERSION, NOTIFYICONDATAW
from codex_auto_resume.ui.tray.words import TIP_CHARS

STEPPED = {"_version4", "_tip", "_popup", "_menu_drawn", "_taskbar_created", "_session_locked", "_session_away"}


class HostTipTray:
    def __init__(self, strings=None, edition=None, log=None, days=False, **unused):
        self.__dict__.update(strings=dict(strings or {}), edition=edition, log=log or (lambda *unused: None), days=days,
                             history=[], cards=[], versions=[], makes=[], made=[], delivered={"record": 0, "calls": {}},
                             _hwnd=None, _version4=False, _tip=None, _popup=None, _menu_drawn=None, _taskbar_created=None,
                             _session_locked=False, _session_away=False, _pointer_on_icon=lambda: False, _now=time.time())

    # ------------------------------------------------------------------ what the test assigns
    def __setattr__(self, name, value):
        self.__dict__[name] = value
        if name == "_version4":
            self.history.append(["version4", bool(value)])
        elif name == "_tip":
            if value is None or value is False:
                self.history.append(["tip", "none" if value is None else "broken"])
            else:
                if not any(card is value for card in self.cards):
                    self.cards.append(value)
                index = next(at for at, card in enumerate(self.cards) if card is value)
                self.history.append(["tip", "card", index, getattr(value, "fail", None)])
        elif name in ("_popup", "_menu_drawn"):
            self.history.append(["popup" if name == "_popup" else "menu_drawn",
                                 None if value is None else bool(getattr(value, "visible", False))])
        elif name == "_taskbar_created":
            self.history.append(["taskbar", int(value)])
        elif name in ("_session_locked", "_session_away"):
            self.history.append(["session", bool(self.__dict__["_session_locked"]), bool(self.__dict__["_session_away"])])

    # ------------------------------------------------------------------ the reference's members
    def update(self, snapshot, popup_view=None):
        self._go(["update", dict(snapshot)])

    def _wndproc(self, hwnd, message, wparam, lparam):
        clock = icon_module.time.monotonic()
        self._go(["message", int(message), int(wparam or 0), int(lparam or 0), float(clock), bool(self._pointer_on_icon())])
        return 0

    def _notify(self, action):
        self._go(["notify", int(action)])

    def _set_version(self):
        self._go(["set_version"])

    def _show_tip(self, wparam):
        self._go(["show_tip", int(wparam)])

    def _open_popup(self):
        self._go(["open_popup"])

    def _tip_shows(self):
        return self._go(["tip_shows"], keep=False)["results"][-1]

    def _shown(self):
        return self._go(["shown"], keep=False)["results"][-1]

    # ------------------------------------------------------------------ the run
    def _ask(self, steps):
        from codex_auto_resume.ui import popup
        return surfacehost.SERVE.ask(
            "tip_icon", hwnd=int(self._hwnd or 0), strings=self.strings, edition=self.edition, now=time.time(),
            icon_rect=list(popup.icon_rect(self._hwnd, 1)), versions=self.versions, makes=self.makes, steps=steps)

    def _shell(self, action, flags=0, tip=None):
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd, data.uID, data.uFlags = self._hwnd, 1, flags
        if tip is not None:
            data.szTip = tip[:TIP_CHARS - 1]
        return icon_module._dll("shell32").Shell_NotifyIconW(action, ctypes.byref(data))

    def _go(self, step, keep=True):
        steps = self.history + [step]
        while True:
            found = self._ask(steps)
            if not found["unanswered"]:
                break
            # the shell's answer to the next NIM_SETVERSION, or the test's card class for the next card made
            setversion = sum(1 for line in found["record"] if line.startswith("Shell_NotifyIconW %d " % NIM_SETVERSION))
            if setversion > len(self.versions):
                self.versions.append(bool(self._shell(NIM_SETVERSION)))
                continue
            if not isinstance(tipcard.TipCard, unittest.mock.Base):
                raise AssertionError("the host made a card where the test gave its own card class none")
            try:
                card = tipcard.TipCard(content=None, held=None, log=self.log, days=self.days)
            except Exception:
                self.makes.append("raise")
                continue
            self.made.append(card)
            self.makes.append("card")
        if keep:
            self.history.append(step)
            self._settle(found)
        return found

    def _settle(self, found):
        given = self.delivered
        for line in found["record"][given["record"]:]:
            parts = line.split(" ")
            if parts[0] == "Shell_NotifyIconW":
                action = int(parts[1])
                if action == NIM_SETVERSION:
                    continue                                         # asked of the test's shell already
                if len(parts) >= 5:
                    tip = " ".join(parts[4:])
                    self._shell(action, int(parts[2]), None if tip == "None" else tip.replace("\\n", "\n"))
                else:
                    self._shell(action)
            elif parts[0] in ("SetTimer", "KillTimer"):
                user32 = icon_module._dll("user32")
                arguments = [int(parts[1], 16)] + [int(part) for part in parts[2:]]
                getattr(user32, parts[0])(*(arguments + ([None] if parts[0] == "SetTimer" else [])))
        given["record"] = len(found["record"])
        # the host's cards in its own order: the test's (given) and the ones the test's class made
        owners = {}
        for index, at in found["given"]:
            owners[int(at)] = self.cards[int(index)]
        made = iter(self.made)
        for at in range(len(found["calls"])):
            if at not in owners:
                owners[at] = next(made)
        for at, calls in enumerate(found["calls"]):
            card = owners[at]
            for call in calls[given["calls"].get(at, 0):]:
                if call[0] == "show":
                    box = None if call[1] is None else tuple(int(n) for n in call[1])
                    card.show(icon=lambda box=box: box, point=tuple(int(n) for n in call[2]))
                elif call[0] == "hide":
                    card.hide(at_once=bool(call[1]))
                else:
                    card.destroy()
            given["calls"][at] = len(calls)
        holds = found["holds"]
        self.__dict__["_tip"] = None if holds == "none" else False if holds == "broken" else owners[int(holds)]
        self.__dict__["_version4"] = found["version4"]
        for line in found["logs"][given.get("logs", 0):]:
            self.log(line)
        given["logs"] = len(found["logs"])

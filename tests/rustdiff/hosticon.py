"""The notification-area icon as the Python tests drive it, answered by the C# host's TrayIcon (S6.4d, P6-DESIGN 3.4 "window").

`HostTray` takes the reference `ui.tray.Tray`'s arguments a test hands it (strings, on_open, on_toggle, on_stop, on_pending,
log, control) and answers the members those tests call - `_act`, `_refresh`, `_select`, `_failure_seen`, `_failure_unseen`,
`update`, `_shown`, `_menu`, `_native_menu`, `_drop_menu`, `_popup_can_open` - by `icon_steps` questions of
tests/rustdiff/HostProbe.cs: a TrayIcon with no window and no shell icon is given the state the test set on this object
(`strings`, `_failed`, `_unconfirmed`, `_last_tip`, `_hwnd`, `_menu_drawn`, the snapshot) and runs the step in
gui/TrayIcon.cs / gui/TrayMenu.cs. What it decides comes back and is all the test sees:

* what the icon posted through IHostActions, in order, handed to the callback the reference would have called - the core's
  half of the boundary (toggle {paused} -> on_toggle(paused), stop -> on_stop, open_dashboard {page None} -> on_open,
  {page "pending"} -> on_pending, failure_seen -> control.acknowledge_failure, disarm_power ->
  control.disarm_power_action("tray")). A post where the reference had no callback is a failure (the reference took no
  action there). A callback that raises is the post that raised: the run is made again with that post throwing, and the
  icon's own log lines are what the test's `log` hears;
* what the port's icon asks the core and the test answers - asked back, as surfaceproxy.py's perform is: the probe reports
  the first question it has no answer for, the test's object is asked it, and the step is run again with the answer, until
  nothing new is asked. Whether a failure is unseen (the test's control layer; a read that raises is "raise"); each
  opening of the drawn menu (the test's `_menu_drawn`, or what `popup.Menu` makes where the icon makes one: shown, refused,
  or raised); the command Windows' own menu returns (the test's patched user32, which is handed exactly the calls the host
  made: CreatePopupMenu, every AppendMenuW, TrackPopupMenu, DestroyMenu). The armed power action, which the port's icon
  reads from the snapshot the core sends (`power_armed`), is the test's control layer's `power_view()["armed"]`;
* the state after the step (`_failed`, `_unconfirmed`, `_shown()`, `_menu_drawn`: the object, None, or False once broken),
  the drawn menu's `destroy` as often as the host destroyed it, and the shell's NIM_MODIFY, which goes to the test's
  `_notify` where it replaced it, and the icon's Refresh, which goes to the test's `_refresh` where it replaced it (seen by
  the NIM_MODIFY a refresh from no tip always makes: in that case the step runs with no last tip).

A choice made later in a drawn menu (the `on_choose` the test's menu object was handed) replays the opening it came from -
the snapshot and answers of that moment - then the snapshot of now, then the choice, so the state the menu was drawn in is
the host's own capture, not this object's. Members the host has no seam for are kept on the object and not asked
(`_sync_motion`, `_adopt_settings`, `_theme_menu`: the host's are off or no-ops in the probe).
"""
from __future__ import annotations

import time

import surfacehost
from codex_auto_resume.ui import popup as reference_popup
from codex_auto_resume.ui.tray import menu as reference_menu

NIM_MODIFY = 1
ORIGINAL_DLL = reference_menu._dll


def menu_ids() -> dict:
    """The host's MENU_* numbers (gui/TrayMenu.cs), as the reference module names them."""
    return {name: int(value) for name, value in surfacehost.SERVE.ask("icon_menu_ids").items()}


class HostTray:
    def __init__(self, strings=None, on_open=None, on_toggle=None, on_stop=None, on_pending=None, log=None, control=None,
                 **unused):
        self.strings = dict(strings or {})
        self.on_open, self.on_toggle, self.on_stop, self.on_pending = on_open, on_toggle, on_stop, on_pending
        self.log = log or (lambda *unused: None)
        self.control = control
        self._failed = self._unconfirmed = False
        self._last_tip = None
        self._hwnd = None
        self._menu_drawn = None
        self._snapshot: dict = {}
        self._shown_state = None
        self.tips: list = []           # the tooltip texts the host's icon gave the shell, in order
        self.runs = 0

    # ------------------------------------------------------------------ the reference's members
    def update(self, snapshot, popup_view=None):
        self._snapshot = dict(snapshot or {})
        self._shown_state = None

    def _shown(self):
        if self._shown_state is None:
            self._step([])
        return dict(self._shown_state)

    def _act(self, chosen, paused):
        self._step([["act", chosen, bool(paused)]])

    def _refresh(self):
        self._step([["refresh"]])

    def _select(self, keyboard=False):
        self._step([["select", bool(keyboard)]])

    def _failure_seen(self):
        self._step([["failure_seen"]])

    def _failure_unseen(self, snapshot):
        return self._step([["unseen", dict(snapshot or {})]])["results"][0]

    def _menu(self):
        self._step([["menu"]])

    def _native_menu(self, items):
        return int(self._step([["native", list(items)]])["results"][0])

    def _drop_menu(self):
        self._step([["drop_menu"]])

    def _popup_can_open(self):
        return self._step([["popup_can_open"]])["results"][0]

    # ------------------------------------------------------------------ the run
    def _replaced(self, name):
        return name in self.__dict__

    def _actions(self):
        """The icon has an IHostActions where the reference had something to call: a control layer or a callback."""
        return self.control is not None or any(callback is not None for callback in
                                               (self.on_open, self.on_toggle, self.on_stop, self.on_pending))

    def _core_snapshot(self, snapshot):
        """The snapshot as the core sends it: with the armed power action the reference read from its control layer."""
        view = getattr(self.control, "power_view", None)
        if view is None:
            return snapshot
        try:
            armed = (view() or {}).get("armed")
        except Exception:
            armed = None
        return dict(snapshot, power_armed=armed)

    def _state(self):
        return {"snapshot": self._core_snapshot(self._snapshot), "strings": self.strings, "failed": self._failed,
                "unconfirmed": self._unconfirmed, "last_tip": None if self._replaced("_refresh") else self._last_tip,
                "actions": self._actions(), "pending": self.on_pending is not None, "now": time.time(),
                "hwnd": bool(self._hwnd), "menu_present": self._menu_drawn not in (None, False),
                "menu_broken": self._menu_drawn is False}

    def _answer(self, marks):
        try:
            return self.control.failure_unseen(marks) is True
        except Exception:
            return "raise"

    def _step(self, steps, state=None):
        state = dict(state or self._state(), steps=steps, answers=[], menu_answers=[], raises=[], native_choice=0)
        menu = self._menu_drawn if state["menu_present"] else None
        openings = []                  # the moment each drawn opening was made, for a choice in it later
        while True:
            found = surfacehost.SERVE.ask("icon_steps", **state)
            self.runs += 1
            if found["unanswered"]:
                if self.control is None:
                    raise AssertionError("the host's icon asked a core that the test gave no control layer")
                state["answers"] = state["answers"] + [self._answer(found["asked_with"])]
            elif found["menu_unanswered"]:
                if menu is None:
                    menu = reference_popup.Menu(log=self.log)
                entries, strings = found["menu_opens"][len(state["menu_answers"])]
                opened = dict(state, steps=steps[:steps.index(["menu"]) + 1] if ["menu"] in steps else steps)
                openings.append(opened)
                try:
                    answer = bool(menu.open(entries, strings, lambda chosen, at=opened: self._choose(at, chosen)))
                except Exception:
                    answer = "raise"
                state["menu_answers"] = state["menu_answers"] + [answer]
            else:
                break
        for index, opened in enumerate(openings):
            # a choice replays its opening with the answers that opening was given, and none past it
            opened.update(answers=state["answers"], menu_answers=state["menu_answers"][:index + 1])
        tracked = [line for line in found["record"] if line.startswith("TrackPopupMenu")]
        if tracked:
            if len(tracked) > 1:
                raise AssertionError("the host's icon showed Windows' menu twice in one step")
            chosen = self._windows_menu(found["record"])
            if chosen != state["native_choice"]:
                state["native_choice"] = chosen
                found = surfacehost.SERVE.ask("icon_steps", **state)
        return self._settle(found, state, menu)

    def _choose(self, opened, chosen):
        """A choice in a drawn menu: its opening replayed with that moment's answers, the snapshot of now, the choice."""
        state = dict(opened, steps=opened["steps"] + [["update", self._core_snapshot(self._snapshot)], ["choose", chosen]])
        found = surfacehost.SERVE.ask("icon_steps", **state)
        if found["unanswered"] or found["menu_unanswered"]:
            raise AssertionError("a choice in the drawn menu asked something its opening had not")
        self._settle(found, state, self._menu_drawn or None)

    def _windows_menu(self, record):
        """The calls the host made of Windows' own menu, made again of the test's user32: the command it returns."""
        dll = reference_menu._dll
        if dll is ORIGINAL_DLL:
            raise AssertionError("the host showed Windows' menu where the test patched no user32 to answer it")
        user32 = dll("user32")
        menu = user32.CreatePopupMenu()
        chosen = 0
        for line in record:
            if line.startswith("AppendMenuW "):
                _, flags, identifier, text = line.split(" ", 3)
                user32.AppendMenuW(menu, int(flags), int(identifier), None if text == "None" else text.replace("\\n", "\n"))
            elif line.startswith("TrackPopupMenu "):
                _, flags, x, y = line.split(" ")
                chosen = int(user32.TrackPopupMenu(menu, int(flags), int(x), int(y), 0, self._hwnd, None))
            elif line == "DestroyMenu":
                user32.DestroyMenu(menu)
        return chosen

    def _settle(self, found, state, menu):
        raised = [index for index, (action, fields) in enumerate(found["posted"]) if self._deliver(action, fields)]
        if raised:
            found = dict(found, logs=surfacehost.SERVE.ask("icon_steps", **dict(state, raises=raised))["logs"])
        self._failed, self._unconfirmed = found["failed"], found["unconfirmed"]
        shown = dict(found["shown"])
        if "power_armed" not in self._snapshot:
            shown.pop("power_armed", None)
        self._shown_state = shown
        for line in found["logs"]:
            self.log(line)
        if menu is not None:
            for unused in range(int(found["menu_destroyed"])):
                menu.destroy()
        if found["menu_broken"]:
            self._menu_drawn = False
        elif found["menu_there"]:
            self._menu_drawn = menu
        elif state["menu_present"] or found["menu_made"]:
            self._menu_drawn = None
        modified = [line for line in found["record"] if line.startswith("Shell_NotifyIconW %d " % NIM_MODIFY)]
        for line in modified:
            self.tips.append(line.split(" ", 4)[4].replace("\\n", "\n") if line.count(" ") >= 4 else None)
        if self._replaced("_refresh"):
            for unused in modified:
                self._refresh()
        elif self._replaced("_notify"):
            for unused in modified:
                self._notify(NIM_MODIFY)
        if self._replaced("_popup_for_click") and found["popup"]:
            popup = self._popup_for_click()
            for name in found["popup"]:
                if name.startswith("on_select"):
                    popup.on_select(keyboard=name.endswith("keyboard"))
                else:
                    getattr(popup, name)()
        return found

    def _deliver(self, action, fields) -> bool:
        """The posted action handed to what the reference called; True when that raised."""
        if action == "toggle":
            target, arguments = self.on_toggle, (fields["paused"],)
        elif action == "stop":
            target, arguments = self.on_stop, ()
        elif action == "open_dashboard":
            target = self.on_pending if fields.get("page") == "pending" else self.on_open
            arguments = ()
        elif action == "failure_seen":
            target, arguments = getattr(self.control, "acknowledge_failure", None), ()
        elif action == "disarm_power":
            target, arguments = getattr(self.control, "disarm_power_action", None), ("tray",)
        else:
            raise AssertionError("the host's icon posted an action no test callback stands for: %r" % action)
        if target is None:
            # the reference had nothing to call: an action the host posts here is one the reference never took
            raise AssertionError("the host's icon posted %r where the reference had no callback to call" % action)
        try:
            target(*arguments)
        except Exception:
            return True
        return False

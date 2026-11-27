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
from codex_auto_resume.ui.popup import menuwindow as _menuwindow  # noqa: E402
ORIGINAL_MENU_DLL = _menuwindow._dll


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


# ---------------------------------------------------------------------------------------------------- the drawn menu
def _entries(items):
    return [dict(item) if item else None for item in items]


class HostMenuKeys:
    """menuplan's menu_step, menu_end and menu_letter, answered by the host's MenuPlan (HostProbe.cs `menu_keys`)."""

    @staticmethod
    def menu_step(entries, current, backwards=False):
        return _int(surfacehost.SERVE.ask("menu_keys", asked=[["step", _entries(entries), current, bool(backwards)]])[0])

    @staticmethod
    def menu_end(entries, last=False):
        return _int(surfacehost.SERVE.ask("menu_keys", asked=[["end", _entries(entries), None, bool(last)]])[0])

    @staticmethod
    def menu_letter(entries, current, character):
        index, chooses = surfacehost.SERVE.ask("menu_keys", asked=[["letter", _entries(entries), current, character]])[0]
        return _int(index), chooses


def _int(value):
    return None if value is None else int(value)


class HostMenu:
    """The drawn menu (ui/popup/menuwindow.py's Menu) as tests/test_tray_menu_drawn.py BehaviourTests drives it, answered by
    the host's MenuWindow with no window (HostProbe.cs `menu_messages`).

    The test sets `entries`, `strings`, `on_choose`, `visible`, `selected` and `_spoken` and sends messages to `_handle`;
    each assignment and message is a step of one history, which is run from the start on a fresh MenuWindow for every
    question (the probe keeps nothing between calls), so what the test reads - `selected`, `visible`, `_plan`, what
    `accessible_items()` says, what `_handle` returned - is the host's state after its own handling of every step so far.
    The plan is the host's own, its renderer's MenuLayout at scale 1 as its Open lays it out, read back through `_plan`, so
    where the test points (its `at(index)`) is an item's rectangle in the host's plan; the test's own assignment of the
    reference's plan is not taken (that the two plans are the same is the drawing's, seat S6.4f's). What the host chose goes to `on_choose`, what it told a screen reader to the test's `_tell`,
    and each announcement to `access.announce(self, before, after)` with the host's own item lists - after checking that the
    host's SurfaceAccess.Changes of them are the reference's `access.changes`.
    """

    hwnd = None

    class _renderer:                 # the reference's renderer as the test lays a plan out with it: the host lays its own
        @staticmethod
        def menu_layout(*unused, **ignored):
            return None

    def __init__(self, entries=None, strings=None, on_choose=None, scale=1.0, create=False, owner=None, on_leave=None,
                 locale="en", origin=None):
        """`create`: the menu has its own window, made and never shown (a submenu's, and the pointer's rest timer, need
        one; tests/test_popup_row_menu_drawn.py SubmenuTests' fake create gave it a handle)."""
        self.__dict__.update(entries=list(entries or []), strings=dict(strings or {}), on_choose=on_choose, scale=scale,
                             create=create, owner=owner, on_leave=on_leave, locale=locale, origin=origin,
                             history=[], delivered=0, chosen=0, left=0, records=0, last=None)

    # attributes the test assigns are steps of the history
    def __setattr__(self, name, value):
        if name == "visible":
            self.history.append(["visible", bool(value)])
        elif name == "selected":
            self.history.append(["select", value])
        elif name == "_spoken":
            self.history.append(["spoken"])
        elif name == "_plan":
            pass                     # the host lays its own plan out (see the class's head)
        else:
            self.__dict__[name] = value
            return
        self.__dict__["last"] = None

    def _run(self, extra=()):
        return surfacehost.SERVE.ask("menu_messages", entries=_entries(self.entries), strings=self.strings,
                                     scale=self.scale, steps=self.history + list(extra), create=self.create,
                                     owner=self.owner, locale=self.locale, origin=self.origin,
                                     leave=self.on_leave is not None)

    def _state(self):
        if self.last is None:
            self.__dict__["last"] = self._run([["accessible"]])
        return self.last

    def _now(self):
        return self._state()["steps"][-1]

    @property
    def visible(self):
        return self._now()["visible"]

    @property
    def selected(self):
        return _int(self._now()["selected"])

    @property
    def _plan(self):
        return _plan(self._state()["plan"])

    @property
    def _child(self):
        return HostSubmenu(self) if self._now()["child"] is not None else None

    @property
    def _child_index(self):
        return _int(self._now()["child_index"])

    def accessible_items(self):
        items = self._now()["returned"]
        return [dict(item, target=_int(item["target"]), rect=tuple(int(n) for n in item["rect"])) for item in items]

    def _push(self):
        """The reference's own push; the host's draws offscreen in the probe."""

    def _tell(self, event):
        """The reference's own tell; the host's tellings are handed here."""

    def _handle(self, message, wparam=0, lparam=0, step="send"):
        self.history.append([step, message, wparam, lparam])
        self.__dict__["last"] = None
        found = self._state()
        step = found["steps"][-2]
        told = step["told"]
        from codex_auto_resume.ui.popup import access
        for kind, *rest in told[self.delivered:]:
            if kind == "tell":
                self._tell(int(rest[0]))
            else:
                before, after, changes = rest
                expected = [list(change) for change in access.changes(before, after)]
                if [[int(n) for n in change] for change in changes] != expected:
                    raise AssertionError("the host's announcement %r is not the reference's %r" % (changes, expected))
                access.announce(self, before, after)
        self.__dict__["delivered"] = len(told)
        self._windows(found["record"][self.records:int(step["records"])])
        self.__dict__["records"] = int(step["records"])
        for unused in range(int(step["left"]) - self.left):
            self.on_leave()
        self.__dict__["left"] = int(step["left"])
        for identifier in step["chosen"][self.chosen:]:
            self.on_choose(None if identifier is None else int(identifier))
        self.__dict__["chosen"] = len(step["chosen"])
        returned = step["returned"]
        return None if returned is None else int(returned)

    @staticmethod
    def _windows(record):
        """The host's SetForegroundWindow and SetTimer calls, made again of the test's patched user32 (menuwindow._dll);
        nothing where the test patched none."""
        from codex_auto_resume.ui.popup import menuwindow
        if menuwindow._dll is ORIGINAL_MENU_DLL:
            return
        user32 = menuwindow._dll("user32")
        for line in record:
            parts = line.split(" ")
            if parts[0] == "SetForegroundWindow":
                user32.SetForegroundWindow(int(parts[1], 16))
            elif parts[0] == "SetTimer":
                user32.SetTimer(int(parts[1], 16), int(parts[2]), int(parts[3]), None)


def _plan(plan):
    return {"items": [dict(item, index=_int(item["index"]), rect=tuple(int(n) for n in item["rect"])) for item in plan["items"]],
            "card": tuple(int(n) for n in plan["card"]), "rtl": plan["rtl"]}


class HostSubmenu:
    """The open submenu of a HostMenu, read from the root's run; a message to it is a step of the root's history."""

    def __init__(self, root):
        self._root = root

    def _now(self):
        return self._root._now()["child"]

    @property
    def visible(self):
        return self._now()["visible"]

    @property
    def selected(self):
        return _int(self._now()["selected"])

    @property
    def entries(self):
        """The parent's item's own entries where the host's submenu holds exactly those objects, else what it holds."""
        found = self._now()
        if found["entries_of"] is not None:
            return self._root.entries[int(found["entries_of"])]["items"]
        return found["entries"]

    @property
    def _plan(self):
        return _plan(self._now()["plan"])

    def _handle(self, message, wparam=0, lparam=0):
        return self._root._handle(message, wparam, lparam, step="send_child")

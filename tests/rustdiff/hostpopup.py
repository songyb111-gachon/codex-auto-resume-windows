"""The popup's row menu and focus as the Python tests drive them, answered by the C# host's PopupWindow (S6.4d, P6-DESIGN
3.4 "window").

`HostPopup` takes the reference `ui.popup.Popup`'s arguments a test hands it (strings, make_menu, log) and answers what
tests/test_popup_row_menu_drawn.py calls - `_context_menu`, `_handle`, `hide`, `destroy` - by `popup_steps` questions of
tests/rustdiff/HostProbe.cs: a PopupWindow whose window is a message-only window of the probe's (never shown), given the
core's popup, what the test painted and its row menu, runs every step so far again from the start (the probe keeps nothing
between calls), so what the test sees is the host's state after its own handling of the whole history:

* the core's popup is the test's model's - `model.view(now)` at the `now` the test last asked of it and `model.menu_for` of
  each task - as the core sends it (`{view, menus, read}`; car-watcher's surface field is the same two calls);
* what the popup posted through IHostActions goes to the test's `_run` as the reference's action tuple (`popup {call, args}`
  -> (kind, *args), `open_dashboard` -> ("dashboard",) or ("dashboard_row", ...)): the core's half of the boundary;
* each opening of the row menu is asked back of the test's object (what its `make_menu` makes, as often as the host made
  one, or the `_row_menu` it set): `open(entries, strings, on_choose, point=, owner=, on_leave=)` with the host's own numbered
  entries, point and owner (the popup's window: the test's `hwnd`), and its click-away (the host's own `Hide`: this object's
  `hide`). A choice in it later is a step that runs the host's chooser of that opening;
* the menu's `close` and `destroy` as often as the host called them; where the test replaced `hide` on this object, a hide
  the host made while handling a message goes to the test's replacement instead, with the closes that hide made (as the
  reference's replaced hide would not have made them);
* `visible` and `_row_menu` (the object, None, or False once broken) after the last step; the host's log lines to `log`.

Where the host would open Windows' own row menu the probe stops (PopupWindow.ContextMenu calls user32 for it directly, not
through SurfaceScreen, so it cannot run unrecorded) and this object fails: those tests wait for that half to be probe-safe.
"""
from __future__ import annotations

import time

import surfacehost
from codex_auto_resume.ui.popup.model import PopupModel

CALL_KINDS = {"set_interruption_recovery": "recovery", "set_enabled": "enabled", "postpone": "postpone",
              "unpostpone": "unpostpone", "release_hold": "release", "set_thread_tier": "tier",
              "set_project_rule": "project", "set_once_words": "unsay"}


class CoreModel(PopupModel):
    """The core's model of the popup: the reference's, remembering the `now` it was last asked to view."""

    now = None

    def view(self, now):
        self.now = now
        return super().view(now)


def _ids(entries):
    """A menu's entries as the reference numbers them: every id an int."""
    found = []
    for entry in entries:
        if entry is None:
            found.append(None)
            continue
        entry = dict(entry)
        if isinstance(entry.get("id"), float):
            entry["id"] = int(entry["id"])
        if entry.get("items"):
            entry["items"] = _ids(entry["items"])
        found.append(entry)
    return found


def action_of(name, fields):
    """The reference's action tuple for what the host posted."""
    if name == "popup":
        return (CALL_KINDS[fields["call"]],) + tuple(fields["args"])
    if name == "open_dashboard":
        row = fields.get("row")
        return ("dashboard",) if row is None else ("dashboard_row",) + tuple(row)
    raise AssertionError("the host's popup posted an action the reference has no call for: %r" % name)


class HostPopup:
    def __init__(self, strings=None, make_menu=None, log=None, **unused):
        self.__dict__.update(strings=dict(strings or {}), make_menu=make_menu, log=log or (lambda *unused: None),
                             model=CoreModel(strings), hwnd=None, history=[], menu_answers=[], made=[], given=None,
                             delivered={"posted": 0, "closed": 0, "destroyed": 0, "logs": 0},
                             _painted_plan=None, _row_menu=None, visible=False, focus=None)
        self.__dict__["_run"] = lambda action: None
        self.__dict__["_update"] = lambda *unused: None

    # what the test assigns that is a step of the history
    def __setattr__(self, name, value):
        if name == "visible":
            self.history.append(["visible", bool(value)])
        elif name == "focus":
            self.history.append(["focus"] + (list(value) if value else [None, None]))
        elif name == "_row_menu":
            if value is False:
                self.history.append(["row_menu", False])
            elif value is None:
                self.history.append(["row_menu", None])
            else:
                self.__dict__["given"] = value
                self.history.append(["row_menu", "there"])
        self.__dict__[name] = value

    def _replaced(self, name):
        return name in self.__dict__

    # ------------------------------------------------------------------ the reference's members
    def _context_menu(self, lparam):
        self._go(["context", int(lparam)])

    def _handle(self, hwnd, message, wparam, lparam):
        self._go(["message", int(message), int(wparam), int(lparam or 0)])
        return 0

    def hide(self):
        self._go(["hide"])

    def destroy(self):
        self._go(["destroy"])

    # ------------------------------------------------------------------ the run
    def _core(self):
        vm = self.model.view(self.model.now if self.model.now is not None else time.time())
        menus = [[task["interruption_id"], self.model.menu_for(task["interruption_id"])] for task in vm["tasks"]]
        return {"view": vm, "menus": menus, "read": True, "attention": False}

    def _object(self):
        """The test's row menu the host's opens stand for: the last its make_menu made, or the one it set."""
        return self.made[-1] if self.made else self.given

    def _ask(self):
        painted = self._painted_plan
        menu = self._object()
        return surfacehost.SERVE.ask(
            "popup_steps", strings=self.strings, core=self._core(),
            painted=None if painted is None else {"rows": [[key, list(rect)] for key, rect in painted.get("rows") or ()],
                                                  "rtl": painted.get("rtl")},
            make_menu=self.make_menu is not None, menu_hwnd=getattr(menu, "hwnd", None),
            menu_answers=self.menu_answers, steps=self.history)

    def _go(self, step):
        self.history.append(step)
        while True:
            found = self._ask()
            last = found["steps"][-1]
            while len(self.made) < int(last["made"]):
                self.made.append(self.make_menu())
            if not found["unanswered"] or len(found["opens"]) <= len(self.menu_answers):
                break
            index = len(self.menu_answers)
            opening = found["opens"][index]
            try:
                answer = bool(self._object().open(
                    _ids(opening["entries"]), dict(opening["strings"]),
                    lambda command, at=index: self._go(["choose", at, int(command)]),
                    point=None if opening["point"] is None else tuple(int(n) for n in opening["point"]),
                    owner=self.hwnd if opening["owner"] == "popup" else int(opening["owner"]),
                    on_leave=None if opening["leave"] is None else
                    (self.hide if opening["leave"] == "hide" else lambda at=index: self._go(["leave", at]))))
            except Exception:
                answer = "raise"
            self.menu_answers.append(answer)
        if found["windows"]:
            raise AssertionError("the host's popup went to Windows' own row menu, which PopupWindow.ContextMenu shows by "
                                 "calling user32 directly; the probe does not run it")
        if len(found["steps"]) != len(self.history):
            raise AssertionError("the host's popup stopped before the last step")
        self._settle(found, step)

    def _settle(self, found, step):
        last, given = found["steps"][-1], self.delivered
        for line in found["logs"][given["logs"]:]:
            self.log(line)
        given["logs"] = len(found["logs"])
        menu = self._object()
        closes = int(last["closed"]) - given["closed"]
        given["closed"] = int(last["closed"])
        if step[0] != "hide" and int(last["hid"]) and self._replaced("hide"):
            for unused in range(int(last["hid"])):
                self.__dict__["hide"]()
        else:
            for unused in range(closes):
                menu.close()
        for unused in range(int(last["destroyed"]) - given["destroyed"]):
            menu.destroy()
        given["destroyed"] = int(last["destroyed"])
        self.__dict__["visible"] = last["visible"]
        self.__dict__["_row_menu"] = {"none": None, "broken": False}.get(last["row_menu"], menu)
        posted = found["posted"][given["posted"]:]
        given["posted"] = len(found["posted"])
        for name, fields in posted:
            self._run(action_of(name, fields))

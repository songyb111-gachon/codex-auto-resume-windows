"""The notification-area icon as the Python tests drive it, answered by the C# host's TrayIcon (S6.4d, P6-DESIGN 3.4 "window").

`HostTray` takes the reference `ui.tray.Tray`'s arguments a test hands it (strings, on_open, on_toggle, on_stop, on_pending,
log, control) and answers the members those tests call - `_act`, `_refresh`, `_select`, `_failure_seen`, `_failure_unseen`,
`update`, `_shown` - by one `icon_steps` question of tests/rustdiff/HostProbe.cs each: a TrayIcon with no window and no shell
icon is given the state the test set on this object (`strings`, `_failed`, `_unconfirmed`, `_last_tip`, the snapshot) and runs
the one step in gui/TrayIcon.cs / gui/TrayMenu.cs. What it decides comes back and is all the test sees:

* what the icon posted through IHostActions, in order, handed to the callback the reference would have called - the core's
  half of the boundary (toggle {paused} -> on_toggle(paused), stop -> on_stop, open_dashboard {page None} -> on_open,
  {page "pending"} -> on_pending, failure_seen -> control.acknowledge_failure, disarm_power ->
  control.disarm_power_action("tray")); a callback that raises is the post that raised, so the run is made again with that
  post throwing and the icon's own log lines are what the test's `log` hears;
* whether a failure is unseen, which the port's icon asks of the core: the probe reports the question unanswered with the
  marks it was asked about, the test's control layer is asked them, and the step is run again with the answer (a read that
  raises is "raise"), until the icon asks nothing new;
* the state after the step (`_failed`, `_unconfirmed`, `_shown()`), and the shell's NIM_MODIFY, which goes to the test's
  `_notify` where it replaced it, and the icon's Refresh, which goes to the test's `_refresh` where it replaced it (seen by
  the NIM_MODIFY a refresh from no tip always makes: in that case the step runs with no last tip).

Members a test replaces on the object are the reference's seams; the ones the host has no seam for are kept on the object and
not asked (`_sync_motion`, `_adopt_settings`, `_adopt_reduce_motion`: the host's are no-ops in the probe). `_popup_for_click`
replaced means the probe's recording popup, whose calls are handed to the one the test returned.
"""
from __future__ import annotations

import surfacehost

NIM_MODIFY = 1
SEAMS = ("_notify", "_refresh", "_popup_for_click")


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

    # ------------------------------------------------------------------ the run
    def _replaced(self, name):
        return name in self.__dict__

    def _actions(self):
        """The icon has an IHostActions where the reference had something to call: a control layer or a callback."""
        return self.control is not None or any(callback is not None for callback in
                                               (self.on_open, self.on_toggle, self.on_stop, self.on_pending))

    def _ask(self, steps, answers, raises, witness):
        return surfacehost.SERVE.ask(
            "icon_steps", steps=steps, answers=answers, raises=raises, snapshot=self._snapshot, strings=self.strings,
            failed=self._failed, unconfirmed=self._unconfirmed, last_tip=None if witness else self._last_tip,
            actions=self._actions(), pending=self.on_pending is not None, now=0.0)

    def _answer(self, marks):
        try:
            return self.control.failure_unseen(marks) is True
        except Exception:
            return "raise"

    def _step(self, steps):
        witness = self._replaced("_refresh")
        answers: list = []
        while True:
            found = self._ask(steps, answers, [], witness)
            self.runs += 1
            if not found["unanswered"]:
                break
            if self.control is None:
                raise AssertionError("the host's icon asked a core that the test gave no control layer")
            answers.append(self._answer(found["asked_with"]))
        raised = [index for index, (action, fields) in enumerate(found["posted"]) if self._deliver(action, fields)]
        if raised:
            found = dict(found, logs=self._ask(steps, answers, raised, witness)["logs"])
        self._failed, self._unconfirmed = found["failed"], found["unconfirmed"]
        self._shown_state = found["shown"]
        for line in found["logs"]:
            self.log(line)
        modified = [line for line in found["record"] if line.startswith("Shell_NotifyIconW %d " % NIM_MODIFY)]
        for line in modified:
            self.tips.append(line.split(" ", 4)[4].replace("\\n", "\n") if line.count(" ") >= 4 else None)
        if witness:
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

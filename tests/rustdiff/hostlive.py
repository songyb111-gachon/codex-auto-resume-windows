"""The drawn menu's own real window and the icon started for real, as the Python live tests drive them, answered by the C#
host (S6.4d6, P6-DESIGN 3.4 "window").

The originals make real windows and read them with Windows itself: tests/test_menu_opening_motion.py WindowTests (the
drawn menu shown far off every screen, fading in and out on its own timer), tests/test_tray_menu_drawn.py LiveWindowTests
(the same window read as a screen reader reads it, through the test's own AccessibleObjectFromWindow) and tests/test_tray.py
LiveIconTests (the notification-area icon started, its tooltip changed by the tick, stopped and its thread ended). The main
session's word of 2026-11-28 bounds the twins: they show what the originals show - the host's real menu window, the host's
real tray icon - exactly as the originals do (the same far-off coordinates, never activated, no focus or foreground
change, removed in the test's own teardown), inside gui_lock.sh, never a dialog.

* `HostLiveMenu` takes what the tests hand the reference `popup.Menu` and answers what they read, by `menu_live` questions
  of tests/rustdiff/HostProbe.cs: ONE MenuWindow made by its own Create, kept on a thread of its own between questions.
  A window's handle is the same in every process, so the original's own user32 calls (ShowWindow, IsWindowVisible) and
  its own AccessibleObjectFromWindow reach the host's window unchanged. Each question carries what the test's patched
  `menuwindow.look.reduced_motion` answers now. Its fade's frames, each read at its own instant, are handed to the lists
  the test's `recorded("opening")` / `recorded("closing")` return, in the reference's words (elapsed, alpha, below, done)
  / (elapsed, alpha, done); a choice the host's menu made is handed to the test's `on_choose`.
* `HostLiveTray` takes what the test hands the reference `tray.Tray` (icon_path, strings) and answers `start`, `update`,
  `stop`, `_last_tip` and `_thread.is_alive()` by `icon_live` questions: the host's TrayIcon on a thread of its own.
"""
from __future__ import annotations

import surfacehost
from codex_auto_resume.ui.popup import menuwindow


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def _int(value):
    return int(value) if isinstance(value, float) and value == int(value) else value


class _Plan:
    """A plan the test asked the menu's renderer for: the host lays out the same entries at the same scale and locale."""

    def __init__(self, entries, scale, locale, max_width):
        if max_width is not None:
            raise AssertionError("the live tests lay the menu out with no width cap")
        self.step = ["plan", plain(entries), float(scale), str(locale)]


class _Renderer:
    def menu_layout(self, entries, scale, locale, max_width=None):
        return _Plan(entries, scale, locale, max_width)


class HostLiveMenu:
    """The reference `popup.Menu` as the live tests drive it, over `menu_live` (see the module's words)."""

    _STEPS = {"entries": "entries", "strings": "strings", "_origin": "origin", "_theme": "theme", "contrast": "contrast",
              "visible": "visible"}

    def __init__(self, recorders=None, running=False, **unused):
        self.__dict__.update(_id=None, _state=None, _recorders=recorders if recorders is not None else {},
                             _running=bool(running), _chosen=0, _fades=0, on_choose=None, _renderer=_Renderer(),
                             entries=[], strings={}, contrast=False)

    # ------------------------------------------------------------------ the host's questions
    def _ask(self, op, **fields):
        fields["reduced"] = bool(menuwindow.look.reduced_motion())
        state = surfacehost.SERVE.ask("menu_live", op=op, **fields)
        self.__dict__["_state"] = state
        for chosen in state["chosen"][self._chosen:]:
            self.__dict__["_chosen"] += 1
            if self.on_choose is not None:
                self.on_choose(_int(chosen))
        for way, elapsed, alpha, below, done in state["fades"][self._fades:]:
            self.__dict__["_fades"] += 1
            if way == "in" and "opening" in self._recorders:
                self._recorders["opening"].append((elapsed, int(alpha), int(below), bool(done)))
            elif way == "out" and "closing" in self._recorders:
                self._recorders["closing"].append((elapsed, int(alpha), bool(done)))
        return state

    def _do(self, *steps):
        if self._id is None:
            raise AssertionError("the host's menu is not made")
        return self._ask("do", id=self._id, steps=[list(step) for step in steps])

    def refresh(self):
        """The host's menu as it is now (a screen reader's call may have changed it)."""
        return self._do()

    def pump(self, seconds):
        """Windows' messages for the host's menu thread for `seconds`, as the reference's test pumps its own."""
        if self._id is not None:
            self._do(("pump", float(seconds)))

    # ------------------------------------------------------------------ the reference Menu's surface
    def create(self):
        state = self._ask("new", running=self._running)
        self.__dict__["_id"] = int(state["id"])

    def destroy(self):
        if self._id is not None:
            self._ask("end", id=self._id)
            self.__dict__["_id"] = None

    def _appear(self):
        self._do(("appear",))

    def _push(self):
        self._do(("push",))

    def close(self, quietly=False):
        self._do(("close", bool(quietly)))

    def __setattr__(self, name, value):
        if name == "_plan":
            self._do(value.step)
        elif name in self._STEPS:
            self.__dict__[name] = value
            if name in ("entries", "strings"):
                value = plain(value)
            elif name == "_origin":
                value = [int(n) for n in value]
            elif name in ("contrast", "visible"):
                value = bool(value)
            self._do((self._STEPS[name], value))
        else:
            self.__dict__[name] = value

    @property
    def hwnd(self):
        return int(self._state["hwnd"]) or None

    @property
    def visible(self):
        return bool(self._state["visible"])

    @property
    def _alpha(self):
        return int(self._state["alpha"])

    @property
    def _below(self):
        return int(self._state["below"])

    @property
    def _fade(self):
        way = self._state["fade"]
        return None if way is None else (way,)


class _Thread:
    def __init__(self, owner):
        self._owner = owner

    def is_alive(self):
        return bool(self._owner._read()["alive"])


class HostLiveTray:
    """The reference `tray.Tray` as tests/test_tray.py LiveIconTests drives it, over `icon_live`."""

    started = []                                     # every icon started and not yet stopped, for the twin's teardown

    def __init__(self, icon_path=None, strings=None, **unused):
        self._icon, self._strings, self._id, self._thread = str(icon_path), plain(dict(strings or {})), None, None

    def start(self):
        state = surfacehost.SERVE.ask("icon_live", op="start", icon=self._icon, strings=self._strings)
        self._id, self._thread = int(state["id"]), _Thread(self)
        HostLiveTray.started.append(self)
        return bool(state["started"])

    def update(self, snapshot):
        surfacehost.SERVE.ask("icon_live", op="update", id=self._id, snapshot=plain(dict(snapshot)))

    def stop(self):
        if self._id is None:
            return
        state = surfacehost.SERVE.ask("icon_live", op="stop", id=self._id)
        if not state["alive"] and self in HostLiveTray.started:
            HostLiveTray.started.remove(self)

    def _read(self):
        return surfacehost.SERVE.ask("icon_live", op="read", id=self._id)

    @property
    def _last_tip(self):
        return self._read()["last_tip"]

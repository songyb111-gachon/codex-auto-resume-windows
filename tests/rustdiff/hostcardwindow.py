"""The popup with its own real windows, as the Python window tests drive it, answered by the C# host's PopupWindow (S6.4d5,
P6-DESIGN 3.4 "window").

`HostCardPopup` takes the arguments the tests hand the reference `ui.popup.Popup` (a control layer, strings, a log) and
answers what tests/test_popup_card_window.py's CardWindowTests and the motion tests' WindowTests read and call, by
`popup_live` questions of tests/rustdiff/HostProbe.cs. Unlike the other host twins, which replay a history on windows that
are never shown, the host keeps ONE PopupWindow made by its own Create - the card and its shadow, real top-level layered
windows - on a thread of its own between questions, because the originals make exactly those windows and read them with
user32 (styles, owner, class, rectangles, region, visibility): a window's handle is the same in every process, so the
original's own user32 calls read the host's windows unchanged. The main session's word of 2026-11-28 bounds it: the
originals' far-off coordinates, never activated, destroyed in the test's teardown, inside gui_lock.sh, never a dialog.

* The core's popup is the test's control layer read as the reference reads it (`perform(("read",), control)` into the
  reference's model), sent as the core sends it (`{view, menus, read}`).
* Each question carries the look the test's patched questions give now - `theme.high_contrast`, `theme.reduced_motion`,
  `theme.text_scale`, `window.effective_theme`, `window.design_setting` - which the host's popup is asked through (its
  AskContrast, AskReduced, AskTextScale and the adopted theme and design).
* Where the test records the layers' uploads (its `recorded()`), the host records its popup's calls instead of making them
  (SurfaceScreen's probe mode) from then on: each `update` line becomes (hwnd, keywords) as the reference's
  `layers.update` is called; a SetLayeredWindowAttributes the host records is handed to the test's patched
  `messages._dll` (its guard), never to the real one. While recording, what the popup posts itself and its frame and tick
  timers are delivered by the host when the test pumps.
* Its log lines go to the test's `log`.
"""
from __future__ import annotations

import ctypes
import re
import time

import surfacehost
from codex_auto_resume.ui import popup as tray_popup
from codex_auto_resume.ui.popup import layers as popup_layers, messages as popup_messages
from codex_auto_resume.ui.popup.model import PopupModel, perform

_REAL_UPDATE = popup_layers.update
_REAL_DLL = popup_messages._dll
_REAL_SCREEN = tray_popup.window.Popup._screen_now
_UPDATE = re.compile(r"^update (\S+) \(([^,]+), ([^)]+)\) (\S+) (\([^)]*\)|None) (\([^)]*\)|None) (\([^)]*\)|None)$")


def _tuple(value):
    if isinstance(value, list):
        return tuple(_tuple(item) for item in value)
    return value


def _int(value):
    return int(value) if isinstance(value, float) and value == int(value) else value


def _numbers(text):
    if text == "None":
        return None
    return tuple(_int(float(part)) for part in text.strip("()").split(",") if part.strip())


def look():
    """What the test's patched questions answer now: the host's popup is asked through the same five."""
    theme_module = tray_popup.theme
    apps = theme_module.apps_use_light_theme()
    held = getattr(look, "held", None)
    return {"contrast": bool(theme_module.high_contrast()), "reduced": bool(theme_module.reduced_motion()),
            "text": float(theme_module.text_scale()),
            "theme": tray_popup.window.effective_theme(tray_popup.window.theme_setting(), apps),
            "design": tray_popup.window.design_setting(), "still": held() if callable(held) else False}


def plain(value):
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


class _Renderer:
    def __init__(self, owner):
        self._owner = owner

    @property
    def lone(self):
        return self._owner._state["lone"]

    @property
    def halo_rows(self):
        rows = self._owner._state["halo_rows"]
        return None if rows is None else tuple(int(n) for n in rows)


class _Layers:
    def __init__(self, owner):
        self._owner = owner

    @property
    def shadow_hwnd(self):
        return int(self._owner._state["shadow"]) or None

    @property
    def margin(self):
        margin = self._owner._state["margin"]
        return None if margin is None else int(margin)

    @property
    def shadows(self):
        return tuple(_tuple(shadow) for shadow in self._owner._state["shadows"])


class _Canvas:
    def __init__(self, first):
        self._first = bytes(int(n) for n in first)

    def pixels(self):
        """The first pixel's four bytes, in memory order (all the tests read of it)."""
        return self._first


class HostCardPopup:
    def __init__(self, control=None, strings=None, log=None, calls=None, **unused):
        model = PopupModel(strings)
        if control is not None:
            model.apply_outcome(("read",), perform(("read",), control), time.time())
        vm = model.view(time.time())
        menus = [[task["interruption_id"], model.menu_for(task["interruption_id"])] for task in vm["tasks"]]
        self._log = log or (lambda *unused: None)
        self._calls = calls
        self._seen = {"logs": 0, "records": 0}
        self._ended = False
        self._state = surfacehost.SERVE.ask("popup_live", op="new", strings=dict(strings or {}), look=look(),
                                            core=plain({"view": vm, "menus": menus, "read": True, "attention": False}),
                                            record=calls is not None)
        self._id = self._state["id"]
        self._renderer = _Renderer(self)
        self._layers = _Layers(self)
        self._settle()

    # ------------------------------------------------------------------ the run
    def _do(self, *steps, op="do"):
        if self._ended:
            return [None] * len(steps)
        self._state = surfacehost.SERVE.ask("popup_live", op=op, id=self._id, look=look(), steps=[list(step) for step in steps])
        self._settle()
        return self._state["answers"]

    def _settle(self):
        state, seen = self._state, self._seen
        for line in state["logs"][seen["logs"]:]:
            self._log(line)
        seen["logs"] = len(state["logs"])
        records = state["records"][seen["records"]:] if state["recording"] else []
        seen["records"] = len(state["records"]) if state["recording"] else 0
        names = {"card": int(state["hwnd"]), "shadow": int(state["shadow"])}
        for line in records:
            found = _UPDATE.match(line)
            if found and self._calls is not None:
                name, x, y, alpha, size, source, dirty = found.groups()
                self._calls.append((names.get(name, name), {"at": (_int(float(x)), _int(float(y))), "alpha": _int(float(alpha)),
                                                             "size": _numbers(size), "source": _numbers(source),
                                                             "dirty": _numbers(dirty)}))
            elif line.startswith("SetLayeredWindowAttributes ") and popup_messages._dll is not _REAL_DLL:
                parts = line.split()
                popup_messages._dll("user32").SetLayeredWindowAttributes(names.get(parts[1], parts[1]), 0, int(parts[2]), 2)

    def record(self, calls):
        """The test records the layers' uploads from now on, into `calls`."""
        self._calls = calls
        self._do(("record", True))

    def pump(self, seconds=0.05):
        self._do(("pump", float(seconds)))

    # ------------------------------------------------------------------ the reference's members
    @property
    def hwnd(self):
        return int(self._state["hwnd"]) if self._state["live"] else None

    @property
    def visible(self):
        return self._state["visible"]

    @property
    def _card(self):
        return self._state["card"]

    @property
    def _rounded(self):
        return self._state["rounded"]

    @property
    def _alpha(self):
        return int(self._state["alpha"])

    @property
    def _below(self):
        return int(self._state["below"])

    @property
    def _opening(self):
        opening = self._state["opening"]
        return None if opening is None else tuple(opening)

    @property
    def _owed(self):
        return self._state["owed"]

    @property
    def _frame_running(self):
        return self._state["frames"]

    @property
    def _plan(self):
        plan = self._state["plan"]
        if plan is None:
            return None
        return {"card": _tuple(plan["card"]), "size": _tuple(plan["size"]), "scale": plan["scale"],
                "targets": [(_tuple(target), _tuple(rect)) for target, rect in plan["targets"]]}

    @property
    def _static_dirty(self):
        return self._state["static_dirty"]

    @_static_dirty.setter
    def _static_dirty(self, value):
        self._do(("static_dirty", bool(value)))

    @property
    def hover(self):
        raise AttributeError("the host's hover is set, not read, by these tests")

    @hover.setter
    def hover(self, target):
        targets = [entry[0] for entry in self._plan["targets"]]
        self._do(("hover_index", targets.index(_tuple(target))))

    def show(self, keyboard=False, activate=True, origin=None):
        steps = []
        if tray_popup.window.Popup._screen_now is not _REAL_SCREEN:
            screen = tray_popup.window.Popup._screen_now(self)
            steps.append(("screen", plain(screen)))
        if popup_layers.update is not _REAL_UPDATE and not popup_layers.update(None, at=(0, 0), alpha=0, dc=None, size=(0, 0)):
            steps.append(("refuse",))
        steps.append(("show", bool(keyboard), bool(activate), None if origin is None else [int(n) for n in origin]))
        self._do(*steps)

    def hide(self):
        self._do(("hide",))

    def destroy(self):
        if not self._ended:
            self._do(op="end")
            self._ended = True

    def _read_look(self):
        self._do(("read_look",))

    def _invalidate(self):
        self._do(("invalidate",))

    def _push(self):
        self._do(("push",))

    def _update(self, *unused):
        self._do(("update",))

    def _hit(self, lparam):
        found = self._do(("hit", int(lparam)))[0]
        return _tuple(found)

    def _client_offset(self):
        return _tuple(self._do(("client_offset",))[0])

    def render(self):
        return _Canvas(self._do(("render",))[0])


class HostAccessible:
    """access.PopupAccessible over the host's popup: its children (SurfaceAccess.AccessibleItems) and accLocation as the
    host's client object answers it to a reader (AccessibleObjectFromWindow on the host's own window)."""

    def __init__(self, window):
        self.window = window

    def items(self):
        found = self.window._do(("access", 0))[0]["items"]
        return [dict(item, target=_tuple(item["target"]), rect=_tuple(item["rect"])) for item in found]

    def _location(self, this, left, top, width, height, *variant):
        from codex_auto_resume.ui.popup import access
        if access._WIDE:
            child = ctypes.cast(variant[0], ctypes.POINTER(access.VARIANT)).contents.value.lVal
        else:
            child = variant[2]
        result, *box = self.window._do(("access", int(child)))[0]["location"]
        for pointer, value in zip((left, top, width, height), box):
            pointer.contents.value = int(value)
        return int(result)

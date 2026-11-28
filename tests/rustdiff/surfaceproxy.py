"""CODEX_AR_CORE=rust: the popup's pure half, as car-surface (S6.4, P6-DESIGN 3.4 "pure").

`shim.install()` calls `install(module)` as `codex_auto_resume.ui.popup.words` and `...popup.model` load, so every
module that reaches the popup's words and its view model by name - the popup package, the window, the icon, a test -
asks car-surface and not Python: `say`, `one_line`, `kept`, `locale_of`, and `activity`, `light_for`, `icon_attention`,
`watcher_known_running`, `snapshot_activity`, `urgency`, `is_waiting`, `task_item`, `row_menu`, `view_model`,
`busy_key`, `select_action`. Each is one case of `car-harness serve`'s `surface.batch` (the cases tests/rustdiff/
diffs_surface_popup.py holds equal to the tag), answered in one `car-harness serve` process the whole run shares.

What stays Python's, and why: `PopupModel` and `perform` read and write the objects a test hands in (a control layer, a
Dashboard, a clock), which car-surface's own scripted case (`popup.model`, `popup.perform`) holds equal but a test cannot
hand its objects to; they are asked back over the pipe only when a later seat needs them. The drawing half (layout,
renderer, windows) is C#'s (gui/host.sources), not car-surface's.

An answer comes back as JSON, so the tuples Python's functions return are made tuples again where the reference has them
(`urgency`, `busy_key`, a view model's `counts`, an action) - the same values, so a test's `assertEqual` against a tuple
holds as it did. A Python exception the reference would raise is raised here by its class name; nothing falls back to
Python on a refusal.

Self-contained: stdlib only at import (it loads by path before anything is on sys.path); the product is imported where used.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ROOT = Path(__file__).resolve().parents[2]
FLOAT_TAG = "$float"
MODULES = ("codex_auto_resume.ui.popup.words", "codex_auto_resume.ui.popup.model", "codex_auto_resume.ui.words",
           "codex_auto_resume.ui.tray.model", "codex_auto_resume.ui.tray.words", "codex_auto_resume.ui.tray.menu", "codex_auto_resume.ui.tray.motion",
           "codex_auto_resume.ui.tray.dashboard")
HOMES = ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "CODEX_HOME", "TEMP", "TMP")

BUILTINS = {"ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError, "AttributeError": AttributeError,
            "OSError": OSError, "IndexError": IndexError, "ZeroDivisionError": ZeroDivisionError,
            "OverflowError": OverflowError, "RuntimeError": RuntimeError}


def harness() -> Path:
    named = os.environ.get("CODEX_AR_HARNESS_EXE")
    if named:
        return Path(named)
    target = Path(os.environ["CARGO_TARGET_DIR"]) if os.environ.get("CARGO_TARGET_DIR") else ROOT / "rust" / "target"
    return target / "release" / "car-harness.exe"


def tagged(value):
    if isinstance(value, float):
        if value != value:
            return {FLOAT_TAG: "nan"}
        if value in (float("inf"), float("-inf")):
            return {FLOAT_TAG: "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, (list, tuple)):
        return [tagged(each) for each in value]
    if isinstance(value, dict):
        return {key: tagged(each) for key, each in value.items()}
    return value


def untagged(value):
    if isinstance(value, dict):
        if list(value) == [FLOAT_TAG]:
            return float(value[FLOAT_TAG])
        return {key: untagged(each) for key, each in value.items()}
    if isinstance(value, list):
        return [untagged(each) for each in value]
    return value


class Pipe:
    """The one `car-harness serve` of this process, started at the first call, ended with the process. It runs with
    every home variable pointed into a folder of its own: it never reads this person's profile."""

    def __init__(self):
        self.lock, self.process, self.next_id, self.home, self.calls = threading.Lock(), None, 0, None, {}

    def start(self):
        self.home = tempfile.mkdtemp(prefix="car-surface-proxy-")
        environment = {name: value for name, value in os.environ.items() if name not in ("CODEX_AR_CORE",)}
        environment.update({name: self.home for name in HOMES})
        # Never this PC's Codex: an engine discovery under the proxy finds no codex.exe to start.
        environment["CODEX_AUTO_RESUME_CODEX_EXE"] = str(Path(self.home) / "no-codex" / "codex.exe")
        self.process = subprocess.Popen([str(harness()), "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=environment, creationflags=NO_WINDOW)
        atexit.register(self.stop)

    def case(self, *case):
        return self.ask("surface.batch", case)

    def leaf(self, *case):
        """A case of car-harness's `leaves.batch` (car-words' ui/words.py and the like)."""
        return self.ask("leaves.batch", case)

    def ask(self, call, case):
        with self.lock:
            if self.process is None:
                self.start()
            self.next_id += 1
            self.calls[case[0]] = self.calls.get(case[0], 0) + 1
            request = {"id": self.next_id, "call": call, "cases": [tagged(list(case))], "scratch": self.home}
            self.process.stdin.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            self.process.stdin.flush()
            line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("car-harness ended (%s)" % harness())
        reply = json.loads(line.decode("utf-8"))["reply"]
        if not reply.get("ok"):
            raise RuntimeError("car-harness refused %s: %s" % (case[0], line[:300]))
        answer = reply["value"][0]
        if "error" in answer:
            raise BUILTINS.get(answer["error"], RuntimeError)(answer["error"])
        return untagged(answer["ok"])

    def stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(timeout=20)
        except Exception:
            process.kill()
        finally:
            if os.environ.get("CAR_SURFACE_PROXY_REPORT"):
                with open(os.environ["CAR_SURFACE_PROXY_REPORT"], "a", encoding="utf-8") as out:
                    out.write(json.dumps({"pid": os.getpid(), "calls": self.calls}, sort_keys=True) + "\n")


PIPE = Pipe()


def _locale() -> str:
    """The language this process speaks, as the reference's `l10n.current()` says it."""
    from codex_auto_resume import l10n
    return l10n.current()


def _tuple_action(value):
    return tuple(value) if isinstance(value, list) else value


def _menu(entries):
    """A row menu's entries with their actions as tuples again (the reference writes `("postpone", key, thread, ...)`)."""
    out = []
    for entry in entries:
        if isinstance(entry, dict):
            entry = dict(entry, action=_tuple_action(entry.get("action")))
            if isinstance(entry.get("items"), list):
                entry["items"] = _menu(entry["items"])
        out.append(entry)
    return out


def _task(task):
    if isinstance(task, dict):
        for key, value in list(task.items()):
            if isinstance(value, list) and key in ("action", "actions"):
                task[key] = _tuple_action(value) if key == "action" else [_tuple_action(each) for each in value]
    return task


def _says_as(say):
    """Which shipped catalog `say` speaks: the one whose text it gives for a set of keys, as `l10n.text(key, locale)` does.
    car-words' functions take a locale, not a callable; a callable that is no catalog's cannot be sent."""
    from codex_auto_resume import l10n
    probes = (("time.just_now", {}), ("time.ago", {"time": "T"}), ("time.seconds", {"n": 7}), ("time.hours", {"n": 3}),
              ("usage.limit", {}), ("usage.weekly", {}), ("usage.days", {"n": 2}), ("usage.minutes", {"n": 45}),
              ("usage.window", {"window": "W", "percent": 12}),
              ("usage.window_resets", {"window": "W", "percent": 12, "time": "12:34"}),
              ("usage.line", {"age": "A", "windows": "X"}))
    try:
        said = [say(key, **fields) for key, fields in probes]
    except Exception:
        said = None
    for locale in l10n.LOCALES:
        if said is not None and said == [l10n.text(key, locale, **fields) for key, fields in probes]:
            return locale
    raise TypeError("the words this `say` gives are no shipped catalog's: car-words takes a locale")


def _stamps(*moments):
    """The broken-down local times the Rust side is handed for `clock_time`: what the platform gives it."""
    import time
    stamps = {}
    for value in moments:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            local = time.localtime(value)
            stamps[repr(float(value))] = [local.tm_year, local.tm_mon, local.tm_mday, local.tm_hour, local.tm_min]
    return stamps


def _ui_words(module):
    leaf = PIPE.leaf

    def countdown(seconds):
        return leaf("words.countdown", seconds)

    def age(seconds, say):
        return leaf("words.age", seconds, _says_as(say))

    def clock_time(at, now):
        stamps = _stamps(at, now)
        return leaf("words.clock_time", stamps[repr(float(at))], stamps[repr(float(now))], at, now)

    def window_name(minutes, say):
        return leaf("words.window_name", minutes, _says_as(say))

    def share(window):
        return leaf("words.share", window)

    def left(window):
        return leaf("words.left", window)

    def _keeping(keep):
        if keep is not None and not getattr(keep, "rust_kept", False):
            raise TypeError("a custom `keep` cannot be sent to car-words")
        return keep is not None

    def usage_windows(windows, say, now, keep=None):
        moments = [now] + [window.get("reset_at") for window in (windows or ()) if isinstance(window, dict)]
        return leaf("words.usage_windows", windows, _says_as(say), _keeping(keep), now, _stamps(*moments))

    def usage_line(reading, say, now, keep=None):
        moments = [now]
        if isinstance(reading, dict) and isinstance(reading.get("windows"), list):
            moments += [window.get("reset_at") for window in reading["windows"] if isinstance(window, dict)]
        return leaf("words.usage_line", reading, _says_as(say), _keeping(keep), now, _stamps(*moments))

    for function in (countdown, age, clock_time, window_name, share, left, usage_windows, usage_line):
        function.rust_core = "words"
        function.__wrapped__ = getattr(module, function.__name__)
        function.__doc__ = function.__wrapped__.__doc__
        setattr(module, function.__name__, function)


def _tray_model(module):
    original = module.snapshot_from

    def snapshot_from(store, now):
        """The four things the snapshot reads of a store, each as it answers (or raises), sent as car-surface's stand-in."""
        def field(read):
            try:
                return read()
            except Exception as error:
                return {"raise": type(error).__name__}
        spec = {"pending": field(lambda: list(store.pending())),
                "disabled": field(lambda: list(store.disabled_threads())),
                "settings": field(store.settings), "marks": field(store.failure_marks)}
        return PIPE.case("tray.snapshot", spec)

    snapshot_from.rust_core = "surface"
    snapshot_from.__wrapped__ = original
    snapshot_from.__doc__ = original.__doc__
    module.snapshot_from = snapshot_from


def _host():
    """surfacehost.py, loaded by path once: the host's render mode."""
    import importlib.util
    import sys
    found = sys.modules.get("rustdiff_surfacehost")
    if found is None:
        spec = importlib.util.spec_from_file_location("rustdiff_surfacehost", Path(__file__).resolve().with_name(
            "surfacehost.py"))
        found = importlib.util.module_from_spec(spec)
        sys.modules["rustdiff_surfacehost"] = found
        spec.loader.exec_module(found)
    return found


def _tray_words(module):
    """The icon's words as the C# host makes them (gui/TrayWords.cs, the render mode's `tray_words` case): the reference's
    parts, tooltip, joined text and meter line from a snapshot, the catalog, the moment and the edition."""
    original = {name: getattr(module, name) for name in ("tooltip_parts", "tooltip", "tooltip_joined", "meter_line")}

    def ask(snapshot, strings, now, edition):
        return {"name": "tray_words", "snapshot": snapshot, "strings": strings, "now": now, "edition": edition}

    def lines(parts):
        parts["line"] = [tuple(piece) for piece in parts["line"]]
        return parts

    def tooltip_parts(snapshot, strings, now, edition=None):
        return lines(_host().SERVE.ask(**ask(snapshot, strings, now, edition))["parts"])

    def tooltip(snapshot, strings, now, edition=None):
        return _host().SERVE.ask(**ask(snapshot, strings, now, edition))["tooltip"]

    def tooltip_joined(parts):
        return _host().SERVE.ask("tray_joined", parts=parts)

    def meter_line(snapshot, strings):
        return _host().SERVE.ask(**ask(snapshot, strings, 0.0, None))["meter_line"]

    for name, function in (("tooltip_parts", tooltip_parts), ("tooltip", tooltip), ("tooltip_joined", tooltip_joined),
                           ("meter_line", meter_line)):
        function.rust_core = "host"
        function.__wrapped__ = original[name]
        function.__doc__ = original[name].__doc__
        function.__name__ = name
        setattr(module, name, function)


def _tray_menu(module):
    """What the icon's menu offers (gui/TrayMenu.cs `MenuItems`), as the host's probe answers it."""
    original = module.menu_items

    def menu_items(snapshot, strings, now, pending=False, armed=None, popup=False):
        found = _host().SERVE.ask("menu_items", snapshot=snapshot, strings=strings, now=now, pending=bool(pending),
                                  armed=armed, popup=bool(popup))
        return [None if item is None else item for item in found]

    menu_items.rust_core = "host"
    menu_items.__wrapped__ = original
    menu_items.__doc__ = original.__doc__
    module.menu_items = menu_items


def _tray_motion(module):
    """The icon's state from a tick's snapshot (gui/TrayMotion.cs's states, gui/TipPlan.cs's activity word), as the probe answers it."""
    original = module.icon_state

    def icon_state(snapshot, *, attention=False, failed=False):
        import time
        return _host().SERVE.ask("icon_state", snapshot=snapshot, attention=bool(attention), failed=bool(failed),
                                 now=time.time())

    icon_state.rust_core = "host"
    icon_state.__wrapped__ = original
    icon_state.__doc__ = original.__doc__
    module.icon_state = icon_state


def _words(module):
    case = PIPE.case

    def say(strings, key, **fields):
        return case("popup.say", strings, key, fields)

    def one_line(text, limit=120):
        return case("popup.one_line", text, limit)

    def kept(strings):
        locale = _locale()

        def keep(value):
            return case("popup.kept", strings, locale, value)

        keep.rust_kept = True
        return keep

    def locale_of(strings):
        return case("popup.locale_of", strings, _locale())

    for function in (say, one_line, kept, locale_of):
        function.rust_core = "surface"
        function.__wrapped__ = getattr(module, function.__name__)
        function.__doc__ = function.__wrapped__.__doc__
        setattr(module, function.__name__, function)


def _model(module):
    case = PIPE.case
    original = {name: getattr(module, name) for name in (
        "activity", "light_for", "icon_attention", "watcher_known_running", "snapshot_activity", "urgency", "is_waiting",
        "_blocked", "task_item", "row_menu", "view_model", "busy_key", "select_action", "newest_reading")}

    def newest_reading(status):
        # Integration 12: the v0.6.26 final's rule (domain/usage.newest), car-surface's `popup::model::newest_reading`.
        return case("popup.newest_reading", status)

    def activity(status, rows, now):
        return case("popup.activity", status, rows, now)

    def light_for(status, word, rows=None):
        return case("popup.light", status, word, rows)

    def icon_attention(status, rows):
        return case("popup.icon_attention", status, rows)

    def watcher_known_running(status, rows):
        return case("popup.known_running", status, rows)

    def snapshot_activity(snapshot, now, *, attention=False):
        return case("popup.snapshot_activity", snapshot, now, attention)

    def urgency(row):
        return tuple(case("popup.urgency", row))

    def is_waiting(row):
        return case("popup.is_waiting", row)

    def _blocked(watcher):
        return case("popup.blocked", watcher)

    def task_item(row, strings, now, keep=None):
        if keep is not None and not getattr(keep, "rust_kept", False):
            raise TypeError("a custom `keep` cannot be sent to car-surface")
        return _task(case("popup.task", row, strings, now, _locale()))

    def row_menu(task, strings, default_tier):
        return _menu(case("popup.row_menu", task, strings, default_tier))

    def view_model(rows, status, strings, now, *, notice=None, error=None):
        found = case("popup.view_model", rows, status, strings, now, notice, error, _locale())
        found["counts"] = [tuple(each) for each in found["counts"]]
        found["tasks"] = [_task(each) for each in found["tasks"]]
        return found

    def busy_key(action):
        found = case("popup.busy_key", list(action) if isinstance(action, tuple) else action)
        return None if found is None else tuple(found)

    def select_action(visible, now, *, hidden_at=None, double_click_at=None, previous_key_at=None, keyboard=False):
        return case("popup.select", visible, now, hidden_at, double_click_at, previous_key_at, keyboard)

    _perform(module)
    _popup_model(module)
    for name, function in (("activity", activity), ("light_for", light_for), ("icon_attention", icon_attention),
                           ("watcher_known_running", watcher_known_running), ("snapshot_activity", snapshot_activity),
                           ("urgency", urgency), ("is_waiting", is_waiting), ("_blocked", _blocked),
                           ("task_item", task_item), ("row_menu", row_menu), ("view_model", view_model),
                           ("busy_key", busy_key), ("select_action", select_action),
                           ("newest_reading", newest_reading)):
        function.rust_core = "surface"
        function.__wrapped__ = original[name]
        function.__doc__ = original[name].__doc__
        function.__name__ = name
        setattr(module, name, function)


# ------------------------------------------------------------------------------ perform and PopupModel: the objects asked back
PROXIED_FOR = ("test_dont_postpone", "test_postpone_and_tiers", "test_popup_row_menu_parity", "test_surface_askback")
CONTROL_SHAPES = {
    # Rust's recorded call name -> how the reference writes the call: (method, positional indexes, keyword name -> index)
    "list_pending": ("list_pending", (), {"source": 0}),
    "get_status": ("get_status", (), {}),
    "set_enabled": ("set_enabled", (0,), {}),
    "set_interruption_recovery": ("set_interruption_recovery", (0, 1, 2), {}),
    "postpone": ("postpone", (0, 1), {"preset": 2}),
    "unpostpone": ("unpostpone", (0, 1), {}),
    "release_hold": ("release_hold", (0, 1), {}),
    "set_thread_tier": ("set_thread_tier", (0, 1), {"interruption_id": 2}),
    "set_project_rule": ("set_project_rule", (0, 1, 2), {"source": 3}),
    "set_once_words": ("set_once_words", (0, 1, 2), {}),
}


def _plain(value):
    """A control layer's answer as JSON carries it; what JSON cannot carry cannot be sent to car-surface."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(each) for key, each in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(each) for each in value]
    raise TypeError("an answer of %s cannot be sent to car-surface" % type(value).__name__)


def _raised(error):
    code = getattr(error, "code", None)
    return {"raise": type(error).__name__, "code": code if isinstance(code, str) else None}


def _perform(module):
    """`perform(action, control, *, source, dashboard)`: car-surface decides which control calls the action makes, in what
    order and with what; each is made here, once and in that order, on the control layer the test handed in, and its answer
    (or the exception it raised, as its class and `code`) is what car-surface is run again with. The first call not yet
    answered is the reference's next call: everything before it was answered for real, so the path to it is the reference's."""
    original = module.perform

    def ask(action, spec, source, dashboard):
        return PIPE.case("popup.perform", list(action) if isinstance(action, (tuple, list)) else action, spec, source,
                         dashboard)

    def perform(action, control, *, source=None, dashboard=None):
        spec, answered = {}, set()
        # The Codex source is only ever handed on, and Rust only asks whether there is one: a token stands for the object.
        token = None if source is None else "$source:%d" % id(source)
        for _ in range(16):
            found = ask(action, spec, token, None if dashboard is None else spec.get("dashboard", {"ok": True}))
            fresh = [call for call in found["calls"] if call[0] not in answered]
            if not fresh:
                break
            call = fresh[0]
            name = call[0]
            try:
                if name == "dashboard":
                    row = call[1]
                    answer = _plain(dashboard() if row is None else dashboard(row=tuple(row)))
                else:
                    method, positional, keywords = CONTROL_SHAPES[name]
                    args = [call[1 + index] for index in positional]
                    kwargs = {key: (source if call[1 + index] == token and token is not None else call[1 + index])
                              for key, index in keywords.items()
                              if not (name == "list_pending" and call[1 + index] is None)}
                    answer = _plain(getattr(control, method)(*args, **kwargs))
            except Exception as error:
                answer = _raised(error)
            answered.add(name)
            spec[name] = answer
        else:
            raise RuntimeError("car-surface asked more of the control layer than a perform makes")
        names = [call[0] for call in found["calls"]]
        if len(set(names)) != len(names):
            raise TypeError("a perform that asks the same control call twice cannot be routed: the answers are by name")
        return tuple(found["result"])

    perform.rust_core = "surface"
    perform.__wrapped__ = original
    perform.__doc__ = original.__doc__
    module.perform = perform


def _popup_model(module):
    """`PopupModel`: its state lives in car-surface's, which a test reaches by replay - every step the test took is sent again
    with the question, as the `popup.model` script case takes them (diffs_surface_popup.py holds that case equal to the
    reference's). Attributes are read from the state after the last step; assigning one is refused, which no routed test does."""
    original = module.PopupModel
    state_names = ("rows", "status", "read_failed", "notice_key", "notice_until", "busy", "drawn_paused", "wants_read")

    class PopupModel:
        rust_core = "surface"
        __wrapped__ = original

        def __new__(cls, strings=None):
            # Only the tests that hold the model itself get the proxy (PROXIED_FOR): Python's own popup window and the tests that
            # hand a model to it (it sets `strings` and `wants_read` on it as it runs, and every paint asks it again) keep the
            # original - that window is what the C# host replaces, and a replay per paint would be quadratic.
            import sys
            if sys._getframe(1).f_globals.get("__name__", "") not in PROXIED_FOR:
                return original(strings)
            return object.__new__(cls)

        def __init__(self, strings=None):
            object.__setattr__(self, "strings", dict(strings or {}))
            object.__setattr__(self, "_steps", [])
            object.__setattr__(self, "_known", None)
            object.__setattr__(self, "_view", {"tasks": []})
            object.__setattr__(self, "_assigned", {})

        def _flush(self):
            """A test that sets `rows` and `status` directly: the same two values as one successful read (which also
            clears `read_failed`, so a model that has failed cannot be set this way)."""
            assigned = self._assigned
            if not assigned:
                return
            current = (PIPE.case("popup.model", self.strings, _locale(), list(self._steps) + [["state"]])[-1]["ok"]
                       if self._steps else {"rows": None, "status": None, "read_failed": False})
            rows, status = assigned.get("rows", current["rows"]), assigned.get("status", current["status"])
            if rows is None or status is None or current["read_failed"]:
                raise TypeError("rows and status can be set only together, on a model whose last read did not fail")
            assigned.clear()
            self._steps.append(["apply", ["read"], ["ok", {"rows": rows, "status": status}], 0.0])
            object.__setattr__(self, "_known", None)

        def _run(self, *tail):
            self._flush()
            found = PIPE.case("popup.model", self.strings, _locale(), list(self._steps) + list(tail))
            out = found[len(self._steps):]
            for entry in out:
                if "error" in entry:
                    raise BUILTINS.get(entry["error"], RuntimeError)(entry["error"])
            return [entry["ok"] for entry in out]

        def _state(self):
            self._flush()
            if self._known is None:
                object.__setattr__(self, "_known", self._run(["state"])[0])
            return self._known

        def _step(self, *step):
            found = self._run(list(step))[0]
            self._steps.append(list(step))
            object.__setattr__(self, "_known", None)
            return found

        def __getattr__(self, name):
            if name in state_names:
                value = self._state()[name]
                if name == "busy":
                    return {tuple(json.loads(each)) for each in value}
                return value
            raise AttributeError(name)

        def __setattr__(self, name, value):
            if name not in ("rows", "status"):
                raise TypeError("the popup's state is car-surface's: %s cannot be assigned" % name)
            self._assigned[name] = value

        @property
        def drawn(self):
            return {task["interruption_id"]: (task["thread_id"], task["checked"]) for task in self._view["tasks"]}

        @property
        def drawn_tasks(self):
            return {task["interruption_id"]: dict(task) for task in self._view["tasks"]}

        def view(self, now):
            found = self._step("view", now)
            found["counts"] = [tuple(each) for each in found["counts"]]
            found["tasks"] = [_task(each) for each in found["tasks"]]
            object.__setattr__(self, "_view", found)
            return found

        def action_for(self, target):
            if not target:
                return None
            found = self._run(["action_for", list(target)])[0]
            return None if found is None else tuple(found)

        def menu_for(self, interruption_id):
            return _menu(self._run(["menu_for", interruption_id])[0])

        def begin(self, action):
            return self._step("begin", list(action))

        def apply_outcome(self, action, outcome, now):
            self._step("apply", list(action), list(outcome), now)

        def attention(self):
            return self._run(["attention"])[0]

    PopupModel.__name__ = "PopupModel"
    PopupModel.__doc__ = original.__doc__
    module.PopupModel = PopupModel


# ------------------------------------------------------------------------------ the Dashboard opener (S6.4e)
def _opener(module):
    """`open_dashboard` and `open_chat` (ui/tray/dashboard.py), `PAGES` and `ROW_DIALOGS`: car-watcher's dashboard.rs, as the
    harness compiles it again over a scratch world (rust/crates/car-harness/src/opener.rs, held to the tag by
    diffs_ui_opener.py), decides what is refused (the class and the message), whether there is a window to open, which
    hand-over it asks for and what it would start. What a test stands in for is asked back, in the reference's shapes:

    * the hand-over to an open window is the test's `win.handover.hand_over` at call time, called as the reference calls
      it - `hand_over(exe, page)`, or `hand_over(exe, page, row)` with a row - with the exe as a Path; its truthiness is the
      answer Rust is run again with (an exception it raises is the test's verdict and propagates);
    * the start Rust records (argv, working folder, creation flags) is handed to `subprocess.Popen` at call time, as the
      reference calls it (`cwd=`, `close_fds=True`, `creationflags=`). An OSError from it is dropped and the open answers
      True, because dashboard.rs drops the start's error (`let _ = ...`): a difference from the reference, which raises it,
      that diffs_ui_opener's expected failure names.

    A home is sent as `str(Path(home))` (the watcher's paths are resolved on both sides); a page that is not text, or a row
    or thread JSON cannot carry, is not sent (TypeError): car-watcher is never handed one (api.rs reads the host's action)."""
    from pathlib import Path as _Path
    originals = {"open_dashboard": module.open_dashboard, "open_chat": module.open_chat}
    found = PIPE.case("opener.consts")
    module.ROW_DIALOGS, module.PAGES = tuple(found[4]), tuple(found[5])

    def home_of(home):
        return str(_Path(home))

    def started(found):
        result = found["result"]
        if "error" in result:
            raise BUILTINS.get(result["error"], RuntimeError)(result.get("message", result["error"]))
        for start in found["started"]:
            try:
                module.subprocess.Popen(list(start["argv"]), cwd=start["cwd"], close_fds=True,
                                        creationflags=start["flags"])
            except OSError:
                pass
        return result["ok"]

    def open_dashboard(home, page=None, row=None):
        if page is not None and not isinstance(page, str):
            raise TypeError("a page that is not text cannot be sent to the port")
        sent, world = (home_of(home), page, _plain(row)), {}
        for _ in range(3):
            found = PIPE.case("opener.dashboard", *sent, world)
            if not found["handed"] or "hand_over" in world:
                break
            from codex_auto_resume.win import handover
            exe, asked_page, asked_row = found["handed"][0]
            answer = (handover.hand_over(_Path(exe), asked_page, asked_row) if asked_row is not None
                      else handover.hand_over(_Path(exe), asked_page))
            world = {"hand_over": bool(answer)}
        else:
            raise RuntimeError("car-watcher asked more than one hand-over of an open")
        return started(found)

    def open_chat(home, thread_id):
        return started(PIPE.case("opener.chat", home_of(home), _plain(thread_id), {}))

    for name, function in (("open_dashboard", open_dashboard), ("open_chat", open_chat)):
        function.rust_core = "surface"
        function.__wrapped__ = originals[name]
        function.__doc__ = originals[name].__doc__
        function.__name__ = name
        setattr(module, name, function)


def install(module) -> None:
    """Replace the module's pure functions as it loads; once."""
    if getattr(module, "_rust_surface", False):
        return
    if module.__name__.endswith("popup.words"):
        _words(module)
    elif module.__name__.endswith("popup.model"):
        _model(module)
    elif module.__name__.endswith("ui.words"):
        _ui_words(module)
    elif module.__name__.endswith("tray.model"):
        _tray_model(module)
    elif module.__name__.endswith("tray.words"):
        _tray_words(module)
    elif module.__name__.endswith("tray.menu"):
        _tray_menu(module)
    elif module.__name__.endswith("tray.motion"):
        _tray_motion(module)
    elif module.__name__.endswith("tray.dashboard"):
        _opener(module)
    module._rust_surface = True

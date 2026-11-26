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
           "codex_auto_resume.ui.tray.model", "codex_auto_resume.ui.tray.words", "codex_auto_resume.ui.tray.menu", "codex_auto_resume.ui.tray.motion")
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
        "_blocked", "task_item", "row_menu", "view_model", "busy_key", "select_action")}

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

    for name, function in (("activity", activity), ("light_for", light_for), ("icon_attention", icon_attention),
                           ("watcher_known_running", watcher_known_running), ("snapshot_activity", snapshot_activity),
                           ("urgency", urgency), ("is_waiting", is_waiting), ("_blocked", _blocked),
                           ("task_item", task_item), ("row_menu", row_menu), ("view_model", view_model),
                           ("busy_key", busy_key), ("select_action", select_action)):
        function.rust_core = "surface"
        function.__wrapped__ = original[name]
        function.__doc__ = original[name].__doc__
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
    module._rust_surface = True

"""What the S7.2c-remainder diffs (seat adv72d) share: `win/stopflag`, `win/waketimer`, `codex/tokens`,
`codex/wmi_escape`, `protocol.Session`/`submitted`, `codex/headless`, `codex/ipc` and `turns.booted_of`, run by the
v0.6.26 final's own advanced edition and by car-adv's `advcodex` probe on the same inputs, held equal.

The shape is S7.2c's (`advcodex.py`): a request `{"world": {...}, "cases": [[op, arg, ...], ...]}` answered
`{"results": [{"ok": value} | {"error": class[, "code": code]}]}` by both sides; the probe is the same `advcodex`
example, the reference this module's own script (`REFERENCE`), run by `advref.run` under the tag with every home a
scratch folder. Windows is never asked anything real: the wake timer, the power settings and the stop event are
scripted stand-ins on both sides that log every call (compared in order), the WMI escape is never run (only the
command lines it would build are compared), and the Desktop's pipe is a pipe of the test's own name.

Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from rustdiff import advcodex, advref

TAG = advcodex.TAG

REFERENCE = r'''
import json, os, sys, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

WORLD = dict(request.get("world") or {})


def norm(value):
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {str(key): norm(each) for key, each in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    return value


def number(value):
    return float(value) if isinstance(value, str) else value


class Script:
    """Answers per call kind, taken in order (the last repeated); "raise" raises."""
    def __init__(self, script):
        self.script = {key: list(value) for key, value in (script or {}).items()}
        self.calls = []

    def answer(self, kind, default):
        found = self.script.get(kind)
        if not found:
            return default
        value = found.pop(0) if len(found) > 1 else found[0]
        if value == "raise":
            raise RuntimeError("stand-in")
        return value


# ------------------------------------------------------------------------------------------------ win/
from codex_auto_resume_advanced.win import stopflag, waketimer  # noqa: E402


class TimerKernel(Script):
    def CreateWaitableTimerExW(self, security, name, flags, access):
        self.calls.append(["create", security, name, flags, access])
        return self.answer("create", 501)

    def SetWaitableTimer(self, handle, due, period, routine, argument, resume):
        self.calls.append(["set", handle, due._obj.value, period, routine, argument, bool(resume)])
        return self.answer("set", 1)

    def CancelWaitableTimer(self, handle):
        self.calls.append(["cancel", handle])
        return self.answer("cancel", 1)

    def CloseHandle(self, handle):
        self.calls.append(["close", handle])
        return self.answer("close", 1)

    def GetSystemPowerStatus(self, status):
        self.calls.append(["status"])
        found = self.answer("status", 1)
        if found == "fail":
            return 0
        status._obj.ACLineStatus = found
        return 1

    def LocalFree(self, pointer):
        self.calls.append(["free", bytes(pointer.contents).hex()])
        return self.answer("free", None)


class Power(Script):
    def __init__(self, script, log):
        super().__init__(script)
        self.calls = log

    def PowerGetActiveScheme(self, root, scheme):
        self.calls.append(["scheme"])
        code, guid = self.answer("scheme", [0, "00112233445566778899aabbccddeeff"])
        if guid is not None:
            scheme._obj.contents = waketimer.GUID.from_buffer_copy(bytes.fromhex(guid))
        return code

    def _read(self, which, root, scheme, subgroup, setting, value):
        self.calls.append(["read", which, bytes(scheme.contents).hex(), bytes(subgroup._obj).hex(),
                           bytes(setting._obj).hex()])
        code, found = self.answer(which, [0, 1])
        value._obj.value = found
        return code

    def PowerReadACValueIndex(self, *arguments):
        return self._read("ac", *arguments)

    def PowerReadDCValueIndex(self, *arguments):
        return self._read("dc", *arguments)


def timer(script, steps):
    kernel = TimerKernel(script)
    power = Power(script, kernel.calls)
    made = waketimer.WakeTimer(kernel=kernel, power=power)
    answers = []
    for step in steps:
        try:
            if step[0] == "set":
                answers.append(made.set(number(step[1])))
            elif step[0] == "cancel":
                answers.append(made.cancel())
            elif step[0] == "close":
                answers.append(made.close())
            elif step[0] == "allowed":
                answers.append(made.allowed())
            elif step[0] == "on_battery":
                answers.append(made.on_battery())
            elif step[0] == "due":
                answers.append(made.due)
        except Exception:
            answers.append({"raised": True})
    return {"answers": answers, "calls": kernel.calls}


class EventKernel(Script):
    def CreateEventW(self, security, manual, initial, name):
        self.calls.append(["create", security, bool(manual), bool(initial), name])
        return self.answer("create", 7)

    def OpenEventW(self, access, inherit, name):
        self.calls.append(["open", access, bool(inherit), name])
        return self.answer("open", 9)

    def WaitForSingleObject(self, handle, millis):
        self.calls.append(["wait", handle, millis])
        return self.answer("wait", 258)

    def CloseHandle(self, handle):
        self.calls.append(["close", handle])
        return self.answer("close", 1)


def stop(state_dir, script, steps):
    kernel = EventKernel(script)
    flag = stopflag.StopFlag(types.SimpleNamespace(state_dir=Path(state_dir)), kernel=kernel)
    answers = []
    for step in steps:
        if step[0] == "hold":
            answers.append(flag.hold())
        elif step[0] == "signalled":
            answers.append(flag.signalled())
        elif step[0] == "wait":
            answers.append(flag.wait(number(step[1])))
        elif step[0] == "release":
            answers.append(flag.release())
        elif step[0] == "name":
            answers.append(flag._name)
    return {"answers": answers, "calls": kernel.calls}


OPS = {
    "wn.timer": timer,
    "wn.stop": stop,
    "wn.filetime": lambda seconds: __import__("ctypes").c_longlong(waketimer.filetime(number(seconds))).value,
    "wn.event_name": lambda state_dir: stopflag.event_name(types.SimpleNamespace(state_dir=Path(state_dir))),
}

from codex_auto_resume_advanced.codex import turns as turns_  # noqa: E402
OPS["bt.booted_of"] = lambda state_dir: turns_.booted_of(types.SimpleNamespace(state_dir=Path(state_dir)))

# The later families add themselves below this line (EXTRA).
#EXTRA#

results = []
for case in request["cases"]:
    try:
        results.append({"ok": norm(OPS[case[0]](*case[1:]))})
    except OSError:
        results.append({"error": "OSError"})
    except Exception as error:
        results.append({"error": type(error).__name__})
sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False))
'''

EXTRA: list = []


def script() -> str:
    return REFERENCE.replace("#EXTRA#", "\n".join(EXTRA))


def ask_reference(request: dict, profile: Path) -> list:
    path = Path(tempfile.mkdtemp(prefix="advcodexd-req-")) / "request.json"
    try:
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        done = advref.run(script(), str(path), profile=profile, tag=TAG, timeout=1800)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    if done.returncode != 0:
        raise AssertionError("the reference failed: %s" % done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def snapshot(folders) -> dict:
    """S7.2c's snapshot, with a SQLite database that opens taken as its dump (schema and rows): two engines' pages
    may differ in bytes the store never reads (the change counter, free pages) and car-store's own diffs compare
    dumps too. A file that does not open as a database stays its bytes."""
    found = advcodex.snapshot(folders)
    for key in list(found):
        if not key.endswith((".sqlite", ".db")):
            continue
        root, relative = key.split("|", 1)
        for folder in folders:
            path = Path(folder) / relative
            if Path(folder).name != root or not path.is_file():
                continue
            try:
                connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
                try:
                    found[key] = {"dump": list(connection.iterdump())}
                finally:
                    connection.close()
            except sqlite3.Error:
                pass
    return found


class AdvCodexRestDiff(advcodex.AdvCodexDiff):
    """S7.2c's `AdvCodexDiff` with this module's reference script."""

    def same(self, label: str, cases: list, *, world: dict | None = None, profile: Path | None = None,
             chunk: int = 4000) -> list:
        profile = profile or self.fresh(label)
        want, got = [], []
        for start in range(0, len(cases), chunk):
            request = {"world": world or {}, "cases": cases[start:start + chunk]}
            want += ask_reference(request, profile)
            got += advcodex.ask_rust(request, profile)
        self.compare(label, cases, want, got)
        return want

    def scene(self, label: str, cases: list, setup, folders, *, world: dict | None = None, engines=(),
              profile: Path | None = None) -> tuple:
        """S7.2c's `scene` with this module's reference: the reference on the folders `setup()` made, then the probe
        on them made again; the answers, the files left and what each engine was asked, equal."""
        profile = profile or self.fresh(label)
        request = {"world": world or {}, "cases": cases}
        left = []
        for ask in (ask_reference, advcodex.ask_rust):
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)
            for engine in engines:
                engine.clear_log()
            setup()
            answers = ask(request, profile)
            left.append((answers, snapshot(folders), [advcodex.engine_log(engine.folder) for engine in engines]))
        (want, want_files, want_log), (got, got_files, got_log) = left
        self.compare(label, cases, want, got)
        self.assertEqual(sorted(want_files), sorted(got_files), "%s: the files left differ" % label)
        for name in want_files:
            self.assertEqual(want_files[name], got_files[name], "%s: %s differs" % (label, name))
        self.assertEqual(want_log, got_log, "%s: the engine was asked differently" % label)
        return want, want_files

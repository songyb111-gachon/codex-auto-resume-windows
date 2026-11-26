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

from codex_auto_resume_advanced.codex import inuse as inuse_, tokens as tokens_  # noqa: E402


def P(home):
    if home is None:
        return None
    return types.SimpleNamespace(home=home, settings_file=Path(home) / "config" / "settings.json")


def rollout_of(parts):
    return tokens_.Rollout(Path(parts[0]), Path(parts[1]), parts[2], parts[3], parts[4])


OPS.update({
    "tk.file_key": lambda path: tokens_.file_key(path),
    "tk.tell": lambda home, exe, where: inuse_.tell(P(home), exe, where),
    "tk.watched_homes": lambda home: tokens_.watched_homes(P(home)),
    "tk.rollouts": lambda homes, now, keep: [list(each) for each in tokens_.rollouts(homes, now, keep_days=keep)],
    "tk.unchanged": lambda rollout, known: tokens_.unchanged(rollout_of(rollout), known),
    "tk.read": lambda rollout, known, budget: list(tokens_.read(rollout_of(rollout), known, budget)),
})

# ------------------------------------------------------------------------------------------------ wmi_escape (never run)
import ctypes as _ctypes  # noqa: E402
import subprocess as _subprocess  # noqa: E402
from codex_auto_resume import pwsh as _pwsh, startup as _startup  # noqa: E402
from codex_auto_resume.win import kernel as _wkernel  # noqa: E402
from codex_auto_resume_advanced.codex import wmi_escape  # noqa: E402

_REAL_WINDLL = _ctypes.WinDLL


class WmiChain(Script):
    """Every effect of wmi_escape.probe, scripted and logged; nothing is started, opened or written."""

    def __init__(self, script):
        super().__init__(script)
        chain = self

        class RecPath(type(Path())):
            def write_text(self, text, encoding=None, errors=None, newline=None):
                chain.calls.append(["write", str(self), text])
                chain.answer("write", None)
                return len(text)

        self.RecPath = RecPath

        class Popen:
            def __init__(self, argv, creationflags=0, **unused):
                chain.calls.append(["spawn", [str(each) for each in argv], creationflags])
                self.pid = chain.answer("spawn", 4100)

            def wait(self, timeout=None):
                chain.calls.append(["wait_child", self.pid, float(timeout)])
                chain.answer("wait_child", None)

        self.Popen = Popen

    # kernel32 as _kernel() gives it
    def CreateJobObjectW(self, attributes, name):
        self.calls.append(["job"])
        return self.answer("job", 300)

    def SetInformationJobObject(self, job, klass, info, size):
        self.calls.append(["setinfo", job, klass, info._obj.basic.flags])
        return self.answer("setinfo", 1)

    def AssignProcessToJobObject(self, job, process):
        self.calls.append(["assign", job, process])
        return self.answer("assign", 1)

    def OpenProcess(self, access, inherit, pid):
        self.calls.append(["open", access, bool(inherit), int(pid)])
        return self.answer("open", 77)

    def TerminateProcess(self, handle, code):
        self.calls.append(["terminate", handle, code])
        return self.answer("terminate", 1)

    def WaitForSingleObject(self, handle, millis):
        self.calls.append(["wait", handle, millis])
        return self.answer("wait", 0x102)

    def CloseHandle(self, handle):
        self.calls.append(["close", handle])
        return self.answer("close", 1)

    def NtResumeProcess(self, handle):
        self.calls.append(["resume", handle.value])


def wmi_probe(script, src_paths):
    chain = WmiChain(script)

    def launcher():
        chain.calls.append(["launcher"])
        return chain.answer("launcher", "C:/Python/pythonw.exe")

    def mkdtemp(prefix=None):
        chain.calls.append(["mkdtemp", prefix])
        return chain.answer("workdir", "C:/Temp/car-mw-abc")

    def await_json(path, timeout):
        chain.calls.append(["await", str(path), float(timeout)])
        return chain.answer("heartbeat", None)

    held = (_startup.python_launcher, wmi_escape.tempfile, wmi_escape._src_paths, wmi_escape._kernel,
            wmi_escape.subprocess, wmi_escape._await_json, wmi_escape.time, wmi_escape._remove, wmi_escape.Path)
    _startup.python_launcher = launcher
    wmi_escape.tempfile = types.SimpleNamespace(mkdtemp=mkdtemp)
    wmi_escape._src_paths = lambda: src_paths
    wmi_escape._kernel = lambda: chain
    wmi_escape.subprocess = types.SimpleNamespace(Popen=chain.Popen, DEVNULL=_subprocess.DEVNULL)
    wmi_escape._await_json = await_json
    wmi_escape.time = types.SimpleNamespace(sleep=lambda seconds: chain.calls.append(["sleep", float(seconds)]))
    wmi_escape._remove = lambda directory: chain.calls.append(["remove", str(directory)])
    wmi_escape.Path = chain.RecPath
    _ctypes.WinDLL = lambda name, *a, **k: chain if name == "ntdll" else _REAL_WINDLL(name, *a, **k)
    try:
        try:
            facts = wmi_escape.probe()
        except Exception as error:
            return {"raised": type(error).__name__, "calls": chain.calls}
        return {"facts": facts, "calls": chain.calls}
    finally:
        (_startup.python_launcher, wmi_escape.tempfile, wmi_escape._src_paths, wmi_escape._kernel,
         wmi_escape.subprocess, wmi_escape._await_json, wmi_escape.time, wmi_escape._remove, wmi_escape.Path) = held
        _ctypes.WinDLL = _REAL_WINDLL


def wmi_helper(src_paths, workdir, launcher, bootstrap, fails):
    log = []

    def run(script, values, *, timeout):
        log.append(["pwsh", script, dict(values), float(timeout)])
        if fails:
            raise _pwsh.PowerShellError("stand-in")
        return 0

    held = (_pwsh.run, wmi_escape.time)
    _pwsh.run = run
    wmi_escape.time = types.SimpleNamespace(sleep=lambda seconds: log.append(["sleep", float(seconds)]))
    try:
        wmi_escape._helper_main(src_paths, workdir, launcher, bootstrap)
    finally:
        _pwsh.run, wmi_escape.time = held
    return log


def wmi_env(values):
    found = _pwsh.environment(values)
    return sorted([key, value] for key, value in found.items() if key.upper().startswith(_pwsh.PREFIX))


OPS.update({
    "wm.probe": wmi_probe,
    "wm.helper": wmi_helper,
    "wm.env": wmi_env,
    "wm.record": lambda pid, in_job, kill: json.dumps({"pid": pid, "in_job": in_job, "kill_on_close": kill}),
    "wm.constants": lambda: [wmi_escape._WMI_SCRIPT, wmi_escape._BOOTSTRAP, wmi_escape.CREATE_SUSPENDED,
                             _wkernel.NO_WINDOW, _wkernel.JOB_KILL_ON_CLOSE, wmi_escape._JOB_EXTENDED_LIMIT_INFORMATION,
                             wmi_escape._HEARTBEAT_SECONDS, wmi_escape._HELPER_SECONDS, wmi_escape._WMI_TIMEOUT,
                             wmi_escape._SETTLE_SECONDS, list(_startup.NO_REMOTE_DEBUG)],
})

# ------------------------------------------------------------------------------------------------ Session, submitted
from codex_auto_resume.codex import pairing as _pairing, transport as _transport  # noqa: E402
from codex_auto_resume.win import authenticode as _authenticode  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError as _AdapterError  # noqa: E402
from codex_auto_resume_advanced.codex import protocol as protocol_  # noqa: E402


def _fake_signer(path):
    for name, value in (WORLD.get("signers") or {}).items():
        if name.lower() == str(path).lower():
            if isinstance(value, str):
                return value
            raise RuntimeError("stand-in")
    raise _AdapterError("unsigned")


def _no_identity(pid):
    raise _AdapterError("process_exited")


_authenticode.signer = _fake_signer
_pairing.processes_named = lambda names, families: json.loads(json.dumps(WORLD.get("processes") or []))
_pairing.resource_users = lambda *paths: []
_pairing.process_identity = _no_identity
# v0.6.26 final (FINAL-DELTA #6): the case's package folders, never this PC's.
_pairing.package_roots = lambda family: (
    [each for each in WORLD.get("packages") if isinstance(each, str)] if isinstance(WORLD.get("packages"), list)
    else [])


def session_error(error):
    found = {"error": type(error).__name__}
    if isinstance(error, (_AdapterError, protocol_.SessionRefused)):
        found["text"] = str(error)
    if hasattr(error, "method"):
        found["method"], found["code"] = error.method, error.code
    return found


def session_run(exe, measurement, capability, config, steps):
    backend = _transport.Backend(Path(os.environ["CODEX_HOME"]), Path(exe))
    try:
        session = protocol_.Session(backend, measurement, capability=capability,
                                    config=[tuple(pair) for pair in config])
    except Exception as error:
        return {"new": session_error(error)}
    try:
        session.__enter__()
    except Exception as error:
        return {"enter": session_error(error)}
    out, pending = [], []
    for step in steps:
        try:
            if step[0] == "call":
                out.append({"ok": session.call(step[1], step[2])})
            elif step[0] == "submit":
                out.append({"ok": session.submit(step[1], step[2])})
            elif step[0] == "receive":
                out.append({"ok": session.receive(step[1], step[2], step[3], seconds=step[4])})
            elif step[0] == "submitted":
                pending.append(protocol_.submitted(session, step[1], step[2]))
                out.append({"ok": len(pending) - 1})
            elif step[0] == "answer":
                out.append({"ok": pending[step[1]]()})
            elif step[0] == "events":
                out.append({"ok": session.drain_events()})
            elif step[0] == "declined":
                out.append({"ok": session.declined_count()})
        except Exception as error:
            out.append(session_error(error))
    session.__exit__()
    return {"steps": out, "declined": dict(sorted(session.declined.items())),
            "refused": dict(sorted(session.refused.items()))}


OPS["ss.run"] = session_run

# ------------------------------------------------------------------------------------------------ headless
from codex_auto_resume_advanced.codex import headless as headless_  # noqa: E402


class Answers:
    """Per kind, answers taken in order (the last repeated)."""
    def __init__(self, script):
        self.script = {key: list(value) for key, value in (script or {}).items()}

    def take(self, kind, default):
        found = self.script.get(kind)
        if not found:
            return default
        return found.pop(0) if len(found) > 1 else found[0]


def raised(marker, method):
    kind = marker.get("raise")
    if kind == "SessionRefused":
        return protocol_.SessionRefused("method not permitted for this session")
    if kind == "RefusedByCodex":
        return protocol_._refused_by_codex(marker.get("method", method), marker.get("code"))
    if kind == "protocol_timeout":
        return _AdapterError("protocol_timeout")
    return RuntimeError("stand-in")


def headless_case(spec):
    log = []
    tick = {"t": float(spec.get("clock0", 100.0))}

    def clock():
        tick["t"] += float(spec.get("tick", 1.0))
        log.append(["clock"])
        return tick["t"]

    follower = headless_.Follower(clock=clock, poll=0)
    answers = Answers(spec.get("session"))
    events = list(spec.get("events") or [])

    class Fake:
        def __enter__(self):
            log.append(["enter"])
            if spec.get("enter") == "raise":
                raise RuntimeError("stand-in")
            return self

        def __exit__(self, *unused):
            log.append(["exit"])

        def call(self, method, params=None):
            log.append(["call", method, params])
            found = answers.take(method, {})
            if isinstance(found, dict) and "raise" in found:
                raise raised(found, method)
            return found

        def drain_events(self):
            log.append(["drain"])
            entry = events.pop(0) if events else []
            if isinstance(entry, dict) and "stop" in entry:
                log.append(["stopped", follower.stop(*entry["stop"])])
                return []
            return entry

    def opener(capability):
        log.append(["open", capability])
        if spec.get("open") == "raise":
            raise RuntimeError("stand-in")
        return Fake()

    looks = Answers({"app": spec.get("app") or [False], "owe": spec.get("owe") or [True],
                     "still": spec.get("still") or [True], "guard": spec.get("guard") or [True],
                     "guard_exit": spec.get("guard_exit") or ["ok"]})

    def look(kind, *arguments):
        log.append([kind, *arguments])
        found = looks.take(kind, True)
        if found == "raise":
            raise RuntimeError("stand-in")
        return found

    class Guard:
        def __enter__(self):
            return look("guard")

        def __exit__(self, *unused):
            if look("guard_exit") == "raise":
                raise RuntimeError("stand-in")
            return False

    run = headless_.HeadlessRun(spec.get("capability", "headless_run"), key=spec.get("key", "k1"), session=opener,
                                follower=follower, seconds=float(spec.get("seconds", 8)), mode=spec.get("mode", "turn"),
                                app_running=(lambda: look("app")) if spec.get("app") else None,
                                owe=(lambda thread, model, seconds: look("owe", thread, model, seconds))
                                if spec.get("owe") else None)
    out = []
    for step in spec["resumes"]:
        answer = run.resume(step.get("thread"), launch_guard=Guard() if step.get("guard") else None,
                            still_unloaded=(lambda: look("still")) if step.get("still") else None,
                            words=step.get("words"), client_id=step.get("client_id"))
        deadline = time.monotonic() + 20
        while follower.live() is not None and time.monotonic() < deadline:
            time.sleep(0.002)
        out.append({"answer": answer, "refused": None if run.refused is None else str(run.refused),
                    "on_default": run.on_default, "model": run.model, "live": follower.live() is not None,
                    "ends": [dict(end) for end in follower.drain(run.capability)],
                    "others": [dict(end) for end in follower.drain("other")],
                    "empty_refused": headless_.EMPTY_REFUSED})
    return {"steps": out, "log": log}


import time  # noqa: E402
OPS["hl.case"] = headless_case
OPS["hl.pure"] = lambda kind, value: {
    "settings_allowed": lambda: headless_.settings_allowed(value),
    "model": lambda: headless_._model(value),
    "default_model": lambda: headless_._default_model(value),
    "turn_id": lambda: headless_._turn_id(value),
    "completed": lambda: headless_._completed(value[0], value[1], value[2]),
}[kind]()

# ------------------------------------------------------------------------------------------------ ipc (a test's own pipe)
from codex_auto_resume_advanced.codex import ipc as ipc_  # noqa: E402


class _Id:
    def __init__(self, number):
        self.number = number

    def __str__(self):
        return "00000000-0000-4000-8000-%012x" % self.number


def ipc_run(kind, name, thread, extra, message, gate_spec):
    if not isinstance(name, str) or "codex-ipc" in name.lower():
        raise AssertionError("never the Desktop's own pipe")
    ipc_.PIPE = name
    counter = {"n": 0}

    def uuid4():
        counter["n"] += 1
        return _Id(counter["n"])

    ipc_.uuid = types.SimpleNamespace(uuid4=uuid4)
    log = []
    gate = None
    if gate_spec is not None:
        answers = Answers({"enter": gate_spec.get("enter") or [True], "exit": gate_spec.get("exit") or ["ok"]})

        class Guard:
            def __enter__(self):
                log.append("enter")
                found = answers.take("enter", True)
                if found == "raise":
                    raise RuntimeError("stand-in")
                return found

            def __exit__(self, *unused):
                log.append("exit")
                if answers.take("exit", "ok") == "raise":
                    raise RuntimeError("stand-in")
                return False

        gate = Guard
    if kind == "stop":
        word = ipc_.stop_turn(thread, extra, gate=gate)
    elif kind == "start":
        word = ipc_.start_turn(thread, extra, gate=gate)
    else:
        word = ipc_.steer_turn(thread, extra, message=message, gate=gate)
    return {"word": str(word), "gate": log}


OPS["ip.run"] = ipc_run
OPS["ip.filled"] = lambda method, expecting, fields: ipc_._filled(
    (ipc_.INTERRUPT_EXPECTING if expecting else ipc_.REQUESTS[method])[1], fields)
OPS["ip.version"] = lambda method, expecting: (ipc_.INTERRUPT_EXPECTING if expecting else ipc_.REQUESTS[method])[0]

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

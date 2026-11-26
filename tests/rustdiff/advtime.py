"""What the S7.2e2 diffs share (time, fleet and the weekly look: `engine/{supervise,powertasks,wake,analytics,
updatecheck,fleet,anchor}.py`): one request of cases, answered by the v0.6.26 final's own advanced edition (this module's
`REFERENCE`, run by `advref.run` under the tag, every home a scratch folder) and by car-adv's example `advtime`, held
equal case by case - every answer, every call the code made of its stand-ins (in order), every row of the home's
advanced.sqlite and every file a case names, byte for byte.

Each side runs on the same folders: the harness seeds a case's home, runs the reference, keeps what it left, seeds the
home again from nothing and runs the Rust side (`Scene`). Nothing real is asked of Windows or of a network: the stop
flag, the wake timer, the update check's PowerShell, Codex's usage sessions and the request's process are scripted
stand-ins on both sides that log every call (a request "process" is a child the test starts itself: a Python one-liner
that prints what the case says), the shared folder is a scratch folder, and no Codex is looked for.

Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

from rustdiff import advref, diffs

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NOW = 1_800_000_000.0
THREAD = "0a1b2c3d-0001-7000-8000-00000000000%d"
TURN = "0a1b2c3d-0002-7000-8000-00000000000%d"

REFERENCE = r'''
import contextlib, json, os, sys, threading
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

import secrets
counter = [0]
def token_hex(count=32):
    counter[0] += 1
    return ("%x" % counter[0]).rjust(count * 2, "0")[-count * 2:]
secrets.token_hex = token_hex

from codex_auto_resume import config
from codex_auto_resume.domain.plug import DEFER, Alternative
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced.state import AdvancedState


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


CLASSES = {"ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError, "RuntimeError": RuntimeError,
           "OSError": OSError, "LookupError": LookupError}


class Script:
    """Answers per call kind, taken in order (the last repeated); {"raise": class} raises; every call logged."""
    def __init__(self, script, log):
        self.script = {key: list(value) for key, value in (script or {}).items()}
        self.log = log

    def answer(self, kind, default, *logged):
        self.log.append([kind, *[norm(each) for each in logged]])
        found = self.script.get(kind)
        if not found:
            return default
        value = found.pop(0) if len(found) > 1 else found[0]
        if isinstance(value, dict) and "raise" in value:
            raise CLASSES.get(value["raise"], RuntimeError)("stand-in")
        return value


def said(value):
    if value is DEFER:
        return "DEFER"
    if isinstance(value, Alternative):
        return {"word": str(value)}
    if hasattr(value, "run"):
        return {"object": "errand"}
    return {"value": norm(value)}


class View:
    """Core's view as a capability's tick is handed it: `settings()` and `records_in(states)`, scripted and logged."""
    def __init__(self, script, log):
        self.script = Script(script, log)

    def settings(self):
        return self.script.answer("settings", {"enabled": True})

    def records_in(self, states):
        return self.script.answer("records_in", [])


@contextlib.contextmanager
def guard_of(log, permitted=True):
    log.append(["guard", permitted])
    yield permitted


def run_errand(errand, log):
    """An errand a tick answered, run with a guard that is always permitted; "none" where there was none, and a raise
    as the one word core's errand runner sees (it logs `plug_errand_failed` whatever the class)."""
    if errand is None or errand is DEFER or not hasattr(errand, "run"):
        return "none"
    try:
        return norm(errand.run(lambda: guard_of(log)))
    except Exception:
        return {"error": "raised"}


def homed(value, home):
    """`value` with every text's "{home}" made the case's home."""
    if isinstance(value, str):
        return value.replace("{home}", home)
    if isinstance(value, list):
        return [homed(each, home) for each in value]
    if isinstance(value, dict):
        return {key: homed(each, home) for key, each in value.items()}
    return value


class Case:
    """One case's home, clock, state and Scoped (`state.scoped(capability, on=..., verdict=..., armed=...)`)."""
    def __init__(self, case):
        self.case = case
        self.paths = config.Paths(Path(case["home"]))
        self.clock = [case.get("now", 1800000000.0)]
        self.on = [case.get("on", True)]
        self.armed = set(case.get("armed", ()))
        self.verdicts = dict(case.get("verdicts", {}))
        self.state = AdvancedState(self.paths, registry=REGISTRY, clock=lambda: self.clock[0])
        for method, arguments, keywords in homed(case.get("setup", ()), case["home"]):
            getattr(self.state, method)(*arguments, **keywords)
        self.scoped = self.state.scoped(case["capability"], on=lambda: self.on[0],
                                        verdict=lambda measurement: self.verdicts.get(str(measurement)),
                                        armed=lambda other: other in self.armed)
        self.log = []

    def common(self, step):
        """A step every capability's scenario takes; whether it was one."""
        if step[0] == "clock":
            self.clock[0] = step[1]
        elif step[0] == "on":
            self.on[0] = step[1]
        elif step[0] == "armed":
            self.armed = set(step[1])
        elif step[0] == "call":
            getattr(self.state, step[1])(*step[2], **step[3])
        else:
            return False
        return True

    def close(self):
        self.state.close()


OPS = {}


def op(name):
    def register(function):
        OPS[name] = function
        return function
    return register
'''

REF_SUPERVISE = r'''
from codex_auto_resume_advanced.engine import supervise


class Flag(Script):
    def hold(self):
        return self.answer("hold", True)

    def signalled(self):
        return self.answer("signalled", False)

    def wait(self, seconds):
        return self.answer("wait", False, seconds)


@op("sv")
def sv(case):
    made = Case(case)
    flag = Flag(case.get("flag"), made.log)
    notices = Script({"notify": case.get("notify", [False])}, made.log)
    code = supervise.CrashRestart(made.paths, stop=flag, notify=lambda paths: notices.answer("notify", False))
    if case.get("bind", True):
        code.bind(made.scoped)
    answers = []
    for step in case["steps"]:
        if made.common(step):
            answers.append(None)
            continue
        try:
            answers.append(said(code.supervise(step[1])))
        except Exception as error:
            answers.append({"error": type(error).__name__})
    made.close()
    return {"answers": answers, "log": made.log}


@op("sv.view")
def sv_view(case):
    class Runtime:
        paths = config.Paths(Path(case["home"]))
        def states(self):
            return {supervise.CAPABILITY: case["state"]} if case.get("state") else {}
    from codex_auto_resume.control import codexstart
    asked = []
    def there(pid):
        asked.append(pid)
        return pid in case.get("running", ())
    codexstart._process_there = there
    return {"view": norm(supervise.view(Runtime())), "asked": asked}
'''

REF_POWER = r'''
from codex_auto_resume_advanced.engine import powertasks


@op("pt.valid")
def pt_valid(case):
    return powertasks.valid(case["document"])


@op("pt.read")
def pt_read(case):
    return norm(powertasks.read(config.Paths(Path(case["home"]))))


@op("pt.write")
def pt_write(case):
    paths = config.Paths(Path(case["home"]))
    done = powertasks.write(paths, case["document"])
    if case.get("remove"):
        powertasks.remove(paths)
    return done


def history(case, log):
    script = case.get("turns") or {}

    class Turns:
        def status(self, thread, turn):
            log.append(["status", thread, turn])
            found = script.get("status", {}).get("%s|%s" % (thread, turn))
            if isinstance(found, dict) and "raise" in found:
                raise CLASSES.get(found["raise"], RuntimeError)("stand-in")
            return found

    if "latest" in script:
        def latest(thread):
            log.append(["latest", thread])
            found = script["latest"].get(thread)
            if isinstance(found, dict) and "raise" in found:
                raise CLASSES.get(found["raise"], RuntimeError)("stand-in")
            if found is None:
                return None
            from types import SimpleNamespace
            return SimpleNamespace(turn_id=found)
        Turns.latest = lambda self, thread: latest(thread)
    return Turns()


@op("pt.end_of")
def pt_end_of(case):
    log = []
    turns = history(case, log)
    end = powertasks.end_of(case["task"], case["records"], turns.status, getattr(turns, "latest", None))
    return {"end": end, "log": log}


@op("pt.judge")
def pt_judge(case):
    return powertasks.judge(case["ends"], case.get("failed", False), case.get("interrupted", False))


@op("pt.power")
def pt_power(case):
    log = []
    def records():
        log.append(["records"])
        if case.get("records") == "raise":
            raise RuntimeError("stand-in")
        return case.get("records") or []
    code = powertasks.PowerAfterTasks(config.Paths(Path(case["home"])), records=records,
                                      turns=history(case, log))
    try:
        answer = norm(code.power(case.get("facts")))
    except Exception as error:
        answer = {"error": type(error).__name__}
    return {"answer": answer, "log": log}
'''

REF_WAKE = r'''
from codex_auto_resume_advanced.engine import wake


class Timer(Script):
    due = None

    def set(self, at):
        done = self.answer("set", True, at)
        if done:
            self.due = at
        return done

    def cancel(self):
        done = self.answer("cancel", self.due is not None)
        self.due = None
        return done

    def allowed(self):
        return self.answer("allowed", True)


@op("wk")
def wk(case):
    made = Case(case)
    timer = Timer(case.get("timer"), made.log)
    starts = Script({"start": case.get("start", [None])}, made.log)
    code = wake.WakeForReset(made.paths, timer=timer, start=lambda target: starts.answer("start", None))
    if case.get("bind", True):
        code.bind(made.scoped)
    view = View(case.get("view"), made.log)
    answers, errand = [], None
    for step in case["steps"]:
        if made.common(step):
            answers.append(None)
            continue
        try:
            if step[0] == "tick":
                errand = code.tick(view)
                answers.append(said(errand))
            elif step[0] == "run":
                answers.append(run_errand(errand, made.log))
            elif step[0] == "look":
                answers.append(code.look())
            elif step[0] == "earliest":
                answers.append(code.earliest(view))
            elif step[0] == "apply":
                answers.append(code.apply(step[1]))
            elif step[0] == "lead":
                answers.append(code.lead())
            elif step[0] == "due":
                answers.append(timer.due)
            else:
                raise SystemExit("unknown step %s" % step[0])
        except Exception as error:
            answers.append({"error": type(error).__name__})
    made.close()
    return {"answers": answers, "log": made.log}
'''

REF_ANALYTICS = r'''
from codex_auto_resume_advanced.engine import analytics


@op("ua")
def ua(case):
    made = Case(case)
    home = Path(case["home"])
    homes = [str(home / each) for each in case.get("homes", ())]
    ticks = list(case.get("clock") or [0.0])

    def clock():
        made.log.append(["clock"])
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]
    keys = case.get("keys") or {}

    class Source:
        def project_key(self, thread):
            made.log.append(["project_key", thread])
            found = keys.get(thread)
            if isinstance(found, dict) and "raise" in found:
                raise RuntimeError("stand-in")
            return found

    def source(where):
        made.log.append(["source", Path(where).name])
        if case.get("source_raise"):
            raise RuntimeError("stand-in")
        return Source()
    code = analytics.UsageAnalytics(made.paths, homes=lambda: homes, source=source, clock=clock)
    if case.get("bind", True):
        code.bind(made.scoped)
    answers, errand = [], None
    for step in case["steps"]:
        if made.common(step):
            answers.append(None)
            continue
        try:
            if step[0] == "tick":
                errand = code.tick(View({}, made.log))
                answers.append(said(errand))
            elif step[0] == "run":
                answers.append(run_errand(errand, made.log))
            else:
                raise SystemExit("unknown step %s" % step[0])
        except Exception as error:
            answers.append({"error": type(error).__name__})
    made.close()
    return {"answers": answers, "log": made.log}


@op("ua.pace")
def ua_pace(case):
    return norm(analytics.pace(case["samples"], case["row"], case["now"]))


@op("ua.route")
def ua_route(case):
    return analytics.route(case["verdict"])
'''

REF_UPDATE = r'''
from codex_auto_resume_advanced.engine import updatecheck


@op("uc")
def uc(case):
    made = Case(case)
    script = Script(case.get("script"), made.log)
    home = str(made.paths.home)

    def run(where, given):
        made.log.append(["run", Path(where).name, str(given) == home])
        found = script.answer("answer", None)
        return None if found is None else tuple(found)

    def start(target):
        script.answer("start", None)
        if case.get("start_runs", True):
            target()
    code = updatecheck.IdleUpdateCheck(made.paths, run=run, managed=lambda: script.answer("managed", False),
                                       start=start, installed=lambda: script.answer("installed", None),
                                       log=lambda line: made.log.append(["log", line]))
    if case.get("bind", True):
        code.bind(made.scoped)
    view = View(case.get("view"), made.log)
    answers, errand = [], None
    for step in case["steps"]:
        if made.common(step):
            answers.append(None)
            continue
        try:
            if step[0] == "tick":
                errand = code.tick(view)
                answers.append(said(errand))
            elif step[0] == "run":
                answers.append(run_errand(errand, made.log))
            elif step[0] == "offered":
                answers.append(norm(code.offered()))
            elif step[0] == "script":
                Path(made.paths.home, "app", "scripts").mkdir(parents=True, exist_ok=True)
                Path(made.paths.home, "app", "scripts", "bootstrap.ps1").write_text("# stand-in", encoding="utf-8")
                answers.append(None)
            else:
                raise SystemExit("unknown step %s" % step[0])
        except Exception as error:
            answers.append({"error": type(error).__name__})
    made.close()
    return {"answers": answers, "log": made.log}


@op("uc.pure")
def uc_pure(case):
    name, arguments = case["name"], case["arguments"]
    if name == "said":
        answered = arguments[0]
        return updatecheck.said(None if answered is None else tuple(answered), arguments[1])
    return norm(getattr(updatecheck, name)(*arguments))
'''

REF_FLEET = r'''
from codex_auto_resume_advanced.engine import fleet


def raised(error):
    if isinstance(error, FileNotFoundError):
        return {"error": "FileNotFoundError"}
    if isinstance(error, OSError):
        return {"error": "OSError"}
    return {"error": type(error).__name__}


@op("fl")
def fl(case):
    made = Case(case)
    ticks = list(case.get("clock") or [0.0])

    def clock():
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]
    alive = list(case.get("alive") or [False])

    class Worker:
        def is_alive(self):
            made.log.append(["alive"])
            return alive.pop(0) if len(alive) > 1 else alive[0]

    def spawn(run):
        made.log.append(["spawn"])
        if case.get("spawn_raise"):
            raise RuntimeError("stand-in")
        if case.get("run_pass", True):
            run()
        return Worker()

    def status(now):
        made.log.append(["status", now])
        if case.get("status") is None:
            raise RuntimeError("stand-in")
        found = dict(case["status"])
        if found.get("written_at") == "now":
            found["written_at"] = now
        return found
    code = fleet.FleetView(made.paths, status=status, spawn=spawn, clock=clock)
    if case.get("bind", True):
        code.bind(made.scoped)
    answers, errand = [], None
    for step in case["steps"]:
        if made.common(step):
            answers.append(None)
            continue
        try:
            if step[0] == "tick":
                errand = code.tick(View({}, made.log))
                answers.append(said(errand))
            elif step[0] == "run":
                answers.append(run_errand(errand, made.log))
            elif step[0] == "seen":
                answers.append(norm(fleet.read_seen(made.paths)))
            else:
                raise SystemExit("unknown step %s" % step[0])
        except Exception as error:
            answers.append({"error": type(error).__name__})
    made.close()
    return {"answers": answers, "log": made.log}


@op("fl.pure")
def fl_pure(case):
    name, arguments = case["name"], homed(case["arguments"], case["home"])
    paths = config.Paths(Path(case["home"]))
    try:
        if name == "folder_problem":
            return fleet.folder_problem(arguments[0], paths)
        if name == "within":
            return fleet._within(*arguments)
        if name == "write":
            return fleet.write(*arguments)
        if name == "read_peers":
            steps = []
            found = fleet.read_peers(arguments[0], arguments[1], lambda: steps.append(1))
            return {"found": norm(found), "steps": len(steps)}
        if name == "remove_old_name":
            return fleet.remove_old_name(*arguments)
        if name == "seen":
            fleet.write_seen(paths, *arguments)
            return norm(fleet.read_seen(paths))
        if name == "read_seen":
            return norm(fleet.read_seen(paths))
        return norm(getattr(fleet, name)(*arguments))
    except Exception as error:
        return raised(error)
'''

REF_ANCHOR = r'''
import time as _time
from codex_auto_resume_advanced.engine import anchor


@op("an.pure")
def an_pure(case):
    name, arguments = case["name"], case["arguments"]
    if name in ("midnight", "occurrence", "slot_due", "next_due", "hhmm"):
        function = {"hhmm": anchor._hhmm}.get(name) or getattr(anchor, name)
        return norm(function(*arguments))
    if name in ("tokens_of", "thread_started", "refused"):
        value = arguments[0]
        if isinstance(value, dict):
            value = bytes.fromhex(value["hex"])
        return norm(getattr(anchor, name)(value))
    if name == "toml_key":
        return anchor._toml_key(*arguments)
    return norm(getattr(anchor, name)(*arguments))
'''

REF_END = r'''
results = []
for case in request["cases"]:
    try:
        results.append({"ok": OPS[case["op"]](case)})
    except Exception as error:
        results.append({"error": type(error).__name__})
sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False, allow_nan=False))
'''

PARTS = [REFERENCE, REF_SUPERVISE, REF_POWER, REF_WAKE, REF_ANALYTICS, REF_UPDATE, REF_FLEET, REF_ANCHOR]


def add_reference(part: str) -> None:
    """A later module's ops (each diffs_advtime_* file adds its own before it runs)."""
    if part not in PARTS:
        PARTS.append(part)


# ------------------------------------------------------------------------------------------------ the Rust side
_BUILT = []


def probe_path() -> Path:
    named = os.environ.get("CODEX_AR_ADV_TIME_EXE")
    return Path(named) if named else advref.target_dir() / "release" / "examples" / "advtime.exe"


def build() -> None:
    """`cargo build --release --locked --example advtime` once a process: cargo does nothing where it is current."""
    if _BUILT or os.environ.get("CODEX_AR_ADV_TIME_EXE"):
        return
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advtime",
                    "--manifest-path", str(advref.ADVANCED / "Cargo.toml")],
                   env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)
    _BUILT.append(True)


def run_rust(cases: list, scratch: Path) -> list:
    build()
    request = scratch / "advtime-rust.json"
    request.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([str(probe_path()), str(request)], capture_output=True, creationflags=NO_WINDOW,
                          timeout=1800, env=advref.environment(scratch), cwd=str(scratch))
    if done.returncode != 0:
        raise AssertionError("advtime failed (%d): %s" % (done.returncode, done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def run_reference(cases: list, scratch: Path) -> list:
    request = scratch / "advtime-reference.json"
    request.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    done = advref.run("".join(PARTS) + REF_END, str(request), profile=scratch, timeout=1800)
    if done.returncode != 0:
        raise AssertionError("reference failed: %s" % done.stderr[-4000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def dump(home: Path) -> dict:
    """Every row of the home's advanced.sqlite, table by table, in rowid order."""
    path = home / "config" / "advanced" / "advanced.sqlite"
    if not path.is_file():
        return {}
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: [[each.hex() if isinstance(each, bytes) else each for each in row]
                        for row in connection.execute("SELECT * FROM %s ORDER BY rowid" % table)]
                for table in tables}
    finally:
        connection.close()


def left(home: Path, names) -> dict:
    """The files a case names (relative to its home), as bytes in hex; None for one not there."""
    found = {}
    for name in names:
        path = home / name
        found[name] = path.read_bytes().hex() if path.is_file() else ("<dir>" if path.is_dir() else None)
    return found


def seed(home: Path, files: dict) -> None:
    """A case's home from nothing: its files (relative path -> text, or {"hex": bytes, "mtime_ns": n}, or
    {"dir": True}); a file's modification time is the one it names, so both sides see the same."""
    if home.exists():
        shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True)
    for name, content in (files or {}).items():
        path = home / name
        if isinstance(content, dict) and content.get("dir"):
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            path.write_bytes(bytes.fromhex(content["hex"]))
            if "mtime_ns" in content:
                os.utime(path, ns=(content["mtime_ns"], content["mtime_ns"]))
        else:
            path.write_bytes(content.encode("utf-8"))


def first_difference(want, got, path="") -> str:
    """Where two answers first differ, and what each holds there."""
    if isinstance(want, dict) and isinstance(got, dict):
        for key in list(want) + [key for key in got if key not in want]:
            if diffs.encode(want.get(key)) != diffs.encode(got.get(key)):
                return first_difference(want.get(key), got.get(key), "%s.%s" % (path, key))
    if isinstance(want, list) and isinstance(got, list):
        for index, (one, other) in enumerate(zip(want, got)):
            if diffs.encode(one) != diffs.encode(other):
                return first_difference(one, other, "%s[%d]" % (path, index))
        if len(want) != len(got):
            return "%s: lengths %d and %d" % (path, len(want), len(got))
    return "%s: reference %s, rust %s" % (path, json.dumps(want, ensure_ascii=False)[:400],
                                          json.dumps(got, ensure_ascii=False)[:400])


class Scene:
    """Run `cases` on both sides over the same folders; the per-case results with what each left, side by side."""

    def __init__(self, test, label: str):
        self.test, self.label = test, label

    def run(self, cases: list, chunk: int = 200, tz: str | None = None) -> list:
        root = Path(tempfile.mkdtemp(prefix="advtime-"))
        before = os.environ.get("TZ")
        if tz is not None:
            os.environ["TZ"] = tz
        try:
            for index, case in enumerate(cases):
                case.setdefault("home", str(root / ("case%04d" % index)))
            sides = []
            for runner in (run_reference, run_rust):
                results = []
                for start in range(0, len(cases), chunk):
                    part = cases[start:start + chunk]
                    for case in part:
                        seed(Path(case["home"]), case.get("files"))
                    answered = runner(part, root)
                    for case, result in zip(part, answered):
                        home = Path(case["home"])
                        result = {"result": result, "dump": dump(home) if case.get("dump", True) else None,
                                  "left": left(home, case.get("left", ()))}
                        results.append(result)
                sides.append(results)
            expected, actual = sides
            self.test.assertEqual(len(expected), len(actual))
            for index, (want, got) in enumerate(zip(expected, actual)):
                if diffs.encode(want) != diffs.encode(got):
                    self.test.fail("%s: case %d differs at %s\n  case      %s\n  reference %s\n  rust      %s" % (
                        self.label, index, first_difference(want, got),
                        json.dumps(cases[index], ensure_ascii=False)[:2500],
                        json.dumps(want, ensure_ascii=False)[:1500], json.dumps(got, ensure_ascii=False)[:1500]))
            return expected
        finally:
            if tz is not None:
                if before is None:
                    os.environ.pop("TZ", None)
                else:
                    os.environ["TZ"] = before
            shutil.rmtree(root, ignore_errors=True)

"""What the S7.4 diffs (diffs_advmeasure*.py) share: the measurement harness (`measure.py`, `evidence.py`) run by the
v0.6.26 final's own advanced edition and by car-adv's `advmeasure` probe on the same cases, held equal.

A request is `{"cases": [case, ...]}`; both sides answer `{"results": [{"answer": {"ok": value} | {"raised": class},
"log": [...]}]}`. The log is every call the fakes saw, in order: the session factory's opens, the session's enter,
calls (method and params), drains, declined counts and exit, the clock's readings and sleeps, the random ids, the
named hands, the CLI, the IPC look and the launcher. Nothing real is asked: the session is a script (replies per
method taken in order, the last repeated, `{"$raise": {...}}` raising; a drain takes the next batch of events), and
it refuses a method its measurement did not declare as the tests' FakeSession does; the clock is pinned and moves only
by the probe's own sleeps; `uuid.uuid4` is a counter. Each side writes its records to its own scratch folder; the
diff compares the answers with the folder's name taken out, and every file left, byte for byte.

Never a real Codex, a real turn or a real Codex home (the owner's Q2 (a)).
Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from rustdiff import advref

TAG = os.environ.get("CODEX_AR_REFERENCE") or "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXAMPLE = "advmeasure"

REFERENCE = r'''
import json, sys, time, types
from pathlib import Path
from codex_auto_resume.codex.errors import AdapterError
from codex_auto_resume_advanced import evidence, measure
from codex_auto_resume_advanced.codex import protocol
from codex_auto_resume_advanced.vocabulary import Measurement, NoteCode, Verdict

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

# Never the real engine (the main session's notice of 2026-11-27): no discovery, no process look, no live seam.
import os, tempfile
os.environ["CODEX_AUTO_RESUME_CODEX_EXE"] = os.path.join(tempfile.gettempdir(), "car-v0627-s74-no-such-engine",
                                                         "codex.exe")


def _refused(*unused, **also):
    raise RuntimeError("refused in the S7.4 diff: no real engine, process or install is asked")


from codex_auto_resume.codex import pairing
from codex_auto_resume_advanced.codex import inuse
pairing.processes_named = pairing.resource_users = pairing.process_identity = _refused
inuse.backend = _refused
for _name in ("live_backend", "live_session_factory", "live_launcher", "live_cli", "live_ipc", "live_hands"):
    setattr(measure, _name, _refused)
try:
    from codex_auto_resume.win import inventory
    inventory.resource_users = _refused
except ImportError:
    pass
try:
    from codex_auto_resume import windows as _windows
    _windows.resource_users = _refused
except ImportError:
    pass
TIMING = {"m2b_queue": "_M2B_QUEUE_SECONDS", "m2b_poll": "_M2B_POLL_SECONDS", "m6_turn": "_M6_TURN_SECONDS",
          "m6_interrupt": "_M6_INTERRUPT_SECONDS", "m6_poll": "_M6_POLL_SECONDS", "mu_spacing": "_MU_SPACING",
          "m4_turn": "_M4_TURN_SECONDS", "m4_note": "_M4_NOTE_SECONDS", "mc1_queue": "_MC1_QUEUE_SECONDS",
          "mc1_start": "_MC1_START_SECONDS", "mc2": "_MC2_SECONDS", "mc2_poll": "_MC2_POLL_SECONDS",
          "mqp_add": "_MQP_ADD_SECONDS", "mqg_settle": "_MQG_SETTLE_SECONDS", "mqo_open": "_MQO_OPEN_SECONDS",
          "mqo_find": "_MQO_FIND_SECONDS", "mopen": "_MOPEN_SECONDS", "mopen_poll": "_MOPEN_POLL_SECONDS",
          "mal": "_MAL_SECONDS", "mal_poll": "_MAL_POLL_SECONDS", "msteer_look": "_MSTEER_LOOK_SECONDS",
          "msteer_poll": "_MSTEER_POLL_SECONDS", "manchor_gap": "_MANCHOR_GAP"}
HELD = {name: getattr(measure, name) for name in TIMING.values()}


class RefusedByCodex(AdapterError):
    pass


def answer(spec):
    if isinstance(spec, dict) and "$raise" in spec:
        raise_ = spec["$raise"]
        cls = raise_.get("class", "ValueError")
        if cls == "SessionRefused":
            raise protocol.SessionRefused("stand-in")
        if cls == "EvidenceUnavailable":
            raise measure.EvidenceUnavailable("stand-in")
        if cls in ("AdapterError", "RefusedByCodex"):
            made = (RefusedByCodex if cls == "RefusedByCodex" else AdapterError)("stand-in")
            made.code = raise_.get("code")
            if raise_.get("method") is not None:
                made.method = raise_["method"]
            raise made
        raise {"ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
               "OSError": OSError, "RuntimeError": RuntimeError}.get(cls, RuntimeError)("stand-in")
    return spec


class Queue:
    def __init__(self, value):
        self.items = value if isinstance(value, list) else ([] if value is None else [value])
        self.at = 0

    def next(self, default):
        if not self.items:
            return default
        found = self.items[min(self.at, len(self.items) - 1)]
        self.at += 1
        return answer(found)


class FakeSession:
    def __init__(self, measurement, script, log, shared=None):
        self.allowed = protocol.methods_for(measurement)
        self.replies = shared if shared is not None else {
            method: Queue(value) for method, value in (script.get("replies") or {}).items()}
        self.events = list(script.get("events") or [])
        self.declined = script.get("declined", 0)
        self.enter_raises = script.get("enter_raises")
        self.log = log

    def __enter__(self):
        self.log.append(["enter"])
        if self.enter_raises is not None:
            answer(self.enter_raises)
        return self

    def __exit__(self, *unused):
        self.log.append(["exit"])
        return False

    def call(self, method, params=None):
        self.log.append(["call", method, params])
        if method not in self.allowed:
            raise protocol.SessionRefused("not permitted for this measurement")
        queue = self.replies.get(method)
        return queue.next({}) if queue is not None else {}

    def drain_events(self):
        self.log.append(["drain"])
        if not self.events:
            return []
        batch = self.events.pop(0)
        return list(batch) if isinstance(batch, list) else [batch]

    def declined_count(self):
        self.log.append(["declined"])
        return self.declined


def factory_of(script, log):
    # "shared": one set of answers for every session the case opens (MAL's reads, MF's resumes), else each its own.
    shared = ({method: Queue(value) for method, value in (script.get("replies") or {}).items()}
              if script.get("shared") is True else None)

    def opened(measurement, home, config):
        log.append(["open", str(measurement), None if home is None else str(home),
                    None if config is None else list(config)])
        if script.get("open_raises") is not None:
            answer(script["open_raises"])
        if home is not None and script.get("writes_config") is True:
            (Path(home) / "config.toml").write_bytes(b"x")
        return FakeSession(measurement, script, log, shared)
    takes_home, takes_config = script.get("takes_home") is True, script.get("takes_config") is True
    if takes_home and takes_config:
        return lambda measurement, home=None, config=None: opened(measurement, home, config)
    if takes_home:
        return lambda measurement, home=None: opened(measurement, home, None)
    if takes_config:
        return lambda measurement, config=None: opened(measurement, None, config)
    return lambda measurement: opened(measurement, None, None)


class Clock:
    def __init__(self, spec, log):
        spec = spec or {}
        self.now = float(spec.get("time", 1790000000.0))
        self.mono = float(spec.get("monotonic", 1000.0))
        self.ids = 0
        self.log = log

    def time(self):
        self.log.append(["time"])
        return self.now

    def monotonic(self):
        self.log.append(["monotonic"])
        return self.mono

    def sleep(self, seconds):
        self.log.append(["sleep", float(seconds)])
        self.now += seconds
        self.mono += seconds
        self.slept = getattr(self, "slept", 0) + 1
        grow(getattr(self, "grows", None), getattr(self, "home", None), self.slept)

    def uuid4(self):
        self.log.append(["uuid"])
        self.ids += 1
        return "00000000-0000-4000-8000-%012x" % self.ids


class Backend:
    def __init__(self, spec, log=None):
        self.engine_version = spec.get("engine_version")
        if spec.get("codex_home") is not None:
            self.codex_home = spec["codex_home"]
        if "app_identity" in spec:
            def app_identity(_spec=spec["app_identity"]):
                log.append(["app_identity"])
                return answer(_spec)
            self.app_identity = app_identity
        if "loaded" in spec:
            queue = Queue(spec["loaded"])

            def loaded(thread, identity):
                log.append(["loaded", thread, identity])
                return queue.next(None)
            self.loaded = loaded
        if "codex_exe" in spec:
            self.codex_exe = spec["codex_exe"]


def last_text(arguments):
    found = None
    for each in arguments:
        if isinstance(each, (list, tuple)):
            found = last_text(each) or found
        elif isinstance(each, (str, Path)):
            found = str(each)
    return found


def files_then(found, arguments):
    """A hand's answer {"$files": {name: text}, "$answer": value}: the files written into the last folder its arguments
    name (the schema's --out), then the answer."""
    if not isinstance(found, dict) or not isinstance(found.get("$files"), dict):
        return found
    folder = last_text(arguments)
    if folder is not None:
        for name, body in found["$files"].items():
            path = Path(folder) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body if isinstance(body, str) else "", encoding="utf-8")
    return answer(found.get("$answer"))


def holders(case, log):
    """windows.resource_users, pairing.inventory and pairing.session_kind for this case."""
    users = Queue(case.get("users"))
    holder = Queue(case.get("holder"))

    def resource_users(path, *more):
        if case.get("users") is None:
            raise RuntimeError("refused in the S7.4 diff: no real engine, process or install is asked")
        log.append(["users", str(path)])
        found = users.next([])
        if not isinstance(found, list):
            raise TypeError("stand-in")
        return found

    def inventory_of(*unused, **also):
        log.append(["inventory"])
        return []

    def session_kind(rows, user, codex_exe):
        log.append(["session_kind", user, codex_exe])
        return bool(holder.next(False))
    _windows.resource_users = resource_users
    inventory.resource_users = resource_users
    pairing.inventory = inventory_of
    pairing.session_kind = session_kind


def grow(steps, home, slept):
    """The Codex home changing while a probe watches it: each step at its sleep (`at`), history rows and rollout
    lines added."""
    import sqlite3
    if not steps or home is None:
        return
    for step in steps:
        if step.get("at") != slept:
            continue
        for sql in step.get("history_sql") or ():
            connection = sqlite3.connect(Path(home) / "thread_history_1.sqlite")
            try:
                connection.execute(sql[0], sql[1:])
                connection.commit()
            finally:
                connection.close()
        for thread, lines in (step.get("append") or {}).items():
            with (Path(home) / "sessions" / ("rollout-" + thread + ".jsonl")).open("ab") as stream:
                for line in lines:
                    stream.write(json.dumps(line).encode("utf-8") + b"\n")


def seams(case, log):
    given = {}
    backend = case.get("backend")
    given["backend"] = Backend(backend, log) if isinstance(backend, dict) else None
    if case.get("session") is not None:
        given["session_factory"] = factory_of(case["session"], log)
    if case.get("launcher") is not None:
        queue = Queue(case["launcher"])
        def launcher():
            log.append(["launcher"])
            return queue.next(None)
        given["launcher"] = launcher
    if case.get("cli") is not None:
        spec = case["cli"]
        def cli(arguments):
            joined = " ".join(arguments)
            log.append(["cli", joined])
            return answer(spec[joined]) if joined in spec else None
        given["cli"] = cli
    if case.get("ipc") is not None:
        spec = case["ipc"]
        def ipc():
            log.append(["ipc"])
            return answer(spec)
        given["ipc"] = ipc
    hands = {}
    for name, spec in (case.get("hands") or {}).items():
        def hand(*arguments, _name=name, _queue=Queue(spec)):
            log.append(["hand", _name, [str(each) if isinstance(each, Path) else
                                        (list(each) if isinstance(each, tuple) else each) for each in arguments]])
            return files_then(_queue.next(None), arguments)
        hands[name] = hand
    if case.get("restart") is not None:
        spec = case["restart"]

        def codex_restart(home, read):
            log.append(["restart", None if home is None else str(home)])
            for _ in range(spec.get("reads") or 0):
                log.append(["read", read()])
            return answer(spec.get("answer"))
        hands["codex_restart"] = codex_restart
    holders(case, log)
    given["hands"] = hands or None
    return given


def norm(value):
    if isinstance(value, (set, frozenset)):
        return sorted(norm(each) for each in value)
    if isinstance(value, (tuple, list)):
        return [norm(each) for each in value]
    if isinstance(value, dict):
        return {str(key): norm(each) for key, each in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def one(case, log):
    op = case["op"]
    clock = Clock(case.get("clock"), log)
    measure.time = types.SimpleNamespace(time=clock.time, monotonic=clock.monotonic, sleep=clock.sleep,
                                         strftime=time.strftime, gmtime=time.gmtime)
    measure.uuid = types.SimpleNamespace(uuid4=clock.uuid4)
    for name, value in HELD.items():
        setattr(measure, name, value)
    for name, value in (case.get("timing") or {}).items():
        setattr(measure, TIMING[name], value)
    folder = case.get("dir")
    clock.grows = case.get("grow")
    clock.home = (case.get("backend") or {}).get("codex_home") if isinstance(case.get("backend"), dict) else None
    product, windows = case.get("product_version", "0.6.26"), case.get("windows_build")
    measure.config = types.SimpleNamespace(version=lambda: product)
    measure.sys = types.SimpleNamespace(getwindowsversion=None if windows is None else (
        lambda: types.SimpleNamespace(**dict(zip(("major", "minor", "build"), map(int, windows.split(".")))))))
    if op == "run":
        given = seams(case, log)
        return norm(measure.run(case["measurement"], session_factory=given.get("session_factory"),
                                launcher=given.get("launcher"), backend=given["backend"],
                                versions=case.get("versions"), clock=clock.time, directory=folder,
                                thread=case.get("thread"), may_spend=case.get("may_spend") is True,
                                cli=given.get("cli"), ipc=given.get("ipc"), hands=given.get("hands")))
    if op == "complete":
        backend = case.get("backend")
        return norm(measure.complete(case["measurement"], case["verdict"], case.get("note", ""),
                                     backend=Backend(backend, log) if isinstance(backend, dict) else None,
                                     versions=case.get("versions"), clock=clock.time, directory=folder))
    if op == "ev_complete":
        Measurement(case["measurement"]), Verdict(case["verdict"])
        return str(evidence.complete(case["measurement"], case["verdict"], case.get("note", ""),
                                     codex_version=case.get("codex_version"),
                                     recorded_at=case.get("recorded_at", ""), directory=folder))
    if op in ("build", "build_write"):
        record = evidence.build(case["measurement"], case["verdict"], case.get("observed"),
                                product_version=case.get("product_version"),
                                codex_version=case.get("codex_version"), windows_build=case.get("windows_build"),
                                recorded_at=case.get("recorded_at"), note=case.get("note"))
        return norm(record) if op == "build" else str(evidence.write(record, directory=folder))
    if op == "outcome":
        found = evidence.outcome(case.get("record"))
        return None if found is None else [str(found[0]), found[1]]
    if op == "content_free":
        return evidence._content_free(case.get("value"))
    if op == "no_content":
        return evidence._no_content(case.get("value", ""))
    if op == "iso":
        return measure._iso(case.get("value", 0.0))
    if op == "threads_valid":
        Measurement(case["measurement"])
        return measure._threads_valid(Measurement(case["measurement"]), case.get("value"))
    if op == "completed_status":
        return measure._completed_status(case.get("events") or [], case.get("thread", ""), case.get("turn"))
    if op == "goal_status":
        return measure._goal_status(case.get("value"))
    raise RuntimeError("unknown op " + op)


results = []
for case in request["cases"]:
    log = []
    try:
        answer_ = {"ok": one(case, log)}
    except Exception as exc:
        answer_ = {"raised": type(exc).__name__}
    results.append({"answer": answer_, "log": norm(log)})
sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False))
'''


def probe_path() -> Path:
    return advref.target_dir() / "release" / "examples" / (EXAMPLE + ".exe")


def build() -> None:
    """`cargo build --release --locked --example advmeasure` (incremental: quick when nothing changed)."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "--example", EXAMPLE, "--manifest-path",
                    str(advref.MANIFEST)], env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


def _line(line) -> bytes:
    if isinstance(line, dict) and "$hex" in line:
        return bytes.fromhex(line["$hex"])
    return json.dumps(line).encode("utf-8") + b"\n"


def build_home(root: Path, spec: dict) -> Path:
    """A Codex home on disk from a case's declarative `home` (codexdiff.Home's tables and rollouts): `threads`, `turns`,
    `items`, `users` (a person's messages with a client id), `edges`, `state_sql` / `history_sql` (raw statements),
    `append` (rollout lines per thread: events, or {"$hex": raw}), `files` (relative path: hex) and `remove`."""
    from rustdiff import codexdiff
    home = codexdiff.Home(root)

    def rooted(sql):
        return [sql[0]] + [each.replace("$root", str(root)) if isinstance(each, str) else each for each in sql[1:]]
    for sql in spec.get("state_sql") or ():
        home.state(*rooted(sql))
    for sql in spec.get("history_sql") or ():
        home.history(*rooted(sql))
    for row in spec.get("threads") or ():
        row = dict(row)
        thread = row.pop("id")
        if "first_hex" in row:
            row["first"] = bytes.fromhex(row.pop("first_hex"))
        home.thread(thread, **row)
    for row in spec.get("turns") or ():
        row = dict(row)
        home.turn(row.pop("thread"), row.pop("turn"), **row)
    for row in spec.get("items") or ():
        home.item(row["thread"], row["turn"], row["item"], row["type"], row.get("payload"), row.get("ordinal", 1))
    for row in spec.get("users") or ():
        home.user_message(row["thread"], row["turn"], row["item"], row.get("text", "words"), row.get("client_id"),
                          row.get("ordinal", 1))
    if spec.get("edges") is not None:
        home.state("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT, status TEXT)")
        for parent, child, status in spec["edges"]:
            home.state("INSERT INTO thread_spawn_edges VALUES (?,?,?)", parent, child, status)
    for thread, lines in (spec.get("append") or {}).items():
        with home.sim.rollout(thread).open("ab") as stream:
            for line in lines:
                stream.write(_line(line))
    for name, raw in (spec.get("files") or {}).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes.fromhex(raw))
    for sql in spec.get("after_sql") or ():
        home.state(*rooted(sql))
    for name in spec.get("remove") or ():
        (root / name).unlink()
    return root


def _with_dirs(cases: list, folder: Path) -> list:
    made = []
    for index, case in enumerate(cases):
        case = dict(case)
        if case.get("home") is not None:
            root = build_home(folder / ("home%03d" % index), case.pop("home"))
            case["backend"] = dict(case.get("backend") or {}, codex_home=str(root))
        if case.get("dir") == "$dir":
            target = folder / ("case%03d" % index)
            target.mkdir(parents=True, exist_ok=True)
            for name, raw in (case.pop("seed", None) or {}).items():
                (target / name).write_bytes(bytes.fromhex(raw))
            case["dir"] = str(target)
        elif case.get("dir") == "$missing":
            case["dir"] = str(folder / ("missing%03d" % index))
        case.pop("seed", None)
        made.append(case)
    return made


def _files(folder: Path) -> dict:
    # A case's Codex home is its input (its databases name their own folder): only the evidence left is compared.
    return {str(path.relative_to(folder)): path.read_bytes().hex() for path in sorted(folder.rglob("*"))
            if path.is_file() and not path.relative_to(folder).parts[0].startswith("home")}


_SCRATCH = re.compile(r"^.*?(car-(?:mb2?|mtok|mhk|mimg)-)[A-Za-z0-9_]+")


def _scrub(value, folder: str):
    if isinstance(value, str):
        if len(value) > 20000:
            return "<sha256 %s>" % hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()
        return _SCRATCH.sub(r"<tmp>\1X", value.replace(folder, "<dir>"))
    if isinstance(value, list):
        return [_scrub(each, folder) for each in value]
    if isinstance(value, dict):
        return {key: _scrub(each, folder) for key, each in value.items()}
    return value


def _settle(cases: list, results: list) -> list:
    """MQP's adds run on threads of their own on both sides: what their sessions logged is compared as a set (each
    add's open, enter, call and exit), the rest in order."""
    for case, result in zip(cases, results):
        if case.get("measurement") != "mqp":
            continue
        log = result["log"]
        opens = [index for index, entry in enumerate(log) if entry and entry[0] == "open"]
        lists = [index for index, entry in enumerate(log)
                 if entry[:2] == ["call", "thread/queue/list"]]
        if not opens:
            continue
        stop = len(log)
        for index in opens:
            if lists and index < lists[0] and index + 2 == lists[0]:
                stop = index
                break
            if not lists:
                stop = len(log)
        head = [entry for entry in log[:opens[0]]]
        middle = sorted(log[opens[0]:stop], key=lambda entry: json.dumps(entry, sort_keys=True))
        result["log"] = head + middle + log[stop:]
    return results


def both(cases: list) -> tuple:
    """(reference's answers and files, probe's answers and files), each scrubbed of its own folder."""
    sides = []
    for runner in ("reference", "probe"):
        folder = Path(tempfile.mkdtemp(prefix="car-v0627-s74-%s-" % runner))
        try:
            request = {"cases": _with_dirs(cases, folder)}
            request_file = folder / "request.json"
            request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            if runner == "reference":
                done = advref.run(REFERENCE, str(request_file), tag=TAG)
                if done.returncode != 0:
                    raise AssertionError("reference failed: " + done.stderr.decode("utf-8", "replace")[-3000:])
                answer = json.loads(done.stdout.decode("utf-8"))
            else:
                done = subprocess.run([str(probe_path())], input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                                      capture_output=True, creationflags=NO_WINDOW, timeout=900,
                                      env=dict(os.environ, CODEX_AUTO_RESUME_CODEX_EXE=str(folder / "no-such-engine.exe")))
                if done.returncode != 0:
                    raise AssertionError("advmeasure failed: " + done.stderr.decode("utf-8", "replace")[-3000:])
                answer = json.loads(done.stdout.decode("utf-8"))
            request_file.unlink()
            files = _files(folder)
            sides.append((_settle(cases, _scrub(answer["results"], str(folder))), files))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return sides[0], sides[1]

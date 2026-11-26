"""What the S3.3 diffs (diffs_codex_appserver*.py, diffs_codex_compat*.py) share: a stand-in world and a list of
operations, run by the reference and by car-harness (`codexapp.script`), held equal.

A case is `{"world": {...}, "ops": [{"op": name, "args": [...]}, ...]}`. The world is everything the pairing, the
transport and the registry's checks ask of Windows, given rather than read: the process list (`processes`, rows or
`{"raise": code}`), who holds a file (`holders`, by the file's lower-case name, `"*"` for any, or `{"raise": code}`),
live processes' identities (`identities`), files' signers (`signers`, by lower-case path: a name, `{"raise": code}`
or `{"other": true}`), the four variables the pairing reads (`env`: LOCALAPPDATA, ProgramW6432, ProgramFiles,
USERPROFILE; absent means unset), this process's pid (`pid`), the clock the pairing and the transport read
(`clock`, moved by the `advance` op) and the Restart Manager (`restart_manager`). Nothing of this machine's
processes, holders or signatures is read by either side: the reference has `processes_named`, `resource_users`,
`process_identity`, `authenticode.signer`, `os.getpid` and `windows.restart_manager_available` replaced, car-harness
answers from the same world (`car-harness/src/appserver.rs`, `World`).

Each answer is `{"ok": value}`, `{"error": "AdapterError", "code": code}`, `{"error": "DocumentError", "code": code}`
or `{"error": ClassName}`. The module state of both (the inventory, the signers, our own servers, RESULTS, the
reported table, the verified versions) is cleared before each case, as a fresh process starts.

Processes are started only where an operation asks the backend for its engine checks, its usage, a send or a delete,
and then only the `car-fake-codex` copy the diff wrote into the case's scratch bin folder (`Fake`), with no window.
Not a test module (no `test` in its name, and not `diffs_*`): run.py imports it through them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time

from rustdiff import core, diffs, reference

ROOT = core.ROOT

SCRIPT = r'''
import io, json, logging, os, sys, time, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
from codex_auto_resume import windows, compat, compatio
from codex_auto_resume.codex import pairing, layout, appserver, transport
from codex_auto_resume.compat import files, cache, probes, views, evaluator, reported, standing, report
from codex_auto_resume.win import authenticode
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume.compat.model import DocumentError

MANAGED = ("LOCALAPPDATA", "ProgramW6432", "ProgramFiles", "USERPROFILE")
WORLD = {}
CLOCK = [1000.0]
SAID = []
LOGGED = []


class Catch(logging.Handler):
    def emit(self, record):
        LOGGED.append(record.getMessage())


logger = logging.getLogger("codex_auto_resume.codex.appserver")
logger.addHandler(Catch())
logger.setLevel(logging.INFO)
logger.propagate = False


KEEP = 64

def nesting(value):
    best, stack = 0, [(value, 0)]
    while stack:
        node, level = stack.pop()
        if isinstance(node, dict):
            best = max(best, level + 1)
            stack.extend((each, level + 1) for each in node.values())
        elif isinstance(node, (list, tuple, set, frozenset)):
            best = max(best, level + 1)
            stack.extend((each, level + 1) for each in node)
    return best

def shallow(value):
    # The runner's own `json.loads` may be 3.13's (2,998 levels): a value nested past KEEP levels is answered as the one-key
    # object "$nested" and its depth, as car-harness's `shallow` does.
    depth = nesting(value)
    return {"$nested": depth} if depth > KEEP else value


def plain(value):
    if isinstance(value, (tuple, list)):
        return [plain(each) for each in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(each) for each in value)
    if isinstance(value, dict):
        return {str(key) if not isinstance(key, str) else key: plain(each) for key, each in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float) and value != value:
        return "NaN-float"
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return "inf-float" if value > 0 else "-inf-float"
    return value


def raise_of(spec):
    if spec == "OSError":
        return OSError("stand-in")
    if spec in ("ValueError", "TypeError", "RuntimeError"):
        return {"ValueError": ValueError, "TypeError": TypeError, "RuntimeError": RuntimeError}[spec]("stand-in")
    return AdapterError(spec if isinstance(spec, str) else "process_inventory_unavailable")


def fake_named(names, families):
    rows = WORLD.get("processes")
    if isinstance(rows, dict):
        raise raise_of(rows.get("raise"))
    return json.loads(json.dumps(rows if isinstance(rows, list) else []))


def fake_users(*paths):
    holders = WORLD.get("holders") or {}
    if isinstance(holders.get("raise"), str):
        raise raise_of(holders["raise"])
    found = []
    for path in paths:
        key = Path(str(path)).name.lower()
        listed = holders.get(key)
        if not isinstance(listed, list):
            listed = holders.get("*") if isinstance(holders.get("*"), list) else []
        found += json.loads(json.dumps(listed))
    return found


def fake_identity(pid):
    for each in WORLD.get("identities") or []:
        if each.get("pid") == pid:
            if isinstance(each.get("raise"), str):
                raise raise_of(each["raise"])
            return {"pid": each.get("pid"), "path": each.get("path"), "created": each.get("created")}
    raise AdapterError("process_exited")


def fake_signer(path):
    for name, value in (WORLD.get("signers") or {}).items():
        if name.lower() == str(path).lower():
            if isinstance(value, str):
                return value
            if isinstance(value.get("raise"), str):
                raise AdapterError(value["raise"])
            raise RuntimeError("stand-in")
    raise AdapterError("unsigned")


clock = types.SimpleNamespace(monotonic=lambda: CLOCK[0], time=lambda: CLOCK[0], sleep=time.sleep)
pairing.processes_named = fake_named
pairing.resource_users = fake_users
transport.resource_users = fake_users
pairing.process_identity = fake_identity
authenticode.signer = fake_signer
os.getpid = lambda: WORLD.get("pid", 999999) if isinstance(WORLD.get("pid"), int) else 999999
windows.restart_manager_available = lambda: WORLD.get("restart_manager") is not False
pairing.time = clock
transport.time = clock
probes.time = clock
BUNDLED_DEFAULT = files.load_bundled.__defaults__


def fresh(world):
    WORLD.clear()
    WORLD.update(world)
    CLOCK[0] = float(world.get("clock", 1000.0))
    for name in MANAGED:
        os.environ.pop(name, None)
        value = (world.get("env") or {}).get(name)
        if isinstance(value, str):
            os.environ[name] = value
    pairing._LISTED = None
    pairing._OFFICIAL.clear()
    pairing._OWN.clear()
    appserver.RESULTS.clear()
    appserver._SEQUENCE[0] = 0
    transport._VERIFIED = None
    reported._held.clear()
    del LOGGED[:]


def results_of(value):
    return {method: (entry[0], entry[1]) for method, entry in (value or {}).items()}


def doc(text):
    return None if text is None else compat.parse_document(text.encode("utf-8"))


def sources(items):
    return [(name, doc(text), allowed) for name, text, allowed in items]


class Paths:
    def __init__(self, spec, ensure_ok=True):
        self.compat_cache_file = Path(spec.get("cache_file") or "absent-cache.json")
        self.compat_report_file = Path(spec.get("report_file") or "absent-report.json")
        self.ensure_ok = ensure_ok

    def ensure(self):
        if not self.ensure_ok:
            raise OSError("stand-in")


def registry(spec):
    """The module constants the registry reads, set to the case's files, and the paths it is handed."""
    files.load_bundled.__defaults__ = (Path(spec["bundled"]),) + BUNDLED_DEFAULT[1:] if spec.get("bundled") else BUNDLED_DEFAULT
    if spec.get("reported"):
        reported.BUNDLED = Path(spec["reported"])
    return Paths(spec)


class Guard:
    def __init__(self, spec):
        self.spec = spec

    def __enter__(self):
        if self.spec.get("enter") == "raise":
            raise RuntimeError("stand-in")
        return self.spec.get("enter")

    def __exit__(self, *unused):
        if self.spec.get("exit") == "raise":
            raise RuntimeError("stand-in")
        return False


class Stub:
    def __init__(self, spec):
        self.spec, self.seen = spec, None

    def __call__(self, argv, **kwargs):
        import subprocess
        self.seen = {"argv": list(argv), "home": kwargs["env"].get("CODEX_AUTO_RESUME_PLUGIN_HOME"),
                     "timeout": float(kwargs["timeout"])}
        if self.spec.get("raise") == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if self.spec.get("raise"):
            raise OSError("stand-in")
        return types.SimpleNamespace(stdout=self.spec.get("stdout"), returncode=self.spec.get("code"))


class State:
    backend = None
    watch = None
    found = None
    evaluator = None


def backend_state(backend):
    return {"codex_home": str(backend.codex_home), "codex_exe": str(backend.codex_exe),
            "engine_version": backend.engine_version, "engine_verified": backend.engine_verified,
            "queue_remote_supported": backend.queue_remote_supported,
            "served_elsewhere": sorted(backend.served_elsewhere), "app_look": backend.app_look,
            "app_look_why": backend.app_look_why, "looked": backend.app_looked_at is not None,
            "server_holds": backend.server_holds, "layout": backend.layout,
            "protocol_results": {m: list(e) for m, e in getattr(backend, "protocol_results", {}).items()},
            "session_holder": backend.session_holder, "last_checks": backend.last_checks(),
            "reason": backend.app_unmatched_reason}


def messages(path):
    stream = io.TextIOWrapper(io.BytesIO(Path(path).read_bytes()), encoding="utf-8", errors="replace")
    found = []
    del LOGGED[:]
    while True:
        try:
            value = appserver.next_message(stream)
        except RecursionError:
            found.append("RecursionError")
            break
        if value is None:
            break
        found.append("skipped" if value is appserver.SKIPPED else shallow(value))
    return {"messages": found, "said": list(LOGGED)}


def run(state, name, args):
    a = list(args) + [None] * 10
    if name == "world":
        WORLD.update(a[0]); return None
    if name == "advance":
        CLOCK[0] += a[0]; return None
    simple = {
        "engine_row": lambda: pairing.engine_row(a[0]), "app_process": lambda: pairing.app_process(a[0]),
        "windows_apps": lambda: str(pairing._windows_apps()), "package_app": lambda: pairing._package_app(a[0]),
        "package_file": lambda: pairing._package_file(a[0]), "main_slot": lambda: pairing._main_slot(a[0]),
        "main_place": lambda: pairing._main_place(a[0]), "extension_engine": lambda: pairing._extension_engine(a[0]),
        "at_official_location": lambda: pairing.at_official_location(a[0]),
        "official_engine": lambda: pairing.official_engine(a[0]),
        "server_engines": lambda: pairing.server_engines(a[0]),
        "engines_instead": lambda: pairing.engines_instead(a[0], a[1]),
        "app_running": lambda: pairing.app_running(a[0]), "app_running_now": lambda: pairing.app_running_now(),
        "app_engines": lambda: pairing.app_engines(), "inventory": lambda: pairing.inventory(),
        "forget_inventory": lambda: pairing.forget_inventory(),
        "session_kind": lambda: pairing.session_kind(a[0], a[1], a[2]),
        "database_holders": lambda: pairing._database_holders(None if a[0] is None else Path(a[0])),
        "own_server": lambda: pairing.own_server(a[0]),
        "own_server_gone": lambda: pairing.own_server_gone(tuple(a[0]) if isinstance(a[0], list) else a[0]),
        "own_holder": lambda: pairing.own_holder(a[0]),
        "snapshot": lambda: layout.snapshot(a[0], a[1], a[2]), "catalogued": lambda: layout.catalogued(a[0]),
        "layout.read": lambda: layout.read(a[0]),
        "file": lambda: Path(a[0]).read_bytes().hex() if Path(a[0]).is_file() else None,
        "unknown": lambda: appserver._unknown(a[0], a[1]),
        "last_result": lambda: appserver.last_result(a[0], results_of(a[1])),
        "messages": lambda: messages(a[0]),
        "offers": lambda: transport.offers(a[0], a[1]),
        "results": lambda: {m: list(e) for m, e in appserver.RESULTS.items()},
        "said": lambda: [LOGGED.pop(0) for _ in range(len(LOGGED))],
    }
    if name in simple:
        return simple[name]()
    if name == "app_mains":
        mains = pairing.app_mains(a[0])
        return [index for index, row in enumerate(a[0]) if any(row is each for each in mains)]
    if name == "under_app":
        row = a[0][a[1]] if isinstance(a[1], int) and not isinstance(a[1], bool) else a[1]
        return pairing.under_app(a[0], row, a[2])
    if name == "desktop_pair":
        seen = {} if a[4] else None
        try:
            paired = pairing.desktop_pair(a[0], a[1], None if a[2] is None else Path(a[2]), require_holder=bool(a[3]),
                                          seen=seen)
        except AdapterError as error:
            return {"__error__": {"error": "AdapterError", "code": str(error), "seen": seen or {}}}
        return {"paired": paired, "seen": seen or {}}
    if name == "watch.new":
        del SAID[:]
        state.watch = layout.Watch(a[0], a[1], log=lambda line: SAID.append(line), clock=lambda: CLOCK[0])
        return {"said": [SAID.pop(0) for _ in range(len(SAID))], "updated_from": state.watch.updated_from}
    if name == "watch.look":
        if a[0] == "again":
            found = state.found
        elif a[0] is None:
            found = None
        else:
            found = state.found = a[0]
        kept = state.watch.look(found, stamp=a[1], engine_version=a[2])
        return {"kept": kept, "said": [SAID.pop(0) for _ in range(len(SAID))], "updated_from": state.watch.updated_from}
    if name == "backend.new":
        state.backend = transport.Backend(Path(a[0]), Path(a[1]), bool(a[2]))
        return None
    if name == "backend.set":
        state.backend.named_engine = bool((a[0] or {}).get("named_engine"))
        return None
    if name == "backend.state":
        return backend_state(state.backend)
    if name == "backend.engine_checks":
        return state.backend.engine_checks()
    if name == "backend.compatible":
        return state.backend._compatible()
    if name == "backend.app_identity":
        return state.backend.app_identity()
    if name == "backend.loaded":
        return state.backend.loaded(a[0], a[1])
    if name == "backend.holder":
        return state.backend.holder(a[0])
    if name == "backend.usage":
        started = time.monotonic()
        found = state.backend.usage()
        return {"usage": found, "seconds": time.monotonic() - started}
    if name == "backend.delete_queue":
        return state.backend.delete_queue(a[0], a[1])
    if name == "backend.send":
        return state.backend.send(a[0], a[1], launch_guard=None if a[2] is None else Guard(a[2]))
    if name == "backend.send_scoped":
        # Integration 6: Rust sends through car-engine's Transport with a guard of the engine's shape; the reference
        # has one shape, so it answers with the same send and the same stand-in guard.
        return state.backend.send(a[0], a[1], launch_guard=Guard(a[2]))
    if name == "backend.queue_daemon_remote":
        return state.backend._queue_daemon_remote()
    # --------------------------------------------------------------------------------------------- the registry
    if name == "registry.standing":
        return compat.document_standing(doc(a[0]), product=a[1], bundled=doc(a[2]), now=a[3],
                                        role="bundled" if a[4] == "bundled" else "cache")
    if name == "registry.evidence":
        return compat.evidence_for(a[0], a[1], sources(a[2]))
    if name == "registry.evaluate":
        return compat.evaluate(a[0] or {}, version=a[1], sources=sources(a[2]))
    if name == "registry.accepted":
        return compat.accepted_word(a[0], sources(a[1]))
    if name == "registry.verified":
        return compat.verified_versions(doc(a[0]))
    if name == "registry.combine":
        return compat.combine(a[0] or [])
    if name == "registry.resolve":
        return compat.resolve(a[0], a[1])
    if name == "registry.aggregate":
        return compat.aggregate(a[0]) if a[1] is None else compat.aggregate(a[0], a[1])
    if name == "registry.validate_report":
        return compat.validate_report(a[0], now=a[1])
    if name == "registry.build_report":
        return compat.build_report(checked_at=a[0], product=a[1], engine=a[2], data=a[3], checks=a[4] or {},
                                   capabilities=a[5], acting=a[6])
    if name == "registry.unusable_view":
        return compat.unusable_view(a[0], data=a[1], checked_at=a[2], engine=a[3])
    if name == "registry.view_of":
        return compat.view_of(a[0])
    if name == "registry.mcp_view":
        return compat.mcp_view(a[0])
    if name == "registry.finite_number":
        return report._finite_number(a[0])
    if name == "registry.reported_parse":
        return reported.parse(files._read_capped(Path(a[0]), reported.MAX_BYTES))
    if name == "registry.reported_read":
        standing_word, table = reported.read(Path(a[0]))
        return [str(standing_word), table]
    if name == "registry.reported_lookup":
        found = reported.lookup(a[0], path=Path(a[1]))
        return dict(found, state=str(found["state"]))
    if name == "registry.read_capped":
        return files._read_capped(Path(a[0]), a[1]).hex()
    if name == "registry.stamp":
        return files._signature(Path(a[0]))
    if name == "registry.product_version":
        import codex_auto_resume.config as config
        saved = config.version
        config.version = lambda: a[0]
        try:
            return files.product_version()
        finally:
            config.version = saved
    if name == "registry.load_bundled":
        document, state_word = files.load_bundled(Path(a[0]), product=a[1], now=0)
        return [document, str(state_word)]
    if name == "registry.bundled_verified":
        files.load_bundled.__defaults__ = (Path(a[0]),) + BUNDLED_DEFAULT[1:]
        import codex_auto_resume.config as config
        saved = config.version
        config.version = lambda: a[1]
        try:
            return files.bundled_verified_versions()
        finally:
            config.version = saved
            files.load_bundled.__defaults__ = BUNDLED_DEFAULT
    if name == "registry.write_json":
        return files.write_json_atomic(Path(a[0]), a[1], a[2])
    if name == "registry.path_digest":
        return files.path_digest(a[0])
    if name == "registry.read_cache":
        bundled = files.load_bundled(Path(a[1]), product=a[2], now=a[3])[0] if a[1] else None
        return cache.read_cache(Path(a[0]), bundled=bundled, product=a[2], now=a[3])
    if name == "registry.judge_cache":
        bundled = files.load_bundled(Path(a[1]), product=a[2], now=a[3])[0] if a[1] else None
        first = cache.read_cache(Path(a[0]), bundled=bundled, product=a[2], now=a[3])
        return cache.judge_cache(first, bundled=bundled, product=a[2], now=a[4])
    if name == "registry.import":
        files.load_bundled.__defaults__ = (Path(a[0]),) + BUNDLED_DEFAULT[1:]
        try:
            paths = Paths({"cache_file": a[1]}, ensure_ok=a[6] is not False)
            return cache.import_document(paths, a[2], origin=a[3], product=a[4], now=a[5])
        finally:
            files.load_bundled.__defaults__ = BUNDLED_DEFAULT
    if name == "registry.engine_word":
        files.load_bundled.__defaults__ = (Path(a[0]),) + BUNDLED_DEFAULT[1:]
        import codex_auto_resume.config as config
        saved = config.version
        config.version = lambda: a[3]
        try:
            return cache.engine_word(Paths({"cache_file": a[1]}), a[2], now=a[4])
        finally:
            config.version = saved
            files.load_bundled.__defaults__ = BUNDLED_DEFAULT
    if name == "registry.coerce":
        return cache._coerce(a[0])
    if name == "registry.source_checks":
        source = types.SimpleNamespace(home=Path(a[0]))
        from codex_auto_resume.codex import LocalSource
        source = LocalSource(Path(a[0]))
        return probes.source_checks(source)
    if name == "registry.seed":
        appserver.RESULTS.clear()
        appserver.RESULTS.update({m: (e[0], e[1]) for m, e in (a[0] or {}).items()})
        appserver._SEQUENCE[0] = max([e[1] for e in (a[0] or {}).values()] or [0])
        return None
    if name == "registry.api_checks":
        return probes.api_checks()
    if name == "registry.protocol_check":
        return probes.protocol_check(a[0])
    if name == "registry.engine_part":
        return probes._engine_part(a[0])
    if name == "registry.engine_from_discovery":
        return probes.engine_from_discovery(dict((p, r) for p, r in (a[0] or [])), candidates=a[1])
    if name == "registry.engine_from_backend":
        return probes.engine_from_backend(state.backend)
    if name == "registry.server_check":
        return probes.server_check(state.backend)
    if name == "registry.candidate_paths":
        return probes._candidate_paths(a[0])
    if name == "registry.served_engines":
        return list(probes._served_engines())
    if name == "registry.read_report":
        report_value, status = views.read_report(Paths({"report_file": a[0]}), now=a[1])
        return [report_value, status]
    if name == "registry.watchers_server_check":
        return views._watchers_server_check(Paths({"report_file": a[0]}), a[1])
    if name == "registry.binding":
        registry(a[0])
        return views._binding_holds(a[1], a[2])
    if name == "registry.read_view":
        return views.read_view(registry(a[0]), now=a[1], explicit=a[2])
    if name == "registry.reader_view":
        return views.reader_view(registry(a[0]), now=a[1], settings=a[2])
    if name == "registry.reported_for":
        registry(a[0])
        return views.reported_for(a[1])
    if name == "registry.assemble":
        bundled, bundled_state = files.load_bundled(Path(a[3]), product=a[5], now=a[6])
        found = cache.read_cache(Path(a[4]), bundled=bundled, product=a[5], now=a[6])
        return views.assemble(engine_checks=a[0] or {}, engine=a[1] or {}, other_checks=a[2] or {}, bundled=bundled,
                              bundled_state=bundled_state, cache=found, product=a[5], now=a[6], acting=a[7])
    if name in ("registry.live_report", "registry.live_view"):
        paths = registry(a[0])
        import codex_auto_resume.config as config
        saved = config.version
        config.version = lambda: a[0].get("version") or saved()
        try:
            make = views.live_report if name == "registry.live_report" else views.live_view
            discovery = None if a[2] is None else dict((p, r) for p, r in a[2])
            return make(paths, Path(a[1]), backend=state.backend if a[5] else None, discovery=discovery,
                        explicit=a[3], now=a[4])
        finally:
            config.version = saved
    if name == "registry.evaluator.new":
        paths = registry(a[0])
        del SAID[:]
        state.evaluator = evaluator.Evaluator(paths, Path(a[1]), product=a[3], log=lambda line: SAID.append(line),
                                              clock=lambda: CLOCK[0], explicit=a[2],
                                              **({} if a[4] is None else {"recompute": a[4]}))
        return None
    if name == "registry.evaluator.tick":
        acting = state.evaluator.tick(state.backend if a[1] else None, dict((p, r) for p, r in (a[0] or [])))
        return {"acting": acting, "said": [SAID.pop(0) for _ in range(len(SAID))]}
    if name == "registry.evaluator.state":
        e = state.evaluator
        return {"report": e.report, "cache": e.cache, "bundled_state": str(e.bundled_state), "acting": e.acting}
    if name == "registry.run_refresh":
        stub = Stub(a[4] or {})
        import codex_auto_resume.config as config
        saved_root = config.PROJECT_ROOT
        config.PROJECT_ROOT = Path(a[2])
        try:
            found = evaluator.run_refresh(a[0], script=a[1], runner=stub,
                                          **({} if a[3] is None else {"timeout": a[3]}))
        finally:
            config.PROJECT_ROOT = saved_root
        return {"answer": found, "seen": stub.seen}
    return {"__error__": {"error": "NotPorted:" + name}}


def answer(state, operation):
    try:
        value = run(state, operation["op"], operation.get("args", []))
    except AdapterError as error:
        return {"error": "AdapterError", "code": str(error)}
    except DocumentError as error:
        return {"error": "DocumentError", "code": error.code}
    except OSError:
        return {"error": "OSError"}
    except Exception as error:
        return {"error": type(error).__name__}
    if isinstance(value, dict) and "__error__" in value:
        return value["__error__"]
    return {"ok": plain(value)}


answers = []
for case in request["cases"]:
    fresh(case.get("world") or {})
    state = State()
    answers.append({"results": [answer(state, operation) for operation in case.get("ops", [])]})
sys.stdout.write(json.dumps(answers, ensure_ascii=True, allow_nan=False))
'''


def fake_binary() -> Path:
    """The fake engine the harness crate builds beside car-harness."""
    return core.target_dir() / "release" / "car-fake-codex.exe"


class Fake:
    """One case's fake engine: `codex.exe` (a copy of car-fake-codex) in `<local>\\OpenAI\\Codex\\bin\\<hex>\\`, its
    script beside it, and what it was asked (`log()`, `stdin()`), cleared between the two sides."""

    def __init__(self, local: Path, script: dict, hexname: str = "c0de"):
        self.folder = local / "OpenAI" / "Codex" / "bin" / hexname
        self.folder.mkdir(parents=True, exist_ok=True)
        self.exe = self.folder / "codex.exe"
        shutil.copy2(fake_binary(), self.exe)
        (self.folder / "fake.json").write_text(json.dumps(script), encoding="utf-8")

    def taken(self) -> dict:
        """What it was asked since the last call, and the files cleared."""
        log, stdin = self.folder / "fake.log.jsonl", self.folder / "stdin.bin"
        found = {"log": [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                 if log.exists() else [],
                 "stdin": stdin.read_bytes().hex() if stdin.exists() else ""}
        log.unlink(missing_ok=True)
        stdin.unlink(missing_ok=True)
        return found


class AppBase(diffs.Base):
    """`script(cases, label)`: every case through the reference and through car-harness, held equal."""

    def reference_answers(self, cases: list) -> list:
        profile = self.profile("reference-%d" % time.perf_counter_ns())
        path = profile / "cases.json"
        path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
        done = reference.run(SCRIPT, path, profile=profile)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:].decode("utf-8", "replace"))
        self.reference_cwd = str(profile)
        return json.loads(done.stdout.decode("utf-8"))

    def rust_answers(self, cases: list) -> list:
        with core.Harness(reference.scratch_environment(self.profile("rust-%d" % time.perf_counter_ns()))) as harness:
            number, line = harness.call("codexapp.script", cases=cases)
        reply = json.loads(line.decode("utf-8"))
        self.assertEqual(reply.get("id"), number, line[:300])
        self.assertTrue(reply["reply"].get("ok"), line[:600])
        return reply["reply"]["value"]

    def script(self, cases: list, label: str, *, chunk: int = 200, fakes=None, compare=None,
               files=()) -> tuple[int, int]:
        """Held equal: (cases, operations). With `fakes` (one Fake or None per case), what each fake engine was
        asked is held equal too: its arguments, working folder, variables and every byte it was sent. `compare`
        may turn an answer into what is compared (a time in seconds, say). `files` are the paths the operations
        write: each is put back as it was before the Rust side runs, and both sides must leave the same bytes."""
        calls = 0
        for start in range(0, len(cases), chunk):
            part = cases[start:start + chunk]
            part_fakes = (fakes or [None] * len(cases))[start:start + chunk]
            before = {path: Path(path).read_bytes() if Path(path).is_file() else None for path in files}
            expected = self.reference_answers(part)
            asked_reference = [own_cwd(fake.taken(), self.reference_cwd) if fake else None for fake in part_fakes]
            left_reference = {path: Path(path).read_bytes() if Path(path).is_file() else None for path in files}
            for path, data in before.items():
                if data is None:
                    Path(path).unlink(missing_ok=True)
                else:
                    Path(path).write_bytes(data)
            actual = self.rust_answers(part)
            asked_rust = [own_cwd(fake.taken(), os.getcwd()) if fake else None for fake in part_fakes]
            left_rust = {path: Path(path).read_bytes() if Path(path).is_file() else None for path in files}
            for path in files:
                if left_reference[path] != left_rust[path]:
                    self.fail("%s: %s differs after the run: reference %r, rust %r" % (
                        label, path, (left_reference[path] or b"")[:1500], (left_rust[path] or b"")[:1500]))
            self.assertEqual(len(expected), len(actual), label)
            for number, (want, got, case) in enumerate(zip(expected, actual, part)):
                for index, (a, b) in enumerate(zip(want["results"], got["results"])):
                    if compare is not None:
                        a, b = compare(case["ops"][index], a), compare(case["ops"][index], b)
                    if same(a) != same(b):
                        self.fail("%s case %d, op %d (%s %s) differs:\n  reference %s\n  rust      %s" % (
                            label, start + number, index, case["ops"][index]["op"],
                            json.dumps(case["ops"][index].get("args"), ensure_ascii=False)[:400],
                            json.dumps(a, ensure_ascii=False)[:2500], json.dumps(b, ensure_ascii=False)[:2500]))
                self.assertEqual(len(want["results"]), len(got["results"]), "%s case %d" % (label, start + number))
                calls += len(case["ops"])
            for number, (theirs, mine) in enumerate(zip(asked_reference, asked_rust)):
                if theirs != mine:
                    self.fail("%s case %d: the fake engine was asked differently:\n  reference %s\n  rust      %s"
                              % (label, start + number, json.dumps(theirs)[:3000], json.dumps(mine)[:3000]))
        return len(cases), calls


FACTS = r'''
import json, sys
from codex_auto_resume import config
from codex_auto_resume.compat import files, reported
print(json.dumps({"version": config.version(), "bundled": str(files.BUNDLED), "reported": str(reported.BUNDLED),
                  "root": str(config.PROJECT_ROOT)}))
'''
_FACTS = {}


def facts() -> dict:
    """The reference's own version and the data files beside its package (asked once)."""
    if not _FACTS:
        done = reference.run(FACTS)
        _FACTS.update(json.loads(done.stdout.decode("utf-8")))
    return dict(_FACTS)


def same(value) -> str:
    """What is compared: the value's JSON with every character escaped (a lone surrogate is a value too)."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def own_cwd(taken: dict, cwd: str) -> dict:
    """A child started with no working folder of its own inherits its parent's: the reference's scratch profile on one
    side, the harness's folder on the other. That folder is named the same for both."""
    for entry in taken["log"]:
        if entry.get("cwd", "").lower() == str(cwd).lower():
            entry["cwd"] = "<the starter's own working folder>"
    return taken


def op(name: str, *args) -> dict:
    return {"op": name, "args": list(args)}


__all__ = ["AppBase", "Fake", "SCRIPT", "facts", "fake_binary", "op"]

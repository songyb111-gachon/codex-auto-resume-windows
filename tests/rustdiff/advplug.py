"""The plug's runtime traced (seat S7.2a, P7-DESIGN 3.2 `diffs_advplug_*`): one scenario format, run by the reference
tag's own `Runtime` (`advanced/src/codex_auto_resume_advanced/runtime.py`) and by car-adv's `runtime` in the example
`advtrace`, over the same scripted capability, the same clock and the same catalogs, each on a scratch home of its own.

A scenario (`scenario(...)`) is the tests' own capability definitions (`advancedcase.definition()`'s shape, dumped as
`advdiff.dump_def` writes one), a script per capability - what each hook answers, call by call - and steps: arm or watch
a capability, ask at a point, tick and run the errands, P2, P12, P14, P18, P19, the start routes. What is compared, step
by step: every answer (a word, a value, or the kind of object core is handed), the hooks the runtime asked of each code,
in order, and at the end every row of the home's advanced.sqlite, table by table. `secrets.token_hex` is one counter on
both sides and the clock is the scenario's.

Nothing here reaches the real machine: every home is a scratch folder, the policy is NONE, the Compatibility Registry
view and the measurements are the scenario's (`advancedcase.view()` and `{}`), and no Codex is looked for.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess

from rustdiff import advref

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000002"
KEY = "a" * 64
OTHER_KEY = "b" * 64
ENGINE = "0.155.0"
NOW = 1_800_000_000.0
COMPAT = "not_loaded_recovery"

# What every scenario's runtime is made with on the reference's side, then the scenario's own steps. The script is the
# tag's own advanced edition; it writes {"results": [...], "asked": [...]} on stdout.
REFERENCE = r'''
import contextlib, json, secrets, shutil, sys
from pathlib import Path
from codex_auto_resume import config, l10n
from codex_auto_resume.domain.plug import BACKEND, DEFER, Alternative, Point
from codex_auto_resume_advanced import policy, statement
from codex_auto_resume_advanced.registry import Registry
from codex_auto_resume_advanced.runtime import Runtime

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
scenario = request["scenario"]
counter = [0]
def token_hex(count=32):
    counter[0] += 1
    return ("%x" % counter[0]).rjust(count * 2, "0")[-count * 2:]
secrets.token_hex = token_hex

clock = [scenario.get("now", 1800000000.0)]
asked = []
CLASSES = {"ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError, "RuntimeError": RuntimeError,
           "OSError": OSError}

class Thing:
    """An object core is handed: a channel, a route, an errand or a start route, as the spec says."""
    def __init__(self, kind, spec, capability):
        self.kind, self.spec, self.capability = kind, spec, capability
    def __getattr__(self, name):
        if self.kind == "channel" and name == "send":
            return lambda *a, **k: {"ok": True}
        if self.kind == "channel" and name == "pools" and "pools" in self.spec:
            return lambda: answer(self.spec["pools"], (), self.capability, "pools")
        if self.kind == "route" and name == "resume":
            return lambda *a, **k: {"ok": True}
        if self.kind == "route" and name == "takes_words":
            return lambda: bool(self.spec.get("words"))
        if self.kind == "start" and name == "start":
            return lambda *a, **k: {"ok": True}
        if self.kind == "errand" and name == "run":
            def run(guard):
                asked.append([self.capability, "errand.run"])
                if "raise" in self.spec:
                    raise CLASSES.get(self.spec["raise"], RuntimeError)("raised")
                with guard() as permitted:
                    asked.append([self.capability, "errand.permitted", bool(permitted)])
                return self.spec.get("returns")
            return run
        raise AttributeError(name)

calls = {}
def answer(spec, arguments, capability, hook):
    if isinstance(spec, dict) and "seq" in spec:
        index = calls.get((capability, hook), 0)
        calls[(capability, hook)] = index + 1
        items = spec["seq"]
        spec = items[min(index, len(items) - 1)]
    if isinstance(spec, dict) and "by" in spec:
        chosen = arguments[spec["by"]] if spec["by"] < len(arguments) else None
        spec = spec["cases"].get(chosen if isinstance(chosen, str) else json.dumps(chosen), spec.get("else", "DEFER"))
    if spec == "DEFER":
        return DEFER
    if spec == "BACKEND":
        return BACKEND
    if not isinstance(spec, dict):
        return spec
    if "word" in spec:
        return Alternative(spec["word"])
    if "value" in spec:
        return spec["value"]
    if "tuple" in spec:
        return tuple(spec["tuple"])
    if "set" in spec:
        return frozenset(spec["set"])
    if "raise" in spec:
        raise CLASSES.get(spec["raise"], RuntimeError)("raised")
    if "call" in spec:
        arguments[0]()
        return None
    for kind in ("channel", "route", "errand", "start"):
        if kind in spec:
            return Thing(kind, spec[kind], capability)
    return spec

MAIN = {"records", "gate", "text", "sender", "outcome", "schedule", "tick", "start_route", "partition", "supervise",
        "delivery", "unloaded", "admission", "sessions", "eligibility", "notice", "power", "resident"}
OPTIONAL = {"rule_for", "taken", "carries", "not_taken", "holds", "watched_due", "words_sent", "tend", "images_of",
            "acted_when_told"}

class Scripted:
    def __init__(self, capability, script):
        self._capability, self._script = capability, script
        for name in OPTIONAL:
            if name in script:
                setattr(self, name, self._hook(name))
    def _hook(self, name):
        def hook(*arguments):
            asked.append([self._capability, name])
            plain = [a for a in arguments if a is not BACKEND]
            return answer(self._script[name], [a if not hasattr(a, "now") else None for a in plain],
                          self._capability, name)
        return hook
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in MAIN and name in self._script:
            return self._hook(name)
        raise AttributeError(name)

definitions = [build_def(each) for each in scenario["definitions"]]
script = scenario.get("script", {})
def maker(capability):
    def make(paths):
        if capability in scenario.get("unmakeable", ()):
            raise TypeError("no code")
        return Scripted(capability, script.get(capability, {}))
    return make
import dataclasses
definitions = [dataclasses.replace(each, make=maker(each.id)) for each in definitions]
home = Path(request["home"])
directory = Path(request["catalogs"])
if not directory.exists():
    # advancedcase.catalogs: the shipped catalogs, with a statement for each definition in every language.
    shutil.copytree(statement.DIRECTORY, directory)
    for locale in l10n.LOCALES:
        path = directory / ("%s.json" % locale)
        table = json.loads(path.read_text(encoding="utf-8"))
        for made in definitions:
            for field in statement.FIELDS:
                table[statement.key(made.id, field)] = "%s %s (%s)" % (made.id, field, locale)
        path.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
catalogs = statement.Catalogs(directory)
view = {"status": "ok", "engine": {"found": True, "version": "0.155.0"},
        "capabilities": {"not_loaded_recovery": {"state": scenario.get("compat_state", "COMPATIBLE"),
                                                 "reason": "local_checks_passed"}}}
runtime = Runtime(config.Paths(home), registry=Registry(definitions), clock=lambda: clock[0],
                  policy=lambda: policy.NONE, view=lambda: view, measured=lambda: {}, catalogs=catalogs)

class View:
    def __init__(self, core):
        self.now, self._core = clock[0], core
    def get(self, key):
        return self._core.get(key)

def said(value):
    if value is DEFER:
        return "DEFER"
    if value is BACKEND:
        return "BACKEND"
    if isinstance(value, Alternative):
        return {"word": str(value)}
    if isinstance(value, Thing):
        return {"object": value.kind}
    if hasattr(value, "run") and hasattr(value, "errands"):
        return {"object": "errands"}
    return {"value": norm(value)}

@contextlib.contextmanager
def guard():
    yield True

results, last = [], [None]
for step in scenario["steps"]:
    op, args = step[0], step[1:]
    try:
        if op == "clock":
            clock[0] = args[0]
            out = None
        elif op == "arm":
            capability, state = args[0], args[1]
            request = dict(state=state, revision=runtime.registry.get(capability).revision,
                           generation=runtime.state.meta()["generation"], acknowledged_version="0.155.0",
                           actor="dashboard")
            request.update(args[2] if len(args) > 2 else {})
            out = norm(runtime.arming.arm(capability, **request))
        elif op == "ask":
            point = Point(args[0])
            arguments = list(args[1:]) + ([BACKEND] if point == Point.SENDER else [])
            out = said(runtime.ask(point, *arguments))
        elif op == "tick":
            found = runtime.tick(View(scenario.get("core", {})))
            last[0] = None if found is DEFER else found
            out = "DEFER" if found is DEFER else {"object": "errands"}
        elif op == "resident":
            found = runtime.resident(View(scenario.get("core", {})))
            last[0] = None if found is DEFER else found
            out = "DEFER" if found is DEFER else {"object": "errands"}
        elif op == "run":
            out = None if last[0] is None else norm(last[0].run(guard))
        elif op == "records":
            out = said(runtime.records(View(scenario.get("core", {}))))
        elif op == "partition":
            out = said(runtime.partition(args[0]))
        elif op == "moved":
            out = said(runtime.moved(args[0], args[1]))
        elif op == "sessions":
            out = said(runtime.sessions())
        elif op == "eligibility":
            out = said(runtime.eligibility())
        elif op == "wants":
            out = runtime.wants(Point(args[0]))
        elif op == "start_route":
            out = said(runtime.start_route(args[0]))
        elif op == "start_held":
            out = runtime.start_held()
        elif op == "supervise":
            out = said(runtime.supervise(args[0]))
        elif op == "supervise_held":
            out = runtime.supervise_held()
        elif op == "conversation_off":
            out = said(runtime.conversation_off(args[0]))
        elif op == "states":
            found = runtime.states(fresh=bool(args and args[0]))
            out = {capability: str(state) for capability, state in sorted(found.items())}
        else:
            raise SystemExit("unknown op %s" % op)
        results.append({"ok": out})
    except Exception as error:
        results.append({"error": type(error).__name__})
runtime.state.close()
sys.stdout.write(json.dumps({"results": results, "asked": asked}, ensure_ascii=False, allow_nan=False))
'''


def probe_path() -> Path:
    named = os.environ.get("CODEX_AR_ADV_TRACE_EXE")
    return Path(named) if named else advref.target_dir() / "release" / "examples" / "advtrace.exe"


def build() -> None:
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advtrace",
                    "--manifest-path", str(advref.ADVANCED / "Cargo.toml")],
                   env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


def ensure() -> Path:
    if not probe_path().is_file():
        build()
    return probe_path()


def dump(home: Path) -> dict:
    """Every row of the home's advanced.sqlite, table by table, in rowid order (none where there is no file)."""
    path = home / "config" / "advanced" / "advanced.sqlite"
    if not path.is_file():
        return {}
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        found = {}
        for table in tables:
            rows = connection.execute("SELECT * FROM %s ORDER BY rowid" % table).fetchall()
            found[table] = [list(row) for row in rows]
        return found
    finally:
        connection.close()


def run_reference(scenario: dict, home: Path, catalog_dir: Path, scratch: Path) -> dict:
    from rustdiff import advdiff
    request = scratch / "advplug-request.json"
    request.write_text(json.dumps({"scenario": scenario, "home": str(home), "catalogs": str(catalog_dir)},
                                  ensure_ascii=False), encoding="utf-8")
    done = advref.run(advdiff.PRELUDE + REFERENCE, str(request), profile=scratch)
    if done.returncode != 0:
        raise AssertionError("reference failed: %s" % done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))


def run_rust(scenario: dict, home: Path, catalog_dir: Path) -> dict:
    request = json.dumps({"scenario": scenario, "home": str(home), "catalogs": str(catalog_dir)}, ensure_ascii=False)
    done = subprocess.run([str(ensure())], input=request.encode("utf-8"), capture_output=True,
                          creationflags=NO_WINDOW, timeout=600)
    if done.returncode != 0:
        raise AssertionError("advtrace failed (%d): %s" % (done.returncode,
                                                           done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))

"""The engine's capabilities for sends and turns traced (seat S7.2e1, P7-DESIGN 3.2 `diffs_advturns_*`): one scenario
format, run by the v0.6.26 tag's own `Runtime` over its own capability classes and by car-adv's `runtime` in the example
`advturns` over the ported ones, each made with the scenario's fakes (`seams`: a session's answers, a conversation's
turns, the run follower's state, the app's look), on the same clock and the same catalogs, each on a scratch home.

A scenario names the shipped capabilities its registry holds (`capabilities`), the measurements passed (`measured`), the
fakes, and steps: arm (warnings "AUTO": the ones its statement shows), choose an option, ask at a point, tick and run the
errands, P2, P12, P18, P19, and the fakes' own steps (`world` ops). What is compared, step by step: every answer, every
call a fake was asked, in order, and at the end every row of the home's advanced.sqlite. `secrets.token_hex` is one
counter on both sides and the clock is the scenario's. No Codex is started or looked for; no real home is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess

from rustdiff import advref
from rustdiff import advturnsworld

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
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict

request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
scenario = request["scenario"]
counter = [0]
def token_hex(count=32):
    counter[0] += 1
    return ("%x" % counter[0]).rjust(count * 2, "0")[-count * 2:]
secrets.token_hex = token_hex

clock = [scenario.get("now", 1800000000.0)]
asked = []

from codex_auto_resume_advanced import registry as shipped_registry
every = {d.id: d for d in list(shipped_registry.DEFINITIONS) + [d for d, _ in shipped_registry.WAITING]
         + list(shipped_registry.INSTALLED_ONLY)}
import dataclasses
WORLD = World(scenario.get("seams", {}), asked, clock)
definitions = [dataclasses.replace(every[each], make=WORLD.maker(each)) for each in scenario["capabilities"]]
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
compat_names = ["not_loaded_recovery"] + [d.compat for d in definitions if d.compat]
view = {"status": "ok", "engine": {"found": True, "version": "0.155.0"},
        "capabilities": {name: {"state": scenario.get("compat_state", "COMPATIBLE"), "reason": "local_checks_passed"}
                         for name in compat_names}}
measured = {Measurement(name): (Verdict(entry[0]), entry[1]) for name, entry in scenario.get("measured", {}).items()}
runtime = Runtime(config.Paths(home), registry=Registry(definitions), clock=lambda: clock[0],
                  policy=lambda: policy.NONE, view=lambda: view, measured=lambda: measured, catalogs=catalogs)

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
    if hasattr(value, "run") and hasattr(value, "errands"):
        return {"object": "errands"}
    if hasattr(value, "resume"):
        return {"object": "route"}
    if hasattr(value, "run"):
        return {"object": "errand"}
    if hasattr(value, "send"):
        return {"object": "channel"}
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
            if request.get("warnings") == "AUTO":
                request["warnings"] = [str(word) for word in runtime.arming.warnings(runtime.registry.get(capability))]
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
        elif op == "choose":
            out = norm(runtime.arming.set_option(args[0], args[1], args[2],
                                                 generation=runtime.state.meta()["generation"], actor="dashboard"))
        else:
            out = WORLD.step(op, args, runtime)
        results.append({"ok": out})
    except Exception as error:
        results.append({"error": type(error).__name__})
runtime.state.close()
sys.stdout.write(json.dumps({"results": results, "asked": asked}, ensure_ascii=False, allow_nan=False))
'''


def probe_path() -> Path:
    named = os.environ.get("CODEX_AR_ADV_TURNS_EXE")
    return Path(named) if named else advref.target_dir() / "release" / "examples" / "advturns.exe"


def build() -> None:
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advturns",
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
    request = scratch / "advturns-request.json"
    request.write_text(json.dumps({"scenario": scenario, "home": str(home), "catalogs": str(catalog_dir)},
                                  ensure_ascii=False), encoding="utf-8")
    done = advref.run(advdiff.PRELUDE + advturnsworld.REFERENCE_WORLD + REFERENCE, str(request), profile=scratch)
    if done.returncode != 0:
        raise AssertionError("reference failed: %s" % done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))


def run_rust(scenario: dict, home: Path, catalog_dir: Path) -> dict:
    request = json.dumps({"scenario": scenario, "home": str(home), "catalogs": str(catalog_dir)}, ensure_ascii=False)
    done = subprocess.run([str(ensure())], input=request.encode("utf-8"), capture_output=True,
                          creationflags=NO_WINDOW, timeout=600)
    if done.returncode != 0:
        raise AssertionError("advturns failed (%d): %s" % (done.returncode,
                                                           done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))


def scenario(name, capabilities, steps, **more) -> dict:
    """A scenario; every arm step is followed by a fresh look at the states (the runtime keeps them for a moment of
    its clock, as a tick does)."""
    expanded = []
    for step in steps:
        expanded.append(step)
        if step and step[0] == "arm":
            expanded.append(["states", True])
    made = {"name": name, "capabilities": list(capabilities), "steps": expanded, "now": NOW}
    made.update(more)
    return made


def arm(capability, state="armed", **changes) -> list:
    """Armed as a person arms it: confirming the warnings its statement shows."""
    return ["arm", capability, state, dict({"warnings": "AUTO"}, **changes)]


def record(key=KEY, thread=THREAD, **fields) -> dict:
    made = {"interruption_id": key, "thread_id": thread}
    made.update(fields)
    return made


class AdvTurnsCase:
    """A mixin for a unittest.TestCase: `check(scenario)` runs it on both sides and compares the results, the calls
    asked and every row of advanced.sqlite."""

    @classmethod
    def setUpClass(cls):
        ensure()

    def check(self, made: dict) -> None:
        import shutil
        import tempfile
        from rustdiff import advdiff
        scratch = Path(tempfile.mkdtemp(prefix="advturns-"))
        self.addCleanup(shutil.rmtree, scratch, True)
        catalogs = scratch / "catalogs"
        reference = run_reference(made, scratch / "reference-home", catalogs, scratch)
        rust = run_rust(made, scratch / "rust-home", catalogs)
        for part in ("results", "asked"):
            if json.dumps(reference[part]) != json.dumps(rust[part]):
                self.fail("%s %s: %s\nreference %s\nrust      %s" % (
                    made["name"], part, advdiff.first_difference(reference[part], rust[part]),
                    json.dumps(reference[part])[:1500], json.dumps(rust[part])[:1500]))
        want, got = dump(scratch / "reference-home"), dump(scratch / "rust-home")
        if json.dumps(want, sort_keys=True) != json.dumps(got, sort_keys=True):
            self.fail("%s advanced.sqlite: %s" % (made["name"], advdiff.first_difference(want, got)))

    def check_all(self, corpus) -> None:
        only = [name for name in os.environ.get("CODEX_AR_ADVTURNS_ONLY", "").split(",") if name]
        for made in corpus:
            if only and made["name"] not in only:
                continue
            with self.subTest(made["name"]):
                self.check(made)

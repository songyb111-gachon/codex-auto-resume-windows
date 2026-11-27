"""What the S7.2c diffs (diffs_advcodex_*.py) share: the advanced edition's codex parts, autocheck, compatdata and inuse,
run by the v0.6.26 final's own advanced edition and by car-adv's `advcodex` probe, on the same inputs, held equal.

A request is `{"world": {...}, "cases": [[op, arg, ...], ...]}`. The reference (`REFERENCE`, run by `advref.run` under
the final tag: PYTHONPATH the tag's `src;advanced/src`, CODEX_AR_EDITION=advanced, every home a scratch folder) and the
probe (car-adv's example `advcodex`, started with the very same environment) each run every case in order and answer
`{"results": [{"ok": value} | {"error": class[, "code": code]}]}`. The world stands in for what the engines' checks ask
of Windows: each file's Authenticode signer (`signers`, by lower-case path) and the process list (`processes`); the
reference has `authenticode.signer`, `pairing.processes_named`, `resource_users`, `process_identity` and `os.getpid`
replaced, the probe answers from the same world (`examples/advcodex/world.rs`).

Where a case writes files or starts the fake engine, `Scene` runs the reference first and the probe second on the SAME
folders (a digest of an engine's path is part of what the check writes, so the two may not run on copies): `setup()`
makes the homes, the reference runs, what it left is taken, `setup()` makes them again, the probe runs, and both
answers and both sets of files must be equal. The engine is car-adv's example `advfake` (a stand-in for codex.exe that
answers from a script beside it and logs what it was asked), copied into a scratch folder that both runs share and
neither changes; nothing else is ever started.

D17: the reference is the v0.6.26 final (`inuse.saw`/`elsewhere` are the final's), CODEX_AR_REFERENCE names another.
Not a test module (no `test` in its name, and not `diffs_*`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from rustdiff import advdiff, advref, diffs, refguard

TAG = os.environ.get("CODEX_AR_REFERENCE") or "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PRODUCT_VERSION = "0.6.26"

REFERENCE = r'''
import json, os, shutil, sys, tempfile, time, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
from codex_auto_resume import config
from codex_auto_resume.codex import pairing
from codex_auto_resume.win import authenticode
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume_advanced import compatdata, autocheck, measured
from codex_auto_resume_advanced.codex import inuse, protocol
from codex_auto_resume_advanced.vocabulary import Measurement, Verdict

WORLD = dict(request.get("world") or {})


def fake_signer(path):
    for name, value in (WORLD.get("signers") or {}).items():
        if name.lower() == str(path).lower():
            if isinstance(value, str):
                return value
            raise RuntimeError("stand-in")
    raise AdapterError("unsigned")


def fake_named(names, families):
    rows = WORLD.get("processes")
    if isinstance(rows, dict):
        raise AdapterError("process_inventory_unavailable")
    return json.loads(json.dumps(rows if isinstance(rows, list) else []))


def no_identity(pid):
    raise AdapterError("process_exited")


authenticode.signer = fake_signer
pairing.processes_named = fake_named
pairing.resource_users = lambda *paths: []
pairing.process_identity = no_identity
os.getpid = lambda: WORLD.get("pid", 999999) if isinstance(WORLD.get("pid"), int) else 999999
pairing.time = types.SimpleNamespace(monotonic=lambda: float(WORLD.get("clock", 1000.0)), time=time.time,
                                     sleep=time.sleep)


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


def unhex(text):
    return bytes.fromhex(text)


class NoProduct:
    """A product whose version cannot be read. The memo of parsed documents (`_SEEN`) is keyed by the product handed
    in, not by what `this_product()` answers - constant in one process - so it is cleared on the way in and out."""
    def __enter__(self):
        self.held = compatdata.this_product
        compatdata.this_product = lambda: None
        compatdata._SEEN.clear()

    def __exit__(self, *unused):
        compatdata.this_product = self.held
        compatdata._SEEN.clear()


class Same:
    def __enter__(self):
        return None

    def __exit__(self, *unused):
        return False


def product_of(value):
    if value == "none":
        return None, NoProduct()
    return (None if value is None else tuple(value)), Same()


def document(found):
    if found is None:
        return None
    return {"sequence": found["sequence"], "published_at": found["published_at"], "expires_at": found["expires_at"],
            "engines": {version: {str(m): [str(v), at] for m, (v, at) in verdicts.items()}
                        for version, verdicts in found["engines"].items()}}


def table_in(rows):
    return {Measurement(m): (Verdict(v), e) for m, v, e in rows}


def table_out(table):
    return sorted([str(m), str(v), e] for m, (v, e) in table.items())


def validated(raw, product):
    wanted, guard = product_of(product)
    with guard:
        try:
            return compatdata.validate(unhex(raw), product=wanted)
        except compatdata.Refused:
            return None


def judged(found):
    return {str(m): [str(word), list(gone)] for m, (word, gone) in found.items()}


def P(home):
    if home is None:
        return None
    return types.SimpleNamespace(home=home, settings_file=Path(home) / "config" / "settings.json")


def run_engine(exe):
    scratch = tempfile.mkdtemp(prefix="car-autocheck-")
    try:
        found = autocheck.run_engine(exe, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return None if found is None else [found[0], judged(found[1])]


def tend(home, now):
    paths = config.Paths(home)
    started = autocheck.tend(paths, clock=lambda: now)
    thread = autocheck._RUNNING.get(Path(paths.home))
    if thread is not None:
        thread.join()
    return started


def backend(home):
    made = inuse.backend(P(home))
    return {"codex_exe": str(made.codex_exe), "codex_home": str(made.codex_home), "engine_version": made.engine_version}


def validate_op(raw, product):
    wanted, guard = product_of(product)
    with guard:
        try:
            return document(compatdata.validate(unhex(raw), product=wanted))
        except compatdata.Refused as refused:
            return {"refused": str(refused)}


def with_product(product, call):
    wanted, guard = product_of(product)
    with guard:
        return call(wanted)


def tables():
    return {"measurement": {str(m): list(v) for m, v in protocol.MEASUREMENT_METHODS.items()},
            "capability": {k: list(v) for k, v in protocol.CAPABILITY_METHODS.items()},
            "forbidden": sorted(protocol.FORBIDDEN_METHODS), "declines": protocol.DECLINE_ANSWERS,
            "accepting": sorted(protocol.ACCEPTING_WORDS), "measured": sorted(protocol.MEASURED_METHODS),
            "advanced": sorted(protocol.ADVANCED_METHODS), "rejection": protocol._REJECTION}


def checks():
    return [[str(m), str(row.reach), list(row.methods), [list(p) for p in row.params], list(row.requests),
             [list(f) for f in row.fields], [list(w) for w in row.words], row.feature]
            for m, row in autocheck.CHECKS.items()]


OPS = {
    "world": lambda value: WORLD.clear() or WORLD.update(value) or None,
    "cd.validate": validate_op,
    "cd.read": lambda path, product: with_product(product, lambda p: document(compatdata._read(Path(path), product=p))),
    "cd.adopt": lambda folder, bundled, now, product: with_product(product, lambda p: compatdata.adopt(
        folder, bundled=None if bundled is None else Path(bundled), now=now, product=p)),
    "cd.in_force": lambda folder, bundled, now, product: with_product(product, lambda p: document(compatdata.in_force(
        folder, bundled=None if bundled is None else Path(bundled), now=now, product=p))),
    "cd.overlay": lambda table, raw, product, engine: table_out(compatdata.overlay(
        table_in(table), None if raw is None else validated(raw, product), engine)),
    "cd.table_for": lambda folder, engine, table, now: table_out(compatdata.table_for(
        None if folder is None else types.SimpleNamespace(state_dir=folder), engine,
        table=None if table is None else table_in(table), now=now)),
    "cd.summary": lambda raw, product: compatdata.summary(None if raw is None else validated(raw, product)),
    "cd.dumps": lambda value: compatdata.dumps(value),
    "cd.slug": lambda text: compatdata.slug(text),
    "cd.evidence_path": lambda version, name: compatdata.evidence_path(version, name),
    "cd.product": lambda text: compatdata._product(text),
    "ac.checks": checks,
    "ac.judge": lambda document, features: judged(autocheck.judge(document, features)),
    "ac.feature_words": lambda text, name: autocheck.feature_words(text, name),
    "ac.read_record": lambda folder: autocheck.read_record(types.SimpleNamespace(advanced_dir=folder)),
    "ac.results_for": lambda folder, engine: dict(sorted((str(m), str(w)) for m, w in autocheck.results_for(
        types.SimpleNamespace(advanced_dir=folder), engine).items())),
    "ac.diagnostics": lambda folder: autocheck.diagnostics(types.SimpleNamespace(advanced_dir=folder)),
    "ac.due": lambda record, key, now: autocheck.due(record, key, now),
    "ac.write": lambda home, record: autocheck._write(config.Paths(home), record),
    "ac.engine_key": lambda exe: autocheck._engine_key(exe),
    "ac.run_engine": run_engine,
    "ac.probe_engine": lambda exe: autocheck.probe_engine(exe),
    "ac.tend": tend,
    "ac.reset": lambda: autocheck._RUNNING.clear() or autocheck._LOOKED.clear() or None,
    "ac.attempt": lambda key, tries, now: autocheck._attempt(None, key, tries, now),
    "iu.tell": lambda home, exe, where: inuse.tell(P(home), exe, where),
    "iu.told": lambda home: inuse.told(P(home)),
    "iu.forget": lambda home: inuse.forget(P(home)),
    "iu.saw": lambda home, look: inuse.saw(P(home), types.SimpleNamespace(**look)),
    "iu.elsewhere": lambda home: inuse.elsewhere(P(home)),
    "iu.home": lambda home: inuse.home(P(home)),
    "iu.pinned": lambda home: inuse._pinned(P(home)),
    "iu.backend": backend,
    "iu.reset": lambda: inuse._TOLD.clear() or inuse._ELSEWHERE.clear() or None,
    "pr.tables": tables,
    "pr.reply_to": lambda request: protocol.reply_to(request),
    "pr.grants_nothing": lambda value: protocol._grants_nothing(value),
    "pr.methods_for": lambda m: protocol.methods_for(m),
    "pr.methods_for_capability": lambda c: protocol.methods_for_capability(c),
}

from codex_auto_resume_advanced.codex import (conversation as conversation_, credits as credits_, goals as goals_,  # noqa: E402
                                              lineage as lineage_, sessions as sessions_, threads as threads_,
                                              turns as turns_)

OPS.update({
    "rd.alpha": lambda text: text.isalpha(),
    "rd.turns.latest": lambda home, thread: turns_.Turns(home).latest(thread),
    "rd.turns.turn_code": lambda home, thread, turn: turns_.Turns(home).turn_code(thread, turn),
    "rd.turns.status": lambda home, thread, turn: turns_.Turns(home).status(thread, turn),
    "rd.turns.recent": lambda home, since: turns_.Turns(home).recent(since),
    "rd.turns.running": lambda home, booted: turns_.Turns(home).running(booted),
    "rd.turns.between": lambda home, thread, after, before: turns_.Turns(home).between(thread, after, before),
    "rd.turns.plan_statuses": lambda home, thread: turns_.Turns(home).plan_statuses(thread),
    "rd.lineage.children": lambda home, parent: lineage_.Lineage(home).children(parent),
    "rd.threads.own": lambda home, limit, skip: threads_.Threads(home).own(limit, frozenset(skip or ())),
    "rd.conversation.view": lambda home, thread: conversation_.Conversation(home).view(thread),
    "rd.sessions.rollout": lambda home, thread: sessions_.Origins(home).rollout(thread),
    "rd.sessions.find": lambda home, thread: sessions_.Origins(home).find(thread),
    "rd.sessions.names": lambda home: sessions_.Origins(home).names(),
    "rd.sessions.origin": lambda home, thread: sessions_.Origins(home).origin(thread),
    "rd.sessions.events_since": lambda home, thread, offset: sessions_.Origins(home).events_since(thread, offset),
    "rd.sessions.newest_event": lambda home, thread: sessions_.Origins(home).newest_event(thread),
    "rd.goals.read": lambda home, thread: goals_.Goals(home).read(thread),
    "rd.credits.parse": lambda reply: credits_.parse(reply),
    "rd.credits.details_listed": lambda reply: credits_.details_listed(reply),
    "rd.credits.outcome": lambda reply: str(credits_.outcome(reply)),
    "rd.credits.full": lambda windows: credits_.full(windows),
    "rd.credits.params": lambda: [credits_.DETAILED, credits_.LIGHT],
})

results = []
for case in request["cases"]:
    try:
        results.append({"ok": norm(OPS[case[0]](*case[1:]))})
    except AdapterError as error:
        results.append({"error": "AdapterError", "code": str(error)})
    except OSError:
        results.append({"error": "OSError"})                # every subclass: what the callers catch
    except Exception as error:
        message = str(error) if type(error).__name__ in ("TurnsUnavailable", "GoalsUnavailable") else None
        results.append({"error": type(error).__name__} if message is None else
                       {"error": type(error).__name__, "code": message})
sys.stdout.write(json.dumps({"results": results}, ensure_ascii=False))
'''

# ------------------------------------------------------------------------------------------------ the Rust side
EXAMPLES = ("advcodex", "advfake")


def example(name: str) -> Path:
    named = os.environ.get("CODEX_AR_ADVCODEX_DIR")
    folder = Path(named) if named else advref.target_dir() / "release" / "examples"
    return folder / ("%s.exe" % name)


def build() -> None:
    """`cargo build --release --locked -p car-adv --example advcodex --example advfake` in the advanced workspace."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    command = ["cargo", "build", "--release", "--locked", "-p", "car-adv", "--manifest-path", str(advref.ADVANCED / "Cargo.toml")]
    for name in EXAMPLES:
        command += ["--example", name]
    subprocess.run(command, env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


def ensure() -> None:
    if not all(example(name).is_file() for name in EXAMPLES):
        build()


# The scratch tree of the running AdvCodexDiff class (its setUpClass sets it): core's discovery is this family's subject
# (inuse.backend, the official folder under a scratch LOCALAPPDATA), so a profile inside it runs both sides as a
# refguard DISCOVERY run on that tree (refguard.DISCOVERY_SUBJECTS names this file): the real inuse.backend, no engine
# path, every home and program-files root and PATH checked, the lookups still the script's stand-ins, and nothing found
# or started outside the tree. Any other profile (advcodexd's) runs as every reference does.
DISCOVERY_TREES: list = []


def environment(profile: Path) -> dict:
    made = advref.environment(Path(profile), TAG)
    for root in DISCOVERY_TREES[-1:]:
        if Path(profile).resolve().is_relative_to(Path(root).resolve()):
            return refguard.discovery_environment(made, root)
    return made


def ask_reference(request: dict, profile: Path) -> list:
    path = Path(tempfile.mkdtemp(prefix="advcodex-req-")) / "request.json"
    try:
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        if len(REFERENCE) > 8000:  # as advref.run: a long script goes in a file of the scratch folder
            script = path.parent / "advcodex-reference.py"
            script.write_text(REFERENCE, encoding="utf-8")
            command = advref.reference.script_command(script, str(path), paths=advref.trees(TAG))
        else:
            command = advref.reference.command(REFERENCE, str(path), paths=advref.trees(TAG))
        done = subprocess.run(command, capture_output=True, env=environment(profile), cwd=str(profile),
                              creationflags=NO_WINDOW, timeout=1800)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    if done.returncode != 0:
        raise AssertionError("the reference failed: %s" % done.stderr[-3000:].decode("utf-8", "replace"))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def ask_rust(request: dict, profile: Path) -> list:
    body = dict(request, product_version=PRODUCT_VERSION)
    done = subprocess.run([str(example("advcodex"))], input=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, env=environment(profile), cwd=str(profile),
                          creationflags=NO_WINDOW, timeout=1800)
    if done.returncode != 0:
        raise AssertionError("advcodex failed (%d): %s" % (done.returncode, done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))["results"]


def snapshot(folders) -> dict:
    """Every file under `folders`, by its path relative to its folder, with its bytes as hex."""
    found = {}
    for folder in folders:
        root = Path(folder)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                found["%s|%s" % (root.name, path.relative_to(root).as_posix())] = path.read_bytes().hex()
    return found


SCRATCH = re.compile(r"^.*?\\(?:car-autocheck-|car-mauto-)[^\\]*", re.IGNORECASE)


def scrubbed(value):
    if isinstance(value, str):
        return SCRATCH.sub("<scratch>", value)
    if isinstance(value, list):
        return [scrubbed(each) for each in value]
    if isinstance(value, dict):
        return {key: scrubbed(each) for key, each in value.items()}
    return value


def engine_log(folder: Path) -> list:
    """What the fake engine was asked, the scratch folders of each run (named at random) written as <scratch>."""
    path = folder / "advfake.log.jsonl"
    if not path.is_file():
        return []
    return [scrubbed(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


class Engine:
    """A fake codex.exe in a folder of its own: `advfake` copied in as codex.exe, with its script and any files."""

    def __init__(self, folder: Path, script: dict, files: dict | None = None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(example("advfake"), self.folder / "codex.exe")
        (self.folder / "advfake.json").write_text(json.dumps(script), encoding="utf-8")
        for name, data in (files or {}).items():
            (self.folder / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        self.exe = str(self.folder / "codex.exe")

    def clear_log(self):
        (self.folder / "advfake.log.jsonl").unlink(missing_ok=True)


class AdvCodexDiff(unittest.TestCase):
    """A diff of S7.2c's modules: `same(...)` runs one request through both sides and holds every answer equal."""

    @classmethod
    def setUpClass(cls):
        ensure()
        advref.package(TAG)
        cls.root = Path(tempfile.mkdtemp(prefix="advcodex-"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        DISCOVERY_TREES.append(cls.root)
        cls.addClassCleanup(DISCOVERY_TREES.remove, cls.root)

    def fresh(self, label: str) -> Path:
        short = re.sub(r"[^A-Za-z0-9]+", "-", label)[:40]
        return Path(tempfile.mkdtemp(prefix="%s-" % short, dir=self.root))

    def compare(self, label, cases, want, got):
        self.assertEqual(len(want), len(got), label)
        for index, (one, other) in enumerate(zip(want, got)):
            if diffs.encode(one) != diffs.encode(other):
                self.fail("%s: case %d differs at %s\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, advdiff.first_difference(one, other), json.dumps(cases[index], ensure_ascii=False)[:600],
                    json.dumps(one, ensure_ascii=False)[:600], json.dumps(other, ensure_ascii=False)[:600]))

    def same(self, label: str, cases: list, *, world: dict | None = None, profile: Path | None = None,
             chunk: int = 4000) -> list:
        """Pure cases (or ones whose files are the case's own): both sides, every answer equal."""
        profile = profile or self.fresh(label)
        want, got = [], []
        for start in range(0, len(cases), chunk):
            request = {"world": world or {}, "cases": cases[start:start + chunk]}
            want += ask_reference(request, profile)
            got += ask_rust(request, profile)
        self.compare(label, cases, want, got)
        return want

    def scene(self, label: str, cases: list, setup, folders, *, world: dict | None = None, engines=(),
              profile: Path | None = None) -> tuple:
        """Cases that write: the reference on the folders `setup()` made, then the probe on them made again; the answers,
        the files left in `folders` and what each engine was asked, equal."""
        profile = profile or self.fresh(label)
        request = {"world": world or {}, "cases": cases}
        left = []
        for ask in (ask_reference, ask_rust):
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)
            for engine in engines:
                engine.clear_log()
            setup()
            answers = ask(request, profile)
            left.append((answers, snapshot(folders), [engine_log(engine.folder) for engine in engines]))
        (want, want_files, want_log), (got, got_files, got_log) = left
        self.compare(label, cases, want, got)
        self.assertEqual(sorted(want_files), sorted(got_files), "%s: the files left differ" % label)
        for name in want_files:
            self.assertEqual(want_files[name], got_files[name], "%s: %s differs" % (label, name))
        self.assertEqual(want_log, got_log, "%s: the engine was asked differently" % label)
        return want, want_files

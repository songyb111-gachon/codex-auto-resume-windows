"""Every codexsim scenario, run twice: once as the standard edition, once with a plug that defers.

A plug that answers DEFER everywhere - and the sender's own backend at P5 - must leave core doing
exactly what NULL leaves it doing: the same rows in the state, the same calls to Codex, in the
same order. That is what makes an advanced installation with nothing turned on the standard
edition, and it is not something reading the code can settle, because the two differ in the one
place core tells them apart: the claim asks a plug's ledger inside its transaction, and NULL's
not at all (store/claims.py). So tests/test_neutral_plug.py runs every scenario in the modules
below as it is written, with NULL, and again with `DeferringPlug`, and compares the two.

Only what the scenario itself does is compared, so what varies from run to run on its own is
held still for both runs alike. The ids a scenario makes up are drawn from one seed for both
runs, and a moment read off the wall clock while the pair ran is written as the one word
WALL_CLOCK wherever it lands: the scenarios keep their own clocks, and a real time in a row is
the test's or the store's reading, never a plug's doing.

The pairs run in worker processes, a few at once, because every scenario runs twice: `run_all`
starts them and hands each the next scenario as it finishes one, and `serve` is what a worker
runs. Not a test module (no `test_` prefix), so discovery does not collect it.

In the advanced lane each scenario runs a third time, with the advanced package's own plug for
a home of its own where nothing was ever turned on (`real_plug`). The core suite there cannot
show it: core takes the package only from beside itself, so with advanced/src on the path the
suite is still the standard edition, and DeferringPlug is only a stand-in for the real one.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import random
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
# Where the advanced package is in the repository, and the variable that names a run's edition
# (tests/editions.py, LEG).
ADVANCED_SRC = ROOT / "advanced" / "src"
LEG = "CODEX_AR_EDITION"
for entry in (str(ROOT / "src"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume.domain.plug import Edition, Plug, Point  # noqa: E402
from codex_auto_resume.engine import options  # noqa: E402
from codex_auto_resume.store import session  # noqa: E402

# Every test module that drives the engine against codexsim (tests/test_neutral_plug.py holds
# this to the modules that import it), and the ones that import it and are not scenarios here.
MODULES = ("test_compat_characterization", "test_compat_io", "test_correlation", "test_engine",
           "test_engine_gates", "test_outcomes", "test_pause_unknown", "test_recovery")
NOT_SCENARIOS = {
    "test_codex_schema": "reads a Codex home through the source alone; it builds no engine",
    "test_source": "reads a Codex home through the source alone; it builds no engine",
    "test_screenshots": "draws the settings window's pictures, one GUI module at a time",
    "test_plug_points": "gives every engine a plug of its own, to hold each point where it stands",
}
# The module whose scenarios simulate days of ticks, handed out first (run_all).
FIRST = ("test_outcomes",)
# The points the engine asks during a tick, a dispatch and a claim. The scenarios between them
# have to reach every one, or a point nothing reaches would pass for a neutral one.
ENGINE_POINTS = frozenset({Point.RECORDS, Point.GATES, Point.TEXT, Point.SENDER, Point.OUTCOME,
                           Point.SCHEDULE, Point.TICK, Point.CLAIM_LEDGER, Point.CONCURRENCY})
# What a moment read off the wall clock while a pair ran is written as, in rows and calls alike.
WALL_CLOCK = "<wall clock>"
# What a scenario is asked of Codex: every call the engine can make of a backend.
BACKEND_CALLS = ("send", "delete_queue", "loaded", "usage", "app_identity")


class DeferringPlug(Plug):
    """The advanced edition with nothing turned on: asked everywhere, NULL's answer everywhere.

    It reads what it is shown, as a plug with capabilities would - its view of the store, and
    the claim's own connection - and remembers each point it was asked at, so a point no
    scenario reaches is seen to be one."""
    __slots__ = ("asked",)
    edition = Edition.ADVANCED
    badge = "Advanced"

    def __init__(self):
        self.asked = set()

    def records(self, view):
        self.asked.add(Point.RECORDS)
        view.settings()
        return super().records(view)

    def gate(self, name, record, facts):
        self.asked.add(Point.GATES)
        return super().gate(name, record, facts)

    def text(self, record, text):
        self.asked.add(Point.TEXT)
        return super().text(record, text)

    def sender(self, record, backend):
        self.asked.add(Point.SENDER)
        return super().sender(record, backend)

    def outcome(self, record, outcome):
        self.asked.add(Point.OUTCOME)
        return super().outcome(record, outcome)

    def schedule(self, record, due):
        self.asked.add(Point.SCHEDULE)
        return super().schedule(record, due)

    def tick(self, view):
        self.asked.add(Point.TICK)
        view.records_in(frozenset({"queued"}))
        return super().tick(view)

    def start_route(self, request):
        self.asked.add(Point.START_ROUTE)
        return super().start_route(request)

    def surface(self, name, facts):
        self.asked.add(Point.SURFACES)
        return super().surface(name, facts)

    def claim_ledger(self, connection, record, now, carried):
        self.asked.add(Point.CLAIM_LEDGER)
        connection.execute("SELECT count(*) FROM interruptions").fetchone()
        return super().claim_ledger(connection, record, now, carried)

    def partition(self, records):
        self.asked.add(Point.CONCURRENCY)
        return super().partition(records)

    def supervise(self, facts):
        self.asked.add(Point.SUPERVISION)
        return super().supervise(facts)


def scenarios(modules=MODULES) -> list[str]:
    """Every test in `modules`, by id, in the order the loader gives them."""
    found = []

    def flatten(suite):
        for test in suite:
            if isinstance(test, unittest.TestCase):
                found.append(test.id())
            else:
                flatten(test)

    for name in modules:
        flatten(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
    return found


def _rows(connection) -> dict:
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: [list(row) for row in connection.execute("SELECT * FROM %s ORDER BY rowid" % table)]
            for table in tables}


def run_one(test_id: str, *, plug=None, seed: str = "") -> dict:
    """One scenario, as written: whether it passed, the rows of every store it opened - as each
    was when it was closed, or when the scenario ended - and every call made of a backend."""
    stores, rows, calls, engines = [], {}, [], []
    drawn = random.Random(seed)

    def uuid4():
        return uuid.UUID(int=drawn.getrandbits(128), version=4)

    opened, closed, built = (session.SessionMixin.__init__, session.SessionMixin.close,
                             options.OptionsMixin.__init__)

    def keep(store):
        if store._connection is not None:
            try:
                rows[stores.index(store)] = _rows(store._connection)
            except sqlite3.Error as exc:
                rows[stores.index(store)] = "unreadable: %s" % type(exc).__name__

    def open_store(self, *args, **kwargs):
        opened(self, *args, **kwargs)
        stores.append(self)

    def close_store(self):
        if self in stores:
            keep(self)
        closed(self)

    def build_engine(self, store, source, backend, *args, **kwargs):
        if plug is not None:
            kwargs.setdefault("plug", plug)
        built(self, store, source, backend, *args, **kwargs)
        engines.append(self)
        if getattr(backend, "_neutral_recorded", False):
            return
        for name in BACKEND_CALLS:
            method = getattr(backend, name, None)
            if method is None:
                continue

            def recorded(*arguments, _name=name, _method=method, **keywords):
                calls.append([_name, list(arguments), sorted(keywords)])
                return _method(*arguments, **keywords)
            setattr(backend, name, recorded)
        with contextlib.suppress(AttributeError):
            backend._neutral_recorded = True

    tests = []

    def flatten(suite):
        for test in suite:
            (tests.append(test) if isinstance(test, unittest.TestCase) else flatten(test))

    flatten(unittest.defaultTestLoader.loadTestsFromName(test_id))
    if len(tests) != 1:
        raise LookupError("%s names %d tests" % (test_id, len(tests)))
    test = tests[0]
    tear_down = test.tearDown

    def keep_open_stores():
        try:
            tear_down()
        finally:
            for store in stores:
                keep(store)

    test.tearDown = keep_open_stores
    result = unittest.TestResult()
    with mock.patch.object(uuid, "uuid4", uuid4), \
            mock.patch.object(session.SessionMixin, "__init__", open_store), \
            mock.patch.object(session.SessionMixin, "close", close_store), \
            mock.patch.object(options.OptionsMixin, "__init__", build_engine):
        # In a suite of its own, so its class's and its module's fixtures run around it as
        # they do in the suite: a registry frozen for a module is frozen for its scenarios too.
        unittest.TestSuite([test]).run(result)
    return {"ok": result.wasSuccessful(), "rows": rows, "calls": calls, "engines": len(engines)}


def steady(value, since: float, until: float):
    """`value` as JSON would carry it, with every moment between `since` and `until` - read off
    the wall clock while the pair ran - written as WALL_CLOCK."""
    if isinstance(value, float) and since <= value <= until:
        return WALL_CLOCK
    if isinstance(value, (list, tuple)):
        return [steady(item, since, until) for item in value]
    if isinstance(value, dict):
        return {str(key): steady(item, since, until) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _difference(standard: dict, plugged: dict) -> str | None:
    """Where the two runs of one scenario part, in a line, or None where they do not."""
    if standard["calls"] != plugged["calls"]:
        index = next((i for i, (a, b) in enumerate(zip(standard["calls"], plugged["calls"])) if a != b),
                     min(len(standard["calls"]), len(plugged["calls"])))
        return "backend call %d: %s with NULL, %s with the plug" % (
            index, (standard["calls"][index:index + 1] or [["nothing"]])[0][0],
            (plugged["calls"][index:index + 1] or [["nothing"]])[0][0])
    for store in sorted(set(standard["rows"]) | set(plugged["rows"])):
        one, other = standard["rows"].get(store), plugged["rows"].get(store)
        if one == other:
            continue
        if not (isinstance(one, dict) and isinstance(other, dict)):
            return "store %s differs as a whole" % store
        return "store %s differs in %s" % (store, ", ".join(sorted(
            table for table in set(one) | set(other) if one.get(table) != other.get(table))))
    return None


def advanced_lane() -> bool:
    """Whether this run is the advanced lane: it says so, and the package is importable."""
    if os.environ.get(LEG) != Edition.ADVANCED:
        return False
    return importlib.util.find_spec("codex_auto_resume_advanced") is not None


def real_plug(home):
    """The advanced package's own plug for `home`, a scratch home where nothing was turned on."""
    from codex_auto_resume import config
    from codex_auto_resume_advanced import plug
    return plug.create(config.Paths(home))


def compare(test_id: str) -> dict:
    """One scenario with NULL and then with a DeferringPlug - and, in the advanced lane, with the
    advanced package's real plug - and how each compares with NULL."""
    since = time.time()
    standard = run_one(test_id, seed=test_id)
    plug = DeferringPlug()
    plugged = run_one(test_id, plug=plug, seed=test_id)
    real = None
    if advanced_lane():
        with tempfile.TemporaryDirectory() as home:
            real = run_one(test_id, plug=real_plug(home), seed=test_id)
    until = time.time()
    standard, plugged = steady(standard, since, until), steady(plugged, since, until)
    result = {"id": test_id, "standard_ok": standard["ok"], "plugged_ok": plugged["ok"],
              "engines": standard["engines"], "difference": _difference(standard, plugged),
              "asked": sorted(plug.asked)}
    if real is not None:
        real = steady(real, since, until)
        result.update(real_ok=real["ok"], real_difference=_difference(standard, real))
    return result


def serve() -> None:
    """A worker: one scenario id a line in, one JSON result a line out, until the input ends.

    What a scenario prints goes to stderr, so nothing but results ever reaches the parent."""
    out = sys.stdout
    sys.stdout = sys.stderr
    for line in sys.stdin:
        test_id = line.strip()
        if not test_id:
            continue
        try:
            result = compare(test_id)
        except Exception as exc:                        # noqa: BLE001 - reported, not raised
            result = {"id": test_id, "error": "%s: %s" % (type(exc).__name__, exc)}
        out.write(json.dumps(result) + "\n")
        out.flush()


def workers() -> int:
    return max(1, min(os.cpu_count() or 1, 8))


def run_all(ids, *, count=None, timeout=1800) -> dict:
    """Every scenario in `ids`, compared, in `count` worker processes: id -> result.

    Each worker is handed the next scenario as it finishes one, and the slowest module's go
    first (FIRST), so no worker is left alone with a long one at the end."""
    pending = queue.Queue()
    for test_id in sorted(ids, key=lambda name: name.split(".", 1)[0] not in FIRST):
        pending.put(test_id)
    results, lock = {}, threading.Lock()
    env = dict(os.environ)
    path = [str(ROOT / "src"), str(HERE)] + ([str(ADVANCED_SRC)] if advanced_lane() else [])
    env["PYTHONPATH"] = os.pathsep.join(path)
    env["PYTHONIOENCODING"] = "utf-8"
    deadline = time.monotonic() + timeout

    def work(path):
        with open(path, "w", encoding="utf-8") as log, subprocess.Popen(
                [sys.executable, "-c", "import neutral; neutral.serve()"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", cwd=str(ROOT),
                env=env) as process:
            while time.monotonic() < deadline:
                try:
                    test_id = pending.get_nowait()
                except queue.Empty:
                    break
                process.stdin.write(test_id + "\n")
                process.stdin.flush()
                line = process.stdout.readline()
                if line:
                    result = json.loads(line)
                else:
                    log.flush()
                    said = Path(path).read_text(encoding="utf-8", errors="replace")[-2000:]
                    result = {"id": test_id, "error": "the worker ended: " + said}
                with lock:
                    results[test_id] = result
                if not line:
                    break
            process.stdin.close()

    with tempfile.TemporaryDirectory() as logs:
        threads = [threading.Thread(target=work, args=(Path(logs) / ("worker-%d.log" % index),),
                                    daemon=True) for index in range(count or workers())]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    return results

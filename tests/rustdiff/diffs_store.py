"""The state store's diffs (seat S1.2, car-store): each runs the same calls through the reference tag's store
(reference.py) and through car-store (`car-harness serve`, core.py) and holds the answers and the files equal.

* SeamVocabularyDiff - the closed lists car-store's seam still carries (rust/crates/car-store/src/seam/vocab.rs: the
  policy's) against the reference's own sets, member for member and, where order means something, in order. The
  lists car-machine holds are car-machine's, held to the reference by diffs_leaves_machine.py.
* FreshStateDiff - a fresh state, and a fresh state opened by the watcher (the mark written): equal dumps.
* MigrationDiff - a state written by v0.3.2 (schema 1), v0.5.6 and v0.5.7 (schema 2), v0.6.10 (3) and
  v0.6.13 (4), each opened with migrate=True at a pinned clock: the same answer, the same dump, the same
  forensic copy; without migrate, the same UpgradePending. And a later schema: marked readable from 5 (opened,
  read by its own columns), unmarked or marked readable from 6 only (StateFromNewerVersion).
* RefusalDiff - the states the store refuses to open, refused with the same class and sentence.
* ScriptDiff - one long script of store calls - registration, claims, releases, correlation, updates, tiers,
  holds, postponements, cancels, the heartbeat, notices, usage checks, reports - each answer equal, the file
  equal; then the reference reads the file car-store wrote and car-store the reference's, and every read is
  equal (the reference reads Rust's state).
* DowngradeDiff - schema 5 to 4, 3 and 2, and the refusals: the same report, the same file.
* LegacyDiff - an older watcher's state opened as LegacyStore: the same answers, the same file.
* OpenStateDiff - openstate.open_state over its policies with a Windows stand-in: the same store opened.
* ConnectionDiff - the connection's PRAGMAs (foreign_keys, synchronous, trusted_schema, journal_mode,
  busy_timeout), on the store and on the legacy store.
* ClaimRaceDiff - two processes claim one record at the same moment, all four pairings of Python and Rust:
  exactly one wins, the other is refused submission_safe/possibly_sent, one claim in the journal.
* BusyDiff - with a write lock held elsewhere: a read does not wait, a write waits for it (BEGIN IMMEDIATE,
  busy timeout 10 s) and succeeds, and past 10 s fails "State transaction failed".

Run by run.py with diffs.py; never by the lanes' discovery (tests/rustdiff has no __init__.py).
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

import released
from rustdiff import core, reference
from rustdiff.diffs import RECORD, Base, encode, tagged

ROOT = core.ROOT
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# S2.1 moved the store seam's policy lists to car-policy, whose vocabulary is generated from the tag (gen_policy.py).
VOCAB = ROOT / "rust" / "crates" / "car-policy" / "src" / "classify" / "vocab_gen.rs"
SEAM = ROOT / "rust" / "crates" / "car-store" / "src" / "seam"

THREAD, OTHER = released.THREAD, released.OTHER
THIRD = "0a1b2c3d-0001-7000-8000-000000000003"
CLOCK = 1_700_000_000.0
N = 1_700_000_100.0


def turn(index: int) -> str:
    return released.turn(index)


def key(index: int) -> str:
    return released.key(index)


# ------------------------------------------------------------------------------------------- the dump
def _typed(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, float):
        return ["float", repr(value)]
    return [type(value).__name__, value]


def dump(path: Path) -> dict:
    """A state's shape and contents in a stable order: user_version, application_id, the journal mode, every
    schema object (type, name, table, SQL) sorted, and every table's rows by rowid with each value's type."""
    uri = "file:%s?mode=ro" % urllib.parse.quote(Path(path).as_posix(), safe="/:")
    connection = sqlite3.connect(uri, uri=True)
    try:
        answer = {name: connection.execute("PRAGMA %s" % name).fetchone()[0]
                  for name in ("user_version", "application_id", "journal_mode", "page_size", "auto_vacuum",
                               "encoding")}
        schema = sorted(list(row) for row in connection.execute(
            "SELECT type, name, tbl_name, coalesce(sql, '') FROM sqlite_master"))
        answer["schema"] = schema
        tables = {}
        for _type, name, _table, _sql in schema:
            if _type != "table":
                continue
            columns = [row[1] for row in connection.execute("PRAGMA table_info(%s)" % name)]
            tables[name] = {"columns": columns, "rows": [
                [_typed(value) for value in row]
                for row in connection.execute("SELECT * FROM %s ORDER BY rowid" % name)]}
        answer["tables"] = tables
        answer["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return answer
    finally:
        connection.close()


def backups(home: Path) -> list:
    """The forensic copies beside a state, by name with its time taken out, and each one's dump."""
    found = []
    for path in sorted(home.glob("state.v*-backup-*.sqlite")):
        name = re.sub(r"-backup-\d{8}T\d{6}Z", "-backup-<time>", path.name)
        found.append([name, dump(path)])
    return found


# ------------------------------------------------------------------------------- the reference's runner
_RUNNER = r'''
import json, sys, time, types
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
home = Path(request["home"])


def plain(value):
    if isinstance(value, tuple) or isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # bytes sort by their bytes before they are written as car-store's BLOB value
        return [plain(item) for item in sorted(value)]
    if isinstance(value, dict):
        return {name: plain(item) for name, item in value.items()}
    if isinstance(value, bytes):
        # a BLOB, as car-store's value.rs carries it: {"\u0000bytes": hex}
        return {"\x00bytes": value.hex()}
    return value


def raised(exc):
    return {"raised": type(exc).__name__, "message": str(exc)}


def wait_for_go():
    if request.get("ready"):
        Path(request["ready"]).write_text("ready")
    if request.get("go"):
        started = time.time()
        while not Path(request["go"]).exists() and time.time() - started < 120:
            time.sleep(0.001)


def operate(store, op):
    method, args, kwargs = op["method"], op.get("args", []), dict(op.get("kwargs", {}))
    if method == "pragma":
        return store._connection.execute("PRAGMA %s" % args[0]).fetchone()[0]
    if method == "version":
        return store.version
    if method == "submission_guard":
        with store.submission_guard(*args) as permitted:
            return permitted
    if method == "heartbeat" and isinstance(kwargs.get("usage"), list):
        kwargs["usage"] = tuple(kwargs["usage"])
    for name in ("resend", "caps"):
        if isinstance(kwargs.get(name), list):
            kwargs[name] = tuple(kwargs[name])
    return getattr(store, method)(*args, **kwargs)


def run_ops(store):
    results = []
    for op in request.get("ops", []):
        started = time.perf_counter()
        try:
            value = plain(operate(store, op))
        except Exception as exc:
            value = raised(exc)
        if op.get("timed"):
            value = {"value": value, "seconds": time.perf_counter() - started}
        results.append(value)
    return results


kind = request["kind"]
if kind == "script":
    from codex_auto_resume.store import Store
    opening = request.get("open", {})
    clock = opening.get("clock")
    try:
        store = Store(home, migrate=opening.get("migrate", False), check=opening.get("check", True),
                      clock=(lambda: clock) if clock is not None else time.time)
    except Exception as exc:
        print(json.dumps({"open": raised(exc), "migrated_from": None, "results": []}, ensure_ascii=False))
        raise SystemExit(0)
    with store:
        answer = {"open": None, "migrated_from": store.migrated_from}
        wait_for_go()
        answer["results"] = run_ops(store)
    print(json.dumps(answer, ensure_ascii=False))
elif kind == "legacy":
    from codex_auto_resume.store import LegacyStore
    try:
        store = LegacyStore(home)
    except Exception as exc:
        print(json.dumps({"open": raised(exc), "results": []}, ensure_ascii=False))
        raise SystemExit(0)
    with store:
        print(json.dumps({"open": None, "results": run_ops(store)}, ensure_ascii=False))
elif kind == "downgrade":
    from codex_auto_resume.store import downgrade_state
    now = request["now"]
    time.time = lambda: now
    try:
        value = plain(downgrade_state(home, request["target"]))
    except Exception as exc:
        value = raised(exc)
    print(json.dumps(value, ensure_ascii=False))
elif kind == "open_state":
    from codex_auto_resume import openstate
    from codex_auto_resume.store import LegacyStore
    mutex_free, install = request.get("mutex_free", False), request.get("install_in_progress")

    class StandIn:
        def __init__(self, name, timeout=0.0):
            if not mutex_free:
                raise openstate.AdapterError("held")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    openstate.Mutex = StandIn
    openstate.windows = types.SimpleNamespace(install_in_progress=lambda: install)
    if request.get("clock") is not None:
        pinned, opened_with = request["clock"], openstate.Store
        openstate.Store = lambda *args, **keywords: opened_with(*args, clock=lambda: pinned, **keywords)
    keywords = {name: request[name] for name in ("legacy", "reducing", "check", "hold_while_installing")
                if name in request}
    if "superseded" in request:
        keywords["superseded"] = lambda: request["superseded"]
    try:
        opened = openstate.open_state(home, **keywords)
        value = {"opened": "LegacyStore" if isinstance(opened, LegacyStore) else "Store",
                 "version": opened.version if isinstance(opened, LegacyStore) else opened.schema_version()}
        opened.close()
    except Exception as exc:
        value = raised(exc)
    print(json.dumps(value, ensure_ascii=False))
'''


def reference_call(kind: str, home: Path, profile: Path, **request) -> bytes:
    """Run one request through the reference tag's store; its stdout, the JSON value, as bytes."""
    request = dict(request, kind=kind, home=str(home))
    path = profile / ("request-%d.json" % time.perf_counter_ns())
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    done = reference.run(_RUNNER, path, profile=profile)
    if done.returncode != 0:
        raise AssertionError("the reference failed:\n%s" % done.stderr.decode("utf-8", "replace")[-3000:])
    return done.stdout


def reference_process(kind: str, home: Path, profile: Path, **request) -> subprocess.Popen:
    """The same, started and not waited for (the claim race)."""
    request = dict(request, kind=kind, home=str(home))
    path = profile / ("request-%d.json" % time.perf_counter_ns())
    path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    source = released.package(reference.TAG)
    environment = reference.scratch_environment(profile, PYTHONPATH=str(source))
    return subprocess.Popen(reference.command(_RUNNER, path, paths=[source]), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=environment, cwd=str(profile), creationflags=NO_WINDOW)


CALLS = {"script": "store.script", "legacy": "store.legacy", "downgrade": "store.downgrade",
         "open_state": "store.open_state"}


class StoreBase(Base):
    def setUp(self):
        super().setUp()
        self.harness = core.Harness(reference.scratch_environment(self.profile("rust-profile"))).__enter__()
        self.addCleanup(self.harness.__exit__, None, None, None)
        self.reference_profile = self.profile("reference-profile")

    def home(self, name: str) -> Path:
        folder = self.scratch / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def both(self, kind: str, homes: tuple, label: str = "", **request):
        """The request through both: (the reference's value, car-store's value), held byte for byte equal."""
        theirs, mine = homes
        expected = reference_call(kind, theirs, self.reference_profile, **request).decode("utf-8").strip()
        value = json.loads(expected)
        # A NaN or an infinity goes to car-harness as its {"$float": ...} tag (diffs.TAGGING); the reference reads it
        # from its request file with json.loads, which takes NaN as it is.
        number, line = self.harness.call(CALLS[kind], home=str(mine), **tagged(request))
        reply = json.loads(line)
        if reply.get("reply", {}).get("ok") is not True:
            self.fail("car-harness refused %s: %s" % (kind, line[-2000:]))
        wanted = encode({"id": number, "reply": {"ok": True, "value": json.loads(
            expected.replace(json.dumps(str(theirs))[1:-1], json.dumps(str(mine))[1:-1]))}})
        if line != wanted:
            self.report_difference(label or kind, value, reply["reply"]["value"])
        return value, reply["reply"]["value"]

    def report_difference(self, label, theirs, mine):
        if isinstance(theirs, dict) and isinstance(mine, dict) and "results" in theirs and "results" in mine:
            for name in ("open", "migrated_from"):
                if theirs.get(name) != mine.get(name):
                    self.fail("%s: %s differs: reference %r, rust %r" % (label, name, theirs.get(name), mine.get(name)))
            for index, (a, b) in enumerate(zip(theirs["results"], mine["results"])):
                if json.dumps(a, ensure_ascii=False) != json.dumps(b, ensure_ascii=False):
                    self.fail("%s: op %d (%s) differs:\nreference %s\nrust      %s" % (
                        label, index, self.ops[index]["method"] if getattr(self, "ops", None) else "?",
                        json.dumps(a, ensure_ascii=False)[:3000], json.dumps(b, ensure_ascii=False)[:3000]))
        self.fail("%s differs:\nreference %s\nrust      %s" % (label, json.dumps(theirs, ensure_ascii=False)[:4000],
                                                         json.dumps(mine, ensure_ascii=False)[:4000]))

    def same_files(self, theirs: Path, mine: Path, label: str):
        a, b = dump(theirs / "state.sqlite"), dump(mine / "state.sqlite")
        if a != b:
            for part in a:
                if a[part] != b.get(part):
                    if part == "tables":
                        for table in a[part]:
                            if a[part][table] != b[part].get(table):
                                self.fail("%s: table %s differs:\nreference %s\nrust      %s" % (
                                    label, table, json.dumps(a[part][table])[:3000],
                                    json.dumps(b[part].get(table))[:3000]))
                    self.fail("%s: %s differs:\nreference %s\nrust      %s" % (label, part, json.dumps(a[part])[:3000],
                                                                            json.dumps(b.get(part))[:3000]))
        self.assertEqual(backups(theirs), backups(mine), "%s: the forensic copies differ" % label)
        return a


def edit(path: Path, *statements: str) -> None:
    """Statements run on a state file outside any store, each committed on its own."""
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        for statement in statements:
            db.execute(statement)


def edit_state(path: Path, script: str) -> None:
    """A script run on a state file outside any store."""
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.executescript(script)


def query(path: Path, statement: str):
    with closing(sqlite3.connect(path)) as db:
        return db.execute(statement).fetchone()


def twin(source: Path, a: Path, b: Path):
    for target in (a, b):
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / "state.sqlite")


# ------------------------------------------------------------------------------------------ the diffs
ORDERED = {"GATES", "WATCHER_ENDS", "EARLY_STATES"}
# What moved to car-machine (S1.1): the store reads these through car_machine::vocab_gen, no copy of its own.
MACHINE_OWNED = {"STATES", "WAITING", "CLAIMED", "IN_FLIGHT", "OBSERVING", "OUTCOMES", "EXHAUSTED", "TERMINAL",
                 "V2_STATES", "WATCHED", "EVENT_CODES", "REASONS", "ACTORS", "TURN_STATUSES", "WITHDRAW_REASONS",
                 "RELEASABLE_WITHDRAWALS", "HOLDS", "IMPORTANCE_TIERS", "HOME_STATES", "ENGINE_STATES",
                 "USAGE_BUCKETS", "USAGE_SLOTS", "USAGE_KEYS", "PLAIN_MOVES",
                 # car-machine's WatcherEnd enum (S2.1: car-store reads it as words through machine.rs).
                 "WATCHER_ENDS"}
VOCAB_SOURCES = r'''
import json
from codex_auto_resume import failures, ladder, machine, needsyou
from codex_auto_resume.domain import usage
from codex_auto_resume.domain.vocabulary import EngineState, WatcherEnd
from codex_auto_resume.domain.states import PLAIN_MOVES
lists = {name: list(getattr(machine, name)) for name in (
    "STATES", "WAITING", "CLAIMED", "IN_FLIGHT", "OBSERVING", "OUTCOMES", "EXHAUSTED", "TERMINAL", "V2_STATES",
    "WATCHED", "EVENT_CODES", "REASONS", "ACTORS", "TURN_STATUSES", "WITHDRAW_REASONS", "RELEASABLE_WITHDRAWALS",
    "HOLDS", "IMPORTANCE_TIERS", "HOME_STATES", "GATE_RESULTS", "GATES", "GATE_REASONS", "RESENDABLE", "FORCEABLE")}
lists.update(CATEGORIES=list(failures.CATEGORIES), TRANSIENT=list(failures.TRANSIENT),
             ADMISSIBLE=list(failures.ADMISSIBLE), NOTICE_KINDS=list(needsyou.NOTICE_KINDS),
             ENGINE_STATES=list(EngineState), WATCHER_ENDS=list(WatcherEnd), USAGE_BUCKETS=list(usage.BUCKETS),
             USAGE_SLOTS=list(usage.SLOTS), USAGE_KEYS=list(usage.KEYS), EARLY_STATES=list(ladder.EARLY_STATES))
lists["PLAIN_MOVES"] = {state: sorted(moves) for state, moves in PLAIN_MOVES.items()}
print(json.dumps(lists))
'''


class SeamVocabularyDiff(Base):
    def test_seam_lists_are_the_references(self):
        done = reference.run(VOCAB_SOURCES, profile=self.profile("reference"))
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        theirs = json.loads(done.stdout)
        source = VOCAB.read_text(encoding="utf-8")
        mine = {name: re.findall(r'"([^"]*)"', body)
                for name, body in re.findall(r"pub const (\w+): &\[&str\] =\s*&\[(.*?)\];", source, re.S)}
        for name, values in theirs.items():
            if name in MACHINE_OWNED:
                # car-machine's: no copy in the store (the seam is gone but python.rs), held by diffs_leaves_machine.
                continue
            self.assertIn(name, mine, name)
            if name in ORDERED:
                self.assertEqual(mine[name], [str(value) for value in values], name)
            else:
                self.assertEqual(sorted(mine[name]), sorted(str(value) for value in values), name)
        self.assertEqual(sorted(path.name for path in SEAM.iterdir()), ["mod.rs", "python.rs"],
                         "car-store's seam holds only CPython's readings now; the policy is car-policy's")
        RECORD.append("store seam: gone but python.rs; the policy's %d closed lists car-policy's, equal to %s's; "
                      "%d lists are car-machine's" % (len(theirs) - len(MACHINE_OWNED), reference.TAG,
                                                      len(MACHINE_OWNED) - 1))


class FreshStateDiff(StoreBase):
    def test_fresh_and_marked(self):
        for migrate in (False, True):
            with self.subTest(migrate=migrate):
                theirs, mine = self.home("ref-%s" % migrate), self.home("rust-%s" % migrate)
                ops = [{"method": name} for name in ("schema_version", "readable_from", "settings")]
                self.both("script", (theirs, mine), open={"migrate": migrate, "clock": CLOCK}, ops=ops)
                shape = self.same_files(theirs, mine, "fresh (migrate=%s)" % migrate)
                self.assertEqual(shape["user_version"], 5)
                # Reopened by the other: equal again.
                self.both("script", (mine, theirs), open={"migrate": True, "clock": CLOCK}, ops=ops)
                self.same_files(theirs, mine, "fresh reopened")
        RECORD.append("fresh state: created and marked by car-store, the same file as %s's (schema 5, mark 0x%08x)"
                      % (reference.TAG, shape["application_id"]))


def _old_store(tag, folder: Path) -> Path:
    """A state written by a tagged single-file store (v0.3.2, v0.5.6, v0.5.7), as test_store's T37 writes it."""
    import test_store
    module = test_store._tagged_store(tag, folder)
    root = folder / ("fixture-" + tag)
    try:
        test_store.build_old_state(module, root)
    finally:
        sys.modules.pop(module.__name__, None)
    return root / "state.sqlite"


def _released_store(tag, folder: Path, profile: Path) -> Path:
    """A state written by a tagged package store (v0.6.10, v0.6.13): one record in every state it knew."""
    root = folder / ("fixture-" + tag)
    made = reference.run(released._WRITE_STATE, root, THREAD, OTHER, profile=profile, tag=tag)
    if made.returncode != 0:
        raise AssertionError("%s's store failed:\n%s" % (tag, made.stderr[-3000:]))
    return root / "state.sqlite"


READS = [{"method": name} for name in ("schema_version", "readable_from", "settings", "all_records",
                                       "status_counts", "failure_marks", "thread_tiers", "disabled_threads",
                                       "home_keys", "statistics", "watcher_status")] + [
    {"method": "events", "kwargs": {"limit": 5000}}, {"method": "history", "kwargs": {"include_hidden": True}},
    {"method": "usage_checks_shown", "args": [0.0]}]


class MigrationDiff(StoreBase):
    FIXTURES = (("v0.3.2", 1), ("v0.5.6", 2), ("v0.5.7", 2), ("v0.6.10", 3), ("v0.6.13", 4))

    def test_every_old_schema_migrates_to_the_same_file(self):
        fixtures = self.scratch / "fixtures"
        fixtures.mkdir()
        made = []
        for tag, version in self.FIXTURES:
            with self.subTest(tag=tag):
                source = (_old_store(tag, fixtures) if version <= 2
                          else _released_store(tag, fixtures, self.profile("writer-" + tag)))
                self.assertEqual(query(source, "PRAGMA user_version")[0], version)
                # Without migrate: the same refusal, the file untouched.
                theirs, mine = self.home("pending-ref-" + tag), self.home("pending-rust-" + tag)
                twin(source, theirs, mine)
                answer, _ = self.both("script", (theirs, mine), open={"clock": CLOCK}, ops=[])
                self.assertEqual(answer["open"]["raised"], "UpgradePending")
                self.same_files(theirs, mine, tag + " pending")
                # With migrate, as the watcher: the same upgrade, the same reads after it.
                theirs, mine = self.home("ref-" + tag), self.home("rust-" + tag)
                twin(source, theirs, mine)
                self.ops = READS
                answer, _ = self.both("script", (theirs, mine), label=tag, open={"migrate": True, "clock": CLOCK},
                                      ops=READS)
                self.assertIsNone(answer["open"], answer)
                self.assertEqual(answer["migrated_from"], version)
                shape = self.same_files(theirs, mine, tag)
                self.assertEqual(shape["user_version"], 5)
                self.assertEqual(len(backups(mine)), 1)
                made.append("%s (schema %d, %d records)" % (tag, version, len(shape["tables"]["interruptions"]["rows"])))
        RECORD.append("migrations: %s each upgraded to the same schema-5 file, the same forensic copy and the same "
                      "%d reads; the same UpgradePending without migrate" % (", ".join(made), len(READS)))

    def test_later_schemas(self):
        """READABLE_FROM: a schema 6 marked readable from 5 is used as it is; unmarked, or marked readable from 6, it
        is refused as newer."""
        seed = self.home("seed")
        reference_call("script", seed, self.reference_profile, open={"clock": CLOCK}, ops=[
            {"method": "set_enabled", "args": [True, N]},
            {"method": "register", "args": [record(0), N]}])
        cases = {"marked-5": 0x43410000 | 6 << 8 | 5, "unmarked": 0, "marked-6": 0x43410000 | 6 << 8 | 6,
                 "mark-of-5": 0x43410000 | 5 << 8 | 5}
        for name, mark in cases.items():
            with self.subTest(case=name):
                source = self.home("later-" + name) / "state.sqlite"
                shutil.copyfile(seed / "state.sqlite", source)
                edit(source, "ALTER TABLE interruptions ADD COLUMN later TEXT DEFAULT 'x'",
                     "ALTER TABLE notices ADD COLUMN later INTEGER DEFAULT 0", "PRAGMA user_version=6",
                     "PRAGMA application_id=%d" % mark)
                theirs, mine = self.home("ref-later-" + name), self.home("rust-later-" + name)
                twin(source, theirs, mine)
                for migrate in (False, True):
                    answer, _ = self.both("script", (theirs, mine), label="later " + name,
                                          open={"migrate": migrate, "clock": CLOCK},
                                          ops=[{"method": "all_records"}, {"method": "readable_from"},
                                               {"method": "update", "args": [key(0)], "kwargs": {"retry_count": 1}}])
                    self.assertEqual(answer["open"] is None, name == "marked-5", answer["open"])
                self.same_files(theirs, mine, "later " + name)
        RECORD.append("readable-from: a schema 6 marked readable from 5 opened and written alike; unmarked, marked "
                      "from 6 or with schema 5's mark, StateFromNewerVersion alike")


class RefusalDiff(StoreBase):
    def test_refused_alike(self):
        seed = self.home("seed")
        reference_call("script", seed, self.reference_profile, open={"clock": CLOCK}, ops=[])
        edits = {
            "empty-file": None,
            "bad-settings": "UPDATE settings SET poll_seconds=1",
            "extra-table": "CREATE TABLE extra (x)",
            "a-trigger": "CREATE TRIGGER t AFTER INSERT ON threads BEGIN SELECT 1; END",
            "bad-record": ("INSERT INTO interruptions (interruption_id, thread_id, turn_id, completed_at, ordinal, "
                           "detected_at, uncertain, state, retry_count, next_retry_at, marker, attempt_count, "
                           "cancel_requested) VALUES ('k', 'not-a-uuid', 't', 1, 0, 1, 0, 'waiting_poll', 0, 1, 'm', 0, 0)"),
            "bad-tier": "INSERT INTO threads VALUES ('%s', 1, 'sometimes')" % THREAD,
            "column-dropped": "ALTER TABLE notices DROP COLUMN seen_at",
            "old-unknown": "PRAGMA user_version=0",
        }
        for name, change in edits.items():
            with self.subTest(case=name):
                source = self.home("src-" + name) / "state.sqlite"
                if change is None:
                    source.write_bytes(b"")
                else:
                    shutil.copyfile(seed / "state.sqlite", source)
                    edit_state(source, change)
                theirs, mine = self.home("ref-" + name), self.home("rust-" + name)
                twin(source, theirs, mine)
                for check in (True, False):
                    answer, _ = self.both("script", (theirs, mine), label=name, open={"check": check, "clock": CLOCK},
                                          ops=[{"method": "all_records"}])
                if change is not None:
                    self.same_files(theirs, mine, name)
        RECORD.append("refusals: %d broken states refused with the same class and sentence, check on and off"
                      % len(edits))


def record(index: int, category: str = "usage_limit", reset_at=None, thread: str = THREAD, turn_index=None,
           ordinal=None) -> dict:
    return {"thread_id": thread, "turn_id": turn(index if turn_index is None else turn_index), "completed_at": 110.0,
            "started_at": 105.0, "ordinal": index if ordinal is None else ordinal, "interruption_id": key(index),
            "reset_at": reset_at, "limit_type": "x", "uncertain": False, "category": category}


LIMITS = {"max_no_progress": 3, "max_chain_continuations": 6, "max_recovery_attempts": 4}
GATES = {"engine_compatible": ["PASS", "ok"], "single_owner": ["PASS", "ok"], "identity": ["PASS", "ok"],
         "known_failure": ["PASS", "ok"], "thread_available": ["PASS", "ok"], "no_newer_user_work": ["PASS", "ok"],
         "usage": ["PASS", "ok"]}
WINDOWS = [{"bucket": "codex", "window": "primary", "used_percent": 42.5, "window_minutes": 300,
            "reset_at": 1700003600}]
QUEUE = "0a1b2c3d-0003-7000-8000-000000000001"
OTHER_HOME = "b" * 64


def op(method, *args, **kwargs):
    entry = {"method": method}
    if args:
        entry["args"] = list(args)
    if kwargs:
        entry["kwargs"] = kwargs
    return entry


def script_ops() -> list:
    """One long script through most of the store: each answer and the file it leaves are compared."""
    return [
        op("settings"), op("set_enabled", True, N), op("set_enabled", True, N + 1), op("set_enabled", "yes", N),
        op("set_observe_only", False), op("schema_version"), op("readable_from"),
        op("register", record(0, "server_5xx"), N), op("register", record(0, "server_5xx"), N),
        op("register", record(0, "server_5xx", ordinal=9), N),
        op("register", record(1, "usage_limit", reset_at=N + 500), N, state="waiting_reset"),
        op("register", record(2, "server_5xx"), N, limits=LIMITS, next_retry_at=N + 30),
        op("register", record(3, "server_5xx", turn_index=2), N),
        op("register", record(4, "unknown"), N), op("register", record(5), N, state="submitting"),
        op("register", {"thread_id": THREAD}, N), op("register", record(6), -5.0),
        op("reserve_detailed", key(0), N + 10), op("reserve_detailed", key(0), N + 11),
        op("reserve_detailed", key(2), N + 12, limits=LIMITS, gates=GATES),
        op("reserve_detailed", key(4), N + 13),
        op("reserve_detailed", key(2), N + 12, gates=GATES),
        op("reserve_detailed", "f" * 64, N + 12),
        op("submission_guard", key(0)),
        op("release_claim", key(0), "waiting_backoff", "queue_process_not_started", N + 14),
        op("release_claim", key(0), "waiting_backoff", "queue_process_not_started", N + 14),
        op("release_claim", key(0), "turn_started", "x", N + 14),
        op("reserve_detailed", key(4), N + 15), op("reserve_detailed", key(4), N + 15, relaxed="admitted"),
        op("reserve_detailed", key(2), N + 40, limits=LIMITS, gates=GATES, caps=[1, 3600]),
        op("reserve", key(0), N + 16, caps=[10, 1]),
        op("others_in_flight", THREAD, key(2)),
        op("recent_claims", THREAD, 0.0), op("recent_claim_count", THREAD, 0.0),
        op("update", key(0), state="queued", queue_id=QUEUE),
        op("update", key(0), state="queued", queue_id=None),
        op("update", key(0), bogus=1),
        op("correlate", key(0), turn(100), N + 20, client_id="abc-1", status="inProgress"),
        op("correlate", key(1), turn(100), N + 21),
        op("correlate", key(2), "not-a-uuid", N + 21),
        op("update", key(0), state="turn_completed", at=N + 22),
        op("update", key(0), state="recovered", outcome_at=N + 30, event="outcome", at=N + 30),
        op("update", key(0), state="waiting_poll"),
        op("update", key(0), recovery_turn_id=turn(101)),
        op("register", record(7, turn_index=100), N + 31, owner_id=key(0), failed_turn_progress=False, limits=LIMITS),
        op("get", key(7)), op("chain_parent", THREAD, turn(100), key(0)),
        op("set_thread_tier", THREAD, "ask_first", N + 32), op("thread_tiers"), op("thread_tier", THREAD),
        op("release_hold", key(1), THREAD, N + 33), op("release_hold", key(1), THREAD, N + 33),
        op("release_hold", key(1), OTHER, N + 33),
        op("postpone", key(1), THREAD, N + 3600, N + 34), op("postpone", key(1), THREAD, N + 100, N + 35),
        op("postpone", key(1), THREAD, N + 10 ** 7, N + 35), op("postpone", key(1), THREAD, "soon", N + 35),
        op("unpostpone", key(1), THREAD, N + 36), op("unpostpone", key(1), THREAD, N + 36),
        op("open_objection_window", key(2), N + 600, N + 37), op("open_objection_window", key(2), N + 700, N + 37),
        op("request_retry_now", key(1), N + 38), op("request_retry_now", key(0), N + 38),
        op("request_retry_now", key(2), N + 38),
        op("set_thread_tier", THREAD, None, N + 39),
        op("hold_waiting", [key(1), key(1), key(2)], "ask", N + 39), op("hold_waiting", [key(1)], "nope", N + 39),
        op("hold_changed", key(1), "c" * 64, N + 39), op("hold_changed", key(1), "short", N + 39),
        op("hide_history", N + 40),
        op("register", record(8, "server_5xx", thread=OTHER), N + 40),
        op("cancel_thread", OTHER, N + 42), op("set_thread_enabled", OTHER, True, at=N + 43),
        op("set_thread_enabled", OTHER, True), op("thread_enabled", OTHER), op("disabled_threads"),
        op("enrol_conversation", THIRD, "objection_window", N + 44),
        op("enrol_conversation", THIRD, "objection_window", N + 44), op("enrol_conversation", THIRD, None, N + 44),
        op("heartbeat", N + 45, pid=1234, session_id="s1", started_at=N, ok=True, engine_state="verified",
           code_version="0.6.26", usage=[N + 45, WINDOWS], awake_since=N, memory_peak=1000,
           sign_in="0123456789abcdef", booted_at=N - 100,
           homes=[{"key": "", "state": "watched"}, {"key": OTHER_HOME, "state": "lock_busy"}]),
        op("watcher_status"),
        op("heartbeat", N + 46, pid=1234, session_id="s1" * 40, started_at="x", ok=0, engine_state="what",
           code_version="v", usage=None, homes=[{"key": "", "state": "watched"}]),
        op("watcher_status"), op("watcher_ended", N + 46, "clean"), op("watcher_ended", N + 46, "running"),
        op("watcher_status"),
        op("raise_notice", key(4), THREAD, "terminal_failure", N + 47),
        op("raise_notice", key(4), THREAD, "terminal_failure", N + 47),
        op("raise_notice", key(4), THREAD, "whatever", N + 47),
        op("ask_usage_check", key(1), N + 48), op("ask_usage_check", key(2), N + 48, source="rescan"),
        op("ask_usage_check", "short", N + 48), op("usage_checks_asked", N + 48),
        op("usage_check_taken", key(1)), op("usage_check_taken", key(1)),
        op("usage_not_checked", key(2), N + 49, "paused"), op("usage_not_checked", key(1), N + 49, "nope"),
        op("usage_checked", key(1), N + 50, "usage_available"), op("usage_checked", key(1), N + 51, "odd"),
        op("usage_checks_shown", 0.0),
        op("ask_early_check", N + 52), op("early_check_asked", N + 53), op("early_check_asked", N + 900),
        op("early_check_taken"),
        op("record_gates", key(1), GATES, N + 54), op("record_would_send", key(1), GATES, N + 55, N + 60),
        op("record_would_send", key(1), GATES, N + 56, N + 60),
        op("register", record(9), N + 57, limits={"max_no_progress": 0, "max_chain_continuations": 6,
                                                   "max_recovery_attempts": 4}),
        op("restore_budget_detailed", key(9), N + 58), op("restore_budget_detailed", key(9), N + 58),
        op("restore_budget", key(1), N + 58),
        op("rescan_apply", key(1), {}, "rechecked", N + 59), op("rescan_apply", key(1), {}, "gone", N + 59),
        op("register", record(10), N + 60, home_key=OTHER_HOME), op("home_keys"),
        op("records_in", ["waiting_reset", "waiting_poll", "nonsense"], home_key=OTHER_HOME),
        op("cancel_home", OTHER_HOME, N + 61, "home_removed"), op("cancel_home", "", N + 61, "x"),
        op("register", record(11, "server_5xx"), N + 62), op("reserve", key(11), N + 63),
        op("update", key(11), state="queued", queue_id="0a1b2c3d-0003-7000-8000-000000000002"),
        op("update", key(11), state="withdrawn_unconfirmed", withdraw_reason="paused", withdrawn_at=N + 64,
           withdraw_deleted=True),
        op("release_withdrawn", key(11), N + 65, window=10, later_turn=False, marker_rows=0, row_present=False,
           fresh=True, target="waiting_retry"),
        op("release_withdrawn", key(11), N + 80, window=10, later_turn=False, marker_rows=0, row_present=False,
           fresh=True, target="waiting_retry"),
        op("cancel_waiting", [key(11), key(1), 5], N + 81, "kind_off"),
        op("cancel_interruption", key(2), N + 82), op("cancel_interruption", key(7), N + 82),
        op("cancel_interruption", "f" * 64, N + 82),
        op("claimed_on_thread", THREAD), op("pending"), op("status_counts"), op("statistics"),
        op("statistics", N, N + 50), op("failure_marks"), op("history", include_hidden=True, limit=3),
        op("history"), op("all_records"), op("events", limit=5000), op("events", key(0)),
        op("events", chain_origin_id=key(0)),
    ]


class ScriptDiff(StoreBase):
    def test_the_same_writes_and_each_reads_the_others(self):
        theirs, mine = self.home("ref"), self.home("rust")
        self.ops = script_ops()
        answer, _ = self.both("script", (theirs, mine), label="script", open={"clock": CLOCK}, ops=self.ops)
        self.assertIsNone(answer["open"])
        shape = self.same_files(theirs, mine, "script")
        refused = sum(1 for value in answer["results"] if isinstance(value, dict) and "raised" in value)
        # The reference reads Rust's state, and car-store the reference's: every read equal.
        self.ops = READS
        for migrate in (False, True):
            self.both("script", (mine, theirs), label="cross read", open={"check": True, "migrate": migrate,
                                                                          "clock": CLOCK}, ops=READS)
            self.same_files(theirs, mine, "after the cross read")
        RECORD.append("script: %d store calls (%d refused alike) gave equal answers and the same file (%d records, %d "
                      "journal entries); %s's store read car-store's file and car-store the reference's, %d reads "
                      "equal" % (len(answer["results"]), refused, len(shape["tables"]["interruptions"]["rows"]),
                                 len(shape["tables"]["events"]["rows"]), reference.TAG, len(READS)))

    def test_the_journal_is_pruned_alike(self):
        """Every 256th entry prunes: first by age (300 entries a day apart), then by count (5,200 at one time, past
        EVENT_LIMIT) - entries of no record, so nothing running keeps them."""
        theirs, mine = self.home("ref"), self.home("rust")
        tiers = ("automatic", "objection_window")
        ops = [op("set_thread_tier", THIRD, tiers[index % 2], N + 86400 * index) for index in range(300)]
        ops += [op("set_thread_tier", THIRD, tiers[index % 2], N + 86400 * 400) for index in range(1, 5201)]
        ops += [op("events", limit=5000)]
        self.ops = ops
        self.both("script", (theirs, mine), label="prune", open={"clock": CLOCK}, ops=ops)
        shape = self.same_files(theirs, mine, "prune")
        events = shape["tables"]["events"]["rows"]
        self.assertLess(len(events), 5500 - 100)
        RECORD.append("journal: 5,500 entries pruned by age and by count to the same %d (first kept id %s)"
                      % (len(events), events[0][0][1]))


def _rich_state(home: Path, profile: Path) -> None:
    """A schema-5 state for the downgrade: records in every state, short markers, holds, tiers, a postponement,
    notices, observe only, withdrawals with schema-5 words, and records of another Codex home."""
    script = r'''
import json, sqlite3, sys
from pathlib import Path
from codex_auto_resume import machine
from codex_auto_resume.store import Store
root, thread, other, now, home, extra = Path(sys.argv[1]), sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5], sys.argv[6]
turn = lambda index: "0a1b2c3d-0002-7000-8000-%012d" % index
key = lambda index: ("%02x" % (index + 1)) * 32
states = sorted(machine.STATES)
with Store(root, clock=lambda: now) as store:
    store.set_enabled(True, now)
    for index, state in enumerate(states):
        store.register({"thread_id": thread, "turn_id": turn(index), "completed_at": 110.0, "started_at": 105.0,
                        "ordinal": index, "interruption_id": key(index), "reset_at": None, "limit_type": "x",
                        "uncertain": False, "category": "server_5xx"}, now)
    for index in range(len(states), len(states) + 3):
        store.register({"thread_id": other, "turn_id": turn(index), "completed_at": 110.0, "started_at": 105.0,
                        "ordinal": index, "interruption_id": key(index), "reset_at": None, "limit_type": "x",
                        "uncertain": False}, now, home_key=home if index > len(states) else "", hold="ask")
    store.set_thread_tier(extra, "notify_only", now)
    store.postpone(key(0), thread, now + 3600, now)
    store.raise_notice(key(1), thread, "terminal_failure", now)
    store.set_observe_only(True)
db = sqlite3.connect(root / "state.sqlite")
for index, state in enumerate(states):
    db.execute("UPDATE interruptions SET state=?, submitted_at=?, recovery_turn_id=?, withdraw_reason=?, "
               "withdrawn_at=?, cancel_requested=?, last_error=? WHERE interruption_id=?",
               (state, None if state in machine.WAITING else 101.0,
                None if state in machine.WAITING else turn(100 + index),
                "window_ended" if state == "withdrawn_unconfirmed" else None,
                101.0 if state == "withdrawn_unconfirmed" else None,
                1 if state == "cancelled" else 0,
                "observe_only" if state == "waiting_retry" else None, key(index)))
db.execute("UPDATE interruptions SET marker='[codex-auto-resume:' || interruption_id || ']' WHERE interruption_id=?",
           (key(1),))
db.commit()
db.close()
print("{}")
'''
    done = reference.run(script, home, THREAD, OTHER, N, OTHER_HOME, THIRD, profile=profile)
    if done.returncode != 0:
        raise AssertionError("the reference could not write the state:\n%s" % done.stderr[-3000:])


class DowngradeDiff(StoreBase):
    def test_downgrades_alike(self):
        seed = self.home("seed")
        _rich_state(seed, self.reference_profile)
        cases = 0
        for target in (4, 3, 2):
            with self.subTest(target=target):
                theirs, mine = self.home("ref-%d" % target), self.home("rust-%d" % target)
                twin(seed / "state.sqlite", theirs, mine)
                self.both("downgrade", (theirs, mine), label="downgrade to %d" % target, target=target, now=N + 500)
                self.same_files(theirs, mine, "downgrade to %d" % target)
                cases += 1
                # Again: nothing to do, alike.
                self.both("downgrade", (theirs, mine), label="again to %d" % target, target=target, now=N + 600)
                self.same_files(theirs, mine, "downgrade again to %d" % target)
        # A record of another home still in its queue refuses it; a bad target; a schema-2 state.
        edit(seed / "state.sqlite", "UPDATE interruptions SET state='queued', submitted_at=101.0 WHERE home_key<>''")
        theirs, mine = self.home("ref-busy"), self.home("rust-busy")
        twin(seed / "state.sqlite", theirs, mine)
        for target in (4, 7):
            self.both("downgrade", (theirs, mine), label="refused to %d" % target, target=target, now=N + 700)
        self.same_files(theirs, mine, "a refused downgrade")
        theirs, mine = self.home("ref-two"), self.home("rust-two")
        twin(self.home("ref-2") / "state.sqlite", theirs, mine)
        edit(theirs / "state.sqlite", "PRAGMA user_version=1")
        shutil.copyfile(theirs / "state.sqlite", mine / "state.sqlite")
        self.both("downgrade", (theirs, mine), label="schema 1 to 3", target=3, now=N)
        self.both("downgrade", (self.home("ref-none"), self.home("rust-none")), label="no state", target=3, now=N)
        RECORD.append("downgrade: a rich schema-5 state to 4, 3 and 2 gave the same report and file, again a no-op "
                      "alike; another home's queued record, a bad target and a missing state refused alike")


class LegacyDiff(StoreBase):
    def test_older_watchers_states(self):
        fixtures = self.scratch / "fixtures"
        fixtures.mkdir()
        sources = [("v0.5.7", _old_store("v0.5.7", fixtures)),
                   ("v0.6.10", _released_store("v0.6.10", fixtures, self.profile("writer-v0.6.10"))),
                   ("v0.6.13", _released_store("v0.6.13", fixtures, self.profile("writer-v0.6.13")))]
        ops = [op("version"), op("settings"), op("pragma", "foreign_keys"), op("pragma", "busy_timeout"),
               op("pragma", "trusted_schema"), op("status_counts"), op("disabled_threads"),
               op("thread_enabled", THREAD), op("thread_enabled", "nope"), op("set_enabled", False, N),
               op("set_enabled", True, N + 1), op("set_thread_enabled", OTHER, True), op("thread_of", key(0)),
               op("thread_of", "missing"), op("cancel_thread", THREAD, N + 2), op("status_counts"),
               op("disabled_threads"), op("settings")]
        self.ops = ops
        for tag, source in sources:
            with self.subTest(tag=tag):
                theirs, mine = self.home("ref-" + tag), self.home("rust-" + tag)
                twin(source, theirs, mine)
                self.both("legacy", (theirs, mine), label="legacy " + tag, ops=ops)
                self.same_files(theirs, mine, "legacy " + tag)
        theirs, mine = self.home("ref-current"), self.home("rust-current")
        reference_call("script", theirs, self.reference_profile, open={"clock": CLOCK}, ops=[])
        shutil.copyfile(theirs / "state.sqlite", mine / "state.sqlite")
        self.both("legacy", (theirs, mine), label="legacy of a current state", ops=ops)
        self.both("legacy", (self.home("ref-none"), self.home("rust-none")), label="legacy of nothing", ops=ops)
        RECORD.append("legacy store: v0.5.7, v0.6.10 and v0.6.13 states opened as LegacyStore, %d calls each equal, the "
                      "same file; a current state and no state refused alike" % len(ops))


class OpenStateDiff(StoreBase):
    def test_policies(self):
        fixtures = self.scratch / "fixtures"
        fixtures.mkdir()
        source = _released_store("v0.6.10", fixtures, self.profile("writer"))
        cases = []
        for mutex_free in (True, False):
            for legacy, reducing in (("never", False), ("if_reducing", True), ("if_reducing", False), ("always", False),
                                     ("sometimes", False)):
                for install, hold in ((None, False), (True, True), (False, True), (None, True)):
                    cases.append(dict(mutex_free=mutex_free, legacy=legacy, reducing=reducing,
                                      install_in_progress=install, hold_while_installing=hold))
        cases.append(dict(mutex_free=True, legacy="always", superseded=True))
        cases.append(dict(mutex_free=True, legacy="never", superseded=False, check=True))
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                theirs, mine = self.home("ref-%d" % index), self.home("rust-%d" % index)
                twin(source, theirs, mine)
                self.both("open_state", (theirs, mine), label="open_state %r" % case, clock=CLOCK, **case)
                self.same_files(theirs, mine, "open_state %r" % case)
        theirs, mine = self.home("ref-new"), self.home("rust-new")
        self.both("open_state", (theirs, mine), label="open_state of nothing", legacy="never", clock=CLOCK)
        self.same_files(theirs, mine, "open_state of nothing")
        RECORD.append("open_state: %d policy and Windows combinations over a v0.6.10 state opened the same store and "
                      "left the same file" % (len(cases) + 1))


class ConnectionDiff(StoreBase):
    PRAGMAS = ("foreign_keys", "synchronous", "trusted_schema", "journal_mode", "busy_timeout", "locking_mode",
               "recursive_triggers", "cache_size", "temp_store", "secure_delete", "cell_size_check",
               "automatic_index", "application_id", "user_version", "page_size", "auto_vacuum", "encoding")

    def test_pragmas(self):
        theirs, mine = self.home("ref"), self.home("rust")
        ops = [op("pragma", name) for name in self.PRAGMAS]
        self.ops = ops
        answer, _ = self.both("script", (theirs, mine), label="pragmas", open={"clock": CLOCK}, ops=ops)
        RECORD.append("connection: %s" % ", ".join("%s=%s" % (name, value)
                                                   for name, value in zip(self.PRAGMAS, answer["results"])))


class ClaimRaceDiff(StoreBase):
    ROUNDS = 6
    PAIRS = (("python", "python"), ("rust", "rust"), ("python", "rust"), ("rust", "python"))

    def claimant(self, kind, home, index, results, profile, **asked):
        ready, go = home / ("ready-%d" % index), home / "go"
        request = dict(open={"clock": CLOCK}, ops=[op("reserve_detailed", key(0), N + 10)], ready=str(ready),
                       go=str(go))
        request.update(asked)
        if kind == "python":
            process = reference_process("script", home, profile, **request)

            def finish():
                out, err = process.communicate(timeout=300)
                results[index] = json.loads(out) if process.returncode == 0 else {"failed": err.decode()[-2000:]}
            thread = threading.Thread(target=finish)
        else:
            harness = core.Harness(reference.scratch_environment(profile)).__enter__()

            def finish():
                try:
                    _number, line = harness.call("store.script", home=str(home), **request)
                    results[index] = json.loads(line)["reply"]["value"]
                finally:
                    harness.__exit__(None, None, None)
            thread = threading.Thread(target=finish)
        thread.start()
        return thread, ready

    def test_exactly_one_claim(self):
        tally = {}
        for first, second in self.PAIRS:
            wins = 0
            for round_ in range(self.ROUNDS):
                home = self.home("race-%s-%s-%d" % (first, second, round_))
                reference_call("script", home, self.reference_profile, open={"clock": CLOCK}, ops=[
                    op("set_enabled", True, N), op("register", record(0, "server_5xx"), N)])
                results = {}
                started = [self.claimant(kind, home, index, results, self.profile("p-%s-%s-%d-%d" % (
                    first, second, round_, index))) for index, kind in enumerate((first, second))]
                deadline = time.time() + 120
                while not all(ready.exists() for _thread, ready in started) and time.time() < deadline:
                    time.sleep(0.005)
                (home / "go").write_text("go")
                for thread, _ready in started:
                    thread.join(300)
                answers = [results[index]["results"][0] for index in (0, 1)]
                granted = [answer for answer in answers if answer == [True, None, None]]
                self.assertEqual(len(granted), 1, (first, second, answers))
                self.assertIn([False, "submission_safe", "possibly_sent"], answers, (first, second, answers))
                wins += answers[0] == [True, None, None]
                claims = query(home / "state.sqlite", "SELECT count(*) FROM events WHERE code='claim'")[0]
                state = query(home / "state.sqlite", "SELECT state, attempt_count FROM interruptions")
                self.assertEqual((claims, tuple(state)), (1, ("submitting", 1)), (first, second))
            tally["%s+%s" % (first, second)] = wins
        RECORD.append("claim race: %d rounds of each pairing (python+python, rust+rust, python+rust, rust+python), "
                      "two processes released at once on one record: one claim every round, the other refused "
                      "submission_safe/possibly_sent; first-started won %s" % (self.ROUNDS, tally))


class BusyDiff(StoreBase):
    def hold(self, home: Path, seconds: float):
        """A write lock held by a third connection for `seconds` (BEGIN IMMEDIATE, as another store's write)."""
        connection = sqlite3.connect(home / "state.sqlite", isolation_level=None, check_same_thread=False)
        connection.execute("BEGIN IMMEDIATE")
        timer = threading.Timer(seconds, lambda: (connection.execute("COMMIT"), connection.close()))
        timer.start()
        return timer

    def test_waits_and_timeouts(self):
        found = {}
        racer = ClaimRaceDiff.claimant
        for hold, label in ((2.0, "short"), (13.0, "long")):
            theirs, mine = self.home("ref-" + label), self.home("rust-" + label)
            for home in (theirs, mine):
                reference_call("script", home, self.reference_profile, open={"clock": CLOCK}, ops=[
                    op("set_enabled", True, N), op("register", record(0, "server_5xx"), N)])
            ops = [dict(op("get", key(0)), timed=True), dict(op("reserve_detailed", key(0), N + 10), timed=True)]
            answers = []
            for home, kind in ((theirs, "python"), (mine, "rust")):
                # Opened first, then the lock taken, then the calls let go: the wait is the lock's alone.
                results = {}
                thread, ready = racer(self, kind, home, 0, results, self.profile("p-%s-%s" % (label, kind)),
                                      open={"clock": CLOCK, "check": False}, ops=ops)
                deadline = time.time() + 120
                while not ready.exists() and time.time() < deadline:
                    time.sleep(0.005)
                timer = self.hold(home, hold)
                (home / "go").write_text("go")
                thread.join(300)
                timer.join(30)
                answers.append(results[0])
            for value in answers:
                self.assertIsNone(value["open"], value)
            (read_ref, claim_ref), (read_rust, claim_rust) = (value["results"] for value in answers)
            self.assertEqual(read_ref["value"], read_rust["value"])
            self.assertEqual(claim_ref["value"], claim_rust["value"], label)
            for read in (read_ref, read_rust):
                self.assertLess(read["seconds"], 1.0, "a read waited for the writer")
            if label == "short":
                self.assertEqual(claim_rust["value"], [True, None, None])
                for claim in (claim_ref, claim_rust):
                    self.assertGreater(claim["seconds"], 1.0, "the claim did not wait for the write lock")
            else:
                self.assertEqual(claim_rust["value"], {"raised": "StoreError", "message": "State transaction failed"})
                for claim in (claim_ref, claim_rust):
                    self.assertTrue(9.0 < claim["seconds"] < 12.9, claim)   # Windows sleeps round the waits up
            found[label] = (claim_ref["seconds"], claim_rust["seconds"])
            self.same_files(theirs, mine, "busy " + label)
        RECORD.append("busy: a read under another's write lock did not wait; a claim waited %.1f s / %.1f s "
                      "(python / rust) for a 2 s lock and got it; behind a 13 s lock both gave up at %.1f s / %.1f s "
                      "with StoreError 'State transaction failed' (timeout=10)" % (found["short"] + found["long"]))


def junction(link: Path, target: Path) -> None:
    """`mklink /J link target`: a directory junction, which any user may make (a symbolic link needs a privilege)."""
    target.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise AssertionError("mklink /J failed: %r" % done.stderr)


class JunctionDiff(StoreBase):
    """A state folder that is a junction - a moved profile, a folder linked elsewhere - is a folder to Python 3.12+
    (`Path.is_symlink()` is False), and so to car-store (`session::Links` over car-platform's `links.rs`): opened,
    written, downgraded, read as an older watcher's, its usage-checks folder a junction too, all alike."""

    def test_a_junction_is_a_folder(self):
        ops = [op("set_enabled", True, N), op("register", record(0, "server_5xx"), N),
               op("ask_usage_check", key(0), N + 1), op("usage_checks_asked", N + 1), op("usage_check_taken", key(0)),
               op("ask_early_check", N + 2), op("early_check_asked", N + 3), op("all_records")]
        self.ops = ops
        homes = {}
        for side in ("ref", "rust"):
            target = self.scratch / ("target-" + side)
            junction(self.scratch / ("home-" + side), target)
            homes[side] = (self.scratch / ("home-" + side), target)
        answer, _ = self.both("script", (homes["ref"][0], homes["rust"][0]), label="a junction home",
                              open={"clock": CLOCK}, ops=ops)
        self.assertIsNone(answer["open"], answer["open"])
        self.same_files(homes["ref"][1], homes["rust"][1], "a junction home")
        self.both("legacy", (homes["ref"][0], homes["rust"][0]), label="a junction home, legacy", ops=[op("settings")])
        for target in (4, 2):
            self.both("downgrade", (homes["ref"][0], homes["rust"][0]), label="a junction home, downgrade",
                      target=target, now=N + 10)
            self.same_files(homes["ref"][1], homes["rust"][1], "a junction home, downgraded to %d" % target)
        # The usage-checks folder a junction, in an ordinary home.
        theirs, mine = self.home("ref-checks"), self.home("rust-checks")
        for home in (theirs, mine):
            junction(home / "usage-checks", self.scratch / ("checks-of-" + home.name))
        ops = [op("set_enabled", True, N), op("register", record(1), N), op("ask_usage_check", key(1), N + 1),
               op("usage_checks_asked", N + 1), op("usage_check_taken", key(1)), op("ask_early_check", N + 2),
               op("early_check_asked", N + 3), op("early_check_taken"), op("usage_checks_asked", N + 4)]
        self.ops = ops
        answer, _ = self.both("script", (theirs, mine), label="a junction usage-checks folder", open={"clock": CLOCK},
                              ops=ops)
        self.assertIs(answer["results"][2], True, answer["results"])
        self.same_files(theirs, mine, "a junction usage-checks folder")
        RECORD.append("junctions: a state folder that is a junction opened, written, read as legacy and downgraded to 4 "
                      "and 2 alike; a usage-checks folder that is a junction asked, read and taken alike")


ARABIC_THREAD = "\u0660" + THREAD[1:]
# A lone surrogate as a JSON escape: six ASCII characters in the stored text.
SURROGATE = chr(92) + "ud800"


class PythonTextDiff(StoreBase):
    """The readings car-store makes as CPython does (seam/python.rs): a UUID with a Unicode digit is a UUID written
    another way; a request file's time read by float(), underscores and Unicode digits included, its words split as
    str.split() splits; a stored gate vector or usage reading holding NaN, Infinity or a lone surrogate escape read as
    json.loads reads it."""

    def test_python_readings(self):
        theirs, mine = self.home("ref"), self.home("rust")
        for home in (theirs, mine):
            reference_call("script", home, self.reference_profile, open={"clock": CLOCK}, ops=[
                op("set_enabled", True, N), op("register", record(0, "server_5xx"), N),
                op("register", record(1, "server_5xx"), N), op("register", record(2, "server_5xx"), N),
                op("heartbeat", N, pid=1, session_id="s", started_at=N, ok=True, engine_state="verified",
                   code_version="v")])
            path = home / "state.sqlite"
            edit(path,
                 "UPDATE interruptions SET gate_eval='{\"consent\":[\"WAIT\",\"paused\"],\"x\":NaN}', gate_eval_at=%r "
                 "WHERE interruption_id='%s'" % (N + 5, key(0)),
                 "UPDATE interruptions SET gate_eval='{\"consent\":[\"WAIT\",\"paused\"],\"x\":\"" + SURROGATE + "\"}', "
                 "gate_eval_at=%r WHERE interruption_id='%s'" % (N + 5, key(1)),
                 "UPDATE interruptions SET gate_eval='{\"consent\":[\"WAIT\",-Infinity]}', gate_eval_at=%r "
                 "WHERE interruption_id='%s'" % (N + 5, key(2)),
                 ("UPDATE watcher_status SET usage_at=%r, usage='[{\"bucket\":\"codex\",\"window\":\"primary\","
                  "\"used_percent\":1,\"window_minutes\":null,\"reset_at\":NaN}]', homes='[{\"key\":\"\","
                  "\"state\":\"watched\"},{\"key\":\"" % N) + SURROGATE + "\",\"state\":\"watched\"}]'")
            checks = home / "usage-checks"
            checks.mkdir()
            (checks / key(0)).write_text("1_700_000_148.5", encoding="ascii")
            (checks / key(1)).write_text("1700000149.0\x1crescan", encoding="ascii")
            (checks / key(2)).write_text("1__7", encoding="ascii")
            (checks / "early").write_text(" 1_700_000_000.0\n", encoding="ascii")
        ops = [op("set_thread_enabled", ARABIC_THREAD, False), op("thread_enabled", ARABIC_THREAD),
               op("usage_checks_asked", N), op("early_check_asked", N), op("usage_check_taken", key(1)),
               op("usage_check_taken", key(0)), op("watcher_status")]
        ops += [op("reserve_detailed", key(index), N + 50, limits=LIMITS, gates=GATES) for index in range(3)]
        ops += [op("get", key(index)) for index in range(3)]
        self.ops = ops
        answer, _ = self.both("script", (theirs, mine), label="python readings", open={"clock": CLOCK}, ops=ops)
        self.same_files(theirs, mine, "python readings")
        RECORD.append("python readings: %d calls over a UUID with an Arabic-Indic digit, request files with underscores "
                      "and U+001C, and stored JSON with NaN, -Infinity and a lone surrogate: equal answers, the same file "
                      "(the first refusal: %s)" % (len(ops), answer["results"][0]))

"""car-store on values a column can hold that no store writes: BLOBs, a sign-in with a newline, no settings row.

REVIEW-int5 S4 and its notes 1 and 5. Each state is written once (by the reference's own store), edited outside any
store as a damaged or foreign state could be - `PRAGMA ignore_check_constraints` lets a BLOB into a column whose CHECK
would refuse it - copied, and then read and written by both stores (`StoreBase.both`), the answers and the files left
compared as diffs_store.py compares them. A BLOB (Python's `bytes`) is written in an answer as car-store's value.rs
carries it, `{"\\u0000bytes": hex}` (the reference's runner's `plain`).

* BlobDiff - the heartbeat's columns as BLOBs read by `watcher_status` (`bool(bytes)` of `last_tick_ok`: x'01' True,
  x'' False; every other column not a number or a text); a legacy store's `enabled`, `armed_at` and thread ids as BLOBs
  through `settings`, `thread_enabled`, `set_enabled` (the BLOB `armed_at` written back as itself), `disabled_threads`
  and `thread_of`.
* SignInDiff - the sign-ins a heartbeat keeps: `$` matches before one final newline, so 16 digits and a `\\n` are kept.
* NoSettingsDiff - a legacy state with no settings row: `set_enabled` raises TypeError and leaves the file as it was.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3

from rustdiff import reference
from rustdiff.diffs_store import CLOCK, N, OTHER, THREAD, StoreBase, _released_store, key, op, reference_call

RECORD: list[str] = []


def damage(path: Path, *statements: str) -> None:
    """Statements run on a state file outside any store, the CHECK constraints off, each committed on its own."""
    with closing(sqlite3.connect(path, isolation_level=None)) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        for statement in statements:
            db.execute(statement)


HEARTBEAT = op("heartbeat", N, pid=1234, session_id="s1", started_at=N - 50, ok=True, engine_state="running",
               code_version="0.6.26", usage=None, awake_since=N - 10, memory_peak=1000, sign_in="0123456789abcdef",
               booted_at=N - 100, homes=[{"key": "", "state": "watched"}, {"key": "a" * 64, "state": "lock_busy"}])

# Each a list of edits to watcher_status, read back by watcher_status.
WATCHER_EDITS = [
    ["UPDATE watcher_status SET last_tick_ok=x'01'"],
    ["UPDATE watcher_status SET last_tick_ok=x'00'"],
    ["UPDATE watcher_status SET last_tick_ok=x''"],
    ["UPDATE watcher_status SET last_tick_ok=x'0000ff'"],
    ["UPDATE watcher_status SET pid=x'05', session_id=x'7331', started_at=x'01', last_tick_at=x''"],
    ["UPDATE watcher_status SET engine_state=CAST('running' AS BLOB), code_version=CAST('0.6.26' AS BLOB)"],
    ["UPDATE watcher_status SET usage=CAST('[]' AS BLOB), usage_at=x'01', awake_since=x'02', memory_peak=x'03'"],
    ["UPDATE watcher_status SET end_mark=CAST('clean' AS BLOB), ended_at=x'04', sign_in=CAST('0123456789abcdef' AS BLOB)"],
    ["UPDATE watcher_status SET booted_at=x'05', homes=CAST('[{\"key\":\"\",\"state\":\"watched\"}]' AS BLOB)"],
]


class BlobDiff(StoreBase):
    def test_watcher_status_reads_a_blob_as_bytes(self):
        source = self.home("source")
        reference_call("script", source, self.reference_profile, open={"clock": CLOCK, "migrate": True},
                       ops=[HEARTBEAT])
        for index, statements in enumerate(WATCHER_EDITS):
            with self.subTest(edit=index):
                theirs, mine = self.home("ref-%d" % index), self.home("rust-%d" % index)
                shutil.copyfile(source / "state.sqlite", theirs / "state.sqlite")
                damage(theirs / "state.sqlite", *statements)
                shutil.copyfile(theirs / "state.sqlite", mine / "state.sqlite")
                self.ops = [op("watcher_status"), op("status_counts")]
                answer, _ = self.both("script", (theirs, mine), label="watcher edit %d" % index,
                                      open={"clock": CLOCK}, ops=self.ops)
                self.same_files(theirs, mine, "watcher edit %d" % index)
        RECORD.append("blobs: watcher_status over %d heartbeats with BLOB columns (last_tick_ok x'01', x'00', x'', "
                      "x'0000ff'; every other column) equal %s's" % (len(WATCHER_EDITS), reference.TAG))

    def test_a_legacy_store_reads_and_writes_a_blob_as_bytes(self):
        fixtures = self.scratch / "fixtures"
        fixtures.mkdir()
        source = _released_store("v0.6.10", fixtures, self.profile("writer-v0.6.10"))
        cases = [
            # enabled as a BLOB: bool(b'\x00') is True, so set_enabled(True) keeps the BLOB armed_at and writes it back
            ["UPDATE settings SET enabled=x'00', armed_at=x'abcd'"],
            ["UPDATE settings SET enabled=x'', armed_at=x'abcd'"],
            ["UPDATE settings SET enabled=x'01', armed_at=x''"],
            ["INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES ('%s', x'01')" % THREAD,
             "INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES ('%s', x'')" % OTHER],
            ["INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES (x'0102', 0)",
             "INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES (x'01', 0)",
             "INSERT OR REPLACE INTO threads (thread_id, enabled) VALUES (x'', 0)",
             "UPDATE threads SET enabled=1 WHERE typeof(thread_id)='text'"],
            ["UPDATE interruptions SET thread_id=x'0a0b' WHERE interruption_id='%s'" % key(0)],
        ]
        ops = [op("settings"), op("thread_enabled", THREAD), op("thread_enabled", OTHER), op("disabled_threads"),
               op("thread_of", key(0)), op("set_enabled", True, N), op("settings"), op("set_enabled", True, N + 1),
               op("set_enabled", False, N + 2), op("set_enabled", True, N + 3), op("settings"),
               op("status_counts"), op("thread_enabled", THREAD)]
        self.ops = ops
        for index, statements in enumerate(cases):
            with self.subTest(edit=index):
                theirs, mine = self.home("ref-legacy-%d" % index), self.home("rust-legacy-%d" % index)
                shutil.copyfile(source, theirs / "state.sqlite")
                damage(theirs / "state.sqlite", *statements)
                shutil.copyfile(theirs / "state.sqlite", mine / "state.sqlite")
                self.both("legacy", (theirs, mine), label="legacy edit %d" % index, ops=ops)
                self.same_files(theirs, mine, "legacy edit %d" % index)
        RECORD.append("blobs: a v0.6.10 state as LegacyStore with BLOB enabled, armed_at and thread ids, %d edits x %d "
                      "calls equal, the same file" % (len(cases), len(ops)))


class SignInDiff(StoreBase):
    def test_the_sign_ins_a_heartbeat_keeps(self):
        theirs, mine = self.home("ref"), self.home("rust")
        signs = ["0123456789abcdef", "0123456789abcdef\n", "0123456789abcdef\n\n", "0123456789abcdef\r\n",
                 "\n0123456789abcdef", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0", "0123456789abcdef ",
                 "٠123456789abcdef", "", None, 5]
        self.ops = []
        for each in signs:
            beat = dict(HEARTBEAT, kwargs=dict(HEARTBEAT["kwargs"], sign_in=each))
            self.ops += [beat, op("watcher_status")]
        self.both("script", (theirs, mine), label="sign-ins", open={"clock": CLOCK, "migrate": True}, ops=self.ops)
        self.same_files(theirs, mine, "sign-ins")
        RECORD.append("sign-ins: %d written by heartbeat and read by watcher_status equal (16 digits and one final "
                      "newline kept)" % len(signs))


class NoSettingsDiff(StoreBase):
    def test_set_enabled_with_no_settings_row(self):
        fixtures = self.scratch / "fixtures"
        fixtures.mkdir()
        source = _released_store("v0.6.10", fixtures, self.profile("writer-v0.6.10"))
        theirs, mine = self.home("ref"), self.home("rust")
        shutil.copyfile(source, theirs / "state.sqlite")
        damage(theirs / "state.sqlite", "DELETE FROM settings")
        shutil.copyfile(theirs / "state.sqlite", mine / "state.sqlite")
        self.ops = [op("set_enabled", True, N), op("set_enabled", False, N), op("settings"),
                    op("thread_enabled", THREAD), op("set_thread_enabled", OTHER, False), op("disabled_threads")]
        answer, _ = self.both("legacy", (theirs, mine), label="no settings row", ops=self.ops)
        self.same_files(theirs, mine, "no settings row")
        RECORD.append("no settings row: LegacyStore.set_enabled %s alike, the file unchanged"
                      % answer["results"][0].get("raised", "answered"))


class CapsDiff(StoreBase):
    def test_a_claim_with_spacing_and_a_day_that_are_not_finite(self):
        """`_caps_refusal`: `now - latest >= cooldown` with a NaN cooldown is False, so the spacing refuses (note 6);
        an infinite one refuses too, and a NaN or an infinite day passes to the spacing."""
        from rustdiff.diffs_store import LIMITS, record
        caps = [[10, float("nan")], [10, float("inf")], [10, float("-inf")], [float("nan"), 5], [float("inf"), 5],
                [float("-inf"), 5], [10, 5], [10, 30]]
        self.ops = [op("set_enabled", True, N), op("register", record(0, "server_5xx"), N),
                    op("register", record(1, "server_5xx"), N)]
        for index, pair in enumerate(caps):
            at = N + 10 + index * 20
            self.ops += [op("reserve_detailed", key(0), at),
                         op("release_claim", key(0), "waiting_backoff", "queue_process_not_started", at + 1),
                         op("reserve_detailed", key(0), at + 10, limits=LIMITS, caps=pair),
                         op("reserve", key(1), at + 11, caps=pair),
                         op("release_claim", key(0), "waiting_backoff", "queue_process_not_started", at + 12),
                         op("release_claim", key(1), "waiting_backoff", "queue_process_not_started", at + 12)]
        theirs, mine = self.home("ref"), self.home("rust")
        self.both("script", (theirs, mine), label="caps", open={"clock": CLOCK, "migrate": True}, ops=self.ops)
        self.same_files(theirs, mine, "caps")
        RECORD.append("caps: %d claims with a day and a spacing of NaN, both infinities and finite numbers equal"
                      % len(caps))

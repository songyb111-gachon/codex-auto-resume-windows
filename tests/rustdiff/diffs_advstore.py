"""The advanced store's diffs (seat S7.1a, car-adv `state/`, `ledger`, `profiles`, `watchlog`, `images`).

Each case runs the same request through the reference tag's own advanced package and through car-adv's `advstore`
example on two copies of one scratch home (advstore.py) and holds every answer and every file left equal:

* GeneratedDiff - the statements, words and registry facts car-adv carries are the tag's (gen_advstore.py and
  gen_advpolicy.py --check).
* FreshDiff - a file made by the first write, and every read of a home with none: equal answers, the same file.
* MigrationDiff - files made by older releases' own code (v0.6.11-alpha's version 1 to v0.6.25's version 9, the
  ceiling of 12, the words' 8,192, `options` and `wordings` with their CHECKs) and by the tag's own historic
  statements, opened by a read and by a write: the same answers, the same upgraded file. And a later version marked
  readable from 7 (used as it is), marked from 10 or unmarked (refused as newer), a file with a table too many.
* ScriptDiff - one long script over every method of AdvancedState - arming, keep on, the ceiling, spend, records and
  overrides, the journal and the sampler, options, stamps, wordings, rules, admissions and samples, the reset actions,
  continuations, keep going, prompts, the meter, runs, chat, analytics, restarts, opens, the account, steers - with
  refusals and wrong types; then the reference reads Rust's file and Rust the reference's, every read equal.
* ScopedDiff - a capability's view and every table's handle, on, off and unset, its own and another's.
* DamagedDiff - rows hand-edited to words the vocabulary does not hold, the wrong types, a file that is not SQLite.
* PruneDiff - the journal's 256th line and the bounds of every table, at old times.
* LedgerDiff - P11 on core's state (schema 5, the tag's own store) with this file attached: claims held and granted,
  the ceilings, a Send now, a resend, a queue for open, a record's claim and launch.
* ClaimRaceDiff - two processes claim one record of this edition's at the same moment, all four pairings of Python
  and Rust: exactly one is granted.
* ProfilesDiff, ImagesDiff, WatchlogDiff - the saved accounts (unsealed contents compared), a prompt's pictures, the
  watch log.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest

from rustdiff import advref, advstore, reference
from rustdiff.advstore import CLOCK, OTHER, THREAD, Twin, key, thread

RECORD = []
HERE = Path(__file__).resolve().parent


def op(method, *args, **kwargs):
    return {"method": method, "args": list(args), "kwargs": kwargs}


def at(seconds):
    return {"clock": seconds}


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not advstore.binary().is_file():
            advstore.build()

    def same(self, twin: Twin, request: dict, label: str) -> list:
        python, rust = twin.run(request)
        self.assertEqual(len(python), len(rust), "%s: answers" % label)
        for index, (one, other) in enumerate(zip(python, rust)):
            self.assertEqual(advstore.comparable(one), advstore.comparable(other),
                             "%s: op %d (%s) differs" % (label, index, json.dumps(request["ops"][index])[:200]))
        python_files, rust_files = advstore.dump_home(twin.python), advstore.dump_home(twin.rust)
        for name in sorted(set(python_files) | set(rust_files)):
            self.assertEqual(python_files.get(name), rust_files.get(name), "%s: %s differs" % (label, name))
        return python


def request(ops, **extra):
    return dict({"clock": CLOCK, "tokens": 0, "ops": ops}, **extra)


# ------------------------------------------------------------------------------------------- generated
class GeneratedDiff(unittest.TestCase):
    def test_generated(self):
        # The store's statements are gen_advstore's; the closed words and the registry it reads are S7.1b's (Integration 5).
        for script in ("gen_advstore.py", "gen_advpolicy.py"):
            done = subprocess.run(reference.script_command(HERE / script, "--check", "--ref", reference.TAG, paths=[]),
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        RECORD.append("generated: schema_gen.rs (gen_advstore) and the vocabulary and registry tables (gen_advpolicy) "
                      "match %s" % reference.TAG)


READS = [op("exists"), op("meta"), op("arming"), op("ever_moved", "usage_meter"), op("spent", "usage_meter", THREAD),
         op("journal"), op("journal", capability="usage_meter", limit=3), op("samples", "usage_meter"),
         op("options", "usage_wrap_up"), op("options", "usage_meter"), op("options", "nope"),
         op("wordings", "usage_wrap_up"), op("rules"), op("rule_hits", 0), op("failure_samples", 0),
         op("windows"), op("reading"), op("reset_rules"), op("reset_rules", pending=None), op("credit_spends"),
         op("continuations", pending=None), op("keep_going"), op("prompts", pending=None), op("meter"),
         op("runs", live=False), op("chats"), op("token_files"), op("token_days"), op("usage_samples"),
         op("restarts_since", 0), op("opens", 0), op("account_seen"), op("steers"), op("waiting_steers"),
         op("records_on", THREAD), op("open_overrides", "force_once"), op("messages_in_flight"),
         op("continuations_in_flight"), op("prompts_in_flight"), op("chats_in_flight"),
         op("stamped", "idle_update_check", "last_check"), op("spends_since", "usage_meter", 0),
         op("payers", key(1), None), op("channel_paid", key(1), None), op("resent", key(1)),
         op("overrides_for", key(1)), op("admission", key(1)), op("account_seen"),
         {"watchlog": "exported"}, {"watchlog": "view", "args": ["usage_meter"]}]


class FreshDiff(Base):
    def test_fresh(self):
        twin = Twin()
        try:
            self.same(twin, request(READS), "no file")
            self.assertFalse((twin.rust / "config").exists(), "a read made the folder")
            self.same(twin, request([op("move", "usage_meter", "shadow", actor="dashboard")] + READS), "fresh")
            RECORD.append("fresh: %d reads with no file (nothing made), one write making the file, equal" % len(READS))
        finally:
            twin.close()


# ------------------------------------------------------------------------------------------- old files
OLD_TAGS = ("v0.6.11-alpha", "v0.6.12", "v0.6.13", "v0.6.14", "v0.6.15-beta", "v0.6.15", "v0.6.16-beta.3",
            "v0.6.16-beta.4", "v0.6.16", "v0.6.17", "v0.6.18", "v0.6.19", "v0.6.20", "v0.6.21", "v0.6.22", "v0.6.23",
            "v0.6.25")
MAKE_OLD = r'''
import json, sqlite3, sys
from pathlib import Path
from codex_auto_resume import config
home = Path(sys.argv[1])
paths = config.Paths(str(home))
import codex_auto_resume_advanced.state as package
try:
    state = package.AdvancedState(paths)
except TypeError:
    from codex_auto_resume_advanced.registry import REGISTRY
    state = package.AdvancedState(paths, registry=REGISTRY)
state._open(create=True)
state.close()
connection = sqlite3.connect(str(Path(paths.advanced_dir) / "advanced.sqlite"), isolation_level=None)
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
rows = [
    ("arming", "INSERT INTO arming (capability, state, since, actor, reason, statement_revision, engine_version) VALUES ('usage_meter', 'armed', 1764000000.0, 'dashboard', NULL, 3, '0.130.0')"),
    ("arming", "INSERT INTO arming (capability, state, since, actor) VALUES ('keep_going', 'shadow', 1764000001.0, 'dashboard')"),
    ("spend", "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES (1763999000.0, 'usage_meter', '%s', NULL)" % THREAD),
    ("records", "INSERT INTO records (record_id, capability, thread_id, state, created_at, claims) VALUES ('%s', 'prompt_queue', '%s', 'waiting', 1763990000.0, 0)" % ("a" * 64, THREAD)),
    ("overrides", "INSERT INTO overrides (interruption_id, capability, kind, created_at) VALUES ('%s', 'send_now', 'force_once', 1763999999.0)" % ("b" * 64)),
    ("journal", "INSERT INTO journal (at, capability, code, reason, actor) VALUES (1763999990.0, 'usage_meter', 'armed', NULL, 'dashboard')"),
    ("sampler", "INSERT INTO sampler (capability, code, day, count) VALUES ('usage_meter', 'mtr.read', 20416, 3)"),
    ("options", "INSERT INTO options (capability, choice, value) VALUES ('usage_meter', 'window_weekly', 2)"),
    ("options", "INSERT INTO options (capability, choice, value) VALUES ('usage_meter', 'poll_minutes', 30)"),
    ("rules", "INSERT INTO rules (tag, status_from, status_to, category, created_at) VALUES ('weirdCode', 500, 503, 'server_5xx', 1763000000.0)"),
    ("keep_going", "INSERT INTO keep_going (thread_id, count, used, armed_at, state) VALUES ('%s', 3, 1, 1763000000.0, 'on')" % THREAD),
    ("prompts", "INSERT INTO prompts (thread_id, words, trigger, occurrences, sent_count, depends, position, state, created_at, due_at) VALUES ('%s', 'hello', 'after_turn', 1, 0, 0, 0, 'waiting', 1763999000.0, 1763999000.0)" % THREAD),
    ("meter", "INSERT INTO meter (bucket, minutes, used_percent, reset_at, read_at) VALUES ('codex', 300, 42.5, 1764010000, 1763999999.0)"),
    ("wordings", "INSERT INTO wordings (capability, choice, words, changed_at) VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Wrap up please', 1763000000.0)"),
    ("steers", "INSERT INTO steers (thread_id, words, client_id, state, created_at) VALUES ('%s', 'more', '%s', 'requested', 1763999999.0)" % (THREAD, "0" * 36)),
]
for table, statement in rows:
    if table in tables:
        try:
            connection.execute(statement)
        except sqlite3.Error:
            pass
if "meta" in tables:
    connection.execute("UPDATE meta SET generation = 7")
connection.close()
print(json.dumps(sorted(tables)))
'''


def old_home(tag: str, home: Path) -> None:
    done = advref.run(MAKE_OLD, str(home), profile=home.parent / "profile", tag=tag)
    if done.returncode != 0:
        raise AssertionError("%s could not make its file:\n%s" % (tag, done.stderr.decode("utf-8", "replace")[-2000:]))


HISTORIC = r'''
import sqlite3, sys
from pathlib import Path
from codex_auto_resume import config
from codex_auto_resume_advanced.state import schema
home = Path(sys.argv[1])
folder = Path(config.Paths(str(home)).advanced_dir)
folder.mkdir(parents=True)
connection = sqlite3.connect(str(folder / "advanced.sqlite"), isolation_level=None)
for statement in getattr(schema, sys.argv[2]):
    connection.execute(statement)
for statement in sys.argv[3:]:
    connection.execute(statement)
connection.close()
'''


def historic(name: str, *extra: str):
    def make(home: Path) -> None:
        done = advref.run(HISTORIC, str(home), name, *extra, profile=home.parent / "profile")
        if done.returncode != 0:
            raise AssertionError(done.stderr.decode("utf-8", "replace")[-2000:])
    return make


class MigrationDiff(Base):
    def test_older_releases(self):
        made = []
        for tag in OLD_TAGS:
            for first in ("read", "write"):
                twin = Twin(lambda home, tag=tag: old_home(tag, home))
                try:
                    opening = [op("meta")] if first == "read" else [op("set_global_hourly", 5, generation=7,
                                                                            actor="dashboard")]
                    self.same(twin, request(opening + READS), "%s, %s first" % (tag, first))
                finally:
                    twin.close()
            made.append(tag)
        RECORD.append("migrations: files made by %d releases' own code (%s ... %s), each opened by a read and by a "
                      "write, %d reads each: equal answers and files" % (len(made), made[0], made[-1], len(READS)))

    def test_historic_statements(self):
        cases = {
            "v2": historic("STATEMENTS_V2"),
            "v3": historic("STATEMENTS_V3"),
            "before stage 4": historic("STATEMENTS_BEFORE_STAGE4"),
            "v7": historic("STATEMENTS_V7"),
            "v1": historic("STATEMENTS_V2", "PRAGMA user_version=1"),
            "newer readable from 7": historic("STATEMENTS", "PRAGMA user_version=10", "CREATE TABLE extra (x)"),
            "newer marked from 10": historic("STATEMENTS", "PRAGMA user_version=10", "PRAGMA application_id=1128333322"),
            "newer unmarked": historic("STATEMENTS", "PRAGMA user_version=10", "PRAGMA application_id=0"),
            "a table too many": historic("STATEMENTS", "CREATE TABLE extra (x)"),
            "a column too few": historic("STATEMENTS", "ALTER TABLE token_files DROP COLUMN read_at"),
            "no meta row": historic("STATEMENTS", "DELETE FROM meta"),
            "empty schema": historic("STATEMENTS", "DROP TABLE meta"),
            "ceiling 12 at 12": historic("STATEMENTS_V7", "UPDATE meta SET global_hourly=12"),
            "ceiling 12 at 7": historic("STATEMENTS_V7", "UPDATE meta SET global_hourly=7"),
            "version 0 empty file": lambda home: (Path(advstore.advref.ROOT) and _empty_file(home)),
            "not a database": lambda home: _garbage_file(home),
        }
        for label, setup in cases.items():
            for first in ("read", "write"):
                twin = Twin(setup)
                try:
                    opening = [op("meta")] if first == "read" else [op("move", "usage_meter", "shadow",
                                                                            actor="dashboard")]
                    self.same(twin, request(opening + READS[:8]), "%s, %s first" % (label, first))
                finally:
                    twin.close()
        RECORD.append("historic statements: %d files (versions 1, 2, 3, 6, 7, three newer, malformed, the old "
                      "ceiling, empty, not SQLite) by a read and by a write: equal" % len(cases))


def _advanced_folder(home: Path) -> Path:
    folder = home / "config" / "advanced"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _empty_file(home: Path) -> None:
    (_advanced_folder(home) / "advanced.sqlite").write_bytes(b"")


def _garbage_file(home: Path) -> None:
    (_advanced_folder(home) / "advanced.sqlite").write_bytes(b"not a database at all" * 20)


# ------------------------------------------------------------------------------------------- the script
def script_ops() -> list:
    t1, t2 = THREAD, OTHER
    ops = [
        # arming
        op("move", "usage_meter", "shadow", actor="dashboard"), op("move", "usage_meter", "armed", actor="dashboard",
                                                                    revision=3, engine_version="0.130.0",
                                                                    warnings=["unmeasured"], generation=1),
        op("move", "usage_meter", "armed", actor="dashboard", generation=0), op("move", "nope", "armed", actor="mcp"),
        op("move", "usage_meter", "on", actor="dashboard"), op("move", "usage_meter", "off", actor="robot"),
        op("move", "usage_meter", "armed", actor="dashboard", warnings="unmeasured"),
        op("move", "usage_meter", "armed", actor="dashboard", warnings=["nope"]),
        op("move", "usage_meter", "armed", actor="dashboard", revision=3, engine_version="0.130.0",
           warnings=["unmeasured"]),
        op("move_set", [["usage_wrap_up", "armed", 1, "0.130.0", None], ["usage_meter", "armed", 3, "0.130.0",
                                                                          ["unmeasured"]]],
           actor="dashboard", generation=2, keep=["usage_wrap_up"]),
        op("move_set", [["usage_wrap_up", "off", 1, None, None]], actor="dashboard", generation=3),
        op("move_set", [["keep_going", "shadow", 1, None, None]], actor="dashboard", generation=3, keep=["keep_going"]),
        op("move_set", [["keep_going", "shadow", 1, None, None]], actor="dashboard", generation=99),
        op("set_keep_on", "usage_meter", True, actor="dashboard", generation=3),
        op("set_keep_on", "usage_meter", True, send_again=True, actor="dashboard", generation=4),
        op("set_keep_on", "usage_meter", "yes", actor="dashboard"),
        op("set_keep_on", "keep_going", True, actor="dashboard", generation=5),
        op("send_again_off", "usage_meter", reason="duplicate_seen"),
        op("send_again_off", "usage_meter", reason="duplicate_seen"),
        op("note_kept", "usage_meter", "statement_changed"), op("note_kept", "usage_meter", "duplicate_seen"),
        op("note_kept", "usage_meter", "disarmed"), op("set_global_hourly", 30, generation=6, actor="dashboard"),
        op("set_global_hourly", 10, generation=6, actor="dashboard"), op("set_global_hourly", True, generation=7,
                                                                          actor="dashboard"),
        op("meta"), op("arming"), op("ever_moved", "usage_meter"), op("ever_moved", "nope"),
        # spend and records
        op("add_record", key(1), "prompt_queue", t1), op("add_record", key(1), "prompt_queue", t1),
        op("add_record", key(2), "nope", t1), op("add_record", "short", "prompt_queue", t1),
        op("add_record", key(3), "prompt_queue", "not-a-thread"), op("move_record", key(1), "finished"),
        op("move_record", key(1), "cancelled"), op("move_record", key(1), "done"), op("records_on", t1),
        op("add_override", key(4), "send_now", "force_once"), op("add_override", key(4), "send_now", "force_once"),
        op("add_override", key(4), "send_now", "bogus"), op("overrides_for", key(4)),
        op("use_override", key(4), "send_now"), op("use_override", key(4), "send_now"),
        op("renew_override", key(4), "send_now", "force_once"), op("override", key(4), "send_now"),
        op("resent", key(4)), op("open_overrides", "force_once"), op("open_overrides", "force_once", "send_now"),
        op("spent", "usage_meter", t1), op("spends_since", "usage_meter", 0), op("payers", key(4), CLOCK),
        op("channel_paid", key(4), None),
        # journal and sampler
        op("note", "armed", capability="usage_meter", reason="disarmed", actor="dashboard", point="tick",
           answer="hold"),
        op("note", "mtr.read", capability="usage_meter"), op("note", "bogus.code", capability="usage_meter",
                                                             reason="nope", actor="nope", point="nope", answer="nope"),
        op("note", "would_have", capability="usage_meter", answer="keep_going"),
        op("sample", "usage_meter", "read"), op("sample", "usage_meter", "nope"),
        op("counted", "usage_meter", "read"), op("counted", "nope", "read"),
        op("counted_since", "usage_meter", "read", 0), op("counted_since", "usage_meter", "read", True),
        op("samples", "usage_meter"), op("journal"), op("journal", capability="usage_meter", limit="2"),
        op("journal", limit=0), op("journal", limit=[1]), op("journal_times", "usage_meter", "read", 0),
        op("journal_times", "usage_meter", "nope", 0),
        # options, stamps, wordings
        op("options", "usage_meter"), op("set_option", "usage_meter", "poll_minutes", 30, generation=7,
                                         actor="dashboard"),
        op("set_option", "usage_meter", "poll_minutes", 30, generation=8, actor="dashboard"),
        op("set_option", "usage_meter", "poll_minutes", 15, generation=9, actor="dashboard"),
        op("set_option", "usage_meter", "poll_minutes", 31, generation=10, actor="dashboard"),
        op("set_option", "usage_meter", "poll_minutes", 999, generation=10, actor="dashboard"),
        op("set_option", "usage_meter", "nope", 1, generation=10, actor="dashboard"),
        op("set_option", "usage_wrap_up", "window_weekly", 1, generation=10, actor="dashboard"),
        op("options", "usage_meter"), op("options", "usage_wrap_up"),
        op("stamp", "idle_update_check", "last_check", 1764000000), op("stamp", "idle_update_check", "last_check", 0),
        op("stamp", "idle_update_check", "nope", 5), op("stamped", "idle_update_check", "last_check"),
        op("unstamp", "idle_update_check", "last_check"), op("unstamp", "idle_update_check", "last_check"),
        op("set_wording", "usage_wrap_up", "wrap_custom_weekly", "Please wrap up", generation=11, actor="dashboard"),
        op("set_wording", "usage_wrap_up", "nope", "x", generation=12, actor="dashboard"),
        op("set_wording", "usage_wrap_up", "wrap_custom_weekly", 5, generation=12, actor="dashboard"),
        op("wordings", "usage_wrap_up"),
        op("set_wording", "usage_wrap_up", "wrap_custom_weekly", None, generation=12, actor="dashboard"),
        # rules, admissions, samples
        op("add_rule", "weirdCode", 500, 503, "server_5xx", generation=13, actor="dashboard"),
        op("add_rule", "weirdCode", 501, 501, "server_5xx", generation=14, actor="dashboard"),
        op("add_rule", "usage_limit_exceeded", None, None, "server_5xx", generation=14, actor="dashboard"),
        op("add_rule", "bad tag", None, None, "server_5xx", generation=14, actor="dashboard"),
        op("add_rule", "otherCode", 500, None, "server_5xx", generation=14, actor="dashboard"),
        op("add_rule", "otherCode", None, None, "usage_limit", generation=14, actor="dashboard"),
        op("add_rule", "otherCode", None, None, "timeout", generation=14, actor="dashboard"),
        op("rules"), op("remove_rule", 99, generation=15, actor="dashboard"), op("remove_rule", "1", generation=15,
                                                                                actor="dashboard"),
        op("remove_rule", 2, generation=15, actor="dashboard"),
        op("admit", key(5), "structured_rules", "as_server_5xx", rule_id=1,
           shape={"code": "weirdCode", "status": 502, "form": "tagged", "has_message": True}),
        op("admit", key(5), "structured_rules", "hold"), op("admit", key(6), "unknown_failure_budget", "admit",
                                                            shape={"form": "absent"}),
        op("admit", key(7), "nope", "admit"), op("admit", key(7), "unknown_failure_budget", "admit", rule_id="1"),
        op("admission", key(5)), op("taken", key(5), "structured_rules", "matched"),
        op("taken", key(5), "structured_rules", "matched"), op("taken", key(6), "unknown_failure_budget", "sampled",
                                                              sample={"code": "x1", "status": 500, "form": "tagged",
                                                                      "items": {"agentMessage": 2, "other": -1},
                                                                      "duration": 12.5}),
        op("taken", key(6), "structured_rules", "nope"), op("rule_hits", 0), op("failure_samples", 0),
        op("fn.aggregated", [{"tag": "a", "status": 500, "form": "tagged", "at": 1764000000.0},
                             {"tag": "a", "status": 500, "form": "tagged", "at": 1764100000.0},
                             {"tag": None, "status": None, "form": "absent", "at": None}]),
        op("fn.tag_problem", "abc"), op("fn.tag_problem", "1abc"), op("fn.tag_problem", 5),
        # the reset actions
        op("save_windows", [{"bucket": "codex", "minutes": 300, "open_reset_at": 1764010000, "open_full": 1,
                             "last_closed_at": None, "resets": 2, "hits": 1, "seen_at": CLOCK, "misses": 0}]),
        op("save_windows", [{"bucket": "nope", "minutes": 300}]), op("save_windows", [{"bucket": "codex"}]),
        op("windows"), op("set_reading", read_at=CLOCK, credits=3), op("set_reading", nope=1), op("reading"),
        op("add_reset_rule", "reset_credit", "codex", 300, 0), op("add_reset_rule", "reset_message", "codex", 300, 1,
                                                                   thread_id=t1, words="Go on", record_id=key(8)),
        op("add_reset_rule", "reset_message", "codex", 300, 1, thread_id=t1, words="Again", record_id=key(9)),
        op("add_reset_rule", "reset_message", "codex", 300, 0, thread_id=t2, words="x", record_id=key(9)),
        op("add_reset_rule", "reset_message", "weekly", 300, 1, thread_id=t2, words="", record_id=key(9)),
        op("add_reset_rule", "reset_credit", "codex", 300, 1, repeat="yes"),
        op("add_reset_rule", "reset_credit", "codex", 0, 1), op("reset_rules"), op("reset_rule", 2),
        op("change_rule", 2, state="ready", due_at=CLOCK, gate="pace", gate_reason="held"),
        op("change_rule", 2, nope=1), op("change_rule", 2, gate="bad word!"), op("change_rule", 2, base=-1),
        op("record_moved", key(8), "waiting", gate="submission_safe", reason="held"),
        op("record_moved", key(8), "sent", queue_id="0a1b2c3d-0003-7000-8000-000000000001"),
        op("cancel_reset_rule", 2), op("record_moved", key(8), "withdrawn"), op("cancel_reset_rule", 2),
        op("add_credit_spend", 1, "codex", 300, 1, "0" * 36), op("add_credit_spend", 1, "codex", 300, 1, "0" * 36),
        op("add_credit_spend", 1, "codex", 300, 1, "short"), op("finish_credit_spend", 1, "spent"),
        op("retry_credit_spend", 1), op("drop_credit_spend", 1), op("credit_spends"),
        op("end_rule", 1, "done", "delivered"), op("end_rule", 1, "counting", "delivered"),
        op("end_messages_in", t1), op("release_unlaunched"), op("carry_message", 2), op("carried_message", 2, True),
        # continuations and keep going
        op("add_continuation", key(10), "empty_response", "empty_reply", t1, "Please continue.", ordinal=0),
        op("add_continuation", key(10), "empty_response", "empty_reply", t1, "Please continue.", ordinal=0),
        op("add_continuation", key(11), "nope", "empty_reply", t1, "x", ordinal=0),
        op("add_continuation", key(11), "keep_going", "kept_going", t1, "x" * 2001, ordinal=0),
        op("add_held_continuation", key(12), "usage_pause", "after_reset", t1, ordinal=1),
        op("note_continuation", key(13), "subagent_parent", "subagent_stop", t1, "left_alone"),
        op("continuation", key(10)), op("continuations"), op("continuations", pending=None),
        op("continuations", capability="empty_response", thread_id=t1, pending=False),
        op("last_continuation", t1, "empty_response"), op("continuation_moved", key(10), "sent",
                                                          queue_id="0a1b2c3d-0003-7000-8000-000000000002"),
        op("continuation_moved", key(10), "delivered"), op("continuation_moved", key(10), "delivered"),
        op("hold_continuation", key(12), "usage_pause"), op("doubt_continuation", key(12), "usage_pause"),
        op("end_continuations", "turned_off"), op("release_unlaunched_continuations", 60),
        op("set_keep_going", t1, 2), op("set_keep_going", t1, 11), op("keep_going", t1), op("keep_going_used", t1),
        op("keep_going_used", t1), op("keep_going_used", t1), op("stop_keep_going", "by_person"), op("keep_going"),
        # prompts
        op("add_prompt", t1, "First", "after_turn"), op("add_prompt", t1, "At a time", "at_time", at=CLOCK + 600),
        op("add_prompt", t1, "Daily", "recurring", at=CLOCK + 60, every="day", occurrences=3),
        op("add_prompt", t1, "  ", "after_turn"), op("add_prompt", t1, "x", "after_turn", while_running="wait"),
        op("add_prompt", t1, "x", "at_time", at=CLOCK - 3600), op("add_prompt", t2, "x", "after_turn", depends=True),
        op("add_prompt", t1, "x", "recurring", at=CLOCK + 60, every="day", occurrences=31),
        op("prompts"), op("prompt", 1), op("prompt", "1"),
        op("edit_prompt", 2, 16, "Changed", "at_time", at=CLOCK + 900),
        op("edit_prompt", 2, 99, "Changed", "at_time", at=CLOCK + 900),
        op("change_prompt", 1, state="ready", record_id=key(14)), op("change_prompt", 1, words="x"),
        op("cancel_prompt", 2), op("cancel_prompt", 2), op("placed_prompt", 3),
        op("change_prompt", 3, state="held"), op("go_on_prompt", 3), at(CLOCK + 86400 * 2), op("go_on_prompt", 3),
        op("prompt_moved", key(14), "sent", queue_id="0a1b2c3d-0003-7000-8000-000000000003"),
        op("add_record", key(14), "prompt_queue", t1), op("prompt_moved", key(14), "delivered"),
        op("prompts", pending=None), op("prompts_in_flight"), op("release_unlaunched_prompts", 60),
        op("clear_done", [1, 1], 0), op("clear_done", [1], 0), op("end_prompts", "turned_off"),
        # meter, runs, chat
        op("save_meter", [{"bucket": "codex", "window_minutes": 300, "used_percent": 42.5, "reset_at": 1764010000},
                          {"bucket": "codex", "window_minutes": 300, "used_percent": 50, "reset_at": None},
                          {"bucket": "nope", "window_minutes": 300, "used_percent": 1}, "junk"]),
        op("mark_meter", "codex", 300, warned_reset_at=1764010000), op("mark_meter", "codex", 300),
        op("mark_meter", "codex", 300, clear_pause=True), op("meter"),
        op("run_started", key(15), "headless_run", t1, started_at=CLOCK, ends_by=CLOCK + 600),
        op("run_owed", key(16), "model_fallback", t1, "gpt-5", started_at=CLOCK, ends_by=CLOCK + 600),
        op("run_owed", key(16), "model_fallback", t1, "", started_at=CLOCK, ends_by=CLOCK + 600),
        op("run_stop", key(15)), op("run_ended", key(15), "completed"), op("run_ended", key(15), "completed"),
        op("runs"), op("runs", live=False, limit="5"), op("runs_owed", "model_fallback"), op("run_restored", key(16)),
        op("prune_runs", CLOCK + 86400 * 10), op("add_chat", t1, "Hi there", key(17)),
        op("add_chat", t1, "Again", key(17)), op("chats"), op("chat_by_record", key(17)),
        op("chat_moved", key(17), "sent"), op("chat_moved", key(17), "delivered"), op("chat_moved", key(17), "nope"),
        op("add_chat", t2, "Third", key(18)), op("cancel_chat", "by_person", thread_id=t2), op("chats", pending=True),
        # analytics, restarts, opens, account, steers
        op("ingest_file", "0123456789abcdef", t1, size=100, offset=50, changed_ns=5, project_key=None,
           days={"2025-11-24": [1, 2, 3, 4, 5]}),
        op("ingest_file", "0123456789abcdef", t1, size=100, offset=100, changed_ns=6, project_key="fedcba9876543210",
           days={"2025-11-24": [1, 0, 0, 0, 1], "2025-11-25": [7, 7, 7, 7, 7]}),
        op("ingest_file", "XYZ", t1, size=1, offset=1, changed_ns=1, project_key=None, days={}),
        op("token_files"), op("token_days"), op("token_days", "2025-11-25"),
        op("add_samples", [{"bucket": "codex", "window_minutes": 300, "used_percent": 12, "reset_at": 5}]),
        op("usage_samples"), op("restart_noted", 3, True), op("restart_noted", "3", True), op("restarts_since", 0),
        op("add_open", t1, key(19)), op("settle_open", 1, "loaded"), op("settle_open", 1, "loaded"),
        op("settle_open", 1, "opened"), op("opens", 0), op("opens", "0"),
        op("save_account_seen", "0123456789abcdef", None), op("save_account_seen", "XYZ", None), op("account_seen"),
        op("end_account_seen"), op("end_account_seen"),
        op("add_steer", t1, "Go faster", "0a1b2c3d-0004-7000-8000-000000000001", bounds=[86400, 3, 2]),
        op("add_steer", t1, "Again", "0a1b2c3d-0004-7000-8000-000000000002", bounds=[86400, 3, 2]),
        op("add_steer", t1, "   ", "0a1b2c3d-0004-7000-8000-000000000002"),
        op("claim_steer", 1), op("claim_steer", 1), op("settle_steer", 1, "accepted"),
        op("add_steer", t2, "Other", "0a1b2c3d-0004-7000-8000-000000000003"),
        op("settle_steer", 2, "refused", "turned_off"), op("settle_steer", 2, "accepted", "turned_off"),
        op("end_requested_steers", "turned_off"), op("settle_cut_short"), op("steers"), op("waiting_steers"),
        # everything off
        op("all_off", actor="dashboard", reason="all_off"), op("all_off", actor="dashboard", reason="all_off"),
        op("meta"), op("arming"), op("journal", limit=5000),
    ]
    return ops


class ScriptDiff(Base):
    def test_script(self):
        twin = Twin()
        try:
            ops = script_ops()
            answers = self.same(twin, request(ops), "script")
            refused = sum(1 for answer in answers if "raised" in answer)
            # Each implementation reads the other's file.
            reads = READS + [op("continuations", pending=None), op("prompts", pending=None), op("chats"),
                             op("runs", live=False), op("rules"), op("journal", limit=5000)]
            crossed = Twin()
            try:
                import shutil
                shutil.rmtree(crossed.python)
                shutil.rmtree(crossed.rust)
                shutil.copytree(twin.rust, crossed.python)
                shutil.copytree(twin.python, crossed.rust)
                python, rust = crossed.run(request(reads))
                self.assertEqual([advstore.comparable(a) for a in python], [advstore.comparable(b) for b in rust],
                                 "the reference reading Rust's file and Rust the reference's")
            finally:
                crossed.close()
            RECORD.append("script: %d calls (%d refused alike) gave equal answers and the same file; the reference "
                          "read car-adv's file and car-adv the reference's, %d reads equal"
                          % (len(ops), refused, len(reads)))
        finally:
            twin.close()


class ChoicesDiff(Base):
    """The writes that need the generation the page read, each against the right one (the script's are mostly stale)."""

    def test_choices(self):
        ops = [op("move", "usage_meter", "shadow", actor="dashboard"),
               op("set_option", "usage_meter", "poll_minutes", 30, generation=1, actor="dashboard"),
               op("set_option", "usage_meter", "poll_minutes", 30, generation=2, actor="dashboard"),
               op("options", "usage_meter"),
               op("set_option", "usage_meter", "poll_minutes", 15, generation=3, actor="dashboard"),
               op("set_option", "usage_meter", "poll_minutes", 31, generation=4, actor="dashboard"),
               op("set_option", "usage_wrap_up", "window_weekly", 1, generation=5, actor="dashboard"),
               op("set_option", "usage_wrap_up", "window_weekly", 1, generation=5, actor="dashboard"),
               op("set_wording", "usage_wrap_up", "wrap_custom_weekly", "Wrap up", generation=6, actor="dashboard"),
               op("add_rule", "weirdCode", 500, 503, "server_5xx", generation=7, actor="dashboard"),
               op("add_rule", "weirdCode", 503, 504, "server_5xx", generation=8, actor="dashboard"),
               op("add_rule", "otherCode", None, None, "timeout", generation=8, actor="dashboard"),
               op("remove_rule", 1, generation=9, actor="dashboard"),
               op("move", "usage_meter", "armed", actor="dashboard", generation=10),
               op("set_keep_on", "usage_meter", True, actor="dashboard", generation=11),
               op("set_keep_on", "usage_meter", True, send_again=True, actor="dashboard", generation=12),
               op("set_keep_on", "usage_meter", False, actor="dashboard"),
               op("set_global_hourly", 7, generation=14, actor="dashboard"),
               op("move_set", [["usage_wrap_up", "armed", 1, "0.130.0", None]], actor="dashboard", generation=15,
                  keep=["usage_wrap_up"]),
               op("meta"), op("options", "usage_meter"), op("options", "usage_wrap_up"), op("wordings", "usage_wrap_up"),
               op("rules"), op("arming"), op("journal"),
               op("set_option", "usage_meter", "poll_minutes", 15, generation=16, actor="dashboard")]
        twin = Twin()
        try:
            answers = self.same(twin, request(ops), "choices")
            self.assertEqual(answers[-8]["ok"]["generation"], 16, "the case's generations went stale")
            RECORD.append("choices: %d writes against the generation each read, and the reads after: equal" % len(ops))
        finally:
            twin.close()

    def test_watch_limit(self):
        ops = [op("move", "usage_meter", "shadow", actor="dashboard")]
        ops += [op("note", "would_have", capability="usage_meter", answer="hold", at=CLOCK + index) for index in range(300)]
        ops += [op("journal", limit=5000), {"watchlog": "view", "args": ["usage_meter"]}]
        twin = Twin()
        try:
            self.same(twin, request(ops), "watch limit")
            RECORD.append("watch limit: 300 would_have lines of one capability through a prune pass: equal")
        finally:
            twin.close()


# ------------------------------------------------------------------------------------------- views
def scoped(capability, name, *args, on=True, verdict=None, armed=None, **kwargs):
    return {"scoped": {"capability": capability, "on": on, "verdict": verdict, "armed": armed}, "name": name,
            "args": list(args), "kwargs": kwargs}


def scoped_ops() -> list:
    ops = [op("move", "reset_message", "armed", actor="dashboard"), op("move", "usage_meter", "armed",
                                                                         actor="dashboard"),
           op("add_reset_rule", "reset_message", "codex", 300, 1, thread_id=THREAD, words="Go on", record_id=key(1)),
           op("change_rule", 1, state="ready")]
    for on in (True, False, None):
        ops += [scoped("reset_message", "count", "sent", on=on), scoped("reset_message", "sample", "sent", on=on),
                scoped("idle_update_check", "stamp", "last_check", 5, on=on),
                scoped("idle_update_check", "stamped", "last_check", on=on),
                scoped("idle_update_check", "unstamp", "last_check", on=on),
                scoped("usage_meter", "since", on=on), scoped("usage_meter", "stored_on", on=on),
                scoped("structured_rules", "rules", on=on), scoped("usage_meter", "rules", on=on),
                scoped("usage_meter", "options", on=on), scoped("usage_meter", "options_of", "usage_wrap_up", on=on),
                scoped("usage_meter", "passed", "MW", on=on, verdict={"MW": "pass"}),
                scoped("usage_meter", "failed", "MW", on=on, verdict={"MW": "pass"}),
                scoped("usage_meter", "armed", "usage_analytics", on=on, armed={"usage_analytics": True}),
                scoped("reset_message", "resets.on", on=on), scoped("reset_message", "resets.windows", on=on),
                scoped("reset_message", "resets.set_reading", on=on, read_at=CLOCK),
                scoped("reset_credit", "resets.end_rule", 1, "done", "delivered", on=on),
                scoped("reset_message", "resets.carry_message", 1, on=on),
                scoped("reset_message", "resets.carried_message", 1, False, on=on),
                scoped("reset_message", "resets.message_expired", 1, on=on),
                scoped("empty_response", "continuations.add", key(2), "empty_reply", THREAD, "Continue", ordinal=0,
                       on=on),
                scoped("empty_response", "continuations.mine", on=on),
                scoped("empty_response", "continuations.get", key(2), on=on),
                scoped("keep_going", "continuations.get", key(2), on=on),
                scoped("prompt_queue", "prompts.end", "turned_off", on=on),
                scoped("usage_meter", "meter.save", [{"bucket": "codex", "window_minutes": 300, "used_percent": 5,
                                                      "reset_at": None}], on=on),
                scoped("usage_pause", "meter.save", [], on=on),
                scoped("usage_pause", "meter.mark", "codex", 300, paused_reset_at=7, on=on),
                scoped("usage_wrap_up", "meter.mark", "codex", 300, paused_reset_at=7, on=on),
                scoped("headless_run", "runs.started", key(3), THREAD, started_at=CLOCK, ends_by=CLOCK + 60, on=on),
                scoped("headless_run", "runs.live", on=on),
                scoped("usage_analytics", "analytics.files", on=on),
                scoped("usage_meter", "analytics.sample", [{"bucket": "codex", "window_minutes": 300,
                                                            "used_percent": 5}], on=on,
                       armed={"usage_analytics": True}),
                scoped("crash_restart", "restarts.noted", 1, True, on=on),
                scoped("usage_meter", "restarts.noted", 1, True, on=on),
                scoped("codex_chat", "chat.pending", on=on), scoped("codex_chat", "chat.conversation_off", key(9),
                                                                    on=on),
                scoped("open_to_send", "opens.add_open", THREAD, key(4), on=on),
                scoped("steer_send", "steers.settle", 1, "refused", "turned_off", on=on),
                scoped("steer_send", "steers.claim", 1, on=on),
                scoped("account_switch", "account.save", "0123456789abcdef", None, on=on),
                scoped("account_switch", "account.seen", on=on), scoped("usage_meter", "account.seen", on=on)]
    return ops


class ScopedDiff(Base):
    def test_views(self):
        twin = Twin()
        try:
            ops = scoped_ops()
            self.same(twin, request(ops), "views")
            RECORD.append("views: %d calls of Scoped and the eleven handles, on, off and unset: equal" % len(ops))
        finally:
            twin.close()


# ------------------------------------------------------------------------------------------- damage
def damaged(statements):
    def make(home: Path) -> None:
        historic("STATEMENTS")(home)
        connection = sqlite3.connect(str(home / "config" / "advanced" / "advanced.sqlite"), isolation_level=None)
        connection.execute("PRAGMA ignore_check_constraints=ON")
        for statement in statements:
            connection.execute(statement)
        connection.close()
    return make


DAMAGE = {
    "unknown words": [
        "INSERT INTO arming VALUES ('usage_meter', 'sideways', 1.0, 'robot', 'whim', 'two', 7, 'unmeasured,bogus')",
        "INSERT INTO journal (at, capability, code, reason, actor, point, answer) VALUES "
        "(5.0, 'nope', 'weird', 'x', 'y', 'z', 'w')",
        "INSERT INTO options VALUES ('usage_meter', 'poll_minutes', 'many')",
        "INSERT INTO overrides VALUES ('%s', 'send_now', 'whatever', 1.0, NULL)" % key(1),
    ],
    "wrong types": [
        "INSERT INTO arming VALUES ('keep_going', 'armed', 'yesterday', 'dashboard', NULL, 1.5, 12, NULL)",
        "INSERT INTO spend (at, capability, thread_id, interruption_id) VALUES ('soon', 'usage_meter', 5, NULL)",
        "INSERT INTO keep_going VALUES ('%s', 'three', 1, 1.0, 'on', NULL, NULL)" % THREAD,
        "INSERT INTO meter VALUES ('codex', 300, 'full', 1, 1.0, NULL, NULL, NULL)",
        "UPDATE meta SET generation = 2.5",
    ],
}


class DamagedDiff(Base):
    def test_damaged(self):
        reads = READS + [op("move", "keep_going", "off", actor="dashboard"), op("set_keep_going", THREAD, 2),
                         op("keep_going_used", THREAD), op("meta"), op("set_option", "usage_meter", "poll_minutes", 30,
                                                                       generation=2, actor="dashboard")]
        for label, statements in DAMAGE.items():
            twin = Twin(damaged(statements))
            try:
                self.same(twin, request(reads), label)
            finally:
                twin.close()
        RECORD.append("damaged: %d hand-edited files (words the vocabulary does not hold, wrong types), %d calls "
                      "each: equal" % (len(DAMAGE), len(reads)))


class PruneDiff(Base):
    def test_prune(self):
        old = CLOCK - 100 * 86400
        ops = [op("move", "usage_meter", "shadow", actor="dashboard", at=old)]
        for index in range(300):
            ops.append(op("note", "would_have" if index % 3 else "armed", capability="usage_meter",
                          answer="hold", at=old + index))
        ops += [op("add_record", key(1), "prompt_queue", THREAD, at=old), op("move_record", key(1), "cancelled",
                                                                               at=old)]
        ops += [op("note", "armed", capability="usage_meter", at=CLOCK + index) for index in range(256)]
        ops += [op("journal", limit=5000), op("records_on", THREAD), {"watchlog": "view", "args": ["usage_meter"]},
                {"watchlog": "exported"}]
        twin = Twin()
        try:
            self.same(twin, request(ops), "prune")
            RECORD.append("prune: %d journal lines across two passes at old and new times: the same file" % len(ops))
        finally:
            twin.close()


# ------------------------------------------------------------------------------------------- the ledger
CORE = r'''
import json, sys
from pathlib import Path
from codex_auto_resume import config
from codex_auto_resume.store import Store
home = Path(sys.argv[1])
paths = config.Paths(str(home))
paths.ensure()
store = Store(paths.state_dir, migrate=True, clock=lambda: 1764000000.0)
records = json.loads(sys.argv[2])
for record in records:
    store.register(record, 1764000000.0 - 3600)
for name, change in json.loads(sys.argv[3]):
    store._connection.execute(change)
store.close()
'''


def core_home(records, changes=(), advanced=()):
    def make(home: Path) -> None:
        done = advref.run(CORE, str(home), json.dumps(records), json.dumps(list(changes)),
                                profile=home.parent / "profile")
        if done.returncode != 0:
            raise AssertionError(done.stderr.decode("utf-8", "replace")[-2000:])
        if advanced:
            historic("STATEMENTS", *advanced)(home)
    return make


def core_record(index, thread_id=THREAD):
    import released
    return {"thread_id": thread_id, "turn_id": released.turn(index), "completed_at": 110.0, "started_at": 105.0,
            "ordinal": index, "interruption_id": key(100 + index), "reset_at": None, "limit_type": "x",
            "uncertain": False, "category": "usage_limit"}


class LedgerDiff(Base):
    def test_claims(self):
        armed = ["INSERT INTO arming (capability, state, since, actor) VALUES ('send_now', 'armed', %r, 'dashboard')"
                 % (CLOCK - 100,),
                 "INSERT INTO arming (capability, state, since, actor) VALUES ('once_more_when_unsure', 'armed', %r, "
                 "'dashboard')" % (CLOCK - 100,),
                 "INSERT INTO arming (capability, state, since, actor) VALUES ('prompt_queue', 'armed', %r, "
                 "'dashboard')" % (CLOCK - 100,),
                 "INSERT INTO arming (capability, state, since, actor) VALUES ('queue_for_open', 'armed', %r, "
                 "'dashboard')" % (CLOCK - 100,),
                 "INSERT INTO overrides VALUES ('%s', 'send_now', 'force_once', %r, NULL)" % (key(100), CLOCK - 10),
                 "INSERT INTO records VALUES ('%s', 'prompt_queue', '%s', 'waiting', %r, NULL, 0, NULL, NULL, 0)"
                 % (key(50), OTHER, CLOCK - 50),
                 "INSERT INTO prompts (thread_id, words, trigger, occurrences, sent_count, depends, position, state, "
                 "record_id, created_at, due_at) VALUES ('%s', 'hi', 'after_turn', 1, 0, 0, 0, 'ready', '%s', %r, %r)"
                 % (OTHER, key(50), CLOCK - 50, CLOCK - 50)]
        record = {"interruption_id": key(100), "thread_id": THREAD}
        ledger = []
        for words in ({}, {"send_now": ["send_now"]}, {"send_now": ["send_now"]}, {"once_more_when_unsure": ["resend"]},
                      {"once_more_when_unsure": ["resend"]}, {"queue_for_open": ["queue_for_open"]},
                      {"queue_for_open": ["queue_for_open"]}, {"nope": []}, ["send_now", "once_more_when_unsure"]):
            ledger.append({"ledger": "claim", "record": record, "now": CLOCK, "acted": words})
        ledger += [{"ledger": "claim", "record": record, "now": CLOCK, "acted": {"send_now": []},
                    "verified": ["send_now"]},
                   {"ledger": "claim", "record": record, "now": CLOCK, "acted": {}, "unvouched": True},
                   {"ledger": "claim", "record": "not a dict", "now": CLOCK, "acted": {"send_now": []}},
                   {"ledger": "record", "record": {"record_id": key(50), "thread_id": OTHER, "phase": "claim"},
                    "now": CLOCK},
                   {"ledger": "record", "record": {"record_id": key(50), "thread_id": OTHER, "phase": "claim"},
                    "now": CLOCK},
                   {"ledger": "record", "record": {"record_id": key(50), "thread_id": OTHER, "phase": "launch"},
                    "now": CLOCK + 1},
                   {"ledger": "record", "record": {"record_id": key(51), "thread_id": OTHER, "phase": "claim"},
                    "now": CLOCK},
                   op("spent", "send_now", THREAD), op("journal"), op("overrides_for", key(100)),
                   # who paid for the send, and whether a channel or a route did (CHANNELS: P5 and P16)
                   op("payers", key(100), None), op("channel_paid", key(100), None)]
        twin = Twin(core_home([core_record(0)], advanced=armed))
        try:
            self.same(twin, request(ledger), "ledger")
        finally:
            twin.close()
        nofile = Twin(core_home([core_record(0)]))
        try:
            self.same(nofile, request(ledger[:3]), "ledger with no advanced file")
        finally:
            nofile.close()
        RECORD.append("ledger: %d claims and records on core's schema-5 state with this file attached (and 3 with "
                      "none): equal answers and both files the same" % len(ledger))

    def test_race(self):
        setup = core_home([], advanced=[
            "INSERT INTO arming (capability, state, since, actor) VALUES ('prompt_queue', 'armed', %r, 'dashboard')"
            % (CLOCK - 100,)] + [
            "INSERT INTO records VALUES ('%s', 'prompt_queue', '%s', 'waiting', %r, NULL, 0, NULL, NULL, 0)"
            % (key(60 + index), THREAD, CLOCK - 50) for index in range(2)] + [
            "INSERT INTO prompts (thread_id, words, trigger, occurrences, sent_count, depends, position, state, "
            "record_id, created_at, due_at) VALUES ('%s', 'hi', 'after_turn', 1, 0, 0, %d, 'ready', '%s', %r, %r)"
            % (THREAD, index, key(60 + index), CLOCK - 50, CLOCK - 50) for index in range(2)])
        results = []
        for first, second in (("python", "python"), ("rust", "rust"), ("python", "rust"), ("rust", "python")):
            for round_ in range(3):
                twin = Twin(setup)
                try:
                    import shutil
                    shutil.rmtree(twin.rust)
                    go = twin.folder / "go"
                    processes = []
                    for index, side in enumerate((first, second)):
                        ready = twin.folder / ("ready-%d" % index)
                        claim = {"ledger": "record", "record": {"record_id": key(60 + index), "thread_id": THREAD,
                                                                "phase": "claim"}, "now": CLOCK}
                        body = request([claim], ready=str(ready), go=str(go))
                        start = advstore.popen_reference if side == "python" else advstore.popen_rust
                        processes.append((start(twin.python, body), ready))
                    deadline = time.time() + 60
                    while not all(ready.exists() for _process, ready in processes) and time.time() < deadline:
                        time.sleep(0.01)
                    go.write_text("go")
                    answers = []
                    for process, _ready in processes:
                        out, err = process.communicate(timeout=120)
                        self.assertEqual(process.returncode, 0, err.decode("utf-8", "replace")[-2000:])
                        answers.append(json.loads(out.decode("utf-8").splitlines()[0]))
                    words = sorted(str(answer.get("ok")) for answer in answers)
                    self.assertEqual(words, ["DEFER", "hold"], "%s+%s round %d: %r" % (first, second, round_,
                                                                                      answers))
                    results.append(words)
                finally:
                    twin.close()
        RECORD.append("claim race: %d rounds (python+python, rust+rust, python+rust, rust+python): one record of "
                      "this edition's granted every round, the other held" % len(results))


# ------------------------------------------------------------------------------------------- accounts, pictures
SIGN_IN = list(b'{"tokens": {"id_token": "x"}, "auth_mode": "chatgpt"}')


def profiles(name, *args, **kwargs):
    return {"profiles": name, "args": list(args), "kwargs": kwargs}


class ProfilesDiff(Base):
    def test_profiles(self):
        ops = [profiles("ids"), profiles("view"), profiles("intent"), profiles("attempts"),
               profiles("save", SIGN_IN, "Person@Example.com", "plus"),
               profiles("save", SIGN_IN, "person@example.com", "pro"), profiles("save", SIGN_IN, "no address", "plus"),
               profiles("save", list(b"[]"), "a@b.c", "plus"), profiles("save", list(b"{}"), "a@b.c", "plus"),
               profiles("save", SIGN_IN, "second@example.org", None), profiles("ids"), profiles("view"),
               profiles("find", "PERSON@example.com"), profiles("find", 5), profiles("get", "0000000000000001"),
               profiles("get", "nope"), profiles("get", "0000000000000099"),
               profiles("update", "0000000000000001", used_at=1764000000, exhausted_until=CLOCK + 100,
                        usage={"read_at": 5, "available": True, "most_used": 40.5,
                               "five_hour": {"used": 40.5, "resets_at": 7}, "weekly": {"used": "x"}},
                        unread_at=6, seen_at=7),
               profiles("update", "0000000000000001", nope=1), profiles("view"),
               profiles("begin", "0000000000000001", "0000000000000002", put_in=SIGN_IN, previous=SIGN_IN,
                        to_email="second@example.org"),
               profiles("intent"), profiles("end"), profiles("intent"), profiles("note_attempts", [5, 6, 7]),
               profiles("attempts"), profiles("mark_switched", "Person@Example.com"), profiles("last_switch_at"),
               profiles("switched_to", "person@example.com", 0), profiles("switched_to", "person@example.com", CLOCK + 1),
               profiles("note_read_now", CLOCK), profiles("read_now_at"), profiles("delete", "0000000000000002"),
               profiles("delete", "zz"), profiles("delete_all"), profiles("ids"),
               profiles("fn.mask", "someone@example.com"), profiles("fn.mask", "a@b"), profiles("fn.mask", "a@@b"),
               profiles("fn.mask", " x@y.z "), profiles("fn.is_id", "0123456789abcdef\n"),
               profiles("fn.is_id", "0123456789ABCDEF"),
               profiles("fn.reading", {"read_at": 1, "available": 1, "most_used": float("inf"), "five_hour": None})]
        ops = [entry for entry in ops if entry["profiles"] != "fn.reading"] + [
            profiles("fn.reading", {"read_at": 1, "available": 1, "most_used": 2, "five_hour": None})]
        twin = Twin()
        try:
            self.same(twin, request(ops), "profiles")
            RECORD.append("profiles: %d calls over sealed scratch files (the seal a stand-in both use; the unsealed "
                          "contents compared): equal" % len(ops))
        finally:
            twin.close()


def sealed_profiles(texts: dict):
    """Profiles written as a hand or another build could leave them: sealed with the stand-in, JSON as given."""
    def make(home: Path) -> None:
        folder = home / "accounts"
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in texts.items():
            (folder / name).write_bytes(b"SEALED:" + text.encode("utf-8"))
    return make


def _auth(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


LENIENT = {
    "0000000000000a01.dat": '{"auth": "%s", "email": "nan@example.com", "plan": "plus", "used_at": NaN, '
                            '"exhausted_until": Infinity, "failed_at": null, "seen_at": -Infinity, "unread_at": 1e999, '
                            '"usage": {"read_at": 5, "available": true, "most_used": NaN, "five_hour": {"used": NaN, '
                            '"resets_at": Infinity}, "weekly": {"used": -Infinity}}}' % _auth('{"tokens": {"id": "x"}}'),
    "0000000000000a02.dat": '{"auth": "%s", "email": "a\\ud800b@ex\\udc00ample.com", "plan": "\\udfff", "used_at": 5}'
                            % _auth('{"tokens": "\\ud83d"}'),
    "0000000000000a03.dat": '{"auth": "%s", "email": "deep@example.com", "plan": "plus", "usage": %s1%s}'
                            % (_auth('{"a": %s1%s}' % ("[" * 1500, "]" * 1500)), "[" * 900, "]" * 900),
    "0000000000000a05.dat": '{"auth": "%s", "email": "big@example.com", "used_at": %s}' % (_auth('{"a": 1}'), "9" * 5000),
    "0000000000000a06.dat": '{"auth": "%s", "email": "auth-nan@example.com"}' % _auth('{"tokens": NaN, "n": -Infinity}'),
    "switch.intent": '{"from": "0000000000000a01", "to": "0000000000000a02", "at": NaN, "step": "swap", "tries": Infinity}',
    "switch.last": '{"email": "a\\ud800b@ex\\udc00ample.com", "at": 5}',
}
DEEP = {
    "0000000000000a01.dat": LENIENT["0000000000000a01.dat"],
    "0000000000000a04.dat": '{"auth": "%s", "email": "deeper@example.com", "usage": %s1%s}'
                            % (_auth('{"a": 1}'), "[" * 100000, "]" * 100000),
    "usage.read": '{"at": %s1%s}' % ("[" * 100000, "]" * 100000),
    "switch.intent": '{"at": %s1%s}' % ("[" * 100000, "]" * 100000),
}


class LenientProfilesDiff(Base):
    """What `json.loads` reads that serde would not: NaN, the infinities, half a surrogate pair, an int past the
    float's range and of 5,000 digits, deep nesting - read, shown, found, rewritten and refused as the tag does."""

    def test_lenient(self):
        ids = ["0000000000000a0%d" % index for index in (1, 2, 3, 5, 6)]
        ops = [profiles("ids"), profiles("view"), profiles("intent"), profiles("last_switch_at")]
        ops += [profiles("get", each) for each in ids]
        ops += [profiles("find", "NAN@example.com"), profiles("find", "A\ud800B@EX\udc00AMPLE.COM"),
                profiles("find", "nobody@example.com"), profiles("switched_to", "A\ud800B@EX\udc00AMPLE.COM", 0),
                profiles("fn.mask", "a\ud800b@ex\udc00ample.com"),
                profiles("update", "0000000000000a01", seen_at=7), profiles("get", "0000000000000a01"),
                profiles("update", "0000000000000a02", plan="pro"), profiles("get", "0000000000000a02"),
                profiles("save", list(b'{"tokens": NaN}'), "fresh@example.com", None), profiles("view")]
        ops = [json.loads(json.dumps(entry).replace("\\ud800", "\ud800").replace("\\udc00", "\udc00"))
               for entry in ops]
        twin = Twin(sealed_profiles(LENIENT))
        try:
            self.same(twin, request(ops), "lenient profiles")
        finally:
            twin.close()
        deep = [profiles("ids"), profiles("view"), profiles("get", "0000000000000a04"), profiles("find", "x@y.z"),
                profiles("read_now_at"), profiles("intent"), profiles("delete_all"),
                profiles("save", list(b'{"a": %s1%s}' % (b"[" * 100000, b"]" * 100000)), "x@y.z", None)]
        twin = Twin(sealed_profiles(DEEP))
        try:
            self.same(twin, request(deep), "deep profiles")
        finally:
            twin.close()
        RECORD.append("lenient profiles: %d calls over sealed files holding NaN, the infinities, half surrogate pairs, "
                      "5,000-digit ints and nesting of 900 and 1,500 levels, and %d more where the nesting is too "
                      "deep (RecursionError): equal" % (len(ops), len(deep)))


PNG = list(b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
GIF = list(b"GIF89a" + b"\1" * 10)


def images(name, *args, **kwargs):
    return {"images": name, "args": list(args), "kwargs": kwargs}


class ImagesDiff(Base):
    def test_images(self):
        def setup(home: Path) -> None:
            folder = _advanced_folder(home)
            (folder / ("image-7-1-1-%s.png" % ("c" * 32))).write_bytes(bytes(PNG))
            (folder / ("image-8-1-2-%s.gif" % ("d" * 32))).write_bytes(bytes(GIF))
            (folder / ("image-08-1-1-%s.png" % ("e" * 32))).write_bytes(bytes(PNG))
            (folder / ("image-9-%s.webp" % ("f" * 32))).write_bytes(b"RIFF0000WEBPxxxx")
            (folder / "unrelated.txt").write_bytes(b"x")
            (home / "picture.png").write_bytes(bytes(PNG))
            (home / "text.txt").write_bytes(b"hello")
        ops = [images("kind", PNG), images("kind", GIF), images("kind", list(b"RIFF0000WEBP")), images("kind", [1, 2]),
               images("read", "relative.png"), images("read", ""), images("read", 5),
               images("of", 7), images("of", 8), images("count", 8), images("kept", [7, 8]), images("problem", 7),
               images("problem", 8), images("stage", PNG, "png"), images("stage", GIF, "gif"),
               images("place", 7, ["c" * 32, "%032x" % 1]), images("of", 7), images("place", 7, ["nope"]),
               images("place", 7, ["c" * 32, "c" * 32]), images("drop", ["%032x" % 2]),
               images("sweep", [7]), images("of", 8)]
        twin = Twin(setup)
        try:
            for name in ("picture.png", "text.txt"):
                ops.insert(5, {"images": "read", "args": [str(twin.source / name)], "kwargs": {}})
            self.same(twin, request(ops), "images")
            RECORD.append("images: %d calls over a folder of copies (kinds, reads, places, stages, sweeps): equal"
                          % len(ops))
        finally:
            twin.close()


class WatchlogDiff(Base):
    def test_watchlog(self):
        ops = [op("move", "usage_meter", "shadow", actor="dashboard", at=CLOCK - 40 * 86400),
               op("move", "keep_going", "shadow", actor="dashboard")]
        for index in range(110):
            ops.append(op("note", "would_have", capability="usage_meter", point="tick" if index % 2 else "gates",
                          answer=["hold", "text", "nope", "admit"][index % 4], at=CLOCK - (index % 45) * 86400))
        ops += [op("note", "would_have", capability="keep_going", answer="hold"),
                {"watchlog": "view", "args": ["usage_meter"]}, {"watchlog": "view", "args": ["keep_going"]},
                {"watchlog": "view", "args": ["nope"]}, {"watchlog": "view", "args": [5]}, {"watchlog": "exported"}]
        twin = Twin()
        try:
            self.same(twin, request(ops), "watch log")
            RECORD.append("watch log: views and the export over %d would_have lines: equal" % len(ops))
        finally:
            twin.close()


if __name__ == "__main__":
    unittest.main()

"""Advanced state version 8, the v0.6.19 stage's (plans/v0619-design/D-groundwork.md, section 1): ten tables and a
column at the end of `prompts`, `wordings` freed of the CHECK on its keys as v0.6.17 freed `options`, every table
bounded by the journal's pass - and the file still marked readable from 7, so v0.6.17's and v0.6.18's own code use it
as it is, while v0.6.16's, which reads no mark, refuses it and writes nothing.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, StateError, journal, session  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, PromptReason, PromptTrigger,  # noqa: E402
                                                   WhileRunning)

ROOT = Path(__file__).resolve().parents[2]
MARKED_7 = schema_module.MARK | 7
KEY = "%064x" % 41
DIGEST16 = "0123456789abcdef"
# The readers of version 7 that read the mark, by their tags (v0.6.18 once it is tagged); and the one that does not.
READERS = ("v0.6.17", "v0.6.18")
UNMARKED_READER = "v0.6.16"


def dump(path, *, without=()) -> dict:
    """Every row of every table but `without`, sorted: what "every row kept" compares."""
    with contextlib.closing(sqlite3.connect(path)) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted(map(tuple, connection.execute("SELECT * FROM %s" % name)), key=repr)
                for name in names if name not in without}


def header(path) -> tuple:
    """(user_version, application_id)."""
    with contextlib.closing(sqlite3.connect(path)) as connection:
        return (connection.execute("PRAGMA user_version").fetchone()[0],
                connection.execute("PRAGMA application_id").fetchone()[0])


def sql_of(path, table) -> str:
    with contextlib.closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]


class V8Case(StateCase):
    def version_7(self, *, marked=False):
        """A version-7 file as v0.6.16 made it - or, `marked`, as v0.6.17 and v0.6.18 leave it: `options` freed and the
        mark set - holding a row in `arming`, `options`, `spend`, `journal`, `wordings`, `chat_messages`, a run and a
        waiting prompt with its words."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_V7:
                connection.execute(statement)
            if marked:
                for statement in schema_module.FREE_OPTIONS:
                    connection.execute(statement)
            connection.execute("INSERT INTO arming VALUES ('test_wake','armed',?,'dashboard',NULL,1,NULL,NULL)",
                               (self.now,))
            connection.execute("INSERT INTO options VALUES ('test_wake', 'keep_on', 1)")
            connection.execute("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               (self.now, ac.THREAD))
            connection.execute("INSERT INTO journal (at, code) VALUES (?, 'other')", (self.now,))
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Stop soon.', 1.0)")
            connection.execute("INSERT INTO chat_messages (thread_id, words, state, record_id, created_at) "
                               "VALUES (?, 'mine', 'waiting', ?, 1.0)", (ac.THREAD, "%064x" % 5))
            connection.execute("INSERT INTO headless_runs (interruption_id, capability, thread_id, started_at, ends_by) "
                               "VALUES (?, 'headless_run', ?, 1.0, 2.0)", (KEY, ac.THREAD))
            connection.execute("INSERT INTO prompts (thread_id, words, trigger, occurrences, sent_count, depends, "
                               "position, state, created_at, due_at) VALUES (?, 'my words', 'after_turn', 1, 0, 0, 0, "
                               "'waiting', ?, ?)", (ac.THREAD, self.now, self.now))
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError, msg="version 7 knew no turn_running"):
                connection.execute("UPDATE prompts SET reason='turn_running'")
            with self.assertRaises(sqlite3.IntegrityError, msg="nor a fleet wording"):
                connection.execute("INSERT INTO wordings VALUES ('fleet_view', 'fleet_alias', 'desk', 1.0)")
        self.assertEqual(header(path), (7, MARKED_7 if marked else 0))
        return path

    def opened(self):
        """The file opened once - a read - and closed: what brings it to version 8."""
        state = self.state()
        state.arming()
        state.close()


class UpgradeTests(V8Case):
    def assert_upgraded(self, path, before):
        self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, MARKED_7),
                         "version 8 and every later step (v0.6.20: 9), still marked readable from 7")
        after = dump(path)
        for name, rows in before.items():
            with self.subTest(table=name):
                kept = after[name] if name != "prompts" else [row[:-1] for row in after[name]]
                self.assertEqual(kept, rows, "every row of every version-7 table kept")
        self.assertEqual([row[-1] for row in after["prompts"]], [WhileRunning.QUEUE],
                         "a prompt already queued goes into Codex's queue as it always did")
        for name in schema_module.V019_TABLES:
            self.assertEqual(after[name], [], name)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            self.assertFalse(schema_module.names_checked(connection))
            self.assertFalse(schema_module.wordings_checked(connection))
            connection.execute("UPDATE prompts SET reason='turn_running'")                     # the word version 8 added
            connection.execute("INSERT INTO wordings VALUES ('fleet_view', 'fleet_alias', 'desk', 1.0)")   # a free key

    def test_v0616s_file_is_brought_to_version_8_and_keeps_every_row(self):
        """Fails with the step reverted: the file would stay at version 7 - refused as malformed by this version."""
        path = self.version_7()
        before = dump(path)
        self.opened()
        self.assert_upgraded(path, before)

    def test_v0618s_marked_file_is_brought_to_version_8_the_same_way(self):
        path = self.version_7(marked=True)
        before = dump(path)
        self.opened()
        self.assert_upgraded(path, before)

    def test_a_file_of_stage_4s_version_before_takes_both_steps(self):
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_BEFORE_STAGE4:
                connection.execute(statement)
            connection.execute("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               (self.now, ac.THREAD))
            connection.commit()
        self.opened()
        self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, MARKED_7))
        self.assertEqual(len(dump(path)["spend"]), 1)

    def test_a_new_file_is_version_8_free_and_marked(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.close()
        self.assertEqual(header(state.path), (schema_module.SCHEMA_VERSION, MARKED_7))
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            self.assertFalse(schema_module.wordings_checked(connection))
        self.assertIn("turn_running", sql_of(state.path, "prompts"))

    def test_the_step_adds_ten_tables_and_one_column_and_remakes_only_prompts(self):
        self.assertEqual(set(schema_module.TABLES_V8) - set(schema_module.TABLES_V7), set(schema_module.V019_TABLES))
        self.assertEqual(len(schema_module.V019_TABLES), 10)
        self.assertEqual(schema_module.TABLES["prompts"], schema_module.TABLES_V7["prompts"] + ("while_running",))
        self.assertEqual({name for name in schema_module.TABLES_V7 if name != "prompts"
                          and schema_module.TABLES[name] != schema_module.TABLES_V7[name]}, set())
        dropped = [s for s in schema_module.UPGRADE_TO_V019 if s.startswith("DROP TABLE")]
        self.assertEqual(dropped, ["DROP TABLE prompts"])
        self.assertEqual((schema_module.V019_VERSION, schema_module.READABLE_FROM), (8, 7))
        # v0.6.20 adds one table on top (version 9, steer_send) and keeps the mark.
        self.assertEqual(schema_module.SCHEMA_VERSION, 9)

    def test_a_run_cut_short_leaves_the_version_7_file_whole(self):
        """The step and the freeing run in the opening's one transaction: cut short after `prompts` was dropped, the
        file is as it was, every row there; the next opening does it whole."""
        path = self.version_7(marked=True)
        before, made = dump(path), header(path)
        steps = schema_module.UPGRADE_TO_V019
        cut_at = steps.index("DROP TABLE prompts") + 1
        with patch.object(session, "UPGRADE_TO_V019", steps[:cut_at] + ("INSERT INTO no_such_table VALUES (1)",)):
            with self.assertRaises(StateError):
                self.state().arming()
        self.assertEqual((dump(path), header(path)), (before, made))
        self.opened()
        self.assert_upgraded(path, before)

    def test_wordings_are_freed_once_and_never_again(self):
        path = self.version_7(marked=True)
        self.opened()
        after = dump(path)
        with patch.object(session, "FREE_WORDINGS", ("SELECT no_such_column FROM wordings",)):
            self.opened()
        self.assertEqual(dump(path), after)


class CheckTests(V8Case):
    """Every word a column holds is one of a closed list, every id and digest of its shape: a hand-written row with
    anything else is refused by the file itself."""
    GOOD = {
        "usage_samples": "INSERT INTO usage_samples VALUES ('codex', 300, 1.0, 12.5, 1800000000)",
        "token_days": "INSERT INTO token_days VALUES ('2026-10-22', '%s', '%s', 1, 0, 2, 0, 1)" % (ac.THREAD, DIGEST16),
        "token_files": "INSERT INTO token_files VALUES ('%s', '%s', 10, 4, 5, 1.0)" % (DIGEST16, ac.THREAD),
        "outbox": "INSERT INTO outbox (channel, event, category, alias, at, tries, state) "
                  "VALUES ('ntfy', 'recovered', 'usage_limit', 'task 12', 1.0, 0, 'waiting')",
        "feed": "INSERT INTO feed VALUES (1, 1.0, 'operational', 'degraded', 2)",
        "remote": "INSERT INTO remote VALUES ('telegram', NULL, 0, NULL, '%s', 2.0)" % ("a" * 64),
        "opens": "INSERT INTO opens (thread_id, record_id, at, outcome) VALUES ('%s', '%s', 1.0, 'loaded')"
                 % (ac.THREAD, KEY),
        "restarts": "INSERT INTO restarts VALUES (1.0, 3221225477, 1)",
        "account_seen": "INSERT INTO account_seen VALUES (1, '%s', 'plus', 1.0)" % DIGEST16,
        "hook_claims": "INSERT INTO hook_claims VALUES ('%s', '%s', 1.0, 'blocked')" % (KEY, "b" * 64),
    }
    BAD = (
        "INSERT INTO usage_samples VALUES ('elsewhere', 300, 1.0, 12.5, NULL)",
        "INSERT INTO usage_samples VALUES ('codex', 300, 2.0, -1, NULL)",
        "INSERT INTO token_days VALUES ('22/10/2026', '%s', NULL, 1, 0, 2, 0, 1)" % ac.THREAD,
        "INSERT INTO token_days VALUES ('2026-10-22', 'not-a-thread', NULL, 1, 0, 2, 0, 1)",
        "INSERT INTO token_days VALUES ('2026-10-22', '%s', 'C:/work/project', 1, 0, 2, 0, 1)" % ac.THREAD,
        "INSERT INTO token_days VALUES ('2026-10-23', '%s', NULL, -1, 0, 2, 0, 1)" % ac.THREAD,
        "INSERT INTO token_files VALUES ('C:/sessions/x.jsonl', '%s', 10, 4, 5, 1.0)" % ac.THREAD,
        "INSERT INTO outbox (channel, event, at, tries, state) VALUES ('sms', 'recovered', 1.0, 0, 'waiting')",
        "INSERT INTO outbox (channel, event, at, tries, state) VALUES ('ntfy', 'anything', 1.0, 0, 'waiting')",
        "INSERT INTO outbox (channel, event, alias, at, tries, state) "
        "VALUES ('ntfy', 'test', 'My project', 1.0, 0, 'waiting')",
        "INSERT INTO outbox (channel, event, at, tries, state) VALUES ('ntfy', 'test', 1.0, 4, 'waiting')",
        "INSERT INTO outbox (channel, event, at, tries, state) VALUES ('ntfy', 'test', 1.0, 1, 'sent')",
        "INSERT INTO feed VALUES (2, 1.0, 'operational', NULL, 0)",
        "INSERT INTO feed VALUES (1, 1.0, 'fine', NULL, 0)",
        "INSERT INTO remote VALUES ('email', NULL, 0, NULL, NULL, NULL)",
        "INSERT INTO remote VALUES ('telegram', 1.0, 0, NULL, '%s', NULL)" % ("a" * 64),
        "INSERT INTO remote VALUES ('telegram', NULL, 6, NULL, NULL, NULL)",
        "INSERT INTO opens (thread_id, record_id, at, outcome) VALUES ('%s', '%s', 1.0, 'maybe')" % (ac.THREAD, KEY),
        "INSERT INTO restarts VALUES (2.0, 1, 2)",
        "INSERT INTO account_seen VALUES (1, 'someone@example.com', 'plus', 1.0)",
        "INSERT INTO account_seen VALUES (1, NULL, 'ultra', 1.0)",
        "INSERT INTO hook_claims VALUES ('%s', 'turn-1', 1.0, 'blocked')" % KEY,
        "INSERT INTO hook_claims VALUES ('%s', '%s', 1.0, 'continued')" % ("c" * 64, "d" * 64),
        "UPDATE prompts SET while_running='later'",
    )

    def test_a_row_of_the_closed_words_is_taken_and_anything_else_refused(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.add_prompt(ac.THREAD, "mine", PromptTrigger.AFTER_TURN)
        connection = self.raw(state)
        for table, statement in self.GOOD.items():
            with self.subTest(table=table):
                connection.execute(statement)
        connection.commit()
        for statement in self.BAD:
            with self.subTest(statement=statement[:60]), self.assertRaises(sqlite3.IntegrityError):
                connection.execute(statement)
        self.assertEqual(connection.execute("SELECT while_running FROM prompts").fetchall(), [("queue",)])


class PruneTests(V8Case):
    def prune(self, state, now):
        with state._transaction() as connection:
            state._prune(connection, now)

    def count(self, state, table):
        return self.raw(state).execute("SELECT count(*) FROM %s" % table).fetchone()[0]

    def test_each_table_is_bounded_by_the_journals_pass(self):
        """Fails with the pass's calls reverted: the old rows stay."""
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        day, now = 86400, self.now
        for at in (now - 91 * day, now - day):
            connection.execute("INSERT INTO usage_samples VALUES ('codex', 300, ?, 1.0, NULL)", (at,))
            connection.execute("INSERT INTO token_files VALUES (?, ?, 1, 1, 1, ?)",
                               ("%016x" % int(at), ac.THREAD, at))
            connection.execute("INSERT INTO hook_claims VALUES (?, ?, ?, 'passed')", ("%064x" % int(at), KEY, at))
        for name in ("2026-01-01", "2027-01-14"):        # 90 days before the tests' clock (2027-01-15) and after it
            connection.execute("INSERT INTO token_days VALUES (?, ?, NULL, 1, 1, 1, 1, 1)", (name, ac.THREAD))
        for at in (now - 8 * day, now - day):
            connection.execute("INSERT INTO outbox (channel, event, at, tries, state, finished_at) "
                               "VALUES ('ntfy', 'test', ?, 1, 'sent', ?)", (at, at))
            connection.execute("INSERT INTO opens (thread_id, record_id, at, outcome) VALUES (?, ?, ?, 'opened')",
                               (ac.THREAD, KEY, at))
            connection.execute("INSERT INTO restarts VALUES (?, 1, 1)", (at,))
        connection.execute("INSERT INTO feed VALUES (1, 1.0, 'outage', NULL, 1)")
        connection.execute("INSERT INTO account_seen VALUES (1, NULL, 'pro', 1.0)")
        connection.execute("INSERT INTO remote VALUES ('telegram', 1.0, 0, 7, NULL, NULL)")
        connection.commit()
        self.prune(state, now)
        for table in schema_module.V019_TABLES:
            with self.subTest(table=table):
                self.assertEqual(self.count(state, table), 1)
        self.assertEqual(self.raw(state).execute("SELECT day FROM token_days").fetchall(), [("2027-01-14",)])

    def test_the_row_bounds_cut_the_oldest_and_a_waiting_notice_last(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        for offset in range(5):
            at = self.now - 100 + offset
            connection.execute("INSERT INTO usage_samples VALUES ('codex', 300, ?, 1.0, NULL)", (at,))
            connection.execute("INSERT INTO opens (thread_id, record_id, at, outcome) VALUES (?, ?, ?, 'opened')",
                               (ac.THREAD, KEY, at))
            waiting = offset == 0
            connection.execute("INSERT INTO outbox (channel, event, at, tries, state, finished_at) "
                               "VALUES ('ntfy', 'test', ?, 0, ?, ?)",
                               (at, "waiting" if waiting else "sent", None if waiting else at))
        connection.commit()
        with patch.object(journal, "SAMPLES_LIMIT", 2), patch.object(journal, "OPENS_LIMIT", 3), \
                patch.object(journal, "OUTBOX_LIMIT", 2):
            self.prune(state, self.now)
        self.assertEqual([row[0] for row in self.raw(state).execute("SELECT at FROM usage_samples ORDER BY at")],
                         [self.now - 97, self.now - 96])
        self.assertEqual(self.count(state, "opens"), 3)
        self.assertEqual(sorted(row[0] for row in self.raw(state).execute("SELECT state FROM outbox")),
                         ["sent", "waiting"], "the waiting notice outlasts the sent ones")

    def test_the_bounds_are_the_designs(self):
        day = 86400
        self.assertEqual((journal.SAMPLES_MAX_AGE, journal.SAMPLES_LIMIT, journal.TOKENS_MAX_AGE), (90 * day, 20000,
                                                                                                    90 * day))
        self.assertEqual((journal.OUTBOX_MAX_AGE, journal.OUTBOX_LIMIT, journal.OPENS_MAX_AGE, journal.OPENS_LIMIT),
                         (7 * day, 500, 7 * day, 1000))
        self.assertEqual((journal.RESTARTS_MAX_AGE, journal.HOOK_CLAIMS_MAX_AGE), (7 * day, 90 * day))


class SimulatedReaderTests(V8Case):
    def test_a_version_7_reader_that_reads_the_mark_uses_a_version_8_file_as_it_is(self):
        """This version's code held to version 7's TABLES (as v0.6.17 and v0.6.18 are): it opens a version-8 file,
        reads and writes, and leaves its version, mark, tables and rows as they were. Fails with the mark not kept
        at 7: the file is refused as newer."""
        made = self.state()
        made.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        made.close()
        with contextlib.closing(sqlite3.connect(made.path)) as connection:
            connection.execute(CheckTests.GOOD["outbox"])
            connection.commit()
        with patch.object(session, "SCHEMA_VERSION", 7), patch.object(session, "TABLES", schema_module.TABLES_V7):
            older = self.state()
            self.assertEqual(older.arming()["test_wake"]["state"], ArmingState.SHADOW)
            prompt = older.add_prompt(ac.THREAD, "from an older reader", PromptTrigger.AFTER_TURN)
            older.move("test_wake", ArmingState.OFF, actor=Actor.DASHBOARD)
            older.close()
        self.assertEqual(header(made.path), (schema_module.SCHEMA_VERSION, MARKED_7))
        with contextlib.closing(sqlite3.connect(made.path)) as connection:
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            self.assertEqual(connection.execute("SELECT count(*) FROM outbox").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT while_running FROM prompts WHERE prompt_id=?",
                                                (prompt,)).fetchone(), ("queue",))


# Run by an older release's own sources against this home: everything it reads and writes of the advanced state, with
# its shipped registry. A refusal anywhere is "refused".
OLDER = """
import json, sys
sys.path[:0] = sys.argv[3:]
from pathlib import Path
from codex_auto_resume import config
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced.state import AdvancedState, StateError
state = AdvancedState(config.Paths(Path(sys.argv[1])), registry=REGISTRY, clock=lambda: 1.8e9)
out = {}
try:
    out["arming"] = {key: row["state"] for key, row in state.arming().items()}
    out["options"] = {str(key): value for key, value in state.options("queue_for_open").items()}
    out["wordings"] = sorted(state.wordings("usage_wrap_up"))
    out["prompts"] = [row["words"] for row in state.prompts(pending=None)]
    out["journal"] = len(state.journal())
    out["prompt"] = state.add_prompt(sys.argv[2], "from the older release", "after_turn")
    days = REGISTRY.get("queue_for_open").option("days").choices[-1]
    state.set_option("queue_for_open", "days", days, generation=state.meta()["generation"], actor="dashboard")
    with state._transaction() as connection:
        state._prune(connection, 1.8e9)
    out["after"] = {key: row["state"] for key, row in state.arming().items()}
except StateError as exc:
    out["refused"] = str(exc)
state.close()
print(json.dumps(out))
"""


class OlderReleaseTests(V8Case):
    """Install another version from a version-8 installation: v0.6.17 and v0.6.18 - each its own code, from its tag -
    use the file as it is; v0.6.16 refuses it as newer and writes nothing. Skipped where a tag is not in the checkout
    (v0.6.18's until it is published)."""

    def sources(self, ref):
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref, "--",
                                  "src/codex_auto_resume", "advanced/src/codex_auto_resume_advanced"],
                                 capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if archive.returncode != 0:
            self.skipTest("%s is not in this checkout" % ref)
        tree = tempfile.TemporaryDirectory()
        self.addCleanup(tree.cleanup)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(tree.name, filter="data")
        return Path(tree.name)

    def run_release(self, ref) -> dict:
        tree = self.sources(ref)
        ran = subprocess.run([sys.executable, "-I", "-c", OLDER, str(self.home), ac.THREAD, str(tree / "src"),
                              str(tree / "advanced" / "src")], capture_output=True, text=True, timeout=120,
                             env=dict(os.environ, CODEX_AR_EDITION="advanced"), cwd=tree,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return json.loads(ran.stdout)

    def version_8(self):
        """A version-8 file this version made from a version-7 one, holding a row of every version-7 table the fixture
        fills, a row in two of version 8's own, and the fleet's wording under its free key."""
        path = self.version_7(marked=True)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO arming VALUES ('queue_for_open','armed',?,'dashboard',NULL,1,NULL,NULL)",
                               (self.now,))
            connection.commit()
        self.opened()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute(CheckTests.GOOD["outbox"])
            connection.execute(CheckTests.GOOD["restarts"])
            connection.execute("INSERT INTO wordings VALUES ('fleet_view', 'fleet_alias', 'desk', 1.0)")
            connection.execute("UPDATE prompts SET while_running='wait'")
            connection.commit()
        self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, MARKED_7))
        return path

    def test_each_reader_of_the_mark_uses_a_version_8_file_and_refuses_nothing(self):
        for ref in READERS:
            with self.subTest(release=ref):
                self.home = self.home.parent / ("home-" + ref)
                self.paths = config.Paths(self.home)
                path = self.version_8()
                before = dump(path, without=("prompts", "options", "journal", "arming", "meta", "spend"))
                found = self.run_release(ref)
                self.assertNotIn("refused", found)
                self.assertEqual(found["arming"]["queue_for_open"], "armed")
                self.assertEqual(found["wordings"], ["wrap_custom_weekly"])
                self.assertEqual(found["prompts"], ["my words"])
                self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, MARKED_7), "its version and mark left as they are")
                self.assertEqual(dump(path, without=("prompts", "options", "journal", "arming", "meta", "spend")),
                                 before, "version 8's tables and rows left as they are")
                with contextlib.closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
                    rows = connection.execute("SELECT words, while_running FROM prompts ORDER BY prompt_id").fetchall()
                self.assertEqual(rows, [("my words", "wait"), ("from the older release", "queue")])

    def test_v0616_refuses_a_version_8_file_and_writes_nothing(self):
        path = self.version_8()
        before = path.read_bytes()
        found = self.run_release(UNMARKED_READER)
        self.assertIn("refused", found)
        self.assertEqual(path.read_bytes(), before)


class WordTests(unittest.TestCase):
    def test_the_frozen_version_7_lists_are_the_vocabularys_before_version_8(self):
        """V7_PROMPT_REASONS and V7_WORDING_KEYS are what a version-7 file's CHECKs named: version 8 added exactly one
        word to each list a CHECK of it names, and the frozen ones are the rest."""
        self.assertEqual(set(PromptReason) - set(schema_module.V7_PROMPT_REASONS), {PromptReason.TURN_RUNNING})
        self.assertNotIn("turn_running", "".join(schema_module.STATEMENTS_V7))
        self.assertNotIn("fleet_alias", "".join(schema_module.STATEMENTS_V7))


if __name__ == "__main__":
    unittest.main()

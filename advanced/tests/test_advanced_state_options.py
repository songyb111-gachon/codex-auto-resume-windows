"""The advanced state as v0.6.17 keeps it (the owner's decision of 2026-10-18), its version still 7: `options` without
the CHECK on its names - the code alone keeps a name it does not know out, and passes one over that a later version
wrote - and the readable-from mark (schema.READABLE_FROM), by which a reader uses a later version's file that says it
may, and still refuses one marked newer than itself. v0.6.16's file is freed of the CHECK with every row kept, once, and
a run cut short leaves the old table whole. The way down: v0.6.16 compared columns alone and read v0.6.17's file with
every feature on; since version 8 (v0.6.19) the oldest release that reads this version's file is v0.6.17 (OLDEST_READER),
which reads the mark - and its own code still refuses a name it does not know.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
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
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume_advanced.registry import Option, Registry, RegistryError  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, Refused, StateError, session  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, KeepOn, OptionKey,  # noqa: E402
                                                   Refusal)

ROOT = Path(__file__).resolve().parents[2]
UNKNOWN = "tries"                                   # a name no version's vocabulary holds
MARKED_7 = schema_module.MARK | 7
# What a file is once this version opened it: its version (8 since v0.6.19, schema.SCHEMA_VERSION), marked readable from 7,
# `options` free.
OPENED = (schema_module.SCHEMA_VERSION, MARKED_7, False)
# The oldest release whose own code reads this version's file: v0.6.17, the first to read the mark. v0.6.16 read the file
# v0.6.17 made, version 7, as its own; since version 8 it refuses it as newer (test_advanced_schema_v8).
OLDEST_READER = "v0.6.17"


def dump(path) -> dict:
    """Every row of every table, sorted: what "every row kept" compares."""
    with contextlib.closing(sqlite3.connect(path)) as connection:
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: sorted(map(tuple, connection.execute("SELECT * FROM %s" % name)), key=repr) for name in names}


def kept(path) -> dict:
    """`dump`, less the tables version 8 added (v0.6.19), which a version-7 file had none of."""
    return {name: rows for name, rows in dump(path).items() if name not in schema_module.V019_TABLES}


def header(path) -> tuple:
    """(user_version, application_id, whether `options` still has its CHECK on names)."""
    with contextlib.closing(sqlite3.connect(path)) as connection:
        return (connection.execute("PRAGMA user_version").fetchone()[0],
                connection.execute("PRAGMA application_id").fetchone()[0], schema_module.names_checked(connection))


class OptionsCase(StateCase):
    def definition(self, **changes):
        fields = dict(options=(Option(OptionKey.ATTEMPTS, (1, 2, 3), 1),))
        fields.update(changes)
        return ac.definition(**fields)

    def opened(self):
        """The file opened once - a read - and closed: what frees `options` and marks the file."""
        state = self.state(self.definition())
        state.arming()
        state.close()

    def as_v0616_made_it(self, *rows):
        """A file exactly as v0.6.16 made it - version 7, no mark, `options` with its CHECK on names - holding a row in
        `arming`, `options` (a choice and Keep it on), `spend`, `journal`, `wordings` and `chat_messages`, and `rows`."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_V7:
                connection.execute(statement)
            connection.execute("INSERT INTO arming VALUES ('test_wake','armed',?,'dashboard',NULL,1,NULL,NULL)",
                               (self.now,))
            connection.execute("INSERT INTO options VALUES ('test_wake', 'attempts', 3)")
            connection.execute("INSERT INTO options VALUES ('test_wake', 'keep_on', 1)")
            connection.execute("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               (self.now, ac.THREAD))
            connection.execute("INSERT INTO journal (at, code) VALUES (?, 'other')", (self.now,))
            connection.execute("INSERT INTO wordings VALUES ('usage_wrap_up', 'wrap_custom_weekly', 'Stop soon.', 1.0)")
            connection.execute("INSERT INTO chat_messages (thread_id, words, state, record_id, created_at) "
                               "VALUES (?, 'mine', 'waiting', ?, 1.0)", (ac.THREAD, "%064x" % 5))
            for statement in rows:
                connection.execute(statement)
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError, msg="v0.6.16's CHECK on names"):
                connection.execute("INSERT INTO options VALUES ('test_wake', ?, 1)", (UNKNOWN,))
        self.assertEqual(header(path), (7, 0, True))
        return path


class FreeingTests(OptionsCase):
    def test_v0616s_file_is_freed_of_the_check_and_keeps_every_row_and_its_version(self):
        """Fails with the freeing reverted: the CHECK stays and the file has no mark."""
        path = self.as_v0616_made_it()
        before = dump(path)
        state = self.state(self.definition())
        self.assertEqual(state.arming()["test_wake"]["state"], ArmingState.ARMED)
        self.assertTrue(state.arming()["test_wake"]["keep_on"])
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 3})
        state.close()
        self.assertEqual(header(path), OPENED)
        self.assertEqual(schema_module.READABLE_FROM, 7, "marked readable from 7: v0.6.17 on reads the file as it is")
        self.assertEqual(kept(path), before, "every row of every table kept, and no table less")
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            connection.execute("INSERT INTO options VALUES ('test_wake', ?, 1)", (UNKNOWN,))   # no CHECK on names
            with self.assertRaises(sqlite3.IntegrityError, msg="the value's CHECK stays"):
                connection.execute("INSERT INTO options VALUES ('test_wake', 'workers', 0)")

    def test_a_new_file_is_made_free_and_marked(self):
        state = self.state(self.definition())
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.close()
        self.assertEqual(header(state.path), OPENED)

    def test_it_is_done_once_and_never_on_a_free_table(self):
        """Opened again, a freed file - or a new one, free from the start - is left as it is: the step is not taken."""
        path = self.as_v0616_made_it()
        self.opened()
        after = (dump(path), header(path))
        with patch.object(session, "FREE_OPTIONS", ("SELECT no_such_column FROM options",)), \
                patch.object(session, "MARKED", "SELECT no_such_column FROM options"):
            again = self.state(self.definition())
            self.assertEqual(again.options("test_wake"), {OptionKey.ATTEMPTS: 3})
            again.close()
            self.home = self.home.parent / "home-new"
            self.paths = config.Paths(self.home)
            new = self.state(self.definition())
            new.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
            new.close()
            self.assertEqual(self.state(self.definition()).arming()["test_wake"]["state"], ArmingState.SHADOW)
        self.assertEqual((dump(path), header(path)), after)

    def test_a_run_cut_short_leaves_the_old_table_whole_and_is_done_at_the_next_opening(self):
        """Done in the opening's one transaction: cut short after `options` was dropped, the file is as v0.6.16 left it,
        every row there; the next opening does it whole."""
        path = self.as_v0616_made_it()
        before = dump(path)
        steps = schema_module.FREE_OPTIONS
        self.assertTrue(steps[2].startswith("DROP TABLE options"))
        cut = steps[:3] + ("INSERT INTO no_such_table VALUES (1)",) + steps[3:]
        with patch.object(session, "FREE_OPTIONS", cut):
            with self.assertRaises(StateError):
                self.state(self.definition()).arming()
        self.assertEqual(header(path), (7, 0, True))
        self.assertEqual(dump(path), before)
        self.opened()
        self.assertEqual(header(path), OPENED)
        self.assertEqual(kept(path), before)


class NameTests(OptionsCase):
    def test_a_name_the_vocabulary_does_not_hold_is_refused_by_the_code(self):
        """With no CHECK on names, the code is what refuses one, twice: the registry takes no capability offering a
        choice the vocabulary does not hold (registry._option_problem), and were one let through, set_option still
        stores nothing under it. Fails with the vocabulary's check in set_option reverted: the row is written."""
        offering = self.definition(options=(Option(UNKNOWN, (1, 2, 3), 1),))
        with self.assertRaises(RegistryError):
            Registry((offering,))
        state = AdvancedState(self.paths, registry=SimpleNamespace(
            get=lambda capability: offering if capability == "test_wake" else None), clock=lambda: self.now)
        self.addCleanup(state.close)
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        with self.assertRaises(Refused) as raised:
            state.set_option("test_wake", UNKNOWN, 2, generation=state.meta()["generation"], actor=Actor.DASHBOARD)
        self.assertEqual(raised.exception.refusal, Refusal.OPTION_INVALID)
        with self.assertRaises(Refused):
            state.set_option("test_wake", OptionKey.WORKERS, 2, generation=state.meta()["generation"],
                             actor=Actor.DASHBOARD)                     # a word it holds, not offered here
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM options").fetchone()[0], 0)

    def test_a_name_a_later_version_wrote_is_passed_over(self):
        """A row under a name this version does not know - a later version's choice - is read past: the choices are
        the defaults and the stored ones offered, Keep it on reads from its own words only. Fails with the freeing
        reverted: the file refuses the row."""
        path = self.as_v0616_made_it()
        self.opened()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO options VALUES ('test_wake', ?, 2)", (UNKNOWN,))
            connection.execute("INSERT INTO options VALUES ('test_wake', 'a_later_choice', 1)")
            connection.commit()
        state = self.state(self.definition())
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 3})
        found = state.arming()["test_wake"]
        self.assertEqual((found["keep_on"], found["send_again"]), (True, False))
        state.set_keep_on("test_wake", False, actor=Actor.DASHBOARD, generation=state.meta()["generation"])
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            kept = {row[0] for row in connection.execute("SELECT choice FROM options")}
        self.assertEqual(kept, {"attempts", UNKNOWN, "a_later_choice"}, "a later version's rows are left as they are")
        self.assertNotIn(str(KeepOn.KEEP_ON), kept)

    def test_the_frozen_names_are_still_the_vocabularys(self):
        """V7_OPTION_WORDS is what v0.6.16's CHECK named: every word of it is still the vocabulary's."""
        self.assertEqual(set(schema_module.V7_OPTION_WORDS) - {str(word) for word in (*OptionKey, *KeepOn)}, set())


class DefaultTests(OptionsCase):
    """Choosing a choice's default stores nothing (v0.6.17): on the owner's PC the queue's days set back to 3 left an
    explicit `days=3` where there had been none, so a later release that changed the default would not have reached
    that person. The row is taken away instead; reading an absent row gives the default."""

    def set(self, state, key, value):
        return state.set_option("test_wake", key, value, generation=state.meta()["generation"], actor=Actor.DASHBOARD)

    def stored(self, state) -> dict:
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            return {row[0]: row[1] for row in connection.execute(
                "SELECT choice, value FROM options WHERE capability='test_wake'")}

    def test_the_default_chosen_stores_nothing_and_reads_as_the_default(self):
        state = self.state(self.definition())
        self.set(state, OptionKey.ATTEMPTS, 1)
        self.assertEqual(self.stored(state), {})
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 1})

    def test_another_value_is_stored_and_the_default_chosen_again_takes_its_row_away(self):
        """Fails with the fix reverted: the default is written as `attempts=1`."""
        state = self.state(self.definition())
        before = state.meta()["generation"]
        self.set(state, OptionKey.ATTEMPTS, 3)
        self.assertEqual(self.stored(state), {"attempts": 3})
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 3})
        after = self.set(state, OptionKey.ATTEMPTS, 1)
        self.assertEqual(self.stored(state), {}, "the default chosen again: no row")
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 1})
        self.assertEqual(after, before + 2, "each choice moves the generation as any choice does")

    def test_a_default_stored_before_is_left_as_it_is(self):
        # A guard for rows this change never touches, not a proof of it: it passes with the fix reverted. No migration.
        path = self.as_v0616_made_it("UPDATE options SET value=1 WHERE capability='test_wake' AND choice='attempts'")
        state = self.state(self.definition())
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 1})
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM options WHERE capability='test_wake' "
                                                "AND choice='attempts'").fetchone(), (1,))

    def test_every_choice_of_every_shipped_capability_stores_nothing_at_its_default(self):
        """Not only the queue's days: each choice the shipped registry offers, set to another value and back to its
        default, leaves no row - but the wrap-up's and the stop's window switches, whose missing row an opening fills
        from the meter's (session._carry_windows), so their default is written as any value is."""
        from codex_auto_resume_advanced.registry import REGISTRY
        from codex_auto_resume_advanced.state.choices import CARRIED
        state = AdvancedState(self.paths, registry=REGISTRY, clock=lambda: self.now)
        self.addCleanup(state.close)
        checked = 0
        for definition in REGISTRY:
            for option in definition.options:
                other = next(value for value in option.choices if value != option.default)
                for value in (other, option.default):
                    state.set_option(definition.id, option.key, value, generation=state.meta()["generation"],
                                     actor=Actor.DASHBOARD)
                with contextlib.closing(sqlite3.connect(state.path)) as connection:
                    row = connection.execute("SELECT value FROM options WHERE capability=? AND choice=?",
                                             (definition.id, str(option.key))).fetchone()
                with self.subTest(capability=definition.id, choice=str(option.key)):
                    self.assertEqual(row, (option.default,) if (definition.id, str(option.key)) in CARRIED else None)
                    self.assertEqual(state.options(definition.id)[option.key], option.default)
                checked += 1
        self.assertGreater(checked, 10)

    def test_a_carried_window_switch_chosen_on_stays_on_after_the_next_opening(self):
        """The wrap-up's five-hour switch turned off and back on, with the meter's off: were its row taken away, the
        next opening would carry the meter's off over to it."""
        from codex_auto_resume_advanced.registry import USAGE_METER, USAGE_PAUSE, USAGE_WRAP_UP
        registry = Registry((USAGE_METER, USAGE_WRAP_UP, USAGE_PAUSE))
        state = AdvancedState(self.paths, registry=registry, clock=lambda: self.now)
        for capability, value in (("usage_meter", 2), ("usage_wrap_up", 2), ("usage_wrap_up", 1)):
            state.set_option(capability, OptionKey.WINDOW_FIVE_HOUR, value, generation=state.meta()["generation"],
                             actor=Actor.DASHBOARD)
        state.close()
        state = AdvancedState(self.paths, registry=registry, clock=lambda: self.now)
        self.addCleanup(state.close)
        self.assertEqual(state.options("usage_wrap_up")[OptionKey.WINDOW_FIVE_HOUR], 1)
        self.assertEqual(state.options("usage_meter")[OptionKey.WINDOW_FIVE_HOUR], 2)


class MarkTests(OptionsCase):
    def later(self, readable, *, extra=True):
        """This version's file as a later version (8) would leave it, marked readable from `readable`: with a table of
        its own and a column at the end of `journal`, each holding a row."""
        state = self.state(self.definition())
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.close()
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            if extra:
                connection.execute("CREATE TABLE later_things (thing TEXT)")
                connection.execute("INSERT INTO later_things VALUES ('kept')")
                connection.execute("ALTER TABLE journal ADD COLUMN later TEXT")
                connection.execute("UPDATE journal SET later='kept'")
            connection.execute("PRAGMA application_id=%d" % (schema_module.MARK | readable))
            connection.execute("PRAGMA user_version=%d" % (schema_module.SCHEMA_VERSION + 1))
            connection.commit()
        return state.path

    def test_a_later_file_marked_readable_from_this_version_is_used_as_it_is(self):
        """Read and written, with nothing upgraded and nothing taken away: its version, its mark, its table and column
        stay. Fails with the mark not honoured: the file is refused as newer."""
        path = self.later(schema_module.SCHEMA_VERSION)
        state = self.state(self.definition())
        self.assertEqual(state.arming()["test_wake"]["state"], ArmingState.SHADOW)
        state.move("test_wake", ArmingState.OFF, actor=Actor.DASHBOARD)
        state.set_option("test_wake", OptionKey.ATTEMPTS, 2, generation=state.meta()["generation"],
                         actor=Actor.DASHBOARD)
        state.close()
        self.assertEqual(header(path)[:2], (schema_module.SCHEMA_VERSION + 1,
                                            schema_module.MARK | schema_module.SCHEMA_VERSION))
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT thing FROM later_things").fetchall(), [("kept",)])
            self.assertEqual(connection.execute("SELECT state FROM arming").fetchall(), [("off",)])
            self.assertIn("later", AdvancedState._tables(connection)["journal"])

    def test_an_older_reader_honours_the_mark(self):
        """A version-6 reader that reads the mark uses a version-7 file marked readable from 6, and refuses this
        version's own (marked 7) - as each later reader will judge a file newer than itself. Fails with the mark not
        honoured: the first is refused too."""
        state = self.state(self.definition())
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.close()
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("PRAGMA application_id=%d" % (schema_module.MARK | 6))
            connection.commit()
        with patch.object(session, "SCHEMA_VERSION", 6):
            older = self.state(self.definition())
            self.assertEqual(older.arming()["test_wake"]["state"], ArmingState.SHADOW)
            older.close()
            with contextlib.closing(sqlite3.connect(state.path)) as connection:
                connection.execute("PRAGMA application_id=%d" % MARKED_7)
                connection.commit()
            before = state.path.read_bytes()
            with self.assertRaises(StateError):
                self.state(self.definition()).arming()
            self.assertEqual(state.path.read_bytes(), before)

    def test_a_later_file_marked_newer_than_this_version_is_refused_and_left_untouched(self):
        path = self.later(schema_module.SCHEMA_VERSION + 1)
        before = path.read_bytes()
        for attempt in (lambda state: state.arming(),
                        lambda state: state.move("test_wake", ArmingState.ARMED, actor=Actor.DASHBOARD, revision=1)):
            with self.assertRaises(StateError):
                attempt(self.state(self.definition()))
        self.assertEqual(path.read_bytes(), before)

    def test_a_later_file_without_a_table_this_version_knows_is_refused(self):
        path = self.later(schema_module.SCHEMA_VERSION, extra=False)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("DROP TABLE chat_messages")
            connection.commit()
        with self.assertRaises(StateError):
            self.state(self.definition()).arming()

    def test_without_a_mark_a_file_is_readable_from_its_own_version(self):
        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            self.assertEqual(schema_module.readable_from(connection, 9), 9)
            connection.execute("PRAGMA application_id=%d" % (0x12340000 | 7))      # somebody else's application id
            self.assertEqual(schema_module.readable_from(connection, 9), 9)
            connection.execute("PRAGMA application_id=%d" % MARKED_7)
            self.assertEqual(schema_module.readable_from(connection, 9), 7)


# Run with the oldest reader's own sources (v0.6.16's until version 8): its shipped registry, reading the file this
# version freed and marked. One of its
# capabilities is armed there with a choice of its own; it reads both, refuses a name it does not know, and sets its
# own choice into the free table.
V0616 = """
import json, sys
sys.path[:0] = sys.argv[2:]
from pathlib import Path
from codex_auto_resume import config
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced.state import AdvancedState, Refused, StateError
state = AdvancedState(config.Paths(Path(sys.argv[1])), registry=REGISTRY, clock=lambda: 1.8e9)
out = {}
try:
    out["arming"] = {key: row["state"] for key, row in state.arming().items()}
    out["options"] = {str(key): value for key, value in state.options("queue_for_open").items()}
    try:
        state.set_option("queue_for_open", "tries", 2, generation=state.meta()["generation"], actor="dashboard")
        out["unknown"] = "written"
    except Refused as exc:
        out["unknown"] = str(exc.refusal)
    days = REGISTRY.get("queue_for_open").option("days").choices[-1]
    state.set_option("queue_for_open", "days", days, generation=state.meta()["generation"], actor="dashboard")
    out["set"] = days
except StateError as exc:
    out["refused"] = str(exc)
state.close()
print(json.dumps(out))
"""

# The oldest reader's own sources again, reading the units this version wrote for two claims of one record at one reading of the
# clock - the second at the next float above the first (state/spend.claim_time) - and paying a unit of its own.
V0616_SPEND = """
import json, sys
sys.path[:0] = sys.argv[3:]
from pathlib import Path
from codex_auto_resume import config
from codex_auto_resume_advanced.registry import REGISTRY
from codex_auto_resume_advanced.state import AdvancedState, StateError
asked = json.loads(sys.argv[2])
state = AdvancedState(config.Paths(Path(sys.argv[1])), registry=REGISTRY, clock=lambda: asked["now"])
out = {}
try:
    out["spent"] = state.spent("queue_for_open", asked["thread"], asked["now"])
    out["payers"] = {key: list(times) for key, times in state.payers(asked["key"], asked["at"]).items()}
    with state._transaction() as connection:
        state.record_spend(connection, "main", "queue_for_open", asked["thread"], asked["key"], asked["now"])
    out["after"] = state.spent("queue_for_open", asked["thread"], asked["now"])["capability_day"]
except StateError as exc:
    out["refused"] = str(exc)
state.close()
print(json.dumps(out))
"""


class DowngradeTests(OptionsCase):
    """Install another version back to the oldest release that reads this version's file (OLDEST_READER, which reads
    the mark and compares column names only) - v0.6.16 until version 8, whose file v0.6.16 refuses as newer."""

    def migrated(self):
        path = self.as_v0616_made_it(
            "INSERT INTO arming VALUES ('queue_for_open','armed',%r,'dashboard',NULL,1,NULL,NULL)" % self.now,
            "INSERT INTO options VALUES ('queue_for_open', 'days', 5)")
        self.opened()
        self.assertEqual(header(path), OPENED)
        return path

    def oldest(self):
        """The oldest reader's own sources, from its tag; skipped where the tag is not in the checkout."""
        archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", OLDEST_READER, "--",
                                  "src/codex_auto_resume", "advanced/src/codex_auto_resume_advanced"],
                                 capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if archive.returncode != 0:
            self.skipTest("the %s tag is not in this checkout" % OLDEST_READER)
        tree = tempfile.TemporaryDirectory()
        self.addCleanup(tree.cleanup)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(tree.name, filter="data")
        return Path(tree.name)

    def run_oldest(self, script, *arguments) -> dict:
        """`script` run by the oldest reader's own sources against this home, `arguments` after it: what it printed."""
        tree = self.oldest()
        ran = subprocess.run([sys.executable, "-I", "-c", script, str(self.home), *arguments, str(tree / "src"),
                              str(tree / "advanced" / "src")], capture_output=True, text=True, timeout=120,
                             env=dict(os.environ, CODEX_AR_EDITION="advanced"), cwd=tree,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return json.loads(ran.stdout)

    def test_the_oldest_readers_own_code_reads_the_units_of_two_claims_at_one_reading(self):
        """The second of two claims of one record at one reading of the clock writes its units at the next float
        above the first's - no column for it, so the oldest reader reads the file as it is: it counts both units, finds
        both paid for that send of the record (within its SAME_CLAIM), and pays a unit of its own beside them."""
        from codex_auto_resume_advanced.registry import REGISTRY
        path = self.migrated()
        key = "%064x" % 7
        state = AdvancedState(config.Paths(self.home), registry=REGISTRY, clock=lambda: self.now)
        self.addCleanup(state.close)
        for _ in range(2):
            with state._transaction() as connection:
                at = state.claim_time(connection, "main", key, self.now)
                state.record_spend(connection, "main", "queue_for_open", ac.THREAD, key, at)
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            times = [row[0] for row in connection.execute(
                "SELECT at FROM spend WHERE interruption_id=? ORDER BY spend_id", (key,))]
        self.assertEqual(len(times), 2)
        self.assertLess(times[0], times[1], "the second claim's units stand apart from the first's")
        found = self.run_oldest(V0616_SPEND, json.dumps({"now": self.now, "thread": ac.THREAD, "key": key,
                                                        "at": self.now}))
        self.assertNotIn("refused", found)
        self.assertEqual(found["spent"]["capability_day"], 2)
        self.assertEqual(found["spent"]["global_hour"], 3, "it counts units: these two and test_wake's")
        self.assertEqual(found["payers"], {"queue_for_open": [times[1], times[0]]})
        self.assertEqual(found["after"], 3)
        self.assertEqual(header(path), OPENED)

    def test_the_oldest_readers_own_code_reads_a_choice_set_back_to_its_default_as_the_default(self):
        """This version takes the queue's `days=5` away when a person sets it back to its default; the oldest reader's
        own code reads the default where there is no row, and the file is still this version's, marked."""
        from codex_auto_resume_advanced.registry import REGISTRY
        path = self.migrated()
        default = REGISTRY.get("queue_for_open").option("days").default
        state = AdvancedState(config.Paths(self.home), registry=REGISTRY, clock=lambda: self.now)
        self.addCleanup(state.close)
        state.set_option("queue_for_open", "days", default, generation=state.meta()["generation"],
                         actor=Actor.DASHBOARD)
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM options WHERE capability='queue_for_open' "
                                                 "AND choice='days'").fetchone())
        found = self.run_oldest(V0616)
        self.assertNotIn("refused", found)
        self.assertEqual(found["options"], {"days": default})
        self.assertEqual(found["unknown"], "option_invalid")
        self.assertEqual(header(path), OPENED)

    def test_the_oldest_readers_own_code_reads_the_freed_file_with_its_features_on(self):
        """Its features as they stood, its own choice read and set, a name it does not know refused by its code, and the
        file still this version's, marked readable from 7, every other row as it was. Fails with the mark moved past 7:
        the oldest reader refuses the file as newer."""
        path = self.migrated()
        tree = self.oldest()
        ran = subprocess.run([sys.executable, "-I", "-c", V0616, str(self.home), str(tree / "src"),
                              str(tree / "advanced" / "src")], capture_output=True, text=True, timeout=120,
                             env=dict(os.environ, CODEX_AR_EDITION="advanced"), cwd=tree,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(ran.returncode, 0, ran.stderr)
        found = json.loads(ran.stdout)
        self.assertNotIn("refused", found)
        self.assertEqual(found["arming"], {"queue_for_open": "armed"})
        self.assertEqual(found["options"], {"days": 5})
        self.assertEqual(found["unknown"], "option_invalid")
        self.assertEqual(header(path), OPENED)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            # Less the window switches the oldest reader carries over for its own wrap-up and stop on opening (session._carry_windows).
            stored = {(row[0], row[1]): row[2] for row in connection.execute("SELECT * FROM options")
                      if row[1] not in schema_module.WINDOW_CHOICES}
        self.assertEqual(stored, {("test_wake", "attempts"): 3, ("test_wake", "keep_on"): 1,
                                  ("queue_for_open", "days"): found["set"]})


if __name__ == "__main__":
    unittest.main()

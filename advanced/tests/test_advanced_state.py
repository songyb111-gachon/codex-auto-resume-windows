"""The advanced state: one file under a marked directory, closed words, bounded tables, and
nothing of it in core's state or settings.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
from enum import StrEnum
import inspect
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import cli, config, failures, settings, shortcut, startup  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, FailureForm  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.store.schema import _TABLES_V4  # noqa: E402
from codex_auto_resume_advanced import vocabulary  # noqa: E402
from codex_auto_resume_advanced.state import (ATTACHED, EVENT_LIMIT, EVENT_MAX_AGE,  # noqa: E402
                                              FILE_NAME, SCHEMA_VERSION, TABLES, AdvancedState,
                                              StateError)
from codex_auto_resume_advanced.registry import Option  # noqa: E402
from codex_auto_resume_advanced.state import Refused, StaleGeneration  # noqa: E402
from codex_auto_resume_advanced.state import choices as choices_module  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.state import journal as journal_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning,  # noqa: E402
                                                   JournalCode, OffReason, OptionKey, OverrideKind,
                                                   RecordState, Refusal)
from test_cli import FakeWinreg, _reset_logging  # noqa: E402

DAY = 86400


class StateCase(ac.AdvancedCase):
    def state(self, *definitions) -> AdvancedState:
        made = AdvancedState(self.paths, registry=ac.Registry(definitions or (ac.definition(),)),
                             clock=lambda: self.now)
        self.addCleanup(made.close)
        return made

    def raw(self, state):
        connection = sqlite3.connect(state.path)
        self.addCleanup(connection.close)
        return connection


class VocabularyTests(unittest.TestCase):
    def test_a_members_name_is_its_value_in_capitals_and_no_word_is_two_members(self):
        """The rule core's vocabularies keep (tests/test_vocabulary.py), so a port can
        generate the names."""
        lists = [value for _name, value in inspect.getmembers(vocabulary, inspect.isclass)
                 if issubclass(value, StrEnum) and value is not StrEnum]
        self.assertGreaterEqual(len(lists), 12)
        for words in lists:
            values = [member.value for member in words]
            self.assertEqual(len(values), len(set(values)), words.__name__)
            for member in words:
                with self.subTest(member=member):
                    self.assertEqual(member.name, member.value.upper().replace("-", "_"))

    def test_every_tripwire_is_a_reason_a_capability_is_off(self):
        self.assertEqual({str(word) for word in vocabulary.TRIPWIRES},
                         {"submission_unknown", "local_check_failed", "failed_here", "incompatible",
                          "hook_exception", "statement_changed", "measurement_failed"})


class FileTests(StateCase):
    def test_nothing_is_created_until_something_is_turned_on(self):
        state = self.state()
        self.assertEqual(state.arming(), {})
        self.assertEqual(state.meta(), {"generation": 0, "global_hourly": 12})
        self.assertEqual(state.journal(), [])
        self.assertEqual(state.all_off(actor=Actor.MCP, reason=OffReason.ALL_OFF), (0, 0))
        self.assertEqual(state.move("test_wake", ArmingState.OFF, actor=Actor.MCP,
                                    reason=OffReason.DISARMED), (False, 0))
        state.note(JournalCode.OTHER)
        self.assertFalse(self.home.exists())

    def test_a_read_makes_nothing_of_an_empty_file(self):
        """A crash between making the file and writing its schema leaves it empty. A read of it
        is a read of nothing - every capability off - and makes no schema and no marker, as a
        read never makes the file; the next write finishes making it."""
        self.paths.ensure()
        self.paths.advanced_dir.mkdir()
        empty = self.paths.advanced_dir / FILE_NAME
        empty.write_bytes(b"")
        marker = self.paths.advanced_dir / config.OWNER_MARKER
        state = self.state()
        self.assertEqual(state.meta(), {"generation": 0, "global_hourly": 12})
        self.assertEqual(state.arming(), {})
        self.assertEqual(state.journal(), [])
        self.assertEqual(empty.stat().st_size, 0)
        self.assertFalse(marker.exists())
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        self.assertEqual(state.arming()["test_wake"]["state"], ArmingState.SHADOW)
        self.assertTrue(marker.is_file())

    def test_it_lives_in_one_marked_directory_under_config(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        self.assertEqual(state.path, self.paths.state_dir / "advanced" / FILE_NAME)
        self.assertEqual(self.paths.advanced_dir, state.directory)
        self.assertTrue(self.paths.owns(self.paths.advanced_dir))
        self.assertEqual(sorted(path.name for path in self.paths.advanced_dir.iterdir()),
                         sorted([FILE_NAME, config.OWNER_MARKER]))
        connection = self.raw(state)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual({row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")},
            set(TABLES))

    def test_a_file_that_is_not_exactly_this_schema_is_refused_not_repaired(self):
        for damage in ("CREATE TABLE extra (x)", "ALTER TABLE journal ADD COLUMN words TEXT",
                       "PRAGMA user_version=4", "PRAGMA user_version=2", "PRAGMA user_version=1",
                       "DELETE FROM meta", "DROP TABLE samples", "ALTER TABLE samples ADD COLUMN words TEXT"):
            with self.subTest(damage):
                self.home = self.home.parent / ("home-%d" % abs(hash(damage)))
                self.paths = config.Paths(self.home)
                state = self.state()
                state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
                state.close()
                with contextlib.closing(sqlite3.connect(state.path)) as connection:
                    connection.execute(damage)
                    connection.commit()
                with self.assertRaises(StateError):
                    self.state().arming()

    def version_one(self, *rows):
        """A file exactly as v0.6.11-alpha made it - version 1, no `warnings` column - holding
        `rows` of the arming table, each (capability, state, revision, engine version)."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_V2:
                statement = statement.replace(",\n        %s" % schema_module.WARNINGS_COLUMN, "")
                connection.execute(statement.replace("user_version=2", "user_version=1"))
            for capability, state, revision, version in rows:
                connection.execute("INSERT INTO arming VALUES (?,?,?,?,?,?,?)",
                                   (capability, state, self.now, "dashboard", None, revision, version))
            connection.commit()
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        return path

    def test_a_version_one_file_is_brought_to_this_version_when_it_is_first_read(self):
        """v0.6.11-alpha made version 1, with no column for the warnings a person confirmed. It
        is upgraded - a read's opening too - and every row keeps what it held; a row from then
        confirmed no warning, the strictest reading of it."""
        path = self.version_one(("test_wake", "armed", 1, ac.ENGINE))
        state = self.state()
        row = state.arming()["test_wake"]
        self.assertEqual((row["state"], row["statement_revision"], row["engine_version"], row["warnings"]),
                         (ArmingState.ARMED, 1, ac.ENGINE, ()))
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(AdvancedState._tables(connection), TABLES)
        self.assertEqual(self.state().meta(), {"generation": 0, "global_hourly": 12})

    def version_two(self):
        """A file exactly as v0.6.11 and v0.6.12 made it - version 2, seven tables - with a row in
        each table a person's or a capability's past is kept in."""
        self.paths.advanced_dir.mkdir(parents=True)
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / FILE_NAME
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement in schema_module.STATEMENTS_V2:
                connection.execute(statement)
            connection.execute("INSERT INTO arming VALUES ('test_wake','shadow',?,'dashboard',NULL,1,NULL,"
                               "'unmeasured')", (self.now,))
            connection.execute("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               (self.now, ac.THREAD))
            connection.execute("INSERT INTO journal (at, code) VALUES (?, 'watched')", (self.now,))
            connection.execute("UPDATE meta SET generation=7, global_hourly=5")
            connection.commit()
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES_V2)
        return path

    def test_a_version_two_file_is_brought_to_version_three_and_keeps_every_row(self):
        """v0.6.11's and v0.6.12's file: the four tables of version 3 are added when it is first read,
        every row it held is kept, and the new tables start empty."""
        path = self.version_two()
        state = self.state()
        self.assertEqual(state.arming()["test_wake"]["warnings"], (ArmingWarning.UNMEASURED,))
        self.assertEqual(state.meta(), {"generation": 7, "global_hourly": 5})
        self.assertEqual(state.spent("test_wake", ac.THREAD)["conversation_day"], 1)
        self.assertEqual([line["code"] for line in state.journal()], ["watched"])
        self.assertEqual((state.rules(), state.failure_samples(0)), ([], []))
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(AdvancedState._tables(connection), TABLES)

    def test_a_version_one_file_takes_both_steps(self):
        path = self.version_one(("test_wake", "shadow", 1, None))
        self.assertEqual(self.state().arming()["test_wake"]["state"], ArmingState.SHADOW)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(AdvancedState._tables(connection), TABLES)

    def test_a_version_one_file_that_is_not_exactly_version_one_is_refused(self):
        path = self.version_one()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            connection.execute("ALTER TABLE journal ADD COLUMN words TEXT")
            connection.commit()
        with self.assertRaises(StateError):
            self.state().arming()

    def test_a_junction_out_of_the_home_is_never_opened_or_purged(self):
        """A junction is not a symbolic link to `is_symlink`, but it is one to `config.is_link`,
        so it is read as a link is - as no file of ours, which is every capability off - and
        writing through it is refused."""
        outside = self.home.parent / "outside"
        outside.mkdir()
        (outside / FILE_NAME).write_bytes(b"someone else's")
        (outside / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        self.paths.ensure()
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.paths.advanced_dir), str(outside)],
                              capture_output=True, text=True) if sys.platform == "win32" else None
        if made is None or made.returncode != 0:
            self.skipTest("could not create a junction here")
        state = self.state()
        self.assertFalse(state.exists())
        self.assertEqual(state.arming(), {})
        with self.assertRaises(StateError):
            state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        self.assertEqual(self.paths.owned_advanced_files(), [])
        self.assertEqual(sorted(path.name for path in outside.iterdir()),
                         sorted([FILE_NAME, config.OWNER_MARKER]))


    def test_a_junction_inside_the_home_is_a_link_all_the_same(self):
        """Confined is not enough: a junction to the home's own logs/ resolves inside the home,
        and `is_symlink` is False for it, so the state was opened, marked and written there."""
        self.paths.ensure()
        target = self.paths.logs_dir
        before = sorted(path.name for path in target.iterdir())
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(self.paths.advanced_dir), str(target)],
                              capture_output=True, text=True) if sys.platform == "win32" else None
        if made is None or made.returncode != 0:
            self.skipTest("could not create a junction here")
        state = self.state()
        with self.assertRaises(StateError):
            state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        self.assertFalse(state.exists())
        self.assertEqual(state.arming(), {})
        self.assertEqual(sorted(path.name for path in target.iterdir()), before)


class ThreadTests(StateCase):
    """One process's state serves every thread of that process. The MCP server asks P9 on its
    start-for-codex thread and answers tool calls on its main one; the watcher's engine and its
    tray popup share one plug. The connection belonged to whichever thread opened it, so a
    disarm from MCP was refused and the badge said nothing was on."""

    def elsewhere(self, work):
        errors, answers = [], []

        def run():
            try:
                answers.append(work())
            except Exception as exc:                   # the failure is the finding
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        self.assertEqual(errors, [])
        return answers[0]

    def test_a_state_opened_on_one_thread_is_read_and_written_on_another(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1, at=self.now)
        self.assertEqual(self.elsewhere(lambda: state.arming()["test_wake"]["state"]), ArmingState.SHADOW)
        moved = self.elsewhere(lambda: state.move("test_wake", ArmingState.OFF, actor=Actor.MCP,
                                                  reason=OffReason.DISARMED, at=self.now)[0])
        self.assertTrue(moved)
        self.assertEqual(state.arming()["test_wake"]["state"], ArmingState.OFF)

    def test_threads_at_once_each_have_a_whole_transaction(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1, at=self.now)
        before = len(state.journal())
        errors = []

        def writer():
            try:
                for _ in range(25):
                    state.note(JournalCode.OTHER, at=self.now)
                    state.arming()
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=writer) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(state.journal()) - before, 150)


class ClosedWordTests(StateCase):
    def test_a_decision_never_stores_a_word_it_does_not_know(self):
        state = self.state()
        for call in (lambda: state.move("test_wake", "on", actor=Actor.DASHBOARD),
                     lambda: state.move("test_wake", ArmingState.OFF, actor="somebody"),
                     lambda: state.move("test_wake", ArmingState.OFF, actor=Actor.MCP, reason="bored"),
                     lambda: state.move("not_a_capability", ArmingState.SHADOW, actor=Actor.DASHBOARD),
                     lambda: state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD,
                                        warnings=("failed_here", "worrying")),
                     lambda: state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD,
                                        warnings="failed_here"),
                     lambda: state.add_record(ac.KEY, "test_wake", "not a thread"),
                     lambda: state.add_record("short", "test_wake", ac.THREAD),
                     lambda: state.add_override(ac.KEY, "test_wake", "forever"),
                     lambda: state.move_record(ac.KEY, "done")):
            with self.subTest(call=call):
                with self.assertRaises(StateError):
                    call()

    def test_the_file_itself_refuses_a_word_the_code_does_not_know(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        for statement in ("UPDATE arming SET state='on'",
                          "INSERT INTO records VALUES ('%s','test_wake','%s','sent',1,NULL,0,NULL)"
                          % (ac.KEY, ac.THREAD),
                          "INSERT INTO overrides VALUES ('%s','test_wake','forever',1,NULL)" % ac.KEY,
                          "UPDATE meta SET global_hourly=13",
                          "UPDATE arming SET warnings='failed here'",
                          "UPDATE arming SET warnings='FAILED_HERE'"):
            with self.subTest(statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)

    def test_the_warnings_a_person_confirmed_are_kept_in_the_vocabularys_words_and_order(self):
        """Stored in its order whatever order they came in, read back the same way; none is
        NULL; and a word the vocabulary does not hold, put there by hand, was never confirmed -
        a row can only ever confirm less."""
        state = self.state()
        state.move("test_wake", ArmingState.ARMED, actor=Actor.DASHBOARD, revision=1,
                   engine_version=ac.ENGINE, warnings=["compat_unknown", "unmeasured"])
        connection = self.raw(state)
        self.assertEqual(connection.execute("SELECT warnings FROM arming").fetchone()[0],
                         "unmeasured,compat_unknown")
        self.assertEqual(state.arming()["test_wake"]["warnings"],
                         (ArmingWarning.UNMEASURED, ArmingWarning.COMPAT_UNKNOWN))
        connection.execute("UPDATE arming SET warnings='failed_here,made_up'")
        connection.commit()
        self.assertEqual(state.arming()["test_wake"]["warnings"], (ArmingWarning.FAILED_HERE,))
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1, warnings=())
        self.assertIsNone(connection.execute("SELECT warnings FROM arming").fetchone()[0])
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1,
                   warnings=("failed_here",))
        state.move("test_wake", ArmingState.OFF, actor=Actor.MCP, reason=OffReason.DISARMED)
        self.assertEqual(state.arming()["test_wake"]["warnings"], ())
        self.assertIsNone(connection.execute("SELECT warnings FROM arming").fetchone()[0])

    def test_turning_everything_off_forgets_what_was_confirmed(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1,
                   warnings=("failed_here",))
        self.assertEqual(state.all_off(actor=Actor.MCP, reason=OffReason.ALL_OFF)[0], 1)
        self.assertIsNone(self.raw(state).execute("SELECT warnings FROM arming").fetchone()[0])

    def test_the_journal_writes_other_for_a_word_it_does_not_know_and_reads_the_same_way(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.note("made_up", capability="test_wake")
        state.note("tw.woke", capability="test_wake")
        state.note("tw.dreamt", capability="test_wake")
        state.note(JournalCode.ACTED, capability="elsewhere", point="nowhere", answer="some words")
        codes = [(line["code"], line["capability"]) for line in state.journal()]
        self.assertEqual(codes, [("watched", "test_wake"), ("other", "test_wake"),
                                 ("tw.woke", "test_wake"), ("other", "test_wake"), ("acted", None)])
        last = state.journal()[-1]
        self.assertEqual((last["point"], last["answer"]), (None, None))
        self.raw(state).execute("UPDATE journal SET code='invented', actor='someone'") \
            .connection.commit()
        self.assertEqual({(line["code"], line["actor"]) for line in state.journal()}, {("other", None)})

    def test_the_sampler_counts_only_a_capabilitys_own_codes(self):
        state = self.state()
        self.assertFalse(state.sample("test_wake", "woke"))       # no file: nothing on to count
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        for code in ("woke", "woke", "slept", "dreamt"):
            state.sample("test_wake", code)
        self.now += DAY
        state.sample("test_wake", "woke")
        self.assertEqual(state.samples("test_wake"), {"woke": 3, "slept": 1})
        self.assertFalse(state.sample("elsewhere", "woke"))


class ChoicesCase(StateCase):
    def definition(self, **changes):
        fields = dict(points=frozenset({ac.Point.ADMISSION, ac.Point.GATES}), codes=("matched", "sampled"),
                      options=(Option(OptionKey.ATTEMPTS, (1, 2, 3), 1),), rules_editor=True, samples=True)
        fields.update(changes)
        return ac.definition(**fields)

    def armed_state(self, *definitions):
        state = self.state(*(definitions or (self.definition(),)))
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        return state

    def generation(self, state):
        return state.meta()["generation"]


SHAPE = {"code": "brandNewVariant", "status": 503, "form": FailureForm.TAGGED, "has_message": True}


class OptionTests(ChoicesCase):
    def test_every_choice_is_its_default_until_a_person_picks_another_it_offers(self):
        state = self.state(self.definition())
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 1})
        self.assertFalse(self.home.exists(), "a read makes nothing")
        after = state.set_option("test_wake", OptionKey.ATTEMPTS, 3, generation=0, actor=Actor.DASHBOARD)
        self.assertEqual((after, state.options("test_wake")), (1, {OptionKey.ATTEMPTS: 3}))
        for key, value in ((OptionKey.ATTEMPTS, 4), (OptionKey.ATTEMPTS, "3"), (OptionKey.CEILING_HOURS, 2),
                           ("tries", 2)):
            with self.subTest(key=key, value=value):
                with self.assertRaises(Refused) as raised:
                    state.set_option("test_wake", key, value, generation=after, actor=Actor.DASHBOARD)
                self.assertEqual(raised.exception.refusal, Refusal.OPTION_INVALID)
        with self.assertRaises(StaleGeneration):
            state.set_option("test_wake", OptionKey.ATTEMPTS, 2, generation=0, actor=Actor.DASHBOARD)
        self.assertIn(JournalCode.OPTION_CHANGED, [line["code"] for line in state.journal()])

    def test_a_stored_value_the_capability_no_longer_offers_reads_as_its_default(self):
        state = self.armed_state()
        state.set_option("test_wake", OptionKey.ATTEMPTS, 2, generation=self.generation(state),
                         actor=Actor.DASHBOARD)
        self.raw(state).execute("UPDATE options SET value=9").connection.commit()
        self.assertEqual(state.options("test_wake"), {OptionKey.ATTEMPTS: 1})


class RuleTests(ChoicesCase):
    def add(self, state, tag="brandNewVariant", low=None, high=None, category="timeout"):
        return state.add_rule(tag, low, high, category, generation=self.generation(state), actor=Actor.DASHBOARD)

    def refusal(self, state, *arguments, **keywords):
        with self.assertRaises(Refused) as raised:
            self.add(state, *arguments, **keywords)
        return raised.exception.refusal

    def test_a_rule_names_a_code_of_codexs_a_range_and_a_temporary_kind(self):
        state = self.armed_state()
        rule, after = self.add(state, low=500, high=599, category="server_5xx")
        self.assertEqual(after, self.generation(state))
        (stored,) = state.rules()
        self.assertEqual((stored["rule_id"], stored["tag"], stored["status_from"], stored["status_to"],
                          stored["category"], stored["known"]), (rule, "brandNewVariant", 500, 599, "server_5xx", False))
        self.assertEqual(state.remove_rule(rule, generation=after, actor=Actor.DASHBOARD), after + 1)
        self.assertEqual(state.rules(), [])
        with self.assertRaises(Refused) as raised:
            state.remove_rule(rule, generation=after + 1, actor=Actor.DASHBOARD)
        self.assertEqual(raised.exception.refusal, Refusal.UNKNOWN_RULE)

    def test_no_code_the_product_knows_and_none_that_may_name_a_decision_is_ever_a_rule(self):
        state = self.armed_state()
        for tag in failures.CODES:
            with self.subTest(tag=tag):
                self.assertEqual(self.refusal(state, tag), Refusal.RULE_KNOWN)
        for tag in ("policyRefused", "budgetExceeded", "approvalDenied", "userCancelled", "quotaGone",
                    "SignInAgain", "tokenExpired", "contextTooLong", "abortedByUser"):
            with self.subTest(tag=tag):
                self.assertEqual(self.refusal(state, tag), Refusal.RULE_DECISION)
        self.assertEqual(state.rules(), [])

    def test_each_other_way_a_rule_is_refused(self):
        state = self.armed_state()
        for arguments, refusal in (((("two words",), {}), Refusal.RULE_SHAPE),
                                   ((("9lives",), {}), Refusal.RULE_SHAPE),
                                   ((("x" * 65,), {}), Refusal.RULE_SHAPE),
                                   (((None,), {}), Refusal.RULE_SHAPE),
                                   (((), {"low": 99, "high": 200}), Refusal.RULE_RANGE),
                                   (((), {"low": 500, "high": 600}), Refusal.RULE_RANGE),
                                   (((), {"low": 503, "high": 500}), Refusal.RULE_RANGE),
                                   (((), {"low": 500}), Refusal.RULE_RANGE),
                                   (((), {"category": "usage_limit"}), Refusal.INVALID_REQUEST),
                                   (((), {"category": "terminal_auth"}), Refusal.INVALID_REQUEST)):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.refusal(state, *arguments[0], **arguments[1]), refusal)
        self.add(state, low=500, high=503)
        self.assertEqual(self.refusal(state, low=503, high=599), Refusal.RULE_OVERLAP)
        self.assertEqual(self.refusal(state), Refusal.RULE_OVERLAP, "no range covers every status")
        self.add(state, low=504, high=599, category="server_5xx")
        for index in range(8):
            self.add(state, "otherVariant%d" % index)
        self.assertEqual(len(state.rules()), choices_module.RULES_LIMIT)
        self.assertEqual(self.refusal(state, "oneMore"), Refusal.RULES_FULL)

    def test_a_rule_whose_code_the_product_comes_to_know_says_so(self):
        state = self.armed_state()
        self.add(state)
        self.raw(state).execute("UPDATE rules SET tag='serverOverloaded'").connection.commit()
        self.assertTrue(state.rules()[0]["known"])

    def test_the_file_refuses_a_rule_or_a_sample_the_code_would_not_write(self):
        state = self.armed_state()
        connection = self.raw(state)
        for statement in ("INSERT INTO rules (tag, category, created_at) VALUES ('two words', 'timeout', 1)",
                          "INSERT INTO rules (tag, category, created_at) VALUES ('fine', 'usage_limit', 1)",
                          "INSERT INTO rules (tag, status_from, category, created_at) VALUES ('fine', 500, 'timeout', 1)",
                          "INSERT INTO rules (tag, status_from, status_to, category, created_at) "
                          "VALUES ('fine', 503, 500, 'timeout', 1)",
                          "INSERT INTO samples (at, tag, form, has_words) VALUES (1, 'a b', 'tagged', 1)",
                          "INSERT INTO samples (at, form, has_words) VALUES (1, 'spoken', 1)",
                          "INSERT INTO samples (at, status, form, has_words) VALUES (1, 700, 'tagged', 1)",
                          "INSERT INTO samples (at, form, has_words, items_agent) VALUES (1, 'tagged', 1, -1)",
                          "INSERT INTO admissions VALUES ('%s', 'test_wake', 'hold', NULL, NULL, NULL, NULL, "
                          "NULL, 0, 1)" % ac.KEY,
                          "INSERT INTO options VALUES ('test_wake', 'tries', 2)",
                          "INSERT INTO options VALUES ('test_wake', 'attempts', 0)"):
            with self.subTest(statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)


class AdmissionTests(ChoicesCase):
    def test_taking_one_up_again_keeps_its_first_time_and_that_it_was_sampled(self):
        state = self.armed_state()
        self.assertTrue(state.admit(ac.KEY, "test_wake", Alternative.ADMIT, shape=SHAPE, at=self.now))
        self.assertTrue(state.taken(ac.KEY, "test_wake", "sampled", sample=SHAPE, at=self.now + 1))
        self.assertTrue(state.admit(ac.KEY, "test_wake", Alternative.AS_TIMEOUT, rule_id=4, at=self.now + 9))
        row = state.admission(ac.KEY)
        self.assertEqual((row["answer"], row["rule_id"], row["sampled"], row["created_at"], row["tag"]),
                         (Alternative.AS_TIMEOUT, 4, True, self.now, None))
        self.assertFalse(state.taken(ac.KEY, "test_wake", "sampled", sample=SHAPE), "once an interruption")
        self.assertEqual(len(state.failure_samples(0)), 1)

    def test_nothing_is_remembered_where_nothing_was_ever_turned_on(self):
        state = self.state(self.definition())
        self.assertFalse(state.admit(ac.KEY, "test_wake", Alternative.ADMIT))
        self.assertIsNone(state.admission(ac.KEY))
        self.assertFalse(self.home.exists())

    def test_a_word_that_takes_nothing_up_a_bad_shape_or_another_capabilitys_mark_is_refused(self):
        state = self.armed_state()
        for call in (lambda: state.admit(ac.KEY, "test_wake", Alternative.HOLD),
                     lambda: state.admit(ac.KEY, "test_wake", "admit please"),
                     lambda: state.admit(ac.KEY, "elsewhere", Alternative.ADMIT),
                     lambda: state.admit("short", "test_wake", Alternative.ADMIT),
                     lambda: state.admit(ac.KEY, "test_wake", Alternative.ADMIT, shape=dict(SHAPE, code="a b")),
                     lambda: state.admit(ac.KEY, "test_wake", Alternative.ADMIT, shape=dict(SHAPE, form="x")),
                     lambda: state.taken(ac.KEY, "test_wake", "woke")):
            with self.subTest(call=call):
                with self.assertRaises(StateError):
                    call()
        state.admit(ac.KEY, "test_wake", Alternative.ADMIT)
        self.assertFalse(state.taken("b" * 64, "test_wake", "sampled"))

    def test_a_sample_keeps_codes_numbers_forms_and_times_and_never_a_word(self):
        """The fixture's message reaches nothing: the shape a sample is made of has no field for it,
        and the file's bytes do not hold it."""
        state = self.armed_state()
        state.admit(ac.KEY, "test_wake", Alternative.ADMIT, shape=SHAPE)
        state.taken(ac.KEY, "test_wake", "sampled", at=self.now + 59, sample=dict(
            SHAPE, message="the secret words", items={"agentMessage": 2, "userMessage": 1, "other": 0},
            duration=12.5))
        (sample,) = state.failure_samples(0)
        self.assertEqual(sample, {"at": float(int((self.now + 59) // 60) * 60), "tag": "brandNewVariant",
                                  "status": 503, "form": "tagged", "has_words": 1, "items_agent": 2,
                                  "items_command": None, "items_file": None, "items_tool": None,
                                  "items_user": 1, "items_other": 0, "duration": 12.5})
        state.close()
        self.assertNotIn(b"secret", state.path.read_bytes())
        line = [line for line in self.state(self.definition()).journal() if line["code"] == "tw.sampled"]
        self.assertEqual(len(line), 1)

    def test_a_capability_that_does_not_sample_keeps_no_sample(self):
        state = self.armed_state(self.definition(samples=False))
        state.admit(ac.KEY, "test_wake", Alternative.ADMIT, shape=SHAPE)
        self.assertTrue(state.taken(ac.KEY, "test_wake", "matched", sample=SHAPE))
        self.assertEqual(state.failure_samples(0), [])

    def test_a_rules_hits_are_the_failures_it_took_up_that_core_went_on_with(self):
        state = self.armed_state()
        state.admit(ac.KEY, "test_wake", Alternative.AS_TIMEOUT, rule_id=1)
        state.admit("b" * 64, "test_wake", Alternative.AS_TIMEOUT, rule_id=1)
        self.assertEqual(state.rule_hits(0), {})
        state.taken(ac.KEY, "test_wake", "matched")
        self.assertEqual(state.rule_hits(0), {1: 1})
        self.assertEqual(state.rule_hits(self.now + 1), {})

    def test_a_capabilitys_view_reads_its_own_and_writes_nothing(self):
        own, other = self.definition(), self.definition(id="test_other", journal_prefix="to", rules_editor=False)
        state = self.state(own, other)
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        state.add_rule("brandNewVariant", None, None, "timeout", generation=1, actor=Actor.DASHBOARD)
        state.admit(ac.KEY, "test_wake", Alternative.ADMIT)
        mine, theirs = state.scoped("test_wake"), state.scoped("test_other")
        self.assertEqual(mine.admission(ac.KEY)["capability"], "test_wake")
        self.assertIsNone(theirs.admission(ac.KEY))
        self.assertEqual(len(mine.rules()), 1)
        self.assertEqual(theirs.rules(), [], "the rules are the one capability's that edits them")
        self.assertEqual(mine.options(), {OptionKey.ATTEMPTS: 1})
        self.assertEqual(mine.now(), self.now)
        for name in ("admit", "taken", "add_rule", "set_option", "move", "state", "path"):
            with self.subTest(name):
                with self.assertRaises(AttributeError):
                    getattr(mine, name)


class ChoiceWriteTests(ChoicesCase):
    """A person's choices and rules are written only in the Dashboard, against the generation it read,
    and each moves the generation on - so a page showing old choices cannot arm against new ones."""

    def test_only_the_dashboard_writes_a_choice_or_a_rule_and_a_stale_page_is_refused(self):
        runtime = self.runtime(self.definition())
        arming = runtime.arming
        for actor in (Actor.MCP, Actor.TRAY, Actor.CARD, "someone"):
            with self.subTest(actor=actor):
                self.assertEqual(arming.set_option("test_wake", OptionKey.ATTEMPTS, 2, generation=0, actor=actor)
                                 ["refusal"], Refusal.NOT_THE_DASHBOARD)
                self.assertEqual(arming.add_rule("brandNewVariant", None, None, "timeout", generation=0,
                                                 actor=actor)["refusal"], Refusal.NOT_THE_DASHBOARD)
                self.assertEqual(arming.remove_rule(1, generation=0, actor=actor)["refusal"],
                                 Refusal.NOT_THE_DASHBOARD)
        done = arming.set_option("test_wake", OptionKey.ATTEMPTS, 2, generation=0, actor=Actor.DASHBOARD)
        self.assertEqual((done["done"], done["generation"]), (True, 1))
        stale = self.arm(runtime, generation=0)
        self.assertEqual(stale["refusal"], Refusal.STALE_GENERATION, "armed against the old choice")
        self.assertEqual(arming.set_option("test_wake", OptionKey.ATTEMPTS, 3, generation=0,
                                           actor=Actor.DASHBOARD)["refusal"], Refusal.STALE_GENERATION)
        self.assertEqual(arming.set_option("test_wake", OptionKey.ATTEMPTS, 9, generation=1,
                                           actor=Actor.DASHBOARD)["refusal"], Refusal.OPTION_INVALID)
        self.assertEqual(arming.set_option("nobody", OptionKey.ATTEMPTS, 2, generation=1,
                                           actor=Actor.DASHBOARD)["refusal"], Refusal.UNKNOWN_CAPABILITY)
        added = arming.add_rule("brandNewVariant", None, None, "timeout", generation=1, actor=Actor.DASHBOARD)
        self.assertEqual((added["done"], added["generation"]), (True, 2))
        self.assertEqual(arming.add_rule("policyRefused", None, None, "timeout", generation=2,
                                         actor=Actor.DASHBOARD)["refusal"], Refusal.RULE_DECISION)
        self.assertEqual(arming.remove_rule(added["rule"], generation=2, actor=Actor.DASHBOARD)["generation"], 3)
        self.assertEqual(arming.remove_rule(added["rule"], generation=3, actor=Actor.DASHBOARD)["refusal"],
                         Refusal.UNKNOWN_RULE)

    def test_a_choice_needs_no_capability_on_and_no_policy_refuses_it(self):
        self.policy = ac.policy.Policy(forbid=True)
        runtime = self.runtime(self.definition())
        self.assertTrue(runtime.arming.set_option("test_wake", OptionKey.ATTEMPTS, 3, generation=0,
                                                  actor=Actor.DASHBOARD)["done"])
        self.assertEqual(runtime.state.options("test_wake"), {OptionKey.ATTEMPTS: 3})


class RecordTests(StateCase):
    def test_records_move_only_along_their_moves_and_a_claim_is_counted(self):
        state = self.state()
        self.assertTrue(state.add_record(ac.KEY, "test_wake", ac.THREAD))
        self.assertFalse(state.add_record(ac.KEY, "test_wake", ac.THREAD))
        self.assertFalse(state.move_record(ac.KEY, RecordState.FINISHED))
        # In flight is a claim, made inside core's, where core's rows are seen too - never a move.
        self.assertFalse(state.move_record(ac.KEY, RecordState.IN_FLIGHT))
        with Store(self.paths.state_dir) as core:
            with core._transaction() as connection:
                self.assertTrue(state.claim_record(connection, ac.KEY, self.now))
            self.assertTrue(state.move_record(ac.KEY, RecordState.WAITING))
            with core._transaction() as connection:
                self.assertFalse(state.claim_record(connection, ac.KEY, self.now + 60), "fifteen minutes apart")
            with core._transaction() as connection:
                self.assertTrue(state.claim_record(connection, ac.KEY, self.now + 900))
        self.assertTrue(state.move_record(ac.KEY, RecordState.FINISHED))
        self.assertFalse(state.move_record(ac.KEY, RecordState.WAITING))
        (record,) = state.records_on(ac.THREAD)
        self.assertEqual((record["state"], record["claims"], record["claimed_at"]),
                         ("finished", 2, self.now + 900))

    def test_an_override_is_one_per_capability_and_record_and_is_used_once(self):
        state = self.state()
        self.assertTrue(state.add_override(ac.KEY, "test_wake", OverrideKind.RESEND_ONCE))
        self.assertFalse(state.add_override(ac.KEY, "test_wake", OverrideKind.FORCE_ONCE))
        self.assertEqual([row["kind"] for row in state.overrides_for(ac.KEY)], ["resend_once"])
        self.assertTrue(state.use_override(ac.KEY, "test_wake"))
        self.assertFalse(state.use_override(ac.KEY, "test_wake"))
        self.assertEqual(state.overrides_for(ac.KEY), [])


class BoundTests(StateCase):
    """Bounded as core's journal is (store/journal.py): 5,000 entries or 90 days."""

    def test_the_bounds_are_core_journals(self):
        from codex_auto_resume.store import journal as core
        self.assertEqual((EVENT_LIMIT, EVENT_MAX_AGE, journal_module._PRUNE_EVERY),
                         (core.EVENT_LIMIT, core.EVENT_MAX_AGE, core._PRUNE_EVERY))

    def test_every_table_is_pruned_and_nothing_a_decision_still_counts(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        old, recent = self.now - EVENT_MAX_AGE - DAY, self.now - 3600
        connection.executemany("INSERT INTO journal (at, code) VALUES (?, 'other')",
                               [(old,)] * 10 + [(recent,)] * (EVENT_LIMIT + 50))
        connection.executemany("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               [(old, ac.THREAD)] * 10 + [(recent, ac.THREAD)] * 30)
        connection.executemany("INSERT INTO records VALUES (?, 'test_wake', ?, ?, ?, NULL, 0, ?)",
                               [("%064x" % n, ac.THREAD, "finished", old, old) for n in range(5)]
                               + [("%064x" % (100 + n), ac.THREAD, "waiting", old, None) for n in range(3)])
        connection.executemany("INSERT INTO overrides VALUES (?, 'test_wake', 'force_once', ?, NULL)",
                               [("%064x" % n, old) for n in range(4)])
        connection.execute("INSERT INTO sampler VALUES ('test_wake', 'woke', ?, 5)", (int(old // DAY),))
        connection.executemany("INSERT INTO admissions VALUES (?, 'test_wake', 'admit', NULL, NULL, NULL, NULL, "
                               "NULL, 0, ?)", [("%064x" % n, old) for n in range(4)]
                               + [("%064x" % (100 + n), recent) for n in range(EVENT_LIMIT + 5)])
        connection.executemany("INSERT INTO samples (at, form, has_words) VALUES (?, 'tagged', 0)",
                               [(old,)] * 6 + [(recent,)] * (EVENT_LIMIT + 7))
        connection.execute("INSERT INTO rules (tag, category, created_at) VALUES ('brandNewVariant', 'timeout', ?)",
                           (old,))
        connection.execute("INSERT INTO options VALUES ('test_wake', 'attempts', 2)")
        connection.commit()
        with state._transaction() as open_:
            state._prune(open_, self.now)
        counts = {table: connection.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                  for table in ("journal", "spend", "records", "overrides", "sampler", "admissions",
                                "samples", "rules", "options")}
        self.assertEqual(counts, {"journal": EVENT_LIMIT, "spend": 30, "records": 3,
                                  "overrides": 0, "sampler": 0, "admissions": EVENT_LIMIT,
                                  "samples": EVENT_LIMIT, "rules": 1, "options": 1})
        self.assertEqual({row[0] for row in connection.execute("SELECT state FROM records")}, {"waiting"})

    def test_a_spend_inside_the_day_is_never_pruned_however_many_there_are(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        connection.executemany("INSERT INTO spend (at, capability, thread_id) VALUES (?, 'test_wake', ?)",
                               [(self.now - 60, ac.THREAD)] * (EVENT_LIMIT + 20))
        connection.commit()
        with state._transaction() as open_:
            state._prune_spend(open_, "main", self.now)
        self.assertEqual(connection.execute("SELECT count(*) FROM spend").fetchone()[0], EVENT_LIMIT + 20)

    def test_the_journal_prunes_itself_as_it_grows(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        connection = self.raw(state)
        connection.executemany("INSERT INTO journal (at, code) VALUES (?, 'other')",
                               [(self.now - EVENT_MAX_AGE - DAY,)] * 254)
        connection.commit()
        state.note(JournalCode.OTHER)                              # the 256th line
        self.assertEqual(connection.execute("SELECT count(*) FROM journal").fetchone()[0], 2)


class CoreStateTests(StateCase):
    """Nothing of the advanced state is in core's: no table in state.sqlite, which would make the
    core store refuse to open (store/session.py), and no key in settings.json, which a standard
    save would drop (settings.py)."""

    def test_the_core_state_and_settings_are_what_the_standard_edition_leaves(self):
        self.paths.ensure()
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, self.now)
        config.save_settings(self.paths, settings.defaults())
        before = self.paths.settings_file.read_bytes()
        runtime = self.runtime()
        self.arm(runtime, state="shadow")
        self.arm(runtime)
        runtime.state.add_record(ac.KEY, "test_wake", ac.THREAD)
        runtime.state.sample("test_wake", "woke")
        runtime.arming.all_off(actor=Actor.MCP)
        self.assertEqual(self.paths.settings_file.read_bytes(), before)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(Store._tables(store._connection), _TABLES_V4)
        self.assertEqual(sorted(path.name for path in self.paths.state_dir.iterdir()),
                         sorted([config.OWNER_MARKER, "advanced", "settings.json", "state.sqlite"]))


class PurgeTests(StateCase):
    """Core's one rule for the advanced state: a purge removes config/advanced/ while it carries
    the marker (config.owned_advanced_files), and nothing of it otherwise."""

    def uninstall(self, *flags):
        """`uninstall` as tests/test_cli.py runs it: the registry a fake, the Start Menu left
        alone, no Codex anywhere, and this test's own home."""
        self.addCleanup(_reset_logging)
        scratch = self.home.parent
        with patch.dict(os.environ, {"LOCALAPPDATA": str(scratch / "no-codex"),
                                     "CODEX_HOME": str(scratch / "codex"),
                                     config.ENV_HOME: str(self.home)}), \
                patch.object(startup, "_winreg", return_value=FakeWinreg()), \
                patch.object(shortcut, "uninstall", return_value=False), \
                contextlib.redirect_stdout(io.StringIO()):
            return cli.main(["--quiet", "uninstall", *flags])

    def advanced_state(self):
        runtime = self.runtime()
        self.arm(runtime, state="shadow")
        runtime.state.close()
        (self.paths.advanced_dir / "advanced.sqlite-journal").write_bytes(b"")
        return runtime.state

    def test_a_purge_takes_the_marked_directory_whole(self):
        self.paths.ensure()
        self.advanced_state()
        self.assertEqual(self.uninstall(), 0)
        self.assertFalse(self.paths.advanced_dir.exists())
        self.assertFalse(self.paths.state_dir.exists())

    def test_keeping_the_state_keeps_it(self):
        self.paths.ensure()
        self.advanced_state()
        self.assertEqual(self.uninstall("--keep-state"), 0)
        self.assertTrue((self.paths.advanced_dir / FILE_NAME).is_file())

    def test_without_its_marker_nothing_in_it_is_ours(self):
        self.paths.ensure()
        self.advanced_state()
        (self.paths.advanced_dir / config.OWNER_MARKER).unlink()
        self.assertEqual(self.paths.owned_advanced_files(), [])
        self.assertEqual(self.uninstall(), 0)
        self.assertTrue((self.paths.advanced_dir / FILE_NAME).is_file())

    def test_what_a_purge_takes_is_every_file_in_it_and_its_marker_last(self):
        self.paths.ensure()
        self.advanced_state()
        stray = self.paths.advanced_dir / "left-by-a-newer-version.sqlite"
        stray.write_bytes(b"x")
        (self.paths.advanced_dir / "nested").mkdir()
        taken = self.paths.owned_advanced_files()
        self.assertEqual(taken[-1].name, config.OWNER_MARKER)
        self.assertEqual({path.name for path in taken[:-1]},
                         {FILE_NAME, "advanced.sqlite-journal", stray.name})
        self.assertLess(self.paths.owned_state_files().index(taken[-1]),
                        self.paths.owned_state_files().index(self.paths.state_dir / config.OWNER_MARKER))

    def test_an_installation_that_was_never_advanced_purges_as_it_always_did(self):
        self.paths.ensure()
        before = self.paths.owned_state_files()
        self.assertFalse(self.paths.advanced_dir.exists())
        self.assertEqual(self.paths.owned_advanced_files(), [])
        self.assertNotIn(self.paths.advanced_dir, [path.parent for path in before])


class AttachTests(StateCase):
    def test_it_is_attached_once_and_only_when_it_is_there(self):
        state = self.state()
        with contextlib.closing(sqlite3.connect(":memory:")) as connection:
            self.assertFalse(state.attach(connection))
            state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
            self.assertTrue(state.attach(connection))
            self.assertTrue(state.attach(connection))
            names = [row[1] for row in connection.execute("PRAGMA database_list")]
            self.assertEqual(names.count(ATTACHED), 1)
            self.assertEqual(connection.execute("SELECT generation FROM %s.meta" % ATTACHED).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

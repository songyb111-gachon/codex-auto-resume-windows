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
from codex_auto_resume import cli, config, settings, shortcut, startup  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume.store.schema import _TABLES_V3  # noqa: E402
from codex_auto_resume_advanced import vocabulary  # noqa: E402
from codex_auto_resume_advanced.state import (ATTACHED, EVENT_LIMIT, EVENT_MAX_AGE,  # noqa: E402
                                              FILE_NAME, TABLES, AdvancedState, StateError)
from codex_auto_resume_advanced.state import journal as journal_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode,  # noqa: E402
                                                   OffReason, OverrideKind, RecordState)
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
        self.assertGreaterEqual(len(lists), 11)
        for words in lists:
            values = [member.value for member in words]
            self.assertEqual(len(values), len(set(values)), words.__name__)
            for member in words:
                with self.subTest(member=member):
                    self.assertEqual(member.name, member.value.upper().replace("-", "_"))

    def test_every_tripwire_is_a_reason_a_capability_is_off(self):
        self.assertEqual({str(word) for word in vocabulary.TRIPWIRES},
                         {"submission_unknown", "local_check_failed", "failed_here", "incompatible",
                          "hook_exception", "statement_changed"})


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

    def test_it_lives_in_one_marked_directory_under_config(self):
        state = self.state()
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)
        self.assertEqual(state.path, self.paths.state_dir / "advanced" / FILE_NAME)
        self.assertEqual(self.paths.advanced_dir, state.directory)
        self.assertTrue(self.paths.owns(self.paths.advanced_dir))
        self.assertEqual(sorted(path.name for path in self.paths.advanced_dir.iterdir()),
                         sorted([FILE_NAME, config.OWNER_MARKER]))
        connection = self.raw(state)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual({row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")},
            set(TABLES))

    def test_a_file_that_is_not_exactly_this_schema_is_refused_not_repaired(self):
        for damage in ("CREATE TABLE extra (x)", "ALTER TABLE journal ADD COLUMN words TEXT",
                       "PRAGMA user_version=2", "DELETE FROM meta"):
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
                          "UPDATE meta SET global_hourly=13"):
            with self.subTest(statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)

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


class RecordTests(StateCase):
    def test_records_move_only_along_their_moves_and_a_claim_is_counted(self):
        state = self.state()
        self.assertTrue(state.add_record(ac.KEY, "test_wake", ac.THREAD))
        self.assertFalse(state.add_record(ac.KEY, "test_wake", ac.THREAD))
        self.assertFalse(state.move_record(ac.KEY, RecordState.FINISHED))
        self.assertTrue(state.move_record(ac.KEY, RecordState.IN_FLIGHT))
        self.assertTrue(state.move_record(ac.KEY, RecordState.WAITING))
        self.assertTrue(state.move_record(ac.KEY, RecordState.IN_FLIGHT))
        self.assertTrue(state.move_record(ac.KEY, RecordState.FINISHED))
        self.assertFalse(state.move_record(ac.KEY, RecordState.WAITING))
        (record,) = state.records_on(ac.THREAD)
        self.assertEqual((record["state"], record["claims"], record["claimed_at"]), ("finished", 2, self.now))

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
        connection.commit()
        with state._transaction() as open_:
            state._prune(open_, self.now)
        counts = {table: connection.execute("SELECT count(*) FROM %s" % table).fetchone()[0]
                  for table in ("journal", "spend", "records", "overrides", "sampler")}
        self.assertEqual(counts, {"journal": EVENT_LIMIT, "spend": 30, "records": 3,
                                  "overrides": 0, "sampler": 0})
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
            self.assertEqual(Store._tables(store._connection), _TABLES_V3)
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

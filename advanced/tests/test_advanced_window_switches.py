"""The window switches of Wrap up near a limit and Stop near a limit (v0.6.16 final, the owner's request of 2026-10-18):
each capability's own pair, rows of `options` the file has admitted since version 6 - no new version - and the one
carry-over from beta.4, where the usage meter's pair decided for all three.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import dataclasses
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced.registry import USAGE_METER, USAGE_PAUSE, USAGE_WRAP_UP  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, Refused  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, OptionKey, Refusal  # noqa: E402

METER, WRAP, PAUSE = "usage_meter", "usage_wrap_up", "usage_pause"
FIVE, WEEKLY = OptionKey.WINDOW_FIVE_HOUR, OptionKey.WINDOW_WEEKLY
ON, OFF = 1, 2


def beta4(definition):
    """A definition as beta.4 had it: no window switches of its own."""
    return dataclasses.replace(definition, options=tuple(option for option in definition.options
                                                         if option.key not in (FIVE, WEEKLY)))


class WindowSwitchCase(ac.AdvancedCase):
    def state(self, *definitions) -> AdvancedState:
        made = AdvancedState(self.paths, registry=ac.Registry(definitions or (USAGE_METER, USAGE_WRAP_UP, USAGE_PAUSE)),
                             clock=lambda: self.now)
        self.addCleanup(made.close)
        return made

    def switch(self, state, capability, key, value):
        state.set_option(capability, key, value, generation=state.meta()["generation"], actor=Actor.DASHBOARD)

    def windows(self, state, capability):
        options = state.options(capability)
        return options[FIVE], options[WEEKLY]

    def reopened(self, state):
        state.close()
        return self.state()

    def as_beta4_left_it(self, state):
        """The file as beta.4 left it: the follower capabilities' window rows - which beta.4 never wrote - gone."""
        state.close()
        with contextlib.closing(sqlite3.connect(state.path)) as connection:
            connection.execute("DELETE FROM options WHERE capability IN (?, ?) AND choice IN (?, ?)",
                               (WRAP, PAUSE, str(FIVE), str(WEEKLY)))
            connection.commit()


class CarryOverTests(WindowSwitchCase):
    def test_a_window_off_in_the_meter_before_the_update_is_off_for_the_wrap_up_and_the_stop_after(self):
        """beta.4: the meter's five-hour switch off meant nothing warned, wrapped up or stopped for it. Opened by this
        version, the wrap-up and the stop have that window off too, the weekly one on, and the meter keeps its own."""
        state = self.state()
        self.switch(state, METER, FIVE, OFF)
        self.as_beta4_left_it(state)
        after = self.state()
        self.assertEqual(self.windows(after, METER), (OFF, ON))
        self.assertEqual(self.windows(after, WRAP), (OFF, ON))
        self.assertEqual(self.windows(after, PAUSE), (OFF, ON))

    def test_afterwards_the_meters_switch_changes_only_its_warnings(self):
        """Once carried over, the meter's switches move nothing of the others - not then, not at the next opening."""
        state = self.state()
        self.switch(state, METER, FIVE, OFF)
        self.as_beta4_left_it(state)
        after = self.state()
        self.switch(after, METER, FIVE, ON)
        self.switch(after, METER, WEEKLY, OFF)
        for opened in (after, self.reopened(after)):
            with self.subTest(opened=opened is after):
                self.assertEqual(self.windows(opened, METER), (ON, OFF))
                self.assertEqual(self.windows(opened, WRAP), (OFF, ON))
                self.assertEqual(self.windows(opened, PAUSE), (OFF, ON))

    def test_a_new_file_has_every_switch_on_and_the_meters_off_later_moves_nothing(self):
        state = self.state()
        self.switch(state, METER, FIVE, OFF)
        again = self.reopened(state)
        self.assertEqual(self.windows(again, WRAP), (ON, ON))
        self.assertEqual(self.windows(again, PAUSE), (ON, ON))

    def test_it_is_written_once_moves_no_generation_and_keeps_the_version(self):
        state = self.state()
        self.switch(state, METER, WEEKLY, OFF)
        self.as_beta4_left_it(state)
        first = self.state()
        generation = first.meta()["generation"]
        rows = self.rows(first)
        second = self.reopened(first)
        self.assertEqual((second.meta()["generation"], self.rows(second)), (generation, rows))
        self.assertEqual(rows, [(METER, "window_weekly", OFF), (PAUSE, "window_five_hour", ON),
                                (PAUSE, "window_weekly", OFF), (WRAP, "window_five_hour", ON),
                                (WRAP, "window_weekly", OFF)])
        second.close()
        with contextlib.closing(sqlite3.connect(second.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], schema_module.SCHEMA_VERSION)
        self.assertEqual(schema_module.SCHEMA_VERSION, 9)                # v0.6.20's, not this carry-over's

    def rows(self, state):
        with state._read() as connection:
            return [tuple(row) for row in connection.execute(
                "SELECT capability, choice, value FROM options WHERE choice IN ('window_five_hour', 'window_weekly') "
                "ORDER BY capability, choice")]

    def test_a_registry_without_the_switches_writes_nothing(self):
        """Only a switch the capability offers is written: a registry of beta.4's definitions - or one without the
        usage capabilities - opens the file and leaves `options` as it was."""
        state = self.state()
        self.switch(state, METER, FIVE, OFF)
        self.as_beta4_left_it(state)
        older = self.state(USAGE_METER, beta4(USAGE_WRAP_UP), beta4(USAGE_PAUSE))
        self.assertEqual(self.rows(older), [(METER, "window_five_hour", OFF)])


class OlderReaderTests(WindowSwitchCase):
    def test_an_older_reader_skips_the_new_rows_and_reads_every_other_choice(self):
        """beta.4's options() takes only a choice its capability offers: the wrap-up's and the stop's window rows are
        not among them, so it reads what it always read - and refuses to set one, as it refuses any choice it lacks."""
        state = self.state()
        self.switch(state, WRAP, FIVE, OFF)
        self.switch(state, PAUSE, WEEKLY, OFF)
        self.switch(state, WRAP, OptionKey.WRAP_STYLE, 3)
        state.close()
        older = self.state(USAGE_METER, beta4(USAGE_WRAP_UP), beta4(USAGE_PAUSE))
        wrap = older.options(WRAP)
        self.assertNotIn(FIVE, wrap)
        self.assertNotIn(WEEKLY, wrap)
        self.assertEqual(wrap[OptionKey.WRAP_STYLE], 3)
        self.assertEqual(set(older.options(PAUSE)), {OptionKey.PAUSE_FIVE_HOUR, OptionKey.PAUSE_WEEKLY})
        with self.assertRaises(Refused) as refused:
            older.set_option(WRAP, FIVE, ON, generation=older.meta()["generation"], actor=Actor.DASHBOARD)
        self.assertEqual(refused.exception.refusal, Refusal.OPTION_INVALID)
        self.assertEqual(self.windows(self.reopened(older), WRAP), (OFF, ON), "the rows are kept for this version")


if __name__ == "__main__":
    unittest.main()

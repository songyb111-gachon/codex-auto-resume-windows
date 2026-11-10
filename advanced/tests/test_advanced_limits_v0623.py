"""The limits the owner decided on 2026-11-10 (v0.6.23, the limits review): each number held, and what goes with it.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_limits_v0623.py
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_state import StateCase  # noqa: E402
from codex_auto_resume import continuation, ladder, settings  # noqa: E402
from codex_auto_resume.domain import ids, plughands  # noqa: E402
from codex_auto_resume_advanced.engine import markerfree  # noqa: E402
from codex_auto_resume_advanced.state import Refused  # noqa: E402
from codex_auto_resume_advanced.state import prompts as prompts_module, resets as resets_module  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402

DAY = 86400
WEEK = 7 * DAY
CATALOG = Path(prompts_module.__file__).resolve().parent.parent / "locales" / "en.json"


def thread(n):
    return "0a1b2c3d-0005-7000-8000-%012d" % n


def key(n):
    return "%064x" % (5000 + n)


class WaitingCounts(StateCase):
    """L1.7, L1.7b and L1.9: the waiting rows are local and cost nothing; what is sent stays under the ceilings."""

    def test_the_numbers(self):
        self.assertEqual((prompts_module.PROMPTS_LIMIT, prompts_module.PER_CONVERSATION), (50, 20))
        self.assertEqual((resets_module.MESSAGES_LIMIT, resets_module.CREDIT_RULES_LIMIT), (50, 4))

    def test_twenty_wait_in_one_conversation_and_the_twenty_first_is_refused(self):
        state = self.state()
        for n in range(20):
            state.add_prompt(ac.THREAD, "mine %d" % n, "after_turn")
        with self.assertRaises(Refused) as refused:
            state.add_prompt(ac.THREAD, "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)

    def test_fifty_wait_in_all_and_the_fifty_first_is_refused(self):
        state = self.state()
        for n in range(50):
            state.add_prompt(thread(n // 20), "mine %d" % n, "after_turn")
        with self.assertRaises(Refused) as refused:
            state.add_prompt(thread(40), "one more", "after_turn")
        self.assertEqual(refused.exception.refusal, Refusal.QUEUE_FULL)

    def test_fifty_reset_messages_wait_each_for_a_conversation_of_its_own(self):
        """The ordinal is which reset a message waits for, so it does not stop the fifty: every one here says the first."""
        state = self.state()
        for n in range(50):
            state.add_reset_rule("reset_message", "codex", 300, 1, thread_id=thread(n), words="go on", record_id=key(n))
        with self.assertRaises(Refused) as refused:
            state.add_reset_rule("reset_message", "codex", 300, 1, thread_id=thread(50), words="go on", record_id=key(50))
        self.assertEqual(refused.exception.refusal, Refusal.RESETS_FULL)

    def test_a_person_reads_the_same_numbers(self):
        english = CATALOG.read_text(encoding="utf-8")
        self.assertIn("twenty for a conversation, fifty in all", english)
        self.assertIn("one message to a conversation and fifty in all", english)


class AdmittedAge(unittest.TestCase):
    """L3.10: a failure the standard edition leaves for the person is taken up within its default look-back."""

    def test_six_hours_as_the_standard_look_back_and_the_waits_stay(self):
        self.assertEqual(ladder.ADMISSION_MAX_AGE, 6 * 3600)
        self.assertEqual(ladder.ADMISSION_MAX_AGE, settings.DEFAULTS["detection_lookback_hours"] * 3600)
        self.assertEqual(ladder.ADMITTED_WAITS, (600, 900, 1800))

    def test_a_person_reads_the_same_age(self):
        english = json.loads(CATALOG.read_text(encoding="utf-8"))
        for capability in ("codex_gave_up", "sign_in_retry", "unknown_failure_budget", "structured_rules"):
            words = english["statement.%s.does" % capability]
            self.assertIn("failures from the last six hours", words, capability)


class SeriesSpan(StateCase):
    """L1.8b: a series runs as many occurrences as the person picked; a row already written keeps working."""

    def weekly(self, state, **options):
        return state.add_prompt(ac.THREAD, "mine", "recurring", at=self.now + 60, every="week", occurrences=30, **options)

    def test_thirty_weekly_run_their_thirty(self):
        """Fails with a default `until`: the fifth week falls past 30 days and the series ends there."""
        state = self.state()
        row = state.prompt(self.weekly(state))
        self.assertIsNone(row["until"])
        due = row["due_at"]
        for used in range(1, 30):
            following = prompts_module.next_slot(dict(row, sent_count=used, due_at=due))
            self.assertEqual(following, due + WEEK, "occurrence %d" % used)
            due = following
        self.assertEqual(due - row["due_at"], 29 * WEEK)
        self.assertIsNone(prompts_module.next_slot(dict(row, sent_count=30, due_at=due)), "the thirtieth is the last")

    def test_a_row_written_before_keeps_its_thirty_days_and_an_edit_leaves_them(self):
        state = self.state()
        until = self.now + schema_module.PROMPT_SPAN
        prompt = self.weekly(state, until=until)
        row = state.prompt(prompt)
        self.assertEqual(row["until"], until)
        self.assertIsNone(prompts_module.next_slot(dict(row, sent_count=4, due_at=row["due_at"] + 4 * WEEK)))
        generation = self.generation(state)
        state.edit_prompt(prompt, generation, "mine, edited", "recurring", at=self.now + 120, every="day", occurrences=30)
        self.assertEqual(state.prompt(prompt)["until"], until)

    def test_a_new_series_edited_still_ends_with_its_occurrences(self):
        state = self.state()
        prompt = self.weekly(state)
        state.edit_prompt(prompt, self.generation(state), "mine, edited", "recurring", at=self.now + 120, every="week",
                          occurrences=12)
        row = state.prompt(prompt)
        self.assertEqual((row["until"], row["occurrences"]), (None, 12))

    def test_the_stored_format_did_not_change(self):
        """The row's CHECK on `until` stands as v0.6.15-beta wrote it, and an `until` past it is still refused."""
        self.assertEqual(schema_module.PROMPT_SPAN, 30 * DAY)
        state = self.state()
        with self.assertRaises(Refused) as refused:
            self.weekly(state, until=self.now + 31 * DAY)
        self.assertEqual(refused.exception.refusal, Refusal.OCCASION_INVALID)

    def test_a_person_reads_the_picker_and_no_span(self):
        words = json.loads(CATALOG.read_text(encoding="utf-8"))["statement.prompt_queue.does"]
        self.assertIn("as many times as you pick, up to 30", words)
        self.assertNotIn("30 days at most", words)

    def generation(self, state):
        with contextlib.closing(self.raw(state)) as connection:
            return connection.execute("SELECT generation FROM meta").fetchone()[0]


class LongestMessage(StateCase):
    """L1.2: 30,000 characters, in every place the bound is written, and a file written with the old CHECK keeps working."""

    LONGEST = continuation.PROMPT_LIMIT

    def test_every_place_says_the_same(self):
        self.assertEqual(continuation.PROMPT_SEND_LIMIT, 30000)
        self.assertEqual(self.LONGEST, 30000 - len("\n\n" + ids.short_marker("0" * ids.INTERRUPTION_ID_LENGTH)))
        for name, value in (("plughands", plughands.WORDS_LIMIT), ("markerfree", markerfree.MAX_PROMPT),
                            ("prompts", prompts_module.WORDS_LIMIT), ("resets", resets_module.WORDS_LIMIT),
                            ("steers", schema_module.STEER_WORDS), ("schema", schema_module.WORDS_MOST)):
            self.assertEqual(value, continuation.PROMPT_SEND_LIMIT, name)

    def test_a_new_file_holds_the_longest_and_refuses_one_more(self):
        state = self.state()
        kept = state.add_prompt(ac.THREAD, "x" * 30000, "after_turn")
        self.assertEqual(len(state.prompt(kept)["words"]), 30000)
        state.add_reset_rule("reset_message", "codex", 300, 1, thread_id=thread(1), words="y" * 30000, record_id=key(1))
        with self.assertRaises(Refused):
            state.add_prompt(ac.THREAD, "x" * 30001, "after_turn")

    def narrowed(self, state, first_id):
        """The file as an earlier version wrote it: each CHECK saying 8,192, a prompt in it, and a higher id used and gone."""
        kept = state.add_prompt(ac.THREAD, "written before", "after_turn")
        state.add_prompt(ac.THREAD, "gone", "after_turn")
        path = state.path
        state.close()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for table in schema_module.WORDS_TABLES:
                stored = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
                self.assertIn("BETWEEN 1 AND 30000", stored, table)
                connection.execute("PRAGMA writable_schema=ON")
                connection.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
                                   (stored.replace("BETWEEN 1 AND 30000", "BETWEEN 1 AND 8192"), table))
                connection.execute("PRAGMA writable_schema=OFF")
            connection.execute("DELETE FROM prompts WHERE words='gone'")
            connection.commit()
        return kept, path

    def stored(self, path, table):
        with contextlib.closing(sqlite3.connect(path)) as connection:
            return connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]

    def test_a_file_with_the_old_check_is_widened_and_keeps_its_rows_indexes_and_ids(self):
        state = self.state()
        kept, path = self.narrowed(state, 1)
        for table in schema_module.WORDS_TABLES:
            self.assertIn("BETWEEN 1 AND 8192", self.stored(path, table), table)
        opened = self.state()
        self.assertEqual(opened.prompt(kept)["words"], "written before", "the row is kept")
        for table in schema_module.WORDS_TABLES:
            self.assertIn("BETWEEN 1 AND 30000", self.stored(path, table), table)
        longest = opened.add_prompt(thread(2), "x" * 30000, "after_turn")
        self.assertEqual(longest, kept + 2, "an id once given is not given again")
        path_now = opened.path
        opened.close()
        with contextlib.closing(sqlite3.connect(path_now)) as connection:
            indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertTrue({"prompts_thread", "reset_rules_state", "steers_created"} <= indexes, indexes)
        self.assertEqual(version, schema_module.SCHEMA_VERSION, "no version raised: an older reader still reads the file")

    def test_a_person_reads_the_same_number(self):
        words = json.loads(CATALOG.read_text(encoding="utf-8"))["statement.long_reset_message.does"]
        self.assertIn("29,962 characters", words)
        self.assertEqual(self.LONGEST, 29962)


if __name__ == "__main__":
    unittest.main()

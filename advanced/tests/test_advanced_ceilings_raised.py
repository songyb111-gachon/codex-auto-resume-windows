"""The advanced edition's ceilings, raised (v0.6.22; the owner's table of 2026-11-05, "고급판 다른 기능도 여유주자").

Each value of the table is pinned here, with the choices some capabilities offer, every second copy of a number the
registry holds (the engines' own caps, core's bounds a plug cannot widen) and the words that tell a person the number,
in every language. The global hourly ceiling is also the highest a person may set, so its stored form is held:
a file made before this version names 12 in its CHECK, and is made again on opening with 24, keeping every other row.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests;advanced/tests" python -m unittest test_advanced_ceilings_raised
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_schema_v8 import V8Case, dump, header  # noqa: E402
from codex_auto_resume import ladder  # noqa: E402
from codex_auto_resume.domain import plughands  # noqa: E402
from codex_auto_resume.engine import foropen as core_foropen  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import opentarget, steer  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState, StateError  # noqa: E402
from codex_auto_resume_advanced.state import schema as schema_module  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, ArmingState, OptionKey  # noqa: E402

CORE = registry.CORE_DAILY_CAP
# id: (sends a day in all, sends a day in one conversation) - the approved table, last section of
# plans/PLAN-v0.6.22-v0.6.25.md.
RAISED = {
    "marker_free_continuation": (48, 5), "silent_continuation": (48, 5), "structured_rules": (48, 5),
    "stop_hook_continuation": (48, 5), "keep_going": (48, 5), "send_now": (48, 5),
    "goal_continuation": (24, 5), "subagent_parent": (24, 5), "open_to_send": (24, 5),
    "other_sessions": (48, 5),
    "empty_response": (24, 4), "codex_gave_up": (24, 4),
    "once_more_when_unsure": (12, 4),
    "sign_in_retry": (4, 2),
    "capacity_retry": (96, 96),
    "unknown_failure_budget": (24, 5), "headless_run": (24, 5),
    "compact_continue": (12, 4), "model_fallback": (12, 4),
    "queue_for_open": (24, 5),
    "parallel_dispatch": (96, 5),
    "prompt_queue": (60, 5),
    "steer_send": (120, 60),
    "usage_wrap_up": (24, 4),
    "reset_credit": (24, 5), "early_reset": (24, 5), "account_auto_switch": (24, 5),
    "reset_message": (20, 4),
}
# What the table leaves as it was: the chat's own pace, the window anchor (five starts a day, one a window).
LEFT = {"codex_chat": (60, 30), "window_anchor": (5, 1)}
# The choices a capability offers that the table lengthens: (id, key): (choices, default).
CHOICES = {
    ("capacity_retry", OptionKey.CEILING_HOURS): ((1, 2, 3, 4, 6, 8, 12, 24), 2),
    ("unknown_failure_budget", OptionKey.ATTEMPTS): ((1, 2, 3, 4, 5), 1),
    ("headless_run", OptionKey.CEILING_HOURS): ((1, 2, 3, 4, 5, 6, 8, 12), 1),
    ("model_fallback", OptionKey.ATTEMPTS): ((1, 2, 3, 4, 5), 2),
    ("queue_for_open", OptionKey.DAYS): ((3, 4, 5, 6, 7, 14, 30), 3),
    ("parallel_dispatch", OptionKey.WORKERS): ((2, 3, 4, 5, 6, 7, 8), 2),
    ("codex_retry_settings", OptionKey.ATTEMPTS): ((6, 8, 10, 12, 16, 20), 8),
}
CATALOGS = sorted(path.stem for path in statement.DIRECTORY.glob("*.json"))
# Every definition, the ones that wait hidden for a measurement included (registry.WAITING).
EVERY = {definition.id: definition
         for definition in registry.DEFINITIONS + tuple(waiting[0] for waiting in registry.WAITING)}


class TableTests(unittest.TestCase):
    def test_each_capability_has_the_ceilings_the_owner_approved(self):
        for capability, expected in RAISED.items():
            with self.subTest(capability):
                found = EVERY[capability].ceilings
                self.assertEqual((found.per_day, found.per_conversation), expected)

    def test_the_others_are_as_they_were_and_the_global_hourly_ceiling_is_24(self):
        self.assertEqual(registry.GLOBAL_HOURLY, 24)
        for capability, expected in LEFT.items():
            found = EVERY[capability].ceilings
            self.assertEqual((capability, found.per_day, found.per_conversation), (capability,) + expected)
        for definition in EVERY.values():
            if definition.id not in RAISED and definition.id not in LEFT and definition.ceilings is not None:
                with self.subTest(definition.id):
                    self.assertEqual((definition.ceilings.per_day, definition.ceilings.per_conversation), (1, 1),
                                     "a capability the table does not name has the schema's floor")

    def test_no_raised_conversation_ceiling_passes_cores_five_without_departing_from_a20(self):
        for capability, (_day, conversation) in RAISED.items():
            definition = EVERY[capability]
            with self.subTest(capability):
                self.assertTrue(conversation <= CORE or "A20" in definition.departs_from)
                self.assertLessEqual(conversation, definition.ceilings.per_day)
                self.assertLessEqual(definition.ceilings.per_day, registry.GLOBAL_HOURLY * 24)

    def test_the_choices_a_capability_offers_are_the_longer_lists(self):
        for (capability, key), (choices, default) in CHOICES.items():
            with self.subTest(capability=capability, key=str(key)):
                option = EVERY[capability].option(key)
                self.assertEqual((option.choices, option.default), (choices, default))
                self.assertTrue(all(option.takes(value) for value in choices))
                self.assertFalse(option.takes(max(choices) + 1))


class SecondCopiesTests(unittest.TestCase):
    """A number the registry holds is held again where the engine enforces it, and a copy left behind wins quietly."""

    def test_the_steer_and_the_open_caps_are_the_registrys(self):
        self.assertEqual((steer.PER_DAY, steer.PER_CONVERSATION), RAISED["steer_send"])
        self.assertEqual(opentarget.PER_DAY, RAISED["open_to_send"][0])
        self.assertEqual(steer.PER_CONVERSATION, EVERY["steer_send"].ceilings.per_conversation)

    def test_core_bounds_a_plug_cannot_widen_reach_the_longest_choice(self):
        capacity = EVERY["capacity_retry"]
        hours = capacity.option(OptionKey.CEILING_HOURS).choices
        self.assertEqual(ladder.CAPACITY_PER_DAY, capacity.ceilings.per_conversation)
        self.assertEqual(ladder.CAPACITY_MAX_SECONDS, max(hours) * 3600)
        workers = EVERY["parallel_dispatch"].option(OptionKey.WORKERS).choices
        self.assertEqual(plughands.MAX_WORKERS, max(workers))
        days = EVERY["queue_for_open"].option(OptionKey.DAYS).choices
        self.assertEqual(core_foropen.DEFERRED_LONGEST, max(days) * 86400 + 3600)

    def test_core_takes_eight_workers_and_no_more(self):
        self.assertEqual([plughands.workers(answer) for answer in (2, 5, 8)], [2, 5, 8])
        for answer in (9, 16, 0, 1, True, "8"):
            self.assertEqual(plughands.workers(answer), 1, answer)


class WordsTests(unittest.TestCase):
    """What a person is told, in every catalog: the new number where the old one was, in digits."""

    def catalog(self, locale):
        return json.loads((statement.DIRECTORY / ("%s.json" % locale)).read_text(encoding="utf-8"))

    @staticmethod
    def decimal_digits(text):
        """Compare the printed number, regardless of the catalog's decimal digit shapes."""
        return "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)

    @staticmethod
    def has(number, text):
        return re.search(r"(?<![\dA-Za-z.])%s(?!\d|\.\d)" % number, WordsTests.decimal_digits(text)) is not None

    def test_decimal_digit_shapes_preserve_the_number_and_its_boundaries(self):
        self.assertEqual(self.decimal_digits("۲۴"), "24")
        self.assertTrue(self.has(24, "تا ۲۴ ساعت"))
        for text in ("۲۵", "۱۲۴", "۲۴۰", "۲۴.۵", "²⁴"):
            with self.subTest(text=text):
                self.assertFalse(self.has(24, text))

    def test_every_catalog_says_the_new_numbers(self):
        for locale in CATALOGS:
            words = self.catalog(locale)
            with self.subTest(locale):
                capacity = words["statement.capacity_retry.does"]
                self.assertTrue(self.has(96, capacity) and not self.has(48, capacity), "96 a day, not 48")
                self.assertTrue(self.has(24, capacity) and not self.has(12, capacity), "up to 24 hours")
                risks = words["statement.capacity_retry.risks"]
                self.assertTrue(self.has(24, risks) and not self.has(12, risks), "24 an hour, together")
                for key in ("statement.steer_send.departs", "page.refused.steer_full"):
                    self.assertTrue(self.has(60, words[key]) and self.has(120, words[key]), key)
                    self.assertFalse(self.has(30, words[key]) and not self.has(60, words[key]), key)
                headless = words["statement.headless_run.does"]
                self.assertTrue(self.has(12, headless) and not self.has(6, headless), "up to 12 hours")
                queue = words["statement.queue_for_open.does"]
                self.assertTrue(self.has(30, queue) and not self.has(7, queue), "up to 30 days")
                retries = words["statement.codex_retry_settings.does"]
                self.assertTrue(self.has(16, retries) and self.has(20, retries), "16 and 20 attempts")

    def test_the_english_words_that_were_numbers_say_the_new_ones(self):
        words = self.catalog("en")
        said = {"statement.unknown_failure_budget.does": ("one to five tries", "at most five a day"),
                "statement.parallel_dispatch.does": ("two to eight continuations",),
                "statement.open_to_send.does": ("and 24 a day",),
                "statement.sign_in_retry.does": ("four a day in all",),
                "statement.usage_wrap_up.risks": ("four a day of these",),
                "statement.capacity_retry.does": ("one to 24 hours",),
                "statement.codex_retry_settings.does": ("(6, 8, 10, 12, 16 or 20;",)}
        for key, phrases in said.items():
            for phrase in phrases:
                with self.subTest(key=key, phrase=phrase):
                    self.assertIn(phrase, words[key])
        old = ("at most 48 times", "one to twelve hours", "one to three tries", "at most three a day", "12 times an hour",
               "two to four continuations", "and twelve a day", "twice a day in all", "two a day of these",
               "30 a conversation and 60 a day", "30 in a conversation and 60 in all", "(6, 8, 10 or 12", "7 at most",
               "6 at most")
        text = " ".join(words.values())
        for phrase in old:
            self.assertNotIn(phrase, text)

    def test_the_koreans_that_were_number_words_say_the_new_ones(self):
        words = self.catalog("ko")
        self.assertIn("하루 24번", words["statement.open_to_send.does"])
        self.assertIn("1번에서 5번까지", words["statement.unknown_failure_budget.does"])
        self.assertIn("두 개에서 여덟 개까지", words["statement.parallel_dispatch.does"])
        self.assertIn("하루 4번이며", words["statement.sign_in_retry.does"])
        self.assertIn("하루 4번", words["statement.usage_wrap_up.risks"])

    def test_the_core_word_for_past_the_capacity_hours_says_24(self):
        core = ac.ROOT / "src" / "codex_auto_resume" / "locales"
        for path in sorted(core.glob("*.json")):
            with self.subTest(path.stem):
                text = json.loads(path.read_text(encoding="utf-8"))["why.capacity_window"]
                self.assertTrue(self.has(24, text), "24 hours, in the catalog's own decimal digits")


class HourlyCase(V8Case):
    """The global hourly ceiling as the file stores it."""

    def version_nine_with_the_old_check(self, *, hourly=12, generation=0):
        """A file as v0.6.20 and v0.6.21 left it: version 9, marked, `meta` with its CHECK to 12."""
        self.paths.advanced_dir.mkdir(parents=True)
        from codex_auto_resume import config
        (self.paths.advanced_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        path = self.paths.advanced_dir / schema_module.FILE_NAME
        old = schema_module._STATEMENTS_V2
        with contextlib.closing(sqlite3.connect(path)) as connection:
            for statement_ in (old[0], old[1]) + schema_module.STATEMENTS[2:]:
                connection.execute(statement_)
            connection.execute("UPDATE meta SET global_hourly=?, generation=?", (hourly, generation))
            connection.commit()
        self.assertEqual(self.bound_of(path), 12)
        self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, schema_module.MARK | schema_module.READABLE_FROM))
        return path

    @staticmethod
    def bound_of(path):
        with contextlib.closing(sqlite3.connect(path)) as connection:
            return schema_module.hourly_bound(connection)

    def meta_of(self, path):
        with contextlib.closing(sqlite3.connect(path)) as connection:
            return connection.execute("SELECT singleton, generation, global_hourly FROM meta").fetchall()


class StoredCeilingTests(HourlyCase):
    def test_a_new_file_starts_at_24_and_refuses_25(self):
        state = self.state()
        self.assertEqual(state.meta(), {"generation": 0, "global_hourly": 24})
        state.move("test_wake", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1)          # makes the file
        connection = self.raw(state)
        self.assertEqual(schema_module.hourly_bound(connection), 24)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE meta SET global_hourly=25")
        connection.execute("UPDATE meta SET global_hourly=24")

    def test_a_ceiling_can_be_set_up_to_24_and_not_past_it(self):
        state = self.state()
        state.arming()
        generation = state.meta()["generation"]
        generation = state.set_global_hourly(7, generation=generation, actor=Actor.DASHBOARD)
        generation = state.set_global_hourly(24, generation=generation, actor=Actor.DASHBOARD)
        self.assertEqual(state.meta(), {"generation": generation, "global_hourly": 24})
        with self.assertRaises(StateError):
            state.set_global_hourly(25, generation=generation, actor=Actor.DASHBOARD)

    def test_the_old_default_in_a_v0621_file_becomes_the_new_one_and_every_other_row_is_kept(self):
        """Fails with the remake reverted: the file would still refuse 13 to 24 and hold the old 12."""
        path = self.version_nine_with_the_old_check(hourly=12, generation=4)
        before = dump(path, without=("meta",))
        state = self.state()
        self.assertEqual(state.meta(), {"generation": 4, "global_hourly": 24})
        state.close()
        self.assertEqual(self.meta_of(path), [(1, 4, 24)], "the generation is not moved: no choice was made")
        self.assertEqual(dump(path, without=("meta",)), before)
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(AdvancedState._tables(connection), schema_module.TABLES)
            self.assertEqual(schema_module.hourly_bound(connection), 24)

    def test_a_ceiling_a_person_lowered_is_kept(self):
        path = self.version_nine_with_the_old_check(hourly=8, generation=2)
        state = self.state()
        self.assertEqual(state.meta(), {"generation": 2, "global_hourly": 8})
        state.close()
        self.assertEqual(self.meta_of(path), [(1, 2, 8)])
        self.assertEqual(self.bound_of(path), 24, "the table is made again either way")

    def test_it_is_done_once_so_a_12_chosen_afterwards_stays(self):
        path = self.version_nine_with_the_old_check(hourly=12)
        state = self.state()
        generation = state.set_global_hourly(12, generation=state.meta()["generation"], actor=Actor.DASHBOARD)
        state.close()
        again = self.state()
        self.assertEqual(again.meta(), {"generation": generation, "global_hourly": 12})
        self.assertEqual(self.meta_of(path), [(1, generation, 12)])

    def test_a_version_seven_file_is_brought_up_the_same_way(self):
        path = self.version_7()
        self.assertEqual(self.meta_of(path), [(1, 0, 12)], "v0.6.16 made it with the old default")
        before = dump(path, without=("meta",))
        self.opened()
        self.assertEqual(self.meta_of(path), [(1, 0, 24)])
        self.assertEqual(self.bound_of(path), 24)
        after = dump(path, without=("meta",))
        for name, rows in before.items():
            if name != "prompts":
                self.assertEqual(after[name], rows, name)

    def test_what_an_older_reader_compares_is_unchanged(self):
        """v0.6.17 to v0.6.21 read the file by its tables and columns and its mark, which the remake leaves alone."""
        path = self.version_nine_with_the_old_check()
        self.state().arming()
        with contextlib.closing(sqlite3.connect(path)) as connection:
            self.assertEqual(AdvancedState._tables(connection)["meta"], ("singleton", "generation", "global_hourly"))
        self.assertEqual(header(path), (schema_module.SCHEMA_VERSION, schema_module.MARK | schema_module.READABLE_FROM))

    def test_the_old_files_builders_still_name_12(self):
        """The statements that build an older file for a test are frozen as that version made it."""
        for statements in (schema_module.STATEMENTS_V2, schema_module.STATEMENTS_V7):
            self.assertIn("BETWEEN 1 AND 12", statements[0])
            self.assertEqual(statements[1], "INSERT INTO meta VALUES (1, 0, 12)")
        self.assertIn("BETWEEN 1 AND 24", schema_module.STATEMENTS[0])
        self.assertEqual(schema_module.STATEMENTS[1], "INSERT INTO meta VALUES (1, 0, 24)")


if __name__ == "__main__":
    unittest.main()

"""v0.6.11: a value of the person's own beside a drop-down's choices - Custom..., and Unlimited.

The owner asked for it in so many words: a time limit or the days of the week should be choosable as a
person likes, not only from the list, and a limit that is only the person's own may be unlimited. What
is protected here is that this stays one rule (ownvalues.py) read the same way everywhere:

* each field takes its choices and a value of the person's own within the bounds its module gives it,
  in one spelling - the spelling its choices already have - and nothing else, on a write and on a read;
* Unlimited is offered where nothing about recovery is bounded by the limit (keeping this PC awake), and
  never where a bound keeps recovery safe (standards A20-A22): the retry waits have bounds, the attempt
  budgets stay numbers in their ranges, and the engine's floor is no setting at all;
* a stored value round-trips, an older settings file still loads, and each reader - quiet hours, the
  retry ladder, the ceiling, sleep, keeping awake, the stall, memory and the context guard - reads a
  value of the person's own as the value it is;
* the MCP schema and the bridge's check-setting answer with that rule, and nothing else.

The Dashboard's and the panel's editors are held to it in test_gui_own_values.py.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import time
import unittest

from codex_auto_resume import (controlcli, guards, ladder, memguard, needsyou, ownvalues, power, quiet,
                               settings)
from codex_auto_resume.mcp import tools as mcp_tools
from test_control import ControlTestCase

DESCRIBED = {entry["name"]: entry for entry in settings.describe()}
# Each field, a value of the person's own it takes, and how that value is stored.
TAKEN = {
    "quiet_hours_start": ("7:05", "07:05"),
    "quiet_hours_end": ("23:59", "23:59"),
    "quiet_hours_days": ("fri,mon", "mon,fri"),
    "retry_wait_1": ("s90", "s90"),
    "retry_wait_2": ("m45", "m45"),
    "retry_wait_3": ("h1", "h1"),
    "retry_wait_4": ("s1800", "m30"),
    "retry_wait_5": ("m300", "h5"),
    "chain_time_ceiling": ("m90", "m90"),
    "context_guard": ("above_300000", "above_300k"),
    "stall_after": ("m60", "h1"),
    "ask_after_sleep_minutes": ("h36", "h36"),
    "keep_awake_hours": ("m45", "m45"),
    "memory_guard_limit": ("mb1280", "mb1280"),
}
# And values each refuses: words of another kind, past a bound, or finer than it takes.
REFUSED = {
    "quiet_hours_start": ("24:00", "07:60", "7", "10pm"),
    "quiet_hours_end": ("off", "25:00"),
    "quiet_hours_days": ("", "sundays", "mon,,tue", "Mon"),
    "retry_wait_1": ("s4", "h3", "s0", "m05"),
    "retry_wait_2": ("m14", "h7", "s930", "s5"),
    "retry_wait_5": ("m10", "h7"),
    "chain_time_ceiling": ("m14", "h169", "s3630", "unlimited"),
    "context_guard": ("above_9k", "above_300500", "above_11m", "above_"),
    "stall_after": ("m4", "h169", "s330"),
    "ask_after_sleep_minutes": ("m4", "h169", "unlimited"),
    "keep_awake_hours": ("m14", "h169", "forever"),
    "memory_guard_limit": ("mb127", "mb16385", "mb1k", "mb0512"),
}


class RuleTests(unittest.TestCase):
    def test_exactly_these_drop_downs_take_a_value_of_the_persons_own(self):
        self.assertEqual(set(settings.OWN), set(TAKEN))
        self.assertEqual({name for name, entry in DESCRIBED.items() if "custom" in entry},
                         set(TAKEN) & set(DESCRIBED))
        for name in TAKEN:
            with self.subTest(name):
                self.assertIn("choices", DESCRIBED[name], "Custom... is the last entry of a list of choices")
                self.assertEqual(settings.field_type(name), "string", "a value of its own is words like its choices")
                self.assertEqual(DESCRIBED[name]["custom"], ownvalues.published(settings.OWN[name]))

    def test_each_choice_is_already_its_own_one_spelling(self):
        """A value spelled as a choice is that choice - so no stored value of the person's own means a choice."""
        for name, spec in settings.OWN.items():
            for choice in DESCRIBED[name]["choices"]:
                measured = ownvalues.amount(spec, choice)
                if measured is None:
                    self.assertIn(choice, ("off", "show", "unlimited"), (name, choice))
                    continue
                with self.subTest(name=name, choice=choice):
                    self.assertEqual(ownvalues.spell(spec, measured), choice)

    def test_a_value_of_its_own_is_taken_in_its_one_spelling(self):
        for name, (sent, stored) in TAKEN.items():
            with self.subTest(name):
                self.assertEqual(settings.validate_update({name: sent}), {name: stored})
                self.assertEqual(settings.coerce({name: sent})[name], stored)
                self.assertEqual(settings.validate_update({name: stored}), {name: stored})

    def test_anything_else_is_refused_on_a_write_and_is_the_default_on_a_read(self):
        for name, values in REFUSED.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(settings.SettingsError):
                        settings.validate_update({name: value})
                    self.assertEqual(settings.coerce({name: value})[name], settings.DEFAULTS[name])

    def test_each_bound_is_taken_and_one_step_past_it_is_not(self):
        for name, spec in settings.OWN.items():
            if spec.kind not in (ownvalues.DURATION, ownvalues.COUNT):
                continue
            table = ownvalues.DURATION_UNITS if spec.kind == ownvalues.DURATION else ownvalues.COUNT_UNITS
            step = table[spec.units[0]]
            with self.subTest(name):
                for inside in (spec.low, spec.high):
                    spelled = ownvalues.spell(spec, inside)
                    self.assertEqual(settings.validate_update({name: spelled}), {name: spelled})
                for outside in (spec.low - step, spec.high + step):
                    with self.assertRaises(settings.SettingsError):
                        settings.validate_update({name: ownvalues.spell(spec, outside)})

    def test_a_set_of_days_a_choice_names_is_that_choice(self):
        for days, choice in (("mon,tue,wed,thu,fri", "weekdays"), ("sun,sat", "weekends"),
                             ("mon,tue,wed,thu,fri,sat,sun", "every_day"), ("sat,sun,sat", "weekends")):
            with self.subTest(days):
                self.assertEqual(settings.validate_update({"quiet_hours_days": days}), {"quiet_hours_days": choice})


class UnlimitedTests(unittest.TestCase):
    """Unlimited where the limit is only the person's own; never for what keeps recovery safe."""

    def test_keeping_this_pc_awake_is_the_one_limit_with_unlimited_and_it_is_last(self):
        having = sorted(name for name, entry in DESCRIBED.items() if "unlimited" in (entry.get("choices") or ()))
        self.assertEqual(having, ["keep_awake_hours"])
        self.assertEqual(DESCRIBED["keep_awake_hours"]["choices"][-1], "unlimited")
        self.assertEqual(settings.validate_update({"keep_awake_hours": "unlimited"}), {"keep_awake_hours": "unlimited"})

    def test_every_other_limit_already_starts_with_off_which_is_no_limit(self):
        """A second word for Off would be two ways to one result."""
        for name in ("chain_time_ceiling", "stall_after", "ask_after_sleep_minutes", "quiet_hours_start"):
            with self.subTest(name):
                self.assertEqual(DESCRIBED[name]["choices"][0], "off")
        self.assertEqual(DESCRIBED["memory_guard"]["choices"][0], "off")
        self.assertEqual(DESCRIBED["context_guard"]["choices"][:2], ["off", "show"])

    def test_the_safety_bounds_take_no_unlimited_and_no_value_past_them(self):
        # The retry waits (A22): a wait of the person's own lies between its list's first and last.
        first, later = settings.OWN["retry_wait_1"], settings.OWN["retry_wait_2"]
        self.assertEqual((first.low, first.high), (5, 7200))
        self.assertEqual((later.low, later.high), (ladder.SPACING, 6 * 3600))
        for field in ladder.STEP_FIELDS:
            self.assertNotIn("unlimited", DESCRIBED[field]["choices"])
        # The attempt budgets (A21) stay numbers in their ranges, and have no list to add to.
        for name, (low, high) in (("max_recovery_attempts", (1, 20)), ("max_no_progress", (1, 10)),
                                  ("max_chain_continuations", (1, 10))):
            with self.subTest(name):
                self.assertEqual((DESCRIBED[name]["min"], DESCRIBED[name]["max"]), (low, high))
                self.assertNotIn("choices", DESCRIBED[name])
                self.assertNotIn(name, settings.OWN)
        # The engine's floor (A20) is no setting at all, and the objection window keeps its range.
        self.assertFalse({"thread_cooldown_seconds", "max_submissions_per_thread_per_day"} & set(settings.FIELDS))
        self.assertEqual((DESCRIBED["objection_minutes"]["min"], DESCRIBED["objection_minutes"]["max"]), (1, 60))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "settings.json"

    def tearDown(self):
        self.folder.cleanup()

    def test_values_of_the_persons_own_round_trip(self):
        stored = {name: kept for name, (_sent, kept) in TAKEN.items()}
        settings.update(self.path, {name: sent for name, (sent, _kept) in TAKEN.items()})
        loaded = settings.load(self.path)
        self.assertEqual({name: loaded[name] for name in stored}, stored)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual({name: on_disk[name] for name in stored}, stored)
        settings.save(self.path, loaded)
        self.assertEqual(settings.load(self.path), loaded)

    def test_an_older_file_still_loads_as_it_was(self):
        """A file v0.6.10 or v0.6.11-beta wrote - choices only - reads exactly as it did."""
        older = {"config_version": 2, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00",
                 "quiet_hours_days": "weekdays", "retry_timing": "custom", "retry_wait_1": "s30",
                 "retry_wait_2": "m30", "chain_time_ceiling": "h6", "context_guard": "above_250k",
                 "stall_after": "m15", "ask_after_sleep_minutes": "h2", "keep_awake_hours": "h12",
                 "memory_guard_limit": "mb512", "max_recovery_attempts": 7}
        self.path.write_text(json.dumps(older), encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual({name: loaded[name] for name in older if name != "config_version"},
                         {name: value for name, value in older.items() if name != "config_version"})
        # A file with no version marker (v0.4.x) keeps them too.
        self.path.write_text(json.dumps({"stall_after": "m30", "keep_awake_hours": "h3"}), encoding="utf-8")
        self.assertEqual({name: settings.load(self.path)[name] for name in ("stall_after", "keep_awake_hours")},
                         {"stall_after": "m30", "keep_awake_hours": "h3"})

    def test_a_hand_edited_file_is_read_in_the_one_spelling_and_its_mistakes_as_defaults(self):
        self.path.write_text(json.dumps({"config_version": 2, "stall_after": "m120", "quiet_hours_days": "sun,sat",
                                         "keep_awake_hours": "h900", "memory_guard_limit": "lots"}), encoding="utf-8")
        loaded = settings.load(self.path)
        self.assertEqual((loaded["stall_after"], loaded["quiet_hours_days"]), ("h2", "weekends"))
        self.assertEqual((loaded["keep_awake_hours"], loaded["memory_guard_limit"]),
                         (settings.DEFAULTS["keep_awake_hours"], settings.DEFAULTS["memory_guard_limit"]))


class ReaderTests(unittest.TestCase):
    """What each module that reads one of these makes of a value of the person's own."""

    def test_quiet_hours_from_any_minute_on_any_days(self):
        values = {"quiet_hours_start": "22:15", "quiet_hours_end": "06:45", "quiet_hours_days": "mon,wed"}
        self.assertEqual(quiet.window(values), (22 * 60 + 15, 6 * 60 + 45, frozenset({0, 2})))
        tuesday_night = time.mktime((2027, 1, 5, 23, 0, 0, 0, 0, -1))   # 5 January 2027 is a Tuesday
        wednesday_night = time.mktime((2027, 1, 6, 23, 0, 0, 0, 0, -1))
        self.assertIsNone(quiet.quiet_until(tuesday_night, values), "a Tuesday is not a day it starts on")
        self.assertEqual(quiet.quiet_until(wednesday_night, values), time.mktime((2027, 1, 7, 6, 45, 0, 0, 0, -1)))

    def test_the_retry_ladder_waits_the_waits_of_the_persons_own(self):
        values = dict(settings.defaults(), retry_timing="custom", retry_wait_1="s90", retry_wait_2="m45",
                      retry_wait_5="h5")
        self.assertEqual(ladder.custom_steps(values), (90, 2700, 900, 900, 18000))
        self.assertEqual(ladder.preview(values), [90, 2700, 900, 900, 18000])
        self.assertEqual(ladder.wait_before(values, 1, "rate_limit_transient"), 90)
        self.assertEqual(ladder.wait_before(values, 2), 2700)
        # A word that is not its own and not a choice is its default, as it always was.
        self.assertEqual(ladder.custom_steps(dict(values, retry_wait_2="m10"))[1], 900)

    def test_a_ceiling_a_sleep_a_stall_memory_and_tokens_of_the_persons_own(self):
        self.assertEqual(ladder.ceiling({"chain_time_ceiling": "m90"}), 5400)
        self.assertEqual(power.sleep_threshold({"ask_after_sleep_minutes": "h36"}), 36 * 3600)
        told = {"notifications": True, "notify_needs_you": True}
        self.assertEqual(needsyou.stall_seconds(dict(told, stall_after="m45")), 2700)
        self.assertEqual(memguard.limit_mib({"memory_guard_limit": "mb1280"}), 1280)
        self.assertEqual(guards.context_limit({"context_guard": "above_300k"}), 300_000)
        self.assertTrue(guards.counts_tokens({"context_guard": "above_300k"}))
        self.assertTrue(guards.over({"context_guard": "above_300k"}, 300_001))
        self.assertFalse(guards.over({"context_guard": "above_300k"}, 300_000))

    def test_keeping_awake_for_a_time_of_its_own_or_without_a_limit(self):
        self.assertEqual(power.awake_cap({"keep_awake_hours": "m45"}), 2700)
        self.assertIsNone(power.awake_cap({"keep_awake_hours": "unlimited"}))
        self.assertEqual(power.awake_cap({"keep_awake_hours": "h900"}), 6 * 3600, "past its bound: the default")


class SurfaceTests(ControlTestCase):
    """The MCP schema and the bridge's check-setting, each the same rule."""

    def test_the_mcp_schema_takes_a_choice_or_the_words_of_a_value_of_its_own(self):
        properties = mcp_tools.settings_schema()["properties"]
        offered = [name for name in TAKEN if name in properties]
        self.assertTrue({"quiet_hours_days", "retry_wait_1", "stall_after", "context_guard"} <= set(offered))
        self.assertNotIn("keep_awake_hours", properties, "a Windows setting: the Dashboard's alone")
        for name in offered:
            with self.subTest(name):
                described = properties[name]
                choices, own = described["anyOf"]
                self.assertEqual(choices["enum"], DESCRIBED[name]["choices"])
                self.assertNotIn("enum", described)
                pattern = re.compile(own["pattern"])
                self.assertTrue(pattern.search(TAKEN[name][1]), TAKEN[name][1])
                self.assertIn(mcp_tools.own_words(DESCRIBED[name]["custom"]), described["description"])

    def test_check_setting_answers_with_the_validator_and_writes_nothing(self):
        path = self.paths.settings_file
        before = path.read_bytes() if path.exists() else None
        reply = controlcli.dispatch(self.control, "check-setting", {"name": "stall_after", "value": "m60"})
        self.assertEqual(reply, {"ok": True, "result": {"name": "stall_after", "value": "h1"}})
        reply = controlcli.dispatch(self.control, "check-setting", {"name": "keep_awake_hours", "value": "unlimited"})
        self.assertEqual(reply["result"]["value"], "unlimited")
        for payload in ({"name": "stall_after", "value": "m4"}, {"name": "retry_wait_2", "value": "m5"},
                        {"name": "no_such_setting", "value": "h1"}, {"name": "stall_after"}, {"value": "h1"}):
            with self.subTest(payload):
                refused = controlcli.dispatch(self.control, "check-setting", payload)
                self.assertFalse(refused["ok"])
                self.assertEqual(refused["error_code"], "request_failed")
        self.assertEqual(path.read_bytes() if path.exists() else None, before, "nothing is written")


if __name__ == "__main__":
    unittest.main()

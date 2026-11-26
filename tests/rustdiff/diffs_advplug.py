"""S7.2a: the advanced plug's runtime against the v0.6.26 tag's (P7-DESIGN 3.2 `diffs_advplug_*`, 3.4 layer (2)).

Each scenario is run by the tag's own `Runtime` and by car-adv's (`advtrace`) over the tests' own capability, scripted the
same on both sides (`advplug.py`): every answer, every hook asked of every code in order, and every row of advanced.sqlite
at the end must be equal. The corpus holds the rules of `runtime.py` one by one - off/watched/on, a hook that raises, keep
on's pass-over, restrictions, the first answer and Send now's preference over EARLY, ceilings, P2's records and holds,
P8's joined errands and their tripwires, P12, P14's tripwires, P17's take-up and P3's relaxation, P18/P19's words, the
start routes' held word, a code that cannot be made.

    python -X utf8 tests/rustdiff/run.py --build -k AdvPlugDiff
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from rustdiff import advdiff, advplug

THREAD, OTHER = advplug.THREAD, advplug.OTHER_THREAD
KEY, OTHER_KEY = advplug.KEY, advplug.OTHER_KEY


def definition(**changes) -> dict:
    """`advancedcase.definition()`, dumped as `advdiff.dump_def` writes one."""
    made = {"id": "test_wake", "kind": "route", "points": ["gates", "schedule", "sender", "text", "tick"],
            "revision": 1, "departs_from": ["A11"], "compat": advplug.COMPAT, "ceilings": [3, 2],
            "journal_prefix": "tw", "codes": ["woke", "slept"], "measurements": [], "options": [],
            "rules_editor": False, "samples": False, "resends": False, "requires": [], "wordings": [],
            "narrowed_by": [], "sends": None}
    made.update(changes)
    made["points"] = sorted(made["points"])
    return made


def other(**changes) -> dict:
    return definition(**dict({"id": "test_other", "journal_prefix": "to", "codes": ["done"]}, **changes))


def record(key=KEY, thread=THREAD, **fields) -> dict:
    found = {"interruption_id": key, "thread_id": thread, "state": "waiting", "category": "usage_limit"}
    found.update(fields)
    return found


def own(key=KEY, thread=THREAD, state="waiting", words="go on", sent_at=None) -> dict:
    return {"record_id": key, "thread_id": thread, "marker": "m", "state": state, "words": words, "sent_at": sent_at}


FACTS = {"name": "consent"}


def scenario(name, definitions, script, steps, **more) -> dict:
    made = {"name": name, "definitions": definitions, "script": script, "steps": steps}
    made.update(more)
    return made


ARM = ["arm", "test_wake", "armed"]
WATCH = ["arm", "test_wake", "shadow"]
ARM_OTHER = ["arm", "test_other", "armed"]


def corpus() -> list:
    one = [definition()]
    found = [
        scenario("off_is_not_asked", one, {"test_wake": {"gate": {"word": "hold"}}},
                 [["ask", "gates", "consent", record(), FACTS], ["states"]]),
        scenario("armed_hold_is_taken_at_once", one, {"test_wake": {"gate": {"word": "hold"}}},
                 [ARM, ["ask", "gates", "consent", record(), FACTS], ["ask", "gates", "consent", record(), FACTS]]),
        scenario("watched_is_a_would_have", one, {"test_wake": {"gate": {"word": "hold"}, "schedule": {"word": "send_now"}}},
                 [WATCH, ["ask", "gates", "consent", record(), FACTS], ["ask", "schedule", record(), {"due": 1}],
                  ["states", True]]),
        scenario("a_hook_that_raises_trips_its_capability", one, {"test_wake": {"gate": {"raise": "ValueError"}}},
                 [ARM, ["ask", "gates", "consent", record(), FACTS], ["states", True],
                  ["ask", "gates", "consent", record(), FACTS]]),
        scenario("kept_on_passes_over_the_record_alone", one,
                 {"test_wake": {"gate": {"seq": [{"raise": "ValueError"}, {"word": "hold"}]}}},
                 [["arm", "test_wake", "armed", {"keep_on": True}], ["ask", "gates", "consent", record(), FACTS],
                  ["ask", "gates", "consent", record(), FACTS], ["ask", "gates", "consent", record(OTHER_KEY), FACTS],
                  ["states", True]]),
        scenario("an_answer_core_would_not_take_is_defer", one,
                 {"test_wake": {"gate": {"word": "send_now"}, "schedule": {"value": "nonsense"},
                                "text": {"value": ""}}},
                 [ARM, ["ask", "gates", "consent", record(), FACTS], ["ask", "schedule", record(), {}],
                  ["ask", "text", record(), "core's words"]]),
        scenario("words_core_takes", one, {"test_wake": {"text": {"value": "Please go on."}}},
                 [ARM, ["ask", "text", record(), "core's words"], ["ask", "text", record(OTHER_KEY), "x"]]),
        scenario("a_channel_and_core_s_backend", one,
                 {"test_wake": {"sender": {"seq": [{"channel": {}}, "BACKEND", "DEFER"]}}},
                 [ARM, ["ask", "sender", record()], ["ask", "sender", record(OTHER_KEY)],
                  ["ask", "sender", record(OTHER_KEY)]]),
        scenario("send_now_is_preferred_over_an_early_look", [definition(), other(points=["schedule"])],
                 {"test_wake": {"schedule": {"word": "early"}}, "test_other": {"schedule": {"word": "send_now"}}},
                 [ARM, ARM_OTHER, ["ask", "schedule", record(), {}]]),
        scenario("the_first_answer_wins_otherwise", [definition(), other(points=["gates"])],
                 {"test_wake": {"gate": "DEFER"}, "test_other": {"gate": {"word": "admit"}}},
                 [ARM, ARM_OTHER, ["ask", "gates", "consent", record(), FACTS]]),
        scenario("a_record_that_is_not_a_dict_meets_the_ceiling", one, {"test_wake": {"schedule": {"word": "send_now"}}},
                 [ARM, ["ask", "schedule", "not a record", {}]]),
        scenario("the_tick_joins_the_errands_and_runs_them", [definition(), other(points=["tick"])],
                 {"test_wake": {"tick": {"errand": {"returns": {"ok": True}}}},
                  "test_other": {"tick": {"errand": {"returns": {"trip": "submission_unknown"}}}}},
                 [ARM, ARM_OTHER, ["tick"], ["run"], ["states", True], ["tick"]]),
        scenario("an_errand_that_raises_trips_its_own", one, {"test_wake": {"tick": {"errand": {"raise": "OSError"}}}},
                 [ARM, ["tick"], ["run"], ["states", True]]),
        scenario("a_watched_tick_is_only_journalled", one, {"test_wake": {"tick": {"errand": {}}}},
                 [WATCH, ["tick"], ["run"]]),
        scenario("a_tick_that_is_no_errand_is_nothing", one, {"test_wake": {"tick": {"value": 3}}},
                 [ARM, ["tick"]]),
        scenario("sessions_take_a_set_or_a_tuple", [definition(points=["sessions"])],
                 {"test_wake": {"sessions": {"seq": [{"set": ["cli", "ide"]}, {"value": ["cli"]}, {"tuple": ["ide"]},
                                                     {"set": ["cli", "nonsense"]}]}}},
                 [ARM, ["sessions"], ["sessions"], ["sessions"], ["sessions"]]),
        scenario("eligibility_words", [definition(points=["eligibility"])],
                 {"test_wake": {"eligibility": {"seq": [{"set": ["every_desktop"]}, "DEFER"]}}},
                 [ARM, ["eligibility"], ["eligibility"], WATCH, ["eligibility"]]),
        scenario("partition_pays_one_per_record", [definition(points=["concurrency"])],
                 {"test_wake": {"partition": {"seq": [{"value": 3}, {"value": 1}, {"value": True}, {"value": 9}]}}},
                 [ARM, ["partition", [record(), record(OTHER_KEY, OTHER)]], ["partition", [record()]],
                  ["partition", [record()]], ["partition", [record()]], ["partition", "not a list"]]),
        scenario("records_of_the_edition_s_own", [definition(points=["records", "tick"])],
                 {"test_wake": {"records": {"value": [own(), own(), own(OTHER_KEY, OTHER), {"bad": 1}]}}},
                 [ARM, ["records"]]),
        scenario("records_held_back_by_a_holder", [definition(points=["records", "tick"])],
                 {"test_wake": {"records": {"tuple": [own(), own(OTHER_KEY, OTHER)]},
                                "holds": {"by": 0, "cases": {}, "else": {"value": True}}}},
                 [ARM, ["records"]]),
        scenario("watched_records_are_journalled", [definition(points=["records", "tick"])],
                 {"test_wake": {"records": {"value": [own()]}, "watched_due": {"value": [KEY, 7]}}},
                 [WATCH, ["records"]]),
        scenario("moved_of_core_s_record", one, {"test_wake": {}},
                 [ARM, ["moved", record(), "submitting"], ["moved", record(), "waiting"]]),
        scenario("wants_each_point", [definition(points=["gates", "tick"])], {"test_wake": {}},
                 [["wants", "gates"], ARM, ["wants", "gates"], ["wants", "tick"], ["wants", "records"]]),
        scenario("no_start_route_definitions", one, {}, [["start_route", {"argv": []}], ["start_held"]]),
        scenario("a_start_route_held", [definition(points=["start_route"])], {"test_wake": {"start_route": "DEFER"}},
                 [ARM, ["start_route", {"argv": []}], ["start_held"]]),
        scenario("a_start_route_named", [definition(points=["start_route"])],
                 {"test_wake": {"start_route": {"start": {}}}},
                 [ARM, ["start_route", {"argv": []}], ["start_held"]]),
        scenario("supervise_at_start", [definition(points=["supervision"])],
                 {"test_wake": {"supervise": {"seq": ["DEFER", {"word": "restart"}]}}},
                 [ARM, ["supervise", {"phase": "start"}], ["supervise_held"], ["supervise", {"phase": "ended"}]]),
        scenario("a_code_that_cannot_be_made", one, {}, [ARM, ["ask", "gates", "consent", record(), FACTS], ["states"]],
                 unmakeable=["test_wake"]),
        scenario("a_hook_the_code_does_not_have", one, {"test_wake": {}},
                 [ARM, ["ask", "schedule", record(), {}], ["states", True]]),
        scenario("conversation_off", one, {}, [ARM, ["conversation_off", THREAD]]),
        scenario("unloaded_routes_and_queued_words", [definition(points=["unloaded"])],
                 {"test_wake": {"unloaded": {"seq": [{"route": {}}, {"word": "queue_for_open"}, {"word": "hold"},
                                                     {"value": "to_session"}]}}},
                 [ARM, ["ask", "unloaded", record()], ["ask", "unloaded", record(OTHER_KEY)],
                  ["ask", "unloaded", record("c" * 64)], ["ask", "unloaded", record("d" * 64)]]),
        scenario("delivery_of_a_route_takes_silent_alone", [definition(points=["delivery"])],
                 {"test_wake": {"delivery": {"seq": [{"word": "client_id"}, {"word": "silent"}, {"value": "silent"}]}}},
                 [ARM, ["ask", "delivery", record(route=True)], ["ask", "delivery", record(route=True)],
                  ["ask", "delivery", record(OTHER_KEY, route=True)]]),
        scenario("notice_and_power", [definition(points=["notice", "power"])],
                 {"test_wake": {"notice": {"value": 1}, "power": {"value": {"tasks": "running", "threads": []}}}},
                 [ARM, ["ask", "notice", {"kind": "near_limit"}], ["ask", "power", {}]]),
        scenario("admission_takes_up_and_known_failure_relaxes",
                 [definition(points=["admission", "gates"])],
                 {"test_wake": {"admission": {"word": "admit"}, "gate": {"word": "admit"}}},
                 [ARM, ["clock", 1_800_000_100.0],
                  ["ask", "admission", {"interruption_id": KEY, "takes": ["admit"], "completed_at": 1_800_000_050.0,
                                         "code": None, "status": None, "form": "absent", "has_message": False}],
                  ["ask", "gates", "known_failure", record(category="unknown"), FACTS],
                  ["ask", "admission", {"interruption_id": OTHER_KEY, "takes": ["capacity"],
                                         "completed_at": 1_800_000_050.0}],
                  ["ask", "admission", {"interruption_id": OTHER_KEY, "takes": ["admit"],
                                         "completed_at": 1_000.0}]]),
        scenario("known_failure_with_nothing_taken_up", [definition(points=["admission", "gates"])],
                 {"test_wake": {"gate": {"word": "admit"}}},
                 [ARM, ["ask", "gates", "known_failure", record(category="unknown"), FACTS],
                  ["ask", "gates", "known_failure", record(category="usage_limit"), FACTS]]),
        scenario("the_clock_refreshes_the_states", one, {"test_wake": {"gate": {"word": "hold"}}},
                 [["ask", "gates", "consent", record(), FACTS], ARM, ["ask", "gates", "consent", record(), FACTS],
                  ["clock", 1_800_000_010.0], ["ask", "gates", "consent", record(OTHER_KEY), FACTS]]),
    ]
    return found


class AdvPlugDiff(unittest.TestCase):
    """The plug's runtime, scenario by scenario, against the tag's."""

    @classmethod
    def setUpClass(cls):
        advplug.ensure()

    def check(self, made: dict) -> None:
        scratch = Path(tempfile.mkdtemp(prefix="advplug-"))
        self.addCleanup(shutil.rmtree, scratch, True)
        catalogs = scratch / "catalogs"
        reference = advplug.run_reference(made, scratch / "reference-home", catalogs, scratch)
        rust = advplug.run_rust(made, scratch / "rust-home", catalogs)
        for part in ("results", "asked"):
            if json.dumps(reference[part]) != json.dumps(rust[part]):
                self.fail("%s %s: %s" % (made["name"], part,
                                          advdiff.first_difference(reference[part], rust[part])))
        want, got = advplug.dump(scratch / "reference-home"), advplug.dump(scratch / "rust-home")
        if json.dumps(want, sort_keys=True) != json.dumps(got, sort_keys=True):
            self.fail("%s advanced.sqlite: %s" % (made["name"], advdiff.first_difference(want, got)))

    def test_scenarios(self):
        for made in corpus():
            with self.subTest(made["name"]):
                self.check(made)


if __name__ == "__main__":
    unittest.main()

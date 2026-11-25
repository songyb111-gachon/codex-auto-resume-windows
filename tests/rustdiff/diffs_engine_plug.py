"""The plug's answer paths in car-engine's traces (review 6, finding S3): a scripted plug on both sides.

`diffs_engine`'s traces ask the NULL plug alone, so none of P3-P22 was ever answered: the relaxed paths (EARLY, SEND_NOW,
RESEND, P17's admissions, CAPACITY), the routes' queued answers (QUEUE_FOR_OPEN, TO_SESSION), P6, P14, the claim's
`carried` set and `_refused`'s held branches had no diff at all. Here a scenario names a `plug` - a script (`enginerun.Script`:
the points the plug wants, and per hook a list of rules answering by the record's facts) - and every step runs on both
sides with the same script: the reference's Engine is handed a `domain.plug.Plug` that asks the script, car-engine's plug
(car-harness `plugscript.rs`, a test double of car-policy's `Plug` trait) asks the very same object over the pipe. After
every step the traces must hold the same: the step's answer, every log line and notification, every backend call, the whole
state store, and - new - every question the engine put to the plug (the hook, what it was handed, the answer it got), in
order, and how many hooks failed (`plug_failures` in `facts`).

What it holds: P3 (every gate the engine names, HOLD), P4 (the plug's words), P5 (asked, DEFER: a channel is S7.2's),
P6 and P14 (every move told), P7 (SCHEDULE: EARLY, SEND_NOW, RESEND, HOLD), P15 (asked), P16 (QUEUE_FOR_OPEN, TO_SESSION),
P17 (ADMIT, CAPACITY, AS_*) with P3's known_failure, P18 and P19 (the kinds a plug names), and a hook that raises or panics
(D15). What it cannot hold - P2's records, P5's channel, P8's and P22's errands, P9-P13, P16's route, P11's ledger, P20 and P21
(the watcher's, not the engine's) - needs the advanced plug (S7.2) and is listed in rust/GROUNDWORK.md.
"""
from __future__ import annotations

import os
import random
import unittest
from unittest import mock

from rustdiff import diffs_engine, reference

RECORD = diffs_engine.RECORD
BASE, RESET, T1, T2, T3 = diffs_engine.BASE, diffs_engine.RESET, diffs_engine.T1, diffs_engine.T2, diffs_engine.T3
TURN_A, TURN_B, TURN_C = diffs_engine.TURN_A, diffs_engine.TURN_B, diffs_engine.TURN_C
Scenario, ready_after_reset = diffs_engine.Scenario, diffs_engine.ready_after_reset
WALKS = int(os.environ.get("CODEX_AR_PLUG_WALKS", "40"))
# CODEX_AR_PLUG_ONLY=name,name: only the scenarios whose name starts with one of these (a mutation check's quick run).
ONLY = tuple(each for each in os.environ.get("CODEX_AR_PLUG_ONLY", "").split(",") if each)

# Every point a scripted plug may be asked to answer (`wants`), as the vocabulary writes them.
EVERY = ["gates", "text", "sender", "outcome", "schedule", "moved", "delivery", "unloaded", "admission", "sessions",
         "eligibility"]
UNKNOWN_CODE = '{"codexErrorInfo": "somethingNew"}'


def script(wants=None, **rules) -> dict:
    """A plug script: the points it wants (default every one) and, per hook, the rules answering it."""
    return {"wants": list(EVERY if wants is None else wants),
            "rules": {("gate" if hook == "gates" else hook): [rule if isinstance(rule, dict) else {"answer": rule}
                                                              for rule in found] for hook, found in rules.items()}}


class Plugged(Scenario):
    """A scenario whose engine is handed a scripted plug."""

    def __init__(self, name, plug=None, **spec):
        super().__init__(name, plug=script() if plug is None else plug, **spec)

    def script(self, **found):
        """Change the plug's answers from here on."""
        return self._(op="plug", **found)


def new(found, name, **spec):
    s = Plugged(name, **spec)
    found.append(s)
    return s.enable()


def after_reset(found) -> dict:
    """P7's relaxations of the schedule: a look early, a person's Send now, a resend, and a plug that holds."""
    s = new(found, "pl_early_looks_before_reset",
            plug=script(schedule=[{"answer": "early", "times": 1}]))
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().adv(1000).tick().adv(11).tick(2)
    s = new(found, "pl_early_ignored_not_asked_twice_in_a_window",
            plug=script(schedule=["early"]))
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().adv(100).tick().adv(100).tick().adv(400).tick().adv(100).tick()
    s = new(found, "pl_early_other_word_ignored", plug=script(schedule=["resend"]))
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().adv(1000).tick().adv(11).tick()
    s = new(found, "pl_early_hold", plug=script(schedule=["hold"]))
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().adv(1000).tick().at(RESET + 61).tick().adv(11).tick()
    s = new(found, "pl_early_waiting_for_usage")
    s.script(rules={"schedule": [{"answer": "early"}]})
    s.backend(usage_result={"available": False, "reset_at": None, "limit_type": "x", "reason": "ok"})
    ready_after_reset(s).tick().adv(1000).tick().backend(usage_result={"available": True, "reset_at": None,
                                                                         "limit_type": "x", "reason": "ok"})
    s.adv(1000).tick().adv(11).tick()
    s = new(found, "pl_send_now_passes_retry_wait", plug=script(schedule=[{"answer": "send_now", "times": 1}]))
    s.backend(default_outcome="not_started")
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).loaded(T1).tick().adv(6).tick().adv(6).tick()
    s.adv(1).tick().adv(1).tick()
    s = new(found, "pl_send_now_postponed", plug=script(schedule=["send_now"]))
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s.tick().store("postpone", {"$key": T1}, T1, RESET + 9000, RESET + 62).adv(1).tick().adv(11).tick().adv(100).tick()
    s = new(found, "pl_send_now_spacing_and_budget",
            plug=script(schedule=["send_now"]), options={"thread_cooldown_seconds": 900})
    s.loaded(T1)
    for _ in range(3):
        s.home("fail_transient", T1, completed=int(s.now)).tick().adv(6).tick().adv(1).tick().adv(11).tick().adv(40)
    s = new(found, "pl_send_now_own_attempt_budget", plug=script(schedule=["send_now"]))
    s.policy(max_recovery_attempts=1, max_no_progress=5).loaded(T1).backend(after_accept="queue")
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(6).tick().adv(6).tick()
    s.helper("dispatch_and_fail", T1).watch().tick().adv(16).tick().adv(30).tick().adv(300).tick()
    s = new(found, "pl_send_now_not_past_quiet_hours_or_reset", plug=script(schedule=["send_now"]))
    s.policy(quiet_hours_start="00:00", quiet_hours_end="23:00")
    ready_after_reset(s).tick().adv(61).tick().adv(600).tick()
    s = new(found, "pl_schedule_raises", plug=script(schedule=["raise"]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick().facts()
    s = new(found, "pl_schedule_hold_after_due", plug=script(schedule=[{"answer": "hold", "times": 2}]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick().adv(61).tick()
    s = new(found, "pl_schedule_unknown_and_foreign_words",
            plug=script(schedule=[{"answer": "bogus", "times": 1}, {"answer": "admit", "times": 1}, {"answer": 5}]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick()
    return {}


def gates(found) -> dict:
    """P3: HOLD at each gate the engine names, and a gate the plug is not asked for."""
    for name in ("submission_safe", "chain_budget", "no_progress_budget", "thread_available", "attempt_budget", "usage",
                 "known_failure"):
        s = new(found, "pl_gate_hold_" + name, plug=script(gates=[{"when": {"name": name}, "answer": "hold", "times": 2}]))
        ready_after_reset(s).tick().adv(11).tick().adv(11).tick().adv(61).tick().adv(11).tick()
    s = new(found, "pl_gate_hold_then_raise", plug=script(gates=[{"when": {"name": "usage"}, "answer": "hold", "times": 1},
                                                                  {"when": {"name": "usage"}, "answer": "raise"}]))
    ready_after_reset(s).tick().adv(11).tick().adv(61).tick().facts()
    s = new(found, "pl_gate_panics", plug=script(gates=[{"when": {"name": "thread_available"}, "answer": "panic",
                                                         "times": 2}]))
    ready_after_reset(s).tick().adv(11).tick().adv(61).tick().facts()
    return {}


def words(found) -> dict:
    """P4 (the plug's words), P15 (asked, never taken without a channel) and P5 (asked, DEFER)."""
    s = new(found, "pl_text_words", plug=script(text=["Please carry on with the plan, step by step."]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick()
    s = new(found, "pl_text_empty_and_not_text", plug=script(text=[{"answer": "", "times": 1}, {"answer": ["x"]}]))
    s.backend(default_outcome="not_started")
    ready_after_reset(s).tick().adv(301).tick().adv(301).tick()
    s = new(found, "pl_text_raises", plug=script(text=["raise"]))
    ready_after_reset(s).tick().adv(11).tick().facts()
    s = new(found, "pl_delivery_client_id_without_channel", plug=script(delivery=["client_id"]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick()
    s = new(found, "pl_delivery_silent_and_raise", plug=script(delivery=["silent", "raise"]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick().facts()
    return {}


def unloaded(found) -> dict:
    """P16: QUEUE_FOR_OPEN and TO_SESSION, kept while the plug says so and taken back when it stops."""
    s = new(found, "pl_unloaded_queue_for_open", plug=script(unloaded=["queue_for_open"]))
    s.backend(after_accept="queue")
    ready_after_reset(s, loaded=False).loaded(T1, "notLoaded").tick().adv(11).tick().watch().adv(30).watch()
    s.adv(61).watch().tick().adv(500).watch()
    s = new(found, "pl_unloaded_queue_for_open_then_defer",
            plug=script(unloaded=[{"answer": "queue_for_open", "times": 2}]))
    s.backend(after_accept="queue")
    ready_after_reset(s, loaded=False).loaded(T1, "notLoaded").tick().adv(11).tick().watch().adv(70).watch().adv(70).watch()
    s.adv(70).watch().tick()
    s = new(found, "pl_unloaded_opened_delivered", plug=script(unloaded=["queue_for_open"]))
    s.backend(after_accept="queue")
    ready_after_reset(s, loaded=False).loaded(T1, "notLoaded").tick().adv(11).tick().watch().loaded(T1, "loaded")
    s.adv(20).watch().adv(200).watch().tick()
    s = new(found, "pl_unloaded_to_session", plug=script(unloaded=["to_session"]))
    s.backend(after_accept="queue")
    s._(op="backend", attrs={"session_holder": [4242, 17.5]})
    ready_after_reset(s, loaded=False).loaded(T1, "elsewhere").tick().adv(11).tick().watch().adv(30).watch()
    s.loaded(T1, "notLoaded").adv(10).watch().tick()
    s = new(found, "pl_unloaded_to_session_expires", plug=script(unloaded=["to_session"]))
    s.backend(after_accept="queue")
    s._(op="backend", attrs={"session_holder": [4242, 17.5]})
    ready_after_reset(s, loaded=False).loaded(T1, "elsewhere").tick().adv(11).tick().watch().adv(200).watch().adv(1).watch()
    s = new(found, "pl_unloaded_to_session_without_holder", plug=script(unloaded=["to_session"]))
    ready_after_reset(s, loaded=False).loaded(T1, "elsewhere").tick().adv(11).tick().adv(11).tick()
    s = new(found, "pl_unloaded_other_word_is_defer", plug=script(unloaded=["early", "hold", "bogus"]))
    ready_after_reset(s, loaded=False).loaded(T1, "notLoaded").tick().adv(11).tick().adv(11).tick()
    s = new(found, "pl_unloaded_raises_and_app_closed", plug=script(unloaded=["raise"]))
    s.backend(app=None)
    s._(op="backend", attrs={"holder": {T1: "none"}})
    ready_after_reset(s, loaded=False).tick().adv(11).tick().adv(11).tick().facts()
    s = new(found, "pl_unloaded_app_closed_holder", plug=script(unloaded=["queue_for_open"]))
    s.backend(app=None)
    s._(op="backend", attrs={"holder": {T1: "none"}})
    ready_after_reset(s, loaded=False).tick().adv(11).tick().adv(11).tick()
    return {}


def admission(found) -> dict:
    """P17 and P3's known_failure: a failure core never recovers alone, taken up; CAPACITY; and the AS_ words."""
    s = new(found, "pl_admit_unknown_code", plug=script(admission=["admit"], gates=[{"when": {"name": "known_failure"},
                                                                                     "answer": "admit"}]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(60).tick().adv(300).tick().adv(300).tick().adv(300).tick()
    s = new(found, "pl_admit_then_readmit_withdrawn", plug=script(admission=["admit"], gates=[
        {"when": {"name": "known_failure"}, "answer": "admit", "times": 1}]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(400).tick().adv(400).tick().adv(400).tick()
    s = new(found, "pl_admit_deferred_is_asked_again_after_a_minute", plug=script(admission=[{"answer": None}]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(30).tick().adv(31).tick().adv(61).tick()
    s = new(found, "pl_admit_as_timeout", plug=script(admission=["as_timeout"], gates=[
        {"when": {"name": "known_failure"}, "answer": "as_timeout"}]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(60).tick().adv(300).tick().adv(300).tick()
    s = new(found, "pl_admit_as_word_switched_off", plug=script(admission=["as_timeout"], gates=[
        {"when": {"name": "known_failure"}, "answer": "as_timeout"}]))
    s.policy(recover_timeout=False).loaded(T1)
    s.home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(60).tick().adv(300).tick()
    s = new(found, "pl_admit_unauthorized", plug=script(admission=["admit"], gates=[
        {"when": {"name": "known_failure"}, "answer": "admit"}]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json='{"codexErrorInfo": "unauthorized"}',
                      completed=int(BASE + 10))
    s.tick().adv(60).tick().adv(300).tick().adv(300).tick().adv(300).tick().adv(300).tick()
    s = new(found, "pl_admit_answer_outside_takes", plug=script(admission=["capacity", "early", "hold"]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(61).tick().adv(61).tick()
    s = new(found, "pl_admit_raises", plug=script(admission=["raise"]))
    s.loaded(T1).home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(61).tick().facts()
    s = new(found, "pl_admit_observe_only_asks_nothing", plug=script(admission=["admit"]))
    s.store("set_observe_only", True).loaded(T1)
    s.home("add_turn", T1, TURN_A, "failed", error_json=UNKNOWN_CODE, completed=int(BASE + 10))
    s.tick().adv(61).tick()
    s = new(found, "pl_capacity_retries", plug=script(gates=[{"when": {"name": "known_failure"}, "answer": "capacity"}]))
    s.backend(after_accept="queue").loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10), code="serverOverloaded")
    s.tick().adv(6).tick().adv(11).tick().helper("dispatch_and_fail", T1, code="serverOverloaded")
    for _ in range(4):
        s.watch().tick().adv(40).tick().adv(40).tick()
    s = new(found, "pl_capacity_window_closes", plug=script(gates=[{"when": {"name": "known_failure"},
                                                                    "answer": "capacity"}]))
    s.backend(default_outcome="not_started").loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10), code="serverOverloaded")
    s.tick().adv(6).tick()
    for _ in range(6):
        s.adv(7200).tick().tick()
    s = new(found, "pl_verified_reset_without_channel", plug=script(gates=[{"when": {"name": "known_failure"},
                                                                            "answer": "verified_reset"}]))
    ready_after_reset(s).tick().adv(11).tick().adv(11).tick()
    return {}


def kinds(found) -> dict:
    """P18 and P19: the kinds and wideners a plug names, each told to the reader and, once gone, cancelling."""
    s = new(found, "pl_kinds_widened_then_gone",
            plug=script(sessions=[{"answer": ["cli", "ide"], "times": 3}],
                        eligibility=[{"answer": ["every_desktop"], "times": 3}]))
    s.home("add_thread", T1, thread_source="review_x").home("add_thread", T2, thread_source="memory_consolidation")
    s.home("fail_usage", T1, TURN_A).home("fail_usage", T2, TURN_B).loaded(T1).loaded(T2)
    s.tick().tick().tick().adv(11).tick().tick().tick().tick().facts()
    s = new(found, "pl_kinds_widened_from_the_start", plug=script(eligibility=["every_desktop"], sessions=["cli"]))
    s.home("add_thread", T1, thread_source="review_x").home("fail_usage", T1, TURN_A).loaded(T1)
    s.tick().at(RESET + 61).tick().adv(11).tick().tick()
    s = new(found, "pl_kinds_bad_answers", plug=script(sessions=[["bogus", 5], "terminal", "raise", ["cli", "cli"]],
                                                       eligibility=[["every_desktop", "x"], "raise", "every_desktop"]))
    ready_after_reset(s).tick().tick().tick().tick().facts()
    s = new(found, "pl_kinds_not_wanted", plug=script(wants=[], sessions=[["cli"]], eligibility=[["every_desktop"]]))
    ready_after_reset(s).tick().tick().facts()
    return {}


def outcomes(found) -> dict:
    """P6 and P14: every outcome the engine tells, whether or not consent holds; a hook that fails."""
    for status, progress in (("completed", True), ("failed", True), ("failed", False), ("interrupted", False)):
        s = new(found, "pl_outcome_%s_%s" % (status, "progress" if progress else "none"))
        s.backend(turn_status=status, turn_progress=progress, after_accept="queue")
        ready_after_reset(s).tick().watch().adv(5).tick().adv(11).tick().home("add_turn", T1, TURN_C).adv(11).tick()
        s.adv(86400).tick()
    s = new(found, "pl_moved_and_outcome_raise", plug=script(moved=["raise"], outcome=["panic"]))
    s.backend(turn_status="completed", turn_progress=True, after_accept="queue")
    ready_after_reset(s).tick().watch().adv(5).tick().adv(11).tick().facts()
    s = new(found, "pl_outcome_not_asked_when_paused")
    s.backend(turn_status="completed", turn_progress=True, after_accept="queue")
    ready_after_reset(s).tick().watch().pause().adv(5).tick().watch().adv(11).tick()
    return {}


def resend(found) -> dict:
    """P7's RESEND: an uncertain submission the watch found no trace of, sent once more where core proves it may."""
    for name, answer, outcome in (("pl_resend_after_lost_send", "resend", "unknown"),
                                  ("pl_resend_not_started_again", "resend", "unknown"),
                                  ("pl_resend_held", "hold", "unknown")):
        s = new(found, name, plug=script(schedule=[{"when": {"state": "submission_unknown"}, "answer": answer}]))
        s.backend(default_outcome=outcome)
        ready_after_reset(s).tick().watch().adv(1).watch().adv(901).watch().tick().adv(60).watch().tick()
        s.adv(1800).watch().tick().watch().adv(60).watch().tick()
        if name == "pl_resend_not_started_again":
            s.backend(default_outcome="not_started").adv(60).watch().tick().adv(900).watch().tick()
    s = new(found, "pl_resend_gate_hold", plug=script(schedule=[{"when": {"state": "submission_unknown"},
                                                                 "answer": "resend"}],
                                                       gates=[{"when": {"name": "usage", "state": "submission_unknown"},
                                                               "answer": "hold"}]))
    s.backend(default_outcome="unknown")
    ready_after_reset(s).tick().watch().adv(1).watch().adv(901).watch().tick().adv(60).watch().tick()
    s = new(found, "pl_resend_receipt_arrives_duplicate", plug=script(schedule=[{"when": {"state": "submission_unknown"},
                                                                                 "answer": "resend"}]))
    s.backend(default_outcome="unknown")
    ready_after_reset(s).tick().watch().adv(1).watch().adv(901).watch()
    s.backend(default_outcome="accepted", after_accept="queue").tick().adv(1).watch().helper("duplicate_head", T1)
    s.adv(61).watch().tick().adv(61).watch().tick()
    return {}


BUILDERS = (after_reset, gates, words, unloaded, admission, kinds, outcomes, resend)


def scenarios() -> dict:
    found = []
    for build in BUILDERS:
        build(found)
    return dict(each.done() for each in found)


def with_plug(corpus: dict, wants=None) -> dict:
    """Every scenario of `corpus`, run again with a plug that wants every point and defers every question: the same
    decisions as NULL's, with each question the engine puts to a plug compared as it is asked."""
    return {"pd_" + name: dict(spec, plug=script(wants)) for name, spec in corpus.items()}


class EnginePlugDiff(unittest.TestCase):
    """Every scripted scenario's trace, step by step, the plug's questions with it."""

    maxDiff = None

    def check(self, found: dict, label: str, tag=None):
        import time
        started = time.monotonic()
        if ONLY:
            found = {name: spec for name, spec in found.items() if name.startswith(ONLY)}
        with mock.patch.object(reference, "TAG", tag or reference.TAG):
            expected, actual = diffs_engine.traces(found)
        steps = sends = asked = 0
        problems = []
        for name in found:
            difference = diffs_engine.first_difference(expected.get(name), actual.get(name))
            if difference:
                where, want, got = difference
                problems.append("%s at %s:\n  reference %s\n  rust      %s"
                                % (name, where, diffs_engine.short(want), diffs_engine.short(got)))
                continue
            trace = expected[name]
            if isinstance(trace, dict):
                problems.append("%s: both sides failed alike: %s" % (name, trace["failed"]))
                continue
            steps += len(trace)
            sends += sum(1 for step in trace for call in step["calls"] if call[0] == "send")
            asked += sum(1 for step in trace for call in step["calls"] if call[0] == "plug")
        RECORD.append("engine plug %s: %d scenarios, %d steps equal (%d sends, %d plug questions), %.0f s"
                      % (label, len(found), steps, sends, asked, time.monotonic() - started))
        self.assertEqual(problems, [], "\n".join(problems[:6]))

    def test_scripted_paths(self):
        self.check(scenarios(), "scripted paths")

    def test_corpus_with_a_deferring_plug(self):
        self.check(with_plug(diffs_engine.corpus()), "the corpus with a deferring plug")

    def test_random_walks_with_a_plug(self):
        self.check(dict(walk(seed) for seed in range(WALKS)), "random walks with a scripted plug")


def walk(seed: int):
    """One of diffs_engine's random walks, with a plug whose answers are drawn from the same seed."""
    name, spec = diffs_engine.generated(seed)
    rng = random.Random(1000 + seed)
    words_ = ["hold", "early", "resend", "send_now", "admit", "capacity", "as_timeout", "verified_reset", "queue_for_open",
              "to_session", "client_id", "silent", "bogus", "raise", "panic", None]
    rules = {hook: [{"answer": rng.choice(words_), "times": rng.choice([1, 2, 3, None]), "skip": rng.choice([0, 0, 1, 2])}
                    for _ in range(rng.choice([1, 2, 3]))]
             for hook in ("gate", "schedule", "outcome", "delivery", "unloaded", "admission", "text", "moved")
             if rng.random() < 0.6}
    spec = dict(spec, plug={"wants": [point for point in EVERY if rng.random() < 0.85], "rules": rules})
    return "pw_" + name, spec


if __name__ == "__main__":
    unittest.main()

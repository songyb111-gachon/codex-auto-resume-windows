"""Engine traces equal (S4.1, car-engine and car-scheduler): the reference's Engine and car-engine driven through the same
scenarios, step by step, and everything compared.

Each scenario is run twice, by `enginerun.run`: once in the reference tag's own Python (its Engine, Store and
LocalSource; `SCRIPT`), once in this process through `car-harness serve`'s engine session (car-engine over car-store and
car-codex), whose backend calls and jitter's draw are asked back to this side's stand-ins. Both worlds are built by the
tag's own `tests/codexsim.py`, with the same ids, on the same clock; quiet hours and a reset's time are read in UTC on
both sides (TZ=UTC0 for the reference, a UTC zone for Rust), a continuation's language from the same variable.

After every step the two traces must hold the same: the step's answer (or the class it raised), every log line and
notification, every backend call with its arguments (the sends' words among them, so the continuation text is held
byte for byte), and the whole state store, table by table, row by row, each value with its type.

The corpus is the frozen scenario modules' flows (tests/neutral.py MODULES: test_engine, test_recovery, test_outcomes,
test_correlation, test_pause_unknown, test_ladder_and_guards, test_skip_reasons, ...) written as step lists - never
those modules themselves, which stay byte for byte (test_released_calls) - and `generated`'s random walks.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest

import released
from rustdiff import core, reference

HERE = Path(__file__).resolve().parent
RECORD: list[str] = []
BASE = 1788628000.0
RESET = BASE + 3600.0
T1 = "11111111-1111-7111-8111-111111111111"
T2 = "22222222-2222-7222-8222-222222222222"
T3 = "33333333-3333-7333-8333-333333333333"
TURN_A = "aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa"
TURN_B = "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb"
TURN_C = "cccccccc-cccc-7ccc-8ccc-cccccccccccc"
# How many random walks, and how long each is (CODEX_AR_ENGINE_WALKS for a longer run).
WALKS = int(os.environ.get("CODEX_AR_ENGINE_WALKS", "60"))
WALK_STEPS = 60

SCRIPT = r'''
import importlib.util, sys
loaded = importlib.util.spec_from_file_location("enginerun", sys.argv[3])
enginerun = importlib.util.module_from_spec(loaded)
loaded.loader.exec_module(enginerun)
enginerun.reference_main(sys.argv[1], sys.argv[2])
'''


def load(path: Path, name: str):
    found = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


enginerun = load(HERE / "enginerun.py", "rustdiff_enginerun")


class Scenario:
    """A scenario as steps, written as the frozen modules' Harness writes them."""

    def __init__(self, name, **spec):
        self.name, self.spec, self.steps = name, dict(spec), []
        self.now = spec.get("clock", BASE + 10.0)

    def _(self, **step):
        self.steps.append(step)
        return self

    def enable(self):
        return self._(op="store", method="set_enabled", args=[True, self.now])

    def pause(self):
        return self._(op="store", method="set_enabled", args=[False, self.now])

    def adv(self, by):
        self.now += by
        return self._(op="advance", by=by)

    def at(self, moment):
        self.now = moment
        return self._(op="clock", at=moment)

    def tick(self, times=1):
        for _ in range(times):
            self._(op="tick")
        return self

    def watch(self):
        return self._(op="watch")

    def facts(self):
        return self._(op="facts")

    def home(self, method, *args, **kwargs):
        return self._(op="home", method=method, args=list(args), kwargs=kwargs)

    def helper(self, name, *args, **kwargs):
        return self._(op="helper", name=name, args=list(args), kwargs=kwargs)

    def backend(self, **values):
        return self._(op="backend", set=values)

    def loaded(self, thread=T1, value="loaded"):
        return self._(op="backend", loaded={thread: value})

    def outcome(self, thread, value):
        return self._(op="backend", outcomes={thread: value})

    def store(self, method, *args, **kwargs):
        return self._(op="store", method=method, args=list(args), kwargs=kwargs)

    def policy(self, **values):
        return self._(op="policy", values=values)

    def done(self):
        return self.name, dict(self.spec, steps=self.steps)


def ready_after_reset(s: Scenario, thread=T1, turn=TURN_A, loaded=True):
    s.home("fail_usage", thread, turn)
    if loaded:
        s.loaded(thread)
    return s.tick().at(RESET + 61)


def corpus() -> dict:
    """The frozen modules' flows, one scenario each (the test each follows is in its name)."""
    found = []

    def new(name, **spec):
        s = Scenario(name, **spec)
        found.append(s)
        return s.enable()

    # test_engine 01-18 and the crash/uncertainty tests
    new("e01_completed_no_action").home("add_turn", T1, TURN_A).tick(2)
    new("e02_interrupted_no_action").home("add_turn", T1, TURN_A, "interrupted").tick(2)
    new("e03_ordinary_failure_no_action").home("add_turn", T1, TURN_A, "failed",
                                               error_json='{"codexErrorInfo": "badRequest"}').tick(2)
    new("e04_malformed_entry").helper("raw_turn", error_json="not json").tick().helper("raw_turn", rollout_ordinal="x").tick()
    new("e05_usage_registers").home("fail_usage", T1, TURN_A).tick(2).facts()
    s = new("e08_after_reset_loaded_resumes")
    ready_after_reset(s).tick().adv(11).tick(2).adv(60).tick()
    s = new("e09_not_loaded_waits")
    ready_after_reset(s, loaded=False).tick().adv(61).tick().loaded(T1).adv(61).tick(2)
    s = new("e11_app_closed").backend(app=None)
    ready_after_reset(s).tick().adv(61).tick().backend(app="APP").adv(61).tick(2)
    s = new("e12_global_disable")
    ready_after_reset(s).pause().tick().adv(61).tick().enable().adv(61).tick()
    s = new("e13_thread_disabled_other_thread").store("set_thread_enabled", T1, False)
    s.home("fail_usage", T1, TURN_A).home("fail_usage", T2, TURN_B).loaded(T1).loaded(T2).tick().at(RESET + 61).tick(2)
    s = new("e15_launch_failures_bounded").backend(default_outcome="not_started")
    ready_after_reset(s)
    for _ in range(7):
        s.tick().adv(301)
    s = new("e15b_unknown_outcome_never_resent").backend(default_outcome="unknown")
    ready_after_reset(s).tick().watch().adv(1).watch().adv(900).tick().adv(86400).tick()
    s = new("e15c_transport_raises").backend(default_outcome="raise")
    ready_after_reset(s).tick().adv(2).tick()
    s = new("e15d_usage_unavailable").backend(usage_result={"available": False, "reset_at": None,
                                                           "limit_type": "exposed_windows", "reason": "ok"})
    ready_after_reset(s).tick().adv(901).tick().adv(1300).tick()
    s = new("e15e_retry_after_cooldown").backend(default_outcome="not_started")
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).loaded(T1).tick().adv(6).tick()
    s.backend(default_outcome="accepted").adv(31).tick().adv(900).tick()
    s = new("e17_two_threads_independent")
    s.home("fail_usage", T1, TURN_A).home("fail_usage", T2, TURN_B).loaded(T1).loaded(T2).tick().at(RESET + 61).tick()
    s.adv(11).tick(2)
    s = new("e_crash_unknown_then_receipt").backend(default_outcome="accepted_lost")
    ready_after_reset(s).tick().watch().adv(181).watch().adv(1).tick()
    s = new("e_queued_then_not_loaded_withdraws").backend(after_accept="queue")
    ready_after_reset(s).tick().watch().loaded(T1, "notLoaded").adv(6).watch().adv(181).watch().adv(1).tick()
    s = new("e_queued_withdrawn_after_timeout").backend(after_accept="queue")
    ready_after_reset(s).tick().adv(181).watch().adv(181).watch().tick()
    s = new("e_cleanup_unconfirmed").backend(after_accept="queue", delete_result=False)
    ready_after_reset(s).tick().pause()
    for _ in range(6):
        s.adv(11).watch()
    s = new("e_unknown_loaded_never_queues").loaded(T1, "unknown")
    ready_after_reset(s).tick().adv(61).tick()
    s = new("e_cancel_pending").home("fail_usage", T1, TURN_A).loaded(T1).tick()
    s.store("cancel_thread", T1, BASE + 10).at(RESET + 61).tick()
    s = new("e_superseded_by_user").home("fail_usage", T1, TURN_A).loaded(T1).tick()
    s.home("add_turn", T1, TURN_B).at(RESET + 61).tick(2)
    s = new("e_cooldown_and_daily_cap", options={"thread_cooldown_seconds": 900})
    s.loaded(T1)
    for index in range(7):
        s.home("fail_transient", T1, completed=int(s.now)).tick().adv(6).tick().adv(1).tick().adv(11).tick()
        s.adv(901 if index % 2 else 120)
    s = new("e_daily_cap_wait", options={"max_submissions_per_thread_per_day": 2, "thread_cooldown_seconds": 60})
    s.loaded(T1)
    for _ in range(3):
        s.home("fail_transient", T1, completed=int(s.now)).tick().adv(6).tick().adv(1).tick().adv(11).tick().adv(70)
    s.tick().adv(61).tick()
    s = new("e_history_unavailable").home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s.helper("history_aside", True).tick().facts().helper("history_aside", False).tick().facts()
    s = new("e_no_reset_conservative").home("fail_usage", T1, TURN_A, reset=None).loaded(T1).tick()
    s.adv(901).tick().adv(11).tick()
    # T01-T10: correlation, the watch, the queue
    s = new("t02a_two_marker_rows").backend(after_accept="queue")
    ready_after_reset(s).tick().helper("duplicate_head", T1).watch().adv(61).watch().tick()
    s = new("t02b_marker_in_someone_elses_turn").backend(after_accept="queue")
    ready_after_reset(s).tick().home("dispatch", T1, first_user=False).watch().adv(1).watch()
    s = new("t03_undetermined_turn").backend(after_accept="queue")
    ready_after_reset(s).tick().home("add_turn", T1, None, "inProgress", user_text=None).adv(181).watch().adv(1).watch()
    s = new("t05_withdrawal_settles").backend(after_accept="queue")
    ready_after_reset(s).tick().store("cancel_thread", T1, RESET + 61).watch().adv(181).watch().adv(1).watch().tick()
    s = new("t05_withdrawal_over_stale_history").backend(after_accept="queue")
    ready_after_reset(s).tick().pause().watch().home("make_stale", T1).adv(181).watch().adv(1).watch()
    s = new("t08_change_between_claim_and_send")
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61).home("make_stale", T1).tick()
    s.home("catch_up", T1).adv(61).tick()
    s = new("t09_foreign_queued_waits").home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s.home("enqueue", T1, "the person's own message").tick().helper("remove_head", T1).adv(61).tick()
    s = new("t09_foreign_behind_ours_takes_ours_back").backend(after_accept="queue")
    ready_after_reset(s).tick().home("enqueue", T1, "typed after ours").watch().adv(1).watch().adv(181).watch()
    s = new("t10_edited_item_handed_over").backend(after_accept="queue")
    ready_after_reset(s).tick().helper("edit_head", T1).watch().adv(1).tick()
    # T13-T17, test_outcomes: how a recovery turn ends
    for status, progress in (("completed", True), ("completed", False), ("failed", True), ("failed", False),
                             ("interrupted", False), ("inProgress", True), ("inProgress", False)):
        s = new("o_turn_%s_%s" % (status, "progress" if progress else "none"))
        s.backend(turn_status=status, turn_progress=progress)
        ready_after_reset(s).tick().adv(5).tick().adv(11).tick().home("add_turn", T1, TURN_C).adv(11).tick()
        s.adv(86400).tick()
    # The edges a whole-second scenario steps over: a settle that ends on the very second, a reset already past.
    s = new("o_settle_boundary")
    ready_after_reset(s).tick()
    for _ in range(13):
        s.adv(1).tick()
    s = new("e_reset_already_past").home("fail_usage", T1, TURN_A, reset=BASE - 100).loaded(T1)
    for _ in range(9):
        s.tick().adv(5)
    # A reset just ahead, with no grace: the first look is half a minute away all the same.
    s = new("e_reset_inside_half_minute", options={"reset_grace_seconds": 0})
    s.home("fail_usage", T1, TURN_A, reset=BASE + 20).loaded(T1)
    for _ in range(8):
        s.tick().adv(5)
    # A usage reading reused for 30 seconds and not one more (C9): the second conversation falls due 31 s after the
    # first one's read, with usage gone meanwhile.
    s = new("f_usage_cache_boundary").loaded(T1).loaded(T2)
    s.home("fail_transient", T1, TURN_A, completed=int(s.now)).tick().adv(6).tick().adv(25)
    s.home("fail_transient", T2, TURN_B, completed=int(s.now)).tick()
    s.backend(usage_result={"available": False, "reset_at": None, "limit_type": "x", "reason": "ok"}).adv(6).tick()
    s.adv(1).tick()
    s = new("o_dispatch_then_usage_child").backend(after_accept="queue")
    ready_after_reset(s).tick().helper("dispatch_and_fail", T1, usage=True, progress=True, reset=RESET + 7200)
    s.watch().tick().adv(11).tick().at(RESET + 7300).tick(2)
    s = new("o_dispatch_then_transient_child").backend(after_accept="queue")
    ready_after_reset(s).tick().helper("dispatch_and_fail", T1, progress=False, code="serverOverloaded")
    s.watch().tick().adv(11).tick().adv(30).tick().adv(11).tick()
    s = new("o_user_joins_turn").backend(after_accept="queue")
    ready_after_reset(s).tick().home("dispatch", T1, status="inProgress", progress=False, steer_user=True)
    s.watch().tick().adv(11).tick()
    # T24/T25, test_pause_unknown: Pause and Observe only take a queued item back
    s = new("t24_pause_withdraws_and_releases").backend(after_accept="queue")
    ready_after_reset(s).tick().pause().watch().adv(181).watch().adv(1).watch().enable().adv(61).tick()
    s = new("t24_paused_withdrawal_ran_anyway").backend(after_accept="queue", delete_result=True)
    ready_after_reset(s).tick().pause().watch().home("dispatch", T1).adv(1).watch().tick()
    s = new("p_pause_unknown_is_final").backend(after_accept="queue", default_outcome="unknown")
    ready_after_reset(s).tick().home("enqueue", T1, "x").pause().watch().adv(181).watch().adv(1).watch()
    s = new("p_observe_only_would_send").store("set_observe_only", True)
    ready_after_reset(s).tick(2).adv(901).tick().store("set_observe_only", False).adv(61).tick()
    s = new("p_observe_only_takes_back").backend(after_accept="queue")
    ready_after_reset(s).tick().store("set_observe_only", True).watch().adv(181).watch().adv(1).watch()
    # T31/T32/T28: waits with a reason, stale histories, usage that never lifts
    s = new("t31_future_reset_waits").home("fail_usage", T1, TURN_A, reset=RESET + 86400).loaded(T1).tick()
    s.at(RESET + 61).tick().at(RESET + 86400 + 61).tick()
    s = new("t32_stale_history_blocks").home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s.home("make_stale", T1).tick().adv(130).tick().home("catch_up", T1).adv(61).tick()
    s = new("t32_missing_projection_table").home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s.helper("drop_projection_table").tick().adv(61).tick()
    s = new("t28_never_available", options={"usage_never_available_seconds": 3000})
    s.backend(usage_result={"available": False, "reset_at": None, "limit_type": "x", "reason": "ok"})
    ready_after_reset(s)
    for _ in range(6):
        s.tick().adv(901)
    s = new("t28_not_restored_after_reset", options={"usage_after_reset_seconds": 1000})
    s.backend(usage_result={"available": False, "reset_at": RESET + 100, "limit_type": "x", "reason": "ok"})
    ready_after_reset(s).tick().adv(1200).tick().adv(1200).tick()
    s = new("t47_subagent_never_detected").home("add_thread", T1, thread_source="subagent")
    s.home("fail_usage", T1, TURN_A).tick(2)
    # settings: categories, ladders, budgets, quiet hours, tiers, guards, needs-you, sleep and the network
    s = new("s_category_off").policy(recover_server_5xx=False).home("fail_transient", T1, TURN_A).tick(3)
    s = new("s_timing_patient").policy(retry_timing="patient").loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(60).tick().adv(600).tick()
    s = new("s_custom_ladder_and_jitter", seed=11).policy(retry_timing="custom", retry_wait_1="2m", retry_wait_2="9m",
                                                          retry_jitter=True).loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(130).tick().adv(11).tick()
    s.helper("dispatch_and_fail", T1).watch().tick().adv(700).tick()
    s = new("s_budget_from_settings").policy(max_recovery_attempts=1, max_no_progress=1).loaded(T1)
    s.backend(after_accept="queue")
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(6).tick()
    s.helper("dispatch_and_fail", T1).watch().tick().adv(16).tick().adv(30).tick()
    s = new("s_quiet_hours").policy(quiet_hours_start="00:00", quiet_hours_end="23:00")
    ready_after_reset(s).tick().adv(61).tick().at(BASE + 86400 * 1.5).tick()
    s = new("s_objection_window").store("set_thread_tier", T1, "objection_window", BASE + 10)
    ready_after_reset(s).tick().adv(61).tick().adv(300).tick()
    s = new("s_ask_first_holds").store("set_thread_tier", T1, "ask_first", BASE + 10)
    ready_after_reset(s).tick(2)
    s = new("s_notify_only_new").policy(new_conversation_policy="notify_only")
    ready_after_reset(s).tick(2)
    s = new("s_needs_you_notices").policy(notify_needs_you=True, stall_after="10m")
    s.home("add_turn", T1, TURN_A, "failed", error_json='{"codexErrorInfo": "unauthorized"}')
    s.home("add_turn", T2, TURN_B, "inProgress").tick().adv(700).tick().adv(60).tick()
    s = new("s_sleep_holds").policy(ask_after_sleep_minutes="m30")
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().at(RESET + 61)
    s._(op="after_sleep", since=RESET - 10, slept=7200.0).tick(2)
    s = new("s_offline_waits", connectivity=False).policy(wait_for_network=True)
    ready_after_reset(s).tick().adv(61).tick()
    s = new("s_engine_incompatible", engine_state="incompatible")
    ready_after_reset(s).tick(2)
    s = new("s_home_lock_unavailable", home_lock=False)
    ready_after_reset(s).tick(2)
    s = new("s_notifier_raises", notify_raises=True)
    ready_after_reset(s).tick().adv(11).tick(2)
    s = new("s_extra_home", home_key="b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6" * 2)
    ready_after_reset(s).tick().adv(11).tick(2)
    s = new("s_language_korean", lang="ko").policy(continuation_style="detailed")
    ready_after_reset(s).tick().adv(11).tick()
    s = new("s_custom_message").policy(continuation_style="custom", custom_message="Keep going, attempt {attempt}.")
    ready_after_reset(s).tick().adv(11).tick()
    s = new("s_retry_now_reads_usage").home("fail_usage", T1, TURN_A, reset=RESET + 86400).loaded(T1).tick()
    s.adv(61).store("request_retry_now", {"$key": T1}, s.now).tick().adv(1).tick()
    s = new("s_retiring").home("fail_usage", T1, TURN_A).loaded(T1).tick()._(op="retiring", value=True)
    s.at(RESET + 61).tick(2)
    # test_skip_reasons: why a failed turn is passed over
    s = new("k_skips_and_counts").store("set_thread_enabled", T2, False)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE - 8 * 3600))
    s.home("fail_transient", T2, TURN_B).home("add_turn", T3, TURN_C, "failed", error_json='{"codexErrorInfo": "x"}')
    s.tick(2).policy(recover_server_5xx=False).home("fail_transient", T1, completed=int(BASE + 10)).tick(2)
    return dict(each.done() for each in found)


CODES = ["serverOverloaded", "internalServerError", "httpConnectionFailed", "responseStreamDisconnected",
         "rateLimitExceeded", "badRequest", "unauthorized"]


def generated(seed: int) -> tuple:
    """A random walk: failures, turns, the person's actions and the app's moods, ticks and watches between."""
    rng = random.Random(seed)
    threads = [T1, T2, T3][:rng.choice([1, 2, 3])]
    options = rng.choice([{}, {"delivery_timeout_seconds": 300}, {"settle_seconds": 0, "state_poll_seconds": 5}])
    s = Scenario("walk_%03d" % seed, seed=seed, options=options).enable()
    if rng.random() < 0.4:
        s.policy(**rng.choice([{"retry_timing": "fast"}, {"retry_timing": "patient"}, {"retry_jitter": True},
                               {"max_recovery_attempts": 2}, {"recover_server_5xx": False},
                               {"continuation_style": "minimal"}, {"max_chain_continuations": 2}]))
    for thread in threads:
        s.home("add_thread", thread)
        if rng.random() < 0.85:
            s.loaded(thread)
    for _ in range(WALK_STEPS):
        thread = rng.choice(threads)
        roll = rng.random()
        if roll < 0.08:
            s.home("fail_usage", thread, completed=int(s.now), reset=rng.choice([None, s.now + 60, s.now + 600]))
        elif roll < 0.18:
            s.home("fail_transient", thread, completed=int(s.now), code=rng.choice(CODES))
        elif roll < 0.21:
            s.home("add_turn", thread)
        elif roll < 0.27:
            s.home("dispatch", thread, status=rng.choice(["completed", "failed", "inProgress"]),
                   progress=rng.random() < 0.6)
        elif roll < 0.31:
            s.helper("dispatch_and_fail", thread, usage=rng.random() < 0.5, progress=rng.random() < 0.5,
                     reset=s.now + 120)
        elif roll < 0.35:
            s.loaded(thread, rng.choice(["loaded", "loaded", "loaded", "notLoaded", "unknown"]))
        elif roll < 0.39:
            s.backend(**rng.choice([{"default_outcome": "accepted"}, {"default_outcome": "accepted"},
                                    {"default_outcome": "not_started"}, {"default_outcome": "unknown"},
                                    {"after_accept": "queue"}, {"after_accept": "dispatch"},
                                    {"turn_status": "failed"}, {"turn_status": "completed"},
                                    {"turn_progress": False}, {"turn_progress": True},
                                    {"delete_result": False}, {"delete_result": None}, {"app": None}, {"app": "APP"},
                                    {"usage_result": {"available": False, "reset_at": None, "limit_type": "x",
                                                      "reason": "ok"}},
                                    {"usage_result": {"available": True, "reset_at": None,
                                                      "limit_type": "exposed_windows", "reason": "ok"}}]))
        elif roll < 0.42:
            choice = rng.random()
            if choice < 0.3:
                s.store("set_enabled", rng.random() < 0.7, s.now)
            elif choice < 0.55:
                s.store("set_thread_enabled", thread, rng.random() < 0.7)
            elif choice < 0.75:
                s.store("set_observe_only", rng.random() < 0.3)
            else:
                s.store("cancel_thread", thread, s.now)
        elif roll < 0.44:
            s.home(rng.choice(["make_stale", "catch_up"]), thread)
        elif roll < 0.46:
            s.home("enqueue", thread, "the person's own words")
        elif roll < 0.48:
            s.helper(rng.choice(["edit_head", "remove_head"]), thread)
        elif roll < 0.83:
            s.adv(rng.choice([1, 6, 11, 31, 61, 181, 301, 901, 3700])).tick()
        elif roll < 0.91:
            s.watch()
        else:
            s.tick()
    return s.done()


def tag_codexsim(tag: str, folder: Path) -> Path:
    """The reference tag's own tests/codexsim.py, taken out of git."""
    found = subprocess.run(["git", "-C", str(core.ROOT), "show", "%s:tests/codexsim.py" % tag], capture_output=True,
                           check=True, creationflags=core.NO_WINDOW)
    path = folder / "codexsim.py"
    path.write_bytes(found.stdout)
    return path


def traces(scenarios: dict) -> tuple:
    """(reference traces, Rust traces) of every scenario, each a name -> list of steps (or {"failed": why})."""
    with tempfile.TemporaryDirectory(prefix="rustdiff-engine-") as scratch:
        scratch = Path(scratch)
        sim_path = tag_codexsim(reference.TAG, scratch)
        profile = scratch / "profile"
        profile.mkdir()
        request = scratch / "request.json"
        out = scratch / "reference.json"
        request.write_text(json.dumps({"codexsim": str(sim_path), "scenarios": scenarios,
                                       "root": str(scratch / "ref")}), encoding="utf-8")
        source = released.package(reference.TAG)
        environment = reference.scratch_environment(profile, PYTHONPATH=str(source), TZ="UTC0")
        ran = subprocess.run(reference.command(SCRIPT, request, out, HERE / "enginerun.py", paths=[source]),
                             capture_output=True, env=environment, cwd=str(profile),
                             creationflags=core.NO_WINDOW, timeout=3600)
        if ran.returncode != 0:
            raise AssertionError("the reference failed: " + ran.stderr.decode("utf-8", "replace")[-3000:])
        expected = json.loads(out.read_text(encoding="utf-8"))
        codexsim = load(sim_path, "rustdiff_codexsim")
        harness = subprocess.Popen([str(core.binary("car-harness")), "serve"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=reference.scratch_environment(profile), creationflags=core.NO_WINDOW)
        actual = {}
        try:
            for number, (name, spec) in enumerate(scenarios.items(), start=1):
                try:
                    actual[name] = enginerun.run(spec, codexsim, scratch / "rust" / name, enginerun.RustSide,
                                                 harness=harness, session=number)
                except Exception as error:
                    actual[name] = {"failed": "%s: %s" % (type(error).__name__, error)}
        finally:
            harness.stdin.close()
            harness.wait(timeout=60)
            os.environ.pop(enginerun.LANG, None)
        return expected, actual


def first_difference(expected, actual, path=""):
    """Where two traces first part: a path and the two values there, or None."""
    if type(expected) is not type(actual):
        return path, expected, actual
    if isinstance(expected, dict):
        for key in list(expected) + [key for key in actual if key not in expected]:
            if key not in expected or key not in actual:
                return path + "/" + str(key), expected.get(key, "<absent>"), actual.get(key, "<absent>")
            found = first_difference(expected[key], actual[key], path + "/" + str(key))
            if found:
                return found
        return None
    if isinstance(expected, list):
        for index, (a, b) in enumerate(zip(expected, actual)):
            found = first_difference(a, b, "%s[%d]" % (path, index))
            if found:
                return found
        if len(expected) != len(actual):
            return path + "/len", len(expected), len(actual)
        return None
    return None if expected == actual else (path, expected, actual)


def short(value, limit=600):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


class EngineTraceDiff(unittest.TestCase):
    """Every scenario's trace, step by step: decisions, state writes, notices, announcements and launches."""

    maxDiff = None

    def check(self, scenarios: dict, label: str):
        started = time.monotonic()
        expected, actual = traces(scenarios)
        steps = sends = moves = 0
        problems = []
        for name in scenarios:
            found = first_difference(expected.get(name), actual.get(name))
            if found:
                where, want, got = found
                problems.append("%s at %s:\n  reference %s\n  rust      %s" % (name, where, short(want), short(got)))
                continue
            trace = expected[name]
            if isinstance(trace, dict):
                problems.append("%s: both sides failed alike: %s" % (name, trace["failed"]))
                continue
            steps += len(trace)
            sends += sum(1 for step in trace for call in step["calls"] if call[0] == "send")
            moves += sum(len(step["log"]) for step in trace)
        RECORD.append("engine %s: %d scenarios, %d steps equal (%d sends, %d log lines), %.0f s"
                      % (label, len(scenarios), steps, sends, moves, time.monotonic() - started))
        self.assertEqual(problems, [], "\n".join(problems[:5]))

    def test_corpus(self):
        self.check(corpus(), "corpus (the frozen modules' flows)")

    def test_generated(self):
        self.check(dict(generated(seed) for seed in range(WALKS)), "random walks")

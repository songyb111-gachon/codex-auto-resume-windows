"""Standard-edition inputs the engine corpus never fed (review 6, S4; outputs/plans/v0627-rust/REVIEW-engine.md), run as
diffs_engine's traces are: the reference's Engine and car-engine through car-harness on the same worlds, every step
compared (the answer, the log, the notifications, every backend call and the whole state store).

* An administrator's policy (`policy` with `managed`): DisableAutoResume as a Pause, ForceObserveOnly, the administrator's
  quiet hours beside a person's (`more_quiet`), and MaxRecoveryAttempts' clamp, on the budgets and on `capacity_limits`.
* engine/impossible.py, pure (`judge`): the recovery rules' looks and gaps, the detection rules' ticks, the words, and
  `usage_reason` / `recovery_facts` over their edges.
* The backend's attributes read with getattr (`backend` with `attrs`): `app_look` "unmatched" and its reason,
  `engine_version`, `protocol_results` (a usage probe that broke), `session_holder` and `holder`.
* What the watcher reads of an engine: `activity` (the power action's) and `last_usage` (the heartbeat's), in `facts`.
* A clock set back: a cached usage reading and a cached loaded state are not reused across it.
* Fractional options (review 6, note 1): a budget, a ladder step, the day's cap and the withdraw attempts given as floats.
"""
from __future__ import annotations

import unittest

from rustdiff import diffs_engine

RECORD = diffs_engine.RECORD
Scenario, ready_after_reset = diffs_engine.Scenario, diffs_engine.ready_after_reset
T1, T2, TURN_A, TURN_B, RESET, BASE = (diffs_engine.T1, diffs_engine.T2, diffs_engine.TURN_A, diffs_engine.TURN_B,
                                       diffs_engine.RESET, diffs_engine.BASE)
QUIET = {"quiet_hours_start": "00:00", "quiet_hours_end": "23:30", "quiet_hours_days": "every_day"}


def managed(**fields) -> dict:
    found = {"disable_auto_resume": False, "force_observe_only": False, "disable_update_check": False,
             "disable_status_file": False, "max_recovery_attempts": None, "quiet_hours": [],
             "disable_power_action": False}
    found.update(fields)
    return found


def administrator() -> list:
    found = []
    s = Scenario("s4_admin_disable_auto_resume").enable()
    s._(op="policy", values={}, managed=managed(disable_auto_resume=True))
    ready_after_reset(s).tick(2).facts()
    s._(op="policy", values={}, managed=managed()).tick().facts()
    found.append(s)
    s = Scenario("s4_admin_force_observe_only").enable()
    s._(op="policy", values={}, managed=managed(force_observe_only=True))
    ready_after_reset(s).tick(2).adv(120).tick().facts()
    found.append(s)
    s = Scenario("s4_admin_quiet_hours").enable()
    s._(op="policy", values={"quiet_hours_start": "off"}, managed=managed(quiet_hours=[QUIET]))
    ready_after_reset(s).tick().adv(1800).tick().adv(86400).tick().facts()
    found.append(s)
    s = Scenario("s4_admin_max_recovery_attempts").enable()
    s._(op="policy", values={"max_recovery_attempts": 4}, managed=managed(max_recovery_attempts=1))
    s.backend(after_accept="queue").loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(6).tick()
    for _ in range(3):          # our continuation runs and fails; the child waits its step, and is sent
        s.helper("dispatch_and_fail", T1).watch().tick().adv(16).tick().adv(30).tick().adv(60).tick()
    s.facts()
    found.append(s)
    return found


def judged() -> list:
    s = Scenario("s4_impossible_judge")
    looks = [["look", BASE + 60 * i, True, {"held_elsewhere": True, "usage_protocol": i % 7 != 3}] for i in range(40)]
    looks += [["word", BASE + 60 * 39], ["look", BASE + 60 * 45, True, {"held_elsewhere": True}],
              ["word", BASE + 60 * 45], ["look", BASE + 60 * 44, True, {"held_elsewhere": True}],
              ["word", BASE + 60 * 46], ["look", BASE + 60 * 47, False, {"held_elsewhere": True}],
              ["word", BASE + 60 * 47]]
    ticks = [["tick", True, {"history_unreadable": True}], ["word", BASE], ["tick", True, {"history_unreadable": True}],
             ["tick", True, {"history_unreadable": True}], ["word", BASE], ["tick", False, {"engine_missing": True}],
             ["word", BASE], ["tick", True, {"engine_missing": True}], ["tick", True, {"engine_missing": True}],
             ["tick", True, {"engine_missing": True, "history_unreadable": True}], ["word", BASE]]
    method, start = "account/rateLimits/read", "initialize"
    usage = [[{"reason": "usage_snapshot_unknown"}, None], [{"reason": "usage_probe_unavailable"}, None],
             [{"reason": "usage_probe_unavailable"}, {method: ["protocol_timeout", 5.0]}],
             [{"reason": "usage_probe_unavailable"}, {method: ["protocol_method_unknown", 5.0]}],
             [{"reason": "usage_probe_unavailable"}, {method: ["ok", 5.0], start: ["protocol_unavailable", 6.0]}],
             [{"reason": "usage_probe_unavailable"}, {method: ["ok", 7.0], start: ["protocol_unavailable", 6.0]}],
             [{"reason": "usage_probe_unavailable"}, {start: ["protocol_home_mismatch", 6.0]}],
             [{"reason": "usage_probe_unavailable"}, {method: ["something_new", 5.0]}],
             [{"reason": "other"}, {method: ["protocol_timeout", 5.0]}], ["not a dict", {}]]
    base = {"matched": True, "server": 41, "reasons": ["held_by_other_session"], "lock_holders": [52],
            "database_holders": [52], "locks_folder": True, "older_holders": []}
    facts = [base, dict(base, matched=False), dict(base, server=None), dict(base, database_holders=None),
             dict(base, database_holders=[41], reasons=["notLoaded"], locks_folder=False),
             dict(base, database_holders=[41], reasons=["notLoaded"], locks_folder=None),
             dict(base, database_holders=[52], older_holders=[[41], [7]]), dict(base, lock_holders=[41]),
             dict(base, reasons=[]), dict(base, reasons=["loaded_state_unknown"], lock_holders=[41, 52])]
    s._(op="judge", script=looks + ticks, usage=usage, facts=facts)
    return [s]


def attributes() -> list:
    found = []
    s = Scenario("s4_backend_app_unmatched").enable()
    s.backend(app=None)
    s._(op="backend", attrs={"app_look": "unmatched", "app_unmatched_reason": "server_not_found"})
    ready_after_reset(s, loaded=False).tick(2).facts()
    found.append(s)
    s = Scenario("s4_backend_usage_probe_broken").enable()
    s.backend(usage_result={"available": None, "reset_at": None, "limit_type": "unknown",
                            "reason": "usage_probe_unavailable"})
    s._(op="backend", attrs={"protocol_results": {"account/rateLimits/read": ["protocol_timeout", BASE]}})
    ready_after_reset(s).tick(2).facts()
    found.append(s)
    s = Scenario("s4_backend_engine_version_and_holder").enable()
    s._(op="backend", attrs={"engine_version": "0.130.0", "session_holder": [4242, 1.5], "holder": {T1: "elsewhere"}})
    s.home("fail_usage", T1, TURN_A).loaded(T1, "elsewhere").tick().at(RESET + 61).tick(2).facts()
    found.append(s)
    return found


def watcher_reads() -> list:
    s = Scenario("s4_activity_and_last_usage").enable()
    windows = [{"bucket": "codex", "window": "primary", "used_percent": 12, "window_minutes": 300,
                "reset_at": int(RESET + 18000)},
               {"bucket": "codex", "window": "secondary", "used_percent": 40.5, "window_minutes": 10080,
                "reset_at": None}]
    s.backend(usage_result={"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok",
                            "windows": windows})
    ready_after_reset(s)
    s._(op="facts", threads=[T1, T2]).tick()._(op="facts", threads=[T1])
    s.helper("dispatch_and_fail", T1, progress=True).tick().adv(31).tick().adv(31).tick()._(op="facts", threads=[])
    return [s]


def clock_back() -> list:
    s = Scenario("s4_clock_set_back").enable()
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick()
    s.backend(usage_result={"available": False, "reset_at": RESET + 3600, "limit_type": "300m", "reason": "blocked"})
    s.at(RESET + 61).tick().at(RESET + 40).tick()
    s.backend(usage_result={"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"})
    s.at(RESET + 50).tick().loaded(T1, "notLoaded").at(RESET + 45).tick().at(RESET + 3700).tick(2).facts()
    return [s]


def fractions() -> list:
    """Note 1: the numbers Engine(options=...) is given, used as given."""
    s = Scenario("s4_fraction_options", options={"max_recovery_attempts": 2.5, "retry_ladder": [5.5, 15, 30.5],
                                                 "max_submissions_per_thread_per_day": 2.5,
                                                 "max_withdraw_attempts": 1.5}).enable()
    s.backend(after_accept="queue").loaded(T1)
    s.home("fail_transient", T1, TURN_A, completed=int(BASE + 10)).tick().adv(6).tick()
    for _ in range(4):
        s.helper("dispatch_and_fail", T1).watch().tick().adv(16).tick().adv(30).tick().adv(60).tick()
    s.facts()
    return [s]


class EngineInputsDiff(unittest.TestCase):
    """Traces of the standard edition's inputs the corpus never fed (review 6, S4)."""

    maxDiff = None

    def check(self, scenarios: list, label: str):
        scenarios = dict(each.done() for each in scenarios)
        expected, actual = diffs_engine.traces(scenarios)
        problems = []
        for name in scenarios:
            found = diffs_engine.first_difference(expected.get(name), actual.get(name))
            if found:
                where, want, got = found
                problems.append("%s at %s:\n  reference %s\n  rust      %s"
                                % (name, where, diffs_engine.short(want), diffs_engine.short(got)))
            elif isinstance(expected.get(name), dict):
                problems.append("%s: both sides failed alike: %s" % (name, expected[name]["failed"]))
        steps = sum(len(each["steps"]) for each in scenarios.values())
        RECORD.append("engine inputs (%s): %d scenarios, %d steps, %d differ" % (label, len(scenarios), steps,
                                                                                  len(problems)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_administrators_policy(self):
        self.check(administrator(), "an administrator's policy")

    def test_impossible_judge(self):
        self.check(judged(), "impossible.py")

    def test_backend_attributes(self):
        self.check(attributes(), "the backend's getattr attributes")

    def test_watcher_reads(self):
        self.check(watcher_reads(), "activity and last_usage")

    def test_fraction_options(self):
        self.check(fractions(), "fractional options")

    def test_clock_set_back(self):
        self.check(clock_back(), "a clock set back")


if __name__ == "__main__":
    unittest.main()

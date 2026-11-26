"""S7.2e2: `engine/wake.py` (wake_for_reset, P8) as the v0.6.26 final has it, held equal to car-adv's `engine::wake`.

A case is one WakeForReset over a scratch home's real advanced state - reset rules with and without a due time, meter
rows with a pause held (or held for another reset), window_anchor's stamps and choices, its own lead, its arming row -
with a scripted timer (set, cancel, allowed: answers or raises; `due` follows what it was told), a scripted view
(settings, records_in: core's waiting records of every category and state, or a raise) and a scripted thread start.
A walk ticks, runs the errand, looks with the watch, moves the clock past STALE and ASK_EVERY, turns the capability
off and on, and arms window_anchor and back. Compared: every answer, every call in order, every row after.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_wake`.
"""
from __future__ import annotations

import random
import unittest

from rustdiff import advtime

CAPABILITY = "wake_for_reset"
NOW = advtime.NOW


def record(rng: random.Random) -> dict:
    found = {"interruption_id": "r%d" % rng.randint(0, 99), "category": rng.choice(["usage_limit"] * 3 + ["network", None]),
             "state": rng.choice(["waiting_reset", "waiting_poll", "waiting_for_usage", "queued", "failed"]),
             "hold": None if rng.random() < 0.85 else "person"}
    for key in ("next_attempt_at", "reset_at", "postponed_until"):
        if rng.random() < 0.6:
            found[key] = rng.choice([NOW + rng.randint(-600, 20000), 0, None, NOW + 0.5])
    return found


def setup(rng: random.Random) -> list:
    calls = []
    if rng.random() < 0.3:
        calls.append(["set_option", [CAPABILITY, "wake_lead_minutes", rng.choice([1, 2, 5])],
                      {"generation": 0, "actor": "dashboard"}])
    if rng.random() < 0.8:
        calls.append(["move", [CAPABILITY, "armed"], {"actor": "dashboard"}])
    for ordinal in range(rng.choice([0, 0, 1, 2])):
        calls.append(["add_reset_rule", ["reset_credit", "codex", 300, ordinal + 1], {}])
        if rng.random() < 0.7:
            calls.append(["change_rule", [ordinal + 1], {"due_at": NOW + rng.choice([-100, 30, 200, 4000, 90000])}])
    if rng.random() < 0.5:
        reset = int(NOW) + rng.choice([500, 3000, -50])
        windows = [{"bucket": "codex", "window_minutes": 300, "used_percent": 100, "reset_at": reset},
                   {"bucket": "codex", "window_minutes": 10080, "used_percent": 40, "reset_at": reset + 86400}]
        calls.append(["save_meter", [windows], {}])
        if rng.random() < 0.8:
            calls.append(["mark_meter", ["codex", 300], {"paused_reset_at": reset + rng.choice([0, 0, 60])}])
    for key, chance in (("anchor_seen_reset", 0.4), ("anchor_slot_done", 0.2), ("anchor_reset_done", 0.2),
                        ("anchor_next_look", 0.3)):
        if rng.random() < chance:
            calls.append(["stamp", ["window_anchor", key, int(NOW) + rng.choice([-4000, 100, 900, 7000])], {}])
    return calls


def view(rng: random.Random) -> dict:
    script = {}
    if rng.random() < 0.7:
        script["records_in"] = [[record(rng) for _ in range(rng.randint(0, 4))] if rng.random() < 0.9
                                else {"raise": "RuntimeError"} for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.5:
        script["settings"] = [rng.choice([{"poll_seconds": rng.choice([5, 60, 300, 3600, 3601, 0, -5, 30.0, True])},
                                          {}, None, [1], "x", {"raise": "RuntimeError"}])]
    return script


def timer(rng: random.Random) -> dict:
    script = {}
    for kind, choices in (("set", [True, True, False, 0, {"raise": "OSError"}]),
                          ("cancel", [True, False, 1, {"raise": "OSError"}]),
                          ("allowed", [True, True, False, 1, None, {"raise": "OSError"}])):
        if rng.random() < 0.3:
            script[kind] = [rng.choice(choices) for _ in range(rng.randint(1, 3))]
    return script


def walk(rng: random.Random) -> dict:
    steps, now = [], NOW
    for _ in range(rng.randint(2, 14)):
        pick = rng.random()
        if pick < 0.3:
            steps.append(["tick"])
            steps.append(["run"])
        elif pick < 0.42:
            steps.append(["look"])
        elif pick < 0.55:
            now += rng.choice([10, 59, 61, 179, 181, 400, 4000])
            steps.append(["clock", now])
        elif pick < 0.62:
            steps.append(["on", rng.random() < 0.6])
        elif pick < 0.7:
            steps.append(["armed", rng.choice([[CAPABILITY], [CAPABILITY, "window_anchor"], [], ["window_anchor"]])])
        elif pick < 0.76:
            steps.append(["apply", rng.choice([None, NOW + 100.0, NOW + 1000.5, NOW - 5.0, NOW + 121.0])])
        elif pick < 0.82:
            steps.append(["earliest"])
        elif pick < 0.88:
            steps.append(["lead"])
        elif pick < 0.92:
            steps.append(["call", "move", [CAPABILITY, rng.choice(["armed", "off", "shadow"])], {"actor": "dashboard"}])
        else:
            steps.append(["due"])
    return {"op": "wk", "capability": CAPABILITY, "now": NOW, "setup": setup(rng), "view": view(rng),
            "timer": timer(rng), "steps": steps, "on": rng.random() < 0.9, "bind": rng.random() < 0.95,
            "armed": rng.choice([[CAPABILITY], [CAPABILITY], [CAPABILITY, "window_anchor"], []]),
            "start": [rng.choice([None, None, {"raise": "RuntimeError"}])]}


class WakeDiff(unittest.TestCase):
    def test_walks(self):
        rng = random.Random(7222)
        cases = [walk(rng) for _ in range(500)]
        waiting = [{"interruption_id": "w", "category": "usage_limit", "state": "waiting_reset", "hold": None,
                    "reset_at": NOW + 3600}]
        cases += [
            {"op": "wk", "capability": CAPABILITY, "view": {"records_in": [waiting]},
             "setup": [["move", [CAPABILITY, "armed"], {"actor": "dashboard"}]], "armed": [CAPABILITY],
             "steps": [["tick"], ["run"], ["due"], ["look"], ["clock", NOW + 200], ["look"], ["due"]]},
            {"op": "wk", "capability": CAPABILITY, "view": {"records_in": [waiting]}, "timer": {"allowed": [False]},
             "steps": [["tick"], ["run"], ["clock", NOW + 30], ["tick"], ["run"], ["clock", NOW + 90], ["tick"],
                       ["run"]]},
            {"op": "wk", "capability": CAPABILITY, "view": {"records_in": [waiting]}, "timer": {"set": [False]},
             "steps": [["tick"], ["run"], ["due"]]},
        ]
        found = advtime.Scene(self, "wake").run(cases)
        sets = sum(1 for each in found for entry in (each["result"].get("ok") or {}).get("log", ())
                   if entry and entry[0] == "set")
        self.assertGreater(sets, 50)


if __name__ == "__main__":
    unittest.main()

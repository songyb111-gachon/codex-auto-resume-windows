"""S7.2e2: `engine/supervise.py` (crash_restart, P13) as the v0.6.26 final has it, held equal to car-adv's
`engine::supervise`.

A case is one CrashRestart over a scratch home's real advanced state (its `restarts` rows and journal), bound or not,
with a scripted stop flag (hold, signalled, wait: answers or raises) and a scripted notice, driven through a walk of
P13's facts (start, ended with every exit code and `clean`, anything else) and clock moves. Compared: every answer, every
call of the stand-ins in order, and every row the state holds after. `view` over every shape of `unsupervised.txt`.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_supervise`.
"""
from __future__ import annotations

import random
import unittest

from rustdiff import advtime

CAPABILITY = "crash_restart"
CODES = [0, 1, 2, 3, 4, 5, 6, -1, 255, 3221225477, True, False, None, "1", 1.0, [], {}]
CLEANS = [None, True, False, 1, 0, "true"]


def facts(rng: random.Random):
    pick = rng.random()
    if pick < 0.25:
        return {"phase": "start"}
    if pick < 0.85:
        found = {"phase": "ended"}
        if rng.random() < 0.9:
            found["exit_code"] = rng.choice(CODES)
        if rng.random() < 0.7:
            found["clean"] = rng.choice(CLEANS)
        return found
    return rng.choice([None, [], "start", {"phase": "other"}, {}, {"phase": None}, {"phase": 1}])


def flag_script(rng: random.Random) -> dict:
    script = {}
    for kind in ("hold", "signalled", "wait"):
        if rng.random() < 0.5:
            choices = [True, False, False, False, {"raise": "OSError"}, 0, 1]
            script[kind] = [rng.choice(choices) for _ in range(rng.randint(1, 4))]
    return script


def walk(rng: random.Random, index: int) -> dict:
    now = advtime.NOW + rng.randint(0, 3) * 1000
    setup = []
    for _ in range(rng.choice([0, 0, 1, 2, 3, 4])):
        setup.append(["restart_noted", [rng.choice([1, 2, 7]), rng.choice([True, True, False])],
                      {"at": now - rng.choice([10, 600, 1800, 3599, 3600, 3601, 7200])}])
    steps = []
    for _ in range(rng.randint(1, 12)):
        pick = rng.random()
        if pick < 0.12:
            steps.append(["clock", now + rng.choice([5, 600, 3600, 4000])])
        elif pick < 0.18:
            steps.append(["on", rng.random() < 0.7])
        else:
            steps.append(["ask", facts(rng)])
    case = {"op": "sv", "capability": CAPABILITY, "now": now, "setup": setup, "steps": steps,
            "flag": flag_script(rng), "on": rng.random() < 0.9, "bind": rng.random() < 0.93}
    if rng.random() < 0.4:
        case["notify"] = [rng.choice([True, False, {"raise": "RuntimeError"}])]
    return case


class SuperviseDiff(unittest.TestCase):
    def test_walks(self):
        rng = random.Random(7202)
        cases = [walk(rng, index) for index in range(400)]
        # The named paths: three restarts in the hour, the fourth refused with gave_up; a stop seen; a wait stopped.
        start, crash = ["ask", {"phase": "start"}], ["ask", {"phase": "ended", "exit_code": 1}]
        cases += [
            {"op": "sv", "capability": CAPABILITY, "steps": [start, crash, crash, crash, crash, crash]},
            {"op": "sv", "capability": CAPABILITY, "steps": [crash, start, crash], "flag": {"signalled": [True]}},
            {"op": "sv", "capability": CAPABILITY, "steps": [start, crash], "flag": {"wait": [True]}},
            {"op": "sv", "capability": CAPABILITY, "steps": [start, ["on", False], crash, ["on", True], crash]},
            {"op": "sv", "capability": CAPABILITY, "steps": [start, crash, crash, crash, crash],
             "notify": [{"raise": "RuntimeError"}]},
            {"op": "sv", "capability": CAPABILITY, "steps": [start, crash], "flag": {"hold": [{"raise": "OSError"}]}},
        ]
        found = advtime.Scene(self, "supervise").run(cases)
        restarts = sum(1 for each in found for answer in (each["result"].get("ok") or {}).get("answers", ())
                       if answer == {"word": "restart"})
        self.assertGreater(restarts, 20)

    def test_view(self):
        bodies = ["123 started", "123 started\n", " 123\tstarted ", "123", "123 a b", "x started", "+12 w", "1_2 w",
                  "١٢ w", "", "-5 w", "99999 gone", "123 été", {"hex": "ff20"}, {"hex": "efbbbf3132332077"}]
        cases = []
        for body in bodies:
            for state in ("armed", "shadow", None):
                files = {"logs/unsupervised.txt": body}
                cases.append({"op": "sv.view", "files": files, "state": state, "running": [123, 12, -5],
                              "dump": False})
        cases.append({"op": "sv.view", "state": "armed", "running": [123], "dump": False})
        cases.append({"op": "sv.view", "state": "armed", "files": {"logs/unsupervised.txt": {"dir": True}},
                      "dump": False})
        advtime.Scene(self, "supervise view").run(cases)


if __name__ == "__main__":
    unittest.main()

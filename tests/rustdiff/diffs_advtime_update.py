"""S7.2e2: `engine/updatecheck.py` (idle_update_check, P8) as the v0.6.26 final has it, held equal to car-adv's
`engine::updatecheck`.

The check itself is never run (it asks GitHub through PowerShell, P7-DESIGN 4): every case hands a scripted `run` that
answers what `bootstrap.ps1 -CheckOnly` would (an exit code and what it printed, or nothing), a scripted administrator
switch, installed version and thread start (which runs the check at once, or never), and a log that keeps each line.
A walk ticks, runs the errand, moves the clock past LOOK_EVERY and WEEK, makes the bootstrap appear, turns the capability
off and on (an offer found before it last stood on is put away), and reads what is offered. Compared: every answer,
every call in order, every log line, every row after. The pure parts over generated answers: `offer`, `said`,
`english`, `encode` and `decode`.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_update`.
"""
from __future__ import annotations

import random
import unittest

from rustdiff import advtime

CAPABILITY = "idle_update_check"
NOW = advtime.NOW
VERSIONS = ["0.6.27", "0.6.26", "1.0.0", "0.6.27-alpha", "0.6.27-beta.3", "0.6.27-beta.1", "0.6.27-beta.10",
            "0.6.27-gamma", "01.2.3", "1.2", "1.2.3.4", "999999.0.0", "1000.0.0", "0.6.27-alpha.999", "v0.6.27", "",
            "0.6.27-beta.0", "1234567.0.0", "0.6.27 "]


def printed(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(0, 4)):
        pick = rng.random()
        if pick < 0.5:
            said = rng.choice(["current", "available", "newer-local", "unavailable", "other", ""])
            lines.append("update: %s %s %s" % (said, rng.choice(VERSIONS), rng.choice(VERSIONS)))
        elif pick < 0.75:
            lines.append("prerelease: %s" % rng.choice(["v" + each for each in VERSIONS] + VERSIONS))
        else:
            lines.append(rng.choice(["noise", "  update: current 0.6.27 0.6.27  ", "update:", "\tprerelease: v1.0.0-beta"]))
    return rng.choice(["\n", "\r\n", "\r"]).join(lines)


def answered(rng: random.Random):
    if rng.random() < 0.15:
        return None
    return [rng.choice([0, 10, 11, 12, 1, 10.0, True]), printed(rng)]


def walk(rng: random.Random) -> dict:
    steps, now = [], NOW
    if rng.random() < 0.8:
        steps.append(["script"])
    for _ in range(rng.randint(2, 10)):
        pick = rng.random()
        if pick < 0.45:
            steps += [["tick"], ["run"]]
        elif pick < 0.6:
            now += rng.choice([30, 61, 7 * 86400, 7 * 86400 + 1, 100000])
            steps.append(["clock", now])
        elif pick < 0.68:
            steps.append(["on", rng.random() < 0.7])
        elif pick < 0.76:
            steps.append(["call", "move", [CAPABILITY, rng.choice(["armed", "off", "shadow"])], {"actor": "dashboard"}])
        elif pick < 0.88:
            steps.append(["offered"])
        else:
            steps.append(["tick"])
    script = {"answer": [answered(rng) for _ in range(rng.randint(1, 3))]}
    if rng.random() < 0.3:
        script["managed"] = [rng.choice([False, True, None, 0, {"raise": "OSError"}])]
    if rng.random() < 0.6:
        script["installed"] = [rng.choice(VERSIONS + [None, {"raise": "OSError"}])]
    if rng.random() < 0.1:
        script["start"] = [{"raise": "RuntimeError"}]
    if rng.random() < 0.1:
        script["answer"] = [{"raise": "OSError"}]
    view = {}
    if rng.random() < 0.3:
        view["records_in"] = [rng.choice([[], [{"interruption_id": "x"}], {"raise": "RuntimeError"}])]
    setup = [["move", [CAPABILITY, "armed"], {"actor": "dashboard"}]] if rng.random() < 0.8 else []
    if rng.random() < 0.3:
        setup.append(["stamp", [CAPABILITY, "offered_version", rng.choice([60270009999, 60262001003, 5, 10000])], {}])
        setup.append(["stamp", [CAPABILITY, "offered_at", int(NOW) - rng.choice([10, 100000])], {}])
    if rng.random() < 0.2:
        setup.append(["stamp", [CAPABILITY, "last_check", int(NOW) - rng.choice([10, 7 * 86400])], {}])
    return {"op": "uc", "capability": CAPABILITY, "now": NOW, "setup": setup, "steps": steps, "script": script,
            "view": view, "on": rng.random() < 0.9, "bind": rng.random() < 0.95, "start_runs": rng.random() < 0.9}


class UpdateCheckDiff(unittest.TestCase):
    def test_walks(self):
        rng = random.Random(7252)
        found = advtime.Scene(self, "update").run([walk(rng) for _ in range(400)])
        lines = sum(1 for each in found for entry in (each["result"].get("ok") or {}).get("log", ())
                    if entry and entry[0] == "log")
        self.assertGreater(lines, 50)

    def test_pure(self):
        rng = random.Random(7253)
        cases = []

        def add(name, *arguments):
            cases.append({"op": "uc.pure", "name": name, "arguments": list(arguments), "dump": False})
        for _ in range(600):
            found = answered(rng)
            if found is not None:
                add("offer", *found)
            add("said", found, rng.choice([None, "missing", "running", "not_started", "other"]))
        for why in ("unavailable", "missing", "running", "failed", "not_started", "x"):
            add("english", why)
        for version in VERSIONS + [None, 5]:
            add("encode", version)
        for value in (60270009999, 60270001001, 60270002003, 60270002999, 60270003000, 1, 0, -5, True, "x", None,
                      9999999999999999, 10000000000000, 60270001000, 60270002001, 999999999999):
            add("decode", value)
        advtime.Scene(self, "update pure").run(cases)


if __name__ == "__main__":
    unittest.main()

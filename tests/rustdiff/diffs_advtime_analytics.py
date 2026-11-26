"""S7.2e2: `engine/analytics.py` (usage_analytics, P8) as the v0.6.26 final has it, held equal to car-adv's
`engine::analytics`.

A case is one UsageAnalytics over a scratch home's real advanced state and a scratch Codex home of generated rollouts
(`diffs_advcodex_tokens.rollout_bytes`: token counts, repeats, damaged lines, other conversations), each file's time
pinned so both sides find them in the same order; its seams scripted - the homes, the monotonic clock a pass is timed
by (so PASS_SECONDS cuts a pass where the script says), and core's project key per conversation (a key, a short one,
none, a raise). A walk ticks and runs the errand, moves the clock past INGEST_EVERY, turns it off, fails MTOK. Compared:
every answer, every call in order, every row (token_files, token_days, the stamp, the journal) after. `pace` over
generated samples and windows, `route` over the verdicts.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_analytics`.
"""
from __future__ import annotations

import random
import unittest

from rustdiff import advtime
from rustdiff.diffs_advcodex_tokens import OTHER, THREAD, rollout_bytes

CAPABILITY = "usage_analytics"
NOW = advtime.NOW


def files(rng: random.Random) -> dict:
    found = {}
    for index in range(rng.randint(0, 5)):
        name = "codex/sessions/2026/11/%02d/rollout-2026-11-%02dT00-00-%02d.jsonl" % (20 + index, 20 + index, index)
        found[name] = {"hex": rollout_bytes(rng).hex(),
                       "mtime_ns": int((NOW - rng.choice([10, 500, 86400, 86400 * 100]) - index) * 10 ** 9)}
    if rng.random() < 0.3:
        found["other/sessions/2026/11/01/rollout-x.jsonl"] = {"hex": rollout_bytes(rng).hex(),
                                                              "mtime_ns": int((NOW - 50) * 10 ** 9)}
    return found


def walk(rng: random.Random) -> dict:
    steps, now = [], NOW
    for _ in range(rng.randint(2, 8)):
        pick = rng.random()
        if pick < 0.55:
            steps += [["tick"], ["run"]]
        elif pick < 0.75:
            now += rng.choice([30, 599, 600, 601, 4000])
            steps.append(["clock", now])
        elif pick < 0.85:
            steps.append(["on", rng.random() < 0.7])
        else:
            steps.append(["tick"])
    keys = {THREAD: rng.choice(["0123456789abcdef0123", "0123456789abcdef", "short", None, 5, {"raise": "x"}]),
            OTHER: rng.choice(["fedcba9876543210ff", None])}
    case = {"op": "ua", "capability": CAPABILITY, "now": NOW, "files": files(rng), "steps": steps,
            "homes": rng.choice([["codex"], ["codex", "other"], ["codex", "codex"], [], ["missing"]]),
            "clock": [rng.choice([0.0, 0.0, 0.5, 1.9, 2.0, 5.0]) for _ in range(rng.randint(1, 6))],
            "keys": keys, "on": rng.random() < 0.9, "bind": rng.random() < 0.95,
            "source_raise": rng.random() < 0.08}
    if rng.random() < 0.15:
        case["verdicts"] = {"mtok": rng.choice(["fail", "pass", None])}
    if rng.random() < 0.15:
        case["setup"] = [["stamp", [CAPABILITY, "last_ingest", int(NOW) - rng.choice([10, 700])], {}]]
    return case


def sample(rng: random.Random, row: dict) -> dict:
    return {"bucket": row["bucket"] if rng.random() < 0.9 else "other",
            "minutes": row["minutes"] if rng.random() < 0.9 else 60,
            "at": NOW - rng.choice([0, 100, 600, 900, 1800, 3000, 3599, 3601, 7200]) - rng.random(),
            "used_percent": rng.choice([1, 5, 10.5, 20, 40, 60, 99]),
            "reset_at": rng.choice([None, row["reset_at"], row["reset_at"], 5])}


class AnalyticsDiff(unittest.TestCase):
    def test_walks(self):
        rng = random.Random(7242)
        found = advtime.Scene(self, "analytics").run([walk(rng) for _ in range(250)])
        days = sum(len(each["dump"].get("token_days", ())) for each in found if each["dump"])
        self.assertGreater(days, 30)

    def test_pace(self):
        rng = random.Random(7243)
        cases = []
        for _ in range(500):
            row = {"bucket": "codex", "minutes": rng.choice([300, 10080, None]),
                   "used_percent": rng.choice([10, 50, 99.5, 100, None, "x"]),
                   "reset_at": rng.choice([int(NOW) + 3600, int(NOW) + 60, int(NOW) - 100, None, NOW + 3600.0])}
            samples = sorted((sample(rng, row) for _ in range(rng.randint(0, 8))), key=lambda each: each["at"])
            if rng.random() < 0.5:
                rising = [dict(each, used_percent=10 + index * 7) for index, each in enumerate(samples)]
                samples = rising
            cases.append({"op": "ua.pace", "samples": samples, "row": row, "now": NOW, "dump": False})
        for verdict in ("fail", "pass", None, "FAIL", 1):
            cases.append({"op": "ua.route", "verdict": verdict, "dump": False})
        advtime.Scene(self, "pace").run(cases)


if __name__ == "__main__":
    unittest.main()

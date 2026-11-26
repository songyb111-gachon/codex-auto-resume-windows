"""S7.2e2: `engine/anchor.py` (window_anchor, P8) as the v0.6.26 final has it, held equal to car-adv's `engine::anchor`.

The pure functions over generated inputs, each under three local clocks (the process's own zone, `JST-9` and `EST5EDT`,
whose summer-time changes the calendar arithmetic of `occurrence` must cross): the time options' code, the times
picked, `midnight`, `occurrence`, `slot_due`, `reset_due`, `next_due`, the windows of a reading, `running_reset`,
`judge` over pairs of readings (idle, running, weekly full, unreadable, readings too close, keys missing, values that
cannot be ordered), `signed_in`, what `codex exec --json` printed (`tokens_of`, `thread_started`, `refused`, bytes that
are not UTF-8, every line break `splitlines` knows), the servers' `-c` value and the log line's words.

Alone: `cd tests && PYTHONPATH="../src;." python -X utf8 -m unittest rustdiff.diffs_advtime_anchor`.
"""
from __future__ import annotations

import json
import random
import unittest

from rustdiff import advtime

NOW = advtime.NOW
# 2026-03-08 and 2026-11-01: the US changes; 2026-03-29 and 2026-10-25: Europe's.
CHANGES = [1772953200, 1772960400, 1774746000, 1792998000, 1793516400, 1793523600]


def options(rng: random.Random) -> dict:
    found = {}
    for key in ("anchor_at_1", "anchor_at_2", "anchor_at_3"):
        if rng.random() < 0.6:
            found[key] = rng.choice([1, 2, 3, 62, 482, 1441, 1442, 0, -1, True, 482.0, "482", None,
                                     rng.randint(2, 1441)])
    if rng.random() < 0.6:
        found["anchor_after_reset"] = rng.choice([1, 2, 1.0, True, 0, None, "1"])
    return found


def window(rng: random.Random, bucket=None, minutes=None) -> dict:
    found = {"bucket": bucket or rng.choice(["codex", "legacy", "other"]),
             "window_minutes": minutes or rng.choice([300, 10080, 300.0, 60])}
    if rng.random() < 0.95:
        found["used_percent"] = rng.choice([0, 0, 0.0, 5, 100, 100.0, 99.9, True, None, "5"])
    if rng.random() < 0.95:
        found["reset_at"] = rng.choice([int(NOW) + 18000, int(NOW) + 17990, int(NOW) + 600, None, NOW + 18000.0, "x"])
    return found


def reading(rng: random.Random, at=None) -> dict:
    if rng.random() < 0.05:
        return rng.choice([None, {}, [], 0])
    found = {"at": at if at is not None else rng.choice([NOW, NOW + 25, NOW + 10, "x", None, True])}
    if rng.random() < 0.95:
        found["windows"] = rng.choice([None, [], [window(rng) for _ in range(rng.randint(1, 4))],
                                       [window(rng, "codex", 300), window(rng, "codex", 10080)], "x", 5])
    return found


def idle(at: float, used=0, offset=18000, weekly=40) -> dict:
    return {"at": at, "windows": [{"bucket": "codex", "window_minutes": 300, "used_percent": used,
                                   "reset_at": int(at) + offset},
                                  {"bucket": "codex", "window_minutes": 10080, "used_percent": weekly,
                                   "reset_at": int(at) + 86400}]}


def printed(rng: random.Random):
    lines = []
    for _ in range(rng.randint(0, 6)):
        pick = rng.random()
        if pick < 0.25:
            usage = {"input_tokens": rng.choice([24000, 0, -1, 10 ** 9, 10 ** 9 - 1, 5.5, None, True]),
                     "cached_input_tokens": rng.choice([12000, None]), "output_tokens": rng.choice([5, "5"])}
            if rng.random() < 0.2:
                del usage["output_tokens"]
            lines.append(json.dumps({"type": "turn.completed", "usage": usage if rng.random() < 0.9 else [1]}))
        elif pick < 0.45:
            lines.append(json.dumps({"type": "thread.started", "thread_id": "t"}))
        elif pick < 0.6:
            lines.append("  " + json.dumps({"type": "item.completed"}) + "  ")
        elif pick < 0.7:
            lines.append("{not json")
        elif pick < 0.8:
            lines.append("[1, 2]")
        else:
            lines.append(rng.choice(["Error loading config.toml: invalid transport", "Error: Unknown feature flag x",
                                     "plain text", "", "été"]))
    separator = rng.choice(["\n", "\r\n", "\r", "\x0b", "\x1c", " ", "\x85"])
    text = separator.join(lines)
    if rng.random() < 0.15:
        return {"hex": (text.encode("utf-8") + b"\xff\xfe" + b"\n{\"type\": \"thread.started\"}").hex()}
    return text


class AnchorPureDiff(unittest.TestCase):
    def cases(self, rng: random.Random) -> list:
        found = []

        def add(name, *arguments):
            found.append({"op": "an.pure", "name": name, "arguments": list(arguments), "dump": False})
        for hour in (-1, 0, 7, 23, 24, True, 7.0, None):
            for minute in (-1, 0, 30, 59, 60, "1"):
                add("encode_time", hour, minute)
        for value in (0, 1, 2, 3, 1441, 1442, True, 2.0, None, "2", 1000):
            add("decode_time", value)
            add("clock_text", value)
        for _ in range(60):
            add("picked", options(rng))
            add("after_reset_on", options(rng))
        add("picked", None)
        add("after_reset_on", None)
        moments = [NOW, NOW + 0.7, NOW - 43200.5] + [change + delta for change in CHANGES for delta in (-3600, 0, 1800, 7200)]
        for now in moments:
            add("midnight", now)
            add("hhmm", now)
            for days in (-1, 0, 1):
                for minute in (0, 90, 150, 480, 1439):
                    add("occurrence", now, days, minute)
        for _ in range(250):
            now = rng.choice(moments) + rng.choice([0, 600, 1799, 1800, 3600])
            done = rng.choice([None, None, int(now) - 900, int(now) - 86400, int(now) + 10, True, "x"])
            add("slot_due", options(rng), now, done)
            seen = rng.choice([None, int(now) - 30, int(now) - 61, int(now) - 60, int(now) + 500, "x", True, 1.5])
            add("reset_due", options(rng), now, seen, rng.choice([None, int(now) - 100, int(now), int(now) + 500]))
            add("next_due", options(rng), now, rng.choice([None, int(now) + 100, int(now) + 90000, True]),
                seen, rng.choice([None, int(now) - 100, int(now) + 600]))
        for _ in range(200):
            add("windows_of", reading(rng).get("windows") if rng.random() < 0.9 else rng.choice([None, 0, 7, "s", {}]))
            add("running_reset", reading(rng), NOW)
            add("judge", reading(rng), reading(rng))
        for at in (NOW, NOW + 0.5):
            add("judge", idle(at), idle(at + 25))
            add("judge", idle(at), idle(at + 25, offset=17900))
            add("judge", idle(at), idle(at + 10))
            add("judge", idle(at), idle(at + 25, used=3))
            add("judge", idle(at, weekly=100), idle(at + 25))
            add("judge", idle(at), idle(at + 25, offset=17970))
            add("judge", idle(at), idle(at + 25, offset=17976))
        for reply in ({"account": {"email": "x"}}, {"account": None}, {"account": "x"}, {}, None, [], {"other": 1}):
            add("signed_in", reply)
        for _ in range(150):
            text = printed(rng)
            add("tokens_of", text)
            add("thread_started", text)
            add("refused", text)
        for names in ([], ["a"], ["a.b", "c d", 'q"t', "back\\slash", "\x7f", "é", "\x01"], ["x"] * 3):
            add("servers_off", names)
            for name in names:
                add("toml_key", name)
        for tokens in ({"input": 1, "cached": 2, "output": 3}, {}, None, {"input": "1", "cached": None, "output": 1.0}):
            add("tokens_said", tokens)
        return found

    def test_pure(self):
        for tz in (None, "JST-9", "EST5EDT"):
            with self.subTest(tz=tz):
                advtime.Scene(self, "anchor pure %s" % tz).run(self.cases(random.Random(7232)), tz=tz)


if __name__ == "__main__":
    unittest.main()

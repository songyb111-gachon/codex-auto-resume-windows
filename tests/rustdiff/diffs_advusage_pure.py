"""Seat S7.2d: the pure parts - the wrap-up's words (wrapwords), what a continuation is keyed and handed as (continued),
the window counting (resetwatch), the usage stages' readings (usage), reset_message's two guards and the stop's
counts_here - each over generated inputs and their edges, held equal to the v0.6.26 final's."""
from __future__ import annotations

import random

from rustdiff.advusage import CLOCK, OTHER, THREAD, AdvUsageDiff

NOW = int(CLOCK)


def fn(name, *args, **kwargs):
    return {"fn": name, "args": list(args), "kwargs": kwargs}


class WrapWordsDiff(AdvUsageDiff):
    def test_render(self):
        rng = random.Random(7)
        styles = [1, 2, 3, 4, 5, 0, 6, None, "2", 2.0, True]
        minutes = [300, 10080, 60, 300.0, None, "300"]
        used = [90, 90.7, 0, 100, -5, None, "91", " 92 ", "9_3", "x", 1e20, True, 99.999]
        stops = [95, 95.0, None, True, 0, 120]
        locales = ["en", "ko", "ja", None, "xx", "de"]
        resets = [None, NOW + 3600, NOW + 3600.5, 0, NOW + 7 * 86400, -1, True]
        customs = [None, "Stop at {stop_at} of {window}, now {percent}.", "{reset} reset {reset}", "{bad}", "",
                   "   ", "x" * 2001, "x" * 2000, "a\x01b", "tab\there\nline", "[codex-auto-resume:x", 5, "{", "}{",
                   "{percent}{percent}", "{{percent}}", "é{window}中", "a\x7fb"]
        ops = []
        for _ in range(900):
            ops.append(fn("wrapwords.render", style=rng.choice(styles), minutes=rng.choice(minutes),
                          used=rng.choice(used), stop_at=rng.choice(stops), locale=rng.choice(locales),
                          reset_at=rng.choice(resets), include_reset=rng.choice([True, False]),
                          custom=rng.choice(customs)))
        for text in customs + ["{percent} {window} {stop_at} {reset}", "{ percent}", "x{y}z", "　", "\x0b"]:
            ops.append(fn("wrapwords.check_custom", text))
        for minute in minutes:
            for locale in locales:
                ops.append(fn("wrapwords.window_words", minute, locale))
                for reset in resets:
                    ops.append(fn("wrapwords.reset_words", reset, minute, locale))
        self.same("wrapwords", ops)


class ContinuedDiff(AdvUsageDiff):
    def test_continued(self):
        ops = []
        for parts in (["usage_wrap_up", THREAD, "codex", 300, NOW], ["after_reset", THREAD, "wrap", 10080, NOW],
                      [None, 1.5, True, False, 0, -1, "é"], [], ["a,b", "\"q\""], [10 ** 30, 1e300]):
            ops.append(fn("continued.answer_key", *parts))
        rows = []
        for kind in ("wrap_up", "after_reset", "keep_going", None):
            for record_state in ("waiting", "in_flight", "finished", None):
                for words in ("Go on.", "", None):
                    rows.append({"record_id": "ab" * 32, "thread_id": THREAD, "kind": kind, "ordinal": 4,
                                 "record_state": record_state, "words": words, "finished_at": None,
                                 "launching_at": None if words else 5.0, "claimed_at": 3.0, "queue_id": "q1",
                                 "withdraw": 1 if words == "" else 0})
        rows += [{"record_id": None}, {"record_id": "k", "finished_at": 1.0}, {}]
        ops += [fn("continued.handed", row) for row in rows]
        for words in ("Go on.", "", None, 5, "x" * 20000, "[codex-auto-resume:abc] go", "\x00"):
            ops.append(fn("continued.words_pass", words))
        self.same("continued", ops)


def row_of(rng):
    opened = rng.choice([None, NOW - 100, NOW + 3000, NOW + 50, NOW - 61])
    return {"bucket": rng.choice(["codex", "other"]), "minutes": rng.choice([300, 10080]),
            "open_reset_at": opened, "open_full": rng.choice([True, False, 0, 1]),
            "last_closed_at": rng.choice([None, NOW - 4000, NOW + 2000, 0]), "resets": rng.randint(0, 5),
            "hits": rng.randint(0, 5), "seen_at": rng.choice([None, NOW - 100, NOW - 20000, NOW - 700000]),
            "misses": rng.randint(0, 3)}


class ResetWatchDiff(AdvUsageDiff):
    def test_counting(self):
        rng = random.Random(11)
        ops = []
        for _ in range(700):
            row = row_of(rng)
            window = rng.choice([None, {"used_percent": rng.choice([0, 50, 100, 120, 99.9]),
                                        "reset_at": rng.choice([None, NOW + 3000, NOW + 3601, NOW - 5, NOW + 18000])}])
            now = rng.choice([NOW, NOW + 0.5, NOW + 100, NOW + 18001])
            ops.append(fn("resetwatch.advance", row, window, now, rng.choice([True, False])))
            ops.append(fn("resetwatch.by_time", row, now))
            ops.append(fn("resetwatch.closed", row, now))
            rule = {"capability": rng.choice(["reset_credit", "reset_message"]),
                    "state": rng.choice(["counting", "ready", "held"]), "base": rng.choice([None, 0, 1, 3]),
                    "ordinal": rng.choice([0, 1, 2])}
            ops.append(fn("resetwatch.count", rule, row))
            ops.append(fn("resetwatch.due", rule, rng.choice([row, None])))
        windows = [{"bucket": "codex", "window_minutes": 300, "used_percent": 40, "reset_at": NOW + 10},
                   {"bucket": "codex", "window_minutes": 300, "used_percent": 70, "reset_at": NOW + 20},
                   {"bucket": "codex", "window_minutes": 300, "used_percent": 70, "reset_at": NOW + 30},
                   {"bucket": "codex", "window_minutes": 10080, "used_percent": 5, "reset_at": None}]
        for family in (["codex", 300], ["codex", 10080], ["other", 300], ["codex", 300.0]):
            ops.append(fn("resetwatch.family_window", windows, family))
            ops.append(fn("resetwatch.family_window", [], family))
            ops.append(fn("resetwatch.family_window", None, family))
        for pair in (["codex", 300], [None, None], [5, "x"]):
            ops.append(fn("resetwatch.blank", *pair))
        self.same("resetwatch", ops)


def meter_row(rng, minutes=None):
    return {"bucket": rng.choice(["codex", "codex_other"]), "minutes": minutes or rng.choice([300, 10080, 60]),
            "used_percent": rng.choice([10, 85, 90, 95, 97, 100, 96.5]),
            "reset_at": rng.choice([NOW + 3000, NOW - 30, NOW - 61, None, NOW + 0.5]),
            "read_at": rng.choice([NOW - 100, NOW - 8000, None, 0]), "warned_reset_at": None,
            "paused_reset_at": rng.choice([None, NOW + 3000])}


class UsageStagesDiff(AdvUsageDiff):
    def test_stages(self):
        rng = random.Random(13)
        ops = []
        keys = ["warn_five_hour", "warn_weekly", "wrap_five_hour", "wrap_weekly", "pause_five_hour", "pause_weekly",
                "stop_words_five_hour", "stop_words_weekly", "window_five_hour", "poll_minutes", "x"]
        for key in keys:
            ops.append(fn("usage.touched", key))
        for _ in range(300):
            options = {key: rng.choice([50, 85, 90, 95, 97, 99, 90.0, None, True, 1, 2])
                       for key in rng.sample(keys, rng.randint(0, len(keys)))}
            for capability in ("usage_meter", "usage_wrap_up", "usage_pause", "other"):
                ops.append(fn("usage.percent", options, capability, rng.choice([300, 10080, 300.0, 60])))
            ops.append(fn("usage.acting", options))
            row = meter_row(rng)
            ops.append(fn("usage.reached", row, rng.choice([None, 85, 90, 97, 100]),
                          rng.choice([NOW, NOW + 0.5, NOW - 100])))
            values = {capability: {key: rng.choice([80, 85, 90, 94, 95, 96, 97, 99])
                                   for key in rng.sample(keys[:8], rng.randint(0, 5))}
                      for capability in rng.sample(["usage_meter", "usage_wrap_up", "usage_pause"], rng.randint(0, 3))}
            ops.append(fn("usage.order_problem", values, rng.choice([[300, 10080], [300], [10080], []])))
            resets = [[row["bucket"], row["minutes"], rng.choice([NOW - 200, NOW - 50, NOW])]] if rng.random() < .7 else []
            ops.append(fn("usage.stale", row, resets))
            rows = [meter_row(rng) for _ in range(rng.randint(0, 3))]
            ops.append(fn("usage.reset_since", rows, rng.choice([300, 10080]), rng.choice([NOW - 20000, NOW - 100, NOW - 4000]),
                          rng.choice([NOW, NOW + 3100])))
        ops.append(fn("usage.order_problem", {"usage_meter": {"warn_five_hour": "x"}}, [300]))
        self.same("usage stages", ops)


class GuardsDiff(AdvUsageDiff):
    def test_message_and_stop_guards(self):
        rng = random.Random(17)
        ops = []
        for _ in range(500):
            rule = {"thread_id": rng.choice([THREAD, OTHER]), "due_at": rng.choice([None, NOW - 10, NOW + 10, True, NOW]),
                    "state": rng.choice(["counting", "ready"]), "base": rng.choice([None, 0, 2]),
                    "ordinal": rng.choice([1, 2, 3]), "bucket": "codex", "minutes": 300, "capability": "reset_message"}
            stops = [{"capability": rng.choice(["usage_pause", "keep_going"]), "kind": rng.choice(["after_reset", "wrap_up"]),
                      "thread_id": rng.choice([THREAD, OTHER]), "finished_at": rng.choice([None, NOW - 5]),
                      "record_state": rng.choice(["waiting", "in_flight"]),
                      "created_at": rng.choice([NOW - 100, NOW + 100, None, "x"])} for _ in range(rng.randint(0, 3))]
            ops.append(fn("resetmessage.carried_by_stop", rule, stops))
            window = rng.choice([None, {"open_reset_at": rng.choice([None, NOW + 300, NOW + 1200]), "resets": rng.randint(0, 3),
                                        "hits": 0, "last_closed_at": rng.choice([None, NOW - 50, NOW - 500]),
                                        "bucket": "codex", "minutes": 300}])
            record = {"category": rng.choice(["usage_limit", "server_5xx"]),
                      "reset_at": rng.choice([NOW + 300, NOW + 1000, None, NOW + 299.5, True])}
            now = rng.choice([NOW, NOW + 1500, NOW + 3000])
            ops.append(fn("resetmessage.same_reset", rule, window, record, now))
            row = {"created_at": rng.choice([NOW - 100, NOW - 600, NOW - 20000]), "chain": rng.choice([300, 10080])}
            meter = [{"bucket": "codex", "minutes": rng.choice([300, 10080]), "reset_at": rng.choice([NOW + 300, None, NOW - 18000]),
                      "used_percent": 90, "read_at": NOW - 10} for _ in range(rng.randint(0, 2))]
            ops.append(fn("usagestop.counts_here", rule, window, row, meter, now))
        self.same("message and stop guards", ops)

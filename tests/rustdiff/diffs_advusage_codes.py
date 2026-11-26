"""Seat S7.2d: the codes - capacity_retry, early_reset, the usage meter (with the v0.6.26 final's SKIP_WAIT, the backend
kept for the told engine and inuse.saw), the wrap-up, the pause and the forced stop, reset_credit and reset_message -
each driven hook by hook on a pinned clock over a scripted world, its answers, the world's log (every session call,
IPC request, guard answer and Codex read, in order), what the code keeps and the advanced state left held equal to the
v0.6.26 final's. Scenarios from the tag's own tests (test_advanced_meter_skip_wait, ..._engine_elsewhere,
test_advanced_usage*, ..._reset_credit, ..._reset_message, ..._matrix_stop_reset) and seeded random walks."""
from __future__ import annotations

import random
import time

from rustdiff.advusage import CLOCK, OTHER, THREAD, AdvUsageDiff

NOW = int(CLOCK)
EXE = r"C:\scratch-engine\codex.exe"
PACKAGE = r"C:\scratch-package\app\resources\codex.exe"
CODEX_HOME = r"C:\scratch-codex-home"
RESET5 = NOW + 3 * 3600
RESETW = NOW + 4 * 86400


def clock(at):
    """The runtime's clock is time.time(), a float."""
    return {"clock": float(NOW + at)}


def world(**changes):
    return {"world": changes}


def hook(code, name, *args):
    return {"hook": name, "code": code, "args": list(args)}


def run(code):
    return {"run": code}


def kept(code):
    return {"kept": code}


LOG = {"log": True}


def reply(five=None, weekly=None, credits=None, listed=None):
    limits = {"limitId": "codex", "limitName": "ExampleUser's plan", "planType": "pro"}
    if five is not None:
        limits["primary"] = {"usedPercent": five[0], "windowDurationMins": 300, "resetsAt": five[1]}
    if weekly is not None:
        limits["secondary"] = {"usedPercent": weekly[0], "windowDurationMins": 10080, "resetsAt": weekly[1]}
    made = {"accountId": "acct_ExampleUser_1234", "planType": "pro", "rateLimitsByLimitId": {"codex": limits},
            "ordinaryUsageAllowed": False}
    if credits is not None:
        made["rateLimitResetCredits"] = {"availableCount": credits, "credits": listed if listed is not None else [
            {"id": "rc_ExampleUser", "title": "Reset credit", "description": "x", "grantedAt": NOW - 86400,
             "expiresAt": NOW + 30 * 86400, "resetType": "codexRateLimits", "status": "available"}]}
    return {"reply": made}


def backend(identity=None, look=None, elsewhere=(), exe=EXE, compatible=()):
    return {"codex_exe": exe, "identity": identity, "app_look": look, "served_elsewhere": list(elsewhere),
            "compatible": list(compatible)}


def turns(running=(), latest=None, between=None):
    return {"running": list(running), "latest": latest or {}, "between": between or {}}


def turn(status, ordinal, turn_id="turn-1"):
    return {"status": status, "ordinal": ordinal, "turn_id": turn_id}


class CapacityDiff(AdvUsageDiff):
    def test_capacity(self):
        ops = [{"make": "capacity_retry", "as": "c"}, {"make": "capacity_retry", "as": "u", "unbound": True}]
        failures = [{"category": "server_5xx", "code": "serverOverloaded"},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": None},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": {"chain_started_at": NOW - 100}},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": {"chain_started_at": NOW - 7300}},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": {"chain_started_at": None}},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": {"chain_started_at": True}},
                    {"category": "server_5xx", "code": "serverOverloaded", "chain": 5},
                    {"category": "server_5xx", "code": "other"}, {"category": "usage_limit"}, {}, None, "x", [1]]
        # Unbound, the code reads the wall clock and its own DEFAULT_HOURS (a bound one reads the option's registry
        # default): a first failure 2.5 hours ago is past two hours and inside three, whatever minute this runs.
        wall = int(time.time()) - 9000
        ops += [hook("u", "admission", {"category": "server_5xx", "code": "serverOverloaded",
                                        "chain": {"chain_started_at": wall}}),
                hook("u", "gate", "known_failure", {"category": "server_5xx", "chain_started_at": wall}, {})]
        records = [{"category": "server_5xx", "chain_started_at": NOW - 10}, {"category": "server_5xx",
                   "chain_started_at": NOW - 7201}, {"category": "server_5xx"}, {"category": "x"}, None, 3]
        for at in (0, 3600, 7199, 7300):
            ops.append(clock(at))
            for code in ("c", "u"):
                ops += [hook(code, "admission", failure) for failure in failures]
                for name in ("known_failure", "usage", None):
                    ops += [hook(code, "gate", name, record, {}) for record in records]
        self.same("capacity", ops)


class EarlyDiff(AdvUsageDiff):
    def test_early_walks(self):
        rng = random.Random(21)
        for walk in range(6):
            ops = [{"make": "early_reset", "as": "e"}]
            at = 0
            for _ in range(160):
                at += rng.choice([0, 1, 10, 29, 31, 120, 299, 301, 600])
                ops.append(clock(at))
                record = {"category": rng.choice(["usage_limit", "usage_limit", "server_5xx"]),
                          "state": rng.choice(["waiting_reset", "waiting_poll", "waiting_retry"]),
                          "interruption_id": rng.choice(["r1", "r2", "r3", 4]),
                          "not_before": rng.choice([None, None, NOW + at + 50, NOW + at - 50])}
                kind = rng.random()
                if kind < .45:
                    ops.append(hook("e", "schedule", record, rng.choice([NOW + at + 600, NOW + at - 1, None, "x"])))
                elif kind < .8:
                    facts = {"schedule": rng.choice([["PASS", "plugged"], ["PASS", "ok"], None, "PASS"])}
                    ops.append(hook("e", "gate", rng.choice(["usage", "usage", "known_failure"]), record, facts))
                elif kind < .88:
                    ops.append(hook("e", "not_taken", record))
                elif kind < .95:
                    ops.append({"method": "stamp", "args": ["early_reset", "check_asked", NOW + at]})
                else:
                    ops.append({"switches": {"on": {"early_reset": rng.random() < .8}}})
                if rng.random() < .2:
                    ops.append(kept("e"))
            ops.append(kept("e"))
            self.same("early walk %d" % walk, ops)

    def test_unhashable_ids(self):
        ops = [{"make": "early_reset", "as": "e"},
               hook("e", "schedule", {"category": "usage_limit", "state": "waiting_reset", "interruption_id": [1]},
                    NOW + 900), kept("e"),
               hook("e", "gate", "usage", {"interruption_id": {"a": 1}}, {"schedule": ["PASS", "plugged"]}),
               hook("e", "not_taken", {"interruption_id": [2]}), hook("e", "schedule", None, NOW + 1)]
        self.same("early unhashable", ops)


def meter_start(identity=None, look=None):
    return [{"inuse": "tell", "args": [EXE, CODEX_HOME]}, {"make": "usage_meter", "as": "m"}]


class MeterDiff(AdvUsageDiff):
    """test_advanced_meter_skip_wait and ..._engine_elsewhere, by the same steps."""

    def look(self, at):
        return [clock(at), hook("m", "tick", None), run("m"), kept("m")]

    def test_skipped_looks_are_spaced(self):
        ops = meter_start()
        ops += self.look(0)
        for at in (5, 30, 59):
            ops += [clock(at), hook("m", "tick", None)]
        ops += self.look(60) + [LOG]
        self.same("skipped looks spaced", ops, world={"backend": backend(), "session": {"replies": []}})

    def test_kept_backend_checks_again(self):
        ops = meter_start() + self.look(0) + self.look(60) + self.look(120) + [LOG]
        ops += [world(backend=backend(compatible=["raise"]))] + self.look(180) + self.look(240) + [LOG]
        ops += [{"inuse": "tell", "args": [PACKAGE, CODEX_HOME]}] + self.look(300) + [LOG]
        self.same("kept backend", ops, world={"backend": backend()})

    def test_read_within_a_wait_of_the_app_opening(self):
        ops = meter_start() + self.look(0)
        ops += [world(backend=backend(identity={"pid": 4242}),
                      session={"replies": [reply((92, RESET5), (40, RESETW)), reply((96, RESET5), (50, RESETW))]})]
        ops += [clock(30), hook("m", "tick", None)] + self.look(60)
        ops += [clock(60 + 1800), hook("m", "tick", None), clock(60 + 900), hook("m", "tick", None)]
        ops += self.look(60 + 901) + [LOG, {"inuse": "elsewhere"}]
        self.same("read after the app opens", ops, world={"backend": backend()})

    def test_unmatched_and_elsewhere(self):
        ops = meter_start() + self.look(0) + [LOG, {"inuse": "elsewhere"}]
        ops += [world(backend=backend(look="unmatched", elsewhere=[PACKAGE.upper()], exe=EXE.lower()))]
        ops += self.look(61) + [{"inuse": "elsewhere"}]
        ops += [world(backend=backend(look="unmatched", elsewhere=[PACKAGE], exe=r"C:\other\codex.exe"))]
        ops += self.look(122) + [{"inuse": "elsewhere"}, {"inuse": "forget"}] + self.look(183)
        ops += [{"inuse": "elsewhere"}, world(backend={"raise": "ConfigError"})] + self.look(244) + self.look(305)
        self.same("unmatched", ops, world={"backend": backend(look="unmatched", elsewhere=[PACKAGE])})

    def test_reading_warnings_and_samples(self):
        replies = [reply((86, RESET5), (88, RESETW)), {"raise": "adapter", "code": "protocol_timeout"},
                   reply((99, RESET5), (99.5, RESETW)), {"reply": {"nothing": 1}}, reply((10, RESET5 + 18000))]
        ops = meter_start()
        ops += [{"switches": {"armed": {"usage_analytics": True}}}]
        for index in range(len(replies)):
            ops += self.look(index * 901)
        ops += [{"method": "stamp", "args": ["account_switch", "account_changed_at", NOW + 5000]}]
        ops += [clock(4600), hook("m", "tick", None), clock(5000), hook("m", "tick", None)]
        ops += [world(switched=NOW + 5100)] + self.look(5200) + [LOG]
        ops += [{"switches": {"on": {"usage_meter": False}}}] + self.look(9000) + [LOG]
        self.same("readings", ops, world={"backend": backend(identity={"pid": 1}), "session": {"replies": replies}})

    def test_meter_walks(self):
        rng = random.Random(31)
        for walk in range(4):
            ops = meter_start()
            at = 0
            replies = [rng.choice([reply((rng.choice([50, 85, 90, 97, 100]), RESET5 + rng.choice([0, 18000])),
                                         (rng.choice([20, 86, 99]), RESETW)),
                                   {"raise": "adapter", "code": "x"}, {"reply": None}]) for _ in range(40)]
            for _ in range(70):
                at += rng.choice([1, 30, 59, 60, 61, 300, 900, 901, 3600])
                choice = rng.random()
                if choice < .15:
                    ops.append(world(backend=rng.choice([backend(), backend(identity={"pid": 2}),
                                                         backend(look="unmatched", elsewhere=[PACKAGE]),
                                                         backend(identity={"pid": 3}, compatible=["ok", "raise"]),
                                                         {"raise": "AdapterError"}])))
                elif choice < .2:
                    ops.append({"inuse": "tell", "args": [rng.choice([EXE, PACKAGE]), CODEX_HOME]})
                elif choice < .23:
                    ops.append({"inuse": "forget"})
                ops += self.look(at)
            ops += [LOG, {"inuse": "elsewhere"}]
            self.same("meter walk %d" % walk, ops,
                      world={"backend": backend(identity={"pid": 1}), "session": {"replies": replies}})


def wrap_world(**more):
    made = {"backend": backend(identity={"pid": 1}), "locale": "en", "home": CODEX_HOME,
            "session": {"replies": [reply((92, RESET5), (96, RESETW))]},
            "turns": turns([THREAD, OTHER], {THREAD: turn("inProgress", 4), OTHER: turn("completed", 2)}),
            "source": {"latest": {THREAD: {"ordinal": 4, "status": "inProgress"}, OTHER: {"ordinal": 2, "status": "completed"}}},
            "view": {"enabled": {}}}
    made.update(more)
    return made


def read_meter():
    return meter_start() + [hook("m", "tick", None), run("m")]


class WrapUpDiff(AdvUsageDiff):
    def test_wrap_up_and_after_reset(self):
        ops = read_meter() + [{"make": "usage_wrap_up", "as": "w"}]
        ops += [hook("w", "tick", None), hook("w", "records", None), kept("w"), LOG]
        ops += [clock(30), hook("w", "tick", None), clock(61), hook("w", "tick", None), hook("w", "records", None)]
        ops += [{"method": "end_continuations", "args": ["sent"], "kwargs": {"capability": "usage_wrap_up",
                                                                             "thread_id": THREAD}}]
        ops += [world(source={"latest": {OTHER: {"ordinal": 9, "status": "inProgress"}}}), hook("w", "records", None), LOG]
        ops += [clock(4 * 3600), world(turns=turns([], {THREAD: turn("completed", 5), OTHER: turn("failed", 3)},
                                                   {THREAD: 0}),
                                       source={"latest": {THREAD: {"ordinal": 5, "status": "completed"}}}),
                hook("w", "tick", None), hook("w", "records", None), LOG]
        ops += [clock(4 * 3600 + 61), world(locale=None), hook("w", "tick", None), hook("w", "records", None), LOG]
        self.same("wrap-up", ops, world=wrap_world())
        for between, status in ((1, "completed"), (0, "failed"), (0, "inProgress")):
            ended = next(index for index, op in enumerate(ops) if op.get("method") == "end_continuations")
            later = ops[:ended + 1] + [clock(5 * 3600), world(turns=turns([], {THREAD: turn(status, 6)}, {THREAD: between}),
                                             source={"latest": {THREAD: {"ordinal": 6, "status": status}}}),
                      hook("w", "tick", None), hook("w", "records", None), LOG]
            self.same("wrap-up after reset %s %s" % (between, status), later, world=wrap_world())

    def test_wrap_up_words_and_edges(self):
        for style, locale, enabled in ((1, "ko", True), (4, "ja", True), (5, "en", "raise"), (3, None, False)):
            ops = read_meter() + [{"make": "usage_wrap_up", "as": "w"}]
            ops += [{"method": "set_wording", "args": ["usage_wrap_up", "wrap_custom_five_hour",
                                                         "Stop at {stop_at} ({window}, {percent}%) {reset}"],
                     "kwargs": {"generation": 0, "actor": "dashboard"}}]
            ops += [hook("w", "tick", None), hook("w", "records", None), LOG]
            more = wrap_world(locale=locale, view={"enabled": {THREAD: enabled}})
            self.same("wrap-up style %s" % style, ops, world=more)

    def test_wrap_up_reads_that_fail(self):
        for broken in ({"home": {"raise": "ConfigError"}}, {"turns": {"running": {"raise": "TurnsUnavailable"}}},
                       {"source": {"make": {"raise": "SourceError"}}},
                       {"turns": turns([THREAD], {THREAD: {"raise": "TurnsUnavailable"}})},
                       {"source": {"latest": {THREAD: {"raise": "SourceError"}}}}):
            ops = read_meter() + [{"make": "usage_wrap_up", "as": "w"}, hook("w", "tick", None),
                                  hook("w", "records", None), LOG]
            self.same("wrap-up broken %s" % sorted(broken), ops, world=wrap_world(**broken))


def stop_world(**more):
    made = wrap_world(session={"replies": [reply((98, RESET5), (40, RESETW)), reply((10, RESET5 + 18000), (40, RESETW))]})
    made["ipc"] = {"stop": [], "start": []}
    made.update(more)
    return made


class StopDiff(AdvUsageDiff):
    def stop_ops(self):
        ops = read_meter() + [{"make": "usage_pause", "as": "s"}, {"make": "usage_pause", "as": "p", "plain": True}]
        ops += [hook("s", "tick", None), run("s"), kept("s"), LOG,
                world(turns=turns([], {THREAD: turn("interrupted", 4), OTHER: turn("completed", 2)}))]
        ops += [hook("s", "gate", "usage", {"interruption_id": "i1"}, {}), hook("p", "gate", "usage", {"interruption_id": "i1"}, {}),
                hook("s", "holds", {"state": "waiting", "purpose": "continuation"}),
                hook("s", "holds", {"state": "waiting", "purpose": "message"}), hook("p", "tick", None)]
        ops += [clock(3600), hook("s", "tick", None)]
        ops += [clock(3 * 3600 + 61), hook("m", "tick", None), run("m"), hook("s", "tick", None), run("s"), kept("s"), LOG]
        ops += [hook("s", "gate", "usage", {"interruption_id": "i1"}, {}), clock(3 * 3600 + 400), hook("s", "tick", None)]
        ops += [run("s"), kept("s"), LOG]
        return ops

    def test_stop_and_continue(self):
        self.same("stop and continue", self.stop_ops(), world=stop_world(ipc={"stop": ["stopped"], "start": ["started"]}))

    def test_stop_words(self):
        for stop, start in ((["unconfirmed"], ["unconfirmed", "started"]), (["held"], []), (["!no_pipe"], []),
                            (["raise"], []), (["not_stopped"], []), (["stopped"], ["!no_client", "started"]),
                            (["stopped"], ["raise"])):
            self.same("stop %s start %s" % (stop, start), self.stop_ops(), world=stop_world(ipc={"stop": stop, "start": start}))

    def test_stop_with_continue_off_and_guard(self):
        ops = [{"method": "set_option", "args": ["usage_wrap_up", "wrap_after_reset", 2],
                "kwargs": {"generation": 0, "actor": "dashboard"}}] + self.stop_ops()
        self.same("continue off", ops, world=stop_world())
        self.same("guard refuses", self.stop_ops(), world=stop_world(guard=False))

    def test_carry_reset_message(self):
        """R2 / review V1: the stop's turn after the reset carries the person's reset message in its place."""
        # A plain word is answered after the gate (the launch written); "!word" before it (nothing launched).
        for start in (["started"], ["unconfirmed"], ["!no_client"], ["raise"], ["no_client"], ["refused"],
                      ["broken"]):
            ops = read_meter() + [{"make": "usage_pause", "as": "s"}, {"switches": {"armed": {"reset_message": True}}},
                                  {"method": "add_reset_rule", "args": ["reset_message", "codex", 300, 1],
                                   "kwargs": {"thread_id": THREAD, "words": "My own words after the reset.",
                                              "record_id": "cd" * 32}}]
            ops += [hook("s", "tick", None), run("s"), LOG,
                    world(turns=turns([], {THREAD: turn("interrupted", 4)}))]
            ops += [{"method": "change_rule", "args": [1], "kwargs": {"expect": "counting", "state": "ready",
                                                                       "due_at": NOW + 3 * 3600 + 70, "base": 0}}]
            ops += [clock(3 * 3600 + 61), hook("m", "tick", None), run("m"), clock(3 * 3600 + 100),
                    hook("s", "tick", None), run("s"), kept("s"), LOG,
                    {"method": "reset_rules", "kwargs": {"pending": None}}]
            ops += [clock(3 * 3600 + 500), hook("s", "tick", None), run("s"), kept("s"), LOG]
            self.same("carry start %s" % start, ops,
                      world=stop_world(ipc={"stop": ["stopped"], "start": start}))


def credit_world(**more):
    made = {"view": {"records": [{"category": "usage_limit", "state": "waiting_reset", "detected_at": NOW - 50}]},
            "session": {"replies": [reply((50, RESET5), credits=2), reply((100, RESET5), credits=2),
                                    reply((100, RESET5), credits=2), {"reply": {"outcome": "reset"}},
                                    reply((5, RESET5 + 18000), credits=1)]}}
    made.update(more)
    return made


class CreditDiff(AdvUsageDiff):
    def credit_ops(self, ordinal=1, ask_first=False):
        ops = [{"make": "reset_credit", "as": "c"},
               {"switches": {"verdict": {"mr": "pass", "mu": "pass"}}},
               {"method": "add_reset_rule", "args": ["reset_credit", "codex", 300, ordinal],
                "kwargs": {"ask_first": ask_first}}]
        for at in (0, 301, 901, 1802, 2703):
            ops += [clock(at), hook("c", "tick", None), run("c"), kept("c"), LOG,
                    {"method": "reset_rules", "kwargs": {"pending": None}}, {"method": "credit_spends"}]
        ops += [hook("c", "schedule", {"category": "usage_limit", "state": "waiting_reset"}, NOW + 99999),
                hook("c", "schedule", {"category": "usage_limit", "state": "waiting_for_usage"}, NOW + 99999)]
        return ops

    def test_credit_spends(self):
        self.same("credit", self.credit_ops(), world=credit_world())
        full = [reply((100, RESET5), credits=2), reply((100, RESET5), credits=2), {"reply": {"outcome": "alreadyRedeemed"}},
                reply((5, RESET5 + 18000), credits=1)]
        self.same("credit now", self.credit_ops(ordinal=0), world=credit_world(session={"replies": full}))
        self.same("credit ask first", self.credit_ops(ask_first=True), world=credit_world())

    def test_credit_answers(self):
        for answer in ({"raise": "adapter", "code": "protocol_timeout"}, {"raise": "bycodex", "code": -32601},
                       {"raise": "bycodex", "code": -32000}, {"reply": {"outcome": "noCredit"}}, {"reply": {}},
                       {"raise": "runtime"}):
            replies = [reply((50, RESET5), credits=2), reply((100, RESET5), credits=2), reply((100, RESET5), credits=2),
                       answer, reply((100, RESET5), credits=2), reply((100, RESET5), credits=2), answer]
            self.same("credit answer %s" % answer, self.credit_ops(),
                      world=credit_world(session={"replies": replies}))
        for broken in ({"session": {"open": {"raise": "x"}}}, {"session": {"enter": {"raise": "x"}, "replies": []}},
                       {"session": {"submit": {"raise": "adapter"}, "replies": [reply((100, RESET5), credits=2)] * 4}},
                       {"guard": False}, {"view": {"records": []}},
                       {"session": {"replies": [reply((100, RESET5), credits=None)] * 4}},
                       {"session": {"replies": [reply((100, RESET5), credits=0)] * 4}}):
            self.same("credit broken %s" % sorted(broken), self.credit_ops(), world=credit_world(**broken))


class MessageDiff(AdvUsageDiff):
    def test_message(self):
        ops = [{"make": "reset_message", "as": "r"}, {"switches": {"verdict": {"mu": "pass"}}},
               {"method": "add_reset_rule", "args": ["reset_message", "codex", 300, 1],
                "kwargs": {"thread_id": THREAD, "words": "Hello after the reset.", "record_id": "a1" * 32}},
               {"method": "add_reset_rule", "args": ["reset_message", "codex", 10080, 2],
                "kwargs": {"thread_id": OTHER, "words": "x" * 2100, "record_id": "b2" * 32}}]
        for at in (0, 301, 3 * 3600 + 61, 3 * 3600 + 400, 3 * 3600 + 2000, 2 * 86400, 9 * 86400):
            ops += [clock(at), hook("r", "tick", None), run("r"), hook("r", "records", None),
                    hook("r", "watched_due", None),
                    hook("r", "gate", "usage", {"thread_id": THREAD, "category": "usage_limit", "reset_at": RESET5}, {}),
                    hook("r", "gate", "usage", {"thread_id": OTHER, "category": "usage_limit", "reset_at": RESETW}, {}),
                    LOG, {"method": "reset_rules", "kwargs": {"pending": None}}]
        replies = [reply((50, RESET5), (60, RESETW)), reply((70, RESET5), (60, RESETW)),
                   reply((10, RESET5 + 18000), (60, RESETW)), reply((10, RESET5 + 18000), (60, RESETW))] * 3
        self.same("message", ops, world={"session": {"replies": replies}, "view": {"enabled": {OTHER: False}}})
        held = [{"switches": {"armed": {"usage_pause": True, "long_reset_message": True}}},
                {"method": "add_continuation", "args": ["k" * 64, "usage_pause", "after_reset", THREAD, "go"],
                 "kwargs": {"ordinal": 4, "chain": 300}}] + ops
        self.same("message held by the stop", held,
                  world={"session": {"replies": replies}, "view": {"enabled": {}}})

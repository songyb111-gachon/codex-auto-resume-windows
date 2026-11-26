"""P2's records of the plug's own and P11's ledger in car-engine's traces (seat S7.2a2): a scripted plug on both sides.

`diffs_engine_plug`'s scripted plug answered every hook but P2 and P11, which only the advanced plug reached. Here the
script hands records over (`records`: waiting with a person's words, or in flight) and answers the claim's ledger
(`claim_ledger`: HOLD, a raise, DEFER), and every step runs on both sides as there: the reference's Engine and Store of the
v0.6.26 tag against car-engine over car-store, compared step by step - the answer, every log line, every backend call (the
send inside `record_guard`, a queue item taken back), the whole state store and every question put to the plug, P14's
`moved` with each record's move, gate and reason among them.
"""
from __future__ import annotations

import unittest

from rustdiff import diffs_engine, diffs_engine_plug

T1, T2 = diffs_engine.T1, diffs_engine.T2
EVERY = diffs_engine_plug.EVERY + ["records", "claim_ledger"]
MARKER_PREFIX = "[codex-auto-resume:"
ID_A = "a" * 63 + "1"
ID_B = "b" * 63 + "2"
ID_C = "c" * 63 + "3"
WORDS = "Please look at the failing test in the parser and tell me what you find."


def marker(key: str) -> str:
    return MARKER_PREFIX + key[:16] + "]"


def waiting(key=ID_A, thread=T1, words=WORDS, **more) -> dict:
    return dict({"record_id": key, "thread_id": thread, "marker": marker(key), "state": "waiting", "words": words,
                 "sent_at": None}, **more)


def flying(key=ID_A, thread=T1, sent_at=diffs_engine.BASE, **more) -> dict:
    return dict({"record_id": key, "thread_id": thread, "marker": marker(key), "state": "in_flight", "words": None,
                 "sent_at": sent_at}, **more)


def script(**rules) -> dict:
    return diffs_engine_plug.script(EVERY, **rules)


def ready(s, thread=T1):
    """A person's own conversation the app holds, whose usage-limit record waits for its reset (never in flight)."""
    s.home("fail_usage", thread, diffs_engine.TURN_A)
    s.loaded(thread)
    return s.tick()


def scenarios() -> dict:
    found = []

    def new(name, **rules):
        s = diffs_engine_plug.Plugged(name, plug=script(**rules))
        found.append(s)
        return s.enable()

    # A waiting message that passes every gate: claimed, sent with its marker inside record_guard, told SENT; then
    # handed in flight and found queued (kept), and once Codex runs it, delivered.
    s = new("pr_sent_then_delivered", records=[{"answer": [waiting()], "times": 1},
                                               {"answer": [flying()], "times": 2}])
    ready(s).adv(5).tick().home("dispatch", T1)
    s.adv(5).tick().adv(5).tick()
    # The ledger holds the claim, then raises (RECORDS carried: held either way, its writes rolled back), then defers.
    s = new("pr_ledger_hold_raise_defer", records=[{"answer": [waiting()]}],
            claim_ledger=[{"answer": "hold", "times": 1}, {"answer": "raise", "times": 1}])
    ready(s).adv(5).tick().adv(5).tick().adv(5).tick()
    # The ledger asked at the launch too: HOLD there refuses the launch (RELEASED, never sent).
    s = new("pr_ledger_holds_the_launch", records=[{"answer": [waiting()], "times": 1}],
            claim_ledger=[{"when": {"phase": "launch"}, "answer": "hold"}])
    ready(s).adv(5).tick()
    # Gates: paused, the conversation off, observe only (the would-send line once), quiet hours, no app.
    s = new("pr_paused", records=[{"answer": [waiting()]}])
    ready(s).pause().tick()
    s = new("pr_observe_only_noted_once", records=[{"answer": [waiting(), waiting(ID_B, T2)]}])
    ready(s).policy(observe_only=True).tick().adv(5).tick()
    s = new("pr_no_app", records=[{"answer": [waiting()]}])
    s.backend(app=None)
    ready(s).tick()
    s = new("pr_not_loaded", records=[{"answer": [waiting()]}])
    s.home("fail_usage", T1, diffs_engine.TURN_A)
    s.loaded(T1, "notLoaded")
    s.tick()
    # Not a person's own conversation: waits (identity); a continuation whose turn is no longer the latest: SUPERSEDED.
    s = new("pr_unknown_conversation", records=[{"answer": [waiting(thread=T2)]}])
    ready(s).tick()
    s = new("pr_continuation_superseded",
            records=[{"answer": [waiting(purpose="continuation", ordinal=0,
                                         words="Continue from where you stopped.")]}])
    ready(s).tick()
    # Words that fail the check are dropped (no move told); damaged records are dropped by core's own check.
    s = new("pr_bad_words_and_damaged", records=[{"answer": [waiting(words=MARKER_PREFIX + "x] hi"),
                                                             {"record_id": "nope"}, waiting(ID_B, words="   ")]}])
    ready(s).tick()
    # The send: not started, refused at the launch, raising, unknown.
    for outcome in ("not_started", "raise", "unknown"):
        s = new("pr_send_" + outcome, records=[{"answer": [waiting()], "times": 1}])
        s.backend(default_outcome=outcome)
        ready(s).adv(5).tick()
    # In flight: never seen, a day passes - unproven; a queue item a person edited - handed over; one a person
    # cancelled - taken back (withdrawn), and one Codex will not give back - refused once, never asked again.
    s = new("pr_unproven_after_a_day", records=[{"answer": [flying(sent_at=diffs_engine.BASE - 90000)]}])
    ready(s).adv(5).tick()
    s = new("pr_in_flight_raise_and_marker_free", records=[{"answer": "raise", "times": 1},
                                                           {"answer": [flying(purpose="message")]}],
            delivery=["client_id"])
    ready(s).adv(5).tick().adv(5).tick()
    # A Pause with a record in flight: watched with the plug asked nothing.
    s = new("pr_sent_then_paused", records=[{"answer": [waiting()], "times": 1}])
    ready(s).adv(5).tick().pause().adv(5).tick().adv(90000).tick()
    return dict(each.done() for each in found)


class EngineRecordsDiff(unittest.TestCase):
    """Every P2/P11 scenario's trace, step by step, the plug's questions with it."""

    maxDiff = None
    check = diffs_engine_plug.EnginePlugDiff.check

    def test_records_and_ledger(self):
        self.check(scenarios(), "P2 records and P11's ledger")


if __name__ == "__main__":
    unittest.main()

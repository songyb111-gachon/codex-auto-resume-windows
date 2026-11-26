"""S7.2e1: the small capabilities of sends and turns against the v0.6.26 tag's (P7-DESIGN 3.2 `diffs_advturns_*`):
silent_continuation (P15), every_conversation (P19), other_sessions (P18, P16), parallel_dispatch (P12) and
once_more_when_unsure (P7), each through the runtime off, watched and on, with the edges of what each hook is handed.

    python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 --reference-python bundled -k AdvTurnsSmallDiff
"""
from __future__ import annotations

import unittest

from rustdiff import advturns
from rustdiff.advturns import KEY, NOW, OTHER_KEY, THREAD, arm, record, scenario

UNKNOWN = dict(state="submission_unknown", last_error="no_receipt_do_not_resend", submitted_at=NOW - 1000,
               queue_id=None, first_queued_at=None, recovery_client_id=None, cancel_requested=0, hold=None,
               gate_eval=None, last_claim_at=NOW - 1000)


def corpus() -> list:
    silent = "silent_continuation"
    every = "every_conversation"
    sessions = "other_sessions"
    parallel = "parallel_dispatch"
    once = "once_more_when_unsure"
    delivery = ["ask", "delivery", record()]
    return [
        scenario("silent_off_watched_on", [silent],
                 [delivery, arm(silent, "shadow"), delivery, arm(silent), delivery, ["ask", "delivery", "not a record"]]),
        scenario("silent_after_codex_refused_empty", [silent],
                 [arm(silent), ["flag", "empty_refused", True], delivery, ["flag", "empty_refused", False], delivery]),
        scenario("every_conversation", [every],
                 [["eligibility"], arm(every, "shadow"), ["eligibility"], arm(every), ["eligibility"]]),
        scenario("other_sessions_kinds_and_holders", [sessions],
                 [["sessions"], arm(sessions), ["sessions"],
                  ["ask", "unloaded", record(holder="session")],
                  ["ask", "unloaded", record(holder="none", app=False)],
                  ["ask", "unloaded", record(holder="session", queued_since=NOW)],
                  ["ask", "unloaded", record(OTHER_KEY, holder="app")],
                  ["ask", "unloaded", record(OTHER_KEY)],
                  ["ask", "unloaded", ["holder", "session"]],
                  ["ask", "unloaded", record(OTHER_KEY, holder="Session")]]),
        scenario("parallel_workers", [parallel],
                 [["partition", [record(), record(OTHER_KEY)]], arm(parallel), ["partition", [record()]],
                  ["partition", [record(), record(OTHER_KEY)]], ["partition", "two"], ["partition", []],
                  ["choose", parallel, "workers", 4], ["partition", [record(), record(OTHER_KEY)]],
                  ["choose", parallel, "workers", 9], ["partition", [record(), record(OTHER_KEY), record("c" * 64)]],
                  ["choose", parallel, "workers", 2], ["partition", [record(), record(OTHER_KEY)]]]),
        scenario("parallel_workers_once_mq_passed", [parallel],
                 [arm(parallel), ["choose", parallel, "workers", 6], ["partition", [record(), record(OTHER_KEY)]],
                  ["choose", parallel, "workers", 8], ["partition", [record(), record(OTHER_KEY)]],
                  ["choose", parallel, "workers", "8"], ["partition", [record(), record(OTHER_KEY)]]],
                 measured={"mq": ["pass", "0.155.0"]}),
        scenario("parallel_watched_only_journals", [parallel],
                 [arm(parallel, "shadow"), ["partition", [record(), record(OTHER_KEY)]]]),
        scenario("once_more_resends_once", [once],
                 [["ask", "schedule", record(**UNKNOWN), None], arm(once),
                  ["ask", "schedule", record(**UNKNOWN), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, state="submitted")), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, submitted_at=NOW - 10)), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, submitted_at=NOW - 7 * 3600)), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, last_claim_at=True)), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, last_claim_at="soon")), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, last_claim_at=10 ** 400)), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, queue_id="q1")), None],
                  ["ask", "schedule", record(**dict(UNKNOWN, cancel_requested=1)), None],
                  ["ask", "schedule", "a record", None],
                  ["clock", NOW + 3600], ["ask", "schedule", record(OTHER_KEY, **UNKNOWN), None]]),
        scenario("once_more_watched", [once],
                 [arm(once, "shadow"), ["ask", "schedule", record(**UNKNOWN), None]]),
    ]


class AdvTurnsSmallDiff(advturns.AdvTurnsCase, unittest.TestCase):
    """The small capabilities, scenario by scenario, against the tag's."""

    def test_scenarios(self):
        self.check_all(corpus())


if __name__ == "__main__":
    unittest.main()

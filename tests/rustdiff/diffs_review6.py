"""Review 6 (car-engine, car-scheduler; outputs/plans/v0627-rust/REVIEW-engine.md): engine traces that differ today.

Each scenario is run as diffs_engine's are - the reference's Engine and car-engine through car-harness on the same
worlds, every step compared - and each is one the corpus and the random walks never feed:

* `r6_fresh_home_history_not_yet` (against the v0.6.26 final, D17's tag): a Codex home Codex has not made its history
  in yet - its state holds no conversation, its history database is not there. The final's engine/detect.py catches
  HistoryNotYet and reads it as a detection that read nothing (no `detection_unavailable_no_submission`,
  `detection_failed` False); car-engine, ported from beta.2, said the detection failed until the final-port seat
  (FINAL-DELTA #11) ported the catch; `r6_fresh_home_then_history` then has Codex make its history. `rediff_engine.py --reference
  v0.6.26` stays equal without this scenario, because no corpus scenario has a home without a conversation.
* `r6_watch_budget_huge`: a watch budget of 1e300 seconds. The reference adds it to `time.monotonic()`; car-scheduler's
  `Duration::from_secs_f64` panics, and the tick ends in a panic the reference never meets.
* `r6_queue_retries_fraction`: `max_queue_retries` 2.5. The reference compares the retry count with 2.5 (it fails at
  the third launch that never started); car-engine's `Options::apply` truncates it to 2 (it fails at the second).

The last two are options no watcher passes today (runtime/app.py hands an engine `delivery_timeout_seconds` alone);
they are what `Engine(options=...)` accepts, as the frozen scenario modules hand it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from rustdiff import diffs_engine, reference

RECORD = diffs_engine.RECORD
FINAL = "v0.6.26"
Scenario, ready_after_reset, T1, TURN_A = (diffs_engine.Scenario, diffs_engine.ready_after_reset, diffs_engine.T1,
                                          diffs_engine.TURN_A)


def fresh_home() -> dict:
    found = []
    s = Scenario("r6_fresh_home_history_not_yet").enable()
    s.helper("history_aside", True).tick().facts().tick().facts()
    found.append(s)
    # test_history_not_yet WatcherTests.test_a_failure_is_detected_once_codex_makes_its_history: the same fresh home,
    # then Codex makes its history and the first conversation fails - detected as any failure is.
    s = Scenario("r6_fresh_home_then_history").enable()
    s.helper("history_aside", True).tick().facts().helper("history_aside", False)
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().facts()
    found.append(s)
    return dict(each.done() for each in found)


def option_edges() -> dict:
    found = []
    s = Scenario("r6_watch_budget_huge", options={"watch_budget_seconds": 1e300}).enable()
    s.home("fail_usage", T1, TURN_A).loaded(T1).tick().facts()
    found.append(s)
    s = Scenario("r6_queue_retries_fraction", options={"max_queue_retries": 2.5}).enable()
    s.backend(default_outcome="not_started")
    ready_after_reset(s)
    for _ in range(5):
        s.tick().adv(301)
    found.append(s)
    return dict(each.done() for each in found)


class EngineReview6(unittest.TestCase):
    """Traces of inputs the engine corpus never feeds (REVIEW-engine.md)."""

    maxDiff = None

    def check(self, scenarios: dict, tag: str):
        with mock.patch.object(reference, "TAG", tag):
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
        RECORD.append("review6 against %s: %d scenarios, %d differ" % (tag, len(scenarios), len(problems)))
        self.assertEqual(problems, [], "\n".join(problems))

    # B1, brought to the v0.6.26 final by the final-port seat (car-codex's HistoryNotYet and car-engine's catch,
    # FINAL-DELTA #1-#4 and #11): equal to the reference, no longer an expected failure.
    def test_final_fresh_home_history_not_yet(self):
        self.check(fresh_home(), FINAL)

    def test_option_edges(self):
        self.check(option_edges(), reference.TAG)


if __name__ == "__main__":
    unittest.main()

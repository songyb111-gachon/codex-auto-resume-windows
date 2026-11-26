"""S7.2e1b: the edition's own continuations against the v0.6.26 tag's (P7-DESIGN 3.2 `diffs_advturns_*`): empty_response
(P8 errand + P2), keep_going (P8 + P2) and subagent_parent (P4, words_sent, P8 + P2), each through the runtime off and
on, over the scenario's looks of the Codex home (turns, goals, core's reader, the spawn edges) and the view's switch.

    python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 --reference-python bundled -k AdvTurnsContDiff
"""
from __future__ import annotations

import hashlib
import json
import unittest

from rustdiff import advturns
from rustdiff.advturns import NOW, THREAD, arm, scenario

EMPTY = "empty_response"
KEEP = "keep_going"
SUBAGENT = "subagent_parent"
EVERY = "every_conversation"
T2 = "0a1b2c3d-0001-7000-8000-000000000002"
T3 = "0a1b2c3d-0001-7000-8000-000000000003"
T4 = "0a1b2c3d-0001-7000-8000-000000000004"
T5 = "0a1b2c3d-0001-7000-8000-000000000005"
T6 = "0a1b2c3d-0001-7000-8000-000000000006"
T7 = "0a1b2c3d-0001-7000-8000-000000000007"
T8 = "0a1b2c3d-0001-7000-8000-000000000008"
DONE = int(NOW) - 100


def key(*parts) -> str:
    """engine/continued.answer_key."""
    return hashlib.sha256(json.dumps([str(part) for part in parts], separators=(",", ":")).encode("utf-8")).hexdigest()


def turn(turn_id="t1", ordinal=5, status="completed", kinds=(("userMessage", 1), ("reasoning", 2)), **more) -> dict:
    made = {"turn_id": turn_id, "status": status, "completed_at": DONE, "ordinal": ordinal,
            "kinds": [list(pair) for pair in kinds]}
    made.update(more)
    return made


def looks(times, start=NOW, every=61) -> list:
    """`times` looks a minute apart: the clock moved, the tick, its errand run."""
    steps = []
    for index in range(times):
        steps += [["clock", start + index * every], ["tick"], ["run"]]
    return steps


def empty_corpus() -> list:
    found_key = key(EMPTY, THREAD, "t1")
    return [
        scenario("empty_found_after_two_looks", [EMPTY],
                 [["tick"], ["records"], arm(EMPTY)] + looks(1) + [["records"]] + looks(1, NOW + 61)
                 + [["records"], ["clock", NOW + 70], ["tick"]] + looks(1, NOW + 125) + [["records"]],
                 seams={"recent": [THREAD], "turns": {THREAD: turn()}}),
        scenario("empty_goals_left_or_not", [EMPTY],
                 [arm(EMPTY)] + looks(2) + [["records"]],
                 seams={"recent": [THREAD, T2, T3, T4],
                        "turns": {THREAD: turn(), T2: turn(), T3: turn(), T4: turn()},
                        "goals": {THREAD: "active", T2: "blocked", T3: "raise", T4: "paused"}}),
        scenario("empty_kinds_that_are_not_empty", [EMPTY],
                 [arm(EMPTY)] + looks(3) + [["records"]],
                 seams={"recent": [THREAD, T2, T3, T4, T5, T6, T7, T8],
                        "turns": {THREAD: turn(final_agent=True), T2: turn(kinds=[["userMessage", 1], ["agentMessage", 1]]),
                                  T3: turn(errored=True), T4: turn(status="failed"),
                                  T5: turn(kinds=[["reasoning", 3]]), T6: turn(completed_at=None),
                                  T7: turn(kinds=[["userMessage", 0], ["reasoning", 1]]),
                                  T8: turn(kinds=[["userMessage", 2], ["userMessage", 0]])}}),
        scenario("empty_settles_and_shape_changes", [EMPTY],
                 [arm(EMPTY)] + looks(1) + [["seam", "turns", {THREAD: turn(completed_at=int(NOW) + 55),
                                                              T2: turn("t9")}]]
                 + looks(3, NOW + 61) + [["records"]],
                 seams={"recent": [THREAD, T2], "turns": {THREAD: turn(completed_at=int(NOW) - 5), T2: turn()}}),
        scenario("empty_switched_off_not_own_and_unreadable", [EMPTY],
                 [arm(EMPTY)] + looks(2) + [["records"]],
                 enabled={THREAD: False, T2: "raise"},
                 seams={"recent": [THREAD, T2, T3, T4, T5, 7],
                        "turns": {THREAD: turn(), T2: turn(), T3: turn(), T4: "raise", T5: None},
                        "own": {T3: False}}),
        scenario("empty_recent_unreadable", [EMPTY], [arm(EMPTY)] + looks(2) + [["records"]],
                 seams={"recent": "raise", "turns": {THREAD: turn()}}),
        scenario("empty_chain_of_three", [EMPTY],
                 [arm(EMPTY)] + looks(2) + [["moved", {"record_id": found_key}, "delivered"],
                                            ["seam", "turns", {THREAD: turn("t2", 6)}]]
                 + looks(2, NOW + 122)
                 + [["moved", {"record_id": key(EMPTY, THREAD, "t2")}, "delivered"],
                    ["seam", "turns", {THREAD: turn("t3", 7)}]]
                 + looks(2, NOW + 244) + [["records"]]
                 + [["seam", "turns", {THREAD: turn("t4", 9)}], ["seam", "between", {THREAD: 1}]]
                 + looks(2, NOW + 366) + [["records"]],
                 seams={"recent": [THREAD], "turns": {THREAD: turn()}}),
        scenario("empty_chain_unreadable_between", [EMPTY],
                 [arm(EMPTY)] + looks(2) + [["moved", {"record_id": found_key}, "delivered"],
                                            ["seam", "turns", {THREAD: turn("t2", 6)}],
                                            ["seam", "between", {THREAD: "raise"}]]
                 + looks(2, NOW + 122) + [["records"]],
                 seams={"recent": [THREAD], "turns": {THREAD: turn()}}),
        scenario("empty_not_own_withdrawn_widened", [EMPTY, EVERY],
                 [arm(EMPTY), arm(EVERY)] + looks(2) + [["records"], ["seam", "own", {THREAD: False}]]
                 + looks(1, NOW + 122) + [["records"]],
                 seams={"recent": [THREAD], "turns": {THREAD: turn()}}),
        scenario("empty_watched_looks_nothing", [EMPTY],
                 [arm(EMPTY, "shadow")] + looks(2) + [["records"]],
                 seams={"recent": [THREAD], "turns": {THREAD: turn()}}),
    ]


def thread(number) -> str:
    return "0a1b2c3d-0001-7000-8000-%012d" % number


PROGRESS = (("userMessage", 1), ("agentMessage", 1))


def keep_corpus() -> list:
    threads = [thread(number) for number in range(11, 27)]
    stops = {threads[0]: turn(kinds=PROGRESS), threads[1]: turn(status="interrupted"),
             threads[2]: turn(status="failed"), threads[3]: turn(errored=True, kinds=PROGRESS),
             threads[4]: turn(), threads[5]: turn(kinds=PROGRESS), threads[6]: turn(kinds=PROGRESS),
             threads[7]: turn(kinds=PROGRESS), threads[8]: turn(kinds=PROGRESS),
             threads[9]: turn(kinds=PROGRESS), threads[10]: turn(status="inProgress"),
             threads[11]: turn(kinds=PROGRESS, completed_at=int(NOW) - 30), threads[12]: "raise",
             threads[13]: turn(kinds=PROGRESS), threads[14]: turn(kinds=PROGRESS), threads[15]: None}
    return [
        scenario("keep_found_used_and_spent", [KEEP],
                 [["tick"], arm(KEEP), ["tick"], ["keep", THREAD, 2]] + looks(1) + [["records"], ["tick"]]
                 + [["kept_used", THREAD], ["seam", "turns", {THREAD: turn("t2", 7, kinds=PROGRESS)}]]
                 + looks(1, NOW + 61) + [["records"], ["kept_used", THREAD],
                                         ["seam", "turns", {THREAD: turn("t3", 9, kinds=PROGRESS)}]]
                 + looks(2, NOW + 122) + [["records"], ["tick"]],
                 seams={"turns": {THREAD: turn(kinds=PROGRESS)}}),
        scenario("keep_unmeasured_three", [KEEP],
                 [arm(KEEP), ["keep", THREAD, 5], ["kept_used", THREAD], ["kept_used", THREAD], ["kept_used", THREAD]]
                 + looks(1) + [["records"]],
                 seams={"turns": {THREAD: turn(kinds=PROGRESS)}}),
        scenario("keep_measured_past_three", [KEEP],
                 [arm(KEEP), ["keep", THREAD, 5], ["kept_used", THREAD], ["kept_used", THREAD], ["kept_used", THREAD]]
                 + looks(1) + [["records"]],
                 measured={"mk": ["pass", "0.155.0"]},
                 seams={"turns": {THREAD: turn(kinds=PROGRESS)}}),
        scenario("keep_every_stop", [KEEP],
                 [arm(KEEP)] + [["keep", each, 3] for each in threads] + looks(2) + [["records"], ["tick"]],
                 enabled={threads[0]: False, threads[14]: "raise"},
                 seams={"turns": stops,
                        "goals": {threads[5]: "active", threads[13]: "raise", threads[9]: "paused"},
                        "plans": {threads[6]: "raise", threads[7]: ["completed", "completed"], threads[8]: [],
                                  threads[9]: ["completed", "pending"]}}),
        scenario("keep_watched", [KEEP],
                 [arm(KEEP, "shadow"), ["keep", THREAD, 2]] + looks(1) + [["records"]],
                 seams={"turns": {THREAD: turn(kinds=PROGRESS)}}),
        scenario("keep_sent_counts_through_the_runtime", [KEEP],
                 [arm(KEEP), ["keep", THREAD, 1]] + looks(1)
                 + [["moved", {"record_id": key(KEEP, THREAD, "t1")}, "sent"],
                    ["seam", "turns", {THREAD: turn("t2", 7, kinds=PROGRESS)}]]
                 + looks(1, NOW + 61) + [["records"]],
                 seams={"turns": {THREAD: turn(kinds=PROGRESS)}}),
    ]


def child(number, status="failed", category="usage_limit", turn_id="c1", thread_id=None) -> dict:
    return {"thread_id": thread(100 + number) if thread_id is None else thread_id, "turn_id": turn_id,
            "status": status, "category": category}


CHILDREN = [child(1), child(2, category="network_transient"), child(3, status="interrupted", category=None),
            child(4, category="terminal_auth"), child(5, status="completed", category=None),
            child(6, turn_id=None), child(7, thread_id="not-a-uuid"), child(8, thread_id=thread(108).upper())]


def subagent_corpus() -> list:
    from rustdiff.advturns import KEY, OTHER_KEY, record
    core = record(KEY, THREAD, category="usage_limit")
    text = ["ask", "text", core, "Core words."]
    return [
        scenario("subagent_lines_in_core_words", [SUBAGENT],
                 [text, arm(SUBAGENT), text, text, ["moved", core, "submitting"], text,
                  ["ask", "text", record(OTHER_KEY, T2), "Core words."],
                  ["ask", "text", record("short", THREAD), "Core words."],
                  ["ask", "text", record(OTHER_KEY, "not-a-thread"), "Core words."],
                  ["ask", "text", record(OTHER_KEY, T3), 7],
                  ["ask", "text", record(OTHER_KEY, T3), "Core words."],
                  ["moved", record(OTHER_KEY, T3), "submitting"], ["records"]],
                 seams={"children": {THREAD: CHILDREN, T2: [], T3: "raise"}}),
        scenario("subagent_lines_past_the_limit", [SUBAGENT],
                 [arm(SUBAGENT), ["ask", "text", core, "x" * 1800], ["ask", "text", core, "é" * 1700],
                  ["ask", "text", core, "y" * 1500]],
                 seams={"children": {THREAD: CHILDREN}}),
        scenario("subagent_five_lines_at_most", [SUBAGENT],
                 [arm(SUBAGENT), text, ["moved", core, "submitting"], text],
                 seams={"children": {THREAD: [child(number) for number in range(1, 8)]}}),
        scenario("subagent_watched_core_words_alone", [SUBAGENT],
                 [arm(SUBAGENT, "shadow"), text, ["moved", core, "submitting"], ["tick"]],
                 measured={"ms": ["pass", "0.155.0"]},
                 seams={"children": {THREAD: CHILDREN}}),
        scenario("subagent_followed_up_once_ms_passed", [SUBAGENT],
                 [arm(SUBAGENT)] + looks(2) + [["records"], text],
                 measured={"ms": ["pass", "0.155.0"]},
                 seams={"recent": [THREAD, T2, T3, T4, T5, T6], "children": {THREAD: CHILDREN, T3: "raise", T4: CHILDREN,
                                                                         T5: CHILDREN, T6: CHILDREN},
                        "turns": {THREAD: turn(kinds=PROGRESS), T2: turn(), T3: turn(), T4: turn(status="failed"),
                                  T5: turn(errored=True), T6: "raise"}}),
        scenario("subagent_waits_for_ms", [SUBAGENT],
                 [arm(SUBAGENT)] + looks(1) + [["records"]],
                 seams={"recent": [THREAD], "children": {THREAD: CHILDREN}, "turns": {THREAD: turn()}}),
        scenario("subagent_withdrawn_when_not_taken", [SUBAGENT, EVERY],
                 [arm(SUBAGENT), arm(EVERY)] + looks(1) + [["records"], ["seam", "own", {THREAD: False}],
                                                            ["seam", "recent", []]]
                 + looks(1, NOW + 61) + [["records"]],
                 measured={"ms": ["pass", "0.155.0"]},
                 seams={"recent": [THREAD], "children": {THREAD: CHILDREN}, "turns": {THREAD: turn()}}),
    ]


def corpus() -> list:
    return empty_corpus() + keep_corpus() + subagent_corpus()


class AdvTurnsContDiff(advturns.AdvTurnsCase, unittest.TestCase):
    """The edition's own continuations, scenario by scenario, against the tag's."""

    def test_scenarios(self):
        self.check_all(corpus())


if __name__ == "__main__":
    unittest.main()

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


MARKER = "marker_free_continuation"
CLIENT = "0a1b2c3d-0002-4000-8000-000000000001"
QUEUED = "0a1b2c3d-0003-4000-8000-000000000001"


def marker_corpus() -> list:
    from rustdiff.advturns import KEY, record
    core = record(KEY, THREAD)

    def send(prompt="Carry on.", thread_id=THREAD, client=CLIENT):
        return ["send", core, thread_id, prompt, client]
    answers = [{"queuedSubmissionId": QUEUED}, {"id": QUEUED}, {"item": {"id": QUEUED}},
               {"queuedSubmission": {"id": QUEUED.upper()}}, {"queuedSubmissionId": "x", "item": {"id": QUEUED}},
               "raise", "timeout", "refused", 5, None, [QUEUED]]
    return [
        scenario("markerfree_points_off_and_on", [MARKER],
                 [["ask", "delivery", core], send(), arm(MARKER), ["ask", "delivery", core],
                  ["ask", "delivery", "a record"], send(), ["pools", core]],
                 seams={"session": {"answers": {"thread/queue/add": [{"queuedSubmissionId": QUEUED}]}}}),
        scenario("markerfree_send_outcomes", [MARKER],
                 [arm(MARKER)] + [send() for _ in answers]
                 + [send(thread_id="nope"), send(""), send("a\x00b"), send("x" * 30001), send("y" * 30000),
                    send("é" * 30000), send(client="nope"), send(client=CLIENT.upper())],
                 seams={"session": {"answers": {"thread/queue/add": answers}}}),
        scenario("markerfree_no_session", [MARKER], [arm(MARKER), send()],
                 seams={"session": {"open": "raise"}}),
        scenario("markerfree_session_will_not_start", [MARKER], [arm(MARKER), send()],
                 seams={"session": {"enter": "raise"}}),
        scenario("markerfree_pools_once_mqp_passed", [MARKER], [arm(MARKER), ["pools", core]],
                 measured={"mqp": ["pass", "0.155.0"]}),
        scenario("markerfree_pools_mqp_failed", [MARKER], [arm(MARKER), ["pools", core]],
                 measured={"mqp": ["fail", "0.155.0"]}),
        scenario("markerfree_watched", [MARKER], [arm(MARKER, "shadow"), ["ask", "delivery", core], send()],
                 seams={"session": {"answers": {"thread/queue/add": [{"id": QUEUED}]}}}),
    ]


GOAL = "goal_continuation"
LIMITED, ACTIVE = "usage_limited", "active"


def goal_corpus() -> list:
    from rustdiff.advturns import KEY, OTHER_KEY, record

    def usage(number, **more):
        return record(KEY, thread(number), **dict({"category": "usage_limit", "holder": "app_free"}, **more))

    def resume(number, still=True):
        return ["resume", usage(number), thread(number), still]
    routes = {thread(31): [LIMITED, LIMITED, ACTIVE], thread(32): LIMITED, thread(33): LIMITED,
              thread(34): [LIMITED, LIMITED, LIMITED], thread(35): [LIMITED, LIMITED, ACTIVE],
              thread(36): LIMITED, thread(37): LIMITED,
              thread(38): [LIMITED, LIMITED, {"goal_id": "other", "status": ACTIVE}],
              thread(39): [LIMITED, LIMITED, ACTIVE], thread(40): [LIMITED, "paused"], thread(41): "raise",
              thread(42): ACTIVE, thread(43): "paused"}
    sends = {thread(51): [LIMITED, LIMITED, ACTIVE], thread(52): [LIMITED, LIMITED, LIMITED],
             thread(53): [LIMITED, LIMITED, ACTIVE], thread(54): [LIMITED, LIMITED, "paused"],
             thread(55): [LIMITED, LIMITED, ACTIVE], thread(56): [LIMITED, LIMITED, ACTIVE],
             thread(57): [LIMITED, "paused"], thread(58): LIMITED}

    def send(number, prompt="Carry on.", client=CLIENT):
        return ["send", usage(number), thread(number), prompt, client]
    return [
        scenario("goal_route_resumed_or_not", [GOAL],
                 [["ask", "unloaded", usage(31)], arm(GOAL)]
                 + [resume(31), resume(32, False), resume(33, "raise"), resume(34), resume(35), resume(36),
                    resume(37), resume(38), resume(39, None), resume(40), resume(41), resume(42),
                    ["ask", "unloaded", usage(43)], ["ask", "unloaded", usage(31, holder="none")],
                    ["ask", "unloaded", record(KEY, thread(31), category="terminal_auth", holder="app_free")],
                    ["ask", "unloaded", record(KEY, "not-a-uuid", category="usage_limit", holder="app_free")],
                    ["ask", "unloaded", "a record"]],
                 seams={"goals": routes,
                        "session": {"answers": {"thread/goal/set": [{}, "no", "no", "timeout", "refused", {}, {}]}}}),
        scenario("goal_route_no_session", [GOAL], [arm(GOAL), resume(31)],
                 seams={"goals": routes, "session": {"open": "raise"}}),
        scenario("goal_held_while_active_and_verified_reset", [GOAL],
                 [arm(GOAL), ["ask", "gates", "thread_available", usage(42), {}],
                  ["clock", NOW + 300], ["ask", "gates", "thread_available", usage(42), {}],
                  ["clock", NOW + 601], ["ask", "gates", "thread_available", usage(42), {}],
                  ["ask", "gates", "thread_available", usage(43), {}],
                  ["ask", "gates", "thread_available", record(OTHER_KEY, thread(42), category="usage_limit"), {}],
                  ["ask", "gates", "thread_available", record(OTHER_KEY, thread(42), category="network_transient"), {}],
                  ["ask", "gates", "known_failure", usage(32, reset_at=NOW), {}],
                  ["ask", "gates", "known_failure", usage(32, reset_at=NOW + 1000), {}],
                  ["ask", "gates", "known_failure", usage(32, reset_at=True), {}],
                  ["ask", "gates", "known_failure", usage(42, reset_at=NOW), {}],
                  ["ask", "gates", "known_failure", usage(41, reset_at=NOW), {}],
                  ["ask", "gates", "global_gates", usage(32), {}]],
                 seams={"goals": routes}),
        scenario("goal_channel_only_once_m2b_passed", [GOAL],
                 [arm(GOAL), ["ask", "sender", usage(58)]],
                 measured={"m2b": ["pass", "0.154.0"]}, seams={"goals": sends}),
        scenario("goal_channel_sends", [GOAL],
                 [arm(GOAL), send(51), send(52), send(53), send(54), send(55), send(56), send(57),
                  send(58, prompt=""), send(58, client="nope"), ["ask", "sender", usage(43)]],
                 measured={"m2b": ["pass", "0.155.0"]},
                 seams={"goals": dict(sends, **{thread(43): "paused"}),
                        "session": {"answers": {"thread/goal/set": [{}, "no", "no", {}, {}, "refused"],
                                                "thread/queue/add": [{"id": QUEUED}, "timeout", "no"]}}}),
        scenario("goal_watched", [GOAL],
                 [arm(GOAL, "shadow"), ["ask", "unloaded", usage(31)],
                  ["ask", "gates", "thread_available", usage(42), {}]],
                 seams={"goals": routes}),
    ]


FOR_OPEN = "queue_for_open"


def for_open_corpus() -> list:
    from rustdiff.advturns import KEY, OTHER_KEY, record

    def free(key=KEY, number=61, **more):
        return record(key, thread(number), **dict({"category": "usage_limit", "holder": "app_free"}, **more))
    third = "c" * 64
    return [
        scenario("for_open_queues_once_and_keeps_for_days", [FOR_OPEN],
                 [["ask", "unloaded", free()], arm(FOR_OPEN), ["ask", "unloaded", free()],
                  ["ask", "unloaded", free(holder="none")], ["ask", "unloaded", free(category="network_transient")],
                  ["ask", "unloaded", free(queued_since=NOW)],
                  ["override", KEY, FOR_OPEN, "queue_for_open"],
                  ["ask", "unloaded", free()], ["ask", "unloaded", free(queued_since=NOW)],
                  ["clock", NOW + 3 * 86400 - 1], ["ask", "unloaded", free(queued_since=NOW)],
                  ["clock", NOW + 3 * 86400], ["ask", "unloaded", free(queued_since=NOW)],
                  ["choose", FOR_OPEN, "days", 7], ["ask", "unloaded", free(queued_since=NOW)],
                  ["clock", NOW + 7 * 86400 + 5], ["ask", "unloaded", free(queued_since=NOW)],
                  ["ask", "unloaded", {"interruption_id": 5, "holder": "app_free"}], ["ask", "unloaded", "a record"],
                  ["ask", "unloaded", free(OTHER_KEY, queued_since=NOW)]]),
        scenario("for_open_beside_an_active_goal", [FOR_OPEN, GOAL],
                 [arm(FOR_OPEN), ["ask", "unloaded", free(number=62)], arm(GOAL),
                  ["ask", "unloaded", free(number=62)], ["ask", "unloaded", free(number=62)],
                  ["ask", "unloaded", free(OTHER_KEY, number=63)], ["ask", "unloaded", free(third, number=64)],
                  ["ask", "unloaded", free(third, number=65)]],
                 seams={"goals": {thread(62): ACTIVE, thread(63): "paused", thread(64): "raise", thread(65): ACTIVE}}),
        scenario("for_open_goal_two_turns", [FOR_OPEN, GOAL],
                 [arm(FOR_OPEN), arm(GOAL), ["ask", "unloaded", free(number=62)]],
                 measured={"mqg": ["fail", "0.155.0"]}, seams={"goals": {thread(62): ACTIVE}}),
        scenario("for_open_goal_one_turn_measured", [FOR_OPEN, GOAL],
                 [arm(FOR_OPEN), arm(GOAL), ["ask", "unloaded", free(number=62)]],
                 measured={"mqg": ["pass", "0.155.0"]}, seams={"goals": {thread(62): ACTIVE}}),
        scenario("for_open_watched", [FOR_OPEN], [arm(FOR_OPEN, "shadow"), ["ask", "unloaded", free()]]),
    ]


OPEN = "open_to_send"


def gates(**named) -> str:
    vector = {"usage": ["PASS", "ok"], "consent": ["UNKNOWN", "not_checked"]}
    vector.update({name: list(gate) for name, gate in named.items()})
    return json.dumps(vector, separators=(",", ":"), sort_keys=True)


def core_row(key, number, state="waiting_for_loaded_thread", gate=("WAIT", "notLoaded"), **more) -> dict:
    row = {"interruption_id": key, "thread_id": thread(number), "state": state, "queue_id": None,
           "gate_eval": gates(thread_available=gate)}
    row.update(more)
    return row


def open_target_corpus() -> list:
    pc = {"idle": 600, "handler": True, "running": True, "link": True}
    a, b, c, d = "a" * 64, "b" * 64, "c" * 64, "d" * 64
    rows = [core_row(a, 71), core_row(b, 72), core_row(c, 73, gate=("WAIT", "desktop_app_unavailable")),
            core_row(d, 74, usage=["WAIT", "x"]), core_row("e" * 64, 75, state="failed"),
            core_row("f" * 64, 76, gate=("WAIT", "unknown"))]
    for_open = [core_row(a, 81, state="queued", queue_id="0a1b2c3d-0003-4000-8000-000000000009",
                         gate=("PASS", "plugged")),
                core_row(b, 82, state="queued", queue_id="0a1b2c3d-0003-4000-8000-000000000008",
                         gate=("PASS", "plugged")),
                core_row(c, 83, state="queued", queue_id="0a1b2c3d-0003-4000-8000-000000000007",
                         gate=("PASS", "plugged"))]
    return [
        scenario("open_one_when_idle_then_settle", [OPEN],
                 [["tick"], arm(OPEN)] + looks(1) + looks(3, NOW + 61)
                 + looks(1, NOW + 700) + [["seam", "core_records", rows[2:]]] + looks(2, NOW + 761)
                 + looks(2, NOW + 3000),
                 core_records=rows, seams={"pc": pc}),
        scenario("open_held_by_the_pc", [OPEN],
                 [arm(OPEN), ["seam", "pc", dict(pc, idle=None)]] + looks(1)
                 + [["seam", "pc", dict(pc, idle=299)]] + looks(1, NOW + 61)
                 + [["seam", "pc", dict(pc, handler=False)]] + looks(1, NOW + 122)
                 + [["seam", "pc", dict(pc, running=None)]] + looks(1, NOW + 183)
                 + [["choose", OPEN, "open_idle_minutes", 2], ["seam", "pc", dict(pc, idle=121, running=False)]]
                 + looks(1, NOW + 244) + [["seam", "pc", dict(pc, link=False)]] + looks(1, NOW + 305)
                 + [["seam", "pc", dict(pc, link="raise")]] + looks(1, NOW + 1000),
                 core_records=rows[:1], seams={"pc": pc}),
        scenario("open_codex_started_for_a_closed_app", [OPEN],
                 [arm(OPEN), ["choose", OPEN, "open_start_codex", 1]] + looks(2),
                 core_records=[rows[2]], seams={"pc": dict(pc, running=False)}),
        scenario("open_queued_for_open_only_when_not_held", [OPEN],
                 [arm(OPEN)] + looks(1) + looks(1, NOW + 700) + looks(1, NOW + 1400),
                 core_records=for_open, seams={"pc": dict(pc, holds={thread(81): True, thread(83): False})}),
        scenario("open_nothing_to_look_at", [OPEN], [arm(OPEN), ["tick"], ["run"]],
                 core_records=rows[3:], seams={"pc": pc}),
        scenario("open_watched", [OPEN], [arm(OPEN, "shadow")] + looks(1), core_records=rows, seams={"pc": pc}),
    ]


STEER = "steer_send"


def steer_corpus() -> list:
    ready = [thread(number) for number in range(91, 100)]
    running = {each: "inProgress" for each in ready}
    started = {each: int(NOW) - 50 for each in ready}
    holders = {each: 1 for each in ready}
    held = {each: True for each in ready}
    seam = {"status": dict(running, **{ready[2]: "completed"}),
            "started": dict(started, **{ready[3]: int(NOW) + 5, ready[4]: None, ready[5]: float(NOW) - 50}),
            "holders": dict(holders, **{ready[6]: 0, ready[7]: None}), "held": dict(held, **{ready[8]: False})}

    def add(number, words="Also check the tests.", client="0a1b2c3d-0004-4000-8000-%012d"):
        return ["steer_add", thread(number), words, client % number]
    return [
        scenario("steer_each_refusal_and_one_write", [PROMPT, STEER],
                 [arm(PROMPT), arm(STEER), ["tick"]] + [add(number) for number in range(90, 100)] + [["tick"], ["run"], ["tick"]],
                 enabled={thread(91): False},
                 seams={"steer": dict(seam, status=dict(seam["status"], **{thread(90): "inProgress"}),
                                      started=dict(seam["started"], **{thread(90): int(NOW) - 50}),
                                      holders=dict(seam["holders"], **{thread(90): 2}),
                                      held=dict(seam["held"], **{thread(90): True}))}),
        scenario("steer_expired_and_turned_off", [PROMPT, STEER],
                 [add(90), arm(PROMPT), arm(STEER), ["clock", NOW + 121], ["tick"], ["run"], add(91),
                  arm(STEER, "off"), ["tick"], ["run"]],
                 seams={"steer": {"status": {thread(91): "inProgress"}}}),
        scenario("steer_pipe_words", [PROMPT, STEER],
                 [arm(PROMPT), arm(STEER)] + [step for word in ("unconfirmed", "held", "no_pipe", "no_client", "refused",
                                                   "version_mismatch", "raise")
                                 for step in (["seam", "steer", {"write": word, "status": {thread(90): "inProgress"},
                                                                 "started": {thread(90): int(NOW) - 50},
                                                                 "holders": {thread(90): 1},
                                                                 "held": {thread(90): True}}],
                                              add(90), ["tick"], ["run"])]),
    ]


PROMPT = "prompt_queue"


def token(number) -> str:
    """The record id the runtime's counted token_hex gives an occurrence: the `number`th asked for in the scenario."""
    return ("%x" % number).rjust(64, "0")


def prompt_corpus() -> list:
    def add(number, words="Run the tests next.", trigger="after_turn", **when):
        return ["prompt_add", thread(number), words, trigger, when]
    later = int(NOW) + 600
    return [
        scenario("prompts_after_turn_in_order", [PROMPT],
                 [add(1), arm(PROMPT), add(1, "Then the docs.", depends=True), add(2), add(3, "x" * 2001),
                  add(4, "y" * 2001), ["records"], ["records"],
                  ["moved", {"record_id": token(1)}, "delivered"], ["records"],
                  ["moved", {"record_id": token(3)}, "superseded"], ["records"]],
                 enabled={thread(2): False}),
        # Longer messages on (long_reset_message armed) waits for S7.2d's reset_message code: its own P2 is asked too.
        scenario("prompts_dependency_failed", [PROMPT],
                 [arm(PROMPT), add(1), add(1, "Then this.", depends=True), ["records"],
                  ["moved", {"record_id": token(1)}, "superseded"], ["records"], ["records"]]),
        scenario("prompts_at_a_time_then_expired", [PROMPT],
                 [arm(PROMPT), add(5, trigger="at_time", at=later), ["records"], ["clock", later], ["records"],
                  ["clock", later + 86400], ["records"], ["records"]]),
        scenario("prompts_recurring_caught_up_and_expired", [PROMPT],
                 [arm(PROMPT), add(6, trigger="recurring", at=later, every="day", occurrences=5),
                  add(7, trigger="recurring", at=later, every="week", occurrences=2),
                  ["clock", later + 3 * 86400 + 100], ["records"], ["clock", later + 5 * 86400], ["records"],
                  ["clock", later + 30 * 86400], ["records"], ["records"]]),
        scenario("prompts_wait_while_a_turn_runs", [PROMPT],
                 [arm(PROMPT)] + [add(number, trigger="at_time", at=later, while_running="wait")
                                  for number in (8, 9, 10)]
                 + [["clock", later], ["records"], ["seam", "running", {}], ["records"],
                    ["clock", later + 2 * 86400], ["records"]],
                 seams={"running": {thread(8): True, thread(9): None}}),
        scenario("prompts_watched_say_what_would_go", [PROMPT],
                 [arm(PROMPT, "shadow"), add(1), add(1, "Then this.", depends=True), add(2),
                  add(8, trigger="at_time", at=later, while_running="wait"), ["records"],
                  ["clock", later], ["records"]],
                 seams={"running": {thread(8): True}}),
        scenario("prompts_no_pictures_no_channel", [PROMPT],
                 [arm(PROMPT), add(1), ["records"], ["ask", "sender", {"record_id": token(1)}],
                  ["ask", "delivery", {"record_id": token(1)}], ["ask", "sender", {"record_id": 5}]]),
    ]


CHAT = "codex_chat"


def chat_corpus() -> list:
    from rustdiff.advturns import KEY, record
    one, two, three, four = "1" * 64, "2" * 64, "3" * 64, "4" * 64

    def add(number, key, words="What changed in the last turn?"):
        return ["chat_add", thread(number), words, key]
    mine = {"record_id": one, "thread_id": thread(1)}
    return [
        scenario("chat_each_conversation_oldest_first", [CHAT],
                 [add(1, one), ["records"], arm(CHAT), add(1, two, "And then?"), add(2, three), add(3, four),
                  ["records"], ["ask", "delivery", mine], ["ask", "delivery", record(KEY, thread(1))],
                  ["send", mine, thread(1), "What changed in the last turn?", CLIENT],
                  ["ask", "sender", record(KEY, thread(1))], ["pools", mine],
                  ["moved", mine, "sent"], ["records"], ["clock", NOW + 181], ["records"]],
                 enabled={thread(3): False},
                 seams={"session": {"answers": {"thread/queue/add": [{"id": QUEUED}]}}}),
        scenario("chat_watched", [CHAT], [arm(CHAT, "shadow"), add(1, one), ["records"], ["ask", "delivery", mine]]),
    ]


RULES, BUDGET, GAVE, SIGN = "structured_rules", "unknown_failure_budget", "codex_gave_up", "sign_in_retry"


def admitted_corpus() -> list:
    from rustdiff.advturns import KEY, OTHER_KEY, record

    counter = [0]

    def failure(category, code=None, status=None, **more):
        """A failure as core puts it at P17: every answer core would carry out offered (`takes`), completed after the
        capability was turned on, under an interruption id of its own (one admission each)."""
        counter[0] += 1
        made = {"category": category, "code": code, "status": status, "interruption_id": "%064x" % counter[0],
                "completed_at": NOW + 1, "form": "tagged", "has_message": False,
                "takes": ["admit", "as_timeout", "as_server_5xx", "as_network_transient"]}
        made.update(more)
        return made

    def admission(found):
        return ["ask", "admission", found]

    def known(category, key=KEY, **more):
        return ["ask", "gates", "known_failure", record(key, THREAD, category=category, **more), {}]
    return [
        scenario("rules_pace_a_named_code", [RULES],
                 [admission(failure("unknown", "weirdError")), arm(RULES),
                  ["rule", "weirdError", None, None, "timeout"], ["rule", "otherError", 500, 599, "server_5xx"],
                  ["rule", "otherError", 400, 450, "network_transient"],
                  admission(failure("unknown", "weirdError")), admission(failure("unknown", "otherError", 503)),
                  admission(failure("unknown", "otherError", 404)), admission(failure("unknown", "otherError", 460)),
                  admission(failure("unknown", "otherError", "503")), admission(failure("unknown", "otherError")),
                  admission(failure("unknown", "badRequest")), admission(failure("server_5xx", "weirdError")),
                  admission(failure("unknown", 7)), admission("not a failure"),
                  known("unknown", "%064x" % 1), known("unknown", "%064x" % 2), known("unknown", "%064x" % 4),
                  ["rule", "thirdError", None, None, "server_5xx"],
                  known("unknown"), ["admit", KEY, RULES, "as_timeout", 1], known("unknown"),
                  ["admit", OTHER_KEY, RULES, "as_server_5xx", 9], known("unknown", OTHER_KEY),
                  known("server_5xx"), ["ask", "gates", "global_gates", record(KEY, THREAD, category="unknown"), {}]]),
        scenario("budget_tries_a_task", [BUDGET],
                 [admission(failure("unknown", "weirdError")), arm(BUDGET),
                  admission(failure("unknown", "weirdError")),
                  admission(failure("unknown", "weirdError", chain={"recovery_attempts": 0})),
                  admission(failure("unknown", "weirdError", chain={"recovery_attempts": 1})),
                  admission(failure("unknown", "weirdError", chain={"recovery_attempts": True})),
                  admission(failure("unknown", "weirdError", chain="a chain")),
                  ["choose", BUDGET, "attempts", 3],
                  admission(failure("unknown", "weirdError", chain={"recovery_attempts": 2})),
                  admission(failure("unknown", "weirdError", chain={"recovery_attempts": 3})),
                  admission(failure("terminal_auth")), known("unknown"), known("terminal_auth"),
                  ["ask", "gates", "known_failure", "a record", {}]]),
        scenario("gave_up_twice_a_task", [GAVE],
                 [arm(GAVE), admission(failure("terminal_failure", "responseTooManyFailedAttempts")),
                  admission(failure("terminal_failure", chain={"recovery_attempts": 1})),
                  admission(failure("terminal_failure", chain={"recovery_attempts": 2})),
                  admission(failure("terminal_failure", chain={})), admission(failure("unknown")),
                  known("terminal_failure"), known("unknown")]),
        scenario("sign_in_once_a_task", [SIGN],
                 [arm(SIGN), admission(failure("terminal_auth", "unauthorized")),
                  admission(failure("terminal_auth", chain={"category": "terminal_auth"})),
                  admission(failure("terminal_auth", chain={"category": "usage_limit"})),
                  admission(failure("terminal_auth", chain={"category": "usage_limit", "categories": None})),
                  admission(failure("terminal_auth", chain="a chain")), admission(failure("unknown")),
                  known("terminal_auth"), known("terminal_failure")]),
        scenario("admitted_watched", [RULES, BUDGET, GAVE, SIGN],
                 [arm(RULES, "shadow"), arm(BUDGET, "shadow"), arm(GAVE, "shadow"), arm(SIGN, "shadow"),
                  admission(failure("unknown", "weirdError")), admission(failure("terminal_auth"))]),
    ]


def corpus() -> list:
    return (empty_corpus() + keep_corpus() + subagent_corpus() + marker_corpus() + goal_corpus()
            + for_open_corpus() + open_target_corpus() + prompt_corpus() + steer_corpus()
            + chat_corpus() + admitted_corpus())


class AdvTurnsContDiff(advturns.AdvTurnsCase, unittest.TestCase):
    """The edition's own continuations, scenario by scenario, against the tag's."""

    def test_scenarios(self):
        self.check_all(corpus())


if __name__ == "__main__":
    unittest.main()

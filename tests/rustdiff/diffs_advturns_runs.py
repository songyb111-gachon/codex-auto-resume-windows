"""S7.2e1: the run kinds and the retry settings against the v0.6.26 tag's (P7-DESIGN 3.2 `diffs_advturns_*`):
headless_run (P16, P8), compact_continue (P17, P3, P16, P8), model_fallback (P16, P8 and its errand) and
codex_retry_settings (P8), each through the runtime over the scenario's fakes (`advturnsworld.py`): the routes handed
core (capability, key, seconds, mode), the run bookkeeping every run kind shares (`follow_up`: the live row, a Stop
handed on, each end journalled, a row no thread follows ended LOST, old rows pruned), the model put back, and the `-c`
settings held in force.

    python -X utf8 tests/rustdiff/run.py --build --reference v0.6.26 --reference-python bundled -k AdvTurnsRunsDiff
"""
from __future__ import annotations

import unittest

from rustdiff import advturns
from rustdiff.advturns import KEY, NOW, OTHER_KEY, OTHER_THREAD, THREAD, arm, record, scenario

TURN = "0a1b2c3d-0002-7000-8000-000000000001"


def unheld_record(key=KEY, thread=THREAD, **fields) -> dict:
    return record(key, thread, **dict({"app": False, "holder": "none", "category": "usage_limit"}, **fields))


def live(capability, key=KEY, thread=THREAD) -> dict:
    return {"key": key, "capability": capability, "thread_id": thread, "started_at": NOW, "ends_by": NOW + 3600}


def turn(status="completed", ordinal=5, kinds=(("contextCompaction", 1),), **more) -> dict:
    made = {"turn_id": TURN, "status": status, "ordinal": ordinal, "kinds": [list(each) for each in kinds],
            "completed_at": int(NOW) - 100}
    made.update(more)
    return made


def headless() -> list:
    cap = "headless_run"
    ask = lambda made: ["ask", "unloaded", made]  # noqa: E731
    return [
        scenario("headless_routes", [cap],
                 [ask(unheld_record()), arm(cap), ask(unheld_record()),
                  ask(unheld_record(app=True)), ask(unheld_record(holder="app")), ask(unheld_record(app=0)),
                  ask(unheld_record(category="terminal_invalid")), ask(unheld_record("not a key")),
                  ask("a record"), ["choose", cap, "ceiling_hours", 3], ask(unheld_record(OTHER_KEY)),
                  ["choose", cap, "ceiling_hours", 7], ask(unheld_record()),
                  ["live", live(cap, OTHER_KEY)], ask(unheld_record()), ["live", None], ask(unheld_record())]),
        scenario("headless_bookkeeping", [cap],
                 [arm(cap), ["live", live(cap)], ["tick"], ["tick"], ["stop_request", KEY], ["tick"],
                  ["told", KEY, cap, "interrupted", None], ["told", OTHER_KEY, "compact_continue", "capped", None],
                  ["live", None], ["tick"],
                  ["live", live(cap, OTHER_KEY, OTHER_THREAD)], ["tick"], ["live", None], ["tick"],
                  ["clock", NOW + 2 * 86400], ["tick"]]),
        scenario("headless_tended_off_and_watched", [cap],
                 [["live", live(cap)], ["tick"], ["told", KEY, cap, "completed", None], ["tick"],
                  arm(cap, "shadow"), ["live", live(cap, OTHER_KEY)], ["tick"], ["live", None], ["tick"],
                  ["live", live("model_fallback")], ["tick"]]),
    ]


def compact() -> list:
    cap = "compact_continue"
    full = dict(category="terminal_invalid")
    failure = {"interruption_id": KEY, "takes": ["admit"], "category": "terminal_invalid",
               "code": "contextWindowExceeded", "completed_at": NOW + 1}
    gate = lambda name, made: ["ask", "gates", name, made, {}]  # noqa: E731
    ask = lambda made: ["ask", "unloaded", made]  # noqa: E731
    return [
        scenario("compact_admits_and_gates", [cap],
                 [arm(cap), ["clock", NOW + 2], ["ask", "admission", failure],
                  ["ask", "admission", dict(failure, interruption_id=OTHER_KEY, code="serverOverloaded")],
                  ["ask", "admission", dict(failure, interruption_id=OTHER_KEY, category="server_5xx")],
                  gate("known_failure", record(ordinal=3, **full)),
                  gate("known_failure", record(OTHER_KEY, ordinal=3, **full)),
                  gate("thread_available", record(ordinal=3, **full)),
                  gate("thread_available", record(ordinal=9, **full)),
                  gate("consent", record(ordinal=3, **full)),
                  gate("known_failure", record(ordinal=3, category="usage_limit")),
                  ["clock", NOW + 86400 + 2], gate("known_failure", record(ordinal=3, **full))],
                 seams={"turns": {THREAD: turn()}}),
        scenario("compact_failed_and_running", [cap],
                 [arm(cap), ["clock", NOW + 2], ["ask", "admission", failure], gate("known_failure", record(ordinal=3, **full)),
                  gate("thread_available", record(ordinal=3, **full)),
                  ask(unheld_record(ordinal=3, **full))],
                 seams={"turns": {THREAD: turn("failed")}}),
        scenario("compact_in_progress", [cap],
                 [arm(cap), ["clock", NOW + 2], ["ask", "admission", failure], gate("known_failure", record(ordinal=3, **full)),
                  gate("thread_available", record(ordinal=3, **full)), ask(unheld_record(ordinal=3, **full))],
                 seams={"turns": {THREAD: turn("inProgress", kinds=(("contextCompaction", 1), ("reasoning", 2)))}}),
        scenario("compact_routes", [cap],
                 [arm(cap), ask(unheld_record(ordinal=3, **full)), ask(unheld_record(ordinal=7, **full)),
                  ask(unheld_record(OTHER_KEY, OTHER_THREAD, ordinal=1, **full)),
                  ask(unheld_record(ordinal=None, **full)), ask(unheld_record(ordinal=3)),
                  ask(unheld_record("c" * 64, "0a1b2c3d-0001-7000-8000-000000000003", ordinal=1, **full)),
                  ["live", live("headless_run")], ask(unheld_record(ordinal=3, **full)), ["live", None],
                  ["tick"], ["told", KEY, cap, "completed", None], ["tick"]],
                 seams={"turns": {THREAD: turn(), OTHER_THREAD: turn(kinds=(("agentMessage", 1),)),
                                  "0a1b2c3d-0001-7000-8000-000000000003": "raise"}}),
        scenario("compact_kinds", [cap],
                 [arm(cap), ask(unheld_record(ordinal=3, **full)),
                  ask(unheld_record(OTHER_KEY, OTHER_THREAD, ordinal=3, **full))],
                 seams={"turns": {THREAD: turn(kinds=(("reasoning", 2), ("contextCompaction", 0))),
                                  OTHER_THREAD: turn("interrupted")}}),
        scenario("compact_raises_on_an_ordinal_it_cannot_compare", [cap],
                 [arm(cap), ask(unheld_record(ordinal="three", **full)), ask(unheld_record(ordinal=3, **full)),
                  ["ask", "admission", "not a failure"]],
                 seams={"turns": {THREAD: turn()}}),
    ]


def fallback() -> list:
    cap = "model_fallback"
    at = dict(category="server_5xx", turn_id=TURN, chain_continuations=2)
    ask = lambda made: ["ask", "unloaded", made]  # noqa: E731
    codes = {"%s %s" % (THREAD, TURN): "serverOverloaded", "%s %s" % (OTHER_THREAD, TURN): "other"}
    resumed = {"model": "gpt-own"}
    return [
        scenario("fallback_routes", [cap],
                 [ask(unheld_record(**at)), arm(cap), ask(unheld_record(**at)),
                  ask(unheld_record(**dict(at, chain_continuations=1))),
                  ask(unheld_record(**dict(at, chain_continuations=None))),
                  ask(unheld_record(OTHER_KEY, OTHER_THREAD, **at)),
                  ask(unheld_record(**dict(at, category="terminal_invalid"))),
                  ["choose", cap, "attempts", 1], ask(unheld_record(**dict(at, chain_continuations=1))),
                  ask({"interruption_id": KEY, "app": False, "holder": "none", "category": "server_5xx",
                       "chain_continuations": 3}),
                  ["live", live("headless_run", OTHER_KEY)], ask(unheld_record(**at))],
                 seams={"codes": codes}),
        scenario("fallback_chain_that_cannot_compare", [cap],
                 [arm(cap), ask(unheld_record(**dict(at, chain_continuations="two"))), ask(unheld_record(**at))],
                 seams={"codes": codes}),
        scenario("fallback_puts_the_model_back", [cap],
                 [arm(cap), ["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500], ["tick"], ["run"],
                  ["tick"], ["clock", NOW + 601], ["tick"]],
                 seams={"session": {"answers": {"thread/resume": [{"model": "gpt-other"}, resumed]}}}),
        scenario("fallback_restore_refused", [cap],
                 [arm(cap), ["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500], ["tick"], ["run"],
                  ["clock", NOW + 300], ["tick"], ["clock", NOW + 700], ["tick"], ["run"]],
                 seams={"session": {"answers": {"thread/resume": [{"model": "gpt-other"}],
                                                "thread/settings/update": ["raise", {}]}}}),
        scenario("fallback_restore_not_unheld", [cap],
                 [arm(cap), ["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500], ["tick"], ["run"],
                  ["tick"]],
                 seams={"unheld": False}),
        scenario("fallback_restore_session_fails", [cap],
                 [arm(cap), ["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500], ["tick"], ["run"],
                  ["clock", NOW + 700], ["tick"]],
                 seams={"session": {"enter": "raise"}}),
        scenario("fallback_told_restored_or_not", [cap],
                 [arm(cap), ["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500],
                  ["owe", OTHER_KEY, cap, OTHER_THREAD, "gpt-two", NOW - 100, NOW + 3500],
                  ["told", KEY, cap, "completed", True], ["told", OTHER_KEY, cap, "failed", False],
                  ["live", live(cap, "c" * 64)], ["tick"], ["live", None], ["tick"], ["run"]],
                 seams={"session": {"answers": {"thread/resume": [{"model": "gpt-two"}]}}}),
        scenario("fallback_tended_off", [cap],
                 [["owe", KEY, cap, THREAD, "gpt-own", NOW - 100, NOW + 3500], ["tick"], ["run"]],
                 seams={"session": {"answers": {"thread/resume": [resumed]}}}),
    ]


def retries() -> list:
    cap = "codex_retry_settings"
    fits = {"config": {"model_provider": "openai", "model_providers": {"mine": {}}}}
    chatgpt = {"account": {"type": "ChatGPT", "email": "person@example.com"}}
    return [
        scenario("retries_held_while_it_fits", [cap],
                 [arm(cap), ["tick"], ["retry_settings"], ["clock", NOW + 100], ["retry_settings"],
                  ["clock", NOW + 200], ["retry_settings"], ["tick"], ["retry_settings"],
                  ["choose", cap, "attempts", 12], ["tick"], ["retry_settings"],
                  ["clock", NOW + 900], ["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {"config/read": [fits, {"config": {"openai_base_url": "x"}}],
                                                "account/read": [chatgpt]}}}),
        scenario("retries_never_on_another_sign_in", [cap],
                 [arm(cap), ["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {"config/read": [{"config": {}}],
                                                "account/read": [{"account": {"type": "apiKey"}}]}}}),
        scenario("retries_never_with_a_provider_of_its_id", [cap],
                 [arm(cap), ["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {
                     "config/read": [{"config": {"model_providers": {"codex_auto_resume_retries": {}}}}],
                     "account/read": [chatgpt]}}}),
        scenario("retries_a_look_that_fails", [cap],
                 [arm(cap), ["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {"config/read": ["raise"]}}}),
        scenario("retries_other_provider_and_shapes", [cap],
                 [arm(cap), ["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {"config/read": [{"config": {"model_provider": "azure"}}],
                                                "account/read": [chatgpt]}}}),
        scenario("retries_off_holds_nothing", [cap],
                 [["tick"], ["retry_settings"]],
                 seams={"session": {"answers": {"config/read": [fits], "account/read": [chatgpt]}}}),
    ]


def corpus() -> list:
    return headless() + compact() + fallback() + retries()


class AdvTurnsRunsDiff(advturns.AdvTurnsCase, unittest.TestCase):
    """The run kinds and the retry settings, scenario by scenario, against the tag's."""

    def test_scenarios(self):
        self.check_all(corpus())


if __name__ == "__main__":
    unittest.main()

"""The v0.6.19 groundwork's probes (plans/v0619-design/D-groundwork.md section 5): MTOK, MOPEN, MAL, MWAKE and MHK,
and M4B's start - what the measurement session runs while the stage's capabilities are built. Each is driven here
through fakes alone: a fake session, a synthetic Codex home, and fake hands for the link, the power read, the wake
timer and the engine on a scratch home - nothing opens a real Codex, a link, a timer or a process. Each record is
written through evidence.build, so each observation is content-free or the run fails.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend, FakeSession  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.runtime import Runtime  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

NEW = (Measurement.MTOK, Measurement.MOPEN, Measurement.MAL, Measurement.MWAKE, Measurement.MHK, Measurement.M4B)
SENTINEL = "PRIVATE-WORDS-5c1e"
ADDRESS = "someone@example.com"


def token_line(total, *, keys=("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")):
    totals = dict({key: 1 for key in keys}, total_tokens=total)
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": totals}}}


def sequence(*replies):
    """A reply that is each of `replies` in turn, then the last one again."""
    left = list(replies)
    return lambda params: left.pop(0) if len(left) > 1 else left[0]


class V019Case(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_MOPEN_SECONDS", 0.2), ("_MOPEN_POLL_SECONDS", 0.01), ("_MAL_SECONDS", 0.5),
                            ("_MAL_POLL_SECONDS", 0.0)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions = []
        self.homes = []

    def factory(self, replies):
        def made(measured):
            self.sessions.append(FakeSession(measured, replies))
            return self.sessions[-1]
        return made

    def run_one(self, measurement, *, replies=None, hands=None, backend=None, thread=THREAD):
        summary = measure.run(measurement, session_factory=self.factory(replies or {}), backend=backend or Backend(),
                              versions=VERSIONS, thread=thread, clock=lambda: 1_800_000_000.0, directory=self.dir,
                              hands=hands)
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn(ADDRESS, text)
        self.assertNotIn(THREAD, text)
        return json.loads(text)

    def scratch_cli(self, features=None, schema=()):
        """A fake engine on a scratch home: `features list` prints `features`; the schema generation writes `schema`
        (file name, document) into its --out folder. Every home it is given is kept, to be looked at afterwards."""
        def run(home, arguments):
            self.homes.append(Path(home))
            if arguments[:2] == ("features", "list"):
                return features
            if arguments[:3] == measure._SCHEMA_ARGUMENTS:
                out = Path(arguments[3])
                for name, document in schema:
                    (out / name).write_text(json.dumps(document), encoding="utf-8")
                return ""
            return None
        return run


class AllowListTests(V019Case):
    def test_every_new_measurement_has_its_methods_and_a_probe(self):
        """Fails with the probes reverted: the ids have no probe and no allow-list."""
        for measurement in NEW:
            with self.subTest(measurement):
                self.assertIn(measurement, measure.PROBES)
                self.assertIn(measurement, protocol.MEASUREMENT_METHODS)
        self.assertEqual(protocol.methods_for(Measurement.MOPEN), {"initialize", "initialized"},
                         "no method: who holds a conversation is core's loaded check, not a list from our session")
        self.assertEqual(protocol.methods_for(Measurement.MAL), {"initialize", "initialized", "account/read"})
        for measurement in (Measurement.MTOK, Measurement.MWAKE, Measurement.MHK, Measurement.MOPEN):
            with self.subTest(measurement), self.assertRaises(measure.EvidenceUnavailable):
                measure.Context(measurement, session_factory=self.factory({})).open()

    def test_a_hand_not_given_does_nothing(self):
        ctx = measure.Context(Measurement.MWAKE)
        self.assertEqual((ctx.open_link(THREAD), ctx.power_look(), ctx.wake_after(1, 1), ctx.scratch_cli("x", ())),
                         (False, {}, {}, None))
        broken = measure.Context(Measurement.MWAKE, hands={"power": lambda: 1 / 0})
        self.assertEqual(broken.power_look(), {})


class TokenTests(V019Case):
    def home(self, lines, *, tokens_used=30, name="codex"):
        home = (self.dir / name).resolve()
        (home / "sessions").mkdir(parents=True)
        rollout = home / "sessions" / ("rollout-%s.jsonl" % THREAD)
        meta = {"type": "session_meta", "payload": {"id": THREAD, "originator": "codex-tui", "source": "cli"}}
        said = {"type": "response_item", "payload": {"type": "message", "content": SENTINEL}}
        empty = {"type": "event_msg", "payload": {"type": "token_count", "info": None}}
        rollout.write_text("".join(json.dumps(line) + "\n" for line in [meta, said, empty, *lines]), encoding="utf-8")
        with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, source TEXT, thread_source TEXT, "
                       "history_mode TEXT, tokens_used INTEGER, title TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?, 'cli', 'user', 'paginated', ?, ?)",
                       (THREAD, str(rollout), tokens_used, SENTINEL))
            db.commit()
        return home

    SCHEMA = (("ClientRequest.json", {"oneOf": [{"properties": {"method": {"enum": ["thread/tokenUsage/read"]}}}]}),)

    def test_two_counts_with_every_kind_never_decreasing_pass(self):
        home = self.home([token_line(10), token_line(30)])
        record = self.run_one(Measurement.MTOK, backend=Backend(home), hands={"scratch_cli": self.scratch_cli(
            schema=self.SCHEMA)})
        self.assertEqual(record["verdict"], "pass", record)
        observed = record["observed"]
        self.assertEqual((observed["token_events"], observed["keys_present"], observed["totals_monotone"],
                          observed["tokens_used_column"], observed["tokens_used_matches"], observed["schema_read"],
                          observed["thread_token_read_listed"]), (2, True, True, True, True, True, True))
        self.assertTrue(self.homes and all(not path.exists() for path in self.homes), "the scratch home is removed")
        self.assertTrue(all(home not in path.parents and path != home for path in self.homes), "never the person's")

    def test_totals_that_decrease_or_lack_a_kind_fail(self):
        for name, lines in (("down", [token_line(30), token_line(10)]),
                            ("short", [token_line(10), token_line(20, keys=("input_tokens",))])):
            with self.subTest(name):
                record = self.run_one(Measurement.MTOK, backend=Backend(self.home(lines, name=name)),
                                      hands={"scratch_cli": self.scratch_cli()})
                self.assertEqual(record["verdict"], "fail", record)
                self.assertIs(record["observed"]["schema_read"], False)

    def test_fewer_than_two_counts_or_no_conversation_is_left_to_the_person(self):
        record = self.run_one(Measurement.MTOK, backend=Backend(self.home([token_line(10)], tokens_used=None)))
        self.assertEqual((record["verdict"], record["observed"]["token_events"],
                          record["observed"]["tokens_used_matches"]), ("blocked", 1, False))
        called = []
        record = self.run_one(Measurement.MTOK, thread=None, hands={"scratch_cli": lambda *a: called.append(a)})
        self.assertEqual((record["verdict"], called), ("blocked", []))


class OpenTests(V019Case):
    """MOPEN times the load by the writer lock's holder count alone (measure._lock_users, Restart Manager, ~0.5 s a read)
    and checks once, after the count first reaches one, with core's identity pairing and loaded check (measure._look,
    ~15 s on codex-cli 0.165) that the holder is the app. It opens no session. The first run (2026-10-29) timed it with
    the full look and could never say "under ten"; by hand the app took the lock 13.4 s after the link."""

    def counting(self, *counts, app=True):
        """`_lock_users` answering each of `counts` in turn (the last again); `_look` answering (`app`, 1) and counting its
        calls into `self.identity_checks`."""
        left = list(counts)
        self.identity_checks = []

        def look(ctx, thread):
            self.identity_checks.append(thread)
            return app, 1
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(measure, "_lock_users",
                                         lambda ctx, thread: left.pop(0) if len(left) > 1 else left[0]))
        stack.enter_context(patch.object(measure, "_look", look))
        return stack

    def test_loaded_soon_after_its_link_is_left_to_the_person_for_the_window(self):
        opened = []
        with self.counting(0, 0, 0, 1):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: opened.append(thread) or True})
        self.assertEqual(record["verdict"], "blocked", record)
        self.assertEqual(opened, [THREAD], "opened once")
        observed = record["observed"]
        self.assertEqual((observed["link_opened"], observed["loaded_seconds"], observed["held_before"],
                          observed["loaded_by_app"], observed["holders"]), (True, "under_2s", False, True, 1))
        self.assertEqual(self.sessions, [], "no session, so no list of ours is asked")

    def test_the_slow_identity_check_is_made_once_and_not_counted_in_the_time(self):
        """Fails with the full look in the polling loop: the load would be timed in tens of seconds."""
        import time

        def slow_look(ctx, thread):
            self.identity_checks.append(thread)
            time.sleep(0.5)                         # 2.5 times the limit: the real one is ~15 s against 30
            return True, 1
        with self.counting(0, 0, 1), patch.object(measure, "_look", slow_look):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: True})
        self.assertEqual(len(self.identity_checks), 1, "once, after the count first reached one")
        self.assertEqual((record["verdict"], record["observed"]["loaded_seconds"]), ("blocked", "under_2s"))

    def test_the_before_look_is_the_fast_count_not_the_full_look(self):
        with self.counting(1):
            self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: True})
        self.assertEqual(self.identity_checks, [], "a conversation already held is never given to the slow check")

    def test_never_held_within_the_limit_is_a_fail_and_the_identity_is_never_checked(self):
        with self.counting(0):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: True})
        self.assertEqual((record["verdict"], record["observed"]["loaded_seconds"], record["observed"]["holders"]),
                         ("fail", "never", 0))
        self.assertEqual(self.identity_checks, [])

    def test_a_holder_that_is_not_the_app_stays_with_the_person(self):
        with self.counting(0, 1, app=False):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: True})
        observed = record["observed"]
        self.assertEqual((record["verdict"], observed["loaded_by_app"], observed["holders"]), ("blocked", False, 1))
        self.assertEqual(len(self.identity_checks), 1)
        self.assertIn("not find it to be the app", record["note"])

    def test_one_something_holds_already_is_never_opened(self):
        opened = []
        with self.counting(1):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: opened.append(thread) or True})
        self.assertEqual((record["verdict"], record["observed"]["held_before"], opened), ("blocked", True, []))

    def test_who_holds_it_unreadable_opens_nothing(self):
        opened = []
        with self.counting(None):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: opened.append(thread) or True})
        self.assertEqual((record["verdict"], record["observed"]["holders_read"], opened), ("blocked", False, []))

    def test_a_link_not_handed_over_or_no_conversation_is_left_to_the_person(self):
        with self.counting(0):
            record = self.run_one(Measurement.MOPEN, hands={"open_link": lambda thread: False})
            self.assertEqual((record["verdict"], record["observed"]["link_opened"]), ("blocked", False))
            record = self.run_one(Measurement.MOPEN, thread=None)
        self.assertEqual((record["verdict"], self.sessions), ("blocked", []), "no session for none")


class AccountTests(V019Case):
    @staticmethod
    def signed(plan):
        return {"account": {"type": "chatgpt", "email": ADDRESS, "planType": plan}, "requiresOpenaiAuth": True}

    def test_a_sign_out_and_in_is_seen_and_the_app_left_to_the_person(self):
        replies = {"account/read": sequence(self.signed("plus"), {"account": None}, self.signed("pro"))}
        record = self.run_one(Measurement.MAL, replies=replies)
        self.assertEqual(record["verdict"], "blocked", record)
        observed = record["observed"]
        self.assertEqual((observed["plan_before"], observed["signed_out_seen"], observed["signed_in_again_seen"],
                          observed["plan_after"]), ("plus", True, True, "pro"))

    def test_a_plan_codex_names_otherwise_is_other_and_none_seen_is_said(self):
        record = self.run_one(Measurement.MAL, replies={"account/read": self.signed("galaxy")})
        observed = record["observed"]
        self.assertEqual((observed["plan_before"], observed["signed_out_seen"], observed["signed_in_again_seen"]),
                         ("other", False, False))

    def test_signed_out_at_the_start_is_left_to_the_person(self):
        record = self.run_one(Measurement.MAL, replies={"account/read": {"account": None}})
        self.assertEqual((record["verdict"], record["observed"]["signed_in_before"]), ("blocked", False))


class WakeTests(V019Case):
    POWER = {"wake_ac": 1, "wake_dc": 0, "on_battery": False, "modern_standby": True, "lid_present": True}

    def wake(self, **woke):
        asked = []
        found = dict({"set": True, "fired": True, "slept_seconds": 150.0, "late_seconds": 4.0}, **woke)
        record = self.run_one(Measurement.MWAKE, hands={"power": lambda: dict(self.POWER),
                                                        "wake_after": lambda *a: asked.append(a) or found})
        self.assertEqual(asked, [(measure._MWAKE_SECONDS, measure._MWAKE_BOUND)])
        return record

    def test_asleep_and_woken_by_the_timer_passes(self):
        record = self.wake()
        self.assertEqual(record["verdict"], "pass", record)
        self.assertEqual(record["observed"], dict(record["observed"], wake_timers_ac=1, wake_timers_dc=0,
                                                  power_source="ac", modern_standby=True, lid_present=True,
                                                  timer_set=True, timer_fired=True, slept=True, woke_on_time=True))

    def test_woken_long_after_the_timer_fails(self):
        self.assertEqual(self.wake(late_seconds=400.0)["verdict"], "fail")
        self.assertEqual(self.wake(fired=False, late_seconds=None)["verdict"], "fail")

    def test_never_asleep_or_no_timer_is_left_to_the_person(self):
        self.assertEqual(self.wake(slept_seconds=3.0)["verdict"], "blocked")
        self.assertEqual(self.wake(set=False)["verdict"], "blocked")
        record = self.run_one(Measurement.MWAKE)
        self.assertEqual((record["verdict"], record["observed"]["timer_set"], record["observed"]["power_source"]),
                         ("blocked", False, "unknown"))


class HookTests(V019Case):
    SCHEMA = (("HookEventName.json", {"enum": ["PreToolUse", "Stop", "SessionStart"]}),
              ("Hooks.json", {"definitions": {
                  "HookSource": {"oneOf": [{"const": "user"}, {"const": "plugin"}]},
                  "StopHookInput": {"properties": {"session_id": {}, "turnId": {}, "hook_event_name": {},
                                                   "stop_hook_active": {}, "cwd": {}}},
                  "StopHookOutput": {"properties": {"decision": {"enum": ["block"]}, "reason": {}}}}}))
    FEATURES = "plugin_hooks                 under development  true\nanother_feature  stable  false\n"

    def test_a_stop_event_for_plugin_hooks_passes_in_counts_and_memberships(self):
        record = self.run_one(Measurement.MHK, hands={"scratch_cli": self.scratch_cli(self.FEATURES, self.SCHEMA)})
        self.assertEqual(record["verdict"], "pass", record)
        observed = record["observed"]
        self.assertEqual({key: observed[key] for key in ("plugin_hooks_listed", "plugin_hooks_on", "hook_event_names",
                                                         "stop_event", "hook_sources", "plugin_source",
                                                         "stop_input_keys", "input_session_id", "input_turn_id",
                                                         "input_transcript_path", "decision_words", "decision_block")},
                         {"plugin_hooks_listed": True, "plugin_hooks_on": True, "hook_event_names": 3,
                          "stop_event": True, "hook_sources": 2, "plugin_source": True, "stop_input_keys": 5,
                          "input_session_id": True, "input_turn_id": True, "input_transcript_path": False,
                          "decision_words": 1, "decision_block": True})
        self.assertTrue(self.homes and all(not path.exists() for path in self.homes), "the scratch home is removed")

    def test_no_stop_event_or_no_feature_fails(self):
        without = (("HookEventName.json", {"enum": ["PreToolUse"]}),)
        record = self.run_one(Measurement.MHK, hands={"scratch_cli": self.scratch_cli(self.FEATURES, without)})
        self.assertEqual((record["verdict"], record["observed"]["stop_event"]), ("fail", False))
        record = self.run_one(Measurement.MHK, hands={"scratch_cli": self.scratch_cli("other  stable  true",
                                                                                      self.SCHEMA)})
        self.assertEqual((record["verdict"], record["observed"]["plugin_hooks_listed"]), ("fail", False))

    def test_an_engine_that_cannot_run_is_left_to_the_person(self):
        self.assertEqual(self.run_one(Measurement.MHK)["verdict"], "blocked")
        record = self.run_one(Measurement.MHK, hands={"scratch_cli": self.scratch_cli(None, self.SCHEMA)})
        self.assertEqual((record["verdict"], record["observed"]["features_read"]), ("blocked", False))


class M4BTests(V019Case):
    def test_it_lists_the_hooks_and_leaves_the_rest_to_the_person(self):
        record = self.run_one(Measurement.M4B, replies={"hooks/list": {"data": []}})
        self.assertEqual((record["verdict"], record["observed"]["hooks_listed"]), ("blocked", True))


class RuntimeTests(ac.AdvancedCase):
    def test_the_dashboards_runtime_hands_its_probes_the_live_hands_or_a_tests(self):
        evidence = Path(self.home).parent / "evidence"
        evidence.mkdir(parents=True)
        given = {"power": lambda: {}, "wake_after": lambda *a: {"set": True, "fired": True, "slept_seconds": 90.0,
                                                                  "late_seconds": 1.0}}
        runtime = Runtime(self.paths, measure_session_factory=lambda measured: None, measure_backend=Backend(),
                          measure_cli=lambda arguments: None, measure_ipc=dict, measure_hands=given,
                          evidence_dir=evidence, **self.options())
        self.addCleanup(runtime.state.close)
        self.assertEqual(runtime.run_measurement(Measurement.MWAKE)["verdict"], "pass")
        live = Runtime(self.paths, measure_session_factory=lambda measured: None, measure_backend=Backend(),
                       measure_cli=lambda arguments: None, measure_ipc=dict, evidence_dir=evidence, **self.options())
        self.addCleanup(live.state.close)
        with patch.object(measure, "live_hands", return_value={"marker": True}) as built, \
                patch.object(measure, "run", return_value={}) as ran:
            live.run_measurement(Measurement.MWAKE)
        built.assert_called_once()
        self.assertEqual(ran.call_args.kwargs["hands"], {"marker": True})


if __name__ == "__main__":
    unittest.main()

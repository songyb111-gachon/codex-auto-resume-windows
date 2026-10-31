"""Another model when one is at capacity (v0.6.16-beta.4): only for a server error Codex coded serverOverloaded, only
after the person's Attempts, only where nothing holds the conversation while Codex is closed - never for a usage,
rate, sign-in or billing failure - one turn on the headless route in fallback mode, and a model Codex would not put
back journalled in a closed word.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codexsim import CodexHome, new_id  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume_advanced import registry  # noqa: E402
from codex_auto_resume_advanced.codex import headless  # noqa: E402
from codex_auto_resume_advanced.codex.turns import Turns  # noqa: E402
from codex_auto_resume_advanced.engine.fallback import CAPABILITY, NOT_RESTORED, ModelFallback  # noqa: E402
from codex_auto_resume_advanced.registry import MODEL_FALLBACK  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, Measurement, OptionKey,  # noqa: E402
                                                   Verdict)
from test_engine import T1  # noqa: E402
from test_advanced_headless import THREAD, RouteCase  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine.fallback import RESTORE_EVERY  # noqa: E402
from codex_auto_resume_advanced.vocabulary import RunEnd  # noqa: E402

KEY = "%064x" % 9
TURN = "11111111-2222-3333-4444-555555555555"


class Codes:
    def __init__(self, code):
        self.code = code

    def turn_code(self, thread_id, turn_id):
        return self.code


class Scoped:
    def __init__(self, attempts=None):
        self.attempts, self.counted = attempts, []

    def options(self):
        return {} if self.attempts is None else {OptionKey.ATTEMPTS: self.attempts}

    def count(self, code):
        self.counted.append(code)


class CodeTests(unittest.TestCase):
    def code(self, error="serverOverloaded", attempts=None, follower=None):
        made = ModelFallback(None, turns=Codes(error), session=lambda capability: None,
                             follower=follower or headless.Follower(poll=0.01), app_running=lambda: False)
        made.bind(Scoped(attempts))
        return made

    @staticmethod
    def record(**changes):
        return dict({"interruption_id": KEY, "thread_id": T1, "turn_id": TURN, "category": "server_5xx",
                     "chain_continuations": 2, "holder": "none", "app": False}, **changes)

    def test_at_capacity_after_the_attempts_it_runs_one_turn_on_the_default_model(self):
        """Fails with the route's mode reverted: the turn would run on the conversation's own model."""
        run = self.code().unloaded(self.record())
        self.assertIsInstance(run, headless.HeadlessRun)
        self.assertEqual(run.mode, "fallback")

    def test_not_before_the_attempts_chosen(self):
        self.assertIs(self.code().unloaded(self.record(chain_continuations=1)), DEFER)
        self.assertIsNot(self.code(attempts=1).unloaded(self.record(chain_continuations=1)), DEFER)
        self.assertIs(self.code(attempts=3).unloaded(self.record(chain_continuations=2)), DEFER)

    def test_never_another_failure_nor_another_server_error(self):
        for category in ("usage_limit", "rate_limit_transient", "terminal_auth", "terminal_failure", "unknown"):
            self.assertIs(self.code().unloaded(self.record(category=category)), DEFER, category)
        for error in ("internalServerError", None, "usageLimitExceeded"):
            self.assertIs(self.code(error).unloaded(self.record()), DEFER, error)

    def test_only_where_nothing_holds_it_and_codex_is_closed(self):
        for where in ({"holder": "session", "app": True}, {"holder": "app_free", "app": True},
                      {"holder": "none", "app": True}):
            self.assertIs(self.code().unloaded(self.record(**where)), DEFER, where)

    def test_a_model_not_put_back_is_journalled_in_a_closed_word(self):
        class Ended:
            def live(self):
                return None

            def drain(self, capability):
                return [{"key": KEY, "end": "completed", "model_restored": False}]

        class Runs:
            def live(self):
                return []

            def ended(self, key, end):
                pass
        made = self.code(follower=Ended())
        made._scoped.runs = Runs()
        made.tick(None)
        self.assertEqual(made._scoped.counted, ["completed", NOT_RESTORED])


class RestoreEveryPathTests(RouteCase):
    """The conversation's own model is stored as owed back before turn/start, and put back on every path - not only
    the follower's: a turn/start that did not answer, answered no turn, or was refused."""
    LISTED = {"model/list": {"data": [{"model": "the-default-model", "isDefault": True}]}}

    def fallback(self, owe=None, **replies):
        route = self.route("model_fallback", mode=headless.FALLBACK, replies=dict(self.LISTED, **replies))
        route.owe = owe
        return route

    def test_a_turn_start_that_never_answers_or_answers_no_turn_still_puts_the_model_back(self):
        """Fails with the route's own restore reverted: the session closed on the default model, nothing journalled."""
        for name, reply, end in (("no answer", AdapterError("protocol_timeout"), RunEnd.LOST),
                                 ("not a turn's id", {"turn": {"id": "x"}}, RunEnd.LOST),
                                 ("refused", protocol._refused_by_codex("turn/start", -32600), RunEnd.FAILED)):
            with self.subTest(name):
                self.servers = []
                self.resume(self.fallback(**{"turn/start": reply}))
                calls = self.servers[0].calls
                self.assertIn(("thread/settings/update", {"threadId": THREAD, "model": "the-threads-model"}), calls)
                self.assertTrue(self.servers[0].closed)
                (ended,) = self.follower.drain("model_fallback")
                self.assertEqual((ended["end"], ended["model_restored"]), (str(end), True))

    def test_the_model_is_owed_before_turn_start_and_no_turn_starts_where_it_could_not_be(self):
        """Fails with the debt written after turn/start, or not at all: a watcher stopped mid-turn left nothing."""
        owed = []

        def owe(thread_id, model, seconds):
            owed.append((thread_id, model, [method for method, _ in self.servers[-1].calls]))
            return True
        self.assertEqual(self.resume(self.fallback(owe))["outcome"], "ran")
        self.ended()
        self.assertEqual(owed[0][:2], (THREAD, "the-threads-model"))
        self.assertNotIn("turn/start", owed[0][2])
        for refusing in (lambda *unused: False, lambda *unused: 1 / 0):
            self.servers = []
            self.assertEqual(self.resume(self.fallback(refusing))["outcome"], "not_started")
            self.assertNotIn("turn/start", self.servers[0].methods())
            self.assertNotIn("thread/settings/update", self.servers[0].methods())


class OwedTests(unittest.TestCase):
    """A model still owed after a restart - or one Codex refused to put back - is P8's errand: put back with the one
    write inside core's errand guard, read back, and the debt cleared."""

    class Runs:
        def __init__(self, owed):
            self.owed_rows, self.cleared, self.ended_as = owed, [], []

        def live(self):
            return []

        def ended(self, key, end):
            self.ended_as.append((key, end))

        def prune(self, before):
            pass

        def owed(self):
            return [row for row in self.owed_rows if row["interruption_id"] not in self.cleared]

        def restored(self, key):
            self.cleared.append(key)

    class Server:
        def __init__(self, model_after):
            self.calls, self.model_after, self.closed = [], model_after, False

        def __enter__(self):
            return self

        def __exit__(self, *unused):
            self.closed = True

        def call(self, method, params=None):
            self.calls.append((method, params))
            return {"model": self.model_after} if method == "thread/resume" else {}

    def code(self, *, model_after="its-own", unheld=True, live=None, ended=()):
        class Follower:
            def live(self):
                return live

            def drain(self, capability):
                return list(ended)
        self.servers = []

        def opening(capability):
            self.servers.append(self.Server(model_after))
            return self.servers[-1]
        made = ModelFallback(None, turns=Codes("serverOverloaded"), session=opening, follower=Follower(),
                             app_running=lambda: False, unheld_now=lambda thread_id: unheld)
        scoped = Scoped()
        scoped.runs = self.Runs([{"interruption_id": KEY, "thread_id": T1, "restore_model": "its-own"}])
        scoped.now = lambda: 1000.0
        made.bind(scoped)
        return made

    @staticmethod
    def guard(permitted=True):
        from contextlib import nullcontext
        return lambda: nullcontext(permitted)

    def test_after_a_restart_the_owed_model_is_put_back_and_read_back(self):
        """Fails with the errand reverted: a watcher stopped mid-turn left the conversation on the default model."""
        made = self.code()
        errand = made.tick(None)
        self.assertIsNot(errand, DEFER)
        errand.run(self.guard())
        self.assertEqual([method for method, _ in self.servers[0].calls],
                         ["thread/resume", "thread/settings/update", "thread/resume"])
        self.assertEqual(self.servers[0].calls[1][1], {"threadId": T1, "model": "its-own"})
        self.assertEqual(made._scoped.runs.cleared, [KEY])
        self.assertIs(made.tick(None), DEFER, "owed no more")

    def test_never_while_a_run_is_live_codex_runs_or_the_guard_refuses(self):
        self.assertIs(self.code(live={"key": KEY, "capability": CAPABILITY}).tick(None), DEFER)
        made = self.code(unheld=False)
        made.tick(None).run(self.guard())
        self.assertEqual(self.servers, [])
        made = self.code()
        made.tick(None).run(self.guard(False))
        self.assertNotIn("thread/settings/update", [method for method, _ in self.servers[0].calls])
        self.assertEqual(made._scoped.runs.cleared, [])

    def test_a_restore_codex_refuses_is_journalled_kept_owed_and_not_asked_every_tick(self):
        made = self.code(model_after="the-default-model")
        made.tick(None).run(self.guard())
        self.assertEqual((made._scoped.runs.cleared, made._scoped.counted), ([], [NOT_RESTORED]))
        self.assertIs(made.tick(None), DEFER, "tried again only after RESTORE_EVERY")
        made._scoped.now = lambda: 1000.0 + RESTORE_EVERY
        self.assertIsNot(made.tick(None), DEFER)

    def test_a_restore_the_follower_read_back_clears_the_debt(self):
        made = self.code(live=None, ended=[{"key": KEY, "end": "completed", "model_restored": True}])
        made._scoped.runs.owed_rows = []
        made.tick(None)
        self.assertEqual(made._scoped.runs.cleared, [KEY])


class ErrorCodeTests(unittest.TestCase):
    def test_only_codex_s_code_is_read_never_a_word_of_the_message(self):
        with tempfile.TemporaryDirectory() as folder:
            home = CodexHome(Path(folder))
            turn = home.add_turn(T1, None, "failed", progress=False, error_json=json.dumps(
                {"codexErrorInfo": "serverOverloaded", "message": "secret words"}))
            self.assertEqual(Turns(home.root).turn_code(T1, turn), "serverOverloaded")
            other = home.add_turn(T1, None, "failed", progress=False, error_json="not json")
            self.assertIsNone(Turns(home.root).turn_code(T1, other))
            self.assertIsNone(Turns(home.root).turn_code(T1, new_id()))


class RegistryTests(TakingCase):
    DEFINITION = MODEL_FALLBACK

    def test_it_answers_at_p16_before_headless_run_and_is_shown_after_the_capacity_retry(self):
        at = tuple(d.id for d in registry.REGISTRY.at(Point.UNLOADED))
        self.assertLess(at.index(self.cap), at.index("headless_run"))
        shown = registry.SHOWN_ORDER
        # 2026-10-31: right after the capacity retry, before compact_continue.
        self.assertEqual(shown.index(self.cap), shown.index("capacity_retry") + 1)
        self.assertEqual(shown[shown.index(self.cap) + 1], "compact_continue")
        self.assertEqual(self.DEFINITION.option(OptionKey.ATTEMPTS).choices, (1, 2, 3))

    def test_unmeasured_on_this_codex_is_a_warning_never_a_refusal(self):
        plug = self.advanced()
        definition = plug.runtime.registry.get(self.cap)
        self.assertIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {Measurement.MF: (Verdict.PASS, ENGINE)}
        self.assertNotIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {}
        definition = plug.runtime.registry.get(self.cap)
        result = plug.runtime.arming.arm(
            self.cap, state="armed", revision=definition.revision, generation=plug.runtime.state.meta()["generation"],
            acknowledged_version=ENGINE, actor=Actor.DASHBOARD,
            warnings=[str(word) for word in plug.runtime.arming.warnings(definition)])
        self.assertTrue(result["done"], result)
        self.assertEqual(plug.runtime.states(fresh=True)[self.cap], ArmingState.ARMED)


if __name__ == "__main__":
    unittest.main()

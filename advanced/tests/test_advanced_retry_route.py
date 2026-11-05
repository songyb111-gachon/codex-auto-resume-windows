"""Codex's own retry settings by a provider of our own, on our own server only (v0.6.22, MB2).

MB's route - writing model_providers.openai - is refused by Codex by design. The new one (plans/v0622-retry-settings-
design.md): engine/retries.overrides, a copy of the built-in provider with the person's Attempts and model_provider
naming it, given as `-c` settings to the app server this product starts for its own turns (codex/headless.live_session)
and written nowhere; `fits` fails closed; the tick's setting lapses by itself. MB2 drives exactly those settings.

Every session is a fake; no Codex runs and no Codex home but a temporary one is touched.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_measure_stage4 import THREAD, TURN, ProbeCase  # noqa: E402
from codex_auto_resume_advanced import measure, registry  # noqa: E402
from codex_auto_resume_advanced.codex import headless, protocol  # noqa: E402
from codex_auto_resume_advanced.engine import retries  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

CHATGPT = {"account": {"type": "chatgpt", "email": "example.user@example.com", "planType": "plus"}}
APIKEY = {"account": {"type": "apiKey"}}


def config_of(settings):
    """The configuration a server started with `settings` ((key, TOML value), ...) answers, as config/read nests it."""
    config = {}
    for key, value in settings:
        node, (*parents, last) = config, key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[last] = True if value == "true" else (int(value) if value.isdigit() else value.strip('"'))
    return config


class Overrides(unittest.TestCase):
    def test_a_copy_of_the_built_in_provider_with_both_retries_and_model_provider_naming_it(self):
        config = config_of(retries.overrides(10))
        self.assertEqual(config["model_provider"], retries.PROVIDER)
        self.assertEqual(config["model_providers"][retries.PROVIDER],
                         {"name": "OpenAI", "base_url": "https://chatgpt.com/backend-api/codex",
                          "wire_api": "responses", "requires_openai_auth": True,
                          "request_max_retries": 10, "stream_max_retries": 10})

    def test_never_a_reserved_provider_id_and_only_an_offered_attempts(self):
        self.assertNotIn(retries.PROVIDER, ("openai", "ollama", "lmstudio"))
        for wrong in (4, 7, 100, True, "8", None):
            with self.subTest(wrong):
                with self.assertRaises(ValueError):
                    retries.overrides(wrong)

    def test_every_value_is_a_toml_literal(self):
        for key, value in retries.overrides(8):
            with self.subTest(key):
                self.assertRegex(value, r'^(true|false|\d+|"[^"\\]*")$')


class Fits(unittest.TestCase):
    def test_only_a_chatgpt_sign_in_on_codex_own_openai_provider(self):
        """Fails with any one check dropped: the copy would replace a provider it does not copy."""
        self.assertTrue(retries.fits({"config": {}}, CHATGPT))
        self.assertTrue(retries.fits({"config": {"model_provider": "openai"}}, CHATGPT))
        for config, account in (({}, APIKEY), ({}, {"account": None}), ({}, None),
                                ({"model_provider": "azure"}, CHATGPT),
                                ({"openai_base_url": "https://proxy.example"}, CHATGPT),
                                ({"model_providers": {retries.PROVIDER: {}}}, CHATGPT),
                                ({"model_providers": "broken"}, CHATGPT)):
            with self.subTest(config=config, account=account):
                self.assertFalse(retries.fits({"config": config}, account))
        self.assertFalse(retries.fits(None, CHATGPT))
        self.assertFalse(retries.fits({"config": "broken"}, CHATGPT))


class Look:
    """A look's session: config/read and account/read answered, or a failure."""

    def __init__(self, config, account, fail=False):
        self.config, self.account, self.fail, self.calls = config, account, fail, []

    def __enter__(self):
        if self.fail:
            raise OSError("Codex could not be started")
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params=None):
        self.calls.append(method)
        self.allowed = protocol.methods_for_capability(retries.CAPABILITY)
        if method not in self.allowed:
            raise protocol.SessionRefused("not permitted")
        return {"config": self.config} if method == retries.READ else self.account


class Scoped:
    def __init__(self, attempts):
        self.attempts = attempts

    def options(self):
        return {retries.OptionKey.ATTEMPTS: self.attempts}


class Tick(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.addCleanup(headless.hold_retry_settings, (), 0.0)

    def code(self, look, attempts=12):
        self.looks = []

        def opened():
            self.looks.append(look)
            return look
        code = retries.RetrySettings(None, session=opened, clock=lambda: self.now)
        code.bind(Scoped(attempts))
        return code

    def test_where_it_fits_our_servers_take_the_settings_and_nothing_is_sent(self):
        code = self.code(Look({}, CHATGPT))
        self.assertIs(code.tick(None), retries.DEFER)
        self.assertEqual(retries.in_force(self.now), retries.overrides(12))
        self.assertEqual(self.looks[0].calls, [retries.READ, retries.ACCOUNT])

    def test_fails_closed_where_it_does_not_fit_or_the_look_fails(self):
        for look in (Look({"model_provider": "azure"}, CHATGPT), Look({}, APIKEY), Look({}, CHATGPT, fail=True)):
            with self.subTest(look.config):
                self.code(look).tick(None)
                self.assertEqual(retries.in_force(self.now), ())

    def test_looks_again_only_after_its_time_and_lapses_when_not_renewed(self):
        """Fails with the lapse removed: a capability turned off would leave our servers on its provider."""
        code = self.code(Look({}, CHATGPT))
        code.tick(None)
        self.now += retries.LOOK_SECONDS - 1
        code.tick(None)
        self.assertEqual(len(self.looks), 1)
        self.now += 1
        code.tick(None)
        self.assertEqual(len(self.looks), 2)
        self.assertEqual(retries.in_force(self.now + retries.FRESH_SECONDS - 1), retries.overrides(12))
        self.assertEqual(retries.in_force(self.now + retries.FRESH_SECONDS), ())

    def test_an_attempts_not_offered_is_the_default(self):
        self.code(Look({}, CHATGPT), attempts=99).tick(None)
        self.assertEqual(retries.in_force(self.now), retries.overrides(retries.DEFAULT_ATTEMPTS))


class OurServerTakesThem(unittest.TestCase):
    def setUp(self):
        self.addCleanup(headless.hold_retry_settings, (), 0.0)

    def started(self):
        with patch.object(headless, "Session", lambda backend, capability, config: config), \
                patch("codex_auto_resume_advanced.codex.inuse.backend", lambda paths: None):
            return headless.live_session(None)("headless_run")

    def test_the_headless_server_starts_with_the_held_settings_and_without_them_once_lapsed(self):
        """Fails with live_session's addition reverted: the route would never reach Codex."""
        self.assertEqual(self.started(), headless.HEADLESS_CONFIG)
        headless.hold_retry_settings(retries.overrides(8), until=float("inf"))
        self.assertEqual(self.started(), headless.HEADLESS_CONFIG + retries.overrides(8))
        headless.hold_retry_settings(retries.overrides(8), until=0.0)
        self.assertEqual(self.started(), headless.HEADLESS_CONFIG)


class Codex:
    """Codex as MB2 meets it: a server's config is the settings it started with; the conversation's recorded provider,
    and whether a list shows it, are the test's to say."""

    def __init__(self, *, in_force=True, writes=False, rewrites=False, listed=True, account=CHATGPT, status="completed"):
        self.in_force, self.writes, self.rewrites, self.listed = in_force, writes, rewrites, listed
        self.account, self.status, self.provider = account, status, "openai"
        self.sessions = []

    def factory(self, measurement, home=None, config=None):
        session = Session(self, measurement, home, tuple(config))
        self.sessions.append(session)
        return session


class Session:
    def __init__(self, codex, measurement, home, config):
        self.codex, self.home, self.config = codex, home, config
        self.allowed = protocol.methods_for(measurement)
        self.calls, self.events = [], []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def drain_events(self):
        events, self.events = self.events, []
        return events

    def call(self, method, params=None):
        if method not in self.allowed:
            raise protocol.SessionRefused("not permitted")
        self.calls.append(method)
        codex = self.codex
        if method == "config/read":
            if codex.writes and self.home is not None:
                (Path(self.home) / "config.toml").write_text("model_provider = 1\n", encoding="utf-8")
            return {"config": config_of(self.config) if codex.in_force else {}, "layers": []}
        if method == "account/read":
            return codex.account
        if method == "thread/list":
            return {"data": [{"id": THREAD}] if codex.listed else []}
        if method == "thread/resume":
            if codex.rewrites:
                codex.provider = params["modelProvider"]
            return {}
        if method == "turn/start":
            self.events.append({"method": "turn/completed",
                                "params": {"threadId": THREAD, "turn": {"id": TURN, "status": codex.status}}})
            return {"turn": {"id": TURN}}
        if method == "thread/read":
            return {"thread": {"id": THREAD, "modelProvider": codex.provider}}
        return {}


class MB2(ProbeCase):
    def run_mb2(self, codex, thread=THREAD):
        return self.run_one(Measurement.MB2, codex.factory, thread=thread)[1]

    def test_it_drives_exactly_the_settings_our_server_starts_with(self):
        codex = Codex()
        self.run_mb2(codex)
        ours = headless.HEADLESS_CONFIG + retries.overrides(retries.DEFAULT_ATTEMPTS)
        self.assertEqual([session.config for session in codex.sessions], [ours, ours, ()])
        self.assertIsNotNone(codex.sessions[0].home, "the scratch part runs on a home of its own")
        self.assertFalse(Path(codex.sessions[0].home).exists(), "and removes it")
        self.assertEqual([session.home for session in codex.sessions[1:]], [None, None])

    def test_all_held_is_left_to_the_person_with_the_app(self):
        record = self.run_mb2(Codex())
        self.assertEqual(record["verdict"], "blocked", record)
        for key in ("override_in_force", "retries_read", "nothing_written", "signed_in_chatgpt", "listed_under_ours",
                    "turn_completed", "thread_kept_openai", "listed_after"):
            self.assertIs(record["observed"][key], True, key)

    def test_without_a_conversation_only_the_scratch_part_runs(self):
        codex = Codex()
        record = self.run_mb2(codex, thread=None)
        self.assertEqual(record["verdict"], "blocked")
        self.assertEqual(len(codex.sessions), 1)
        self.assertNotIn("turn_completed", record["observed"])

    def test_each_thing_that_would_cost_a_person_fails_it(self):
        """Fails with any one check dropped from the verdict: a route that hides a conversation would pass."""
        for name, codex in (("not in force", Codex(in_force=False)), ("config written", Codex(writes=True)),
                            ("api key", Codex(account=APIKEY)), ("no completed turn", Codex(status="failed")),
                            ("provider rewritten", Codex(rewrites=True)), ("not listed", Codex(listed=False))):
            with self.subTest(name):
                self.sessions = []
                self.assertEqual(self.run_mb2(codex)["verdict"], "fail")

    def test_calls_only_what_it_declared(self):
        codex = Codex()
        self.run_mb2(codex)
        called = {method for session in codex.sessions for method in session.calls}
        self.assertTrue(called <= set(protocol.MEASUREMENT_METHODS[Measurement.MB2]))
        self.assertIn("turn/start", called)

    def test_a_factory_that_cannot_take_settings_is_refused(self):
        record = self.run_one(Measurement.MB2, lambda measurement, home=None: None)[1]
        self.assertNotEqual(record["verdict"], "pass")


class Gate(unittest.TestCase):
    def test_hidden_on_mb2_with_only_its_two_reads(self):
        self.assertEqual(registry.CODEX_RETRY_SETTINGS.measurements, (Measurement.MB2,))
        self.assertIn((registry.CODEX_RETRY_SETTINGS, Measurement.MB2), registry.WAITING)
        self.assertEqual(protocol.CAPABILITY_METHODS[retries.CAPABILITY], ("config/read", "account/read"))
        self.assertIs(measure.PROBES[Measurement.MB2], measure._mb2)


if __name__ == "__main__":
    unittest.main()

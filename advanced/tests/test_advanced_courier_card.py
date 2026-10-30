"""The courier's card commands (v0.6.20, control/courier.py, surfaces.courier): the Dashboard reads which channels are
saved - never a secret - saves one channel's checked address and secret into (a fake) Credential Manager, begins
Telegram's pairing with a one-time code whose digest alone is kept, forgets a channel, sends a test notice through a
courier run, and asks for a status reading now. No MCP tool reaches any of it, and nothing secret reaches the state
file, the journal or an answer.

No courier is started and Windows' Credential Manager is never touched: both are fakes.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_courier_channels import SMTP, BOT_INK, TOPIC, Secrets  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import courier as card  # noqa: E402
from codex_auto_resume_advanced.courier import keep  # noqa: E402
from codex_auto_resume_advanced.credentials import SecretError  # noqa: E402
from codex_auto_resume_advanced.registry import PUSH_NOTICES, STATUS_FEED  # noqa: E402
from codex_auto_resume_advanced.vocabulary import BridgeCommand, McpTool, Refusal  # noqa: E402


class CardCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.catalogs = statement.CATALOGS
        self.compat = ac.view(capability="engine_present")
        self.rt = self.runtime(PUSH_NOTICES, STATUS_FEED)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets()

    def on(self, capability="push_notices", state="armed"):
        definition = self.rt.registry.get(capability)
        result = self.arm(self.rt, capability, state=state,
                          warnings=[str(w) for w in self.rt.arming.warnings(definition)])
        self.assertTrue(result["done"], result)


class SaveTests(CardCase):
    def test_off_nothing_is_saved(self):
        self.assertEqual(card.save(self.rt, {"channel": "ntfy", "url": TOPIC}, secrets=self.secrets)["refusal"],
                         Refusal.NOT_ON)
        self.assertEqual(self.secrets.kept, {})

    def test_each_channel_is_checked_and_kept_and_the_view_says_only_saved(self):
        self.on(state="shadow")
        for argument in ({"channel": "ntfy", "url": TOPIC},
                         {"channel": "webhook", "url": "https://hooks.example.com/x", "token": "made-up"},
                         {"channel": "telegram", "token": BOT_INK},
                         dict({"channel": "email"}, **SMTP)):
            with self.subTest(argument["channel"]):
                self.assertTrue(card.save(self.rt, argument, secrets=self.secrets)["done"])
        self.assertEqual(json.loads(self.secrets.kept["smtp"]), SMTP)
        view = card.view(self.rt, secrets=self.secrets)
        self.assertEqual({row["channel"]: row["saved"] for row in view["channels"]},
                         {"ntfy": True, "webhook": True, "telegram": False, "email": True})
        self.assertEqual(view["telegram"], {"token_saved": True, "paired": False, "pairing": False})
        said = json.dumps(view)
        for secret in (TOPIC, BOT_INK, "made-up", SMTP["password"], "hooks.example.com"):
            self.assertNotIn(secret, said)

    def test_a_refused_address_says_why_in_one_word_and_keeps_nothing(self):
        self.on()
        for argument, why in (({"channel": "ntfy", "url": "http://ntfy.example.com/x"}, "not_https"),
                              ({"channel": "webhook", "url": "https://u:p@example.com/"}, "userinfo"),
                              ({"channel": "telegram", "token": "nope"}, "token"),
                              (dict({"channel": "email"}, **dict(SMTP, port=25)), "port")):
            with self.subTest(why):
                self.assertEqual(card.save(self.rt, argument, secrets=self.secrets),
                                 {"done": False, "refusal": Refusal.ADDRESS_REFUSED, "why": why})
        self.assertEqual(self.secrets.kept, {})
        self.assertEqual(card.save(self.rt, {"channel": "sms"}, secrets=self.secrets)["refusal"],
                         Refusal.INVALID_REQUEST)

    def test_credential_manager_refusing_is_said(self):
        self.on()

        class Refusing(Secrets):
            def write(self, capability, name, secret):
                raise SecretError("no")
        self.assertEqual(card.save(self.rt, {"channel": "ntfy", "url": TOPIC}, secrets=Refusing())["refusal"],
                         Refusal.SECRET_UNAVAILABLE)

    def test_a_new_bot_token_forgets_the_chat_paired_before(self):
        self.on()
        self.secrets.kept.update(telegram_token=BOT_INK, telegram_chat="77")
        card.save(self.rt, {"channel": "telegram", "token": "99:" + "B" * 35}, secrets=self.secrets)
        self.assertNotIn("telegram_chat", self.secrets.kept)


class PairTests(CardCase):
    def test_pairing_answers_a_code_keeps_its_digest_and_starts_the_courier(self):
        self.on()
        started = []
        self.assertEqual(card.save(self.rt, {"channel": "telegram", "pair": True}, secrets=self.secrets,
                                   start=lambda paths, *extra: started.append(extra) or True)["refusal"],
                         Refusal.NOT_SAVED)
        self.secrets.kept["telegram_token"] = BOT_INK
        answer = card.save(self.rt, {"channel": "telegram", "pair": True}, secrets=self.secrets,
                           start=lambda paths, *extra: started.append(extra) or True)
        self.assertTrue(answer["done"])
        self.assertRegex(answer["code"], r"\A[0-9]{6}\Z")
        self.assertEqual(started, [("--pair",)])
        row = keep.pairing(self.rt.state)
        self.assertEqual(row["code_digest"], keep.digest(answer["code"]))
        self.assertTrue(card.view(self.rt, secrets=self.secrets)["telegram"]["pairing"])


class ForgetAndTestTests(CardCase):
    def test_forget_takes_only_that_channel_out(self):
        self.secrets.kept.update(ntfy_url=TOPIC, telegram_token=BOT_INK, telegram_chat="1")
        self.assertTrue(card.forget(self.rt, "telegram", secrets=self.secrets)["done"])
        self.assertEqual(set(self.secrets.kept), {"ntfy_url"})

    def test_a_test_notice_s_outcome_is_one_word(self):
        self.on()
        self.assertEqual(card.test(self.rt, "ntfy", secrets=self.secrets)["outcome"], "not_saved")
        self.secrets.kept["ntfy_url"] = TOPIC
        for code, word in ((0, "sent"), (5, "refused"), (6, "server_error"), (7, "timed_out"), (8, "tls"),
                           (3, "busy"), (None, "no_answer")):
            ran = []
            answer = card.test(self.rt, "ntfy", secrets=self.secrets,
                               run=lambda paths, *extra, timeout: ran.append(extra) or code)
            self.assertEqual(answer["outcome"], word)
            self.assertEqual(ran, [("--test", "ntfy")])

    def test_the_feed_is_read_now_only_while_on(self):
        started = []
        self.assertEqual(card.feed_refresh(self.rt, start=lambda paths, *extra: started.append(extra))["refusal"],
                         Refusal.NOT_ON)
        self.on("status_feed")
        self.assertTrue(card.feed_refresh(self.rt, start=lambda paths, *extra: started.append(extra) or True)["done"])
        self.assertEqual(started, [("--feed",)])


class BridgeTests(CardCase):
    def test_the_bridge_answers_the_five_commands_and_refuses_unknown_arguments(self):
        with patch("codex_auto_resume_advanced.courier.keep.secrets_of", lambda registry: self.secrets):
            self.assertTrue(surfaces.bridge(self.rt, BridgeCommand.ADVANCED_COURIER, {})["done"])
            self.assertEqual(surfaces.bridge(self.rt, BridgeCommand.ADVANCED_COURIER_SAVE, {"channel": "ntfy",
                                                                                           "secret": "x"}),
                             {"done": False, "refusal": Refusal.INVALID_REQUEST})
            self.assertTrue(surfaces.bridge(self.rt, BridgeCommand.ADVANCED_COURIER_FORGET, {"channel": "ntfy"})["done"])
        for command in (BridgeCommand.ADVANCED_COURIER, BridgeCommand.ADVANCED_COURIER_SAVE,
                        BridgeCommand.ADVANCED_COURIER_FORGET, BridgeCommand.ADVANCED_COURIER_TEST,
                        BridgeCommand.ADVANCED_FEED_REFRESH):
            self.assertNotIn(command, surfaces.UNANSWERED)

    def test_no_mcp_tool_reaches_the_courier(self):
        names = {tool["name"] for tool in surfaces.TOOLS}
        self.assertEqual(names, {str(tool) for tool in McpTool} & names)
        self.assertFalse([name for name in names if "courier" in name or "feed" in name or "push" in name])


if __name__ == "__main__":
    unittest.main()

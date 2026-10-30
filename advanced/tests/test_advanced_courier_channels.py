"""The four channels a notice is pushed on, the outbox's tries, and Telegram's pairing (v0.6.20,
advanced/src/codex_auto_resume_advanced/courier/channels.py, outbox.py, keep.py).

Each channel's request is held to its shape against a fake opener or a fake SMTP server; the secrets come from a fake
Credential Manager. No request reaches a real service and no real token is used: every token and address here is made
up for the test.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import smtplib
import ssl
import sys
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_courier_http import Opener, Reply  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.courier import channels, http, keep, outbox  # noqa: E402
from codex_auto_resume_advanced.courier import __main__ as courier  # noqa: E402
from codex_auto_resume_advanced.registry import PUSH_NOTICES  # noqa: E402
from codex_auto_resume_advanced.vocabulary import OptionKey  # noqa: E402

BOT_INK = "123456789:" + "T" * 35                    # made up: the shape of a bot token, never a real one
BEARER_INK = "made-up-bearer"                       # made up: a webhook bearer, never a real one
TOPIC = "https://ntfy.example.com/a-topic-made-up-for-the-test"
HOOK = "https://hooks.example.com/in/made-up"
SMTP = {"host": "smtp.example.com", "port": 465, "user": "me@example.com", "password": "made-up-app-password",
        "from": "me@example.com", "to": "phone@example.com"}


class Secrets:
    """Credential Manager, as push_notices sees it through credentials.Secrets: a dict of its own."""

    def __init__(self, **kept):
        self.kept = {name: value for name, value in kept.items()}
        self.writes = []

    def read(self, capability, name):
        assert capability == "push_notices"
        return self.kept.get(name)

    def write(self, capability, name, secret):
        assert capability == "push_notices"
        self.writes.append(name)
        self.kept[name] = secret

    def delete(self, capability, name):
        return self.kept.pop(name, None) is not None


class Server:
    """smtplib's SMTP and SMTP_SSL, as a test says: every call kept, any of them made to raise."""
    made = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context, self.calls = host, port, timeout, context, []
        Server.made.append(self)
        if Server.fail_at == "connect":
            raise Server.error

    def _maybe(self, name):
        self.calls.append(name)
        if Server.fail_at == name:
            raise Server.error

    def starttls(self, context=None):
        self.tls_context = context
        self._maybe("starttls")

    def login(self, user, password):
        self.signed_in = (user, password)
        self._maybe("login")

    def send_message(self, message):
        self.message = message
        self._maybe("send")

    def quit(self):
        self.calls.append("quit")


class Smtp:
    SMTP = Server
    SMTP_SSL = Server


class ChannelCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        Server.made, Server.fail_at, Server.error = [], None, None
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(PUSH_NOTICES)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets(ntfy_url=TOPIC, webhook_url=HOOK, webhook_token=BEARER_INK,
                               telegram_token=BOT_INK, telegram_chat="-1001234", smtp=json.dumps(SMTP))

    def row(self, event="recovered", category="usage_limit", alias="task 3"):
        return {"event": event, "category": category, "alias": alias, "at": ac.NOW}


class LinesTests(ChannelCase):
    def test_at_most_three_lines_the_event_the_task_and_kind_and_time_and_the_edition(self):
        said = channels.lines("recovered", "usage_limit", "task 3", ac.NOW, "en")
        self.assertEqual(len(said), 3)
        self.assertEqual(said[0], statement.CATALOGS.text("page.push.recovered", "en"))
        self.assertTrue(said[1].startswith("task 3 · usage_limit · "), said)
        self.assertEqual(said[2], statement.CATALOGS.text("page.push.edition", "en"))
        self.assertEqual(channels.lines("update_offered", None, None, None, "en"),
                         [statement.CATALOGS.text("page.push.update_offered", "en"),
                          statement.CATALOGS.text("page.push.edition", "en")])

    def test_every_event_has_its_words_in_every_language(self):
        from codex_auto_resume import l10n
        from codex_auto_resume_advanced.vocabulary import CourierEvent
        for locale in l10n.LOCALES:
            table = statement.CATALOGS.own(locale)
            for event in CourierEvent:
                with self.subTest(locale=locale, event=event):
                    self.assertTrue(table.get("page.push.%s" % event), "page.push.%s" % event)
            self.assertTrue(table.get("page.push.edition"))


class ShapeTests(ChannelCase):
    def test_ntfy_posts_the_lines_as_text_with_fixed_ascii_headers(self):
        opener = Opener()
        self.assertEqual(channels.send("ntfy", self.row(), self.secrets, opener=opener, locale="ko"), "2xx")
        (request, _timeout), = opener.requests
        self.assertEqual(request.full_url, TOPIC)
        self.assertEqual(request.data.decode("utf-8"), "\n".join(channels.lines("recovered", "usage_limit", "task 3",
                                                                                ac.NOW, "ko")))
        self.assertEqual((request.get_header("Title"), request.get_header("Tags")), ("Codex Auto Resume", "recovered"))

    def test_the_webhook_posts_closed_keys_as_json_with_its_bearer_token(self):
        opener = Opener()
        channels.send("webhook", self.row(), self.secrets, opener=opener)
        (request, _timeout), = opener.requests
        self.assertEqual(request.full_url, HOOK)
        self.assertEqual(json.loads(request.data), {"event": "recovered", "category": "usage_limit", "task": "task 3",
                                                    "at": int(ac.NOW), "edition": "advanced"})
        self.assertEqual(request.get_header("Authorization"), "Bearer made-up-bearer")
        del self.secrets.kept["webhook_token"]
        opener = Opener()
        channels.send("webhook", self.row(), self.secrets, opener=opener)
        self.assertIsNone(opener.requests[0][0].get_header("Authorization"))

    def test_telegram_sends_to_the_paired_chat_with_the_token_only_in_the_path(self):
        opener = Opener()
        channels.send("telegram", self.row(), self.secrets, opener=opener, locale="en")
        (request, _timeout), = opener.requests
        self.assertEqual(request.full_url, "https://api.telegram.org/bot%s/sendMessage" % BOT_INK)
        body = json.loads(request.data)
        self.assertEqual(set(body), {"chat_id", "text", "disable_web_page_preview"})
        self.assertEqual(body["chat_id"], -1001234)
        self.assertNotIn(BOT_INK, request.data.decode("utf-8"))
        self.assertNotIn(BOT_INK, json.dumps(dict(request.header_items())))

    def test_e_mail_on_465_is_tls_from_the_start_and_587_is_starttls_both_verified(self):
        channels.send("email", self.row(), self.secrets, smtp=Smtp, locale="en")
        server, = Server.made
        self.assertEqual((server.host, server.port), ("smtp.example.com", 465))
        self.assertEqual(server.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(server.calls, ["login", "send", "quit"])
        message = server.message
        self.assertEqual((message["From"], message["To"], message["Subject"]),
                         ("me@example.com", "phone@example.com", "Codex Auto Resume: recovered"))
        self.assertEqual(set(message.keys()) - {"Content-Type", "Content-Transfer-Encoding", "MIME-Version"},
                         {"Subject", "From", "To"})
        self.secrets.kept["smtp"] = json.dumps(dict(SMTP, port=587))
        Server.made = []
        channels.send("email", self.row(), self.secrets, smtp=Smtp)
        server, = Server.made
        self.assertEqual(server.port, 587)
        self.assertEqual(server.calls, ["starttls", "login", "send", "quit"])
        self.assertTrue(server.tls_context.check_hostname)

    def test_e_mail_failures_are_closed_words(self):
        cases = (("login", smtplib.SMTPAuthenticationError(535, b"no"), "4xx"),
                 ("send", smtplib.SMTPDataError(554, b"refused"), "4xx"),
                 ("send", smtplib.SMTPDataError(451, b"later"), "5xx"),
                 ("starttls", smtplib.SMTPNotSupportedError(), "tls"),
                 ("connect", ssl.SSLCertVerificationError("bad cert"), "tls"),
                 ("connect", TimeoutError(), "timeout"),
                 ("connect", smtplib.SMTPServerDisconnected(), "timeout"))
        self.secrets.kept["smtp"] = json.dumps(dict(SMTP, port=587))
        for where, error, word in cases:
            with self.subTest(where=where, word=word):
                Server.fail_at, Server.error = where, error
                with self.assertRaises(http.Failed) as raised:
                    channels.send("email", self.row(), self.secrets, smtp=Smtp)
                self.assertEqual(raised.exception.word, word)

    def test_a_channel_not_saved_or_an_address_kept_badly_sends_nothing(self):
        opener = Opener()
        with self.assertRaises(keep.NotSaved):
            channels.send("ntfy", self.row(), Secrets(), opener=opener)
        with self.assertRaises(keep.NotSaved):
            channels.send("telegram", self.row(), Secrets(telegram_token=BOT_INK), opener=opener)
        from codex_auto_resume_advanced.courier.address import AddressRefused
        with self.assertRaises(AddressRefused):
            channels.send("ntfy", self.row(), Secrets(ntfy_url="http://ntfy.example.com/x"), opener=opener)
        self.assertEqual(opener.requests, [])


class DrainCase(ChannelCase):
    def setUp(self):
        super().setUp()
        self.arm(self.rt, "push_notices", warnings=[str(w) for w in self.rt.arming.warnings(PUSH_NOTICES)])
        for channel in ("ntfy", "telegram"):
            self.rt.state.set_option("push_notices", OptionKey(channel), 1,
                                     generation=self.rt.state.meta()["generation"], actor="dashboard")

    def enqueue(self, *channels_, at=None):
        return outbox.enqueue(self.rt.state, channels_ or ("ntfy",), "recovered", "usage_limit", "task 1",
                              ac.NOW if at is None else at)

    def rows(self):
        with self.rt.state._read() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM outbox ORDER BY item_id")]

    def codes(self):
        with self.rt.state._read() as connection:
            return [row[0] for row in connection.execute("SELECT code FROM journal WHERE code LIKE 'push.%'")]


class DrainTests(DrainCase):
    def test_a_due_row_is_sent_once_and_journalled_by_channel(self):
        self.enqueue("ntfy", "telegram")
        opener = Opener()
        self.assertEqual(channels.drain(self.rt, self.secrets, opener=opener, now=ac.NOW), 2)
        self.assertEqual([row["state"] for row in self.rows()], ["sent", "sent"])
        self.assertEqual(sorted(self.codes()), ["push.sent_ntfy", "push.sent_telegram"])
        self.assertEqual(channels.drain(self.rt, self.secrets, opener=Opener(), now=ac.NOW + 600), 0)

    def test_three_tries_then_dropped_and_each_journalled_with_its_class_never_the_address(self):
        self.enqueue()
        failing = Opener(error=urllib.error.HTTPError(TOPIC, 503, "x", {}, io.BytesIO()))
        for after in (0, 10, 70):
            channels.drain(self.rt, self.secrets, opener=failing, now=ac.NOW + after)
        self.assertEqual(len(failing.requests), 3)
        (row,) = self.rows()
        self.assertEqual((row["state"], row["tries"]), ("dropped", 3))
        self.assertEqual(self.codes(), ["push.refused_ntfy_5xx"] * 3 + ["push.dropped_ntfy"])

    def test_a_try_waits_its_time(self):
        self.enqueue()
        failing = Opener(error=urllib.error.HTTPError(TOPIC, 500, "x", {}, io.BytesIO()))
        channels.drain(self.rt, self.secrets, opener=failing, now=ac.NOW)
        channels.drain(self.rt, self.secrets, opener=failing, now=ac.NOW + 5)
        self.assertEqual(len(failing.requests), 1, "the second try waits 10 s")

    def test_seven_days_old_a_waiting_row_is_dropped_unsent(self):
        self.enqueue(at=ac.NOW - outbox.MAX_AGE - 1)
        opener = Opener()
        channels.drain(self.rt, self.secrets, opener=opener, now=ac.NOW)
        self.assertEqual(opener.requests, [])
        self.assertEqual(self.rows()[0]["state"], "dropped")
        self.assertEqual(self.codes(), ["push.dropped_ntfy"])

    def test_a_channel_switched_off_or_not_saved_drops_its_rows(self):
        self.enqueue("ntfy", "webhook")
        del self.secrets.kept["ntfy_url"]
        opener = Opener()
        channels.drain(self.rt, self.secrets, opener=opener, now=ac.NOW)
        self.assertEqual(opener.requests, [])
        self.assertEqual([row["state"] for row in self.rows()], ["dropped", "dropped"])

    def test_twenty_refusals_in_a_day_switch_that_channel_off_and_no_other(self):
        refusing = Opener(error=urllib.error.HTTPError(TOPIC, 403, "x", {}, io.BytesIO()))
        for n in range(outbox.TRIPWIRE):
            self.enqueue(at=ac.NOW + n)
            channels.drain(self.rt, self.secrets, opener=refusing, now=ac.NOW + n)
        options = self.rt.state.options("push_notices")
        self.assertEqual((options[OptionKey.NTFY], options[OptionKey.TELEGRAM]), (2, 1))
        self.assertIn("push.off_ntfy", self.codes())
        self.assertEqual(outbox.refusals_today(self.rt.state, "ntfy", ac.NOW + 30), outbox.TRIPWIRE)
        self.assertEqual(self.rt.states(fresh=True)["push_notices"], "armed", "the channel, not the capability")

    def test_thirty_an_hour_across_every_channel(self):
        written = sum(self.enqueue("ntfy", "telegram", at=ac.NOW + n) for n in range(20))
        self.assertEqual(written, outbox.HOURLY)
        self.assertEqual(self.enqueue("ntfy", at=ac.NOW + 3601), 1, "an hour on, room again")

    def test_no_secret_reaches_the_state_file(self):
        self.enqueue("ntfy", "telegram")
        channels.drain(self.rt, self.secrets, opener=Opener(error=urllib.error.HTTPError(
            TOPIC, 401, "bad " + BOT_INK, {}, io.BytesIO(BOT_INK.encode()))), now=ac.NOW)
        self.rt.state.close()
        raw = Path(self.rt.state.path).read_bytes()
        for secret in (BOT_INK, TOPIC, "made-up-bearer", "-1001234", "a-topic-made-up"):
            self.assertNotIn(secret.encode("utf-8"), raw)


class TestNoticeTests(DrainCase):
    def test_the_test_notice_s_outcome_is_the_courier_s_exit_code(self):
        self.assertEqual(channels.test(self.rt, "ntfy", self.secrets, opener=Opener()), courier.EXIT_TEST["2xx"])
        for code, word in ((403, "4xx"), (502, "5xx")):
            error = urllib.error.HTTPError(TOPIC, code, "x", {}, io.BytesIO())
            self.assertEqual(channels.test(self.rt, "ntfy", self.secrets, opener=Opener(error=error)),
                             courier.EXIT_TEST[word])
        self.assertEqual(channels.test(self.rt, "ntfy", Secrets(), opener=Opener()), courier.EXIT_REFUSED)
        self.assertEqual(self.rows(), [], "a test is not in the outbox")

    def test_through_the_process_while_on_or_watched_and_refused_off(self):
        argv = ["--home", str(self.paths.home), "--test", "ntfy"]
        seams = dict(runtime=lambda paths: self.rt, mutex=lambda paths: _Lock(), secrets=self.secrets,
                     opener=Opener(), paused=lambda paths: False)
        self.assertEqual(courier.main(argv, **seams), 0)
        self.rt.arming.disarm("push_notices", actor="dashboard")
        self.assertEqual(courier.main(argv, **seams), courier.EXIT_REFUSED)


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return None


class ProcessDrainTests(DrainCase):
    def seams(self, opener, paused=False):
        return dict(runtime=lambda paths: self.rt, mutex=lambda paths: _Lock(), secrets=self.secrets, opener=opener,
                    paused=lambda paths: paused, clock=lambda: ac.NOW)

    def test_paused_nothing_is_sent_and_rows_wait(self):
        self.enqueue()
        opener = Opener()
        self.assertEqual(courier.main(["--home", str(self.paths.home)], **self.seams(opener, paused=True)), 0)
        self.assertEqual(opener.requests, [])
        self.assertEqual(self.rows()[0]["state"], "waiting")
        self.assertEqual(courier.main(["--home", str(self.paths.home)], **self.seams(opener, paused=None)), 0)
        self.assertEqual(opener.requests, [], "a pause that cannot be told is a pause")
        self.assertEqual(courier.main(["--home", str(self.paths.home)], **self.seams(opener)), 0)
        self.assertEqual(len(opener.requests), 1)

    def test_turned_off_nothing_is_sent(self):
        self.enqueue()
        self.rt.arming.disarm("push_notices", actor="dashboard")
        opener = Opener()
        courier.main(["--home", str(self.paths.home)], **self.seams(opener))
        self.assertEqual(opener.requests, [])


class PairingTests(DrainCase):
    def updates(self, *messages, start=10):
        return Reply(200, json.dumps({"ok": True, "result": [
            {"update_id": start + n, "message": {"chat": {"id": chat}, "text": text}}
            for n, (chat, text) in enumerate(messages)]}).encode())

    def pair(self, replies, clock_steps=None):
        class Many(Opener):
            def open(inner, request, timeout=None):
                inner.requests.append((request, timeout))
                return replies.pop(0) if replies else Reply(200, b'{"ok":true,"result":[]}')
        opener = Many()
        times = iter(clock_steps or [ac.NOW + n for n in range(0, 400, 5)])
        code = channels.pair(self.rt, self.secrets, opener=opener, clock=lambda: next(times), sleep=lambda s: None)
        return code, opener

    def test_the_chat_that_sends_the_code_is_kept_and_only_its_digest_was_ever_stored(self):
        del self.secrets.kept["telegram_chat"]
        keep.begin_pairing(self.rt.state, "042317", ac.NOW)
        row = keep.pairing(self.rt.state)
        self.assertEqual(row["code_digest"], keep.digest("042317"))
        code, opener = self.pair([self.updates((555, "hello"), (777, "042317"))])
        self.assertEqual(code, 0)
        self.assertEqual(self.secrets.kept["telegram_chat"], "777")
        row = keep.pairing(self.rt.state)
        self.assertIsNone(row["code_digest"])
        self.assertIsNotNone(row["paired_at"])
        url = opener.requests[0][0].full_url
        self.assertTrue(url.startswith("https://api.telegram.org/bot%s/getUpdates?timeout=" % BOT_INK), url)
        self.rt.state.close()
        self.assertNotIn(b"042317", Path(self.rt.state.path).read_bytes())

    def test_five_other_codes_end_it(self):
        keep.begin_pairing(self.rt.state, "042317", ac.NOW)
        code, _ = self.pair([self.updates(*[(9, "%06d" % n) for n in range(5)])])
        self.assertEqual(code, courier.EXIT_NOT_PAIRED)
        self.assertEqual(self.secrets.kept["telegram_chat"], "-1001234", "the chat paired before is kept")
        self.assertIsNone(keep.pairing(self.rt.state)["code_digest"])

    def test_it_ends_when_the_code_expires(self):
        keep.begin_pairing(self.rt.state, "042317", ac.NOW)
        code, opener = self.pair([], clock_steps=[ac.NOW, ac.NOW + 60, ac.NOW + 121, ac.NOW + 200, ac.NOW + 300])
        self.assertEqual(code, courier.EXIT_NOT_PAIRED)
        self.assertLessEqual(len(opener.requests), 2)

    def test_no_code_begun_or_no_token_refuses(self):
        self.assertEqual(self.pair([])[0], courier.EXIT_REFUSED)
        keep.begin_pairing(self.rt.state, "042317", ac.NOW)
        self.secrets.kept["telegram_token"] = "not a token"
        self.assertEqual(self.pair([])[0], courier.EXIT_REFUSED)
        with self.assertRaises(ValueError):
            keep.begin_pairing(self.rt.state, "42", ac.NOW)


if __name__ == "__main__":
    unittest.main()

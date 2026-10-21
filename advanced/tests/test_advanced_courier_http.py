"""The courier's one way to a service (v0.6.19, advanced/src/codex_auto_resume_advanced/courier/http.py, address.py):
https only, no user name or password in an address, no IP literal and no loopback name, no redirect followed, a body of
at most 4 KiB and a reply read to 64 KiB, the certificate verified - and a failure said in one closed word, never the
address or what the service answered.

No request here reaches the network: every one goes to a fake opener.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import io
from pathlib import Path
import socket
import ssl
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume_advanced.courier import address, http  # noqa: E402
from codex_auto_resume_advanced.courier.address import AddressRefused  # noqa: E402


class Reply:
    def __init__(self, status=200, body=b"ok"):
        self.status, self._body, self.read_with, self.closed = status, body, [], False

    def read(self, n=-1):
        self.read_with.append(n)
        return self._body[:n] if n >= 0 else self._body

    def close(self):
        self.closed = True


class Opener:
    """What urllib's opener would do, as a test says: answer `reply`, or raise `error`. Every request kept."""

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply or Reply(), error, []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.reply


class AddressTests(unittest.TestCase):
    def test_an_https_address_of_a_named_host_is_taken(self):
        for url in ("https://ntfy.sh/a-topic-nobody-guesses", "https://hooks.example.com:8443/in?x=1",
                    "https://api.telegram.org/bot1/sendMessage"):
            with self.subTest(url):
                self.assertEqual(address.checked_url(url), url)

    def test_each_kind_of_address_no_push_may_go_to_is_refused_with_its_own_word(self):
        cases = {"http://ntfy.sh/topic": "not_https", "ftp://example.com/x": "not_https",
                 "https://user:secret@example.com/x": "userinfo", "https://user@example.com/x": "userinfo",
                 "https://127.0.0.1/hook": "ip_literal", "https://[::1]/hook": "ip_literal",
                 "https://10.0.0.5/hook": "ip_literal", "https://localhost/hook": "loopback",
                 "https://api.localhost/hook": "loopback", "https://intranet/hook": "host",
                 "https://exa mple.com/x": "url", "https://example.com/" + "a" * 2050: "url", "": "url",
                 None: "url", "https://example.com:99999/": "url", "https://example.com/\nX: y": "url"}
        for url, word in cases.items():
            with self.subTest(url=url):
                with self.assertRaises(AddressRefused) as raised:
                    address.checked_url(url)
                self.assertEqual(raised.exception.word, word)
                self.assertNotIn("secret", str(raised.exception))

    def test_the_e_mail_settings_are_checked_whole_and_no_header_can_be_injected(self):
        good = {"host": "smtp.example.com", "port": 587, "user": "me@example.com", "password": "app-pass",
                "from": "me@example.com", "to": "phone@example.com"}
        self.assertEqual(address.checked_smtp(dict(good)), good)
        for change, word in (({"port": 25}, "port"), ({"port": "587"}, "port"), ({"host": "127.0.0.1"}, "ip_literal"),
                             ({"to": "a@example.com\nBcc: b@example.com"}, "mailbox"),
                             ({"from": "Me <me@example.com>"}, "mailbox"), ({"password": "two words"}, "token"),
                             ({"user": "line\r\nbreak"}, "token")):
            with self.subTest(change=change):
                with self.assertRaises(AddressRefused) as raised:
                    address.checked_smtp(dict(good, **change))
                self.assertEqual(raised.exception.word, word)
        with self.assertRaises(AddressRefused):
            address.checked_smtp(dict(good, extra="x"))

    def test_a_telegram_token_and_chat_have_their_shapes(self):
        self.assertTrue(address.TELEGRAM_TOKEN.match("123456:" + "A" * 35))
        for bad in ("123456", "abc:" + "A" * 35, "123:" + "A" * 35 + "/x", "123:short"):
            self.assertIsNone(address.TELEGRAM_TOKEN.match(bad), bad)
        self.assertTrue(address.TELEGRAM_CHAT.match("-100123"))
        self.assertIsNone(address.TELEGRAM_CHAT.match("12a"))


class RequestTests(unittest.TestCase):
    def test_a_post_goes_once_with_its_body_and_headers_and_reads_at_most_64_kib(self):
        opener = Opener(Reply(200, b"x" * 100000))
        self.assertEqual(http.post("https://ntfy.sh/topic", b"hello", {"Title": "T"}, opener=opener), "2xx")
        (request, timeout), = opener.requests
        self.assertEqual((request.get_method(), request.full_url, request.data, timeout),
                         ("POST", "https://ntfy.sh/topic", b"hello", http.TIMEOUT))
        self.assertEqual(request.get_header("Title"), "T")
        self.assertEqual(request.get_header("User-agent"), http.USER_AGENT)
        self.assertEqual(opener.reply.read_with, [http.MAX_REPLY])
        self.assertTrue(opener.reply.closed)
        self.assertEqual(len(http.get("https://status.example.com/s.json", opener=Opener(Reply(200, b"y" * 70000)))),
                         http.MAX_REPLY)

    def test_an_address_no_push_may_go_to_sends_nothing(self):
        for url in ("http://ntfy.sh/topic", "https://u:p@example.com/", "https://127.0.0.1/", "https://localhost/"):
            with self.subTest(url):
                opener = Opener()
                with self.assertRaises(AddressRefused):
                    http.post(url, b"x", {}, opener=opener)
                self.assertEqual(opener.requests, [])

    def test_a_body_over_4_kib_is_never_sent(self):
        opener = Opener()
        with self.assertRaises(ValueError):
            http.post("https://ntfy.sh/topic", b"x" * (http.MAX_BODY + 1), {}, opener=opener)
        self.assertEqual(opener.requests, [])

    def test_each_failure_is_one_closed_word_and_never_the_address(self):
        url = "https://api.telegram.org/bot123456:SECRETTOKENSECRETTOKENSECRET/sendMessage"
        cases = ((urllib.error.HTTPError(url, 302, "Found", {"Location": "https://elsewhere.example.com"}, io.BytesIO()),
                  "4xx", 302),
                 (urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"bad token SECRETTOKEN")), "4xx", 401),
                 (urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO()), "5xx", 503),
                 (urllib.error.URLError(ssl.SSLCertVerificationError("self signed")), "tls", None),
                 (urllib.error.URLError(socket.gaierror("no such host")), "timeout", None),
                 (socket.timeout("timed out"), "timeout", None), (ssl.SSLError("handshake"), "tls", None),
                 (ConnectionResetError(), "timeout", None))
        for error, word, status in cases:
            with self.subTest(error=type(error).__name__, word=word):
                with self.assertRaises(http.Failed) as raised:
                    http.post(url, b"x", {}, opener=Opener(error=error))
                self.assertEqual((raised.exception.word, raised.exception.status), (word, status))
                self.assertNotIn("SECRET", str(raised.exception))
                self.assertIsNone(raised.exception.__cause__)
                self.assertTrue(raised.exception.__suppress_context__)
        for status, word in ((204, "2xx"), (301, "4xx"), (404, "4xx"), (500, "5xx")):
            with self.subTest(status=status):
                if word == "2xx":
                    self.assertEqual(http.post(url, b"x", {}, opener=Opener(Reply(status))), "2xx")
                else:
                    with self.assertRaises(http.Failed) as raised:
                        http.post(url, b"x", {}, opener=Opener(Reply(status)))
                    self.assertEqual(raised.exception.word, word)

    def test_the_real_opener_verifies_and_follows_no_redirect(self):
        made = http.make_opener()
        handlers = {type(handler) for handler in made.handlers}
        self.assertIn(http._NoRedirect, handlers)
        self.assertNotIn(urllib.request.HTTPRedirectHandler, handlers)
        https = next(handler for handler in made.handlers if isinstance(handler, urllib.request.HTTPSHandler))
        context = https._context
        self.assertEqual((context.verify_mode, context.check_hostname), (ssl.CERT_REQUIRED, True))
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertIsNone(http._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://x.example.com"))


if __name__ == "__main__":
    unittest.main()

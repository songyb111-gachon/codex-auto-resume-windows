"""The loopback API and web view (local_api, local_api_actions, v0.6.22, plans/v0619-design/D-remote.md; courier/api.py,
courier/page.py, control/remote.py).

Every test here talks to a real server on a real socket: 127.0.0.1, a port the system picks, closed at the end. The
token is a fake Credential Manager's, the clock the test's own, the home a temporary folder, and what the control layer
answers is either a stand-in that notes each call or core's real Control on that home. No other host is ever reached.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import re
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import control as core_control, statusfile  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from codex_auto_resume_advanced.control import remote  # noqa: E402
from codex_auto_resume_advanced.courier import api, page  # noqa: E402
from codex_auto_resume_advanced.registry import LOCAL_API, LOCAL_API_ACTIONS, PUSH_NOTICES, Registry  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402

TOKEN = "a-token-made-up-for-the-test-0123456789abcdef"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
THREAD_2 = "0a1b2c3d-0001-7000-8000-000000000002"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
KEY = "a" * 64
KEY_2 = "b" * 64
# The design's table (D-remote.md), route by route: the method, and whether it changes anything.
DESIGN = {"/": ("GET", False), "/status.json": ("GET", False), "/metrics": ("GET", False), "/pending": ("GET", False),
          "/pause": ("POST", True), "/resume-off": ("POST", True), "/cancel/": ("POST", True)}
# What no channel may ever do, as routes someone would try.
NEVER = ("/send", "/send-now", "/send_now", "/chat", "/message", "/prompt", "/steer", "/give-back", "/attempts",
         "/settings", "/options", "/arm", "/disarm", "/resume", "/recovery-on", "/continue/1", "/token", "/words")


class Secrets:
    """Credential Manager as local_api sees it: one token."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.reads = 0

    def read(self, capability, name):
        assert (capability, name) == ("local_api", "token")
        self.reads += 1
        return self.token

    def write(self, capability, name, secret):
        assert (capability, name) == ("local_api", "token")
        self.token = secret


class Layer:
    """Core's control layer as the API uses it, noting what it is asked."""

    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []
        self.watching = True

    def _open(self, *, legacy_ok=False):
        raise AssertionError("the tests answer reads through patched functions")

    def set_enabled(self, enabled):
        self.calls.append(("set_enabled", enabled))
        return {"enabled": enabled}

    def cancel_interruption(self, key, *, actor="gui"):
        self.calls.append(("cancel", key, actor))
        return {"changed": True}


def row(key=KEY, thread=THREAD, state="waiting_reset"):
    return {"interruption_id": key, "thread_id": thread, "state": state, "category": "usage_limit", "reset_at": ac.NOW + 60,
            "next_check_at": None, "title": "a title that must never be served", "cwd": "C:/never/served"}


class ServerCase(ac.AdvancedCase):
    """A real server, its service answering from a stand-in layer and a fake Credential Manager."""
    LAN = False
    ACTIONS = True

    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(LOCAL_API, LOCAL_API_ACTIONS)
        self.rt.arming.catalogs = statement.CATALOGS
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        if self.ACTIONS:
            self.assertTrue(self.arm(self.rt, "local_api_actions")["done"])
        self.layer, self.secrets = Layer(), Secrets()
        self.service = api.Service(self.rt, 0, self.LAN, layer=self.layer, secrets=self.secrets, clock=lambda: self.now)
        self.running = api.start(self.rt, 0, False, service=self.service, clock=lambda: self.now)
        self.addCleanup(self.running.close)
        self.port = self.running.port

    def ask(self, path, method="GET", *, token=TOKEN, host=None, body=None, headers=None):
        """One request as a client sends it: (status, headers, body)."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name in ([] if host is False else host if isinstance(host, list) else
                         [host or "127.0.0.1:%d" % self.port]):
                connection.putheader("Host", name)
            if token is not None:
                connection.putheader("Authorization", "Bearer " + token)
            for name, value in (headers or {}).items():
                connection.putheader(name, value)
            if body is not None:
                connection.putheader("Content-Length", str(len(body)))
            connection.endheaders()
            if body is not None:
                connection.send(body)
            reply = connection.getresponse()
            return reply.status, dict(reply.getheaders()), reply.read()
        finally:
            connection.close()

    def status(self, *arguments, **keywords):
        return self.ask(*arguments, **keywords)[0]


class TableTests(unittest.TestCase):
    def test_every_route_is_the_designs_and_only_three_change_anything(self):
        """Fails when a route is added to the table without the design saying so."""
        self.assertEqual(api.ROUTES, DESIGN)

    def test_a_route_that_would_send_chat_or_change_a_setting_is_no_route(self):
        for path in NEVER:
            self.assertIsNone(api.route_of(path), path)

    def test_only_a_task_s_place_is_taken_after_cancel(self):
        for path in ("/cancel/1", "/cancel/9999"):
            self.assertEqual(api.route_of(path), "/cancel/", path)
        for path in ("/cancel/", "/cancel", "/cancel/0", "/cancel/01", "/cancel/10000", "/cancel/1/2", "/cancel/a",
                     "/cancel/" + KEY, "/cancel/-1", "/cancel/1%00"):
            self.assertIsNone(api.route_of(path), path)

    def test_the_address_is_loopback_unless_the_lan_is_asked_for(self):
        self.assertEqual(api.bind_address(False), "127.0.0.1")
        self.assertEqual(api.bind_address(True), "0.0.0.0")

    def test_the_host_is_this_server_by_its_own_name_or_on_the_lan_an_address(self):
        for header in ("127.0.0.1:47615", "localhost:47615", "LOCALHOST:47615"):
            self.assertTrue(api.host_allowed(header, 47615, False), header)
        for header in ("192.168.0.2:47615", "evil.example:47615", "127.0.0.1", "127.0.0.1:1", "localhost", "",
                       "127.0.0.1:47615:47615", "127.0.0.1.evil.example:47615", "[::1]:47615", None, 5):
            self.assertFalse(api.host_allowed(header, 47615, False), header)
        self.assertTrue(api.host_allowed("192.168.0.2:47615", 47615, True))
        for header in ("evil.example:47615", "my-pc:47615", "192.168.0.2:1", "[::1]:47615"):
            self.assertFalse(api.host_allowed(header, 47615, True), header)


class HostTests(ServerCase):
    def test_another_name_is_refused_421_even_with_the_token_and_no_data_goes_back(self):
        for host in ("evil.example:%d" % self.port, "evil.example", "127.0.0.1:1", "192.168.0.2:%d" % self.port):
            with self.subTest(host):
                status, _headers, body = self.ask("/status.json", host=host)
                self.assertEqual(status, 421)
                self.assertEqual(json.loads(body), {"error": "misdirected"})
                self.assertEqual(self.status("/", host=host), 421, "nor the page")

    def test_no_host_or_two_hosts_are_refused(self):
        self.assertEqual(self.status("/status.json", host=False), 421)
        good = "127.0.0.1:%d" % self.port
        self.assertEqual(self.status("/status.json", host=[good, "evil.example"]), 421)
        self.assertEqual(self.status("/status.json", host=["evil.example", good]), 421)


class TokenTests(ServerCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(remote, "status_document", lambda layer, now: {"format": "x"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_right_token_reads_and_anything_else_is_401(self):
        self.assertEqual(self.status("/status.json"), 200)
        for token in (None, "", "wrong", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "Bearer " + TOKEN):
            with self.subTest(token):
                status, headers, body = self.ask("/status.json", token=token)
                self.assertEqual(status, 401)
                self.assertEqual(headers.get("WWW-Authenticate"), "Bearer")
                self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_another_scheme_is_401(self):
        self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": "Basic " + TOKEN}), 401)
        self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": "bearer " + TOKEN}), 401)
        self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": TOKEN}), 401)

    def test_a_token_in_a_query_string_is_never_read(self):
        for path in ("/status.json?token=" + TOKEN, "/status.json?access_token=" + TOKEN, "/status.json?" + TOKEN):
            self.assertEqual(self.status(path, token=None), 401, path)

    def test_the_token_is_compared_in_constant_time(self):
        """Fails with the comparison made `==`: compare_digest is never called."""
        seen = []
        real = api.hmac.compare_digest

        def spy(left, right):
            seen.append((left, right))
            return real(left, right)
        with patch.object(api.hmac, "compare_digest", spy):
            self.assertEqual(self.status("/status.json", token="wrong"), 401)
            self.assertEqual(self.status("/status.json"), 200)
        self.assertEqual(seen, [(b"wrong", TOKEN.encode()), (TOKEN.encode(), TOKEN.encode())])

    def test_a_token_that_is_not_ascii_is_a_wrong_token_and_no_failure(self):
        self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": "Bearer \xff\xfe"}), 401)

    def test_with_no_token_kept_nothing_is_read(self):
        """Fails where an empty kept token compares equal to an empty one sent."""
        self.secrets.token = None
        self.assertEqual(self.status("/status.json", token=""), 401)
        self.assertEqual(self.status("/status.json"), 401)

    def test_a_new_token_makes_the_old_one_useless_at_once(self):
        self.assertEqual(self.status("/status.json"), 200)
        found = remote.api_token_new(self.rt, secrets=self.secrets)
        self.assertTrue(found["done"])
        self.assertEqual(self.status("/status.json"), 401)
        self.assertEqual(self.status("/status.json", token=self.secrets.token), 200)

    def test_the_page_alone_asks_no_token_and_carries_no_data(self):
        self.layer.calls.clear()
        status, headers, body = self.ask("/", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(self.secrets.reads, 0, "the page never reads the token")
        self.assertEqual(self.layer.calls, [])
        self.assertTrue(headers["Content-Type"].startswith("text/html"))


class LockTests(ServerCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(remote, "status_document", lambda layer, now: {"format": "x"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def wrong(self, times):
        for _ in range(times):
            self.assertEqual(self.status("/status.json", token="wrong"), 401)

    def test_ten_wrong_in_a_minute_close_it_for_five_minutes_for_everyone(self):
        """Fails with the gate reverted: the eleventh is another 401 and the right token reads."""
        self.wrong(10)
        for path, token in (("/status.json", TOKEN), ("/status.json", "wrong"), ("/", None), ("/nothing", TOKEN)):
            status, headers, _body = self.ask(path, token=token)
            self.assertEqual(status, 503, path)
            self.assertEqual(headers.get("Retry-After"), "300")
        self.now += api.LOCK_SECONDS - 1
        self.assertEqual(self.status("/status.json"), 503)
        self.now += 1
        self.assertEqual(self.status("/status.json"), 200)

    def test_requests_with_no_token_never_close_it(self):
        """R1 (the security review of 2026-11-06): fails with every refusal counted - ten requests any web page can send,
        an <img> or a no-cors fetch, with no Authorization at all, would lock the person's own scraper out for five minutes,
        again and again."""
        for _ in range(30):
            self.assertEqual(self.status("/status.json", token=None), 401)
            self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": "Basic " + TOKEN}), 401)
            self.assertEqual(self.status("/status.json", token=None, headers={"Authorization": "Bearer "}), 401)
        self.assertEqual(self.status("/status.json"), 200)
        self.assertNotIn("api.locked", [line["code"] for line in self.rt.state.journal(capability="local_api")])

    def test_nine_do_not(self):
        self.wrong(9)
        self.assertEqual(self.status("/status.json"), 200)

    def test_only_those_within_a_minute_count(self):
        self.wrong(9)
        self.now += api.LOCK_WINDOW
        self.wrong(9)
        self.assertEqual(self.status("/status.json"), 200)

    def test_the_lock_is_journalled_once_and_the_token_never(self):
        self.wrong(10)
        lines = [line["code"] for line in self.rt.state.journal(capability="local_api")]
        self.assertEqual(lines.count("api.locked"), 1)

    def test_a_right_token_does_not_clear_the_count(self):
        self.wrong(9)
        self.assertEqual(self.status("/status.json"), 200)
        self.wrong(1)
        self.assertEqual(self.status("/status.json"), 503)

    def test_wrong_host_and_unknown_paths_do_not_count(self):
        for _ in range(12):
            self.assertEqual(self.status("/status.json", token="wrong", host="evil.example"), 421)
            self.assertEqual(self.status("/nothing", token="wrong"), 404)
        self.assertEqual(self.status("/status.json"), 200)


class MethodTests(ServerCase):
    def test_a_path_that_is_no_route_is_404(self):
        for path in NEVER + ("/nothing", "/status", "/cancel", "/cancel/0", "/cancel/abc", "/.."):
            with self.subTest(path):
                self.assertEqual(self.status(path), 404)
                self.assertEqual(self.status(path, "POST", body=b"{}"), 404)
        self.assertEqual(self.layer.calls, [])

    def test_a_method_a_route_does_not_take_is_405_and_says_which_it_does(self):
        for route, (method, _action) in DESIGN.items():
            path = "/cancel/1" if route == "/cancel/" else route
            for other in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
                if other == method:
                    continue
                with self.subTest(path=path, method=other):
                    status, headers, _body = self.ask(path, other)
                    self.assertEqual(status, 405)
                    self.assertEqual(headers.get("Allow"), method)
        self.assertEqual(self.layer.calls, [])

    def test_a_body_over_the_limit_is_413_and_nothing_happens(self):
        self.assertEqual(self.status("/pause", "POST", body=b"x" * (api.MAX_BODY + 1)), 413)
        self.assertEqual(self.status("/cancel/1", "POST", body=b"x" * (api.MAX_BODY + 1)), 413)
        self.assertEqual(self.layer.calls, [])
        self.assertEqual(self.status("/pause", "POST", body=b"x" * api.MAX_BODY), 200, "at the limit it is taken")

    def test_a_length_that_is_no_number_is_refused(self):
        self.assertEqual(self.status("/pause", "POST", headers={"Content-Length": "many"}), 400)
        self.assertEqual(self.status("/pause", "POST", headers={"Content-Length": "-1"}), 413)
        self.assertEqual(self.layer.calls, [])

    def test_a_request_line_that_cannot_be_read_gets_one_closed_word_and_no_echo(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            raw.sendall(b"NONSENSE /" + TOKEN.encode() + b" HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            reply = raw.recv(4096)
        self.assertIn(b"501", reply.split(b"\r\n")[0])
        self.assertNotIn(TOKEN.encode(), reply)
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            raw.sendall(b"GET /" + TOKEN.encode() + b" SPDY/9 extra\r\n\r\n")
            reply = raw.recv(4096)
        self.assertNotIn(TOKEN.encode(), reply)


class SlowClientTests(ServerCase):
    def setUp(self):
        patcher = patch.object(api, "DEADLINE", 1.5)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_clients_that_trickle_a_byte_at_a_time_hold_no_slot_past_the_deadline(self):
        """R2 (the security review of 2026-11-06): fails with the deadline reverted - TIMEOUT is per read, so eight
        clients that send one byte every second hold all THREADS slots and everyone else is closed unanswered."""
        import threading
        import time
        stop = threading.Event()
        self.addCleanup(stop.set)
        holders = []
        for _ in range(api.THREADS):
            raw = socket.create_connection(("127.0.0.1", self.port), timeout=10)
            self.addCleanup(raw.close)
            holders.append(raw)

        def trickle(raw):
            for byte in b"GET /status.json HTTP/1.0\r\nX-Slow: " + b"a" * 200:
                if stop.is_set():
                    return
                try:
                    raw.sendall(bytes([byte]))
                except OSError:
                    return
                time.sleep(0.25)
        threads = [threading.Thread(target=trickle, args=(raw,), daemon=True) for raw in holders]
        for thread in threads:
            thread.start()
        time.sleep(api.DEADLINE + 1.5)
        with patch.object(remote, "status_document", lambda layer, now: {"format": "x"}):
            self.assertEqual(self.status("/status.json"), 200)
        stop.set()


class HeaderTests(ServerCase):
    def test_no_answer_carries_cors_a_cookie_or_a_version(self):
        with patch.object(remote, "status_document", lambda layer, now: {"format": "x"}):
            answers = [self.ask(path, method, token=token, headers={"Origin": "http://evil.example"})[1]
                       for path, method, token in (("/", "GET", None), ("/status.json", "GET", TOKEN),
                                                   ("/status.json", "GET", "wrong"), ("/status.json", "OPTIONS", TOKEN),
                                                   ("/nothing", "GET", TOKEN))]
        for headers in answers:
            lowered = {name.lower(): value for name, value in headers.items()}
            self.assertEqual([name for name in lowered if name.startswith("access-control-")], [])
            self.assertNotIn("set-cookie", lowered)
            self.assertEqual(lowered["server"], "codex-auto-resume")
            self.assertEqual(lowered["cache-control"], "no-store")
            self.assertEqual(lowered["x-content-type-options"], "nosniff")
            self.assertEqual(lowered["referrer-policy"], "no-referrer")

    def test_the_page_carries_its_content_security_policy(self):
        _status, headers, _body = self.ask("/", token=None)
        policy = headers["Content-Security-Policy"]
        self.assertEqual(policy, page.CSP)
        self.assertIn("default-src 'none'", policy)
        self.assertIn("script-src 'self' 'unsafe-inline'", policy)
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("http", policy)
        self.assertNotIn("*", policy)


class NothingLoggedTests(ServerCase):
    def test_no_request_reaches_stderr_stdout_or_the_journal(self):
        """Fails with log_message put back: http.server writes each request, with its address, to stderr."""
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "stderr", err), patch.object(sys, "stdout", out), \
                patch.object(remote, "status_document", lambda layer, now: 1 / 0):
            self.ask("/status.json?token=" + TOKEN, token="wrong")
            self.ask("/status.json")
            self.ask("/nothing")
            self.ask("/status.json", host="evil.example")
            with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
                raw.sendall(b"BAD\r\n\r\n")
                raw.recv(1024)
            with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
                raw.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1:%d\r\n\r\n" % self.port)
                raw.shutdown(socket.SHUT_RDWR)
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_a_failure_in_the_server_itself_is_not_printed_either(self):
        """Fails with handle_error put back: socketserver prints the client's address and a traceback to stderr."""
        err = io.StringIO()
        with patch.object(sys, "stderr", err), patch.object(api, "host_allowed", lambda *unused: 1 / 0):
            with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
                raw.sendall(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
                raw.recv(1024)
        self.assertEqual(err.getvalue(), "")

    def test_the_token_is_nowhere_in_the_state_file(self):
        with patch.object(remote, "status_document", lambda layer, now: {"format": "x"}):
            for _ in range(10):
                self.ask("/status.json", token=TOKEN + "x")
        self.rt.state.close()
        for path in Path(self.paths.state_dir).rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), path.name)


class ActionTests(ServerCase):
    def test_pause_and_resume_off_are_the_one_pause(self):
        """There is no remote resume: fails if /resume-off ever asks for anything but a pause."""
        for path in ("/pause", "/resume-off"):
            self.layer.calls.clear()
            status, _headers, body = self.ask(path, "POST")
            self.assertEqual(status, 200)
            self.assertEqual(self.layer.calls, [("set_enabled", False)])
            self.assertEqual(json.loads(body), {"done": True, "enabled": False})
        self.assertEqual([line["code"] for line in self.rt.state.journal(capability="local_api_actions")
                          if line["code"].startswith("apiact.")], ["apiact.paused", "apiact.paused"])

    def test_cancel_goes_by_the_list_it_was_read_on(self):
        rows = [row(), row(KEY_2, THREAD_2)]
        with patch.object(remote, "pending_rows", lambda layer: rows):
            listed = remote.pending(self.layer)
            status, _h, body = self.ask("/cancel/2", "POST", body=json.dumps({"snapshot": listed["snapshot"]}).encode())
        self.assertEqual(status, 200, body)
        self.assertEqual(self.layer.calls, [("cancel", KEY_2, "cli")])
        self.assertEqual(json.loads(body)["task"], "task 2")

    def test_a_list_that_changed_is_refused_list_again_and_nothing_is_cancelled(self):
        """Fails with resolve reverted to take the place alone: task 1 is now another recovery."""
        before = remote.snapshot([row(), row(KEY_2, THREAD_2)])
        with patch.object(remote, "pending_rows", lambda layer: [row(KEY_2, THREAD_2)]):
            status, _h, body = self.ask("/cancel/1", "POST", body=json.dumps({"snapshot": before}).encode())
        self.assertEqual((status, json.loads(body)), (409, {"error": "list_again"}))
        self.assertEqual(self.layer.calls, [])
        self.assertEqual([line["code"] for line in self.rt.state.journal(capability="local_api_actions")
                          if line["code"].startswith("apiact.")], ["apiact.list_again"])

    def test_no_snapshot_a_bad_one_or_a_place_past_the_list_is_refused_too(self):
        rows = [row()]
        now = remote.snapshot(rows)
        with patch.object(remote, "pending_rows", lambda layer: rows):
            for body in (b"", b"{}", json.dumps({"snapshot": "short"}).encode(), json.dumps({"snapshot": 5}).encode()):
                self.assertEqual(self.status("/cancel/1", "POST", body=body), 409, body)
            self.assertEqual(self.status("/cancel/2", "POST", body=json.dumps({"snapshot": now}).encode()), 409)
            self.assertEqual(self.status("/cancel/1", "POST", body=b"not json"), 400)
            self.assertEqual(self.status("/cancel/1", "POST", body=b"[1]"), 400)
        self.assertEqual(self.layer.calls, [])

    def test_a_query_string_cannot_name_a_task(self):
        rows = [row()]
        with patch.object(remote, "pending_rows", lambda layer: rows):
            status, _h, _b = self.ask("/cancel/1?task=9", "POST", body=json.dumps({"snapshot": remote.snapshot(rows)}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(self.layer.calls, [("cancel", KEY, "cli")])


class ActionsOffTests(ServerCase):
    ACTIONS = False

    def test_with_the_actions_off_each_is_403_and_nothing_happens(self):
        """Fails with the check reverted: a token that may only read could pause."""
        for path in ("/pause", "/resume-off", "/cancel/1"):
            status, _headers, body = self.ask(path, "POST", body=b"{}")
            self.assertEqual((status, json.loads(body)), (403, {"error": "not_on"}), path)
        self.assertEqual(self.layer.calls, [])

    def test_a_wrong_token_is_401_before_it_learns_whether_they_are_on(self):
        self.assertEqual(self.status("/pause", "POST", token="wrong"), 401)

    def test_turned_off_at_a_person_s_word_they_stop_at_once(self):
        self.assertTrue(self.arm(self.rt, "local_api_actions")["done"])
        self.assertEqual(self.status("/pause", "POST"), 200)
        self.rt.arming.disarm("local_api_actions", actor="dashboard")
        self.assertEqual(self.status("/pause", "POST"), 403)


class RealControlTests(ServerCase):
    """Core's own Control on the test's home: what is served is core's closed keys, and what is done is core's."""

    def setUp(self):
        super().setUp()
        self.paths.ensure()
        self.layer = core_control.Control(self.paths)
        self.service._layer = self.layer
        for name, value in (("watcher_running", False),):
            patcher = patch.object(core_control.Control, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.layer._open() as store:
            store.set_enabled(True, 100.0)
            for key, thread in ((KEY, THREAD), (KEY_2, THREAD_2)):
                store.register(dict(thread_id=thread, turn_id=TURN, completed_at=110.0, started_at=105.0, ordinal=2,
                                  interruption_id=key, reset_at=150.0, limit_type="codex.primary", uncertain=False,
                                  category="usage_limit"), 100.0)

    def test_status_is_the_status_file_s_keys_and_nothing_else(self):
        status, headers, body = self.ask("/status.json")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        found = json.loads(body)
        self.assertEqual(tuple(found), statusfile.KEYS)
        self.assertEqual(statusfile.clean(found), found, "exactly what the status file may hold")
        self.assertEqual(found["pending"], 2)
        self.assertEqual(found["recovery"], "on")

    def test_pending_is_task_n_its_public_code_and_next_check_and_nothing_else(self):
        """Fails where a row's id, thread, label or path reaches the answer."""
        status, _headers, body = self.ask("/pending")
        self.assertEqual(status, 200)
        found = json.loads(body)
        self.assertEqual(set(found), {"snapshot", "pending"})
        self.assertRegex(found["snapshot"], r"\A[0-9a-f]{16}\Z")
        self.assertEqual([entry["task"] for entry in found["pending"]], ["task 1", "task 2"])
        for entry in found["pending"]:
            self.assertEqual(set(entry), {"task", "state", "next_check_at"})
        for secret in (KEY.encode(), KEY_2.encode(), THREAD.encode(), TURN.encode()):
            self.assertNotIn(secret, body)

    def test_metrics_is_prometheus_text_of_the_same_numbers(self):
        status, headers, body = self.ask("/metrics")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain; version=0.0.4"))
        text = body.decode("utf-8")
        self.assertIn("codex_auto_resume_pending 2\n", text)
        self.assertIn("codex_auto_resume_recovery_on 1\n", text)
        self.assertIn("codex_auto_resume_watcher_running 0\n", text)
        for line in text.splitlines():
            self.assertRegex(line, r"^(# (HELP|TYPE) codex_auto_resume_[a-z_]+ .+|codex_auto_resume_[a-z_]+"
                                   r"(\{state=\"[a-z_]+\"\})? -?[0-9.]+)$")

    def test_pause_is_core_s_and_every_record_stays(self):
        self.assertEqual(self.status("/pause", "POST"), 200)
        found = json.loads(self.ask("/status.json")[2])
        self.assertEqual((found["recovery"], found["pending"]), ("paused", 2))

    def test_cancel_is_core_s_by_the_exact_record_and_the_list_moves_on(self):
        listed = json.loads(self.ask("/pending")[2])
        rows = remote.pending_rows(self.layer)
        target = rows[1]["interruption_id"]
        status, _h, body = self.ask("/cancel/2", "POST", body=json.dumps({"snapshot": listed["snapshot"]}).encode())
        self.assertEqual(status, 200, body)
        self.assertEqual([each["interruption_id"] for each in remote.pending_rows(self.layer)],
                         [rows[0]["interruption_id"]])
        self.assertNotEqual(target, rows[0]["interruption_id"])
        again = self.ask("/cancel/1", "POST", body=json.dumps({"snapshot": listed["snapshot"]}).encode())
        self.assertEqual(again[0], 409, "the list it was read on is gone")


class PageTests(unittest.TestCase):
    def setUp(self):
        self.html = page.render(statement.CATALOGS.catalog("en"), "en").decode("utf-8")

    def test_it_names_no_host_and_loads_nothing(self):
        self.assertEqual(re.findall(r"https?://|//[a-z0-9.-]+\.[a-z]{2,}", self.html), [])
        for loads in ("<link", "<img", "<iframe", "<object", "<embed", "src=", "href=", "@import", "url("):
            self.assertNotIn(loads, self.html)

    def test_it_has_no_inline_handler_and_builds_no_markup_from_what_it_reads(self):
        self.assertEqual(re.findall(r"\son[a-z]+\s*=", self.html), [])
        for markup in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function("):
            self.assertNotIn(markup, self.html)
        self.assertIn("textContent", self.html)

    def test_the_token_is_read_from_the_fragment_and_sent_only_as_a_header(self):
        self.assertIn("location.hash", self.html)
        self.assertIn('"Authorization": "Bearer " + token', self.html)
        for wrong in ("location.search", "localStorage", "sessionStorage", "document.cookie", "?token", "token="):
            self.assertNotIn(wrong, self.html)
        self.assertIn('referrerPolicy: "no-referrer"', self.html)
        self.assertIn('credentials: "omit"', self.html)

    def test_a_word_cannot_close_the_script_or_open_markup(self):
        made = page.render({"page.api.title": "</script><script>alert(1)</script>&<b>",
                            "page.api.watcher": "\"quote\\"}, "en").decode("utf-8")
        self.assertEqual(made.count("</script>"), 1)
        self.assertNotIn("<script>alert", made)
        self.assertNotIn("<b>", made)
        self.assertIn("&lt;/script&gt;", made, "the title's own element is escaped")

    def test_the_language_cannot_carry_markup(self):
        self.assertIn('lang="en"', page.render({}, '"><script>').decode("utf-8"))

    def test_every_word_is_in_every_language(self):
        keys = [key for key, _fallback in page.WORDS.values()]
        for key in keys:
            self.assertIn(key, statement.PAGE_KEYS)
        from codex_auto_resume import l10n
        for locale in l10n.LOCALES:
            table = statement.CATALOGS.own(locale)
            with self.subTest(locale):
                self.assertEqual([key for key in keys if not isinstance(table.get(key), str)], [])


class CardTests(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(LOCAL_API, LOCAL_API_ACTIONS)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets(None)

    def test_off_a_token_is_refused_and_the_card_reads_off(self):
        self.assertEqual(remote.api_token_new(self.rt, secrets=self.secrets)["refusal"], Refusal.NOT_ON)
        self.assertIsNone(self.secrets.token)
        view = remote.api_view(self.rt, secrets=self.secrets, running=lambda runtime: self.fail("off: not asked"))
        self.assertEqual((view["state"], view["token_saved"]), ("off", False))

    def test_the_card_s_read_never_carries_the_token_and_copy_does_only_when_asked(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        made = remote.api_token_new(self.rt, secrets=self.secrets)
        self.assertEqual(made["copy_url"], "http://127.0.0.1:47615/#" + self.secrets.token)
        self.assertGreaterEqual(len(self.secrets.token), 43, "32 bytes, url-safe")
        view = remote.api_view(self.rt, secrets=self.secrets, running=lambda runtime: True)
        self.assertNotIn(self.secrets.token, json.dumps(view))
        self.assertEqual(view["url"], "http://127.0.0.1:47615/")
        self.assertTrue(view["token_saved"])
        copied = remote.api_view(self.rt, copy=True, secrets=self.secrets, running=lambda runtime: True)
        self.assertEqual(copied["copy_url"], "http://127.0.0.1:47615/#" + self.secrets.token)
        self.assertNotIn("?", copied["copy_url"], "never in a query string")

    def test_copy_carries_nothing_while_another_program_holds_the_port_or_it_stopped(self):
        """R7 (the security review of 2026-11-06): fails with the state unread - the address would hand the token in its
        fragment to whatever page the program holding the port serves."""
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        self.secrets.token = TOKEN
        self.rt.state.counted("local_api", "port_taken")
        self.assertNotIn("copy_url", remote.api_view(self.rt, copy=True, secrets=self.secrets, running=lambda r: True))
        self.now += 1
        self.rt.state.counted("local_api", "started")
        self.assertIn("copy_url", remote.api_view(self.rt, copy=True, secrets=self.secrets, running=lambda r: True))
        with patch.object(remote, "_word", lambda runtime, on, alive: "stopped"):
            self.assertNotIn("copy_url", remote.api_view(self.rt, copy=True, secrets=self.secrets, running=lambda r: False))

    def test_copy_while_off_carries_nothing(self):
        self.secrets.token = TOKEN
        self.assertNotIn("copy_url", remote.api_view(self.rt, copy=True, secrets=self.secrets))

    def test_a_token_goes_to_credential_manager_and_nowhere_else(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        remote.api_token_new(self.rt, secrets=self.secrets)
        self.rt.state.close()
        for path in Path(self.paths.state_dir).rglob("*"):
            if path.is_file():
                self.assertNotIn(self.secrets.token.encode(), path.read_bytes(), path.name)

    def test_a_port_is_taken_from_the_options_and_only_a_user_s_port(self):
        self.assertTrue(self.arm(self.rt, "local_api")["done"])
        generation = self.rt.state.meta()["generation"]
        self.assertTrue(self.rt.arming.set_option("local_api", "api_port", 8123, generation=generation,
                                                  actor="dashboard")["done"])
        self.assertEqual(remote.port(self.rt), 8123)
        for port in (0, 80, 1023, 65536, "8000", True):
            generation = self.rt.state.meta()["generation"]
            self.assertFalse(self.rt.arming.set_option("local_api", "api_port", port, generation=generation,
                                                       actor="dashboard")["done"], port)
        self.assertEqual(remote.api_view(self.rt, secrets=self.secrets, running=lambda r: True)["url"],
                         "http://127.0.0.1:8123/")


class RegistryTests(unittest.TestCase):
    def test_a_registry_without_them_serves_nothing(self):
        """Their definitions are what the rest stands on: the actions need the server."""
        self.assertEqual(Registry((LOCAL_API, LOCAL_API_ACTIONS)).requires("local_api_actions"), ("local_api",))
        self.assertEqual(Registry((LOCAL_API, LOCAL_API_ACTIONS)).required_by("local_api"), ("local_api_actions",))
        self.assertEqual(PUSH_NOTICES.id, "push_notices")


if __name__ == "__main__":
    unittest.main()

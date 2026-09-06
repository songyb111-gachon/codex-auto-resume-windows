"""Failure classification and the display identity shown to a person.

Two invariants dominate this file:
  * an error this tool cannot place is `unknown`, and `unknown` is never retried;
  * a name shown to a person is never used to find a thread.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_auto_resume import failures
from codex_auto_resume.source import LocalSource, _label, detect

FIXTURE = {
    "thread_id": "0a1b2c3d-0001-7000-8000-000000000001",
    "turn_id": "0a1b2c3d-0002-7000-8000-000000000002",
    "status": "failed", "rollout_ordinal": 5,
    "started_at": 1788600000.0, "completed_at": 1788600100.0,
}


def failure(error):
    return dict(FIXTURE, error_json=json.dumps(error) if error is not None else None)


class TransientTests(unittest.TestCase):
    def test_structured_transient_codes(self):
        expected = {
            "httpConnectionFailed": "network_transient",
            "rateLimitExceeded": "rate_limit_transient",
            "serverOverloaded": "server_5xx",
            "internalServerError": "server_5xx",
            "responseStreamConnectionFailed": "stream_interrupted",
            "responseStreamDisconnected": "stream_interrupted",
        }
        for code, category in expected.items():
            with self.subTest(code=code):
                self.assertEqual(failures.classify(code), category)
                self.assertIn(category, failures.TRANSIENT)
                self.assertTrue(failures.is_recoverable(category))

    def test_http_status_maps_to_the_right_bucket(self):
        cases = {408: "timeout", 425: "timeout", 429: "rate_limit_transient",
                 500: "server_5xx", 502: "server_5xx", 503: "server_5xx", 504: "server_5xx"}
        for status, category in cases.items():
            with self.subTest(status=status):
                self.assertEqual(failures.classify({"httpStatusCode": status}), category)
                self.assertEqual(failures.classify({"type": "httpStatusCode", "httpStatusCode": status}), category)

    def test_transport_failures_without_a_code_use_the_message_fallback(self):
        cases = {
            "connection reset by peer": "network_transient",
            "connection refused": "network_transient",
            "temporary failure in name resolution": "network_transient",
            "tls handshake failed": "network_transient",
            "broken pipe": "network_transient",
            "request timed out": "timeout",
            "context deadline exceeded": "timeout",
            "stream disconnected": "stream_interrupted",
        }
        for message, category in cases.items():
            with self.subTest(message=message):
                self.assertEqual(failures.classify(None, message), category)


class TerminalTests(unittest.TestCase):
    def test_structured_terminal_codes_are_never_retried(self):
        expected = {
            "contextWindowExceeded": "terminal_invalid",
            "sessionBudgetExceeded": "terminal_invalid",
            "badRequest": "terminal_invalid",
            "cyberPolicy": "terminal_policy",
            "misalignmentPolicyViolation": "terminal_policy",
            "unauthorized": "terminal_auth",
            "responseTooManyFailedAttempts": "terminal_failure",
            "threadRollbackFailed": "terminal_failure",
            "sandboxError": "terminal_failure",
            "activeTurnNotSteerable": "terminal_failure",
        }
        for code, category in expected.items():
            with self.subTest(code=code):
                self.assertEqual(failures.classify(code), category)
                self.assertIn(category, failures.TERMINAL)
                self.assertFalse(failures.is_recoverable(category))

    def test_permanent_http_statuses_are_never_retried(self):
        for status in (400, 401, 403, 404, 409, 413, 422):
            with self.subTest(status=status):
                category = failures.classify({"httpStatusCode": status})
                self.assertIn(category, failures.TERMINAL)
                self.assertFalse(failures.is_recoverable(category))

    def test_authentication_is_terminal_not_a_retry_budget(self):
        # The reference project retries auth with an attempt cap. This one does not:
        # a login problem needs a person, and retrying just burns attempts.
        self.assertEqual(failures.classify("unauthorized"), "terminal_auth")
        self.assertEqual(failures.classify({"httpStatusCode": 401}), "terminal_auth")
        self.assertEqual(failures.classify({"httpStatusCode": 403}), "terminal_auth")


class UnknownTests(unittest.TestCase):
    def test_unknown_is_never_recoverable(self):
        self.assertFalse(failures.is_recoverable(failures.UNKNOWN))

    def test_anything_unrecognised_is_unknown(self):
        for value in (None, "", "somethingNew", 12, [], {}, {"type": "brandNewVariant"},
                      {"httpStatusCode": "503"}, {"httpStatusCode": 999}, True):
            with self.subTest(value=repr(value)):
                self.assertEqual(failures.classify(value), failures.UNKNOWN)

    def test_a_structured_code_is_never_overridden_by_message_text(self):
        # A permanent error whose message happens to mention a timeout must stay permanent.
        self.assertEqual(failures.classify("badRequest", "connection reset, timed out"), "terminal_invalid")
        self.assertEqual(failures.classify("unauthorized", "stream disconnected"), "terminal_auth")

    def test_message_fallback_does_not_apply_when_a_code_is_present(self):
        self.assertEqual(failures.classify("somethingNew", "connection reset"), failures.UNKNOWN)

    def test_message_fallback_ignores_unbounded_text(self):
        self.assertEqual(failures.classify(None, "timed out" + "x" * 8000), failures.UNKNOWN)

    def test_every_mapped_code_names_a_real_category(self):
        for category in failures.CODES.values():
            self.assertIn(category, failures.CATEGORIES)


class DetectionGateTests(unittest.TestCase):
    def test_only_recoverable_categories_are_ever_registered(self):
        for code in ("badRequest", "unauthorized", "contextWindowExceeded", "somethingNew"):
            with self.subTest(code=code):
                self.assertIsNone(detect(failure({"codexErrorInfo": code})))
        for code in ("usageLimitExceeded", "serverOverloaded", "httpConnectionFailed"):
            with self.subTest(code=code):
                self.assertIsNotNone(detect(failure({"codexErrorInfo": code})))

    def test_no_error_text_survives_detection(self):
        secret = "workspace /home/secret/project failed: token sk-abc123"
        found = detect(failure({"codexErrorInfo": "serverOverloaded", "message": secret}))
        self.assertNotIn("secret", repr(found))
        self.assertNotIn("sk-abc", repr(found))
        self.assertNotIn("message", found)


class DisplayLabelTests(unittest.TestCase):
    def test_a_label_is_never_multiline_or_unbounded(self):
        self.assertIsNone(_label("first line\nsecond line"))
        self.assertIsNone(_label("tabbed\tvalue"))
        self.assertIsNone(_label(""))
        self.assertIsNone(_label("   "))
        self.assertIsNone(_label(None))
        self.assertLessEqual(len(_label("x" * 5000)), 72)

    def test_a_normal_title_survives_unchanged(self):
        for value in ("auto-resume 프로젝트 비교", "Payment retry refactor", "example-project"):
            self.assertEqual(_label(value), value)


class IdentitySourceTests(unittest.TestCase):
    """`identity()` reads Codex state read-only, and must never read prompt text."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.thread = FIXTURE["thread_id"]

    def build(self, **columns):
        path = self.home / "state_5.sqlite"
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT,
                          thread_source TEXT, archived INTEGER, history_mode TEXT,
                          name TEXT, title TEXT, preview TEXT, first_user_message TEXT,
                          cwd TEXT, project_id TEXT)""")
            db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT)")
            if columns.get("project_name"):
                db.execute("INSERT INTO projects VALUES ('p1', ?)", (columns["project_name"],))
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                self.thread, "", "vscode", "user", 0, "paginated",
                columns.get("name"), columns.get("title"), columns.get("preview"),
                columns.get("first_user_message"), columns.get("cwd"),
                "p1" if columns.get("project_name") else None))
            db.commit()
        return LocalSource(self.home)

    def test_priority_title_then_project_then_cwd(self):
        source = self.build(name="Retry path refactor", project_name="example-project", cwd=r"C:\work\repo")
        self.assertEqual(source.identity(self.thread),
                         {"name": "Retry path refactor", "project": "example-project", "cwd_basename": "repo"})

    def test_missing_title_leaves_project_and_cwd(self):
        source = self.build(project_name="example-project", cwd=r"C:\work\repo")
        identity = source.identity(self.thread)
        self.assertIsNone(identity["name"])
        self.assertEqual(identity["project"], "example-project")

    def test_only_cwd_remains(self):
        source = self.build(cwd=r"C:\work\my-project")
        self.assertEqual(source.identity(self.thread)["cwd_basename"], "my-project")

    def test_everything_missing_is_not_an_error(self):
        source = self.build()
        self.assertEqual(source.identity(self.thread),
                         {"name": None, "project": None, "cwd_basename": None})

    def test_prompt_bearing_columns_are_never_read(self):
        # On the real schema `title`, `preview` and `first_user_message` hold the raw
        # first prompt, so none of them may reach a label.
        secret = "SECRET PROMPT do not display"
        source = self.build(title=secret, preview=secret, first_user_message=secret,
                            cwd=r"C:\work\repo")
        identity = source.identity(self.thread)
        self.assertNotIn("SECRET", repr(identity))
        self.assertIsNone(identity["name"])

    def test_a_multiline_name_is_dropped_rather_than_shown(self):
        source = self.build(name="line one\nline two", cwd=r"C:\work\repo")
        self.assertIsNone(source.identity(self.thread)["name"])

    def test_an_unknown_thread_yields_no_labels(self):
        source = self.build(name="Something")
        self.assertEqual(source.identity("0a1b2c3d-9999-7000-8000-000000009999"),
                         {"name": None, "project": None, "cwd_basename": None})

    def test_extended_length_paths_do_not_leak_the_prefix(self):
        source = self.build(cwd="\\\\?\\C:\\work\\repo")
        self.assertEqual(source.identity(self.thread)["cwd_basename"], "repo")


if __name__ == "__main__":
    unittest.main()

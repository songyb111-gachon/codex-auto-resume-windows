"""The compatibility report as a file (report/document.py): the reader's body in codex-compat-reporter's
envelope, naming this product as its writer, and the self-check every report passes.

The homes are reportfixtures'; golden/report/ holds, beside each body, the envelope 1.5.0's own
`build` wrote around it (its keys in order, the format, the attribution, the note). The project's own
reader of an arriving report is build/community_report.py, and every document here passes it.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reportfixtures as fixtures  # noqa: E402

from codex_auto_resume_advanced.report import document, evidence, records  # noqa: E402
from codex_auto_resume_advanced.report.document import DocumentError, DocumentRefusal  # noqa: E402

GOLDEN = HERE / "golden" / "report"
VERSION = "0.6.13-beta"
WINDOWS = "10.0.26200"


def receiver():
    spec = importlib.util.spec_from_file_location("community_report_for_document_tests",
                                                  fixtures.ROOT / "build" / "community_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def body(name) -> dict:
    home, asked = fixtures.scenario(name)
    try:
        with fixtures.isolated(home):
            return records.read(home.paths, home.codex, asked, now=fixtures.NOW, view=home.raw_view)["body"]
    finally:
        home.close()


def made(found, login=fixtures.LOGIN, **options) -> dict:
    options = dict(dict(product_version=VERSION, windows=WINDOWS, now=fixtures.NOW), **options)
    return document.assemble(found, login, **options)


class AssemblyTests(unittest.TestCase):
    def test_it_is_the_reporters_file_but_for_who_wrote_it(self):
        for name in fixtures.SCENARIOS:
            with self.subTest(name):
                golden = json.loads((GOLDEN / ("%s.json" % name)).read_text(encoding="ascii"))
                written = made(body(name))
                self.assertEqual(list(written), golden["keys"], "the reporter's keys, in its order")
                for field, value in golden["envelope"].items():
                    self.assertEqual(written[field], value)
                for field, value in golden["body"].items():
                    self.assertEqual(json.dumps(written[field]), json.dumps(value))
                self.assertEqual(written["recorded_at"], "2026-09-30T12:00:00Z")
                self.assertEqual(written["recorded_by"],
                                 "Codex Auto Resume 0.6.13-beta (advanced edition), on a contributor's Windows machine")
                self.assertEqual(written["reporter"], {"github_login": "ExampleUser", "tool": "codex-auto-resume",
                                                       "tool_version": VERSION, "product_version": VERSION,
                                                       "windows": WINDOWS})

    def test_the_project_takes_every_one_as_it_is(self):
        """build/community_report.py, as the pull request's check runs it: nothing refused, and
        nothing its recomputation would change."""
        project = receiver()
        for name in fixtures.SCENARIOS:
            with self.subTest(name):
                raw = document.encode(made(body(name)))
                report, refused, recomputed = project.inspect(raw, author=fixtures.LOGIN, now=fixtures.NOW + 60)
                self.assertEqual((refused, recomputed), ([], []))
                self.assertEqual(raw, project.encode(report), "the project's own bytes for it")
                self.assertEqual(project.filed_copy(report)["recorded_by"],
                                 project.OURS["recorded_by"] % ("codex-auto-resume", VERSION))

    def test_the_bytes_are_ascii_two_space_json_with_one_newline(self):
        written = made(body("state4_ledger2"))
        raw = document.encode(written)
        self.assertTrue(raw.isascii() and raw.endswith(b"}\n") and not raw.endswith(b"\n\n"))
        self.assertEqual(raw, (json.dumps(written, indent=2, ensure_ascii=True) + "\n").encode("ascii"))
        self.assertEqual(document.check(written), raw)
        self.assertEqual(hashlib.sha256(document.check(written)).hexdigest(), hashlib.sha256(raw).hexdigest())

    def test_the_product_version_and_windows_are_this_installations_own(self):
        from codex_auto_resume import config
        if sys.platform != "win32" or config.version() == "unknown":
            self.skipTest("an installation's own version, on Windows")
        written = document.assemble(body("state4_empty"), fixtures.LOGIN, now=fixtures.NOW)
        self.assertEqual(written["reporter"]["product_version"], config.version())
        version = sys.getwindowsversion()
        self.assertEqual(written["reporter"]["windows"], "%d.%d.%d" % (version.major, version.minor, version.build))

    def test_platform_is_never_asked(self):
        """It can start a console program to answer (tests/test_no_console_windows.py)."""
        tree = ast.parse((fixtures.ROOT / "advanced" / "src" / "codex_auto_resume_advanced" / "report"
                          / "document.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertNotIn("platform", imported)


class LoginTests(unittest.TestCase):
    def test_only_a_login_the_project_can_file_under(self):
        found = body("state4_empty")
        for login, code in (("-bad-", DocumentRefusal.LOGIN_INVALID), ("", DocumentRefusal.LOGIN_INVALID),
                            ("a" * 40, DocumentRefusal.LOGIN_INVALID), ("two words", DocumentRefusal.LOGIN_INVALID),
                            (None, DocumentRefusal.LOGIN_INVALID), ("dou--ble", DocumentRefusal.LOGIN_INVALID),
                            ("nul", DocumentRefusal.LOGIN_RESERVED), ("COM1", DocumentRefusal.LOGIN_RESERVED),
                            ("songyb111-gachon", DocumentRefusal.LOGIN_OWNER),
                            ("SongYB111-Gachon", DocumentRefusal.LOGIN_OWNER)):
            with self.subTest(login=login):
                with self.assertRaises(document.DocumentRefused) as raised:
                    made(found, login)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.args, (str(code),))
        for login in ("ExampleUser", "a", "a-b", "com10", "x" * 39):
            self.assertEqual(made(found, login)["reporter"]["github_login"], login)


class SelfCheckTests(unittest.TestCase):
    def setUp(self):
        self.written = made(body("state4_ledger2"))

    def changed(self, change):
        broken = copy.deepcopy(self.written)
        change(broken)
        return broken

    def test_more_than_the_project_takes_is_refused(self):
        many = self.changed(lambda report: report.update(records=report["records"][:1] * (evidence.MAX_RECORDS + 1)))
        with self.assertRaises(document.DocumentRefused) as raised:
            document.check(many)
        self.assertEqual(raised.exception.code, DocumentRefusal.TOO_MANY_RECORDS)
        with mock.patch.object(document, "MAX_BYTES", len(document.encode(self.written)) - 1):
            with self.assertRaises(document.DocumentRefused) as raised:
                document.check(self.written)
        self.assertEqual(raised.exception.code, DocumentRefusal.TOO_LARGE)

    def test_anything_but_the_format_exactly_is_a_fault(self):
        faults = [
            lambda r: r.update(extra=1),
            lambda r: r.pop("note"),
            lambda r: r.update(note="Sent by me"),
            lambda r: r.update(format="codex-auto-resume-compat-evidence/2"),
            lambda r: r.update(codex_version="codex-cli 00.158.0"),
            lambda r: r.update(verdict="GREAT"),
            lambda r: r.update(recorded_at="yesterday"),
            lambda r: r["reporter"].update(tool="codex-compat-reporter"),
            lambda r: r["reporter"].update(tool_version="1.5.0"),
            lambda r: r["reporter"].update(windows="6.1.7601"),
            lambda r: r["reporter"].update(product_version="C:\\Users\\ExampleUser"),
            lambda r: r["reporter"].update(machine="x"),
            lambda r: r["attribution"].update(window=["a", "b"]),
            lambda r: r["local_checks"].update(covers=["queue_withdraw"]),
            lambda r: r["records"][0].update(state="C:\\Users\\ExampleUser\\secret.txt"),
            lambda r: r["records"][0].update(reason="Hello, world"),
            lambda r: r["records"][0].update(detected_at=1790000000),
            lambda r: r["records"][0].update(gates_passed=True),
            lambda r: r["records"][0].update(text="a private sentence"),
            lambda r: r["records"][0].update(progress_items={"agentMessage": 1}),
            lambda r: r["capabilities"].pop("usage_probe"),
            lambda r: r["capabilities"]["usage_probe"].update(level="GREAT"),
            lambda r: r["capabilities"]["usage_probe"].update(confirmed=-1),
        ]
        for number, change in enumerate(faults):
            with self.subTest(number):
                with self.assertRaises(DocumentError) as raised:
                    document.check(self.changed(change))
                for leak in ("ExampleUser", "secret", "Hello", "private"):
                    self.assertNotIn(leak, str(raised.exception))

    def test_the_sentences_are_the_reporters_word_for_word(self):
        golden = json.loads((GOLDEN / "state4_ledger2.json").read_text(encoding="ascii"))
        self.assertEqual(document.RULE, golden["envelope"]["attribution"]["rule"])
        self.assertEqual(document.NOTE, golden["envelope"]["note"])
        self.assertEqual(document.FORMAT, golden["envelope"]["format"])
        project = receiver()
        self.assertEqual((document.FORMAT, document.MAX_BYTES, document.TOOL),
                         (project.FORMAT, project.MAX_BYTES, project.PRODUCT_TOOL))
        self.assertEqual(document.RESERVED, project.RESERVED)
        self.assertEqual(document.LOGIN.pattern, r"\A%s\Z" % project.LOGIN.pattern)

    def test_the_closed_words_keep_the_editions_rule(self):
        for member in DocumentRefusal:
            self.assertEqual(member.name, member.value.upper())
        self.assertEqual(DocumentRefusal.TOO_MANY_RECORDS.value, records.ReadRefusal.TOO_MANY_RECORDS.value,
                         "one word for one refusal, whoever finds it")


if __name__ == "__main__":
    unittest.main()

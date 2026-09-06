"""The detection-time Windows notification and its opt-out button.

The notification is the only control that can be offered at the moment a usage limit
is hit, so it must never be able to *cause* a resume, and never be able to stop the
watcher from working when it fails.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import cli, messages, notify, startup
from codex_auto_resume.store import Store

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
INTERRUPTION = "a1" * 32


class CancelUriTests(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(notify.parse_cancel_uri(notify.cancel_uri(INTERRUPTION)), INTERRUPTION)

    def test_only_the_cancel_action_is_understood(self):
        # There must be no URI that can start, queue or resume anything.
        for action in ("resume", "send", "queue", "enable", ""):
            uri = "%s:%s?i=%s" % (notify.SCHEME, action, INTERRUPTION)
            with self.subTest(action=action):
                self.assertIsNone(notify.parse_cancel_uri(uri))

    def test_hostile_and_malformed_uris_are_rejected(self):
        cases = [
            "https://example.test/cancel?i=" + INTERRUPTION,      # wrong scheme
            "codex-auto-resume:cancel",                            # no id
            "codex-auto-resume:cancel?i=",                         # empty id
            "codex-auto-resume:cancel?i=" + "z" * 64,             # not hex
            "codex-auto-resume:cancel?i=" + "a" * 63,             # too short
            "codex-auto-resume:cancel?i=" + "a" * 65,             # too long
            "codex-auto-resume:cancel?i=%s&i=%s" % (INTERRUPTION, "b" * 64),   # ambiguous
            "codex-auto-resume:cancel?i=../../etc/passwd",
            "", None, 12345,
        ]
        for uri in cases:
            with self.subTest(uri=repr(uri)[:48]):
                self.assertIsNone(notify.parse_cancel_uri(uri))

    def test_uppercase_id_is_accepted_as_the_same_capability(self):
        uri = "%s:cancel?i=%s" % (notify.SCHEME, INTERRUPTION.upper())
        self.assertEqual(notify.parse_cancel_uri(uri), INTERRUPTION)


class ToastPayloadTests(unittest.TestCase):
    def test_text_is_xml_escaped(self):
        xml = notify._toast_xml('a"b&c<d>', "body & more", 'btn"x', "codex-auto-resume:cancel?i=1&j=2")
        self.assertNotIn("a\"b&c<d>", xml)
        self.assertIn("&amp;", xml)
        self.assertIn("&lt;d&gt;", xml)

    def test_button_is_omitted_without_a_uri(self):
        self.assertNotIn("<actions>", notify._toast_xml("t", "b", None, None))
        self.assertNotIn("<actions>", notify._toast_xml("t", "b", "press me", None))

    def test_command_is_passed_as_encoded_base64_never_as_shell_text(self):
        with patch.object(notify, "_powershell", return_value="powershell.exe"), \
             patch.object(subprocess, "run", return_value=MagicMock(returncode=0)) as run:
            self.assertTrue(notify.show("t", "'; Remove-Item C:\\ -Recurse #", button=None, uri=None))
        argv = run.call_args.args[0]
        self.assertIn("-EncodedCommand", argv)
        self.assertIs(run.call_args.kwargs["shell"], False)
        # Nothing user-influenced may appear literally on the command line.
        self.assertFalse(any("Remove-Item" in part for part in argv))

    @staticmethod
    def _embedded_xml(argv):
        """Recover the toast document from the script that was actually sent."""
        import base64
        script = base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
        line = next(l for l in script.splitlines() if "LoadXml(" in l)
        literal = line[line.index("(") + 1:line.rindex(")")]
        assert literal.startswith("'") and literal.endswith("'"), literal
        return literal[1:-1].replace("''", "'")

    def test_the_embedded_document_is_still_valid_xml(self):
        # Regression: the XML was once escaped as if it were an XML *attribute*, which
        # turned its own angle brackets into entities and made every toast fail.
        from xml.etree import ElementTree

        with patch.object(notify, "_powershell", return_value="powershell.exe"),              patch.object(subprocess, "run", return_value=MagicMock(returncode=0)) as run:
            notify.show("title", "body", button="press", uri=notify.cancel_uri(INTERRUPTION))
        root = ElementTree.fromstring(self._embedded_xml(run.call_args.args[0]))
        self.assertEqual(root.tag, "toast")
        action = root.find("./actions/action")
        self.assertEqual(action.get("activationType"), "protocol")
        self.assertEqual(action.get("arguments"), notify.cancel_uri(INTERRUPTION))

    def test_a_quote_in_the_text_cannot_break_out_of_the_script(self):
        from xml.etree import ElementTree

        nasty = "it's ' '' fine'"
        with patch.object(notify, "_powershell", return_value="powershell.exe"),              patch.object(subprocess, "run", return_value=MagicMock(returncode=0)) as run:
            notify.show("t", nasty)
        root = ElementTree.fromstring(self._embedded_xml(run.call_args.args[0]))
        self.assertEqual(root.findall("./visual/binding/text")[1].text, nasty)

    def test_powershell_literal_doubles_embedded_quotes(self):
        self.assertEqual(notify._ps_literal("a'b"), "'a''b'")
        self.assertEqual(notify._ps_literal("<x>"), "'<x>'")

    def test_a_failing_or_missing_powershell_is_not_an_error(self):
        with patch.object(notify, "_powershell", return_value=None):
            self.assertFalse(notify.show("t", "b"))
        with patch.object(notify, "_powershell", return_value="powershell.exe"), \
             patch.object(subprocess, "run", side_effect=OSError("nope")):
            self.assertFalse(notify.show("t", "b"))
        with patch.object(notify, "_powershell", return_value="powershell.exe"), \
             patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("ps", 20)):
            self.assertFalse(notify.show("t", "b"))

    def test_no_conversation_content_is_disclosed(self):
        captured = {}
        with patch.object(notify, "show", side_effect=lambda t, b, **k: captured.update(title=t, body=b, **k) or True):
            notify.scheduled(THREAD, INTERRUPTION, 1788645827.0)
        # A shortened id only; never the full thread, prompt text or error text.
        self.assertIn(THREAD[:8], captured["body"])
        self.assertNotIn(THREAD, captured["body"])
        self.assertEqual(captured["uri"], notify.cancel_uri(INTERRUPTION))

    def test_missing_reset_time_still_produces_a_message(self):
        with patch.object(notify, "show", return_value=True) as show:
            notify.scheduled(THREAD, INTERRUPTION, None)
        body = show.call_args.args[1]
        self.assertNotIn("{", body)


class ProtocolRegistrationTests(unittest.TestCase):
    def setUp(self):
        from test_cli import FakeWinreg    # the shared key-tree fake
        self.fake = FakeWinreg()
        guard = patch.object(startup, "_winreg", return_value=self.fake)
        guard.start()
        self.addCleanup(guard.stop)

    def command(self, home=r"C:\proj") -> str:
        return startup.protocol_command_line(Path(home) / "src" / "auto_resume.py", Path(home),
                                             launcher=Path(r"C:\Py\pythonw.exe"))

    def test_register_is_idempotent_and_removable(self):
        command = self.command()
        self.assertTrue(startup.install_protocol(command))
        self.assertFalse(startup.install_protocol(command))
        self.assertEqual(startup.protocol_value(), command)
        self.assertTrue(startup.uninstall_protocol())
        self.assertFalse(startup.uninstall_protocol())
        self.assertIsNone(startup.protocol_value())

    def test_registration_is_confined_to_the_current_user(self):
        startup.install_protocol(self.command())
        for path in self.fake.keys:
            self.assertTrue(path.startswith("Software\\Classes\\" + startup.PROTOCOL_SCHEME)
                            or path == startup.RUN_KEY, path)

    def test_command_carries_the_home_and_only_the_activate_verb(self):
        argv = startup.parse_command(self.command())
        self.assertIn("--home", argv)
        self.assertIn("activate", argv)
        self.assertEqual(argv[-1], "%1")
        for forbidden in ("run", "enable", "queue", "--last"):
            self.assertNotIn(forbidden, argv)

    def test_ownership_decides_whether_uninstall_may_remove_it(self):
        command = self.command(r"C:\proj")
        self.assertTrue(startup.belongs_to(command, Path(r"C:\proj")))
        self.assertFalse(startup.belongs_to(command, Path(r"C:\other")))


class ActivationTests(unittest.TestCase):
    """`activate` is reached from Windows, so its input is untrusted."""

    def _args(self, uri, home):
        args = cli.build_parser().parse_args(["--home", str(home), "--quiet", "activate", uri])
        return args

    def run_activate(self, uri, home):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(notify, "cancelled", return_value=True):
            code = cli.cmd_activate(self._args(uri, home))
        return code, out.getvalue()

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        # Registered last so it runs first: an open log handler locks the file on Windows.
        self.addCleanup(self._close)

    @staticmethod
    def _close():
        import logging
        logger = logging.getLogger("codex_auto_resume")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_unknown_interruption_cancels_nothing(self):
        with patch.object(Store, "cancel") as cancel:
            code, _ = self.run_activate(notify.cancel_uri("f0" * 32), self.home)
        self.assertEqual(code, cli.EXIT_ERROR)
        cancel.assert_not_called()

    def test_malformed_uri_never_reaches_the_store(self):
        with patch.object(Store, "cancel") as cancel, patch.object(Store, "get") as get:
            code, _ = self.run_activate("codex-auto-resume:cancel?i=not-hex", self.home)
        self.assertEqual(code, cli.EXIT_ERROR)
        get.assert_not_called()
        cancel.assert_not_called()

    def test_a_real_record_is_cancelled_by_its_own_thread_id(self):
        record = {"thread_id": THREAD, "interruption_id": INTERRUPTION}
        with patch.object(Store, "get", return_value=record), \
             patch.object(Store, "cancel") as cancel:
            code, out = self.run_activate(notify.cancel_uri(INTERRUPTION), self.home)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(cancel.call_args.args[0], THREAD)
        self.assertIn(THREAD, out)


class EngineNotificationTests(unittest.TestCase):
    def harness(self, **kwargs):
        import tempfile
        from test_engine import Harness, T1

        temp = tempfile.TemporaryDirectory()
        harness = Harness(Path(temp.name), **kwargs)
        self.addCleanup(temp.cleanup)
        self.addCleanup(harness.store.close)
        harness.source.fail_usage(T1)
        harness.enable()
        harness.tick()
        return harness, T1

    def test_a_failing_notification_never_blocks_a_resume(self):
        harness, thread = self.harness(notify=MagicMock(side_effect=RuntimeError("toast broke")))
        self.assertIsNotNone(harness.record(thread), "detection must still be recorded")
        self.assertTrue(any(entry[1] == "notification_failed" for entry in harness.logs))

    def test_the_notification_receives_the_exact_interruption(self):
        harness, thread = self.harness()
        record = harness.record(thread)
        self.assertEqual(len(harness.notifications), 1)
        thread_id, interruption_id, _reset = harness.notifications[0]
        self.assertEqual(thread_id, record["thread_id"])
        self.assertEqual(interruption_id, record["interruption_id"])


class NotificationSettingTests(unittest.TestCase):
    def test_messages_exist_in_every_language(self):
        for key in ("toast_title", "toast_body_at", "toast_body_soon", "toast_button_cancel",
                    "toast_cancelled_title", "toast_cancelled_body"):
            for code in messages.SUPPORTED:
                self.assertTrue(messages.MESSAGES[code][key], (code, key))


if __name__ == "__main__":
    unittest.main()

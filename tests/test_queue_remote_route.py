"""The queue command keeps --remote when it is needed and takes it only where Codex offers it (v0.6.23).

The audit of v0.6.23, C5: where the process list could not be read at the moment of a send, the queue command went
without `--remote unix://`; recent Codex refuses an embedded queue server with -c overrides while its managed daemon
runs, and a refusal after Popen is "may have been sent", never sent again. Now nothing is started that look
(not_started, queue_preflight_failed), and the next look sends with the route the process list shows.

C6: whether `codex queue` takes --remote (and --thread, --message) was decided by a substring of its help, so a help
that named only `--remote-auth-token` turned every send beside the daemon into an option clap refuses. Now each flag
is matched as an option of its own.

No Codex runs: the backend's compatibility check, the process list and Popen are stand-ins.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import windows as w
from codex_auto_resume.codex import transport

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
QUEUE = "0a1b2c3d-0003-7000-8000-000000000003"


class Case(unittest.TestCase):
    def setUp(self):
        self.backend = w.Backend(Path("state"), Path("codex.exe"))
        compatible = patch.object(self.backend, "_compatible")
        compatible.start()
        self.addCleanup(compatible.stop)
        self.daemon = str(self.backend.codex_home / "packages" / "app-server-daemon" /
                          "releases" / "0.166.0" / "bin" / "codex.exe")

    def process(self):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        return process


class UnreadableInventoryTests(Case):
    def test_an_unreadable_process_list_starts_nothing_and_the_next_look_sends_with_remote(self):
        self.backend.queue_remote_supported = True
        for error in (w.AdapterError("process_inventory_unavailable"), OSError("cim"), ValueError("json")):
            with self.subTest(error=error), patch.object(transport, "inventory", side_effect=error), \
                    patch.object(subprocess, "Popen", return_value=self.process()) as popen:
                self.assertEqual(self.backend.send(THREAD, "harmless"),
                                 {"outcome": "not_started", "error_code": "queue_preflight_failed"})
            popen.assert_not_called()
        with patch.object(transport, "inventory", return_value=[{"pid": 300, "path": self.daemon}]), \
                patch.object(subprocess, "Popen", return_value=self.process()) as popen:
            self.assertEqual(self.backend.send(THREAD, "harmless")["outcome"], "accepted")
        self.assertEqual(popen.call_args.args[0][-2:], ["--remote", "unix://"])

    def test_a_codex_without_remote_never_reads_the_process_list(self):
        self.backend.queue_remote_supported = False
        with patch.object(transport, "inventory", side_effect=AssertionError("read")), \
                patch.object(subprocess, "Popen", return_value=self.process()) as popen:
            self.assertEqual(self.backend.send(THREAD, "harmless")["outcome"], "accepted")
        self.assertNotIn("--remote", popen.call_args.args[0])


class HelpTextTests(Case):
    def interface(self, text):
        result = MagicMock(returncode=0, stdout=text)
        with patch.object(subprocess, "run", return_value=result):
            ok = self.backend._queue_interface_ok()
        return ok, self.backend.queue_remote_supported

    def test_remote_is_an_option_of_its_own(self):
        for text in ("Options:\n      --thread <THREAD>\n      --message <MESSAGE>\n      --remote <ADDR>\n",
                     "Usage: codex queue [--remote <ADDR>] --thread <THREAD> --message <MESSAGE>\n",
                     "  --thread=<THREAD>  --message=<MESSAGE>  --remote=<ADDR>\n"):
            with self.subTest(text=text):
                self.assertEqual(self.interface(text), (True, True))

    def test_a_longer_option_that_starts_with_remote_is_not_remote(self):
        text = "Options:\n      --thread <THREAD>\n      --message <MESSAGE>\n      --remote-auth-token <TOKEN>\n"
        self.assertEqual(self.interface(text), (True, False))

    def test_a_longer_option_that_starts_with_a_required_flag_is_not_that_flag(self):
        for text in ("      --thread-id <ID>\n      --message <MESSAGE>\n",
                     "      --thread <THREAD>\n      --message-file <PATH>\n"):
            with self.subTest(text=text):
                self.assertFalse(self.interface(text)[0])


if __name__ == "__main__":
    unittest.main()

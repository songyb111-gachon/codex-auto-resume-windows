"""The longest message, and the command line it travels on (v0.6.23, the owner's decision of 2026-11-10).

30,000 characters is the bound, and Windows' command line is what would stop a longer one. It counts UTF-16 code units of
the line subprocess makes, so an emoji is two and a quote and the backslashes before it cost more: the send measures that
line and refuses, with the word a message too long has always had, before any process exists. No process is started.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import continuation
from codex_auto_resume import windows as w
from codex_auto_resume.codex import transport

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
QUEUE = "0a1b2c3d-0003-7000-8000-000000000003"
REFUSED = {"outcome": "not_started", "error_code": "queue_preflight_failed"}


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.backend = w.Backend(Path("state"), Path("codex.exe"))
        for name in ("_compatible", "_queue_daemon_remote"):
            patcher = patch.object(self.backend, name, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, prompt):
        """What send answered, and the argv Popen was given (None: no process was started)."""
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        with patch.object(transport.S, "Popen", return_value=process) as popen:
            answer = self.backend.send(THREAD, prompt)
        return answer, popen.call_args.args[0] if popen.called else None

    def room(self):
        """How many plain characters fit the command line with this backend's own fixed part."""
        fixed = transport.command_line_units(self.backend._argv() + ["queue", "--thread", THREAD, "--message="])
        return transport.COMMAND_LINE_UNITS - fixed

    def test_the_numbers(self):
        self.assertEqual(continuation.PROMPT_SEND_LIMIT, 30000)
        self.assertEqual(transport.COMMAND_LINE_UNITS, 32766)

    def test_the_longest_message_goes(self):
        answer, argv = self.send("x" * 30000)
        self.assertEqual(answer["outcome"], "accepted")
        self.assertEqual(len(argv[argv.index("queue") + 3]), len("--message=") + 30000)

    def test_one_character_more_is_refused_before_any_process(self):
        self.assertEqual(self.send("x" * 30001), (REFUSED, None))

    def test_the_measure_is_the_line_subprocess_makes(self):
        for argv in (["a b", 'c"d', "e\\\"f", "g\\"], ["plain"], ["\U0001F600 x"]):
            line = subprocess.list2cmdline(argv)
            self.assertEqual(transport.command_line_units(argv), len(line.encode("utf-16-le")) // 2, argv)

    def test_an_emoji_counts_two(self):
        self.assertEqual(transport.command_line_units(["\U0001F600"]), 2)
        self.assertEqual(transport.command_line_units(["x"]), 1)

    def test_a_quote_costs_two_and_the_backslashes_before_it_double(self):
        self.assertEqual(transport.command_line_units(['"']), 2)            # \"
        self.assertEqual(transport.command_line_units(['\\"']), 4)          # \\\"

    def test_a_message_within_the_count_that_does_not_fit_the_line_is_refused(self):
        """Fails with the measure taken away: `len()` passes a message of quotes Windows then refuses."""
        with patch.object(transport, "COMMAND_LINE_UNITS", 25000):
            room = self.room()
            self.assertEqual(self.send("x" * (room + 1))[1], None)
            self.assertEqual(self.send("x" * (room + 1))[0], REFUSED)
            self.assertIsNotNone(self.send("x" * room)[1], "exactly the room goes")

    def test_emoji_and_quotes_inside_the_bound_can_pass_len_and_fail_the_line(self):
        text = "\U0001F600" * 17000
        self.assertLessEqual(len(text), continuation.PROMPT_SEND_LIMIT)
        self.assertEqual(self.send(text), (REFUSED, None))
        quotes = '"' * 17000
        self.assertEqual(self.send(quotes), (REFUSED, None))

    def test_the_route_by_the_daemon_is_counted_too(self):
        with patch.object(self.backend, "_queue_daemon_remote", return_value=True), \
                patch.object(self.backend, "_argv", return_value=["codex.exe"]):
            suffix = len(" --remote unix://")
            fixed = transport.command_line_units(["codex.exe", "queue", "--thread", THREAD, "--message="])
            room = 30000
            with patch.object(transport, "COMMAND_LINE_UNITS", fixed + room + suffix - 1):
                self.assertEqual(self.send("x" * room), (REFUSED, None))
            with patch.object(transport, "COMMAND_LINE_UNITS", fixed + room + suffix):
                self.assertIsNotNone(self.send("x" * room)[1])


if __name__ == "__main__":
    unittest.main()

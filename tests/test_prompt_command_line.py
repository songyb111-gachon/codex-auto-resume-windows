"""A person's message that the send cannot fit on Windows' command line is refused when it is written (v0.6.23, the
second core audit's K2).

Until v0.6.23 validate_prompt counted characters (29,962 at most) and the send counted the command line it starts Codex
with (32,766 UTF-16 units): a 29,000-character paste with one double quote in ten reached 36,389 units, 17,000 emoji
34,432 - accepted when written, refused at its time on every try, never sent, and nobody told. Now validate_prompt counts
the same line by the same function the send uses (continuation.command_line_units), with the most the send puts beside
the message, so such a message is refused at once, "too_long"; the send's own check stays as the last guard. A plain
message of the full 29,962 characters still goes. No process is started: Popen is stood in for.
"""
from __future__ import annotations

from pathlib import Path
import random
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import continuation
from codex_auto_resume import windows as w
from codex_auto_resume.codex import transport

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
QUEUE = "0a1b2c3d-0003-7000-8000-000000000003"
MARKER = "[codex-auto-resume:0123456789abcdef]"
# The longest program path the room is made for: MAX_PATH, under a folder with a space, so it is quoted.
LONGEST_EXE = "C:\\Program Files\\" + "a" * (260 - len("C:\\Program Files\\"))


def json_ish(length: int) -> str:
    """The audit's paste: code or JSON with one double quote in ten characters."""
    return ('"name": value, more ' * (length // 20 + 1))[:length]


def refusal(text):
    try:
        continuation.validate_prompt(text)
    except continuation.PromptError as exc:
        return exc.code
    return None


class AcceptanceTests(unittest.TestCase):
    def test_the_audits_paste_is_refused_when_it_is_written(self):
        text = json_ish(continuation.PROMPT_LIMIT)
        self.assertEqual(round(text.count('"') / len(text), 2), 0.1, "one in ten")
        self.assertEqual(refusal(text), "too_long")

    def test_seventeen_thousand_emoji_are_refused_when_they_are_written(self):
        self.assertEqual(refusal("\U0001F600" * 17000), "too_long")

    def test_the_full_length_of_plain_words_still_goes(self):
        """The 30,000-character promise holds for plain text: a whole PROMPT_LIMIT, spaces and line ends included."""
        text = ("keep going with the next step\n" * 1000)[:continuation.PROMPT_LIMIT]
        self.assertEqual(len(text), continuation.PROMPT_LIMIT)
        self.assertIsNone(refusal(text))

    def boundary(self):
        """The longest message of plain words and quotes that fits, by the measure itself."""
        base, low, high = "x" * 20000, 0, 20000          # the most quotes that fit, by halves
        while low < high:
            middle = (low + high + 1) // 2
            low, high = (middle, high) if continuation.fits_command_line(base + '"' * middle) else (low, middle - 1)
        quotes = low
        text = base + '"' * quotes
        while continuation.fits_command_line(text + "x"):     # a quote is two: one plain character may be left
            text += "x"
        return text

    def test_at_the_exact_boundary_it_is_accepted_and_one_more_quote_is_refused(self):
        text = self.boundary()
        self.assertIsNone(refusal(text))
        self.assertEqual(refusal(text + '"'), "too_long")
        line = continuation.SEND_ARGV_ROOM + 1 + continuation.command_line_units(["--message=" + text + "\n\n" + MARKER])
        self.assertEqual(line, continuation.COMMAND_LINE_UNITS, "the boundary is the line's own length, to the unit")

    def test_one_emoji_more_than_fits_is_refused(self):
        base = "x" * 20000
        count = 0
        while continuation.fits_command_line(base + "\U0001F600" * (count + 1)):
            count += 1
        self.assertIsNone(refusal(base + "\U0001F600" * count))
        self.assertEqual(refusal(base + "\U0001F600" * (count + 1)), "too_long")


class SameMeasureTests(unittest.TestCase):
    def test_the_line_is_the_one_subprocess_makes(self):
        """continuation writes subprocess.list2cmdline's line itself (a policy module starts no process); every argv
        here - quotes, backslashes before and after them, spaces, tabs, nothing, emoji - is the same line."""
        pieces = ["a", " ", "\t", '"', "\\", "\\\\", '\\"', "x y", "\U0001F600", "", "\n", "--message="]
        chance = random.Random(623)
        cases = [[""], ["a b"], ['c"d'], ["e\\\"f"], ["g\\"], ["h \\"], ['"'], ["\\\\\""]]
        cases += [["".join(chance.choice(pieces) for _ in range(chance.randrange(0, 12)))
                   for _ in range(chance.randrange(1, 5))] for _ in range(2000)]
        for argv in cases:
            self.assertEqual(continuation.joined_command_line(argv), subprocess.list2cmdline(argv), argv)

    def test_the_send_counts_with_the_same_function(self):
        self.assertIs(transport.command_line_units, continuation.command_line_units)
        self.assertEqual(transport.COMMAND_LINE_UNITS, continuation.COMMAND_LINE_UNITS)

    def test_the_room_holds_what_the_send_puts_beside_the_message(self):
        """Measured from the send's own argv (CodexAdapter._argv, then queue, the thread and the daemon's route), with
        the longest program path the room is made for."""
        backend = w.Backend(Path("state"), Path(LONGEST_EXE))
        rest = backend._argv() + ["queue", "--thread", THREAD, "--remote", "unix://"]
        self.assertLessEqual(continuation.command_line_units(rest), continuation.SEND_ARGV_ROOM)


class SendTests(unittest.TestCase):
    """A message accepted at the boundary is one the send starts Codex with, the daemon's route included."""

    def setUp(self):
        self.backend = w.Backend(Path("state"), Path(LONGEST_EXE))
        for name, value in (("_compatible", None), ("_queue_daemon_remote", True)):
            patcher = patch.object(self.backend, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, prompt):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        with patch.object(transport.S, "Popen", return_value=process) as popen:
            answer = self.backend.send(THREAD, prompt)
        return answer, popen.call_args.args[0] if popen.called else None

    def test_the_boundary_message_is_sent(self):
        text = AcceptanceTests.boundary(self)
        continuation.validate_prompt(text)
        answer, argv = self.send(text + "\n\n" + MARKER)
        self.assertEqual(answer["outcome"], "accepted")
        self.assertIn("--message=" + text + "\n\n" + MARKER, argv)
        self.assertLessEqual(transport.command_line_units(argv), transport.COMMAND_LINE_UNITS)

    def test_the_full_length_of_plain_words_is_sent(self):
        text = ("keep going with the next step\n" * 1000)[:continuation.PROMPT_LIMIT]
        continuation.validate_prompt(text)
        self.assertEqual(self.send(text + "\n\n" + MARKER)[0]["outcome"], "accepted")


if __name__ == "__main__":
    unittest.main()

"""A queued message too long for the command line it is sent on is refused when it is added (v0.6.23, audit K2).

With Longer messages on, the prompt queue took any message of up to 29,962 characters, and the send then refused one
whose command line passed Windows' 32,766 units - one of quotes, or of emoji - at its time, every time. Now core's check
(continuation.validate_prompt) counts that line, so the Dashboard is told at once: prompt_refused, nothing kept, nothing
sent. A message at the line's exact boundary is added and sent. Held against core's own engine and a simulated Codex.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_prompt_queue import QueueCase  # noqa: E402
from codex_auto_resume import continuation  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Refusal  # noqa: E402


def boundary() -> str:
    """Plain words and quotes, the longest that fits the line by the measure itself."""
    base, low, high = "x" * 20000, 0, 20000          # the most quotes that fit, by halves
    while low < high:
        middle = (low + high + 1) // 2
        low, high = (middle, high) if continuation.fits_command_line(base + '"' * middle) else (low, middle - 1)
    quotes = low
    words = base + '"' * quotes
    while continuation.fits_command_line(words + "x"):        # a quote is two: one plain character may be left
        words += "x"
    return words


class LineTests(QueueCase):
    def test_quotes_and_emoji_past_the_line_are_refused_when_added(self):
        plug = self.on(long=True)
        quoted = ('"name": value, more ' * 1500)[:continuation.PROMPT_LIMIT]
        for words in (quoted, "\U0001F600" * 17000, boundary() + '"'):
            with self.subTest(words=words[:12]):
                self.assertLessEqual(len(words), continuation.PROMPT_LIMIT)
                self.assertEqual(self.add(plug, words=words)["refusal"], Refusal.PROMPT_REFUSED)
        self.assertEqual(self.prompts(plug), [])

    def test_the_boundary_message_is_added_and_sent_as_written(self):
        plug = self.on(long=True)
        words = boundary()
        self.assertTrue(self.add(plug, words=words)["done"])
        self.h.tick(advance=1)
        self.assertEqual(len(self.sends()), 1)
        self.assertTrue(self.sends()[0].startswith(words + "\n\n"))


if __name__ == "__main__":
    unittest.main()

"""A recovery message that starts with "-" reaches `codex queue` as the message (v0.6.18, the security audit's R1).

The person's Custom message, an advanced queued prompt or a chat message may start with "-" - a Markdown bullet
("- keep going"), a rule ("---"), "-1 more step" - and the validators allow it. Passed as `--message <text>`, a parser
with clap's defaults reads such a value as an unknown option: codex exits non-zero, the send ends unconfirmed and the
record becomes submission_unknown, never sent again. Passed as one `--message=<text>` argument, every parser takes the
value whole. Python's argparse refuses the separate form the same way clap does, so it stands in for codex here.

No process is started: Popen is stood in for.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume import windows as w
from codex_auto_resume.codex import transport

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
QUEUE = "0a1b2c3d-0003-7000-8000-000000000003"
MARKER = "\n\n[codex-auto-resume:0123456789abcdef]"


def parsed(argv):
    """`queue --thread T --message M` as an option parser with clap's defaults reads it, or None where it refuses."""
    parser = argparse.ArgumentParser(prog="codex queue", exit_on_error=False, add_help=False)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--message", required=True)
    try:
        return vars(parser.parse_args(argv))
    except (argparse.ArgumentError, SystemExit):
        return None


class LeadingHyphenTests(unittest.TestCase):
    def setUp(self):
        self.backend = w.Backend(Path("state"), Path("codex.exe"))
        compatible = patch.object(self.backend, "_compatible")
        compatible.start()
        self.addCleanup(compatible.stop)

    def argv(self, prompt):
        process = MagicMock(returncode=0)
        process.communicate.return_value = (f"Queued message {QUEUE} for thread {THREAD}.\n", None)
        with patch.object(transport.S, "Popen", return_value=process) as popen:
            self.assertEqual(self.backend.send(THREAD, prompt), {"outcome": "accepted", "queue_id": QUEUE})
        argv = popen.call_args.args[0]
        return argv[argv.index("queue") + 1:]

    def test_a_message_that_starts_with_a_hyphen_is_read_as_the_message(self):
        for text in ("- keep going", "--- next part", "-1 more step", "--help", "-- continue", "Please continue."):
            with self.subTest(text):
                prompt = text + MARKER
                self.assertEqual(parsed(self.argv(prompt)), {"thread": THREAD, "message": prompt})

    def test_the_message_is_one_argument_and_nothing_else_carries_the_person_s_text(self):
        prompt = "- keep going" + MARKER
        argv = self.argv(prompt)
        self.assertEqual(argv, ["--thread", THREAD, "--message=" + prompt])


if __name__ == "__main__":
    unittest.main()

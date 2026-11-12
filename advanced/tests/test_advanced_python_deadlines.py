"""One deadline for a Check and one for a download of the Python choice (v0.6.23 final, R5 of the second round's limits
audit).

Each read of python.org was bounded only by one wait on its socket: a Check could make 1 + 3 x 40 reads of 30 s each, an
hour with the card busy, and a download that sends a byte under every 60 s never ended. Now a Check ends as Refused(LIST)
past CHECK_SECONDS from its start and a download as Refused(DOWNLOAD) past DOWNLOAD_SECONDS, however the time is spent.

python.org is a fake that moves a fake clock as it answers: nothing reaches the network and nothing waits.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_python_deadlines.py
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume_advanced.control import pythons  # noqa: E402
from codex_auto_resume_advanced.courier import pythonorg  # noqa: E402

VERSION = "3.15.2"
URL = pythonorg.PACKAGE % (VERSION, VERSION)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Slow:
    """python.org, slow as a test says: `per_open` seconds before each answer begins, and each answer handed out
    `piece` bytes at a time, `per_piece` seconds apart. Every wait it is given is kept."""

    def __init__(self, clock, table, *, per_open=0.0, per_piece=0.0, piece=None):
        self.clock, self.table = clock, table
        self.per_open, self.per_piece, self.piece = per_open, per_piece, piece
        self.asked, self.timeouts = [], []

    def open(self, request, timeout=None):
        self.asked.append(request.full_url)
        self.timeouts.append(timeout)
        self.clock.now += self.per_open
        return Reply(self, self.table[request.full_url])


class Reply:
    status = 200

    def __init__(self, source, body):
        self.source, self.stream = source, io.BytesIO(body)

    def read(self, count=-1):
        self.source.clock.now += self.source.per_piece
        return self.stream.read(self.source.piece or count)

    def close(self):
        pass


def release(name, number):
    return {"name": name, "pre_release": False, "resource_uri": "https://www.python.org/api/v2/downloads/release/%d/" % number}


class Case(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        # The clock every reader of time.monotonic sees while a case runs: the courier's, and nothing else of a test's.
        patcher = patch.object(time, "monotonic", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def unpackaged_lines(self):
        """Three lines of 40 releases each, none with a Windows embeddable package: the most reads a Check can make."""
        rows, table = [], {}
        for line, base in (("3.13", 1000), ("3.14", 2000), ("3.15", 3000)):
            for patch_number in range(pythonorg.RELEASES_MOST):
                number = base + patch_number
                rows.append(release("Python %s.%d" % (line, patch_number), number))
                table[pythonorg.FILES % number] = b"[]"
        table[pythonorg.RELEASES] = json.dumps(rows).encode()
        return table


class CheckDeadlineTests(Case):
    def test_the_numbers_and_their_reasons(self):
        self.assertEqual(pythonorg.CHECK_SECONDS, 4 * pythonorg.LIST_TIMEOUT)
        self.assertEqual(pythonorg.DOWNLOAD_SECONDS, 600)
        text = (Path(pythonorg.__file__)).read_text(encoding="utf-8")
        for reason in ("one slow answer still has room", "about 110 KB/s"):
            self.assertIn(reason, text)

    def test_a_check_of_slow_reads_ends_as_list_at_its_deadline(self):
        """Fails with R5 reverted: 121 reads of 29 s each, 58 minutes with the card busy."""
        source = Slow(self.clock, self.unpackaged_lines(), per_open=29.0)
        with self.assertRaises(pythonorg.Refused) as refused:
            pythonorg.offered(pythons.LINES, opener=source)
        self.assertEqual(refused.exception.step, pythonorg.LIST)
        self.assertLessEqual(len(source.asked), pythonorg.CHECK_SECONDS // 29 + 1)
        self.assertLessEqual(self.clock.now - 1000.0, pythonorg.CHECK_SECONDS + pythonorg.LIST_TIMEOUT)

    def test_no_read_is_given_a_wait_past_the_deadline(self):
        source = Slow(self.clock, self.unpackaged_lines(), per_open=29.0)
        with self.assertRaises(pythonorg.Refused):
            pythonorg.offered(pythons.LINES, opener=source)
        start = 1000.0
        for number, timeout in enumerate(source.timeouts):
            self.assertLessEqual(timeout, pythonorg.LIST_TIMEOUT)
            self.assertLessEqual(start + number * 29.0 + timeout, start + pythonorg.CHECK_SECONDS + 1e-6)

    def test_an_answer_that_trickles_ends_as_list(self):
        """Each piece well inside one read's 30 s, the whole far past the Check's."""
        body = json.dumps([release("Python 3.15.2", 301)] * 50).encode()
        source = Slow(self.clock, {pythonorg.RELEASES: body}, per_piece=10.0, piece=16)
        with self.assertRaises(pythonorg.Refused) as refused:
            pythonorg.offered(pythons.LINES, opener=source)
        self.assertEqual(refused.exception.step, pythonorg.LIST)
        self.assertLessEqual(self.clock.now - 1000.0, pythonorg.CHECK_SECONDS + 10.0)

    def test_a_check_in_time_is_what_it_was(self):
        table = {pythonorg.RELEASES: json.dumps([release("Python 3.15.2", 301)]).encode(),
                 pythonorg.FILES % 301: json.dumps([{"name": pythonorg.FILE_NAME}]).encode()}
        source = Slow(self.clock, table, per_open=5.0)
        self.assertEqual(pythonorg.offered(pythons.LINES, opener=source), {"3.15": {"version": VERSION, "release": 301}})

    def test_the_card_says_the_list_step(self):
        """Through the card's own Check: the job ends FAILED at LIST, as a list that could not be read always did."""
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        from test_advanced_python_choice import FakeRuntime, inline
        runtime = FakeRuntime(Path(made.name) / "home")
        self.addCleanup(lambda: (pythons._OUTCOMES.pop(runtime.paths.home, None), pythons._OFFERS.pop(runtime.paths.home, None)))
        source = Slow(self.clock, self.unpackaged_lines(), per_open=29.0)

        class Hands(pythons.Hands):
            @staticmethod
            def newest(lines):
                return pythonorg.offered(lines, opener=source)
        self.assertTrue(pythons.check(runtime, start=inline, hands=Hands)["done"])
        self.assertEqual(pythons._OUTCOMES.get(runtime.paths.home), {"word": pythons.FAILED, "step": pythons.LIST, "version": None})


class DownloadDeadlineTests(Case):
    def download(self, source, size):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        found = {"url": URL, "size": size, "sha256": "a" * 64}
        return pythonorg.download(found, Path(made.name) / "package.zip", opener=source)

    def test_a_download_that_sends_a_piece_a_minute_ends_as_download(self):
        """Fails with R5 reverted: a piece under every 60 s kept it going for ever."""
        size = 4096
        source = Slow(self.clock, {URL: b"x" * size}, per_piece=59.0, piece=1)
        with self.assertRaises(pythonorg.Refused) as refused:
            self.download(source, size)
        self.assertEqual(refused.exception.step, pythonorg.DOWNLOAD)
        self.assertLessEqual(self.clock.now - 1000.0, pythonorg.DOWNLOAD_SECONDS + 59.0)

    def test_a_download_in_time_is_written_whole(self):
        size = 200000
        source = Slow(self.clock, {URL: b"x" * size}, per_piece=1.0)
        self.assertEqual(self.download(source, size), size)
        self.assertLessEqual(source.timeouts[0], pythonorg.DOWNLOAD_TIMEOUT)


if __name__ == "__main__":
    unittest.main()

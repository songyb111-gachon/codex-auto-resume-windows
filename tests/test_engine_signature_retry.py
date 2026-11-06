"""A signature check that failed once is asked again; a settled answer is kept with the file (v0.6.23).

The audit of v0.6.23 (C1): codex/pairing.py official_engine kept every answer by the file's path, size and time -
the #58 hotfix's way to hash a 369 MB engine once - refusals too. An antivirus still scanning a fresh engine
(WinVerifyTrust: in use, `signature_unreadable`) or a chain whose intermediate this PC had not cached yet
(`signature_untrusted`) was then remembered until the watcher restarted, and every recovery waited. Those two are
kept a minute (pairing.PASSING_SECONDS) and asked again after it; every other answer - OpenAI's signature, another
signer, unsigned, a file that no longer matches its signature - is kept as long as the file stays the same, as
v0.6.21 promised. Windows' calls are stubs; the clock is a stand-in.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume.codex import pairing
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume.win import authenticode

# A failure is asked again within a minute (the audit's number); the test outlives it by a second.
PAST_THE_MINUTE = 61.0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-signature-retry-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.engine = root / "WindowsApps" / "OpenAI.Codex_x64__2p2nqsd0c76g0" / "app" / "resources" / "codex.exe"
        self.engine.parent.mkdir(parents=True)
        self.engine.write_bytes(b"MZ-package")
        self.clock = Clock()
        for stand_in in (patch.dict(os.environ, {"LOCALAPPDATA": str(root / "Local")}),
                         patch("time.monotonic", self.clock)):
            stand_in.start()
            self.addCleanup(stand_in.stop)
        pairing._OFFICIAL.clear()
        self.addCleanup(pairing._OFFICIAL.clear)
        self.answers = []

    def signer(self, _path):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FailedOnceTests(Case):
    def test_a_file_held_by_an_antivirus_is_official_once_it_is_free(self):
        self.answers = [AdapterError("signature_unreadable"), pairing.OPENAI_SIGNER]
        with patch.object(authenticode, "signer", side_effect=self.signer) as signer:
            self.assertEqual(pairing.official_engine(self.engine), (False, "signature_unreadable"))
            self.clock.now += PAST_THE_MINUTE
            self.assertEqual(pairing.official_engine(self.engine), (True, "openai_signature"))
            self.clock.now += 3600
            self.assertEqual(pairing.official_engine(self.engine), (True, "openai_signature"))
        self.assertEqual(signer.call_count, 2, "asked again once after the failure, then kept")

    def test_a_chain_not_yet_trusted_is_asked_again(self):
        self.answers = [AdapterError("signature_untrusted"), pairing.OPENAI_SIGNER]
        with patch.object(authenticode, "signer", side_effect=self.signer):
            self.assertEqual(pairing.official_engine(self.engine), (False, "signature_untrusted"))
            self.clock.now += PAST_THE_MINUTE
            self.assertEqual(pairing.official_engine(self.engine), (True, "openai_signature"))

    def test_an_unexpected_failure_is_asked_again(self):
        self.answers = [RuntimeError("boom"), pairing.OPENAI_SIGNER]
        with patch.object(authenticode, "signer", side_effect=self.signer):
            self.assertEqual(pairing.official_engine(self.engine), (False, "signature_unreadable"))
            self.clock.now += PAST_THE_MINUTE
            self.assertEqual(pairing.official_engine(self.engine), (True, "openai_signature"))

    def test_within_the_minute_the_failure_is_kept_and_the_file_is_not_hashed_on_every_tick(self):
        self.answers = [AdapterError("signature_unreadable")]
        with patch.object(authenticode, "signer", side_effect=self.signer) as signer:
            for _ in range(5):
                self.assertEqual(pairing.official_engine(self.engine), (False, "signature_unreadable"))
                self.clock.now += 5
        self.assertEqual(signer.call_count, 1)

    def test_a_clock_that_went_back_asks_again(self):
        self.answers = [AdapterError("signature_unreadable"), pairing.OPENAI_SIGNER]
        with patch.object(authenticode, "signer", side_effect=self.signer):
            self.assertEqual(pairing.official_engine(self.engine), (False, "signature_unreadable"))
            self.clock.now -= 10 * PAST_THE_MINUTE
            self.assertEqual(pairing.official_engine(self.engine), (True, "openai_signature"))


class SettledAnswerTests(Case):
    def test_a_failure_is_kept_at_most_a_minute(self):
        self.assertLessEqual(pairing.PASSING_SECONDS, PAST_THE_MINUTE - 1)
        self.assertEqual(pairing.PASSING, {"signature_unreadable", "signature_untrusted"})

    def test_settled_answers_are_kept_as_long_as_the_file_is_the_same(self):
        for answer, expected in ((pairing.OPENAI_SIGNER, (True, "openai_signature")),
                                 ("Someone Else", (False, "wrong_signer")),
                                 (AdapterError("unsigned"), (False, "unsigned")),
                                 (AdapterError("signature_invalid"), (False, "signature_invalid"))):
            pairing._OFFICIAL.clear()
            self.answers = [answer]
            with self.subTest(expected=expected), \
                    patch.object(authenticode, "signer", side_effect=self.signer) as signer:
                self.assertEqual(pairing.official_engine(self.engine), expected)
                self.clock.now += 24 * 3600
                self.assertEqual(pairing.official_engine(self.engine), expected)
                self.assertEqual(signer.call_count, 1)


if __name__ == "__main__":
    unittest.main()

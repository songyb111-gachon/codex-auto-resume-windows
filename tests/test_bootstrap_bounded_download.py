r"""The downloads that ride on an update check follow the archive's rule: every hop checked first, the body bounded.

Get-Remote -Deadline - the Codex compatibility data's fetch - ran Invoke-WebRequest -MaximumRedirection 5 -OutFile under
a deadline: every redirect was followed before the host was checked, on the final answer only, and the whole body was
written to disk before its size was compared with the 256 KiB bound (the v0.6.18 security review, M5). It now goes
through Save-BoundedDownload: Open-Download holds each hop to the caller's hosts before it is asked, the body is read no
further than one byte past -MaxBytes, the deadline covers every hop and the body, and nothing is left at the target
after a failure. The old request stays only where the .NET one cannot be made, as for the archive.

The cases run through tests/test_bootstrap_streamed_download.py's harness: the real functions lifted by the parser, the
network's one door (Get-DownloadResponse) a stand-in answering from each case, Invoke-WebRequest a stand-in that fails
the case if it is reached. Nothing reaches a network.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_bootstrap_streamed_download import (ARCHIVE, ASSETS, BOOTSTRAP, POWERSHELL, REFUSED, SIZE, STANDIN_PROBE,
                                              BODY_SHA, pattern, redirect)

WANTED = ("$wanted = @('Step', 'Get-FinalUri', 'Assert-TrustedHost', 'Get-RateLimitReset', 'Get-Remote', "
          "'Get-ThrownException', 'Get-DownloadWords', 'New-DownloadRequest', 'Assert-TrustedHop', "
          "'New-ServerError', 'Open-Download', 'Save-StreamedDownload', 'Save-BoundedDownload')\n")
CALL = "Get-Remote -Uri $case.uri -OutFile $out -What 'The archive' -Count:$count"
BOUNDED = ("Get-Remote -Uri $case.uri -OutFile $out -What 'The archive' -Deadline "
           "-TimeoutSec ([int](Get-Field $case 'seconds' 30)) -MaxBytes ([long](Get-Field $case 'max' 0))")
EVIL = "https://downloads.example.net/codex_compat.json"
CAP = 1000


@unittest.skipUnless(POWERSHELL.is_file(), "the bootstrap is PowerShell on Windows")
class BoundedDownloadTests(unittest.TestCase):
    CASES = [
        {"name": "whole", "uri": ARCHIVE, "answers": [redirect(ASSETS), {"status": 200}]},
        {"name": "hop_refused_before_it_is_asked", "uri": ARCHIVE, "answers": [redirect(EVIL), {"status": 200}]},
        {"name": "body_bounded", "uri": ARCHIVE, "max": CAP, "answers": [{"status": 200}]},
        {"name": "body_bounded_without_a_length", "uri": ARCHIVE, "max": CAP, "answers": [{"status": 200, "length": -1}]},
        {"name": "deadline_covers_every_hop", "uri": ARCHIVE, "seconds": 0, "answers": [redirect(ASSETS), {"status": 200}]},
        {"name": "cut_short", "uri": ARCHIVE, "answers": [{"status": 200, "to": 5000, "length": SIZE}]},
    ]

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cases = root / "cases.json"
        cases.write_text(json.dumps(cls.CASES), encoding="utf-8")
        assert STANDIN_PROBE.count(CALL) == 1
        probe = WANTED + STANDIN_PROBE.replace(CALL, BOUNDED)
        environment = dict(os.environ, CAR_BOOTSTRAP=str(BOOTSTRAP), CAR_CASES=str(cases), CAR_ROOT=str(root),
                           CAR_SIZE=str(SIZE))
        done = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", probe],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=600, env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        cls.stdout, cls.stderr, cls.code = done.stdout, done.stderr, done.returncode
        cls.results = {}
        marker = cls.stdout.rfind("@@RESULTS@@")
        if done.returncode == 0 and marker >= 0:
            answer = json.loads(cls.stdout[marker + len("@@RESULTS@@"):])
            cls.results = {row["name"]: row for row in answer["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def case(self, name):
        self.assertEqual(self.code, 0, self.stderr[-3000:] + self.stdout[-3000:])
        self.assertIn(name, self.results, self.stdout[-3000:])
        row = self.results[name]
        for key in ("asked", "leftovers"):
            row[key] = [] if row[key] is None else (row[key] if isinstance(row[key], list) else [row[key]])
        self.assertEqual(row["open"], 0, row)
        self.assertEqual(row["leftovers"], [], row)
        self.assertEqual(row["old"], 0, "the old request was taken")
        return row

    def test_a_whole_body_arrives_through_its_hops(self):
        row = self.case("whole")
        self.assertIsNone(row["threw"], row)
        self.assertEqual(row["file"], BODY_SHA)
        self.assertEqual([hop["redirects"] for hop in row["asked"]], [False, False], "no hop is followed unchecked")

    def test_a_hop_outside_the_hosts_is_refused_before_it_is_asked(self):
        row = self.case("hop_refused_before_it_is_asked")
        self.assertIn(REFUSED + "downloads.example.net", row["threw"])
        self.assertEqual([hop["uri"] for hop in row["asked"]], [ARCHIVE])
        self.assertIsNone(row["file"])

    def test_no_more_than_one_byte_past_the_bound_is_written(self):
        for name in ("body_bounded", "body_bounded_without_a_length"):
            with self.subTest(name):
                row = self.case(name)
                self.assertIsNone(row["threw"], row)
                self.assertEqual(row["file"], hashlib.sha256(pattern(SIZE)[:CAP + 1]).hexdigest())

    def test_the_deadline_covers_every_hop(self):
        row = self.case("deadline_covers_every_hop")
        self.assertIn("did not arrive within 0 s.", row["threw"])
        self.assertEqual([hop["uri"] for hop in row["asked"]], [ARCHIVE])
        self.assertIsNone(row["file"])

    def test_a_body_cut_short_is_no_file(self):
        row = self.case("cut_short")
        self.assertIn("was cut short: 5000 of %d bytes arrived." % SIZE, row["threw"])
        self.assertIsNone(row["file"])

    def test_the_compatibility_data_asks_for_its_bound(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("-Hosts $CompatibilityHosts -TimeoutSec $TimeoutSec -Deadline -MaxBytes $CompatibilityMaxBytes", text)


if __name__ == "__main__":
    unittest.main()

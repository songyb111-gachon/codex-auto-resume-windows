"""codex-start.log keeps every line four servers write at once (v0.6.23, the owner's logs of 2026-11-10, B3).

Codex starts this plugin's servers four in a second, each a process of its own, and each read the whole log and wrote it
back: one that read in the instant another had emptied it wrote back only its own line, and the file held 8 lines of a
bound of 50. Real processes here, released together, on a scratch file.

    PYTHONPATH="src;tests" python -m unittest test_codex_start_log_no_loss
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
NO_WINDOW = 0x08000000
WRITER = r"""
import os, sys, time
from pathlib import Path
from codex_auto_resume.control import _note_line
log, go, name, count = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
Path(str(go) + "." + name).write_text("ready", encoding="utf-8")
while not go.exists():
    time.sleep(0.002)
for line in range(count):
    _note_line(log, "%s line %d" % (name, line))
"""


class FourWritersTests(unittest.TestCase):
    def write(self, writers, each):
        """`writers` processes, released together, each noting `each` lines. The log's lines."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            work = Path(folder).resolve()
            log, go = work / "codex-start.log", work / "go"
            environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
            running = [subprocess.Popen([sys.executable, "-c", WRITER, str(log), str(go), "w%d" % name, str(each)],
                                        env=environment, cwd=str(work), stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
                       for name in range(writers)]
            deadline = time.monotonic() + 120
            while len(list(work.glob("go.w*"))) < writers and time.monotonic() < deadline:
                time.sleep(0.02)
            go.write_text("go", encoding="utf-8")
            for process in running:
                self.assertEqual(process.wait(timeout=120), 0)
            return log.read_text(encoding="utf-8").splitlines()

    def test_no_line_is_lost_when_four_write_at_once(self):
        """Fails with the whole file read and written back: most of the lines are gone."""
        lines = self.write(4, 12)
        said = sorted(line.split("] ", 1)[1] for line in lines)
        self.assertEqual(said, sorted("w%d line %d" % (name, line) for name in range(4) for line in range(12)))

    def test_the_file_stays_within_its_bound_and_keeps_the_newest(self):
        from codex_auto_resume.control import CODEX_START_LOG_LINES
        lines = self.write(4, 30)
        self.assertEqual(len(lines), CODEX_START_LOG_LINES)
        self.assertEqual(len(set(lines)) >= CODEX_START_LOG_LINES - 8, True, "whole lines, none cut in two")
        for line in lines:
            self.assertRegex(line, r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] w\d line \d+$")


if __name__ == "__main__":
    unittest.main()

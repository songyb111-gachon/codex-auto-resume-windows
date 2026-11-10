"""STANDARDS C1's second sentence (the owner, 2026-11-10): the advanced edition's network code does not run unless a person
turns on the capability it belongs to. With every capability off, no module of the courier that sends, receives or listens
is loaded and no courier process starts.

test_advanced_resident's NothingWhileOffTests hold the same for the status server alone; this holds it for every capability.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_network_off.py
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume.win.kernel import NO_WINDOW  # noqa: E402
from codex_auto_resume_advanced import registry  # noqa: E402
from codex_auto_resume_advanced.courier import launch  # noqa: E402


# What the edition may take from the courier's package with every capability off: the package, whose import imports nothing,
# and the outbox, the table the watcher writes (the registry reads push_notices' journal codes from it). Neither imports a
# networking module (test_privacy_claims).
NO_NETWORK = {"codex_auto_resume_advanced.courier", "codex_auto_resume_advanced.courier.outbox"}
NETWORKING = ("socket", "ssl", "socketserver", "smtplib", "http.client", "http.server", "urllib.request")
# The modules a watcher and a Dashboard service take on the way to asking the capabilities anything.
IMPORTED = ("registry", "runtime", "engine.push", "engine.feed", "engine.remote", "control.courier", "control.remote",
            "surfaces")


class NothingOfTheNetworkWhileOffTests(ac.AdvancedCase):
    def test_taking_the_edition_loads_no_code_that_reaches_the_network(self):
        """In a process of its own, as what is already imported here would hide it."""
        code = ("import sys\n"
                + "".join("import codex_auto_resume_advanced.%s\n" % name for name in IMPORTED)
                + "print('\\n'.join(sorted(m for m in sys.modules if '.courier.' in m or m.endswith('.courier')"
                  " or m in %r)))\n" % (NETWORKING,))
        root = Path(__file__).resolve().parents[2]
        found = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                               env=dict(os.environ, CODEX_AR_EDITION="advanced",
                                        PYTHONPATH="%s;%s" % (root / "src", root / "advanced" / "src")),
                               creationflags=NO_WINDOW)
        self.assertEqual((found.returncode, found.stderr), (0, ""))
        loaded = set(found.stdout.split())
        self.assertEqual(loaded - NO_NETWORK - {"codex_auto_resume_advanced.control.courier"}, set())

    def test_with_every_capability_off_no_courier_starts(self):
        """Every way one could start fails the test, and the watcher's tick asks every capability the edition offers."""
        runtime = self.runtime(*registry.DEFINITIONS)
        before = set(threading.enumerate())

        def no(*unused, **keywords):
            raise AssertionError("something of the network was started with every capability off")
        with patch.object(subprocess, "Popen", no), patch.object(socket, "socket", no), \
                patch.object(threading.Thread, "start", no), patch.object(launch, "start", no), \
                patch.object(launch, "start_due", no):
            self.assertIs(runtime.tick({}), DEFER)
        self.assertEqual(set(threading.enumerate()) - before, set())


if __name__ == "__main__":
    unittest.main()

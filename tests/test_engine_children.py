"""The app gate through the real transport, where the app main runs two of the configured engine.

Codex 26.930's app starts a second `codex.exe` beside its app server - `exec-server` for a cloud
environment - from the same binary under the same main (measured 2026-10-04), and the pairing
refused both for ever: a real usage-limit recovery waited for the app long after its reset.

These drive the engine against codexsim, as tests/test_engine.py does, with the harness written
there; only the processes and the Restart Manager are stubs, and the pairing, the identity and
the engine are real. They are a module of their own because tests/test_engine.py is one of the
scenario modules v0.6.10 was tested with and stays the file that tag has (tests/neutral.py,
tests/test_released_calls.py): v0.6.10 has no run of these to be compared with.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codexsim import CodexHome, SimBackend  # noqa: E402
from codex_auto_resume.codex import pairing, transport  # noqa: E402
from test_engine import EngineCase, T1  # noqa: E402


class TransportApp(SimBackend):
    """codexsim's backend, except that who the app is comes from the real transport. The engine
    is built with it, so whatever records the calls an engine makes of its backend sees these."""

    def __init__(self, home, real):
        super().__init__(home)
        self.real = real

    def app_identity(self):
        self.identity_calls += 1
        return self.real.app_identity()


class SeveralEngineChildrenTests(EngineCase):
    NATIVE = r"C:\Program Files"
    STORE_APP = NATIVE + r"\WindowsApps\OpenAI.Codex_26.930.2377.0_x64__2p2nqsd0c76g0\app\ChatGPT.exe"
    ENGINE = r"C:\FakeLocalAppData\OpenAI\Codex\bin\abcdef0123456789\codex.exe"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = CodexHome(Path(temp.name) / "codex-home")
        self.real = transport.Backend(home.root, Path(self.ENGINE))
        self.h = self.fresh(home=home, backend=TransportApp(home, self.real))
        self.root = self.h.root

    def through_the_transport(self, state_holders):
        real = self.real
        exe = str(real.codex_exe)
        rows = [{"pid": 10, "parent": 1, "path": self.STORE_APP},
                {"pid": 20, "parent": 10, "path": exe},      # app-server
                {"pid": 21, "parent": 10, "path": exe}]      # exec-server
        identities = {10: {"pid": 10, "created": 100, "path": self.STORE_APP.lower()},
                      20: {"pid": 20, "created": 200, "path": exe.lower()},
                      21: {"pid": 21, "created": 300, "path": exe.lower()}}

        def holders(path):
            self.assertEqual(Path(path), real.codex_home / "state_5.sqlite")
            return list(state_holders)
        for stub in (patch.dict(os.environ, {"ProgramW6432": self.NATIVE}),
                     patch.object(real, "_compatible"),
                     patch.object(transport, "inventory", return_value=rows),
                     patch.object(pairing, "process_identity", side_effect=lambda pid: dict(identities[pid])),
                     patch.object(pairing, "resource_users", side_effect=holders)):
            stub.start()
            self.addCleanup(stub.stop)
        # The simulated app holds the conversation for exactly the app server's identity.
        self.h.backend.app = {**identities[10], "server": identities[20]}

    def test_the_app_server_holding_the_state_database_passes_the_app_gate(self):
        self.through_the_transport([{"pid": 20, "created": 200}])
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.assertNotIn((T1, "waiting_for_app", "desktop_app_unavailable"), self.h.logs)
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_both_holding_it_still_waits_for_the_app(self):
        self.through_the_transport([{"pid": 20, "created": 200}, {"pid": 21, "created": 300}])
        self.ready_after_reset()
        for _ in range(3):
            self.h.tick(advance=60)
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_app", "desktop_app_unavailable"))


if __name__ == "__main__":
    unittest.main()

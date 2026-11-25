"""v0.6.26 final, live acceptance S5: the standard edition's plug changes nothing of how the watcher follows its engine.

Core's App._served_elsewhere now also reads what the edition's plug saw of the app serving from another engine
(the advanced meter's own look, advanced/tests/test_advanced_meter_engine_elsewhere.py). The standard edition's NULL
plug has nothing to say: the watcher moves only on what its own pairing saw, as before, and lists no process to find
out. A plug that raises there moves nothing either.

The process list, the identities and Windows' signature answer are stubs (test_signed_engine); nothing real is read.

    PYTHONPATH="src;tests" python -m unittest test_engine_elsewhere_null_plug
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_signed_engine import SignedEngineCase  # noqa: E402
from codex_auto_resume.domain.plug import Plug, guard  # noqa: E402


class Raising(Plug):
    @property
    def served_elsewhere(self):
        raise RuntimeError("a plug's own failure")


class NullPlugTests(SignedEngineCase):
    def test_without_the_pairing_looking_the_watcher_lists_no_process_and_stays(self):
        self.assertTrue(self.app.plug.null)
        self.serve(self.package)
        for at in (0, 1, 3600):
            self.assertFalse(self.moved(at))
        self.assertEqual(self.listings, 0, "a process list was read on a tick")
        self.assertIs(self.app.backend(), self.first)

    def test_what_its_own_pairing_saw_still_moves_it(self):
        self.serve(self.package)
        self.assertIsNone(self.paired())
        self.assertTrue(self.moved(0))
        self.assertEqual(self.app.backend().codex_exe, self.package)

    def test_a_plug_that_raises_moves_nothing(self):
        self.app._plug = guard(Raising())
        self.serve(self.package)
        self.assertFalse(self.moved(0))
        self.assertIs(self.app.backend(), self.first)


if __name__ == "__main__":
    unittest.main()

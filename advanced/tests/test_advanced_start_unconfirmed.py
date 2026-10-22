"""A continuation after the reset written to the app with no answer in time is not told as one that failed (v0.6.18,
the advanced audit's M1): the turn may have started, as a stop with no answer may have been made - UNCONFIRMED, no
"could not continue" notice; the next look at the turns finds the newer turn and ends it SUPERSEDED, nothing sent twice.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume_advanced.codex import ipc  # noqa: E402
from test_advanced_ipc import THREAD  # noqa: E402
from test_advanced_usagestop import StopCase  # noqa: E402
from test_engine import T1  # noqa: E402


@unittest.skipUnless(sys.platform == "win32", "a Windows named pipe")
class PipeTests(unittest.TestCase):
    def app(self, **script):
        import fakeipc
        found = fakeipc.FakeApp(script)
        self.addCleanup(found.close)
        return found

    def test_a_start_written_with_no_answer_is_unconfirmed(self):
        """Fails with the mapping reverted: NO_ANSWER, which the stop told as "could not continue"."""
        with patch.object(ipc, "READ_SECONDS", 1.0):
            app = self.app(**{"thread-follower-start-turn": None})
            self.assertEqual(ipc.start_turn(THREAD, "x", channel=ipc.Channel(app.name)), ipc.Stop.UNCONFIRMED)
            before = self.app(**{"thread-owner-discovery": None})
            self.assertEqual(ipc.start_turn(THREAD, "x", channel=ipc.Channel(before.name)), ipc.Stop.NO_ANSWER,
                             "nothing written yet: a plain failure")


class UnconfirmedStartTests(StopCase):
    def test_no_failure_notice_and_the_started_turn_ends_it_superseded(self):
        """Fails with the UNCONFIRMED branch reverted: "not_continued" was said of a turn that had started."""
        plug, turn = self.running()
        plug.runtime._code_of(plug.runtime.registry.get("usage_meter"))._app_running = lambda: False
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        self.start_answer = ipc.Stop.UNCONFIRMED
        self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1)
        self.assertNotIn("not_continued", self.kinds(plug))
        self.assertNotIn("pause.not_continued", self.journal(plug))
        self.h.home.add_turn(T1)                            # it had started after all
        self.h.tick(advance=301)
        self.h.tick(advance=1)
        self.assertEqual(len(self.starts), 1, "never sent twice")
        (row,) = plug.runtime.state.continuations(capability=self.cap, pending=None)
        self.assertEqual(row["reason"], "superseded")


if __name__ == "__main__":
    unittest.main()

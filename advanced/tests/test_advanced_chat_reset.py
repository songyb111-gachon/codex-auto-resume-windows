"""A chat message written while Codex's usage limit is full (v0.6.19, the roadmap's "a message written while the limit is
full, sent when it resets"): it waits in the state with its words - nothing cancels or expires it - core's usage gate
holds it as it holds every send, and it goes into the conversation once Codex says usage is available again; the page
is told the limit is full (control/chat.limit_full), from the reading the watcher keeps, so it can say so.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_chat import ChatCase  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume_advanced.control import chat as control  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ChatState  # noqa: E402
from test_engine import T1  # noqa: E402


class ResetTests(ChatCase):
    def test_a_message_written_while_the_limit_is_full_waits_and_goes_when_it_resets(self):
        """Nothing cancels or expires a waiting message while the limit is full, and core sends it after."""
        plug = self.armed()
        self.h.backend.usage_result = {"available": False, "reset_at": self.h.now + 3600, "limit_type": "300m",
                                       "reason": "blocked"}
        key = self.waiting(plug)
        for _ in range(5):
            self.h.tick(advance=600)
        row = plug.runtime.state.chat_by_record(key)
        self.assertEqual(self.calls, [], "nothing is sent while the limit is full")
        self.assertEqual(row["state"], ChatState.WAITING)
        self.assertEqual(row["words"], "Please run the tests again.", "it keeps its words while it waits")
        self.h.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows",
                                       "reason": "ok"}
        self.h.tick(advance=1200)
        self.assertEqual(len(self.calls), 1, "sent once the limit reset")
        self.assertEqual(plug.runtime.state.chat_by_record(key)["state"], ChatState.IN_FLIGHT)

    def test_the_page_is_told_when_the_limit_is_full(self):
        """Fails with limit_full reverted to always False."""
        plug = self.armed()
        now = self.h.now
        window = {"bucket": "codex", "window": "primary", "used_percent": 100, "window_minutes": 300,
                  "reset_at": int(now) + 3600}
        with Store(plug.runtime.paths.state_dir) as store:
            store.heartbeat(now, pid=1, session_id="s", started_at=now, ok=True, engine_state="compatible",
                            code_version="0", usage=(now, [window]))
        self.assertTrue(control.limit_full(plug.runtime, now))
        self.assertFalse(control.limit_full(plug.runtime, now + 7200), "a reset that has passed is not full")


if __name__ == "__main__":
    unittest.main()

"""A record the plug marks `pause_keeps` (v0.6.23, the in-app chat's: its statement says a Pause or Cancel does not take
back a message Codex already holds) is left in Codex's queue by a Pause - by recovery switched off, as the Dashboard, the
tray, Telegram and the loopback API all switch it, and by an administrator's DisableAutoResume - never deleted and never
withdrawn; asked back by the plug, or with its conversation switched off, it is taken back as before. A record not
marked is taken back by a Pause as it always was (H4).

The plug is test_plug_records' own (`Records`); the engine runs against codexsim, as every engine scenario does.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_engine import T1  # noqa: E402
from test_plug_records import RecordCase, record  # noqa: E402
from codex_auto_resume.domain import plughands  # noqa: E402


def pause_by_settings(h):
    h.store.set_enabled(False, h.now)


def pause_by_policy(h):
    h.engine.managed = SimpleNamespace(disable_auto_resume=True)


PAUSES = {"recovery switched off": pause_by_settings, "DisableAutoResume": pause_by_policy}


class PauseKeepsTests(RecordCase):
    def sent(self, keeps, h=None, **changes):
        """A record sent and held in Codex's queue, as P2 hands it in flight then: its queue id."""
        h = h or self.h
        h.backend.after_accept = "queue"
        plug = self.plug(record(pause_keeps=keeps), h=h)
        h.tick()
        self.assertEqual(plug.moves[-1][0], "sent")
        queue_id = h.home.queued(T1)[0]
        plug.handed = [record(state="in_flight", words=None, sent_at=h.now, queue_id=queue_id, pause_keeps=keeps,
                              **changes)]
        return plug, queue_id

    def fresh_case(self):
        h = self.fresh()
        h.home.add_turn(T1)
        h.backend.loaded_map[T1] = "loaded"
        return h

    def test_a_pause_by_each_route_leaves_one_marked_in_codexs_queue(self):
        """Fails with the mark ignored in `_take_back`: the Pause would delete it and tell it withdrawn."""
        for how, pause in PAUSES.items():
            for watched_first in (False, True):
                with self.subTest(how, watched_first=watched_first):
                    h = self.fresh_case()
                    plug, queue_id = self.sent(True, h=h)
                    if watched_first:
                        h.tick(advance=5)                    # watched once in flight, from P2's answer
                    pause(h)
                    for _ in range(3):
                        h.tick(advance=60)
                    self.assertEqual(h.home.queued(T1), [queue_id], "still in Codex's queue")
                    self.assertEqual(h.backend.deleted, [], "nothing deleted")
                    self.assertNotIn("withdrawn", [move for move, _g, _r in plug.moves])
                    self.assertNotIn("withdraw_refused", [move for move, _g, _r in plug.moves])
                    self.assertEqual(len(h.backend.send_calls), 1, "never sent twice")

    def test_held_through_a_pause_it_is_delivered_when_codex_takes_it(self):
        plug, queue_id = self.sent(True)
        pause_by_settings(self.h)
        self.h.tick(advance=5)
        self.h.home.dispatch(T1)
        self.h.tick(advance=5)
        self.assertEqual(plug.moves[-1][0], "delivered")

    def test_one_not_marked_is_still_taken_back_by_each_pause(self):
        for how, pause in PAUSES.items():
            with self.subTest(how):
                h = self.fresh_case()
                plug, _queue_id = self.sent(False, h=h)
                pause(h)
                h.tick(advance=5)
                self.assertIn(("withdrawn", "consent", "paused"), plug.moves)
                self.assertEqual(h.home.queued(T1), [])

    def test_asked_back_by_the_plug_or_its_conversation_off_one_marked_is_still_taken_back(self):
        plug, _queue_id = self.sent(True, withdraw=True)
        self.h.tick(advance=5)
        self.assertEqual(plug.moves[-1], ("withdrawn", "consent", "user_cancelled"))
        self.assertEqual(self.h.home.queued(T1), [])
        h = self.fresh_case()
        plug, _queue_id = self.sent(True, h=h)
        h.store.set_thread_enabled(T1, False, at=h.now)
        h.tick(advance=5)
        self.assertEqual(plug.moves[-1][0], "withdrawn")
        self.assertEqual(h.home.queued(T1), [])

    def test_what_core_takes_of_the_mark(self):
        base = record()
        self.assertIs(plughands.records_of([base])[0]["pause_keeps"], False, "one naming none is taken back")
        self.assertIs(plughands.records_of([dict(base, pause_keeps=True)])[0]["pause_keeps"], True)
        for bad in (1, "yes", None):
            with self.subTest(bad):
                self.assertEqual(plughands.records_of([dict(base, pause_keeps=bad)]), ())


if __name__ == "__main__":
    unittest.main()

"""A person's message from the edition's plug, marker-free through its channel (v0.6.19, engine/recordchannel.py):
where the plug names a channel for a MESSAGE record and answers CLIENT_ID at P15, the words go through that channel
exactly as typed under the client id core derives from the record's id, and core proves it by that id; a CONTINUATION
never goes so, and with no channel nothing more is asked than before.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_engine import T1  # noqa: E402
from test_plug_records import KEY, WORDS, RecordCase, record  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import Alternative  # noqa: E402


class Channel:
    """The plug's channel, adding the item to codexsim's queue under the id it is handed, as thread/queue/add does."""

    def __init__(self, h):
        self.h, self.sent = h, []

    def send(self, thread_id, words, *, launch_guard=None, client_id=None):
        with launch_guard as permitted:
            if permitted is not True:
                return {"outcome": "not_started", "error_code": "queue_consent_refused"}
            self.sent.append((thread_id, words, client_id))
            self.h.home.enqueue(thread_id, words, client_id=client_id)
        return {"outcome": "accepted", "queue_id": None}


class ChannelTests(RecordCase):
    def test_a_message_goes_exactly_as_typed_under_its_id_and_is_proven_by_it(self):
        """Fails with the channel reverted: the message waits (held) and nothing is sent."""
        channel = Channel(self.h)
        plug = self.plug(sender=channel, delivery=Alternative.CLIENT_ID)
        self.h.tick()
        derived = ids.continuation_client_id(KEY)
        self.assertEqual(channel.sent, [(T1, WORDS, derived)])
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(plug.moves, [("sent", None, None)])
        plug.handed = [record(state="in_flight", words=None, sent_at=self.h.now)]
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.assertEqual(plug.moves[-1][0], "delivered", "proven by its client id, with no marker anywhere")

    def test_a_continuation_never_goes_through_a_channel(self):
        channel = Channel(self.h)
        plug = self.plug(record(purpose="continuation", ordinal=1), sender=channel, delivery=Alternative.CLIENT_ID)
        self.h.tick()
        self.assertEqual(channel.sent, [])

    def test_without_client_id_the_channel_is_still_never_used(self):
        channel = Channel(self.h)
        plug = self.plug(sender=channel)
        self.h.tick()
        self.assertEqual((channel.sent, self.h.backend.send_calls), ([], []))
        self.assertEqual(plug.moves, [("waiting", "submission_safe", "held")])

    def test_with_no_channel_p15_is_not_asked(self):
        plug = self.plug(delivery=Alternative.CLIENT_ID)
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [(T1, WORDS + "\n\n" + ids.short_marker(KEY))])
        asked = [hook for hook, arguments in plug.asked if arguments and isinstance(arguments[0], dict)
                 and "record_id" in arguments[0]]
        self.assertNotIn("delivery", asked)


if __name__ == "__main__":
    unittest.main()

"""A person's message from the edition's plug, sent marker-free through its channel (v0.6.19, the in-app chat).

A record of the plug's (P2, engine/plugrecords.py) goes through core's own backend, its words ending in its marker,
and a channel the plug names for one waits instead. One kind is let through a channel: a person's own MESSAGE for
which the plug names a channel (P5) and answers CLIENT_ID at P15 - the in-app chat's, whose words must reach the
conversation exactly as typed. Its words then go with no marker, under the client id core derives from the record's
id (ids.continuation_client_id), and every look that proves, follows, takes back or settles it is made for that id
(`_record_proof`), as core's own marker-free continuation is (engine/delivery.py). A CONTINUATION or a wrap-up - the
product's own words - never goes so: A4's marker stays on product text. Every gate, the claim, the pre-send look and
the launch guard are the same.

The plug is asked once for a record, where core takes it up - at the one dispatch, after the one question of P5, or
handed in flight - and the answer goes with the record as its `client_id`, which only the id core derives for that
record can be: a Pause then watches and takes back what is in flight with the plug asked nothing (K5). A message sent
with no marker and later handed by a plug that no longer answers CLIENT_ID is looked for by its marker, never found,
and unproven a day on - never sent again (A6).
"""
from __future__ import annotations

from ..domain import ids
from ..domain.plug import Alternative
from ..domain.plughands import RecordPurpose


class RecordChannelMixin:
    def _marker_free(self, record, sender) -> bool:
        """Whether `record` - a person's MESSAGE for which the plug named a channel (`sender`, P5, asked once by the
        one dispatch) and asks at P15 to carry with no marker - goes through that channel under the derived client id.
        Handed in flight, with no `sender` (None), P15 alone is asked: what it answers is how it was sent. P15 is never
        asked where core's backend sends, so a plug with no channel is asked nothing more than before. A look that
        raises is no: the marker, as ever."""
        if record.get("purpose", RecordPurpose.MESSAGE) != RecordPurpose.MESSAGE or sender is self.backend:
            return False
        try:
            return self.plug.delivery(dict(record)) is Alternative.CLIENT_ID
        except Exception:
            return False

    def _record_carried(self, record, sender=None) -> dict:
        """`record` as core carries it from here: with the client id core derives from its id where it goes
        marker-free (`_marker_free`, the plug asked once), else with none."""
        client = ids.continuation_client_id(record["record_id"]) if self._marker_free(record, sender) else None
        return dict(record, client_id=client)

    def _record_queued(self, record) -> dict:
        """`record` handed in flight, with the queue item Codex said it took at its send where the plug kept none (the
        chat keeps no queue id): remembered from that send in this process (`_flying`), so a message Codex has not
        taken can be taken back out of its queue. After a restart nothing is remembered, and one Codex never takes is
        unproven a day on - never sent again (A6)."""
        known = self._flying().get(record["record_id"])
        if record.get("queue_id") is None and isinstance(known, dict) and known.get("queue_id") is not None:
            return dict(record, queue_id=known["queue_id"])
        return record

    @staticmethod
    def _record_client(record):
        """The client id `record` goes under with no marker: the one core derives from its id, and nothing else."""
        client = record.get("client_id")
        if (client is not None and record.get("purpose", RecordPurpose.MESSAGE) == RecordPurpose.MESSAGE
                and client == ids.continuation_client_id(record["record_id"])):
            return client
        return None

    def _record_proof(self, record):
        """What proves `record` is ours: its derived client id when it goes marker-free, else its marker."""
        return self._record_client(record) or record["marker"]

    def _record_words(self, record):
        """What the one send carries: the words alone marker-free, else the words, a blank line and the marker."""
        if self._record_client(record) is not None:
            return record["words"]
        return record["words"] + "\n\n" + record["marker"]

    def _record_carrying(self, record) -> dict:
        """What the one send is handed beside the words: the derived client id marker-free, else nothing."""
        client = self._record_client(record)
        return {"client_id": client} if client is not None else {}

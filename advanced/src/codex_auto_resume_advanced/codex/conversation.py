# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""A conversation's messages and replies, read-only, for the Dashboard's Chat page alone (v0.6.19, codex_chat).

The standard edition never reads what a conversation says (B7). With the chat on, and only while its page asks
(the bridge's advanced-chat-read), this reads the conversation's last TURNS turns from Codex's history: each turn's
status - in progress until Codex records it finished, which MC2 found thread_turns says first (no approval wait shows
there: approvals are still answered in Codex) - the text of its `userMessage` and `agentMessage` items, and how many
commands, file changes and tool calls it made, as counts. Nothing else of an item is read: one statement selects
item_json only for those two kinds (TEXT_KINDS), each cut at ITEM_BYTES and a view at VIEW_BYTES; this product's own
markers are taken out of what is shown. Nothing read is stored, logged, journalled or sent anywhere: it goes to the
page that asked and is dropped.

The file is found and opened as every read of Codex's history here is (codex/turns.connect): the newest generation,
read-only, query_only on and trusted_schema off, the columns read required. Anything that goes wrong is
TurnsUnavailable.
"""
from __future__ import annotations

import json
import re
import sqlite3

from codex_auto_resume.domain import ids

from .turns import TurnsUnavailable, connect

TURNS = 20
ITEM_BYTES = 16 * 1024
VIEW_BYTES = 256 * 1024
TEXT_KINDS = ("userMessage", "agentMessage")
# The kinds shown as counts, never their content.
COUNTED = {"commandExecution": "commands", "fileChange": "files", "mcpToolCall": "tools"}
TURN_COLUMNS = frozenset({"thread_id", "turn_id", "status", "rollout_ordinal", "started_at", "completed_at"})
ITEM_COLUMNS = frozenset({"thread_id", "turn_id", "item_type", "item_json", "rollout_ordinal"})
LAST_TURNS = ("SELECT turn_id, status, started_at, completed_at FROM thread_turns WHERE thread_id=? "
              "ORDER BY rollout_ordinal DESC LIMIT ?")
TEXTS = ("SELECT item_type, item_json FROM thread_items WHERE thread_id=? AND turn_id=? AND item_type IN (?, ?) "
         "ORDER BY rollout_ordinal")
COUNTS = "SELECT item_type, count(*) FROM thread_items WHERE thread_id=? AND turn_id=? GROUP BY item_type"
STATEMENTS = (LAST_TURNS, TEXTS, COUNTS)
MARKER = re.compile(r"\s*\[codex-auto-resume:[0-9a-f]{16}\]\s*$")
STATUSES = ("completed", "failed", "interrupted", "inProgress")


def _text(kind, raw) -> str | None:
    """The words of one item of a TEXT_KINDS kind, cut at ITEM_BYTES, our marker taken out - or None."""
    try:
        item = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    if not isinstance(item, dict):
        return None
    if kind == "userMessage":
        parts = [part.get("text") for part in item.get("content") or () if isinstance(part, dict)
                 and part.get("type") == "text" and isinstance(part.get("text"), str)]
        words = "\n".join(parts)
    else:
        words = item.get("text") if isinstance(item.get("text"), str) else ""
    words = MARKER.sub("", words)
    encoded = words.encode("utf-8")
    if len(encoded) > ITEM_BYTES:
        words = encoded[:ITEM_BYTES].decode("utf-8", errors="ignore")
    return words or None


class Conversation:
    """The history of the Codex home `home`, as the Chat page reads it."""

    def __init__(self, home):
        self.home = home

    def view(self, thread_id) -> list:
        """The conversation's last TURNS turns, oldest first: [{turn_id, status, started_at, completed_at,
        messages: [{"from": "you"|"codex", "words"}], counts: {commands, files, tools}}]."""
        if not ids.is_uuid(thread_id):
            raise TurnsUnavailable("not a conversation")
        connection = connect(self.home, "history", {"thread_turns": TURN_COLUMNS, "thread_items": ITEM_COLUMNS})
        try:
            turns = connection.execute(LAST_TURNS, (thread_id, TURNS)).fetchall()
            shown, budget = [], VIEW_BYTES
            for turn_id, status, started, completed in turns:
                messages = []
                for kind, raw in connection.execute(TEXTS, (thread_id, turn_id, *TEXT_KINDS)):
                    words = _text(kind, raw)
                    if words is None or budget <= 0:
                        continue
                    budget -= len(words.encode("utf-8"))
                    messages.append({"from": "you" if kind == "userMessage" else "codex", "words": words})
                counts = {name: 0 for name in COUNTED.values()}
                for kind, count in connection.execute(COUNTS, (thread_id, turn_id)):
                    if kind in COUNTED:
                        counts[COUNTED[kind]] += int(count)
                shown.append({"turn_id": turn_id if ids.is_uuid(turn_id) else None,
                              "status": status if status in STATUSES else "other",
                              "started_at": started if type(started) is int else None,
                              "completed_at": completed if type(completed) is int else None,
                              "messages": messages, "counts": counts})
            return list(reversed(shown))
        except (sqlite3.Error, ValueError):
            raise TurnsUnavailable("the conversation cannot be read") from None
        finally:
            connection.close()

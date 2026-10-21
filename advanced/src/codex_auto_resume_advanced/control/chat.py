# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's Chat page (v0.6.19): a conversation's last turns read, a message sent, one cancelled.

Each is the long-lived bridge's, the Dashboard's alone (surfaces.py); no MCP tool reaches any of them, and nothing they
read or carry reaches a log, the journal, diagnostics, a notification, the status or MCP. A conversation is read
only while chat stands on (codex/conversation.py, read where the page asks and dropped); a message is accepted only
while chat is on, its conversation is switched on and nothing of the person's from this page waits in it, checked as
core checks a message of a person's (continuation.validate_prompt: no empty text, no marker, no shipped template), at
most 2,000 characters. Cancel reaches only a message still waiting: one Codex already holds is its own.
"""
from __future__ import annotations

import secrets

from codex_auto_resume import continuation
from codex_auto_resume.domain import ids

from ..engine.chat import CAPABILITY, WORDS
from ..vocabulary import ChatReason, ChatState, Refusal
from .resets import _on, _refused, _stale, switched_off

SHOWN = ("chat_id", "state", "reason", "created_at", "sent_at", "finished_at")
RECENT = 3600


def view(runtime, thread) -> dict:
    """advanced-chat-read: the conversation's last turns (codex/conversation.py) and the page's own messages to it -
    a waiting one's words with it (the person's, until it is sent) - or a refusal."""
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _on(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    from ..codex import inuse
    from ..codex.conversation import Conversation
    from ..codex.turns import TurnsUnavailable
    try:
        turns = Conversation(inuse.home(runtime.paths)).view(thread)
    except TurnsUnavailable:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    try:
        rows = runtime.state.chats(thread_id=thread)
        generation = runtime.state.meta()["generation"]
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    now = runtime.clock()
    messages = []
    for row in rows:
        if row["state"] in (ChatState.DONE, ChatState.CANCELLED) and (row["finished_at"] or 0) < now - RECENT:
            continue
        item = {name: row.get(name) for name in SHOWN}
        item["words"] = row["words"] if row["state"] == ChatState.WAITING else None
        messages.append(item)
    return {"done": True, "refusal": None, "generation": generation, "turns": turns, "messages": messages,
            "words_limit": WORDS}


def send(runtime, argument) -> dict:
    """advanced-chat-send: one message to `thread_id`, waiting for core to take it at its next look."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread, words = argument.get("thread_id"), argument.get("words")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    if not _on(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON, runtime)
    if switched_off(runtime, thread):
        return _refused(Refusal.CONVERSATION_OFF, runtime)
    try:
        continuation.validate_prompt(words)
    except Exception:
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    if len(words) > WORDS:
        return _refused(Refusal.PROMPT_REFUSED, runtime)
    try:
        if runtime.state.chats(thread_id=thread, pending=True):
            return _refused(Refusal.BEING_SENT, runtime)
        runtime.state.add_chat(thread, words, secrets.token_hex(32), at=runtime.clock())
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    try:
        from .sendnow import wake
        wake(runtime.paths)
    except Exception:
        pass                                         # the next tick takes it
    return dict(view(runtime, thread), done=True)


def cancel(runtime, argument) -> dict:
    """advanced-chat-cancel: the conversation's message still waiting, cancelled, its words gone."""
    if _stale(runtime, argument.get("generation")):
        return _refused(Refusal.STALE_GENERATION, runtime)
    thread = argument.get("thread_id")
    if not ids.is_uuid(thread):
        return _refused(Refusal.INVALID_REQUEST, runtime)
    try:
        cancelled = runtime.state.cancel_chat(ChatReason.CANCELLED, thread_id=thread, at=runtime.clock())
    except Exception:
        return _refused(Refusal.STATE_UNAVAILABLE, runtime)
    if not cancelled:
        return _refused(Refusal.BEING_SENT, runtime)
    return dict(view(runtime, thread), done=True)

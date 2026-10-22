"""Codex's words and numbers, read the same way everywhere.

A status Codex gives, a time it writes, the JSON in a row: each is read through one function
here, so two readers cannot disagree about what a value means.
"""
from __future__ import annotations

import json
import math

from .. import failures, machine
from ..domain import ids


MAX_SCAN_BYTES = 8 * 1024 * 1024

MAX_META_BYTES = 256 * 1024

MAX_ITEM_BYTES = 1024 * 1024

# A person's own conversations in the Codex desktop app (A15), by what Codex records of them. thread_source is
# Codex's analytics label (codex-rs ThreadSource: user, subagent, guardian_review, memory_consolidation, or a
# feature's name), not a mark of whose a conversation is: the app leaves it unset on many conversations of its
# own - the sessions it copies in from another tool (Claude Code, forks made there included; a fork made in the
# Codex app is labelled user), 41 of 64 on the owner's PC (0.149 to 0.162),
# their rollout's first line without the key - and writes chatgpt_handoff on one ChatGPT handed over to it,
# opened as codex_work_desktop (issue #27). A copied-in turn carries no Codex error code, so nothing in such a
# conversation is detected until Codex itself runs a turn there that fails (A13, A16). The state row and the
# rollout must still say the same; a subagent, a review or a memory pass is never one of these.
OWN_THREAD_SOURCES = frozenset({"user", "chatgpt_handoff", None})
# v0.6.16-beta.3 (P19, plughands.Widening.EVERY_DESKTOP): the kinds Codex makes for itself, which nothing takes up
# however widely the plug asks - a subagent (its parent is told instead), a review, a memory pass, a conversation an
# agent made. A closed list: every other label, today's and tomorrow's, is taken up while the plug asks it.
INTERNAL_THREAD_SOURCES = frozenset({"subagent", "guardian_review", "memory_consolidation", "agent_created_thread"})


def taken_thread_source(value, widened=frozenset()) -> bool:
    """Whether a conversation labelled `value` is one this product takes up: a person's own (OWN_THREAD_SOURCES), or -
    while the plug widens to every desktop conversation (P19) - any label but INTERNAL_THREAD_SOURCES. The standard
    edition's `widened` is always empty, so this is OWN_THREAD_SOURCES exactly."""
    if value in OWN_THREAD_SOURCES:
        return True
    return ("every_desktop" in widened and isinstance(value, str) and 0 < len(value) <= 64
            and value not in INTERNAL_THREAD_SOURCES)
DESKTOP_ORIGINATORS = frozenset({"Codex Desktop", "codex_work_desktop"})
# v0.6.16-beta.4 (issue #37): a conversation started in the Codex CLI's TUI and continued in the Desktop app is the
# app's - Codex rewrites its threads row to source vscode when the app takes it over, while the rollout's first line
# keeps the CLI's originator and source - and a fork the app made of it keeps the originator with source vscode. Only
# with that row (codex/eligibility.py): a TUI conversation the app never took over (threads source cli) stays the
# edition's other_sessions' to name.
ADOPTED_ORIGINATORS = frozenset({"codex-tui"})

KNOWN_STATUSES = machine.TURN_STATUSES - {"other"}      # Codex's own four; "other" is ours

# Item types that count as a turn having produced something. Anything Codex adds later
# does not count until it is added here on purpose.
PROGRESS_ITEM_TYPES = frozenset({"agentMessage", "commandExecution", "fileChange", "mcpToolCall"})
# The same, in one order, for a query's parameters.
PROGRESS_KINDS = tuple(sorted(PROGRESS_ITEM_TYPES))


def _turn_status(value):
    if value is None:
        return None
    return value if value in KNOWN_STATUSES else "other"


def epoch(value) -> bool:
    return machine.epoch(value, *machine.EPOCH_CODEX, exact=True)


def _json(value):
    if not isinstance(value, str) or len(value) > MAX_ITEM_BYTES:
        return None
    try:
        return json.loads(value)
    except (ValueError, RecursionError):
        return None


def normalize(row) -> dict | None:
    """Normalize just the required scalar fields, discarding raw error text."""
    if not isinstance(row, dict):
        return None
    tid, turn = row.get("thread_id"), row.get("turn_id")
    status = row.get("status")
    ordinal = row.get("ordinal", row.get("rollout_ordinal"))
    if (not ids.is_uuid(tid) or not ids.is_uuid(turn)
            or not isinstance(status, str) or status not in KNOWN_STATUSES
            or type(ordinal) is not int or ordinal < 0):
        return None
    started, completed = row.get("started_at"), row.get("completed_at")
    if not epoch(started) or (completed is not None and not epoch(completed)):
        return None
    if completed is not None and completed < started:
        return None
    wait = None
    if "category" in row:
        # Already normalized once: keep the decision rather than reclassifying from
        # fields that no longer exist, so normalize() stays idempotent.
        category = row["category"] if row["category"] in failures.CATEGORIES else None
        wait = failures.wait_seconds(row.get("retry_after"))
    else:
        if "error_json" in row:
            err = _json(row["error_json"])
            info = err.get("codexErrorInfo") if isinstance(err, dict) else None
            text = err.get("message") if isinstance(err, dict) else None
        else:
            info = row.get("error_info", row.get("codexErrorInfo"))
            text = row.get("message")
        # The raw error is classified here and then dropped: only the category name
        # continues past this point, so no error text can reach state, logs or a toast.
        category = failures.classify(info, text) if status == "failed" else None
        # v0.6.11: a Retry-After the structured error names, kept as a number of seconds for a
        # temporary failure only - the least its first wait may be (ladder.py) - and nothing else.
        wait = failures.retry_after(info) if category in failures.TRANSIENT else None
    found = {"thread_id": tid, "turn_id": turn, "status": status,
             "started_at": started, "completed_at": completed,
             "ordinal": ordinal, "category": category}
    if wait is not None and category in failures.TRANSIENT:
        found["retry_after"] = wait
    return found


def error_shape(row) -> dict:
    """What a failed turn's error says of itself (failures.shape), read from its row as `normalize`
    reads it: Codex's code, a status, a form, whether a message exists - never the message. An error
    that is there and is no JSON object is unrecognised."""
    if "error_json" in row:
        raw = row["error_json"]
        err = _json(raw)
        if raw is not None and not isinstance(err, dict):
            return failures.shape(False)                     # there, and no object: unrecognised
        info = err.get("codexErrorInfo") if isinstance(err, dict) else None
        text = err.get("message") if isinstance(err, dict) else None
    else:
        info, text = row.get("error_info", row.get("codexErrorInfo")), row.get("message")
    return failures.shape(info, text)

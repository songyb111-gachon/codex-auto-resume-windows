"""Where Codex keeps its files, and which of them this product may open.

`DB_KINDS` is the whole list: three databases, and for each the columns that must be there.
Anything outside a real path under the Codex home is refused before it is opened.
"""
from __future__ import annotations

from pathlib import Path
import re


# Codex names its databases with a schema generation suffix (state_5, queue_1, ...).
# An app update can bump that number, so the file is discovered by pattern and then
# validated by the columns this tool actually reads. Extra columns are fine (Codex
# adds them over time); a MISSING required column means the schema moved and we refuse.
DB_KINDS = {
    "state": (re.compile(r"state_(\d+)\.sqlite\Z"), {
        "threads": {"id", "rollout_path", "source", "thread_source", "archived", "history_mode"},
    }),
    "history": (re.compile(r"thread_history_(\d+)\.sqlite\Z"), {
        "thread_turns": {"thread_id", "turn_id", "status", "error_json", "started_at",
                         "completed_at", "rollout_ordinal", "rollout_end_byte_offset",
                         "first_user_item_id"},
        "thread_items": {"thread_id", "turn_id", "item_id", "item_type", "item_json"},
    }),
    "queue": (re.compile(r"queue_(\d+)\.sqlite\Z"), {
        "queued_items": {"id", "thread_id", "payload_json"},
    }),
}


def _safe_path(path: Path) -> Path:
    # SQLite stores Windows extended paths; normalize before confinement checks.
    raw = str(path)
    if raw.startswith("\\\\?\\"):
        raw = raw[4:]
    return Path(raw).resolve()

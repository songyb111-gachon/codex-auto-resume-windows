"""What the icon says: its tooltip, and how much of one Windows will take.

Pure - it asks Windows nothing. The countdown is `ui/words.py`'s, shared with the popup and
the notification card, so that "3m 20s" is spelled one way wherever this product writes it.
"""
from __future__ import annotations

from ..words import countdown  # noqa: F401


TIP_CHARS = 128

# v0.6.14: the edition no surface names beside the version or the product (the owner, 2026-10-05: "no
# Standard label in the standard edition"). The status still carries its code; only the word is not shown.
UNNAMED_EDITION = "standard"


def tooltip(snapshot: dict, strings: dict, now: float, edition: str | None = None) -> str:
    """What hovering over the icon says. Built from the last tick; counted down locally.

    `edition` is the code of the edition that runs (edition.shown): the title names an advanced one, in the
    catalog's word, as every surface that shows the version does (v0.6.11). The standard edition, or none, and
    the title is the name alone (v0.6.14)."""
    title = strings.get("tray.title", "Codex Auto Resume")
    if edition and edition != UNNAMED_EDITION:
        title += " · " + strings.get("edition." + edition, edition)
    if not snapshot:
        return title
    if snapshot.get("failed"):
        line = strings.get("tray.failed", "A recovery failed")
    elif not snapshot.get("enabled", True):
        line = strings.get("tray.paused", "Paused")
    else:
        waiting, running = snapshot.get("waiting", 0), snapshot.get("running", 0)
        parts = []
        if running:
            parts.append(strings.get("tray.running", "{n} running in Codex").replace("{n}", str(running)))
        if waiting:
            parts.append(strings.get("tray.waiting", "{n} waiting").replace("{n}", str(waiting)))
            due = snapshot.get("next_at")
            if due:
                parts.append(strings.get("tray.next", "next check in {time}")
                             .replace("{time}", countdown(due - now)))
        line = " · ".join(parts) if parts else strings.get("tray.idle", "Nothing waiting")
    return (title + "\n" + line)[:TIP_CHARS - 1]

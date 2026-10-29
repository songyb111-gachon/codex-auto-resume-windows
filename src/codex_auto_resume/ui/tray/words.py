"""What the icon says: its tooltip, and how much of one Windows will take.

Pure - it asks Windows nothing. The countdown is `ui/words.py`'s, shared with the popup and
the notification card, so that "3m 20s" is spelled one way wherever this product writes it.
"""
from __future__ import annotations

from ..words import countdown, share, window_name  # noqa: F401


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
    elif snapshot.get("unconfirmed"):
        # v0.6.20: a sending nobody has confirmed - the amber light's own word.
        line = strings.get("activity.attention", "Needs your attention")
    elif not snapshot.get("enabled", True):
        line = strings.get("tray.paused", "Paused")
    else:
        waiting, running = snapshot.get("waiting", 0), snapshot.get("running", 0)
        parts = []
        if snapshot.get("held"):
            # v0.6.20: and a record waiting for a person: the amber light's own word, before the counts.
            parts.append(strings.get("activity.attention", "Needs your attention"))
        if running:
            parts.append(strings.get("tray.running", "{n} running in Codex").replace("{n}", str(running)))
        if waiting:
            parts.append(strings.get("tray.waiting", "{n} waiting").replace("{n}", str(waiting)))
            due = snapshot.get("next_at")
            if due:
                parts.append(strings.get("tray.next", "next check in {time}")
                             .replace("{time}", countdown(due - now)))
        line = " · ".join(parts) if parts else strings.get("tray.idle", "Nothing waiting")
    meter = meter_line(snapshot, strings)
    return (title + "\n" + line + ("\n" + meter if meter else ""))[:TIP_CHARS - 1]


# The key a surface puts an edition plug's fields under - domain/plug.EXTRA, which
# tests/test_usage_surfaces.py holds this to: the icon reads that one key and imports nothing of the plug's.
EXTRA = "advanced"
# The words a meter line is said in where the catalog has none (the catalog's own English).
_USAGE_WORDS = {"usage.window": "{window} {percent}%", "usage.weekly": "weekly", "usage.days": "{n}-day",
                "usage.hours": "{n}-hour", "usage.minutes": "{n}-minute", "usage.limit": "limit"}


def meter_line(snapshot, strings) -> str | None:
    """The advanced edition's usage meter as one line (v0.6.16-beta.3, issue #29): each window it last read, its
    length and its share - "5-hour 87% · weekly 40%". Only from what the edition's plug added under its one key; the
    standard edition adds nothing there, so its tooltip is what it always was. None where there is nothing to say."""
    added = snapshot.get(EXTRA) if isinstance(snapshot, dict) else None
    meter = added.get("meter") if isinstance(added, dict) else None
    windows = meter.get("windows") if isinstance(meter, dict) else None
    if not isinstance(windows, list):
        return None

    def say(key, **fields):
        text = strings.get(key) or _USAGE_WORDS.get(key, key)
        for name, value in fields.items():
            text = text.replace("{%s}" % name, str(value))
        return text
    parts = [say("usage.window", window=window_name(window.get("window_minutes"), say), percent=share(window))
             for window in windows if isinstance(window, dict)
             and type(window.get("used_percent")) in (int, float)]
    return " · ".join(parts) or None

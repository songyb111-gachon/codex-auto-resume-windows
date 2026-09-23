"""What the icon shows, as data: the snapshot it is updated from, and what the popup says.

Pure. Both of these are read by the watcher's loop rather than by the icon itself, which is
why they are not methods on it.
"""
from __future__ import annotations

from ... import machine



def popup_attention(popup) -> bool:
    """Whether the open popup says nothing can recover until a person acts.

    Only while it is open. A closed popup reads nothing, so what it last read is a moment ago,
    not now, and a problem that has since cleared would otherwise keep the icon on "needs
    attention" until somebody opened it again.
    """
    return bool(popup is not None and popup.visible and popup.attention())



def snapshot_from(store, now: float) -> dict:
    """What the icon shows, from our own store only: no Codex read, no content."""
    waiting, running, due = 0, 0, []
    for row in store.pending():
        if row["state"] in machine.WAITING:
            waiting += 1
            at = machine.eligible_at(row)
            if at:
                due.append(at)
        else:
            running += 1
    # When the newest certain failure was, and the newest recovery on its way: the icon asks the control layer
    # whether anybody has seen it since (Tray._failure_unseen), every second rather than every tick.
    return {"enabled": store.settings()["enabled"], "waiting": waiting, "running": running,
            "next_at": min(due) if due else None, "failures": store.failure_marks()}

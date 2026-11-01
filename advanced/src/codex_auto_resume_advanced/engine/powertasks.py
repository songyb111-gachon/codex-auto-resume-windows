# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The power action after tasks a person picked (power_after_tasks, v0.6.21, Discussion #57): its list, and its answer
at P21.

A person picks one or more conversations whose turn runs now and arms core's own power action for them, once
(control/powertasks.py). Core keeps the arming, the countdown, its notice with the Stop of that one batch, every way to
turn it off, and every condition but one (poweraction.decide: a stop first, DisablePowerAction, a pause, every recovery
open anywhere, Codex's history and turns and queue, two idle minutes, the countdown run out). The one it asks here is
whether those tasks have ended as the person chose to count them: one word, PowerTasks.

The list is a file of this edition's state folder, config/advanced/power-tasks.json (never settings.json): the core
arming's nonce it belongs to, whether a failed and an interrupted ending count beside a completed one, and each task as
its conversation and the turn that ran when it was armed - ids and booleans, nothing a conversation says (D2). Written
whole under its own named lock; a list for another nonce - a spent or replaced arming - answers nothing core may act on.

A task's end is followed as the follow-through view follows a delivered message (control/follow.py), ids and statuses
only: the turn's status in Codex's history (codex/turns.status, read-only); core's interruption of that turn, if one -
still waiting or on its way is running, recovered goes on to its recovery turn, ended otherwise is the task ended as its
turn's status says (interrupted, else failed); with none, the turn's own status. Anything that cannot be read is
UNKNOWN, on which core waits. Nothing here sends anything, or writes anything but the list.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from codex_auto_resume import config, machine
from codex_auto_resume.domain import ids
from codex_auto_resume.domain.power_vocabulary import PowerTasks

CAPABILITY = "power_after_tasks"
FILE_NAME = "power-tasks.json"
FORMAT = "codex-auto-resume/power-tasks/1"
FILE_LIMIT = 16 * 1024
# How many tasks one arming waits for at most, and how many cut-offs one task is followed through (follow.STEPS).
MOST = 16
STEPS = 12
LOCK_SECONDS = 5.0
# How one task ended, or that it has not.
RUNNING, COMPLETED, FAILED, INTERRUPTED, UNKNOWN = "running", "completed", "failed", "interrupted", "unknown"
ENDS = (RUNNING, COMPLETED, FAILED, INTERRUPTED, UNKNOWN)
_KEYS = {"format", "nonce", "armed_at", "failed", "interrupted", "tasks"}


def path_of(paths) -> Path:
    return Path(paths.advanced_dir) / FILE_NAME


# ------------------------------------------------------------------------------ the list
def valid(document) -> bool:
    """Whether `document` is a list as this writes one: exactly its keys, a power nonce, two booleans, 1 to MOST tasks
    each exactly a conversation id and a turn id, no conversation twice."""
    if not isinstance(document, dict) or set(document) != _KEYS or document["format"] != FORMAT:
        return False
    if not ids.is_power_nonce(document["nonce"]) or type(document["armed_at"]) not in (int, float):
        return False
    if type(document["failed"]) is not bool or type(document["interrupted"]) is not bool:
        return False
    tasks = document["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MOST:
        return False
    for task in tasks:
        if (not isinstance(task, dict) or set(task) != {"thread_id", "turn_id"} or not ids.is_uuid(task["thread_id"])
                or not ids.is_uuid(task["turn_id"])):
            return False
    return len({task["thread_id"] for task in tasks}) == len(tasks)


def read(paths):
    """The list as it may be believed, or None: missing, a link, too large, unreadable or not valid."""
    path = path_of(paths)
    try:
        if config.is_link(path) or config.is_link(path.parent) or path.stat().st_size > FILE_LIMIT:
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None
    return document if valid(document) else None


def write(paths, document) -> bool:
    """`document` written whole under the list's named lock (a temporary file flushed, then moved over it); False where
    it is not valid, the lock was not had, or Windows refused - with nothing left behind."""
    from codex_auto_resume.windows import Mutex
    if not valid(document):
        return False
    path = path_of(paths)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if config.is_link(path.parent):
            return False
        lock = Mutex(str(path), timeout=LOCK_SECONDS)
        lock.__enter__()
    except Exception:
        return False
    try:
        descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix="power-tasks.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            return True
        except (OSError, ValueError, TypeError):
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return False
    except OSError:
        return False
    finally:
        lock.__exit__(None, None, None)


def remove(paths) -> None:
    """The list gone, where it is (an arming spent or turned off). Never raises."""
    try:
        path = path_of(paths)
        if not config.is_link(path):
            path.unlink()
    except OSError:
        pass


# ------------------------------------------------------------------------------ one task's end
def _cut_off(records, turn_id, parent):
    """Core's interruption of `turn_id` - or, failing that, the one whose parent is `parent` - the earliest detected
    (control/follow.py's rule)."""
    found = [record for record in records if record.get("turn_id") == turn_id]
    if not found and parent is not None:
        found = [record for record in records if record.get("parent_interruption_id") == parent]
    found.sort(key=lambda record: (record.get("detected_at") or 0, record.get("interruption_id") or ""))
    return found[0] if found else None


def _status_end(status) -> str:
    return {"inProgress": RUNNING, "completed": COMPLETED, "failed": FAILED,
            "interrupted": INTERRUPTED}.get(status, UNKNOWN)


def end_of(task, records, status_of) -> str:
    """How the task `task` stands (ENDS): `records` core's interruptions of its conversation, `status_of(thread, turn)`
    a turn's status (None for no such turn; raising for unreadable). Pure but for `status_of`."""
    thread, turn, parent, seen = task["thread_id"], task["turn_id"], None, set()
    try:
        for _ in range(STEPS):
            record = _cut_off(records, turn, parent)
            if record is None:
                return _status_end(status_of(thread, turn))
            key = record.get("interruption_id")
            if key in seen:
                return UNKNOWN
            seen.add(key)
            state = record.get("state")
            if state in machine.WAITING or state not in machine.TERMINAL:
                return RUNNING                       # waiting for its recovery, or on its way
            if state in ("recovered", "resumed"):
                following = record.get("recovery_turn_id")
                if not ids.is_uuid(following):
                    return RUNNING
                turn, parent = following, key
                continue
            return INTERRUPTED if status_of(thread, turn) == "interrupted" else FAILED
    except Exception:
        return UNKNOWN
    return UNKNOWN


def judge(ends, failed=False, interrupted=False) -> str:
    """The one word for every task's end: UNKNOWN if any cannot be read, RUNNING while any runs, MET when each ended in
    an ending counted - completed always, failed and interrupted where the person chose - else NOT_MET."""
    ends = list(ends)
    if not ends or any(end not in ENDS or end == UNKNOWN for end in ends):
        return PowerTasks.UNKNOWN.value
    if RUNNING in ends:
        return PowerTasks.RUNNING.value
    counted = {COMPLETED} | ({FAILED} if failed else set()) | ({INTERRUPTED} if interrupted else set())
    return PowerTasks.MET.value if all(end in counted for end in ends) else PowerTasks.NOT_MET.value


# ------------------------------------------------------------------------------ the capability's code
def core_records(paths) -> list:
    """Core's interruptions, every one, read as follow.py reads them; [] where core's state is not there yet. Raises
    where it cannot be read."""
    from codex_auto_resume.store import Store
    if not (Path(paths.state_dir) / "state.sqlite").is_file():
        return []
    with Store(paths.state_dir) as store:
        return list(store.all_records())


class PowerAfterTasks:
    """power_after_tasks' code: its answer at P21. `records` and `turns` are seams a test fills: core's interruptions
    (`core_records`), and Codex's turn history (codex/turns.Turns of the home the watcher drives)."""

    def __init__(self, paths, *, records=None, turns=None):
        self.paths = paths
        self._records = records or (lambda: core_records(paths))
        self._turns = turns

    def turns(self):
        if self._turns is not None:
            return self._turns
        from ..codex import inuse
        from ..codex.turns import Turns
        return Turns(inuse.home(self.paths))

    def stand(self, document):
        """[(task, its end)] for the list `document`, every task UNKNOWN where core's records cannot be read."""
        try:
            records = self._records()
        except Exception:
            return [(task, UNKNOWN) for task in document["tasks"]]
        turns = self.turns()
        found = []
        for task in document["tasks"]:
            own = [record for record in records if record.get("thread_id") == task["thread_id"]]
            found.append((task, end_of(task, own, turns.status)))
        return found

    def power(self, facts):
        """P21: {"tasks": PowerTasks word, "threads": the list's conversations}. A list missing, not valid, or for
        another arming's nonce answers UNKNOWN with no conversation: core waits."""
        nonce = facts.get("nonce") if isinstance(facts, dict) else None
        document = read(self.paths)
        if document is None or not ids.is_power_nonce(nonce) or document["nonce"] != nonce:
            return {"tasks": PowerTasks.UNKNOWN.value, "threads": []}
        ends = [end for _task, end in self.stand(document)]
        return {"tasks": judge(ends, document["failed"], document["interrupted"]),
                "threads": [task["thread_id"] for task in document["tasks"]]}


def make(paths) -> PowerAfterTasks:
    return PowerAfterTasks(paths)

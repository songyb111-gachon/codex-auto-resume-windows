"""Two guards a waiting recovery may be held by (v0.6.11): its task changed, or its conversation grew costly.

The task-changed guard. When an interruption is detected, a digest of what its task was working with
is kept on the record: the branch or commit its folder's `.git/HEAD` names, read as a file and never by
starting git (standard F6), and the model and approval mode Codex records for the conversation, from
their own columns. When the recovery falls due - every check passed, where it would otherwise be sent
now - the digest is taken again. If it differs, Hold keeps the record for a person (`workspace_changed`)
and Tell lets it go and says so on the notice of its continuation. A workspace that could be read when
the task stopped and cannot now counts as changed. A hold makes what was found the record's digest, so
Let it continue lets it go and only a further change holds it again. Off by default, and then nothing
is read.

The context-cost guard, only where Codex's threads table has a numeric `tokens_used` column (read the
way every other column is: only if it is there, standard B5), read when an interruption is detected.
Show puts the count on Pending; a limit - a choice, or with Custom... a count of the person's own
(ownvalues.py) - also holds, from the start, a recovery whose conversation has used more
(`context_cost`) - a count grows only with a new turn, and a new turn supersedes the interruption,
so it is judged once and Let it continue lets it go. A conversation whose count cannot
be read is not held for it: where Codex does not keep the count, the guard is left out, as the plan
for it says. Off by default, and then nothing is read.

Only a digest and a count are ever kept (D2), never a path, a branch name or a model's name. Both
guards can only hold a record back or add words to a notice; neither sends, skips a check or makes
anything sooner.
"""
from __future__ import annotations

import hashlib

from . import ownvalues
from .domain import ids
from .domain.vocabulary import ContextGuard, HoldKind, TaskGuard

TASK_GUARDS = tuple(TaskGuard)
CONTEXT_GUARDS = tuple(ContextGuard)
DEFAULT_TASK_GUARD = TaskGuard.OFF.value
DEFAULT_CONTEXT_GUARD = ContextGuard.OFF.value
# A limit is what its word says (`above_250k`), a choice or, with Custom..., a count of the person's own in whole
# thousands from 10,000 to 10,000,000 (ownvalues.py).
OWN = {"context_guard": ownvalues.Own(ownvalues.COUNT, 10_000, 10_000_000, ("k", "m"), prefix="above_",
                                     label="own.hold_above")}
# The holds each guard puts on a record.
TASK_HOLD = HoldKind.WORKSPACE_CHANGED.value
CONTEXT_HOLD = HoldKind.CONTEXT_COST.value
# What a task whose workspace could not be read at all is recorded as: a digest nothing else has,
# so it never matches - a task that could not be read counts as changed.
UNREADABLE = hashlib.sha256(b"codex-auto-resume:task:unreadable").hexdigest()
# The largest count kept, far past any conversation: a number from Codex beyond it is not a count.
MAX_TOKENS = 2 ** 53


def _values(values) -> dict:
    return values if isinstance(values, dict) else {}


def task_mode(values) -> str:
    chosen = _values(values).get("task_changed_guard")
    return chosen if chosen in TASK_GUARDS else DEFAULT_TASK_GUARD


def watches_task(values) -> bool:
    """Whether anything of a task's workspace is read: False at the default."""
    return task_mode(values) != TaskGuard.OFF


def context_mode(values) -> str:
    """off, show, a limit's choice or a limit of the person's own - off for anything the settings would not store."""
    chosen = _values(values).get("context_guard")
    return ownvalues.coerce(chosen, DEFAULT_CONTEXT_GUARD, CONTEXT_GUARDS, OWN["context_guard"])


def counts_tokens(values) -> bool:
    """Whether a conversation's token count is read: False at the default."""
    return context_mode(values) != ContextGuard.OFF


def context_limit(values):
    """The count above which a recovery is held, or None: off, or Show alone."""
    return ownvalues.amount(OWN["context_guard"], context_mode(values))


def fingerprint(model, approval, head) -> str:
    """The digest of what a task was working with. `head` is workspace.head_digest's word; the model
    and the approval mode are Codex's own values or None where it keeps none. Only the digest leaves."""
    parts = []
    for name, value in (("model", model), ("approval", approval), ("head", head)):
        text = value if isinstance(value, str) and "\x00" not in value else ("-" if value is None else "?")
        parts.append(name + "=" + text)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def is_print(value) -> bool:
    """Whether `value` is a task's digest as `task_print` writes one (a SHA-256: domain/ids.py)."""
    return ids.is_digest(value)


def changed(recorded, now) -> bool:
    """Whether a task changed between its detection and now. A record with no digest was detected while
    the guard was off and is not judged. A workspace that could be read then and cannot now has changed;
    one that could not be read then and still cannot shows no change."""
    if recorded is None:
        return False
    return (now if is_print(now) else UNREADABLE) != recorded


def tokens(value):
    """A count as kept: a whole number from 0 up, or None."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TOKENS:
        return None
    return value


def over(values, count) -> bool:
    """Whether a conversation's count is above the limit set. An unknown count is never above it."""
    limit = context_limit(values)
    return limit is not None and tokens(count) is not None and count > limit

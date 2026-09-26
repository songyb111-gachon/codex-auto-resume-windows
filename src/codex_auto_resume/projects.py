"""Which projects may resume without a person, by a key that is only ever a digest.

A project is what Codex files a conversation under: its own project id when the conversation has
one, and otherwise the folder it works in. Neither is kept. A project's key is the SHA-256 of one
of them, tagged with which it was, so the settings file holds 64 hex digits for a project and no
path or name; the one place a folder is read to make one is codex/history.py.

Three policies (the setting `project_policy`): every project - the default, what v0.6.10 did, and
then nothing here is asked and nothing of Codex's is read for it - only the projects set to Always,
and every project but those set to Never. Always and Never are two lists, kept apart and disjoint,
so switching between the two list policies can never make a project somebody said Never to the
only one allowed. A task's row sets a project to either (`rule`); no settings editor lists them.

A decision here can only hold a record back. An interruption of a project the policy does not
allow - or, in either list policy, of one whose project cannot be read - is held for a person
(`notify_only`) when it is detected: never dropped, and never chosen. A project narrows what may be
sent; it never names a conversation (B8), whose identity stays its exact id (A3).
"""
from __future__ import annotations

import hashlib

from .domain import ids
from .domain.vocabulary import HoldKind, ProjectPolicy

POLICIES = tuple(ProjectPolicy)
DEFAULT_POLICY = ProjectPolicy.EVERY.value
# The settings that hold the two lists, each a comma-separated run of keys in order.
ALWAYS, NEVER = "project_keys_always", "project_keys_never"
MAX_KEYS = 50


def normal_folder(cwd):
    """A folder as one project: without Windows' extended-path prefix or a trailing separator, with
    one kind of separator, and in one case, as Windows compares paths. None for no folder."""
    if not isinstance(cwd, str) or any(character in cwd for character in "\r\n\x00"):
        return None
    plain = cwd.strip()
    if plain.startswith("\\\\?\\"):
        plain = plain[4:]
    plain = plain.replace("/", "\\").rstrip("\\")
    return plain.casefold() or None


def key_for(project_id=None, cwd=None):
    """A project's key: the digest of Codex's project id when there is one, else of its folder.
    None when there is neither - a project that cannot be read."""
    if isinstance(project_id, str) and project_id.strip() and "\x00" not in project_id:
        return hashlib.sha256(("project_id:" + project_id.strip()).encode("utf-8")).hexdigest()
    folder = normal_folder(cwd)
    if folder is None:
        return None
    return hashlib.sha256(("cwd:" + folder).encode("utf-8")).hexdigest()


def is_key(value) -> bool:
    return ids.is_digest(value)


def parse_keys(text):
    """The keys one list holds, in order - or None when `text` is not such a list."""
    if not isinstance(text, str):
        return None
    if text == "":
        return ()
    keys = tuple(text.split(","))
    if len(keys) > MAX_KEYS or len(set(keys)) != len(keys) or not all(map(is_key, keys)):
        return None
    return keys


def format_keys(keys) -> str:
    return ",".join(sorted(set(keys)))


def coerce_keys(value, default):
    """The settings coercer of a list: the list as written, when it is one in its one written form."""
    keys = parse_keys(value)
    return value if keys is not None and format_keys(keys) == value else default


def _policy(values) -> str:
    raw = values.get("project_policy") if isinstance(values, dict) else None
    return raw if raw in POLICIES else DEFAULT_POLICY


def asks(values) -> bool:
    """Whether the policy asks anything at all: False at the default, where every project resumes."""
    return _policy(values) != DEFAULT_POLICY


def _keys(values, name) -> tuple:
    if not isinstance(values, dict):
        return ()
    return parse_keys(values.get(name)) or ()


def allows(values, key) -> bool:
    """Whether a project, by its key (None: it could not be read), may resume without a person."""
    policy = _policy(values)
    if policy == ProjectPolicy.EVERY:
        return True
    if key is None:
        return False
    if policy == ProjectPolicy.ONLY_LISTED:
        return key in _keys(values, ALWAYS)
    return key not in _keys(values, NEVER)


def hold_for(values, key):
    """The hold a project puts on an interruption detected in it: none, or a person's (notify_only)."""
    return None if allows(values, key) else HoldKind.NOTIFY_ONLY.value


def rule(values, key, always: bool) -> dict:
    """The settings a task row's Always (or Never) for this project writes: the key into one list and
    out of the other. Never, under the default policy, also turns the policy to every project but those
    set to Never - otherwise the click would change nothing. Always never widens the policy: under
    only-listed it adds the project, and under the others it changes nothing a person can see.
    Raises ValueError for a key that is not one, and for a list already at MAX_KEYS."""
    if not is_key(key):
        raise ValueError("not a project key")
    always_keys, never_keys = set(_keys(values, ALWAYS)), set(_keys(values, NEVER))
    (always_keys if always else never_keys).add(key)
    (never_keys if always else always_keys).discard(key)
    if len(always_keys) > MAX_KEYS or len(never_keys) > MAX_KEYS:
        raise ValueError("too many projects")
    changes = {ALWAYS: format_keys(always_keys), NEVER: format_keys(never_keys)}
    if not always and _policy(values) == ProjectPolicy.EVERY:
        changes["project_policy"] = ProjectPolicy.EXCEPT_LISTED.value
    return changes

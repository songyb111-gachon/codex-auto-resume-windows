# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the loopback API may read and do, through core's control layer - and its Dashboard card's bridge commands
(v0.6.22, plans/v0619-design/D-remote.md). No network here: the courier serves (courier/api.py) in its own process, and
comes here for every answer.

What it reads is the standard status file's document (core's statusfile.content - its closed keys, nothing more) and
the waiting recoveries as `task N` - each one's 1-based place in Pending as core lists it (store.pending, oldest
first: the place a push names, core's notifier.told), its public state code and when it is next looked at. Never an
id, a label, a title, a path or a word of a conversation. A listing carries a `snapshot`: a digest of the ids it
listed, in their order, so a later `task N` is resolved against exactly that list or refused (Stale: "list again").

What it may do is the reduce-actions alone, each core's own control call, as the Dashboard's bridge makes it: pause
(Control.set_enabled(False)) and cancel one waiting recovery (Control.cancel_interruption). Core's journal names the
actor `cli` (core has no word for a remote surface; the owner may add one); the advanced journal counts each under the
capability that allowed it, with no id. Nothing here sends: the watcher alone does (a test reads the imports and every
name called).

The bridge commands, the Dashboard's alone and never an MCP tool's:

* advanced-api - the card read: the port, the address without its token, whether a token is kept, whether the
  resident answers (running / stopped / starting / port_taken / off) and whether it is open to the network; with
  {"copy": true}, the address carrying the token in its fragment too, for Copy address - that answer alone;
* advanced-api-token-new - a new token kept in Windows Credential Manager (local_api/token), the old one useless at once;
  the address with the token in its fragment is answered this once, for the same Copy.
"""
from __future__ import annotations

import hashlib
import re
import secrets as random

from ..vocabulary import ArmingState, OptionKey, Refusal

API = "local_api"
API_ACTIONS = "local_api_actions"
API_LAN = "local_api_lan"
TOKEN = "token"                                 # local_api's one secret: CodexAutoResume/advanced/local_api/token
ACTOR = "cli"                                   # core's journal: the nearest word core has for a surface beside it
ALIAS = re.compile(r"task ([1-9][0-9]{0,3})\Z")
SNAPSHOT = re.compile(r"[0-9a-f]{16}\Z")


class Stale(Exception):
    """A `task N` that is not on the list the snapshot names - the list changed since it was read, or never had it."""


# ------------------------------------------------------------------------------ what is read
def control(paths):
    """Core's control layer for this home: the one way in, as the Dashboard's bridge has it."""
    from codex_auto_resume.control import Control
    return Control(paths)


def pending_rows(layer) -> list:
    """The waiting recoveries as core lists them (store.pending, oldest first)."""
    with layer._open(legacy_ok=True) as store:
        return list(store.pending())


def snapshot(rows) -> str:
    """A digest of the ids `rows` holds, in their order: what a later `task N` is resolved against."""
    joined = "\n".join(str(row.get("interruption_id")) for row in rows)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def listing(rows) -> list:
    """`rows` as the API lists them: `task N`, the public state code and the next check - nothing else."""
    from codex_auto_resume import machine
    listed = []
    for place, row in enumerate(rows, start=1):
        due = machine.eligible_at(row)
        listed.append({"task": "task %d" % place, "state": machine.public_code(row),
                       "next_check_at": float(due) if isinstance(due, (int, float)) and not isinstance(due, bool)
                       else None})
    return listed


def pending(layer) -> dict:
    """{"snapshot", "pending"} of the waiting recoveries."""
    rows = pending_rows(layer)
    return {"snapshot": snapshot(rows), "pending": listing(rows)}


def status_document(layer, now) -> dict:
    """The status file's document (core's statusfile.content: its closed keys) as it stands now."""
    from codex_auto_resume import config, managed, settings, statusfile
    values = managed.clamp(settings.load(layer.settings_path()), layer.managed())
    with layer._open(legacy_ok=True) as store:
        stored = store.settings()
        heartbeat = store.watcher_status() or {}
        rows = list(store.pending())
    return statusfile.content(
        now=now, version=config.version(), running=layer.watcher_running() is True,
        enabled=bool(stored["enabled"]) and not layer.managed().disable_auto_resume,
        observe_only=bool(stored.get("observe_only") or values.get("observe_only")),
        engine=heartbeat.get("engine_state") or "unknown", rows=rows, reading=heartbeat.get("usage"))


METRICS = (("codex_auto_resume_watcher_running", "Whether the watcher runs (1) or not (0)."),
           ("codex_auto_resume_recovery_on", "Whether recovery is on (1), or paused or only watching (0)."),
           ("codex_auto_resume_pending", "How many recoveries are pending."),
           ("codex_auto_resume_pending_state", "How many pending recoveries are at each public state code."),
           ("codex_auto_resume_next_check_seconds", "When a waiting recovery is next looked at, seconds since 1970."),
           ("codex_auto_resume_written_seconds", "When this was read, seconds since 1970."))


def metrics(document) -> str:
    """The status document as Prometheus' text format: the same keys, as numbers and closed labels."""
    lines = []
    for name, said in METRICS:
        lines += ["# HELP %s %s" % (name, said), "# TYPE %s gauge" % name]
        if name.endswith("watcher_running"):
            lines.append("%s %d" % (name, document["watcher"] == "running"))
        elif name.endswith("recovery_on"):
            lines.append("%s %d" % (name, document["recovery"] == "on"))
        elif name.endswith("_pending"):
            lines.append("%s %d" % (name, document["pending"]))
        elif name.endswith("pending_state"):
            lines += ['%s{state="%s"} %d' % (name, code, count) for code, count in document["states"].items()]
        elif name.endswith("next_check_seconds"):
            if document["next_check_at"] is not None:
                lines.append("%s %.3f" % (name, document["next_check_at"]))
        else:
            lines.append("%s %.3f" % (name, document["written_at"]))
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------ what is done
def resolve(layer, alias, listed) -> dict:
    """The record `alias` (`task N`) names on the list whose snapshot is `listed` - read again now, and Stale where it
    is not that list any more or has no such place."""
    found = ALIAS.match(alias) if isinstance(alias, str) else None
    if found is None or not isinstance(listed, str) or not SNAPSHOT.match(listed):
        raise Stale()
    rows = pending_rows(layer)
    place = int(found.group(1))
    if snapshot(rows) != listed or place > len(rows):
        raise Stale()
    return rows[place - 1]


def pause(layer) -> dict:
    """Recovery paused, as the Dashboard's pause: core's kill switch, every pending record kept."""
    return {"done": True, "enabled": layer.set_enabled(False)["enabled"]}


def cancel(layer, alias, listed) -> dict:
    """One waiting recovery cancelled by its `task N` on the list `listed`: core's own cancel, by its exact id."""
    record = resolve(layer, alias, listed)
    found = layer.cancel_interruption(record["interruption_id"], actor=ACTOR)
    return {"done": True, "task": alias, "changed": bool(found.get("changed"))}


# ------------------------------------------------------------------------------ the Dashboard's card
def _armed(runtime, capability) -> bool:
    try:
        return runtime.states(fresh=True).get(capability, ArmingState.OFF) == ArmingState.ARMED
    except Exception:
        return False


def _standing(runtime, capability):
    """None where `capability` is on or watched; the refusal otherwise."""
    if runtime.registry.get(capability) is None:
        return Refusal.UNKNOWN_CAPABILITY
    try:
        state = runtime.states(fresh=True).get(capability, ArmingState.OFF)
    except Exception:
        return Refusal.STATE_UNAVAILABLE
    return None if state in (ArmingState.ARMED, ArmingState.SHADOW) else Refusal.NOT_ON


def _secrets(runtime, secrets):
    if secrets is not None:
        return secrets
    from ..credentials import Secrets
    return Secrets(runtime.registry)


def port(runtime) -> int:
    from ..engine.remote import DEFAULT_PORT
    try:
        value = runtime.state.options(API).get(OptionKey.API_PORT, DEFAULT_PORT)
    except Exception:
        return DEFAULT_PORT
    return value if type(value) is int else DEFAULT_PORT


def _running(runtime) -> bool:
    from ..courier.resident import running
    try:
        return bool(running(runtime.paths))
    except Exception:
        return False


def _word(runtime, on, alive) -> str:
    """How the resident stands, for the card: off, or running (its port taken by another program, if that is the last
    thing it found), or stopped - given up on for this hour - or starting."""
    from ..engine import remote
    if not on:
        return "off"
    state, now = runtime.state, runtime.clock()
    if alive:
        taken = state.journal_times(API, "port_taken", now - remote.HOUR)
        served = state.journal_times(API, "started", now - remote.HOUR)
        return "port_taken" if taken and (not served or taken[-1] >= served[-1]) else "running"
    return "stopped" if remote.stopped(state.journal_times, now) else "starting"


def api_view(runtime, *, copy=False, secrets=None, running=None) -> dict:
    """advanced-api: what the card shows - and, only with `copy`, the address carrying the token."""
    from ..courier.address import web_view
    from ..credentials import SecretError
    if runtime.registry.get(API) is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    on = _armed(runtime, API)
    try:
        token = _secrets(runtime, secrets).read(API, TOKEN)
    except SecretError:
        token = None
    alive = (running or _running)(runtime) if on else False
    chosen = port(runtime)
    found = {"done": True, "refusal": None, "port": chosen, "url": web_view(chosen),
             "token_saved": isinstance(token, str) and bool(token), "state": _word(runtime, on, alive),
             "lan": on and _armed(runtime, API_LAN), "actions": on and _armed(runtime, API_ACTIONS)}
    if copy is True and found["token_saved"] and _standing(runtime, API) is None:
        found["copy_url"] = web_view(chosen, token)
    return found


def api_token_new(runtime, *, secrets=None) -> dict:
    """advanced-api-token-new: a new token kept, the old one gone; the address carrying it answered this once."""
    from ..courier.address import web_view
    from ..credentials import SecretError
    refusal = _standing(runtime, API)
    if refusal is not None:
        return {"done": False, "refusal": refusal}
    token = random.token_urlsafe(32)
    try:
        _secrets(runtime, secrets).write(API, TOKEN, token)
    except SecretError:
        return {"done": False, "refusal": Refusal.SECRET_UNAVAILABLE}
    return {"done": True, "refusal": None, "copy_url": web_view(port(runtime), token)}

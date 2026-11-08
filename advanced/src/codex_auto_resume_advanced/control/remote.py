# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What the loopback API and Telegram may read and do, through core's control layer - and their Dashboard cards' bridge
commands (v0.6.22, plans/v0619-design/D-remote.md). No network here: the courier serves (courier/api.py) and polls
(courier/telegram.py) in its own process, and both come here for every answer.

What it reads is the standard status file's document (core's statusfile.content - its closed keys, nothing more) and
the waiting recoveries as `task N` - each one's 1-based place in Pending as core lists it (store.pending, oldest
first: the place a push names, core's notifier.told), its public state code and when it is next looked at. Never an
id, a label, a title, a path or a word of a conversation. A listing carries a `snapshot`: a digest of the ids it
listed, in their order, so a later `task N` is resolved against exactly that list or refused (Stale: "list again").

What it may do is the reduce-actions alone, each core's own control call, as the Dashboard's bridge makes it: pause
(Control.set_enabled(False)) and cancel one waiting recovery (Control.cancel_interruption) - and, under
telegram_continue, the person's own release of one held recovery (Control.release_hold) and the pause lifted
(Control.set_enabled(True)). Core's journal names the actor `cli` (core has no word for a remote surface; the owner may add one); the advanced journal counts each under the
capability that allowed it, with no id. Nothing here sends: the watcher alone does (a test reads the imports and every
name called).

The bridge commands, the Dashboard's alone and never an MCP tool's:

* advanced-api - the card read: the port, the address without its token, whether a token is kept, how the server
  stands (running / starting / port_taken / stopped / no_watcher / off) and whether it is open to the network - and then
  this PC's addresses on it (`lan_urls`); with {"copy": true}, the address carrying the token in its fragment too, for
  Copy address - on 127.0.0.1, or with {"host": ...} on one of this PC's own addresses the card listed - and with
  {"copy_token": true} the token alone, for Copy token. Either only while the server runs: the resident stamped that it
  bound its port (courier/resident.py) - never while it starts, never while another program holds the port, however
  long ago that was found (the reachability audit's R1, M1, M2);
* advanced-api-token-new - a new token kept in Windows Credential Manager (local_api/token), the old one useless at once;
  the address with the token in its fragment is answered this once, for the same Copy - and, as Copy, only while the
  server runs;
* advanced-remote-pair-start - Telegram's pairing begun, the same pairing as the notices card's (control/courier.py):
  the one-time code answered for the card to show;
* advanced-remote-pair-state - whether a chat is paired, a pairing waits, and the bot's token is saved, and how the
  resident stands.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets as random

from ..vocabulary import ArmingState, OptionKey, Refusal

API = "local_api"
API_ACTIONS = "local_api_actions"
API_LAN = "local_api_lan"
TELEGRAM = "telegram_remote"
TELEGRAM_CONTINUE = "telegram_continue"
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


def release(layer, alias, listed) -> dict:
    """One recovery held for a person let go on by its `task N` (telegram_continue): core's release_hold, which sends
    nothing and skips no gate."""
    record = resolve(layer, alias, listed)
    layer.release_hold(record["interruption_id"], record["thread_id"], actor=ACTOR)
    return {"done": True, "task": alias}


def lift_pause(layer) -> dict:
    """The pause lifted (telegram_continue): core's set_enabled(True), which an administrator's policy still refuses."""
    return {"done": True, "enabled": layer.set_enabled(True)["enabled"]}


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


def _watcher(runtime) -> bool:
    """Whether the watcher runs, as core's control layer probes it: the resident is started only by the watcher."""
    try:
        return control(runtime.paths).watcher_running() is True
    except Exception:
        return False


def _began(runtime) -> int:
    """When the newest resident was started (engine/remote.py's START_WORD, by either capability), in whole seconds; 0
    where none is journalled."""
    from ..engine import remote
    try:
        found = [at for capability in remote.RESIDENT
                 for at in runtime.state.journal_times(capability, remote.START_WORD, 0)]
    except Exception:
        return 0
    return int(max(found)) if found else 0


def _down(runtime, alive, watcher) -> str | None:
    """Why the resident is not up, for either card - stopped (given up on for this hour), no_watcher (it starts with the
    watcher, which is not running) or starting - or None while it is up."""
    from ..engine import remote
    if alive:
        return None
    if remote.stopped(runtime.state.journal_times, runtime.clock()):
        return "stopped"
    return "starting" if (watcher or _watcher)(runtime) else "no_watcher"


def _word(runtime, on, alive, watcher=None) -> str:
    """How the server stands, for the card: off; running only where the resident stamped that its server bound the port
    (courier/resident.py) since the newest resident was started; port_taken where it found another program on the port
    instead; starting while it has done neither - and, while the resident is not up, stopped, no_watcher or starting."""
    from ..courier.resident import BOUND, TAKEN
    if not on:
        return "off"
    down = _down(runtime, alive, watcher)
    if down is not None:
        return down
    began = _began(runtime)
    try:
        bound, taken = runtime.state.stamped(API, BOUND), runtime.state.stamped(API, TAKEN)
    except Exception:
        return "starting"
    if bound is not None and bound >= began and (taken is None or bound >= taken):
        return "running"
    return "port_taken" if taken is not None and taken >= began else "starting"


def lan_addresses() -> list:
    """This PC's own IPv4 addresses on its networks, as Windows resolves its own name - no request leaves the PC -
    loopback, link-local, multicast and unspecified ones left out, at most four, in the order Windows gives them."""
    import socket
    found = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except (OSError, UnicodeError):
        return []
    for info in infos:
        try:
            address = ipaddress.IPv4Address(info[4][0])
        except (ValueError, IndexError, TypeError):
            continue
        if address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            continue
        if str(address) not in found:
            found.append(str(address))
    return found[:4]


def api_view(runtime, *, copy=False, host=None, copy_token=False, secrets=None, running=None, watcher=None,
             addresses=None) -> dict:
    """advanced-api: what the card shows - and, only with `copy`, the address carrying the token (on `host` where it is
    one of this PC's own addresses), or with `copy_token` the token alone. `running`, `watcher` and `addresses` are the
    seams a test fills: whether the resident answers its mutex, whether the watcher runs, and this PC's addresses."""
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
    lan = on and _armed(runtime, API_LAN)
    found = {"done": True, "refusal": None, "port": chosen, "url": web_view(chosen),
             "token_saved": isinstance(token, str) and bool(token), "state": _word(runtime, on, alive, watcher),
             "lan": lan, "actions": on and _armed(runtime, API_ACTIONS)}
    own = (addresses or lan_addresses)() if lan else []
    if lan:
        found["lan_urls"] = [web_view(chosen, host=address) for address in own]
    # Only while the server runs - bound by the resident; not while it starts, nor on a port another program was found
    # on, however long ago: opened, the address would hand the token in its fragment to that program's page (R7, the
    # security review of 2026-11-06; R1 and M1 of the reachability audit).
    if found["token_saved"] and found["state"] == "running" and _standing(runtime, API) is None:
        if copy is True and (host is None or host in own):
            found["copy_url"] = web_view(chosen, token, host=host)
        if copy_token is True:
            found["copy_token"] = token
    return found


def api_token_new(runtime, *, secrets=None, running=None, watcher=None) -> dict:
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
    made = {"done": True, "refusal": None}
    # As Copy address: the address carrying it only while the server runs (R1).
    on = _armed(runtime, API)
    if _word(runtime, on, on and (running or _running)(runtime), watcher) == "running":
        made["copy_url"] = web_view(port(runtime), token)
    return made


def pair_state(runtime, *, secrets=None, running=None, watcher=None) -> dict:
    """advanced-remote-pair-state: the shared Telegram pairing (push_notices'), as the remote card shows it - and what the
    resident's long poll does (courier/telegram.py, `once`): with no bot token or no chat paired it reads nothing
    (no_token, no_chat), during a pairing it leaves the bot to the pairing (pairing), and only otherwise reads it
    (running) - the reachability audit's M7. `chat` is the paired chat's name as Telegram gave it, where one was kept."""
    from ..courier import keep
    if runtime.registry.get(TELEGRAM) is None or runtime.registry.get(keep.CAPABILITY) is None:
        return {"done": False, "refusal": Refusal.UNKNOWN_CAPABILITY}
    secrets = _secrets(runtime, secrets) if secrets is not None else keep.secrets_of(runtime.registry)
    try:
        row = keep.pairing(runtime.state) or {}
    except Exception:
        return {"done": False, "refusal": Refusal.STATE_UNAVAILABLE}
    now = runtime.clock()
    on = _armed(runtime, TELEGRAM)
    alive = (running or _running)(runtime) if on else False
    paired, token_saved = keep.saved(secrets, "telegram"), _saved_token(secrets)
    pairing = bool(row.get("code_digest") and (row.get("code_expires_at") or 0) > now)
    word = "off" if not on else _down(runtime, alive, watcher)
    if word is None:
        word = ("no_token" if not token_saved else "pairing" if pairing else "no_chat" if not paired else "running")
    found = {"done": True, "refusal": None, "paired": paired, "token_saved": token_saved, "pairing": pairing,
             "state": word, "continue": _armed(runtime, TELEGRAM_CONTINUE)}
    if paired:
        found["chat"] = _chat_name(secrets)
    return found


def _saved_token(secrets) -> bool:
    from ..courier.keep import read
    try:
        return read(secrets, "telegram_token") is not None
    except Exception:
        return False


def _chat_name(secrets):
    """The paired chat's title or @username as Telegram gave it (courier/keep.chat_name), or None."""
    from ..courier.keep import chat_name
    try:
        return chat_name(secrets)
    except Exception:
        return None


def pair_start(runtime, *, secrets=None, start=None) -> dict:
    """advanced-remote-pair-start: the notices card's pairing begun from the remote card - telegram_remote and
    push_notices each on or watched. The one-time code answered for the card; only its digest kept (control/courier.py)."""
    from ..control import courier
    from ..courier import keep
    for capability in (TELEGRAM, keep.CAPABILITY):
        refusal = _standing(runtime, capability)
        if refusal is not None:
            return {"done": False, "refusal": refusal}
    return courier._pair(runtime, secrets if secrets is not None else keep.secrets_of(runtime.registry), start)

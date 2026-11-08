# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's saved accounts (account_auto_switch, v0.6.22): the bridge's five commands, the Dashboard's alone.

`advanced-accounts` reads the saved accounts as a person may see them - {id, mask, plan, state} each, the address only
masked (profiles.Profiles.view) - with whether Codex keeps its sign-in in a file here (codex/authfile.usable's word),
whether an Add an account is under way or how the last one ended (`add_state`), and when the account was last switched. Nothing of a
saved account's address or sign-in file leaves this module.

`advanced-accounts-add` is Add an account: Codex's own `codex login` on a scratch home (codex/swap.add_by_login), on a
thread of this process's own, one at a time per installation (SWITCH_RUNNING while one waits); the card then reads
`add_state` - WAITING, then ADDED or NOT_ADDED, each said once: the read that answers it forgets it (the reachability
audit's M9 - "The account was saved." stayed until the bridge restarted). `advanced-accounts-save` is Save the account in use (codex/swap.save_current).
`advanced-accounts-delete` takes {"id": <a profile's id>} or {"all": true} and deletes the files.

The usage meters (v0.6.22 final): each row of `advanced-accounts` carries its account's five-hour and weekly windows -
used percentage and reset time - with when they were read (`read_at`) and whether a later read broke (`unread`). A saved
account's come from the last read of it, the switch's own at a limit or Read usage's (profiles' `usage`); the account
in use (`in_use`: the one this product last found signed in, profiles' `seen_at`) takes the watcher's own last reading
instead (core's watcher_status), never a read of its own. `candidate` is the masked address the switch would pick now by
its own rule (engine/autoswitch.best) from the readings kept (`candidate_id` its row), `candidate_state` "found", "none_has_room" or None where no
other account has a reading. `advanced-accounts-read` is Read usage: every saved account but the one in use read on a
scratch home, one at a time, on a thread of this process's own (swap.read_profile, the switch's own read, which MPROFILE
measured to touch nothing real) - at most once every READ_EVERY seconds (`read_next_at`), the card following `read_state`
(READING with read_done of read_of, then READ, HELD where a switch began meanwhile, or UNKNOWN where who is signed in
could not be read, when nothing is read). It sends nothing to Codex's conversations and switches nothing.

Adding and saving are refused NOT_ON unless the capability is on or watched - and so while it waits hidden in
registry.WAITING, when no runtime has it at all. Reading the card and deleting answer in every state - on, watched, off
and hidden - so a saved sign-in can always be taken off this PC (the security review's finding 3); `offered` says
whether the capability is in this runtime at all, so the window shows the card under account_switch's while it is
hidden and copies are kept. Adding and saving keep a person's own accounts; nothing here switches one.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from ..vocabulary import Refusal
from .resets import _refused, _standing

CAPABILITY = "account_auto_switch"
WAITING, ADDED, NOT_ADDED = "waiting", "added", "not_added"
# Read usage's states, and how often it may begin: once every ten minutes (the owner's mock, 2026-11-08).
READING, READ, HELD, UNKNOWN = "reading", "read", "held", "unknown"
READ_EVERY = 600
_ADDING = {}
_READING = {}
_LOCK = threading.Lock()


def _saved(runtime):
    from ..profiles import Profiles
    return Profiles(runtime.paths.home)


def _codex_home(runtime):
    from ..codex import inuse
    return inuse.home(runtime.paths)


def _sweep(store, codex_home=None) -> None:
    """What a kill left in plain text in the saved accounts folder (and beside `codex_home`'s sign-in file, where given)
    swept with the normal stale ages - only if nothing holds the saved accounts now (never beside a switch, never
    waiting); a held lock or a failure changes nothing (the review's finding 16)."""
    from ..codex import authfile
    try:
        with store.locked(0):
            authfile.sweep(store.directory, codex_home)
    except Exception:
        pass


def view(runtime, *, store=None, codex_home=None, usage=None, now=None) -> dict:
    """advanced-accounts, in every state; see the module. `store`, `codex_home`, `usage` (the watcher's reading) and `now`
    are a test's. While the capability is not on or watched it touches nothing of Codex's home - `store` is None - and
    sweeps only the saved accounts folder."""
    from ..codex import authfile
    from ..vocabulary import OptionKey
    store = store or _saved(runtime)
    standing = _standing(runtime, CAPABILITY)
    word = None
    if standing:
        try:
            word = authfile.usable(codex_home if codex_home is not None else _codex_home(runtime))
        except Exception:
            word = authfile.UNREADABLE
    _sweep(store)
    try:
        switched = runtime.state.stamped(CAPABILITY, OptionKey.AUTO_SWITCHED_AT)
    except Exception:
        switched = None
    with _LOCK:
        add_state = _ADDING.get(Path(runtime.paths.home))
        if add_state in (ADDED, NOT_ADDED):
            _ADDING.pop(Path(runtime.paths.home), None)  # said once, as the card's other done-lines are
        reading = dict(_READING.get(Path(runtime.paths.home)) or {})
    try:
        offered = runtime.registry.get(CAPABILITY) is not None
    except Exception:
        offered = False
    answer = {"done": True, "refusal": None, "store": word, "add_state": add_state, "switched_at": switched,
              "offered": offered, "standing": standing}
    answer.update(meters(runtime, store, reading, now if now is not None else time.time(), usage=usage))
    return answer


def _watcher_usage(runtime):
    """The watcher's own last usage reading of the account signed in ({read_at, windows}, core's watcher_status), or
    None."""
    from codex_auto_resume.store import Store
    try:
        with Store(runtime.paths.state_dir) as store:
            return (store.watcher_status() or {}).get("usage")
    except Exception:
        return None


def meters(runtime, store, reading, now, *, usage=None) -> dict:
    """The card's rows with their meters, the next candidate and Read usage's state; see the module. `usage` is a test's
    stand-in for the watcher's reading."""
    from ..codex.swap import meters as windows_of
    from ..engine.autoswitch import best
    from ..profiles import READY
    rows = store.view()
    seen = [row for row in rows if type(row.get("seen_at")) is int]
    in_use = max(seen, key=lambda row: row["seen_at"])["id"] if seen else None
    live = usage if usage is not None else _watcher_usage(runtime)
    failed = set(reading.get("failed") or ())
    shown, candidates, read_at = [], [], []
    for row in rows:
        kept = row.get("usage")
        entry = {"id": row["id"], "mask": row["mask"], "plan": row["plan"], "state": row["state"],
                 "in_use": row["id"] == in_use, "five_hour": None, "weekly": None, "read_at": None,
                 "unread": bool(row.get("unread")) or row["id"] in failed}
        if row["id"] == in_use:
            entry["unread"] = False
            if isinstance(live, dict) and isinstance(live.get("read_at"), (int, float)):
                entry.update(windows_of(live.get("windows")), read_at=int(live["read_at"]))
        elif kept is not None:
            entry.update(five_hour=kept["five_hour"], weekly=kept["weekly"], read_at=kept["read_at"])
            read_at.append(kept["read_at"])
            if row["state"] == READY:
                found = {"present": True, "own": True, "available": kept["available"], "most_used": kept["most_used"]}
                candidates.append((row["id"], found, row.get("used_at")))
        shown.append(entry)
    picked = best(candidates)
    masks = {row["id"]: row["mask"] for row in rows}
    last = store.read_now_at()
    following = last + READ_EVERY if last is not None and 0 <= now - last < READ_EVERY else None
    return {"profiles": shown, "read_at": max(read_at) if read_at else None,
            "candidate": masks.get(picked) if picked else None, "candidate_id": picked,
            "candidate_state": "found" if picked else "none_has_room" if read_at else None,
            "read_state": reading.get("state"), "read_done": reading.get("done"), "read_of": reading.get("of"),
            "read_next_at": following}


def read(runtime, *, store=None, start=None, run=None, read_real=None, now=None) -> dict:
    """advanced-accounts-read, Read usage; see the module. `start` (how the thread is started), `run`
    (swap.read_profile's shape) and `read_real` (the account read on the real home) are a test's."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    store = store or _saved(runtime)
    home = Path(runtime.paths.home)
    now = int(now if now is not None else time.time())
    with _LOCK:
        if (_READING.get(home) or {}).get("state") == READING:
            return {"done": True, "refusal": None, "started": False, "read_state": READING}
        last = store.read_now_at()
        if last is not None and 0 <= now - last < READ_EVERY:
            return {"done": True, "refusal": None, "started": False, "read_next_at": last + READ_EVERY}
        try:
            store.note_read_now(now)
        except OSError:
            return _refused(Refusal.STATE_UNAVAILABLE)
        _READING[home] = {"state": READING, "done": 0, "of": None, "failed": []}
    paths = runtime.paths

    def target():
        try:
            ended = read_all(paths, store, home, run=run, read_real=read_real)
        except Exception:
            ended = UNKNOWN
        with _LOCK:
            _READING[home]["state"] = ended
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-read", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _READING[home]["state"] = UNKNOWN
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "started": True, "read_state": READING, "read_next_at": now + READ_EVERY}


def read_all(paths, store, home, *, run=None, read_real=None, clock=time.time) -> str:
    """Read usage's thread: who is signed in told first (the switch's own read on the real home, codex/account.read) and
    that account only marked, never read on a scratch home; then every other saved account that does not need a new
    sign-in read one at a time, each under the saved accounts' lock and only while no switch began since (its intent, or
    a later switch.last): READ, HELD or UNKNOWN. A read that broke is listed in `failed` and keeps its last reading."""
    from ..codex.account import identity
    from ..engine.autoswitch import seen
    from ..profiles import KEEP_SECONDS, Locked, NEEDS_SIGN_IN, ProfileError
    if run is None:
        from ..codex.swap import read_profile as run
    if read_real is None:
        from ..codex.account import read as real

        def read_real():
            return real(paths)
    try:
        current = identity(read_real())
    except Exception:
        current = None
    if current is None:
        return UNKNOWN
    switched = store.last_switch_at()
    targets = []
    for profile_id in store.ids():
        try:
            profile = store.get(profile_id)
        except ProfileError:
            continue
        if (profile.get("email") or "").lower() == current:
            seen(store, profile_id, clock())
        elif store.state(profile) != NEEDS_SIGN_IN:
            targets.append(profile_id)
    with _LOCK:
        _READING[home]["of"] = len(targets)
    for done, profile_id in enumerate(targets, 1):
        broke = True
        try:
            with store.locked(KEEP_SECONDS):
                if store.intent() is not None or store.last_switch_at() != switched:
                    return HELD                          # a switch began: the account in use may have changed
                found = run(paths, store, profile_id, now=int(clock()))
                broke = found.get("present") is None
        except Locked:
            pass
        with _LOCK:
            _READING[home]["done"] = done
            if broke:
                _READING[home]["failed"].append(profile_id)
    return READ


def add(runtime, *, start=None, run=None) -> dict:
    """advanced-accounts-add; see the module. `start` (how the thread is started) and `run` (swap.add_by_login's shape,
    given the paths and the store) are a test's."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    home = Path(runtime.paths.home)
    with _LOCK:
        if _ADDING.get(home) == WAITING:
            return _refused(Refusal.SWITCH_RUNNING)
        _ADDING[home] = WAITING
    paths = runtime.paths
    if run is None:
        from ..codex.swap import add_by_login as run

    def target():
        try:
            added = run(paths, _saved(runtime)) is not None
        except Exception:
            added = False
        with _LOCK:
            _ADDING[home] = ADDED if added else NOT_ADDED
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-add", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _ADDING[home] = NOT_ADDED
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "add_state": WAITING}


def save(runtime, *, store=None, codex_home=None, read_real=None) -> dict:
    """advanced-accounts-save; see the module."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    from ..codex.swap import save_current
    saved = save_current(runtime.paths, store or _saved(runtime),
                         codex_home if codex_home is not None else _codex_home(runtime), read_real=read_real)
    return {"done": True, "refusal": None, "saved": saved is not None}


def delete(runtime, argument, *, store=None, codex_home=None) -> dict:
    """advanced-accounts-delete: {"id": ...} or {"all": true}, in every state; see the module. Delete all sweeps beside
    Codex's sign-in file too (`codex_home`, a test's; else the one in use) - a home that cannot be told stops nothing."""
    from ..profiles import Locked
    store = store or _saved(runtime)
    if codex_home is None and isinstance(argument, dict) and argument.get("all") is True:
        try:
            codex_home = _codex_home(runtime)
        except Exception:
            codex_home = None
    argument = argument if isinstance(argument, dict) else {}
    try:
        with store.locked():
            if argument.get("all") is True:
                return {"done": True, "refusal": None, "deleted": store.delete_all(codex_home)}
            profile_id = argument.get("id")
            if not isinstance(profile_id, str) or profile_id not in store.ids():
                return _refused(Refusal.OPTION_INVALID)
            return {"done": True, "refusal": None, "deleted": int(store.delete(profile_id))}
    except Locked:
        return _refused(Refusal.ACCOUNTS_HELD)            # a switch, a read or a save holds them (the audit's M10)

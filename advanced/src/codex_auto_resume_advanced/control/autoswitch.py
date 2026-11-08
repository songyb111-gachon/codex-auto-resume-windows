# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's saved accounts (account_auto_switch, v0.6.22): the bridge's six commands, the Dashboard's alone.

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

`advanced-accounts-switch` (v0.6.22 final, the owner's 2026-11-08) is Switch to this account: {"id": <a saved account's
row>}, after the window asked first, switches Codex to that account now - the automatic switch's own switch
(engine/autoswitch.AutoSwitch.put_in: the swap, the close and restart, the sign-in check and the undo of a switch that
did not finish), on a thread of this process's own; the card follows `switch_state` (SWITCHING, then the outcome word,
said once as `add_state` is) with `switch_mask`, the account's masked address. It is refused, with nothing changed, for an
account that is not a saved row (OPTION_INVALID), the account in use (ACCOUNT_IN_USE), one that needs a new sign-in or
cannot be opened (ACCOUNT_NOT_READY), a sign-in kept outside a file (SIGN_IN_NOT_FILE), while a turn runs, something is
queued in Codex or a recovery other than a usage-limit wait waits or runs (codex/restart.busy: RESTART_BUSY), while another
Codex engine runs that may use this home (OTHER_ENGINE), while a switch, a put-back or a usage read holds the saved
accounts or one of this card's own runs (ACCOUNTS_HELD), and before the automatic switch is offered at all
(SWITCH_UNMEASURED). The click and the window's question are the person's consent: it needs neither capability on, it is
never counted toward the automatic switch's ceiling, and it is journalled in its own words (MANUAL_SWITCHED,
MANUAL_NOT_FINISHED, MANUAL_NOT_DONE). Nothing switches on its own here.

Since the v0.6.22 final the saved accounts are one store under both account capabilities' cards (the owner, 2026-11-08):
adding, saving and Read usage answer while account_auto_switch or account_switch is on or watched (`_kept_standing`), and
are refused NOT_ON while neither is - and so while account_auto_switch waits hidden in registry.WAITING and account_switch
is off. Reading the card and deleting answer in every state - on, watched, off and hidden - so a saved sign-in can always
be taken off this PC (the security review's finding 3); `offered` says whether account_auto_switch is in this runtime at
all. Adding and saving keep a person's own accounts.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from ..vocabulary import ArmingState, OptionKey, Refusal
from .resets import _refused, _standing

CAPABILITY = "account_auto_switch"
# The capabilities whose cards show the saved accounts: either on or watched lets a person add, save and read them.
STANDING = (CAPABILITY, "account_switch")
WAITING, ADDED, NOT_ADDED = "waiting", "added", "not_added"
# Read usage's states, and how often it may begin: once every ten minutes (the owner's mock, 2026-11-08).
READING, READ, HELD, UNKNOWN = "reading", "read", "held", "unknown"
READ_EVERY = 600
# Switch to this account's state while it runs.
SWITCHING = "switching"
_ADDING = {}
_READING = {}
_SWITCHING = {}
_LOCK = threading.Lock()


def _saved(runtime):
    from ..profiles import Profiles
    return Profiles(runtime.paths.home)


def _codex_home(runtime):
    from ..codex import inuse
    return inuse.home(runtime.paths)


def _kept_standing(runtime) -> bool:
    """Whether either account capability whose card shows the saved accounts is on or watched."""
    return any(_standing(runtime, capability) for capability in STANDING)


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
    standing = _kept_standing(runtime)
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
        switching = dict(_SWITCHING.get(Path(runtime.paths.home)) or {})
        if switching.get("state") not in (None, SWITCHING):
            _SWITCHING.pop(Path(runtime.paths.home), None)   # said once, as Add an account's ending is
    try:
        offered = runtime.registry.get(CAPABILITY) is not None
    except Exception:
        offered = False
    answer = {"done": True, "refusal": None, "store": word, "add_state": add_state, "switched_at": switched,
              "offered": offered, "standing": standing, "switch_state": switching.get("state"),
              "switch_mask": switching.get("mask")}
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
    in_use = _in_use(rows)
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
    if not _kept_standing(runtime):
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
    if not _kept_standing(runtime):
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
    if not _kept_standing(runtime):
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


def _in_use(rows):
    """The row the card says is in use (the one this product last found signed in, profiles' `seen_at`), or None."""
    seen = [row for row in rows if type(row.get("seen_at")) is int]
    return max(seen, key=lambda row: row["seen_at"])["id"] if seen else None


def _manual(runtime, store, codex_home):
    """The automatic switch's own code, on this installation, for a person's switch."""
    from ..engine.autoswitch import AutoSwitch
    return AutoSwitch(runtime.paths, store=store, home=codex_home)


def _other_engine() -> bool:
    """Whether a Codex engine runs that may use this home and is not the app's own (codex/swap.other_engines)."""
    from ..codex import swap
    return swap.other_engines(swap._inventory(), app_open=True)


def _journal(runtime, word) -> None:
    """One line of a person's switch, under the automatic switch - or under account_switch, from whose card it may be
    asked too, where the automatic switch is not in this runtime."""
    for capability in STANDING:
        try:
            if runtime.registry.get(capability) is not None and runtime.state.counted(capability, word):
                return
        except Exception:
            pass


def switch(runtime, argument, *, store=None, codex_home=None, start=None, code=None, engines=None, now=None) -> dict:
    """advanced-accounts-switch, Switch to this account; see the module. `store`, `codex_home`, `start` (how the thread is
    started), `code` (the automatic switch's AutoSwitch, or a stand-in with its `busy` and `put_in`), `engines` (whether
    another Codex engine runs) and `now` are a test's."""
    from ..codex import authfile
    from ..engine import autoswitch as engine
    from ..profiles import DAMAGED, Locked, NEEDS_SIGN_IN
    profile_id = argument.get("id") if isinstance(argument, dict) else None
    if not isinstance(profile_id, str):
        return _refused(Refusal.OPTION_INVALID)
    try:
        offered = runtime.registry.get(CAPABILITY) is not None
    except Exception:
        offered = False
    if not offered:
        return _refused(Refusal.SWITCH_UNMEASURED)       # the switch it would run is not offered on this Codex
    store = store or _saved(runtime)
    rows = store.view()
    row = next((each for each in rows if each["id"] == profile_id), None)
    if row is None:
        return _refused(Refusal.OPTION_INVALID)
    if profile_id == _in_use(rows):
        return _refused(Refusal.ACCOUNT_IN_USE)
    if row["state"] in (NEEDS_SIGN_IN, DAMAGED):
        return _refused(Refusal.ACCOUNT_NOT_READY)
    codex_home = codex_home if codex_home is not None else _codex_home(runtime)
    try:
        usable = authfile.usable(codex_home)
    except Exception:
        usable = authfile.UNREADABLE
    if usable != authfile.USABLE:
        return _refused(Refusal.SIGN_IN_NOT_FILE)        # keyring, auto or ephemeral: nothing can be switched
    code = code or _manual(runtime, store, codex_home)
    if code.busy():
        return _refused(Refusal.RESTART_BUSY)            # a turn runs, something is queued, a recovery is sent
    if (engines or _other_engine)():
        return _refused(Refusal.OTHER_ENGINE)
    home = Path(runtime.paths.home)
    with _LOCK:
        if ((_SWITCHING.get(home) or {}).get("state") == SWITCHING
                or (_READING.get(home) or {}).get("state") == READING or store.intent() is not None):
            return _refused(Refusal.ACCOUNTS_HELD)
        try:
            with store.locked(0):
                pass
        except Locked:
            return _refused(Refusal.ACCOUNTS_HELD)       # another process's switch, put-back, read or save
        _SWITCHING[home] = {"state": SWITCHING, "mask": row["mask"]}

    def target():
        at = int(now if now is not None else time.time())
        try:
            outcome, _closed = code.put_in(profile_id, at, manual=True)
        except Exception:
            outcome = "failed"
        if outcome == "switched":
            word = engine.MANUAL_SWITCHED
            try:
                # The automatic switch's early look at the recoveries waiting for a usage limit follows it, where it is on.
                if runtime.states(fresh=True).get(CAPABILITY) == ArmingState.ARMED:
                    runtime.state.stamp(CAPABILITY, OptionKey.AUTO_SWITCHED_AT, max(1, at))
            except Exception:
                pass
        elif outcome in engine.MANUAL_NOTHING:
            word = engine.MANUAL_NOT_DONE
        else:
            word = engine.MANUAL_NOT_FINISHED
        _journal(runtime, word)
        with _LOCK:
            _SWITCHING[home] = {"state": outcome, "mask": row["mask"]}
    try:
        (start or (lambda job: threading.Thread(target=job, name="account-switch-to", daemon=True).start()))(target)
    except Exception:
        with _LOCK:
            _SWITCHING.pop(home, None)
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None, "switch_state": SWITCHING, "switch_mask": row["mask"]}

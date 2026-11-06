# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's saved accounts (account_auto_switch, v0.6.22): the bridge's four commands, the Dashboard's alone.

`advanced-accounts` reads the saved accounts as a person may see them - {id, mask, plan, state} each, the address only
masked (profiles.Profiles.view) - with whether Codex keeps its sign-in in a file here (codex/authfile.usable's word),
whether an Add an account is under way or how the last one ended (`add_state`), and when the account was last switched. Nothing of a
saved account's address or sign-in file leaves this module.

`advanced-accounts-add` is Add an account: Codex's own `codex login` on a scratch home (codex/swap.add_by_login), on a
thread of this process's own, one at a time per installation (SWITCH_RUNNING while one waits); the card then reads
`add_state` - WAITING, then ADDED or NOT_ADDED. `advanced-accounts-save` is Save the account in use (codex/swap.save_current).
`advanced-accounts-delete` takes {"id": <a profile's id>} or {"all": true} and deletes the files.

Adding and saving are refused NOT_ON unless the capability is on or watched - and so while it waits hidden in
registry.WAITING, when no runtime has it at all. Reading the card and deleting answer in every state - on, watched, off
and hidden - so a saved sign-in can always be taken off this PC (the security review's finding 3); `offered` says
whether the capability is in this runtime at all, so the window shows the card under account_switch's while it is
hidden and copies are kept. Adding and saving keep a person's own accounts; nothing here switches one.
"""
from __future__ import annotations

import threading
from pathlib import Path

from ..vocabulary import Refusal
from .resets import _refused, _standing

CAPABILITY = "account_auto_switch"
WAITING, ADDED, NOT_ADDED = "waiting", "added", "not_added"
_ADDING = {}
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


def view(runtime, *, store=None, codex_home=None) -> dict:
    """advanced-accounts, in every state; see the module. `store` and `codex_home` are a test's. While the capability is
    not on or watched it touches nothing of Codex's home - `store` is None - and sweeps only the saved accounts folder."""
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
    try:
        offered = runtime.registry.get(CAPABILITY) is not None
    except Exception:
        offered = False
    return {"done": True, "refusal": None, "profiles": store.view(), "store": word, "add_state": add_state,
            "switched_at": switched, "offered": offered, "standing": standing}


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
        return _refused(Refusal.SWITCH_RUNNING)

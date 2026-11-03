# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Dashboard's saved accounts (account_auto_switch, v0.6.22): the bridge's four commands, the Dashboard's alone.

`advanced-accounts` reads the saved accounts as a person may see them - {id, mask, plan, state} each, the address only
masked (profiles.Profiles.view) - with whether Codex keeps its sign-in in a file here (codex/authfile.usable's word),
whether an Add an account is under way or how the last one ended, and when the account was last switched. Nothing of a
saved account's address or sign-in file leaves this module.

`advanced-accounts-add` is Add an account: Codex's own `codex login` on a scratch home (codex/swap.add_by_login), on a
thread of this process's own, one at a time per installation (SWITCH_RUNNING while one waits); the card then reads
`adding` - WAITING, then ADDED or NOT_ADDED. `advanced-accounts-save` is Save the account in use (codex/swap.save_current).
`advanced-accounts-delete` takes {"id": <a profile's id>} or {"all": true} and deletes the files.

Each is refused NOT_ON unless the capability is on or watched - and so while it waits hidden in registry.WAITING, when
no runtime has it at all. Adding and saving keep a person's own accounts; nothing here switches one.
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


def view(runtime, *, store=None, codex_home=None) -> dict:
    """advanced-accounts; see the module. `store` and `codex_home` are a test's."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    from ..codex import authfile
    from ..vocabulary import OptionKey
    store = store or _saved(runtime)
    try:
        word = authfile.usable(codex_home if codex_home is not None else _codex_home(runtime))
    except Exception:
        word = authfile.UNREADABLE
    try:
        switched = runtime.state.stamped(CAPABILITY, OptionKey.AUTO_SWITCHED_AT)
    except Exception:
        switched = None
    with _LOCK:
        adding = _ADDING.get(Path(runtime.paths.home))
    return {"done": True, "refusal": None, "profiles": store.view(), "store": word, "adding": adding,
            "switched_at": switched}


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
    return {"done": True, "refusal": None, "adding": WAITING}


def save(runtime, *, store=None, codex_home=None, read_real=None) -> dict:
    """advanced-accounts-save; see the module."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    from ..codex.swap import save_current
    saved = save_current(runtime.paths, store or _saved(runtime),
                         codex_home if codex_home is not None else _codex_home(runtime), read_real=read_real)
    return {"done": True, "refusal": None, "saved": saved is not None}


def delete(runtime, argument, *, store=None) -> dict:
    """advanced-accounts-delete: {"id": ...} or {"all": true}; see the module."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    store = store or _saved(runtime)
    argument = argument if isinstance(argument, dict) else {}
    if argument.get("all") is True:
        return {"done": True, "refusal": None, "deleted": store.delete_all()}
    profile_id = argument.get("id")
    if not isinstance(profile_id, str) or profile_id not in store.ids():
        return _refused(Refusal.OPTION_INVALID)
    return {"done": True, "refusal": None, "deleted": int(store.delete(profile_id))}

"""Opening the state for one command: one set of steps, and the policy each caller chooses.

Every per-call opener - the command line, the control layer behind the window, the panel and
the MCP server, and the App's own commands - opens the state the same way. A current state
opens as it is. An older one is upgraded, but only while this process holds the watcher's
single-instance mutex, which proves no watcher is running: an older watcher would otherwise
be writing rows the upgrade is changing. If a watcher does hold it, it can only be an older
one (a current watcher upgrades at start), and what happens then is a policy, which each
caller states:

    never        upgrade pending, whatever the command (the App's commands);
    if_reducing  the older watcher's own store for an action that only reduces automation -
                 a pause, a cancel, switching a conversation off - and upgrade pending for
                 anything else, or when that store will not open (the control layer);
    always       the older watcher's own store, whose failure to open is the answer (the
                 command line's switches and cancels).

An installation in progress holds the upgrade too, for a caller that says so
(`hold_while_installing`): the control layer, behind the window, the panel and the MCP server. A
version picked in the Dashboard that reads an older state has the state converted for it, and the
watcher stopped, before that version's installer runs, all under the install lock (the bootstrap's
-Pick). A status read in between would find the mutex free and upgrade the state back, and the
older watcher would then refuse it and send nothing. So while the lock is held, or
cannot be looked at, these read the state as an older watcher's, as above. The command line keeps
upgrading under the lock: an installer's own setup runs through it.

These were three copies of the same steps, each with its policy written into it. That the
command line takes the older store where the control layer refuses it is deliberate, and each
caller still passes the policy it had. The watcher's own opening is not one of these: it holds
the mutex already and upgrades at start (App._open_for_watcher).
"""
from __future__ import annotations

from . import windows
from .store import LegacyStore, Store, StoreError, UpgradePending
from .windows import AdapterError, Mutex

POLICIES = ("never", "if_reducing", "always")
UPGRADE_PENDING = ("Upgrade pending: an older watcher still owns the state. Use Stop watcher, "
                   "then Start watcher, or sign out and back in.")


def open_state(state_dir, *, legacy: str = "never", reducing: bool = False, check: bool = False,
               upgrade_failed=None, hold_while_installing: bool = False):
    """The state in `state_dir`: a Store, or - under an older watcher - what `legacy` allows.

    Raises UpgradePending(UPGRADE_PENDING) when the policy offers nothing, and otherwise what
    the store raises: StateFromNewerVersion for a newer state, StoreError for one that cannot
    be read. `upgrade_failed`, when given, turns a failure of the upgrade itself into the
    caller's own error - the control layer reports it as the state being unavailable, whatever
    the store called it. `hold_while_installing` leaves an older state as it is while an
    installation holds its lock, or the lock cannot be looked at, and `legacy` decides what then.
    """
    if legacy not in POLICIES:
        raise ValueError("legacy must be one of " + ", ".join(POLICIES))
    try:
        return Store(state_dir, check=check)
    except UpgradePending:
        pass
    # Looked at only once the state is known to be older: a pick's conversion happens under the
    # install lock, which is held from before it until that version's installer has finished.
    if not (hold_while_installing and windows.install_in_progress() is not False):
        try:
            with Mutex(str(state_dir), timeout=0.0):
                return Store(state_dir, migrate=True, check=True)
        except AdapterError:
            pass                            # an older watcher holds the state
        except StoreError as exc:
            if upgrade_failed is None:
                raise
            raise upgrade_failed(exc) from None
    if legacy == "always":
        return LegacyStore(state_dir)
    if legacy == "if_reducing" and reducing:
        try:
            return LegacyStore(state_dir)
        except StoreError:
            pass
    raise UpgradePending(UPGRADE_PENDING)

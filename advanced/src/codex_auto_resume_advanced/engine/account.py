# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The watcher's side of account_switch (v0.6.19): which account is signed in, and what waits when it changes.

At P8, as an errand, on the watcher's first tick and then at most every LOOK_EVERY seconds while the capability stands
on, the account is read (codex/account.read: account/read through a finite session of the capability's own). What is
kept of it is a digest (codex/account.digest): HMAC-SHA256 over its address in lower case, keyed by a salt of this
installation's own - 32 random bytes in Windows Credential Manager under account_switch/salt (credentials.py) - and
its plan word, in state `account_seen` (state/account.py). Never the address, never the salt.

* The first reading since the capability was last turned on keeps the digest under a new salt, and holds nothing.
* The same digest again holds nothing, whatever the plan says now: a plan that changed is the same account.
* Another digest - another account signed in - holds, in one go, every recovery of core's still waiting for a usage
  limit (core's store.hold_waiting, HoldKind `account_changed`, actor engine: only one that waits unsent with no hold
  and no cancel, so this can only ever hold more back), and every reset rule still counting (reset_credit's and
  reset_message's, which count the windows of the account that was signed in): held as over a gap in the count
  (RuleReason count_gap), its Go on counting the person's - as engine/resetwatch.py holds one. Pending says why each
  record waits, and Let it continue or Cancel is the person's (H7: a hold is theirs to release). One notice says how
  many wait (`account_changed`, a kind registered with core in plug.py), shown once by the watcher (surfaces), and the
  journal counts `account.changed`, and `account.held` once for each.
* A reading that failed, or that finds no one signed in, changes nothing (E1: unknown is not "changed"): the digest
  is compared again once an account is read.

Turned off, the row and the salt are taken away (`forget`, from arming.Arming.sweep, the watcher's), so a digest never
outlives the capability. Nothing here signs anyone out or in: that is the Dashboard's (codex/account.switch).
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import DEFER

from ..codex import account
from ..vocabulary import RuleReason, RuleState

CAPABILITY = account.CAPABILITY
SALT = "salt"
# How often the account is read while it stands on, in seconds; and always on the watcher's first tick.
LOOK_EVERY = 1800
# Core's kind of hold, and the category of a recovery that waits for a usage limit.
HOLD = "account_changed"
USAGE_LIMIT = "usage_limit"


def _secrets():
    from ..credentials import Secrets
    from ..registry import REGISTRY
    return Secrets(REGISTRY)


def _hold_core(paths, keys, now) -> int:
    """Core's records `keys` held for the person, in core's own store: how many it held."""
    from codex_auto_resume.store import Store
    with Store(paths.state_dir) as store:
        return store.hold_waiting(keys, HOLD, now, actor="engine")


def forget(state, secrets=None) -> bool:
    """account_switch is off: the salt taken out of Credential Manager and then the account seen out of the state, where
    there is a row - one that is not there was never salted, so Credential Manager is not asked. Whether both went;
    False leaves them for the next sweep."""
    from ..credentials import SecretError
    from ..state import StateError
    try:
        if state.account_seen() is None:
            return False
        (secrets or _secrets()).delete(CAPABILITY, SALT)
        return state.end_account_seen()
    except (SecretError, StateError, OSError):
        return False


class _Errand:
    __slots__ = ("code", "view", "now")

    def __init__(self, code, view, now):
        self.code, self.view, self.now = code, view, now

    def run(self, guard):
        # Credential Manager, core's store or the state not there now is a reading that changed nothing: the next look
        # compares again, and the capability stays on.
        try:
            return self.code.look(self.view, self.now)
        except Exception:
            return None


class AccountWatch:
    """account_switch's code: its P8 errand, and the notice it asks the watcher to show. `read`, `secrets` and `hold`
    are seams a test fills: the account read (codex/account.read's shape), Credential Manager (credentials.Secrets'
    shape) and core's hold (`_hold_core`'s)."""
    __slots__ = ("paths", "_scoped", "_read", "_secrets", "_hold", "_looked", "_notice")

    def __init__(self, paths, *, read=None, secrets=None, hold=None):
        self.paths = paths
        self._scoped = None
        self._read = read or account.read
        self._secrets = secrets
        self._hold = hold or _hold_core
        self._looked = None
        self._notice = None

    def bind(self, scoped):
        self._scoped = scoped

    def tick(self, view):
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
                return DEFER
            self._looked = now
            return _Errand(self, view, now)
        except Exception:
            return DEFER

    def secrets(self):
        if self._secrets is None:
            self._secrets = _secrets()
        return self._secrets

    def look(self, view, now):
        """One reading, compared with the account seen; see the module's docstring."""
        found = self._read(self.paths)
        text = account.identity(found)
        if text is None:
            return None                      # failed, or no one signed in: nothing changes
        plan = found.get("plan_word")
        handle = self._scoped.account
        row = handle.seen()
        since = self._scoped.since()
        salt = None
        if row is not None and not (isinstance(since, (int, float)) and row["read_at"] < since):
            salt = self.secrets().read(CAPABILITY, SALT)
        if salt is None:
            # The first reading since it was turned on (or a salt that is gone): a new salt, and nothing held.
            salt = account.new_salt()
            self.secrets().write(CAPABILITY, SALT, salt)
            handle.save(account.digest(text, salt), plan, at=now)
            return None
        seen = account.digest(text, salt)
        if seen == row["identity_digest"]:
            handle.save(seen, plan, at=now)
            return None
        held = self._hold_waiting(view, now) + self._hold_rules()
        handle.save(seen, plan, at=now)
        self._count("changed")
        for _ in range(held):
            self._count("held")
        if held:
            self._notice = {"key": "account:%d" % int(now), "count": held}
        return None

    def _hold_waiting(self, view, now) -> int:
        """Every recovery of core's still waiting for a usage limit, held for the person (`account_changed`)."""
        from codex_auto_resume.domain import states
        rows = view.records_in(states.WAITING)
        keys = sorted({row["interruption_id"] for row in rows if row.get("category") == USAGE_LIMIT})
        return self._hold(self.paths, keys, now) if keys else 0

    def _hold_rules(self) -> int:
        """Every reset rule still counting, held as over a gap in its count, for what it had left to count."""
        from .resetwatch import count
        from ..state import StateError
        resets = self._scoped.resets
        held = 0
        windows = resets.windows()
        for rule in resets.reset_rules():
            if rule["state"] != RuleState.COUNTING:
                continue
            row = windows.get((rule["bucket"], rule["minutes"]))
            counted = count(rule, row) - rule["base"] if rule["base"] is not None and row is not None else 0
            try:
                held += bool(resets.change_rule(rule["rule_id"], expect=RuleState.COUNTING, state=RuleState.HELD,
                                                reason=RuleReason.COUNT_GAP,
                                                ordinal=max(1, rule["ordinal"] - max(0, counted)), base=None,
                                                adopted_at=None))
            except StateError:
                continue
        return held

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass

    def notice(self):
        """{"key", "count"} of the last change that held anything, for the watcher to show once - or None."""
        return self._notice


def make(paths) -> AccountWatch:
    return AccountWatch(paths)

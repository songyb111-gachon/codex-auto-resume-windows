# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The account the watcher last saw signed in (version 8, v0.6.19, account_switch).

    account_seen   one row: a keyed digest of the signed-in account (16 hex of HMAC-SHA256 over its address in lower
                   case, or its kind where it has none, keyed by this installation's salt in Credential Manager), its
                   plan word, and when it was read - never the address, never the salt

Written by account_switch's own code alone, and only while it is on (engine/account.py); taken away with the salt once
it is off (arming.Arming.sweep, engine/account.forget).
"""
from __future__ import annotations

import re

from ..vocabulary import PlanWord
from .session import StateError

ACCOUNT = "account_switch"
_DIGEST = re.compile(r"[0-9a-f]{16}\Z")


class AccountMixin:
    def account_seen(self) -> dict | None:
        """The one row of `account_seen` - identity_digest, plan, read_at - or None: none kept, or no file."""
        with self._read() as connection:
            row = None if connection is None else connection.execute(
                "SELECT identity_digest, plan, read_at FROM account_seen WHERE singleton=1").fetchone()
        return dict(row) if row is not None else None

    def save_account_seen(self, identity_digest, plan, *, at=None) -> None:
        """The account read now: its digest and its plan word (None where Codex named none)."""
        if not isinstance(identity_digest, str) or not _DIGEST.match(identity_digest):
            raise StateError("invalid digest")
        if plan is not None and plan not in tuple(str(word) for word in PlanWord):
            raise StateError("invalid plan")
        now = self._now(at)
        with self._transaction() as connection:
            connection.execute("INSERT INTO account_seen (singleton, identity_digest, plan, read_at) VALUES (1,?,?,?) "
                               "ON CONFLICT(singleton) DO UPDATE SET identity_digest=excluded.identity_digest, "
                               "plan=excluded.plan, read_at=excluded.read_at", (identity_digest, plan, now))

    def end_account_seen(self) -> bool:
        """The row taken away. Whether there was one."""
        with self._transaction(create=False) as connection:
            if connection is None:
                return False
            return connection.execute("DELETE FROM account_seen").rowcount > 0


class AccountHandle:
    """What a capability's code is given of the account seen (state.Scoped's `account`): the row, for account_switch
    alone, and its writes only while the runtime has it on. Held in a closure, as the Scoped view is."""
    __slots__ = ("capability", "_calls")

    def __init__(self, state, capability, on):
        self.capability = capability

        def mine(call, writes):
            def called(*arguments, **keywords):
                if capability != ACCOUNT or (writes and (on is None or on() is not True)):
                    raise StateError("only account_switch, while on, keeps the account seen")
                return call(*arguments, **keywords)
            return called
        self._calls = {"seen": mine(state.account_seen, False), "save": mine(state.save_account_seen, True)}

    def __getattr__(self, name):
        calls = object.__getattribute__(self, "_calls")
        if name in calls:
            return calls[name]
        raise AttributeError(name)

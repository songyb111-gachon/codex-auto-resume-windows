# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The watcher's side of account_auto_switch (v0.6.22): at a usage limit, switch to another saved account with room.

At P8, as an errand, at most every LOOK_EVERY seconds while it stands on:

1. a switch a crash left unfinished is settled first, once (codex/swap.recover);
2. it may act only when (`_why_not`) recovery is neither paused nor only observed; Codex keeps its sign-in in a file
   (codex/authfile.usable - a keyring, auto or ephemeral store fails closed, `not_usable`); a recovery of core's has
   waited for a usage limit at least SETTLE seconds (reset_credit, early_reset and wake_for_reset have their turn
   first); no turn runs in any conversation, nothing is queued in Codex and no other recovery waits or runs
   (codex/restart.busy, the account switch's Restart's own rule, with the usage-limit waits that are its reason let
   through); and nobody has used this PC for IDLE seconds - a restart closes Codex's window under a person's hands;
3. one attempt for each set of waiting records (an episode), and at most PER_DAY switches in 24 hours (stamps);
4. the account signed in now is read on the real home (account_switch's own read) and left out - a scratch read of the
   account in use could rotate the running app's tokens - and every other saved account that is neither exhausted
   until a reset still ahead nor needing a sign-in is read on a scratch home (codex/swap.read_profile); the one with
   the most room (the lowest most-used window, ties to the least recently used) is switched in (codex/swap.switch);
5. none with room: the journal counts `all_exhausted` once for the episode, one notice says so (core's kind
   accounts_exhausted, registered by plug.py; surfaces.autoswitch_view), and recovery waits as today;
6. a switch that did not finish - its target not signed in, the previous file not back yet, the app not started again,
   another account signed in meanwhile, a failure - or one a crash left that was settled other than as switched, says so
   once too: the same kind, with the closed word `why` "not_finished" (the security review's finding 9), once for each
   target in this watcher's life.

After a switch the watcher's P7 answers EARLY for every record that waits for a usage limit, for EARLY_FOR seconds:
core then reads live usage (A12's check kept) and recovers as usual on the new account. account_switch's watch, which
holds recoveries when another account is signed in, asks `profiles.switched_to` first and holds none for this switch
(engine/account.py); its reset rules and window_anchor's stamps still follow the change of account.

Every seam is a test's: `store` (profiles.Profiles), `session_for`, `restart`, `read_real`, `idle` and `busy`.
"""
from __future__ import annotations

import time

from codex_auto_resume.domain.plug import DEFER, Alternative

from ..vocabulary import OptionKey

CAPABILITY = "account_auto_switch"
# Seconds: how often it looks; how long a recovery has waited for a usage limit before a switch is considered; how
# long nobody has used this PC; how long after a switch P7 releases the waiting records.
LOOK_EVERY = 60
SETTLE = 300
IDLE = 120
EARLY_FOR = 900
# The most switches in 24 hours (the owner, 2026-11-05: ten, "최대에 더 여유만 줘").
PER_DAY = 10
DAY = 86400
USAGE_LIMIT = "usage_limit"
# What a switch or a settled crash came to that a person is told of once (codex/swap.py's closed words). engine_alive
# from a switch too (the review's finding 18): the app was closed and started in front of nobody and nothing came of it.
# The look's own engine_alive (`_why_not`, nothing closed) stays silent.
NOT_FINISHED = ("not_signed_in", "not_put_back", "not_started", "changed_under", "failed", "left", "engine_alive")


class _Errand:
    __slots__ = ("code", "view", "now")

    def __init__(self, code, view, now):
        self.code, self.view, self.now = code, view, now

    def run(self, guard):
        try:
            return self.code.look(self.view, self.now)
        except Exception:
            return None


def _idle():
    from .opentarget import idle_seconds
    return idle_seconds()


class AutoSwitch:
    """account_auto_switch's code: its P8 errand and its P7 answer. See the module."""
    __slots__ = ("paths", "_scoped", "_saved", "_session_for", "_restart", "_read_real", "_idle", "_busy", "_home",
                 "_looked", "_episode", "_switched_at", "_notice")

    def __init__(self, paths, *, store=None, session_for=None, restart=None, read_real=None, idle=None, busy=None,
                 home=None):
        self.paths = paths
        self._scoped = None
        self._saved, self._session_for, self._restart, self._read_real = store, session_for, restart, read_real
        self._idle = idle or _idle
        self._busy = busy
        self._home = home
        self._looked = None
        self._episode = None
        self._switched_at = None
        self._notice = None

    def bind(self, scoped):
        self._scoped = scoped

    # ------------------------------------------------------------------ seams
    def store(self):
        if self._saved is None:
            from ..profiles import Profiles
            self._saved = Profiles(self.paths.home)
        return self._saved

    def home(self):
        if self._home is None:
            from ..codex import inuse
            return inuse.home(self.paths)
        return self._home

    def busy(self):
        if self._busy is not None:
            return self._busy()
        from ..codex import restart as restarts
        return restarts.busy(self.paths, usage_waiting_ok=True)

    def _restart_now(self, between):
        """codex/restart.restart for a switch, or a put-back a later look finishes - None where it may not restart now:
        something runs or is queued, or someone uses this PC (the switch's own rule, `_why_not`), looked at again right
        before the close: reading every saved account can take minutes (the v0.6.23 audit's A-R1)."""
        idle = self._idle()
        if self.busy() or not isinstance(idle, (int, float)) or idle < IDLE:
            return None
        if self._restart is not None:
            return self._restart(between)
        from ..codex import restart as restarts
        return restarts.restart(self.paths, between=between)

    def read_real(self):
        if self._read_real is not None:
            return self._read_real()
        from ..codex.account import read
        return read(self.paths)

    # ------------------------------------------------------------------ P8
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

    def waiting(self, view, now) -> list:
        """Core's records that have waited for a usage limit at least SETTLE seconds."""
        from codex_auto_resume.domain import states
        return [row for row in view.records_in(states.WAITING)
                if row.get("category") == USAGE_LIMIT and not row.get("hold") and not row.get("cancel_requested")
                and isinstance(row.get("detected_at"), (int, float)) and now - row["detected_at"] >= SETTLE]

    def _why_not(self, view, rows) -> str | None:
        from ..codex import authfile
        try:
            settings = view.settings()
        except Exception:
            settings = None
        if not isinstance(settings, dict) or settings.get("enabled") is not True or settings.get("observe_only"):
            return "paused"
        if not rows:
            return "nothing_waits"
        if authfile.usable(self.home()) != authfile.USABLE:
            return "not_usable"
        if self.busy():
            return "busy"
        from ..codex import swap
        if swap.other_engines(swap._inventory(), app_open=True):
            return "engine_alive"                        # a TUI, IDE or exec-server engine of its own: it waits
        idle = self._idle()
        if not isinstance(idle, (int, float)) or idle < IDLE:
            return "in_use"
        return None

    def _today(self, now) -> int:
        day = int(now // DAY) + 1
        if self._scoped.stamped(OptionKey.AUTO_SWITCH_DAY) != day:
            return 0
        return self._scoped.stamped(OptionKey.AUTO_SWITCH_COUNT) or 0

    def look(self, view, now):
        """One look; see the module's docstring. Returns nothing: what it did is in the journal and the stamps."""
        from ..codex import swap
        from ..codex import authfile
        store, home = self.store(), self.home()
        intent = store.intent()
        # What a kill or a held file left in plain text - a scratch home, a temporary beside the sign-in file - goes first.
        _removed, failed = authfile.sweep(store.directory, home)
        if failed:
            self._count("sweep_failed")
        settled = swap.recover(self.paths, store, home, read_real=self.read_real, restart=self._restart_now)
        if settled == swap.SWITCHED:
            self._switched(now)
        elif settled is not None:
            self._count(settled)
            if settled in NOT_FINISHED and isinstance(intent, dict):
                self._not_finished(intent.get("to"))
        rows = self.waiting(view, now)
        if self._why_not(view, rows) is not None:
            return None
        episode = frozenset(row["interruption_id"] for row in rows)
        if episode == self._episode:
            return None                                  # one attempt for each set of waiting records
        self._episode = episode
        if self._today(now) >= PER_DAY:
            self._count("ceiling")
            return None
        target = self.choose(store, now)
        if target is None:
            self._count("all_exhausted")
            # One notice for this set of waiting records (core's kind accounts_exhausted, plug.NOTICE_KINDS).
            self._notice = {"key": "autoswitch:%d" % int(min(row["detected_at"] for row in rows))}
            return None
        outcome = swap.switch(self.paths, store, home, target, restart=self._restart_now, read_real=self.read_real,
                              now=now)
        self._count(outcome)
        if outcome in NOT_FINISHED:
            self._not_finished(target)
        if outcome in (swap.SWITCHED, swap.NOT_STARTED):
            if outcome == swap.SWITCHED:
                self._switched(now)                      # NOT_STARTED: the app is closed, so P7 releases nothing early
            day = int(now // DAY) + 1
            self._scoped.stamp(OptionKey.AUTO_SWITCH_COUNT, self._today(now) + 1)
            self._scoped.stamp(OptionKey.AUTO_SWITCH_DAY, day)
        return None

    def choose(self, store, now):
        """The saved account to switch to - the most room, ties to the least recently used - or None."""
        from ..codex import swap
        from ..codex.account import identity
        from ..profiles import ProfileError, READY
        current = identity(self.read_real())
        if current is None:
            return None                                  # who is signed in cannot be told: nothing is read or switched
        best = None
        for profile_id in store.ids():
            try:
                profile = store.get(profile_id)
            except ProfileError:
                continue
            if (profile.get("email") or "").lower() == current or store.state(profile, now) != READY:
                continue
            found = swap.read_profile(self.paths, store, profile_id, session_for=self._session_for, now=now)
            if not swap.has_room(found):
                continue
            rank = (found["most_used"], profile.get("used_at") or 0)
            if best is None or rank < best[0]:
                best = (rank, profile_id)
        return best[1] if best else None

    def _switched(self, now) -> None:
        self._switched_at = now
        self._scoped.stamp(OptionKey.AUTO_SWITCHED_AT, max(1, int(now)))

    def _count(self, code) -> None:
        try:
            self._scoped.count(code)
        except Exception:
            pass

    def _not_finished(self, target) -> None:
        """One notice that a switch did not finish, keyed by its target: once for each in this watcher's life."""
        self._notice = {"key": "autoswitch:not_finished:%s" % (target if isinstance(target, str) else "unknown"),
                        "why": "not_finished"}

    def notice(self):
        """{"key"} of the last look that found every saved account at its limit - or {"key", "why": "not_finished"} of a
        switch that did not finish - for the watcher to show once; or None."""
        return self._notice

    # ------------------------------------------------------------------ P7
    def schedule(self, record, eligible_at):
        """EARLY for a record that waits for a usage limit, for EARLY_FOR seconds after this capability switched the
        account; DEFER for anything else. Core reads live usage before it sends (A12's check)."""
        from codex_auto_resume.domain import states
        scoped = self._scoped
        if scoped is None or not isinstance(record, dict) or record.get("category") != USAGE_LIMIT:
            return DEFER
        try:
            now = scoped.now()
            switched = self._switched_at or scoped.stamped(OptionKey.AUTO_SWITCHED_AT)
        except Exception:
            return DEFER
        if (not isinstance(switched, (int, float)) or not 0 <= now - switched < EARLY_FOR
                or record.get("state") not in states.WAITING or not isinstance(eligible_at, (int, float))
                or eligible_at <= now):
            return DEFER
        return Alternative.EARLY


def make(paths) -> AutoSwitch:
    return AutoSwitch(paths)

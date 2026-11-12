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
   the most room (the lowest most-used window, ties to the least recently used: `best`, which the card's next-candidate
   line asks too) is switched in (codex/swap.switch); each read is kept in its profile for the card's meters, and the
   account found signed in is marked as the one in use (profiles' `seen_at`);
5. none with room: the journal counts `all_exhausted` once for the episode, one notice says so (core's kind
   accounts_exhausted, registered by plug.py; surfaces.autoswitch_view), and recovery waits as today - but with no saved
   account other than the one in use (none saved at all, the reachability audit's M8) nothing is said or counted: there
   is no account to be at its limit;
6. a switch that did not finish - its target not signed in, the previous file not back yet, the app not started again,
   another account signed in meanwhile, a failure - or one a crash left that was settled other than as switched, says so
   once too: the same kind, with the closed word `why` "not_finished" (the security review's finding 9), once for each
   target in this watcher's life.

After a switch the watcher's P7 answers EARLY for every record that waits for a usage limit, for EARLY_FOR seconds:
core then reads live usage (A12's check kept) and recovers as usual on the new account. account_switch's watch, which
holds recoveries when another account is signed in, asks `profiles.switched_to` first and holds none for this switch
(engine/account.py); its reset rules and window_anchor's stamps still follow the change of account.

Switch to this account (v0.6.22 final, the owner's 2026-11-08): a person's own switch to one saved account, from the
saved-accounts card under either account capability (control/autoswitch.switch), is this same switch - `put_in`, which
the look calls with the account it chose - given the account the person picked: the same swap, close and restart,
sign-in check and undo of a switch that did not finish. Only what makes it the person's differs: nobody need be away
from the PC (the click is theirs), it is not counted toward PER_DAY, and the bridge journals it in its own words
(MANUAL_SWITCHED, MANUAL_NOT_FINISHED, MANUAL_NOT_DONE).

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
# What a person's own Switch to this account came to, in the journal (registry codes): the account switched; a switch
# that closed the Codex app and did not finish (NOT_FINISHED, undone or still to be put back); and one that changed nothing
# - the app would not close, its hands said no at the last look, another switch or read held the saved accounts, or the
# sign-in was not a file (MANUAL_NOTHING).
MANUAL_SWITCHED, MANUAL_NOT_FINISHED, MANUAL_NOT_DONE = "manual_switched", "manual_not_finished", "manual_not_done"
MANUAL_NOTHING = ("not_closed", "held", "locked", "not_usable")


class _Errand:
    __slots__ = ("code", "view", "now")

    def __init__(self, code, view, now):
        self.code, self.view, self.now = code, view, now

    def run(self, guard):
        try:
            return self.code.look(self.view, self.now)
        except Exception:
            return None


class _Settle:
    """tend's errand: the unfinished switch settled, nothing else."""
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def run(self, guard):
        try:
            return self.code.settle()
        except Exception:
            return None


def _idle():
    from .opentarget import idle_seconds
    return idle_seconds()


class AutoSwitch:
    """account_auto_switch's code: its P8 errand and its P7 answer. See the module."""
    __slots__ = ("paths", "_scoped", "_saved", "_session_for", "_restart", "_read_real", "_idle", "_busy", "_home",
                 "_looked", "_episode", "_switched_at", "_notice", "_others")

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
        self._others = 0

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

    def _restart_now(self, between, *, away=True):
        """codex/restart.restart for a switch, or a put-back a later look finishes - None where it may not restart now:
        something runs or is queued, or someone uses this PC (the switch's own rule, `_why_not`), looked at again right
        before the close: reading every saved account can take minutes (the v0.6.23 audit's A-R1). `away` False for a
        person's own switch: the person at the PC is the one who asked for it."""
        if self.busy():
            return None
        idle = self._idle() if away else IDLE
        if not isinstance(idle, (int, float)) or idle < IDLE:
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
        """How many switches were made in the last DAY seconds - a rolling 24 hours, not a UTC calendar day, which let
        twenty through around midnight UTC (the v0.6.23 audit's A-R2)."""
        return len(self._recent(now))

    def _recent(self, now) -> list:
        store = self.store()
        try:
            times = store.attempts()
        except Exception:
            times = None
        if times is None:
            # Before v0.6.23 the count was the UTC day's, in two stamps: kept as switches made now, so an update never
            # frees that day's ceiling early.
            day = int(now // DAY) + 1
            legacy = self._scoped.stamped(OptionKey.AUTO_SWITCH_COUNT) or 0
            legacy = legacy if self._scoped.stamped(OptionKey.AUTO_SWITCH_DAY) == day else 0
            times = [int(now)] * min(int(legacy), PER_DAY)
            if times:
                self._keep(times)
        return [value for value in times if 0 <= now - value < DAY]

    def _attempted(self, now) -> None:
        """One more switch counted toward the 24-hour ceiling."""
        self._keep((self._recent(now) + [int(now)])[-PER_DAY:])

    def _keep(self, times) -> None:
        try:
            self.store().note_attempts(times)
        except Exception:
            pass

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
        if store.intent() is not None:
            return None                                  # a switch not settled yet (a put-back, an account not read): no other
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
        if target is None and not self._others:
            return None                                  # nothing saved but the account in use: nothing to be at a limit
        if target is None:
            self._count("all_exhausted")
            # One notice for this set of waiting records (core's kind accounts_exhausted, plug.NOTICE_KINDS).
            self._notice = {"key": "autoswitch:%d" % int(min(row["detected_at"] for row in rows))}
            return None
        outcome, closed = self.put_in(target, now)
        self._count(outcome)
        if outcome in NOT_FINISHED:
            self._not_finished(target)
        if outcome == swap.SWITCHED:
            self._switched(now)                          # NOT_STARTED: the app is closed, so P7 releases nothing early
        if outcome in (swap.SWITCHED, swap.NOT_STARTED) or closed:
            self._attempted(now)
        return None

    def put_in(self, target, now, *, manual=False):
        """The switch itself (codex/swap.switch) to the saved account `target`, through this capability's restart hands:
        (its outcome, whether it closed the Codex app). The look's, with the account it chose; and (`manual`) a person's
        own Switch to this account, with the account they picked - for which nobody need be away from the PC."""
        from ..codex import swap
        closed = []

        def hands(between):
            # Whether this attempt closed the Codex app (how it ended, CLOSED or ENDED): every such attempt of the look's
            # counts toward the ceiling, a switch or not - it is about restarts in front of a person too (the v0.6.23
            # audit's A-M2).
            found = self._restart_now(between, away=not manual)
            if isinstance(found, tuple) and len(found) > 1 and found[1] is not None:
                closed.append(found[1])
            return found
        outcome = swap.switch(self.paths, self.store(), self.home(), target, restart=hands, read_real=self.read_real,
                              now=now)
        return outcome, closed

    def choose(self, store, now):
        """The saved account to switch to - the most room, ties to the least recently used (`best`) - or None. How many
        saved accounts other than the one in use there are, in any state, is kept in `_others`."""
        from ..codex import swap
        from ..codex.account import identity
        from ..profiles import ProfileError, READY
        self._others = 0
        current = identity(self.read_real())
        if current is None:
            return None                                  # who is signed in cannot be told: nothing is read or switched
        candidates = []
        for profile_id in store.ids():
            try:
                profile = store.get(profile_id)
            except ProfileError:
                continue
            if (profile.get("email") or "").lower() == current:
                seen(store, profile_id, now)
                continue
            self._others += 1
            if store.state(profile, now) != READY:
                continue
            found = swap.read_profile(self.paths, store, profile_id, session_for=self._session_for, now=now)
            candidates.append((profile_id, found, profile.get("used_at")))
        return best(candidates)

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

    # ------------------------------------------------------------------ off or watched
    def tend(self, view):
        """While the capability is off or watched (runtime.TENDED, the v0.6.23 audit's A-M3): a switch it left unfinished -
        a put-back still waiting - is settled at most every LOOK_EVERY seconds, by codex/swap.recover alone, through the
        same restart hands; never a new switch, never a read of another account. DEFER where no switch is under way."""
        scoped = self._scoped
        if scoped is None:
            return DEFER
        try:
            now = scoped.now()
            if self._looked is not None and 0 <= now - self._looked < LOOK_EVERY:
                return DEFER
            self._looked = now
            if self.store().intent() is None:
                return DEFER
            return _Settle(self)
        except Exception:
            return DEFER

    def settle(self):
        from ..codex import swap
        settled = swap.recover(self.paths, self.store(), self.home(), read_real=self.read_real,
                               restart=self._restart_now)
        if settled is not None:
            self._count(settled)
        return None

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
            # This watcher's own switch, or one the stamp keeps - a person's Switch to this account stamps it too.
            kept = [at for at in (self._switched_at, scoped.stamped(OptionKey.AUTO_SWITCHED_AT))
                    if isinstance(at, (int, float))]
            switched = max(kept) if kept else None
        except Exception:
            return DEFER
        if (not isinstance(switched, (int, float)) or not 0 <= now - switched < EARLY_FOR
                or record.get("state") not in states.WAITING or not isinstance(eligible_at, (int, float))
                or eligible_at <= now):
            return DEFER
        return Alternative.EARLY


def best(candidates):
    """Of (profile id, a read's found, when it was last switched to), the one a switch picks: its own account with room
    (codex/swap.has_room), the lowest most-used window, ties to the least recently used - or None. The look's choice,
    and the card's next candidate from the readings kept (control/autoswitch.py)."""
    from ..codex import swap
    picked = None
    for profile_id, found, used_at in candidates:
        if not swap.has_room(found):
            continue
        rank = (found["most_used"], used_at or 0)
        if picked is None or rank < picked[0]:
            picked = (rank, profile_id)
    return picked[1] if picked else None


def seen(store, profile_id, now) -> None:
    """The saved account found signed in now marked so (profiles' `seen_at`): the card's "in use". Never fatal."""
    from ..profiles import KEEP_SECONDS
    try:
        with store.locked(KEEP_SECONDS):
            store.update(profile_id, seen_at=int(now))
    except Exception:
        pass


def make(paths) -> AutoSwitch:
    return AutoSwitch(paths)

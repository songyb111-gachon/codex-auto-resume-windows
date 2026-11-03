# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""account_auto_switch's two acts on Codex (v0.6.22): read a saved account's usage, and switch the Codex app to it.

`read_profile` reads one saved account on a scratch Codex home made from its sealed copy (authfile.Scratch): one finite
session of this capability's own asks account/read and account/rateLimits/read there - never on the real home, whose
file and running app it leaves alone (MPROFILE measures exactly that). A copy Codex refreshed there is sealed back into
the profile; one Codex answers as signed out is marked as needing a sign-in and never read again until the person signs
it in again. What comes back is closed: present, whether it is the profile's own account, the plan word, whether usage
is available, the most used window's percentage and the latest reset of a full window - never an address.

`switch` puts a profile's account in, in this order (plans/v0622-account-autoswitch-design.md section 6):
1. the switch is written down (profiles' intent), so a crash in the middle is finished or undone at the next look;
2. the Codex app is closed as account_switch's Restart closes it (codex/restart.restart: Windows' request, its process
   ended only if still running 30 s later) - or, where it does not run, nothing is closed;
3. with nothing of the app left to write it, the sign-in file in use is sealed back into its own profile (refresh tokens
   rotate: a copy that is not saved back goes stale), then the target's copy is put in its place in one rename;
4. the app is started again through its own codex: link, and the account read afresh on a session of its own;
5. the target's account signed in is SWITCHED; anything else puts the previous file back - with the app closed again
   and started, once - marks the target as needing a sign-in, and is NOT_SIGNED_IN. Never a second try.

Each hand is a seam: `session_for` (a Codex home -> a session context manager), `restart` (codex/restart.restart's
shape, given `between`) and `read_real` (the account read on the real home). A test fills them all.
"""
from __future__ import annotations

from . import authfile
from .account import identity, parse

CAPABILITY = "account_auto_switch"
ACCOUNT_READ = "account/read"
USAGE_READ = "account/rateLimits/read"
# A saved account may be switched to only while every window it reports is below this percentage.
ROOM_BELOW = 95
# What a switch came to (closed words: the journal's and the card's).
SWITCHED, NOT_SIGNED_IN, NOT_USABLE, NOT_CLOSED, FAILED = "switched", "not_signed_in", "not_usable", "not_closed", "failed"
OUTCOMES = (SWITCHED, NOT_SIGNED_IN, NOT_USABLE, NOT_CLOSED, FAILED)


def default_session_for(paths):
    """A session factory on any Codex home, with the Codex the installation drives."""
    def session_for(home):
        from codex_auto_resume.codex.transport import Backend
        from . import inuse
        from .protocol import Session
        driven = inuse.backend(paths)
        made = Backend(home, driven.codex_exe)
        made._compatible()
        return Session(made, capability=CAPABILITY)
    return session_for


def usage_of(reply) -> dict:
    """{available, most_used, full_until} of one account/rateLimits/read answer (core's allowlist, codex/usage.py)."""
    from codex_auto_resume.codex.usage import parse_usage
    from codex_auto_resume.domain import usage as readings
    parsed = parse_usage(reply)
    windows = readings.windows_of(parsed) or []
    used = [window["used_percent"] for window in windows]
    full = [window["reset_at"] for window in windows
            if window["used_percent"] >= 100 and window.get("reset_at") is not None]
    resets = full or ([parsed["reset_at"]] if parsed.get("available") is False and parsed.get("reset_at") else [])
    return {"available": parsed.get("available") if type(parsed.get("available")) is bool else None,
            "most_used": max(used) if used else None, "full_until": max(resets) if resets else None}


def has_room(found) -> bool:
    """Whether a read saved account may be switched to: its own account, usage available, every window below ROOM_BELOW."""
    return (found.get("present") is True and found.get("own") is True and found.get("available") is True
            and isinstance(found.get("most_used"), (int, float)) and found["most_used"] < ROOM_BELOW)


def read_profile(paths, store, profile_id, *, session_for=None, now=None) -> dict:
    """One read of a saved account on a scratch home; see the module. {present: None, ...} where it could not be read."""
    from ..profiles import ProfileError
    found = {"present": None, "own": None, "plan": None, "available": None, "most_used": None, "full_until": None}
    try:
        profile = store.get(profile_id)
    except ProfileError:
        return found
    session_for = session_for or default_session_for(paths)
    scratch = authfile.Scratch(store.directory, profile["auth"])
    try:
        with scratch as home:
            with session_for(home) as session:
                account = parse(session.call(ACCOUNT_READ, {}))
                usage = session.call(USAGE_READ, {}) if account.get("present") is True else None
    except Exception:
        return found
    found["present"] = account.get("present")
    saved = profile.get("email")
    found["own"] = (identity(account) == saved.lower()) if isinstance(saved, str) and found["present"] else None
    found["plan"] = account.get("plan_word")
    if usage is not None:
        found.update(usage_of(usage))
    try:
        if found["present"] is False or found["own"] is False:
            store.update(profile_id, failed_at=int(now or store._clock()))
        else:
            changes = {}
            if scratch.after is not None and scratch.after != profile["auth"]:
                changes["auth"] = scratch.after                  # Codex refreshed the tokens there: keep the newer copy
            if found["full_until"]:
                changes["exhausted_until"] = int(found["full_until"])
            if changes:
                store.update(profile_id, **changes)
    except (ProfileError, OSError):
        pass
    return found


def switch(paths, store, codex_home, target_id, *, restart=None, read_real=None, now=None) -> str:
    """Put the saved account `target_id` in as Codex's sign-in at `codex_home`; see the module. One of OUTCOMES."""
    from ..profiles import ProfileError
    from . import restart as restarts
    if authfile.usable(codex_home) != authfile.USABLE:
        return NOT_USABLE
    try:
        target = store.get(target_id)
        current = authfile.read(codex_home)
    except (ProfileError, OSError):
        return FAILED
    restart = restart or (lambda between: restarts.restart(paths, between=between))
    read_real = read_real or (lambda: _read_real(paths))
    stamp = int(now or store._clock())
    before = read_real()
    if before.get("present") is not True or not before.get("email"):
        return NOT_USABLE                                    # an account that cannot be told apart is never swapped out
    try:
        # The account in use is kept first - saved now if it never was - so its sign-in is never lost by the swap.
        source_id = store.find(before["email"]) or store.save(current, before["email"], before.get("plan_word"))
    except (ProfileError, OSError):
        return FAILED
    if source_id == target_id:
        return FAILED
    done = {"swapped": False}

    def between():
        # The app is gone: the file in use goes back into its own profile, then the target's copy takes its place.
        latest = authfile.read(codex_home)
        store.update(source_id, auth=latest, used_at=stamp)
        authfile.replace(codex_home, target["auth"])
        done["swapped"] = True

    store.begin(source_id, target_id)
    try:
        outcome, _how = restart(between)
        if outcome == restarts.NOT_RUNNING:
            between()                                        # Codex is closed: the next start reads the new file
        elif outcome in (restarts.NOT_ENDED, restarts.FAILED) and not done["swapped"]:
            return NOT_CLOSED
        if not done["swapped"]:
            return FAILED
        after = read_real()
        if identity(after) is not None and identity(after) == (target.get("email") or "").lower():
            store.update(target_id, used_at=stamp)
            store.mark_switched(target["email"])
            return SWITCHED
        # Not the target: the previous file back, Codex started on it once more, and the target set aside.
        put_back = store.get(source_id)["auth"]

        def back():
            authfile.replace(codex_home, put_back)
        outcome, _how = restart(back)
        if outcome == restarts.NOT_RUNNING:
            back()
        store.update(target_id, failed_at=stamp)
        return NOT_SIGNED_IN
    except (ProfileError, OSError):
        return FAILED
    finally:
        store.end()


def _read_real(paths) -> dict:
    from .account import read
    return read(paths)


def recover(paths, store, codex_home, *, read_real=None) -> str | None:
    """A switch the watcher did not see finish (an intent left behind by a crash): settled once and the intent cleared.
    The account signed in now is read: the target's - SWITCHED; anything else - the previous profile's copy is put back
    where Codex does not run, NOT_SIGNED_IN. None where no switch was under way."""
    from ..profiles import ProfileError
    intent = store.intent()
    if intent is None:
        return None
    read_real = read_real or (lambda: _read_real(paths))
    try:
        target = store.get(intent.get("to")) if isinstance(intent.get("to"), str) else None
        now = identity(read_real())
        if target is not None and now is not None and now == (target.get("email") or "").lower():
            store.mark_switched(target["email"])
            return SWITCHED
        if isinstance(intent.get("from"), str) and not _app_running():
            authfile.replace(codex_home, store.get(intent["from"])["auth"])
        return NOT_SIGNED_IN
    except (ProfileError, OSError):
        return FAILED
    finally:
        store.end()


def _app_running() -> bool:
    try:
        from codex_auto_resume.codex.pairing import app_running, inventory
        return bool(app_running(inventory()))
    except Exception:
        return True                                          # unknown is running: nothing is written under it

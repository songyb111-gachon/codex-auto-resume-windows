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
   and started, once, and only over the target's copy it put in - marks the target as needing a sign-in, and is
   NOT_SIGNED_IN. Where that put-back did not happen (the app would not close, the rename was refused), the intent
   stays - NOT_PUT_BACK - and each later look tries again (`recover`) until the file is the previous one.

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
# A switch left unfinished whose sign-in file is not the one it put in: the file is left as it is (recover).
LEFT = "left"
# The target was not signed in and the previous file could not be put back yet: the intent stays, the next look tries again.
NOT_PUT_BACK = "not_put_back"
OUTCOMES = (SWITCHED, NOT_SIGNED_IN, NOT_USABLE, NOT_CLOSED, FAILED, LEFT, NOT_PUT_BACK)
# The most restarts later looks make to put the previous file back; after them they wait for Codex to be closed.
BACK_TRIES = 3


def default_backend_for(paths, exe=None):
    """Core's Backend on any Codex home, with the Codex the installation drives (or `exe`), checked."""
    def backend_for(home):
        from codex_auto_resume.codex.transport import Backend
        from . import inuse
        made = Backend(home, exe if exe is not None else inuse.backend(paths).codex_exe)
        made._compatible()
        return made
    return backend_for


def default_session_for(paths, exe=None, measurement=None):
    """A session factory on any Codex home: this capability's own session, or a measurement's (MPROFILE, MSWAP)."""
    backend_for = default_backend_for(paths, exe)

    def session_for(home):
        from .protocol import Session
        if measurement is not None:
            return Session(backend_for(home), measurement)
        return Session(backend_for(home), capability=CAPABILITY)
    return session_for


def add_by_login(paths, store, *, backend_for=None, session_for=None, runner=None, seconds=None):
    """Add an account: Codex's own `codex login` on a scratch home (the person signs in in their browser, on OpenAI's
    page - the product never sees a password), then that home's sign-in file sealed as a profile with the address and
    plan account/read answers there; the scratch home removed whatever happened. The profile's id, or None where the
    sign-in did not finish or no address could be read. `backend_for`, `session_for` and `runner` are a test's."""
    from .account import LOGIN_SECONDS, _run_codex
    backend_for = backend_for or default_backend_for(paths)
    session_for = session_for or default_session_for(paths)
    if runner is None:
        from ..report.github import run_process as runner
    scratch = authfile.Scratch(store.directory)
    try:
        with scratch as home:
            backend = backend_for(home)
            code = _run_codex(runner, list(backend._argv()) + ["login"], backend, seconds or LOGIN_SECONDS)
            if code != 0:
                return None
            with session_for(home) as session:
                account = parse(session.call(ACCOUNT_READ, {}))
            data = authfile.read(home)
    except Exception:
        return None
    if account.get("present") is not True or not account.get("email"):
        return None
    try:
        return store.save(data, account["email"], account.get("plan_word"))
    except OSError:
        return None


def save_current(paths, store, codex_home, *, read_real=None):
    """Save the account in use: the real sign-in file sealed as its profile. Its id, or None where the sign-in is not a
    file (authfile.usable) or the account cannot be told apart."""
    if authfile.usable(codex_home) != authfile.USABLE:
        return None
    found = (read_real or (lambda: _read_real(paths)))()
    if found.get("present") is not True or not found.get("email"):
        return None
    try:
        return store.save(authfile.read(codex_home), found["email"], found.get("plan_word"))
    except OSError:
        return None


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
        # Not the target: the previous file back, Codex started on it once more, and the target set aside. The intent
        # stays until the file in place is the previous one, so a put-back that did not happen is tried again.
        store.update(target_id, failed_at=stamp)
        if _put_back(codex_home, target["auth"], store.get(source_id)["auth"], restart):
            return NOT_SIGNED_IN
        store.begin(source_id, target_id, step="back")
        done["kept"] = True
        return NOT_PUT_BACK
    except (ProfileError, OSError):
        return FAILED
    finally:
        if not done.get("kept"):
            store.end()


def _read_real(paths) -> dict:
    from .account import read
    return read(paths)


def _put_back(codex_home, put_in, previous, restart) -> bool:
    """The previous sign-in file back in place of `put_in` - the target's copy a switch put there, and only over it -
    through `restart` (the app closed and started) or directly where Codex does not run. Whether the file in place is
    the previous one now. `restart` None: only where Codex does not run."""
    from . import restart as restarts

    def back():
        if _is_in_place(codex_home, put_in):
            authfile.replace(codex_home, previous)
    if restart is not None:
        outcome = restart(back)
    else:
        outcome = None if _app_running() else (restarts.NOT_RUNNING, None)
    if outcome is not None and outcome[0] == restarts.NOT_RUNNING:
        try:
            back()
        except OSError:
            pass
    return _is_in_place(codex_home, previous)


def recover(paths, store, codex_home, *, read_real=None, restart=None) -> str | None:
    """A switch the watcher did not see finish (an intent left behind by a crash): settled once and the intent cleared.
    The account signed in now is read: the target's - SWITCHED. Anything else: only where the sign-in file in place is,
    byte for byte, the target's copy this switch put in - and Codex does not run - the previous profile's copy goes back,
    NOT_SIGNED_IN; a file it did not put there (the switch never got that far, Codex refreshed it, or a person signed in
    since, the capability off meanwhile) is left exactly as it is, LEFT. Nothing writes the sign-in file unless it knows
    what is there now. Where the previous copy cannot go back yet - Codex runs and may not be restarted now (`restart`
    None, or answering None), or the rename is refused - the intent stays, NOT_PUT_BACK, and the next look tries again;
    at most BACK_TRIES restarts, then only once Codex is closed. None where no switch was under way."""
    from ..profiles import ProfileError
    intent = store.intent()
    if intent is None:
        return None
    read_real = read_real or (lambda: _read_real(paths))
    kept = False
    try:
        target = store.get(intent.get("to")) if isinstance(intent.get("to"), str) else None
        now = identity(read_real())
        if target is not None and now is not None and now == (target.get("email") or "").lower():
            store.mark_switched(target["email"])
            return SWITCHED
        if target is None or not isinstance(intent.get("from"), str) or not _is_in_place(codex_home, target["auth"]):
            return LEFT
        tries = intent.get("tries") if isinstance(intent.get("tries"), int) else 0
        made = []

        def counted(between):
            found = restart(between)
            made.extend(() if found is None else [found])
            return found
        hand = counted if restart is not None and tries < BACK_TRIES else None
        if _put_back(codex_home, target["auth"], store.get(intent["from"])["auth"], hand):
            return NOT_SIGNED_IN
        store.begin(intent["from"], intent["to"], step="back", tries=tries + len(made))
        kept = True
        return NOT_PUT_BACK
    except (ProfileError, OSError):
        return FAILED
    finally:
        if not kept:
            store.end()


def _is_in_place(codex_home, data) -> bool:
    """Whether the sign-in file at `codex_home` is, byte for byte, `data` - the one way to know what is there now."""
    try:
        return authfile.read(codex_home) == data
    except authfile.AuthFileError:
        return False


def _app_running() -> bool:
    try:
        from codex_auto_resume.codex.pairing import app_running, inventory
        return bool(app_running(inventory()))
    except Exception:
        return True                                          # unknown is running: nothing is written under it

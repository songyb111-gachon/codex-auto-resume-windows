# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The person's saved Codex accounts (account_auto_switch, v0.6.22): each a copy of Codex's sign-in file, sealed.

A profile is one file, `<product home>\\accounts\\<id>.dat`: Windows' data protection for the current user
(win/dpapi.py) over a JSON object - the sign-in file's bytes (base64), the account's address and plan word as
account/read answered them, and when it was saved, last switched to, found exhausted until, and found unusable. Nothing
of it is in settings.json, the state, a log, the journal, diagnostics, a compatibility report or a statement; what
leaves this module for a person to see is `view`: an id, the address masked as the account card masks it, the plan
word and a closed state word. Delete takes the file away; Delete all takes every one - in every state, on, watched, off
or hidden, the card listing them while any is kept. Turning the capability off keeps them (the person saved them), and
nothing but that card reads them while it is off. The folder carries the product's provenance marker, so uninstall's
purge (config.Paths.owned_account_files, and the installer's) takes it whole.

Two more sealed files sit beside them: `switch.intent` - a switch under way (from, to, step), so a crash in the middle is
finished or undone at the next look - and `switch.last` - the account a switch of this capability put in and when, so
account_switch's watch tells that change from one a person made (`switched_to`).

The card's usage meters (v0.6.22 final): a profile also keeps the last usage reading made of it - `usage`, the read time,
whether usage was available, the most used window and the five-hour and weekly windows' used percentage and reset time
(numbers only, never an address or anything of the account's content) - and `unread_at`, when a read of it last broke,
and `seen_at`, when this product last found it signed in. They sit in the profile's own sealed file, beside what it
held, so no new secret and no new store is made: an earlier build (v0.6.22-beta.2) opens the file as before, ignores the
three keys, and carries them through its own updates (`update` rewrites the record whole); its Save of the same account
drops them, as it drops nothing else it needs. One more sealed file, `usage.read`, says when the card's Read usage last
began (`read_now_at`), so it reads at most once every ten minutes across the bridge's processes; an earlier build lists
only `<id>.dat` and never opens it.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import time

from .codex import authfile

FOLDER = "accounts"
SUFFIX = ".dat"
INTENT = "switch.intent"
LAST = "switch.last"
# When the last switches were made (v0.6.23 audit A-R2): the 24-hour ceiling counts these, not a calendar day's.
TIMES = "switch.times"
# When the card's Read usage last began (v0.6.22 final): it reads at most once every ten minutes.
READS = "usage.read"
_ID = re.compile(r"^[0-9a-f]{16}$")
# A profile's state word (the card's): ready to be switched to, at its limit until a time, or needing a fresh sign-in.
READY, EXHAUSTED, NEEDS_SIGN_IN, DAMAGED = "ready", "exhausted", "needs_sign_in", "damaged"
STATES = (READY, EXHAUSTED, NEEDS_SIGN_IN, DAMAGED)
# The most profiles a person may keep.
MOST = 8
# Seconds a save, a delete or a profile's update waits for the saved accounts' lock (`locked`).
LOCK_SECONDS = 5.0
# Seconds keeping a copy Codex refreshed on a scratch home waits for it: as long as core's Mutex allows (it caps at 60).
# A switch holds the lock through a whole app restart, and a refreshed copy not kept may leave only a spent one (the
# review's finding 15).
KEEP_SECONDS = 60.0


WINDOWS = ("five_hour", "weekly")


def _whole(value):
    return value if type(value) is int else None


def _window(value):
    if not isinstance(value, dict):
        return None
    used, resets = value.get("used"), value.get("resets_at")
    if type(used) not in (int, float) or used != used or not 0 <= used <= 10000:
        return None
    return {"used": used, "resets_at": _whole(resets)}


def reading(value):
    """A kept usage reading as it is read back - {read_at, available, most_used, five_hour, weekly}, each window
    {used, resets_at} or None - or None for anything that is not exactly one (a hand-edited or damaged value is none)."""
    if not isinstance(value, dict) or type(value.get("read_at")) is not int:
        return None
    most = value.get("most_used")
    available = value.get("available")
    return {"read_at": value["read_at"], "available": available if type(available) is bool else None,
            "most_used": most if type(most) in (int, float) and most == most else None,
            **{name: _window(value.get(name)) for name in WINDOWS}}


class ProfileError(OSError):
    """A profile that cannot be saved, read or found."""


def digest(data) -> str:
    """A sign-in file's bytes as the intent keeps them for comparison: sha256, hex."""
    import hashlib
    return hashlib.sha256(bytes(data)).hexdigest()


class Locked(ProfileError):
    """Another switch, put-back, save or delete holds the saved accounts - in this process or another."""


def _mutex(directory, seconds):
    """One named mutex for the saved accounts of one product home, across every process of the person's (the watcher,
    the bridge, a measurement's hand): core's win/sync.Mutex, which an abandoned holder releases."""
    from codex_auto_resume.win.sync import Mutex
    return Mutex("account-switch:" + os.path.normcase(str(Path(directory).absolute())), timeout=seconds)


def _seal(data):
    from .win.dpapi import protect
    return protect(data)


def _open(blob):
    from .win.dpapi import unprotect
    return unprotect(blob)


class Profiles:
    """The profiles under `home` (the product's home). `seal` and `open_` are Windows' data protection, or a test's."""

    def __init__(self, home, *, seal=None, open_=None, clock=None, lock=None):
        self.directory = Path(home) / FOLDER
        self._seal = seal or _seal
        self._open = open_ or _open
        self._clock = clock or time.time
        self._lock = lock or _mutex

    @contextmanager
    def locked(self, seconds=LOCK_SECONDS):
        """The saved accounts held for one switch, put-back, save or delete (the security review's finding 7: the intent
        had no owner, so a measurement's hand beside an armed watcher, or the bridge's save beside a switch, raced).
        Locked where another holds them after `seconds`. The same thread may take it again inside."""
        try:
            held = self._lock(self.directory, seconds)
            held.__enter__()
        except Exception:
            raise Locked("the saved accounts are held") from None
        try:
            yield
        finally:
            held.__exit__(None, None, None)

    # ------------------------------------------------------------------ sealed files
    def _write(self, name, value) -> None:
        authfile.own_folder(self.directory)
        authfile.write_atomic(self.directory / name, self._seal(json.dumps(value, sort_keys=True).encode("utf-8")))

    def _read(self, name):
        if not authfile.confined(self.directory):
            raise ProfileError("the saved accounts folder is a link")
        try:
            blob = (self.directory / name).read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            raise ProfileError("a profile cannot be read") from None
        try:
            value = json.loads(self._open(blob).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            raise ProfileError("a profile cannot be opened") from None
        if not isinstance(value, dict):
            raise ProfileError("a profile cannot be opened")
        return value

    def _remove(self, name) -> bool:
        if not authfile.confined(self.directory):
            return False                                     # never through a link at the folder
        try:
            (self.directory / name).unlink()
            return True
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------ profiles
    def ids(self) -> list:
        if not authfile.confined(self.directory):
            return []
        try:
            names = sorted(path.name for path in self.directory.iterdir())
        except OSError:
            return []
        return [name[:-len(SUFFIX)] for name in names if name.endswith(SUFFIX) and _ID.match(name[:-len(SUFFIX)])]

    def get(self, profile_id) -> dict:
        """A profile whole - {id, auth (bytes), email, plan, saved_at, used_at, exhausted_until, failed_at}."""
        if not isinstance(profile_id, str) or not _ID.match(profile_id):
            raise ProfileError("no such profile")
        value = self._read(profile_id + SUFFIX)
        if value is None:
            raise ProfileError("no such profile")
        try:
            value["auth"] = authfile.check(base64.b64decode(value.get("auth", ""), validate=True))
        except (ValueError, OSError):
            raise ProfileError("a profile cannot be opened") from None
        value["id"] = profile_id
        return value

    def find(self, email):
        """The id of the profile saved for `email` (any case), or None."""
        wanted = email.lower() if isinstance(email, str) else None
        for profile_id in self.ids():
            try:
                found = self.get(profile_id)
            except ProfileError:
                continue
            if wanted and isinstance(found.get("email"), str) and found["email"].lower() == wanted:
                return profile_id
        return None

    def save(self, data, email, plan) -> str:
        """Keep `data` (a sign-in file's bytes) as the profile of `email`, replacing that account's earlier copy: its id."""
        authfile.check(data)
        if not isinstance(email, str) or "@" not in email:
            raise ProfileError("an account is saved by its address")
        profile_id = self.find(email)
        if profile_id is None:
            if len(self.ids()) >= MOST:
                raise ProfileError("too many profiles")
            profile_id = secrets.token_hex(8)
            kept = {}
        else:
            kept = self.get(profile_id)
        # Its last usage reading, and when it was last found signed in, are kept with a copy saved again.
        record = {"auth": base64.b64encode(bytes(data)).decode("ascii"), "email": email, "plan": plan,
                  "saved_at": int(self._clock()), "used_at": kept.get("used_at"),
                  "exhausted_until": None, "failed_at": None, "usage": kept.get("usage"),
                  "unread_at": kept.get("unread_at"), "seen_at": kept.get("seen_at")}
        self._write(profile_id + SUFFIX, record)
        return profile_id

    def update(self, profile_id, **fields) -> None:
        """Change a profile's times (used_at, exhausted_until, failed_at, unread_at, seen_at), its last usage reading
        (usage, `reading`'s shape) or its sign-in file (auth, bytes)."""
        found = self.get(profile_id)
        for key, value in fields.items():
            if key not in ("used_at", "exhausted_until", "failed_at", "auth", "plan", "usage", "unread_at", "seen_at"):
                raise ProfileError("not a profile's field")
            found[key] = value
        found["auth"] = base64.b64encode(authfile.check(found["auth"])).decode("ascii")
        found.pop("id", None)
        self._write(profile_id + SUFFIX, found)

    def delete(self, profile_id) -> bool:
        if not isinstance(profile_id, str) or not _ID.match(profile_id):
            return False
        return self._remove(profile_id + SUFFIX)

    def delete_all(self, codex_home=None) -> int:
        """Every saved account taken away, and with them the intent, the last switch's stamp, and whatever plain sign-in
        file a kill left (authfile.sweep: every scratch home, whatever its age). How many accounts went."""
        gone = sum(self.delete(profile_id) for profile_id in self.ids())
        self._remove(INTENT)
        self._remove(LAST)
        authfile.sweep(self.directory, codex_home, stale=0)
        return gone

    def state(self, found, now=None) -> str:
        now = self._clock() if now is None else now
        if found.get("failed_at"):
            return NEEDS_SIGN_IN
        until = found.get("exhausted_until")
        return EXHAUSTED if isinstance(until, (int, float)) and until > now else READY

    def view(self) -> list:
        """What a person may see of each profile: {id, mask, plan, state} - the address only masked - with its last usage
        reading (`usage`, or None), whether a read of it broke after that reading (`unread`), and the times the card
        tells the account in use and the next candidate by (seen_at, used_at)."""
        from .codex.account import mask
        shown = []
        for profile_id in self.ids():
            try:
                found = self.get(profile_id)
            except ProfileError:
                shown.append({"id": profile_id, "mask": None, "plan": None, "state": DAMAGED, "usage": None,
                              "unread": False, "seen_at": None, "used_at": None})
                continue
            usage = reading(found.get("usage"))
            unread = found.get("unread_at")
            shown.append({"id": profile_id, "mask": mask(found.get("email")), "plan": found.get("plan"),
                          "state": self.state(found), "usage": usage,
                          "unread": type(unread) is int and (usage is None or unread >= usage["read_at"]),
                          "seen_at": _whole(found.get("seen_at")), "used_at": _whole(found.get("used_at"))})
        return shown

    def read_now_at(self):
        """When the card's Read usage last began (whole seconds), or None."""
        try:
            found = self._read(READS)
        except ProfileError:
            return None
        return _whole(found.get("at")) if isinstance(found, dict) else None

    def note_read_now(self, at) -> None:
        self._write(READS, {"at": int(at)})

    # ------------------------------------------------------------------ a switch under way, and the last one
    def intent(self):
        try:
            return self._read(INTENT)
        except ProfileError:
            return {"damaged": True}

    def begin(self, source, target, step="swap", tries=0, *, put_in=None, previous=None, to_email=None) -> None:
        """A switch under way from `source` to `target`; `step` "back" once only the previous file's return is left,
        `tries` the restarts made for it since. For a put-back (v0.6.23 audit A-R5) the intent carries what it needs
        without either profile - the digest of the copy put in, the previous copy itself and the target's address - so
        deleting the account set aside, or the previous one, no longer cancels it. The intent is sealed as profiles are."""
        value = {"from": source, "to": target, "at": int(self._clock()), "step": step, "tries": tries}
        if put_in is not None:
            value["put_in"] = put_in if isinstance(put_in, str) else digest(put_in)
        if previous is not None:
            value["previous"] = previous if isinstance(previous, str) else base64.b64encode(bytes(previous)).decode("ascii")
        if isinstance(to_email, str):
            value["to_email"] = to_email
        self._write(INTENT, value)

    def end(self) -> None:
        self._remove(INTENT)

    def last_switch_at(self):
        """When this capability last put another account in (`switch.last`), or None."""
        try:
            last = self._read(LAST)
        except ProfileError:
            return None
        at = last.get("at") if isinstance(last, dict) else None
        return at if type(at) is int else None

    def attempts(self):
        """The times of the last switches (whole seconds), or None where none was ever kept. Delete all keeps them: the
        day's ceiling is not freed by deleting the accounts."""
        try:
            found = self._read(TIMES)
        except ProfileError:
            return None
        times = found.get("times") if isinstance(found, dict) else None
        return [value for value in times if type(value) is int] if isinstance(times, list) else None

    def note_attempts(self, times) -> None:
        self._write(TIMES, {"times": [int(value) for value in times]})

    def mark_switched(self, email) -> None:
        self._write(LAST, {"email": email.lower(), "at": int(self._clock())})

    def switched_to(self, identity, after) -> bool:
        """Whether the account `identity` (account.identity's text) is the one this capability last put in, at or after
        `after` - a change account_switch's watch then does not hold recoveries for."""
        try:
            last = self._read(LAST)
        except ProfileError:
            return False
        return (isinstance(last, dict) and isinstance(identity, str) and last.get("email") == identity.lower()
                and isinstance(last.get("at"), int) and isinstance(after, (int, float)) and last["at"] >= after)

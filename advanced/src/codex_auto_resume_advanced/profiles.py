# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The person's saved Codex accounts (account_auto_switch, v0.6.22): each a copy of Codex's sign-in file, sealed.

A profile is one file, `<product home>\\accounts\\<id>.dat`: Windows' data protection for the current user
(win/dpapi.py) over a JSON object - the sign-in file's bytes (base64), the account's address and plan word as
account/read answered them, and when it was saved, last switched to, found exhausted until, and found unusable. Nothing
of it is in settings.json, the state, a log, the journal, diagnostics, a compatibility report or a statement; what
leaves this module for a person to see is `view`: an id, the address masked as the account card masks it, the plan
word and a closed state word. Delete takes the file away; Delete all takes every one. Turning the capability off keeps
them (the person saved them), and nothing reads them while it is off.

Two more sealed files sit beside them: `switch.intent` - a switch under way (from, to, step), so a crash in the middle is
finished or undone at the next look - and `switch.last` - the account a switch of this capability put in and when, so
account_switch's watch tells that change from one a person made (`switched_to`).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import secrets
import time

from .codex import authfile

FOLDER = "accounts"
SUFFIX = ".dat"
INTENT = "switch.intent"
LAST = "switch.last"
_ID = re.compile(r"^[0-9a-f]{16}$")
# A profile's state word (the card's): ready to be switched to, at its limit until a time, or needing a fresh sign-in.
READY, EXHAUSTED, NEEDS_SIGN_IN, DAMAGED = "ready", "exhausted", "needs_sign_in", "damaged"
STATES = (READY, EXHAUSTED, NEEDS_SIGN_IN, DAMAGED)
# The most profiles a person may keep.
MOST = 8


class ProfileError(OSError):
    """A profile that cannot be saved, read or found."""


def _seal(data):
    from .win.dpapi import protect
    return protect(data)


def _open(blob):
    from .win.dpapi import unprotect
    return unprotect(blob)


class Profiles:
    """The profiles under `home` (the product's home). `seal` and `open_` are Windows' data protection, or a test's."""

    def __init__(self, home, *, seal=None, open_=None, clock=None):
        self.directory = Path(home) / FOLDER
        self._seal = seal or _seal
        self._open = open_ or _open
        self._clock = clock or time.time

    # ------------------------------------------------------------------ sealed files
    def _write(self, name, value) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        authfile.write_atomic(self.directory / name, self._seal(json.dumps(value, sort_keys=True).encode("utf-8")))

    def _read(self, name):
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
        try:
            (self.directory / name).unlink()
            return True
        except FileNotFoundError:
            return False

    # ------------------------------------------------------------------ profiles
    def ids(self) -> list:
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
        record = {"auth": base64.b64encode(bytes(data)).decode("ascii"), "email": email, "plan": plan,
                  "saved_at": int(self._clock()), "used_at": kept.get("used_at"),
                  "exhausted_until": None, "failed_at": None}
        self._write(profile_id + SUFFIX, record)
        return profile_id

    def update(self, profile_id, **fields) -> None:
        """Change a profile's times (used_at, exhausted_until, failed_at) or its sign-in file (auth, bytes)."""
        found = self.get(profile_id)
        for key, value in fields.items():
            if key not in ("used_at", "exhausted_until", "failed_at", "auth", "plan"):
                raise ProfileError("not a profile's field")
            found[key] = value
        found["auth"] = base64.b64encode(authfile.check(found["auth"])).decode("ascii")
        found.pop("id", None)
        self._write(profile_id + SUFFIX, found)

    def delete(self, profile_id) -> bool:
        if not isinstance(profile_id, str) or not _ID.match(profile_id):
            return False
        return self._remove(profile_id + SUFFIX)

    def delete_all(self) -> int:
        gone = sum(self.delete(profile_id) for profile_id in self.ids())
        self._remove(INTENT)
        self._remove(LAST)
        return gone

    def state(self, found, now=None) -> str:
        now = self._clock() if now is None else now
        if found.get("failed_at"):
            return NEEDS_SIGN_IN
        until = found.get("exhausted_until")
        return EXHAUSTED if isinstance(until, (int, float)) and until > now else READY

    def view(self) -> list:
        """What a person may see of each profile: {id, mask, plan, state} - the address only masked."""
        from .codex.account import mask
        shown = []
        for profile_id in self.ids():
            try:
                found = self.get(profile_id)
            except ProfileError:
                shown.append({"id": profile_id, "mask": None, "plan": None, "state": DAMAGED})
                continue
            shown.append({"id": profile_id, "mask": mask(found.get("email")), "plan": found.get("plan"),
                          "state": self.state(found)})
        return shown

    # ------------------------------------------------------------------ a switch under way, and the last one
    def intent(self):
        try:
            return self._read(INTENT)
        except ProfileError:
            return {"damaged": True}

    def begin(self, source, target) -> None:
        self._write(INTENT, {"from": source, "to": target, "at": int(self._clock())})

    def end(self) -> None:
        self._remove(INTENT)

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

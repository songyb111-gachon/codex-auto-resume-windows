# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""What an administrator's policy allows, read from the registry and never written.

Three values under Software\\Policies\\CodexAutoResume, in the machine's hive and the user's:

    ForbidAdvanced       DWORD 1: no capability may be on or watched; every one reads as off
    ForceShadow          DWORD 1: a capability may be watched, never on; one that is on is watched
    AllowedCapabilities  REG_MULTI_SZ (or one string, split at commas, semicolons and spaces):
                         only these ids may be on or watched; a key without it allows every id

Both hives count, and together they are as strict as the stricter: forbidden or forced in
either is forbidden or forced, and two lists allow only the ids both hold. A value that is there
but is not what it should be - another type, a number that is not 0 or 1 - counts as the
strictest thing it could have meant, and so does a key that is there but cannot be read: a
policy that cannot be understood is never read as no policy.

A policy restricts; it never turns anything on and changes nothing stored. It is applied each
time a capability's state is read (arming.py), so a policy that is lifted leaves every
capability where the person had put it.

The key is opened for reading only, here and nowhere else in this edition
(advanced/tests/test_advanced_arming.py reads the package for a registry write). The reader is a
function a test hands in; the default one is Windows'.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re

KEY = r"Software\Policies\CodexAutoResume"
FORBID, FORCE_SHADOW, ALLOWED = "ForbidAdvanced", "ForceShadow", "AllowedCapabilities"
VALUES = (FORBID, FORCE_SHADOW, ALLOWED)
HIVES = ("HKLM", "HKCU")
# What a reader says a value is: its kind, or None for a value that is not there.
DWORD, TEXT, LIST, OTHER = "dword", "text", "list", "other"


class Unreadable(OSError):
    """The policy key is there and could not be read."""


@dataclass(frozen=True)
class Policy:
    forbid: bool = False
    force_shadow: bool = False
    allowed: frozenset | None = None     # None: no list, every id allowed

    def admits(self, capability) -> bool:
        """Whether `capability` may be on or watched at all under this policy."""
        return not self.forbid and (self.allowed is None or capability in self.allowed)

    def as_json(self) -> dict:
        return {"forbid": self.forbid, "force_shadow": self.force_shadow,
                "allowed": None if self.allowed is None else sorted(self.allowed)}


NONE = Policy()
STRICTEST = Policy(forbid=True, force_shadow=True, allowed=frozenset())


def _switch(found) -> bool | None:
    """A DWORD switch: None if absent, else whether it is on - anything but a DWORD 0 is on."""
    if found is None:
        return None
    value, kind = found
    return not (kind == DWORD and value == 0)


def _ids(found) -> frozenset | None:
    if found is None:
        return None
    value, kind = found
    if kind == LIST and isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        words = [word for item in value for word in re.split(r"[,;\s]+", item)]
    elif kind == TEXT and isinstance(value, str):
        words = re.split(r"[,;\s]+", value)
    else:
        return frozenset()
    return frozenset(word for word in words if word)


def read(reader=None) -> Policy:
    """The policy in force now. Never raises."""
    reader = reader or windows_reader
    forbid, force, allowed = False, False, None
    try:
        for hive in HIVES:
            found = {name: reader(hive, name) for name in VALUES}
            forbid = forbid or bool(_switch(found[FORBID]))
            force = force or bool(_switch(found[FORCE_SHADOW]))
            listed = _ids(found[ALLOWED])
            if listed is not None:
                allowed = listed if allowed is None else allowed & listed
    except Exception:
        return STRICTEST
    return Policy(forbid=forbid, force_shadow=force, allowed=allowed)


def windows_reader(hive, name):
    """(value, kind) of one policy value, None when it or its key is not there, and Unreadable
    when the key is there and cannot be read. Opened with KEY_READ and nothing else."""
    if os.name != "nt":
        return None
    import winreg
    root = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
    try:
        with winreg.OpenKey(root, KEY, 0, winreg.KEY_READ) as key:
            try:
                value, kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return None
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise Unreadable("the policy key could not be read") from exc
    kinds = {winreg.REG_DWORD: DWORD, winreg.REG_SZ: TEXT, winreg.REG_EXPAND_SZ: TEXT,
             winreg.REG_MULTI_SZ: LIST}
    return value, kinds.get(kind, OTHER)

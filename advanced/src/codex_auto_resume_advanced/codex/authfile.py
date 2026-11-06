# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Codex's sign-in file, for account_auto_switch alone (v0.6.22).

Every other part of the product never reads Codex's sign-in file, a token or a cookie (standard B11, and
codex/protocol.FORBIDDEN_METHODS, which stays as it is: nothing here asks Codex for a token). This capability departs
from that, and only it may: it copies `auth.json` into an encrypted profile (profiles.py) and puts another profile's
copy in its place. The bytes are never parsed for a token, logged, journalled or sent anywhere; the one check made on
them is that they are a JSON object of a bounded size, so a damaged copy is never written into Codex's home.

Codex keeps its sign-in in a file only where `cli_auth_credentials_store` (config.toml) is unset or "file" - its other
modes are keyring, auto (which may pick Windows' Credential Manager) and ephemeral (codex-cli 0.166's schema,
CliAuthCredentialsStoreMode). Anything but a file, or no file there, fails closed: `usable` says why, and nothing is
switched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

NAME = "auth.json"
CONFIG = "config.toml"
KEY = "cli_auth_credentials_store"
# The most a sign-in file may hold: a larger one is not one Codex writes, and is never copied.
LIMIT = 64 * 1024
# Why a home can or cannot be switched (closed words, the card's and the journal's).
USABLE, NOT_FILE, NO_FILE, UNREADABLE = "usable", "not_file", "no_file", "unreadable"
MODES = ("file", "keyring", "auto", "ephemeral")
# The names this capability makes, and nothing else is ever swept: a scratch home in the accounts folder, a temporary
# file beside a file it writes atomically (write_atomic), and that temporary beside Codex's own sign-in file.
_SCRATCH = re.compile(r"^scratch-[0-9a-f]{12}$")
_TEMPORARY = re.compile(r"^.+\.car-[0-9a-f]{8}$")
_BESIDE = re.compile(r"^auth\.json\.car-[0-9a-f]{8}$")
# Seconds: a scratch home older than this belongs to no read or sign-in any more (a sign-in waits ten minutes); a
# temporary file older than the other to no write.
SCRATCH_STALE = 1200
TEMPORARY_STALE = 60


class AuthFileError(OSError):
    """A sign-in file that cannot be read, is not one Codex writes, or could not be put in place."""


def store_mode(codex_home) -> str | None:
    """The `cli_auth_credentials_store` Codex's config at `codex_home` names - "file" where it names none - or None where
    the config cannot be read or names a mode Codex does not have."""
    import tomllib
    path = Path(codex_home) / CONFIG
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "file"
    except OSError:
        return None
    try:
        value = tomllib.loads(text).get(KEY, "file")
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    return value if value in MODES else None


def usable(codex_home) -> str:
    """USABLE where the sign-in at `codex_home` is a file this capability may copy and replace; otherwise why not."""
    mode = store_mode(codex_home)
    if mode is None:
        return UNREADABLE
    if mode != "file":
        return NOT_FILE
    return USABLE if (Path(codex_home) / NAME).is_file() else NO_FILE


def check(data) -> bytes:
    """`data` if it is a sign-in file's shape - a JSON object of at most LIMIT bytes - else AuthFileError."""
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= LIMIT:
        raise AuthFileError("not a sign-in file's size")
    try:
        parsed = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise AuthFileError("not a sign-in file") from None
    if not isinstance(parsed, dict) or not parsed:
        raise AuthFileError("not a sign-in file")
    return bytes(data)


def read(codex_home) -> bytes:
    """The sign-in file's bytes at `codex_home`, checked."""
    try:
        return check((Path(codex_home) / NAME).read_bytes())
    except OSError as error:
        if isinstance(error, AuthFileError):
            raise
        raise AuthFileError("the sign-in file cannot be read") from None


def write_atomic(path, data) -> None:
    """`data` at `path` whole or not at all: written beside it, flushed, then moved over it (one rename on one volume),
    so a crash leaves the old file or the new one, never half of either."""
    path = Path(path)
    temporary = path.with_name(path.name + ".car-" + secrets.token_hex(4))
    try:
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def replace(codex_home, data) -> None:
    """Put `data` (checked) in place as the sign-in file at `codex_home`, atomically."""
    try:
        write_atomic(Path(codex_home) / NAME, check(data))
    except AuthFileError:
        raise
    except OSError:
        raise AuthFileError("the sign-in file could not be put in place") from None


def own_folder(directory) -> None:
    """`directory` made where it is not, with the product's provenance marker in it - what lets uninstall's purge take
    the saved accounts folder whole (config.Paths.owned_account_files) - and, as it is first made ours, an access list
    of the current Windows user's alone, inherited by everything made in it (`private`): sealed copies and, for a
    moment, a scratch home's plain sign-in file live there."""
    from codex_auto_resume import config
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not confined(directory):
        raise AuthFileError("the saved accounts folder is a link")
    marker = directory / config.OWNER_MARKER
    if not marker.exists():
        try:
            marker.write_text(config.OWNER_TEXT, encoding="utf-8")
        except OSError:
            pass
        private(directory)


def confined(directory) -> bool:
    """Whether `directory` - the saved accounts folder - is no link or junction and resolves where it stands, under its
    own parent (the security review's finding 12: a junction there sent the sealed copies and the plain scratch homes
    outside). False where that cannot be told."""
    from codex_auto_resume.config import is_link
    directory = Path(directory)
    try:
        if is_link(directory):
            return False
        resolved = directory.resolve()
        return resolved.parent == directory.parent.resolve() and resolved.name.lower() == directory.name.lower()
    except (OSError, RuntimeError):
        return False


def _private_dacl(directory) -> bool:
    """`directory`'s access list replaced by one entry - the current Windows user, full control, inherited by every file
    and folder in it - and nothing inherited from above (the installer's rule for a home outside the profile, less
    SYSTEM and Administrators). Whether Windows took it; a drive that keeps no access list (FAT, exFAT) does not."""
    import ctypes
    from ctypes import wintypes
    from codex_auto_resume.win.acl import _own_sid
    sid = _own_sid()
    if not sid or not re.fullmatch(r"S-1-[0-9-]+", sid):
        return False
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
                         ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_named = advapi.SetNamedSecurityInfoW
    set_named.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p]
    set_named.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not convert("D:P(A;OICI;FA;;;%s)" % sid, 1, ctypes.byref(descriptor), None):
        return False
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present:
            return False
        # SE_FILE_OBJECT; DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        return set_named(str(directory), 1, 0x00000004 | 0x80000000, None, None, dacl, None) == 0
    finally:
        kernel.LocalFree(descriptor)


def private(directory) -> bool:
    """_private_dacl, never raising (a test replaces it: no test changes a real folder's access list)."""
    try:
        return bool(_PRIVATE(directory))
    except Exception:
        return False


_PRIVATE = _private_dacl


def _remove(entry) -> None:
    from codex_auto_resume.config import is_link
    if is_link(entry):
        try:
            os.unlink(entry)                                 # a link is taken away as a link, never entered
        except OSError:
            os.rmdir(entry)
        return
    if entry.is_dir():
        for child in list(entry.iterdir()):
            _remove(child)
        os.rmdir(entry)
        return
    try:
        os.unlink(entry)
    except PermissionError:
        os.chmod(entry, stat.S_IWRITE)
        os.unlink(entry)


def remove_tree(path) -> bool:
    """A folder this capability made, and everything in it, removed - no link or junction in it followed. Whether it is
    gone (a file something holds open stays, and is said)."""
    try:
        _remove(Path(path))
    except OSError:
        pass
    return not os.path.lexists(path)


def _age(path, now) -> float:
    try:
        return now - os.lstat(path).st_mtime
    except OSError:
        return -1.0


def sweep(directory, codex_home=None, *, now=None, stale=SCRATCH_STALE) -> tuple:
    """What a kill or a held file left of this capability's plain sign-in files, taken away: scratch homes in the saved
    accounts folder `directory` older than `stale` seconds, its write_atomic temporaries, and the temporary beside Codex's
    own sign-in file at `codex_home` - only names this capability makes, only directly in those two folders, nothing
    that is a link or a junction (nor through one). (removed, failed) - counts."""
    from codex_auto_resume.config import is_link
    now = time.time() if now is None else now
    removed = failed = 0
    places = [(Path(directory), True)] + ([(Path(codex_home), False)] if codex_home is not None else [])
    for folder, accounts in places:
        try:
            if is_link(folder) or not folder.is_dir():
                continue
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if is_link(entry):
                continue
            if accounts and _SCRATCH.match(name) and entry.is_dir():
                if _age(entry, now) < stale:
                    continue
                gone = remove_tree(entry)
            elif (_TEMPORARY.match(name) if accounts else _BESIDE.match(name)) and entry.is_file():
                if _age(entry, now) < min(stale, TEMPORARY_STALE):
                    continue
                try:
                    entry.unlink()
                except OSError:
                    pass
                gone = not os.path.lexists(entry)
            else:
                continue
            removed, failed = removed + gone, failed + (not gone)
    return removed, failed


class Scratch:
    """A private Codex home made for one read on a saved account (or Codex's own sign-in for a new one): a folder under
    the product's own accounts folder (never AppData - standard F3 kept), whose config keeps the sign-in in a file, and
    which holds `data` as its sign-in file where given. On leaving, the sign-in file there is kept in `after` - Codex
    may have refreshed its tokens, and the profile keeps the newer copy - and the folder is removed whatever happened,
    no link in it followed; `removed` says whether it went (one that did not is swept at a later look, `sweep`)."""

    def __init__(self, root, data=None):
        self.root = Path(root)
        self.data = data
        self.path = None
        self.after = None
        self.removed = None

    def __enter__(self):
        own_folder(self.root)
        self.path = self.root / ("scratch-" + secrets.token_hex(6))
        self.path.mkdir()
        if not confined(self.path):
            raise AuthFileError("a scratch home is a link")
        (self.path / CONFIG).write_text('%s = "file"\n' % KEY, encoding="utf-8")
        if self.data is not None:
            write_atomic(self.path / NAME, check(self.data))
        return self.path

    def __exit__(self, *_exc):
        try:
            self.after = read(self.path)
        except AuthFileError:
            self.after = None
        self.removed = remove_tree(self.path)
        if not self.removed:
            time.sleep(0.2)                                  # a child that has just ended may still hold a file
            self.removed = remove_tree(self.path)
        return False

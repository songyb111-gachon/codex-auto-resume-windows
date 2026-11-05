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
import secrets
import shutil

NAME = "auth.json"
CONFIG = "config.toml"
KEY = "cli_auth_credentials_store"
# The most a sign-in file may hold: a larger one is not one Codex writes, and is never copied.
LIMIT = 64 * 1024
# Why a home can or cannot be switched (closed words, the card's and the journal's).
USABLE, NOT_FILE, NO_FILE, UNREADABLE = "usable", "not_file", "no_file", "unreadable"
MODES = ("file", "keyring", "auto", "ephemeral")


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
    the saved accounts folder whole (config.Paths.owned_account_files), and nothing else."""
    from codex_auto_resume import config
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / config.OWNER_MARKER
    if not marker.exists():
        try:
            marker.write_text(config.OWNER_TEXT, encoding="utf-8")
        except OSError:
            pass


class Scratch:
    """A private Codex home made for one read on a saved account (or Codex's own sign-in for a new one): a folder under
    the product's own accounts folder (never AppData - standard F3 kept), whose config keeps the sign-in in a file, and
    which holds `data` as its sign-in file where given. On leaving, the sign-in file there is kept in `after` - Codex
    may have refreshed its tokens, and the profile keeps the newer copy - and the folder is removed whatever happened."""

    def __init__(self, root, data=None):
        self.root = Path(root)
        self.data = data
        self.path = None
        self.after = None

    def __enter__(self):
        own_folder(self.root)
        self.path = self.root / ("scratch-" + secrets.token_hex(6))
        self.path.mkdir()
        (self.path / CONFIG).write_text('%s = "file"\n' % KEY, encoding="utf-8")
        if self.data is not None:
            write_atomic(self.path / NAME, check(self.data))
        return self.path

    def __exit__(self, *_exc):
        try:
            self.after = read(self.path)
        except AuthFileError:
            self.after = None
        shutil.rmtree(self.path, ignore_errors=True)
        return False

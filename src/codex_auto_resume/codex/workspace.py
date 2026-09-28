"""The one file of a conversation's folder that is ever read: its git HEAD, as a digest (v0.6.11).

Read only for the task-changed guard (guards.py), which is off by default, and only as a file - git is
never started (standard F6), and nothing is written. `.git/HEAD` names the branch a folder is on, or the
commit it has checked out; a worktree's `.git` is a file naming the folder that holds its HEAD, which is
followed once. At most a few kilobytes are read, a link is never followed, and a folder named by a
share path (`\\\\server\\share`) is not read at all. A folder on a drive letter is read as Codex itself
reads it; this module opens no connection of its own (standard C1).

The answer is a word or a digest: "none" for a folder that is no git checkout, "unreadable" for one that
cannot be read, or the SHA-256 of the HEAD file's bytes. The bytes themselves - a branch name - never
leave this module.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

MAX_HEAD_BYTES = 4096
NONE, UNREADABLE = "none", "unreadable"


def _local_folder(text):
    """A local, absolute folder, or None: no extended-path prefix, no share, nothing that is not a path."""
    if not isinstance(text, str) or not text.strip() or any(c in text for c in "\r\n\x00"):
        return None
    plain = text.strip()
    if plain.startswith("\\\\?\\"):
        plain = plain[4:]
        if plain.upper().startswith("UNC\\"):
            return None
    plain = plain.replace("/", "\\")
    if plain.startswith("\\\\") or not os.path.isabs(plain):
        return None
    return Path(plain)


def _small_file(path: Path):
    """The bytes of a regular file of at most MAX_HEAD_BYTES that is not a link, or None."""
    try:
        found = os.lstat(path)
        if not stat.S_ISREG(found.st_mode) or found.st_size > MAX_HEAD_BYTES:
            return None
        with open(path, "rb") as stream:
            data = stream.read(MAX_HEAD_BYTES + 1)
    except (OSError, ValueError):
        return None
    return data if len(data) <= MAX_HEAD_BYTES else None


def _git_folder(folder: Path):
    """The folder that holds this checkout's HEAD: `.git` itself, or the one a worktree's `.git` file
    names. NONE for a folder with no `.git`, None for one that cannot be read."""
    marker = folder / ".git"
    try:
        found = os.lstat(marker)
    except FileNotFoundError:
        return NONE
    except (OSError, ValueError):
        return None
    if stat.S_ISDIR(found.st_mode):
        return marker
    if not stat.S_ISREG(found.st_mode):
        return None
    data = _small_file(marker)
    if data is None:
        return None
    try:
        line = data.decode("utf-8").splitlines()[0].strip() if data.strip() else ""
    except UnicodeError:
        return None
    if not line.startswith("gitdir:"):
        return None
    target = line[len("gitdir:"):].strip()
    if not target or target.replace("/", "\\").startswith("\\\\"):
        return None
    return _local_folder(target) if os.path.isabs(target) else _local_folder(str(folder / target))


def head_digest(cwd) -> str:
    """NONE, UNREADABLE, or the SHA-256 of the HEAD of the checkout `cwd` is in."""
    folder = _local_folder(cwd)
    if folder is None:
        return UNREADABLE
    holder = _git_folder(folder)
    if holder == NONE:
        return NONE
    if holder is None:
        return UNREADABLE
    data = _small_file(Path(holder) / "HEAD")
    return UNREADABLE if data is None else hashlib.sha256(data).hexdigest()

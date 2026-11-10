"""The Codex homes a watcher is set to watch beside the default one (v0.6.15-beta), as Settings keep them.

The default home is what it always was: `--codex-home`, else CODEX_HOME, else %USERPROFILE%\\.codex
(config.codex_home). Up to MAX_EXTRA more are named in the settings' `codex_homes`, each a folder and an
alias of its own - 1 to 32 characters on one line, which Pending, History and the panel show beside a
record of that home when there are several. Written only in the Dashboard (control/policy.py; MCP's
update_settings refuses the field whatever its schema says, mcp/server.py).

A home is keyed by the SHA-256 of its resolved, case-folded path - the name its lock has had since v0.6.0
(win/homelock.py) and the `home_key` its records carry (state schema 5). Its folder's identity, which no
spelling changes (win/folderid.py), is asked by the callers that may do I/O, never here: two configured
homes that are one folder are refused when they are written (`strict`), and a watcher watches one folder
once (runtime/homes.py).

Pure but for `key` (Path.resolve) and `problem`, which look at the folder; the identity is handed in.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PureWindowsPath
import re

FIELD = "codex_homes"
MAX_EXTRA = 3
ALIAS_MAX = 32
PATH_MAX = 260
_STATE_DB = re.compile(r"^state_[0-9]{1,6}\.sqlite$")

# Why a folder cannot be a Codex home to watch, in the words a refusal uses.
UNC, LINK, MISSING, NO_STATE = "unc", "link", "missing", "no_state"
PROBLEMS = {UNC: "a network path (\\\\server\\share) is not watched",
            LINK: "the folder is a link or a junction; name the folder it points to",
            MISSING: "there is no such folder",
            NO_STATE: "the folder holds no Codex state (state_<N>.sqlite)"}


def as_written(path) -> str:
    """A home's path as it is written, absolute and in one case: how Settings' entries and the suggested folders are told
    apart. It looks at no file, so it is the same whether or not the folder can be reached now, and a junction or a short
    8.3 name stays a spelling of its own. Which folder a path really is, is `key`'s question; which program a window
    runs is win/handover.spelled's."""
    return os.path.normcase(os.path.abspath(str(path)))


def key(path) -> str:
    """The key a Codex home is known by: SHA-256 of its resolved, case-folded path, as lowercase hex - the
    name its lock file has (win/homelock.py), and a record's `home_key` for any home but the default."""
    resolved = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _text(value, low, high) -> bool:
    return (isinstance(value, str) and low <= len(value) <= high
            and not any(ord(character) < 32 or ord(character) == 127 for character in value))


def _path_ok(value) -> bool:
    if not _text(value, 3, PATH_MAX):
        return False
    pure = PureWindowsPath(value)
    return bool(pure.is_absolute() and re.fullmatch(r"[A-Za-z]:", pure.drive or ""))


def _alias_ok(value) -> bool:
    return _text(value, 1, ALIAS_MAX) and value.strip() == value and bool(value.strip())


def well_formed(value) -> bool:
    """Whether `value` is a list of at most MAX_EXTRA {"path", "alias"}: a local absolute folder path and
    an alias of 1-32 characters with nothing around it, no two paths and no two aliases alike."""
    if not isinstance(value, list) or len(value) > MAX_EXTRA:
        return False
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"path", "alias"}:
            return False
        if not _path_ok(entry["path"]) or not _alias_ok(entry["alias"]):
            return False
    paths = {os.path.normcase(os.path.normpath(entry["path"])) for entry in value}
    aliases = {entry["alias"].casefold() for entry in value}
    return len(paths) == len(aliases) == len(value)


def coerce(value, default):
    """The settings' coercer: the list as it is, copied, when it is well formed - else the default (none).
    A hand-edited file cannot add a home in any other shape; Settings' strict write refuses one."""
    if not well_formed(value):
        return list(default)
    return [{"path": entry["path"], "alias": entry["alias"]} for entry in value]


def problem(path) -> str | None:
    """Why `path` cannot be watched as a Codex home now, as a word of PROBLEMS - or None. Looks at the
    folder: it exists, is not itself a link or a junction (F4), and holds a Codex state database."""
    text = str(path)
    if text.startswith(("\\\\", "//")):
        return UNC
    folder = Path(text)
    try:
        if folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction()):
            return LINK
        if not folder.is_dir():
            return MISSING
        if not any(_STATE_DB.match(child.name) and child.is_file() for child in folder.iterdir()):
            return NO_STATE
    except OSError:
        return MISSING
    return None


def strict(value, default_home, identity) -> None:
    """The Dashboard's write of `codex_homes`, refused in words a person can act on (ValueError): each
    home a folder that can be watched (`problem`), none the same folder as another or as the default
    home - asked by `identity`, the folder's id whatever its spelling (win/folderid.py)."""
    if not well_formed(value):
        raise ValueError("invalid value for codex_homes: at most %d homes, each a local folder and an alias "
                         "of 1 to %d characters, no two alike" % (MAX_EXTRA, ALIAS_MAX))
    seen = {}
    default_id = identity(default_home) if default_home is not None else None
    if default_id is not None:
        seen[default_id] = None
    for entry in value:
        found = problem(entry["path"])
        if found is not None:
            raise ValueError("invalid value for codex_homes: %s: %s" % (entry["alias"], PROBLEMS[found]))
        folder = identity(entry["path"])
        if folder is None:
            raise ValueError("invalid value for codex_homes: %s: %s" % (entry["alias"], PROBLEMS[MISSING]))
        if folder in seen:
            raise ValueError("invalid value for codex_homes: %s: that is the same folder as %s" % (
                entry["alias"], "the default Codex home" if seen[folder] is None else seen[folder]))
        seen[folder] = entry["alias"]


# MH - the Codex app run on a second home - passed on codex-cli 0.158.0-alpha.2.1 (2026-09-28) and again on
# codex-cli 0.162.0-alpha.17.2 (2026-10-10). On a Codex newer than 0.162 it is unproven until measured again, which
# Settings say beside the homes (the owner, 2026-10-09).
MEASURED = (0, 162)


def unmeasured(version) -> bool:
    """Whether a second home is unproven on the Codex in force: its version newer than MEASURED, or not known."""
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    return found is None or (int(found.group(1)), int(found.group(2))) > MEASURED


def view(configured, found, version, asked=True) -> dict:
    """What Settings show of the homes (control/watcher.py get_status, only while any is added): the default home and
    each added one - its alias, its folder, its key and what the watcher's last beat found of it (store/watcher.py
    homes) - and whether watching more than one is unproven on the Codex in force, never with the default home alone
    (`asked` False). Never handed to MCP: the folders are paths (mcp/server.py)."""
    states = {entry["key"]: entry["state"] for entry in (found or []) if isinstance(entry, dict)}
    listed = [{"key": "", "alias": None, "path": None, "state": states.get("", "watched")}]
    for entry in coerce(configured, []):
        try:
            name = key(entry["path"])
        except (OSError, ValueError, RuntimeError):
            name = None
        listed.append({"key": name, "alias": entry["alias"], "path": entry["path"], "state": states.get(name)})
    return {"homes": listed, "unmeasured": bool(asked) and unmeasured(version)}

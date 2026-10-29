r"""A Codex home this PC's Codex uses that the watcher does not watch yet, offered in the Dashboard (v0.6.18).

Suggested, never added: Settings > Advanced says "Codex also uses <folder>. Watch it too?" with Add, which
writes it through the one way a home is added (control/policy.py, homes.strict - at most homes.MAX_EXTRA, and
with every home full the line says so instead of offering), and Not now, which remembers the folder so it is
not offered again (DISMISSED). A switch turns the looking off (SWITCH, on by default, since it only offers).

Where it looks, and nowhere else:

* the CODEX_HOME variable of this Windows account, as Windows holds it for the programs it starts
  (HKEY_CURRENT_USER\Environment, read only - win/userenv.py, which the control layer hands in as
  `environment`: this module is below the adapters and reads no registry);
* the Codex app's own list of where it has run, which it writes for the browser extension it talks to:
  %LOCALAPPDATA%\OpenAI\Codex\chrome-native-hosts-v2.json - or the same file in the Codex app's package
  folder, where Windows keeps an MSIX app's writes. Read only, at most APP_FILE_MAX bytes, and only each
  entry's `paths.codexHome` is kept; nothing else in it is looked at or kept.

codex-cli keeps its config.toml inside the home it uses, so it names no other home. Never a process's command
line, its environment or its memory, never Codex's databases or another of its files (B11, B16).

Only an installed copy looks (config.installed_home, which the control layer hands in), as only an installed
copy asks for an administrator's policy keys (control/policy.py): a copy run from a checkout - the test suite -
finds nothing, so no test reads this machine's registry or Codex app. A test that means to look stands in for
`looks`.

A folder is offered only if it is one the product could watch (homes.problem: a local folder, not a link,
holding Codex's state), is not the default home or a home already added - by key, the resolved and
case-folded path every home is known by (homes.key), and by the folder's identity whatever its spelling
(win/folderid.py) - and was not set aside with Not now.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import homes

SWITCH = "home_suggestions"
DISMISSED = "home_suggestions_dismissed"
# The most folders Not now remembers; the oldest is let go first.
DISMISSED_MAX = 16
APP_FILE = ("OpenAI", "Codex", "chrome-native-hosts-v2.json")
# The Codex app's package, where Windows keeps what an MSIX app writes under LOCALAPPDATA.
APP_PACKAGE = ("Packages", "OpenAI.Codex_2p2nqsd0c76g0", "LocalCache", "Local")
APP_FILE_MAX = 1024 * 1024
# The most entries of that file looked at, and the most folders offered from all the places together.
APP_ENTRIES_MAX = 256
FOUND_MAX = 16


def _spelling(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _well_formed(path) -> bool:
    """A local absolute folder path a home may have (homes.well_formed's own check)."""
    return isinstance(path, str) and homes.well_formed([{"path": path, "alias": "home"}])


def coerce_dismissed(value, default):
    """The settings' coercer: the folders set aside, each a local absolute path, none twice, at most
    DISMISSED_MAX (the newest kept) - as they are when they are so, else the default (none)."""
    if not isinstance(value, list) or len(value) > DISMISSED_MAX:
        return list(default)
    if not all(_well_formed(path) for path in value):
        return list(default)
    if len({_spelling(path) for path in value}) != len(value):
        return list(default)
    return list(value)


def dismissed_with(stored, path) -> list:
    """The folders set aside once `path` is: added last, any other spelling of it dropped, the oldest let go
    past DISMISSED_MAX."""
    kept = [entry for entry in coerce_dismissed(stored, []) if _spelling(entry) != _spelling(path)]
    return (kept + [os.path.normpath(path)])[-DISMISSED_MAX:]


def app_homes(local_appdata=None) -> list:
    """Each `paths.codexHome` the Codex app's list of where it has run names, in its order: from its file under
    LOCALAPPDATA, else the same file in its package folder. Read only and capped; a file that is not there, is too
    big or is not that list answers nothing."""
    base = local_appdata if local_appdata is not None else os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    for place in (Path(base).joinpath(*APP_FILE), Path(base).joinpath(*APP_PACKAGE, *APP_FILE)):
        try:
            with open(place, "rb") as handle:
                raw = handle.read(APP_FILE_MAX + 1)
        except OSError:
            continue
        if len(raw) > APP_FILE_MAX:
            continue
        try:
            document = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
        entries = document.get("entries") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            continue
        found = []
        for entry in entries[:APP_ENTRIES_MAX]:
            paths = entry.get("paths") if isinstance(entry, dict) else None
            home = paths.get("codexHome") if isinstance(paths, dict) else None
            if isinstance(home, str) and home.strip():
                found.append(home.strip())
        return found
    return []


def looks(installed) -> bool:
    """Whether this copy looks at all: an installed one - `installed` is config.installed_home() - never a checkout."""
    return installed is not None


def found(environment=None, app=None, installed=None) -> list:
    """The folders the two places name - `environment`, the account's variable (win/userenv.py codex_home), first -
    each once (by spelling), at most FOUND_MAX, as named and not yet checked. Nothing where this copy does not look
    (`looks`). The app's list is looked up when asked (app_homes), so a test that stands in for it is asked instead."""
    if not looks(installed):
        return []
    environment = environment or (lambda: None)
    app = app or app_homes
    listed, seen = [], set()
    for path in [environment()] + list(app()):
        if not isinstance(path, str) or not path.strip():
            continue
        spelled = _spelling(path.strip())
        if spelled in seen:
            continue
        seen.add(spelled)
        listed.append(os.path.normpath(path.strip()))
    return listed[:FOUND_MAX]


def _key(path):
    try:
        return homes.key(path)
    except (OSError, ValueError, RuntimeError):
        return None


def candidates(values, default_home, named, identity=None) -> list:
    """Of `named` (found), each folder that may be offered: well formed, not set aside, one the product could
    watch (homes.problem), and neither the default home nor one already added - by key and, where `identity`
    is handed in, by the folder's identity."""
    added = homes.coerce((values or {}).get(homes.FIELD), [])
    taken = [default_home] + [entry["path"] for entry in added]
    keys = {_key(path) for path in taken if path is not None} - {None}
    ids = set()
    if identity is not None:
        for path in taken:
            try:
                ids.add(identity(path) if path is not None else None)
            except Exception:
                continue
        ids.discard(None)
    aside = {_spelling(path) for path in coerce_dismissed((values or {}).get(DISMISSED), [])}
    offered = []
    for path in named:
        if not _well_formed(path) or _spelling(path) in aside or homes.problem(path) is not None:
            continue
        name = _key(path)
        if name is None or name in keys:
            continue
        if identity is not None:
            try:
                folder = identity(path)
            except Exception:
                folder = None
            if folder is None or folder in ids:
                continue
            ids.add(folder)
        keys.add(name)
        offered.append(path)
    return offered


def on(values) -> bool:
    """Whether the switch lets it look (SWITCH): asked before anything is looked at."""
    return (values or {}).get(SWITCH, True) is not False


def offer(values, default_home, named, identity=None) -> dict:
    """What the Dashboard shows: whether it looks (`on`, the switch), the folder it offers or None, and whether
    every home is already added (`full`), when the line says so instead of offering Add."""
    values = values or {}
    if not on(values):
        return {"on": False, "path": None, "full": False}
    offered = candidates(values, default_home, named, identity)
    full = len(homes.coerce(values.get(homes.FIELD), [])) >= homes.MAX_EXTRA
    return {"on": True, "path": offered[0] if offered else None, "full": full}

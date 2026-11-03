"""Binding the configured Codex to exactly one Windows Store package, and the inventory it reads."""
from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess as S
import threading

from ..domain.errors import AdapterError
from ..win import authenticode
from ..win.inventory import resource_users
from ..win.kernel import NO_WINDOW, process_identity
from .paths import newest_generation


_INVENTORY_PS = r"""
$ErrorActionPreference='Stop'
# Windows PowerShell 5.1 emits the console OEM code page by default; force UTF-8 so
# non-ASCII executable paths (e.g. a non-ASCII user profile) survive the round-trip.
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
@(Get-CimInstance Win32_Process -Filter "Name = 'ChatGPT.exe' OR Name = 'codex.exe'" |
 ForEach-Object { [pscustomobject]@{
 pid=[int]$_.ProcessId; parent=[int]$_.ParentProcessId; path=$_.ExecutablePath
 } }) | ConvertTo-Json -Compress
"""


def inventory():
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = S.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", _INVENTORY_PS],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=15, creationflags=NO_WINDOW, check=True, shell=False)
        rows = json.loads(result.stdout) if result.stdout.strip() else []
        return rows if isinstance(rows, list) else [rows]
    except (OSError, S.SubprocessError, ValueError):
        raise AdapterError("process_inventory_unavailable") from None


# v0.6.21 (#58): the one signer whose signature makes a codex.exe outside the official folder official, compared
# exactly - the subject common name of the certificate on the engines OpenAI ships, in the app's package and in bin.
OPENAI_SIGNER = "OpenAI OpCo, LLC"
# Each file's answer by its path, size and modification time: a 369 MB engine is hashed once, not on every tick.
_OFFICIAL = {}
_OFFICIAL_LOCK = threading.Lock()


def at_official_location(path) -> bool:
    """Whether `path` is `%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hex>\\codex.exe`, the official, content-addressed folder."""
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI/Codex/bin"
    return bool(re.fullmatch(re.escape(str(local)) + r"\\[0-9a-f]+\\codex\.exe", str(path), re.I))


def official_engine(path) -> tuple:
    """Whether the codex.exe at `path` is an official Codex engine, and why: the one rule that the engine check
    (E1, codex/transport.py), discovery (through app_engines), the watcher's look for a moved engine
    (runtime/app.py) and the compatibility readers all ask.

    v0.6.21 (#58): official when it sits in the official folder (`at_official_location`, no file read) or when the
    file carries a valid Authenticode signature, chained to a root this PC trusts, whose signer is OpenAI
    (`OPENAI_SIGNER`) - the Codex app can run its engine from its own package. Returns (True, "official_location"),
    (True, "openai_signature") or (False, reason): `engine_unreadable`, `wrong_signer`, or the signature's own
    (win/authenticode.py). Never raises: anything that cannot be read is not official."""
    try:
        if at_official_location(path):
            return True, "official_location"
        text = str(path)
        found = os.stat(text)
    except (OSError, TypeError, ValueError):
        return False, "engine_unreadable"
    if not stat.S_ISREG(found.st_mode):
        return False, "engine_unreadable"
    key = (os.path.normcase(text), found.st_size, found.st_mtime_ns)
    with _OFFICIAL_LOCK:
        known = _OFFICIAL.get(key)
    if known is not None:
        return known
    try:
        answer = (True, "openai_signature") if authenticode.signer(text) == OPENAI_SIGNER else (False, "wrong_signer")
    except AdapterError as refused:
        answer = (False, str(refused))
    except Exception:
        answer = (False, "signature_unreadable")
    with _OFFICIAL_LOCK:
        if len(_OFFICIAL) >= 32:
            _OFFICIAL.clear()
        _OFFICIAL[key] = answer
    return answer


def _state_holder(servers, codex_home):
    """Of several same-path Codex children of the app main, the one holding Codex's state open.

    Codex 26.930's app starts a second `codex.exe` beside its app server - `exec-server` for a
    cloud environment - from the same binary under the same main, so path and parent no longer
    name the server (measured 2026-10-04 01:15: the app server held state_5, queue_1, logs_2
    and every thread-writer lock; the exec-server none of them). Who holds the newest-generation
    `queue_N.sqlite` or `state_N.sqlite` open - the generations `SchemaMixin.resolve` reads -
    is asked of the Restart Manager in one session, the one source of loaded state (B12); no
    command line, process memory or window is read. Exactly one candidate among their holders,
    or nothing: no home, neither database, the Restart Manager unavailable or failing, none or
    several candidates holding either - each fails closed, as two candidates always did.

    Either database, never both required: at 02:31 the same day the app server held queue_1
    and no process held state_5 - the app had closed its state database - so the state
    database alone left the recovery waiting again. The queue is the one `codex queue` writes
    a continuation into and the app server delivers from. A wrong choice cannot send either:
    `loaded()` still takes a conversation as the app's only when its writer lock's one holder
    is this pid and creation time.

    Returns (row, holder) - the holder's pid and creation time, which the caller holds the
    process's own identity to, so a reused pid fails closed.
    """
    if codex_home is None:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    try:
        databases = [path for path in (newest_generation(codex_home, kind) for kind in ("queue", "state"))
                     if path is not None]
        holders = resource_users(*databases) if databases else []
    except (AdapterError, OSError):
        raise AdapterError("desktop_server_missing_or_ambiguous") from None
    held = [(row, holder) for row in servers for holder in holders
            if isinstance(holder, dict) and holder.get("pid") == row.get("pid")]
    if len(held) != 1:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    return held[0]


def _app_main(rows):
    """The one Windows Store app main among the inventory's rows: the package's ChatGPT.exe whose
    parent is none of the package's own processes. None, or several, fails closed."""
    # Under WOW64 (32-bit Python on 64-bit Windows) ProgramFiles is the (x86) directory;
    # ProgramW6432 always holds the native one, where WindowsApps actually lives.
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    app_pattern = re.compile(re.escape(str(Path(program_files) / "WindowsApps")) +
                             r"\\OpenAI\.Codex_[0-9.]+_(x64|arm64)__2p2nqsd0c76g0\\app\\ChatGPT\.exe", re.I)
    apps = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
            and app_pattern.fullmatch(row["path"])]
    app_ids = {row["pid"] for row in apps}
    mains = [row for row in apps if row.get("parent") not in app_ids]
    if len(mains) != 1:
        raise AdapterError("desktop_main_missing_or_ambiguous")
    return mains[0]


def server_engines(rows) -> frozenset:
    """The image path of every codex.exe the one Windows Store app main runs as a child, as the
    inventory read it: a path and a parent, and nothing else of those processes - no command line
    and no process memory. None, or several, mains fail closed, as the pairing does.

    v0.6.13: what the watcher asks where the engine it found no longer names the app's server. A
    Codex update can start the app's server from a build in another bin/<hex> folder and leave the
    old one on disk, which then still passes every engine check (runtime/app.py, engine_moved).
    """
    main = _app_main(rows)
    return frozenset(row["path"] for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
                     and row.get("parent") == main["pid"]
                     and PureWindowsPath(row["path"]).name.lower() == "codex.exe")


def app_engines() -> frozenset:
    """`server_engines` of the processes running now: what discovery asks where more than one
    official build passes the engine checks (config.discover_codex_exe), and only then."""
    return server_engines(inventory())


def engines_instead(rows, codex_exe) -> frozenset:
    """The codex.exe paths the app main runs as children where none of them is `codex_exe`, and
    otherwise nothing: where the main runs `codex_exe`, runs no codex.exe, or is not exactly one."""
    try:
        served = server_engines(rows)
    except (AdapterError, KeyError, TypeError):
        return frozenset()
    held = str(codex_exe).lower()
    return frozenset() if any(path.lower() == held for path in served) else served


def _extension_engine(path) -> bool:
    """Whether `path` is a codex.exe of the VS Code extension's own (`%USERPROFILE%\\.vscode\\extensions\\
    openai.chatgpt-*\\...\\codex.exe`): compared here, and never kept."""
    profile = os.environ.get("USERPROFILE")
    if not profile or not isinstance(path, str):
        return False
    pattern = re.compile(re.escape(str(Path(profile) / ".vscode" / "extensions")) + r"\\openai\.chatgpt-[^\\]+\\(?:[^\\]+\\)*codex\.exe",
                         re.I)
    return bool(pattern.fullmatch(path))


def app_running(rows) -> bool:
    """Whether any process of the Codex app's package is among the inventory's rows (v0.6.16-beta.4): a main, a
    child, or several - what makes "Codex is closed" untrue even where no one main pairs."""
    try:
        _app_main(rows)
        return True
    except AdapterError as error:
        if str(error) != "desktop_main_missing_or_ambiguous":
            return True
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    root = str(Path(program_files) / "WindowsApps").lower() + "\\openai.codex_"
    return any(isinstance(row, dict) and isinstance(row.get("path"), str) and row["path"].lower().startswith(root)
               for row in rows)


# The app servers this process started and still holds (v0.6.16-beta.4): each one's pid and creation time, read from
# our own spawn while its handle is ours - so the pid cannot be reused under it - and never matched by name or path.
_OWN = set()
_OWN_LOCK = threading.Lock()


def own_server(pid):
    """Count `pid`, a process this one has just started and holds, as an app server of our own: its identity read now.
    The mark to hand `own_server_gone` when it is shut, or None where it could not be read (then it never counts)."""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        held = process_identity(pid)
    except (AdapterError, OSError, ValueError):
        return None
    mark = (held["pid"], held["created"])
    with _OWN_LOCK:
        _OWN.add(mark)
    return mark


def own_server_gone(mark) -> None:
    """The app server `own_server` counted, shut: it no longer counts."""
    with _OWN_LOCK:
        _OWN.discard(mark)


def own_holder(user) -> bool:
    """Whether the Restart Manager holder `user` is an app server this process started and still holds - the same pid
    AND creation time as at our spawn (`own_server`)."""
    if not isinstance(user, dict):
        return False
    with _OWN_LOCK:
        return (user.get("pid"), user.get("created")) in _OWN


def session_kind(rows, user, codex_exe) -> bool:
    """v0.6.16-beta.4: whether the one Restart Manager holder `user` of a conversation's writer lock is another Codex
    session - a terminal's TUI or the VS Code extension's server - rather than the app's, ours or anything unknown.

    Its inventory row, matched by pid, is a codex.exe that is either (a) the configured engine `codex_exe` run by
    neither the one app main nor this process (a TUI the app's bundled engine runs with --no-daemon, M5; our own
    headless app server is this process's child and never counts), or (b) the VS Code extension's own engine
    (`_extension_engine`); and the process is still that image, created when the holder says - a reused pid fails
    closed, as the app's server does. Anything else - another install, two rows, an unreadable path or a pid gone -
    is no. Paths are compared, never kept (D2)."""
    if not isinstance(user, dict) or not isinstance(rows, list):
        return False
    found = [row for row in rows if isinstance(row, dict) and row.get("pid") == user.get("pid")
             and isinstance(row.get("path"), str) and PureWindowsPath(row["path"]).name.lower() == "codex.exe"]
    if len(found) != 1 or found[0].get("parent") == os.getpid():
        return False
    row = found[0]
    try:
        main = _app_main(rows)["pid"]
    except (AdapterError, KeyError, TypeError):
        main = None
    configured = row["path"].lower() == str(codex_exe).lower() and row.get("parent") != main
    if not (configured or _extension_engine(row["path"])):
        return False
    try:
        held = process_identity(row["pid"])
    except (AdapterError, OSError):
        return False
    return held["path"] == row["path"].lower() and held["created"] == user.get("created")


def desktop_pair(rows, codex_exe, codex_home=None, require_holder=False):
    """Bind the configured official engine to exactly one Windows Store app main.

    The app's Codex server is the one child of that main running the configured engine; where
    the main has several such children, the one of them holding Codex's queue or state database
    in `codex_home` open (`_state_holder`), and without a `codex_home` none. With `require_holder`
    (v0.6.15-beta, a Codex home other than the default), even one such child must hold that home's
    database open: an app started on another home holds none of this one's, and its recoveries wait.
    """
    mains = [_app_main(rows)]
    servers = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
               and row["path"].lower() == str(codex_exe).lower() and row.get("parent") == mains[0]["pid"]]
    holder = None
    if len(servers) > 1 or (require_holder and servers):
        row, holder = _state_holder(servers, codex_home)
        servers = [row]
    if len(servers) != 1:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    app = process_identity(mains[0]["pid"])
    server = process_identity(servers[0]["pid"])
    if app["path"] != mains[0]["path"].lower() or server["path"] != str(codex_exe).lower():
        raise AdapterError("process_identity_changed")
    if holder is not None and holder.get("created") != server["created"]:
        raise AdapterError("process_identity_changed")
    if server["created"] < app["created"]:
        raise AdapterError("process_parent_identity_invalid")
    return {**app, "server": server}

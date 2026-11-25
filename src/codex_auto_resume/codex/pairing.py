"""Binding the configured Codex to exactly one Windows Store package, and the inventory it reads."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import re
import stat
import threading
import time

from ..domain.errors import AdapterError
from ..domain.ids import CODEX_APP_FAMILY, CODEX_APP_PUBLISHER
from ..win import authenticode
from ..win.inventory import resource_users
from ..win.kernel import package_roots, process_identity, processes_named
from .paths import newest_generation


# The two program files the inventory lists: the Codex app's (ChatGPT.exe) and every Codex engine's (codex.exe).
INVENTORY_NAMES = ("ChatGPT.exe", "codex.exe")
# v0.6.26 (update resilience #5): and every process of the Codex app's package family, whatever its file is called - a
# main or a helper an update renamed is still the app's (`app_process`).
INVENTORY_FAMILIES = (CODEX_APP_FAMILY,)
# v0.6.24 final: how long, in seconds, one process list answers every caller in this process. One status read asked for
# it nine times - each advanced capability's view binds the compatibility report to the engine the app serves - and
# each list was a PowerShell CIM query of about 10 s on the owner's PC: 90-105 s for one read, and a Dashboard that
# said it could not read the status. A few seconds is longer than one read and shorter than any pace that acts on what
# the list says (the watcher looks every 5 s, and holds each process it trusts to its own identity first); a caller
# that has just started or stopped a process, or is about to act on who runs, asks afresh (`forget_inventory`).
INVENTORY_SECONDS = 3.0
_LISTED = None                                  # (time.monotonic() when read, the rows), or None
_FORGOTTEN = 0                                  # how many times the list was forgotten: a read begun before is not kept
_LISTED_LOCK = threading.Lock()


def inventory():
    """Every ChatGPT.exe and codex.exe running, and (v0.6.26) every process of the Codex app's package family:
    {"pid", "parent", "path", "created", "family"} each (win/kernel.py processes_named) - the path and the creation time
    None where the process cannot be opened. No command line, no environment and no process memory are read. One list serves every caller for
    INVENTORY_SECONDS; each caller gets its own copy. Raises AdapterError("process_inventory_unavailable") where the
    list cannot be made.

    v0.6.24 final: read through one Toolhelp snapshot (win/kernel.py processes_named), no longer by PowerShell's
    Get-CimInstance Win32_Process: no process is started for it."""
    global _LISTED
    with _LISTED_LOCK:
        listed, forgotten = _LISTED, _FORGOTTEN
    if listed is not None and 0 <= time.monotonic() - listed[0] <= INVENTORY_SECONDS:
        return [dict(row) for row in listed[1]]
    try:
        rows = processes_named(INVENTORY_NAMES, INVENTORY_FAMILIES)
    except (AdapterError, OSError, ValueError):
        raise AdapterError("process_inventory_unavailable") from None
    with _LISTED_LOCK:
        if forgotten == _FORGOTTEN:
            _LISTED = (time.monotonic(), [dict(row) for row in rows])
    return rows


def forget_inventory() -> None:
    """The next `inventory` reads the processes afresh: for a caller that has just started or stopped one, or is about
    to act on who runs."""
    global _LISTED, _FORGOTTEN
    with _LISTED_LOCK:
        _LISTED, _FORGOTTEN = None, _FORGOTTEN + 1


# v0.6.21 (#58): the one signer whose signature makes a codex.exe outside the official folder official, compared
# exactly - the subject common name of the certificate on the engines OpenAI ships, in the app's package and in bin.
OPENAI_SIGNER = "OpenAI OpCo, LLC"
# Each file's answer by its path, size and modification time: a 369 MB engine is hashed once, not on every tick.
_OFFICIAL = {}
# v0.6.23 (audit C1): but an answer that can change while the file does not - the file held by an antivirus scanning
# a fresh engine (`signature_unreadable`), a chain whose certificate this PC has not cached yet (`signature_untrusted`)
# - is kept a minute only, so a check that failed once is asked again; every other answer is kept with the file.
PASSING = frozenset({"signature_unreadable", "signature_untrusted"})
PASSING_SECONDS = 60.0
_OFFICIAL_LOCK = threading.Lock()


def at_official_location(path) -> bool:
    """Whether `path` is `%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hex>\\codex.exe`, the official, content-addressed folder.
    Both are resolved first, as config.candidate_codex_exes resolves what it finds: a profile reached through a junction
    or a short 8.3 name is still the folder, and a <hex> that is a junction to somewhere else is not."""
    profile = os.environ.get("LOCALAPPDATA")
    if not profile:
        return False
    try:
        local, found = (Path(profile) / "OpenAI/Codex/bin").resolve(), Path(str(path)).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return bool(re.fullmatch(re.escape(str(local)) + r"\\[0-9a-f]+\\codex\.exe", str(found), re.I))


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
    if known is not None and (known[1] is None or 0 <= known[1] - time.monotonic() <= PASSING_SECONDS):
        return known[0]
    try:
        answer = (True, "openai_signature") if authenticode.signer(text) == OPENAI_SIGNER else (False, "wrong_signer")
    except AdapterError as refused:
        answer = (False, str(refused))
    except Exception:
        answer = (False, "signature_unreadable")
    with _OFFICIAL_LOCK:
        if len(_OFFICIAL) >= 32:
            _OFFICIAL.clear()
        _OFFICIAL[key] = (answer, time.monotonic() + PASSING_SECONDS if answer[1] in PASSING else None)
    return answer


def _database_holders(codex_home):
    """Who holds the home's newest-generation `queue_N.sqlite` or `state_N.sqlite` open - the generations
    `SchemaMixin.resolve` reads - asked of the Restart Manager in one session, the one source of loaded state (B12):
    each holder's pid and creation time, this process left out; nothing where neither database is there (a home that
    is not there has none). Raises AdapterError("desktop_server_missing_or_ambiguous") where it cannot be asked: no
    home given, a home that cannot be listed, the Restart Manager unavailable or failing - a pairing that needs the
    answer then fails closed."""
    if codex_home is None:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    try:
        try:
            databases = [path for path in (newest_generation(codex_home, kind) for kind in ("queue", "state"))
                         if path is not None]
        except (FileNotFoundError, NotADirectoryError):
            databases = []
        holders = resource_users(*databases) if databases else []
    except (AdapterError, OSError):
        raise AdapterError("desktop_server_missing_or_ambiguous") from None
    own = os.getpid()
    return [holder for holder in holders if isinstance(holder, dict) and holder.get("pid") != own]


def _held(rows, holders) -> list:
    """(row, holder) for each of `rows` the Restart Manager lists among `holders`, matched by pid."""
    return [(row, holder) for row in rows for holder in holders if holder.get("pid") == row.get("pid")]


def _state_holder(servers, codex_home, others=()):
    """Of several same-path Codex servers of the app main (`under_app`), the one holding Codex's state open.

    Codex 26.930's app starts a second `codex.exe` beside its app server - `exec-server` for a
    cloud environment - from the same binary under the same main, so path and parent no longer
    name the server (measured 2026-10-04 01:15: the app server held state_5, queue_1, logs_2
    and every thread-writer lock; the exec-server none of them). Who holds the newest-generation
    `queue_N.sqlite` or `state_N.sqlite` open is asked of the Restart Manager (`_database_holders`);
    no command line, process memory or window is read. Exactly one candidate among their holders,
    or nothing: no home, neither database, the Restart Manager unavailable or failing, none or
    several candidates holding either - each fails closed, as two candidates always did. v0.6.26
    (update resilience #2): so does another codex.exe the app runs (`others`, of another path)
    holding either - which of them is the server cannot be told.

    Either database, never both required: at 02:31 the same day the app server held queue_1
    and no process held state_5 - the app had closed its state database - so the state
    database alone left the recovery waiting again. The queue is the one `codex queue` writes
    a continuation into and the app server delivers from. A wrong choice cannot send either:
    `loaded()` still takes a conversation as the app's only when its writer lock's one holder
    is this pid and creation time.

    Returns (row, holder) - the holder's pid and creation time, which the caller holds the
    process's own identity to, so a reused pid fails closed.
    """
    holders = _database_holders(codex_home)
    held = _held(servers, holders)
    if len(held) != 1 or _held(others, holders):
        raise AdapterError("desktop_server_missing_or_ambiguous")
    return held[0]


def _windows_apps() -> Path:
    """The folder Store apps are installed in. Under WOW64 (32-bit Python on 64-bit Windows) ProgramFiles is the (x86)
    directory; ProgramW6432 always holds the native one, where WindowsApps actually lives."""
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    return Path(program_files) / "WindowsApps"


def _package_app(path) -> bool:
    """Whether `path` is a ChatGPT.exe of the Codex app's own Windows Store package: its main, or one of the package's
    other ChatGPT.exe processes (a renderer, a utility)."""
    app_pattern = re.compile(re.escape(str(_windows_apps())) + r"\\OpenAI\.Codex_[0-9.]+_(x64|arm64)__" +
                             CODEX_APP_PUBLISHER + r"\\app\\ChatGPT\.exe", re.I)
    return isinstance(path, str) and bool(app_pattern.fullmatch(path))


def _package_file(path) -> bool:
    """Whether `path` is a file anywhere in a folder of the Codex app's Windows Store package, whatever its version,
    architecture word or layout inside (v0.6.26, update resilience #5): `WindowsApps\\OpenAI.Codex_<...>__<publisher>\\`
    and at least one name below it, none of them `..`. Only Windows' own installer writes there."""
    if not isinstance(path, str) or ".." in path.split("\\"):
        return False
    pattern = re.compile(re.escape(str(_windows_apps())) + r"\\OpenAI\.Codex_[^\\]+__" + CODEX_APP_PUBLISHER +
                         r"(\\[^\\]+)+", re.I)
    return bool(pattern.fullmatch(path))


def _main_slot(path) -> bool:
    """Whether `path` is a file directly in the package's `app` folder, where its main is (`...\\app\\ChatGPT.exe`) -
    not in a folder below it, where the package keeps its own engine (`...\\app\\resources\\codex.exe`, #58)."""
    if not _package_file(path):
        return False
    pattern = re.compile(re.escape(str(_windows_apps())) + r"\\OpenAI\.Codex_[^\\]+__" + CODEX_APP_PUBLISHER +
                         r"\\app\\[^\\]+", re.I)
    return bool(pattern.fullmatch(path))


def engine_row(row) -> bool:
    """Whether the inventory row `row` may be a Codex engine: a process of a file called codex.exe, whatever its case,
    but not where the app's main is (`_main_slot`). v0.6.26 (fourth round A3): the package's `app\\Codex.exe` is its
    update trampoline (an OpenAI-signed program of 20 KB, not an engine) or a main an update renamed (review K7) - never
    paired as a server, counted among the engines the app serves, or run with --version as a candidate engine."""
    return (isinstance(row, dict) and isinstance(row.get("path"), str)
            and PureWindowsPath(row["path"]).name.lower() == "codex.exe" and not _main_slot(row["path"]))


def app_process(row) -> bool:
    """Whether the inventory row `row` is a process of the Codex app's own package - a main or a helper: a ChatGPT.exe
    of the package (`_package_app`), as always, or (v0.6.26, update resilience #5) any other file of the package's
    folder (`_package_file`) whose process Windows says is of the package's family (`CODEX_APP_FAMILY`, asked as
    win/kernel.py decide_host asks it) - a main or a helper an update renamed is still the app's. A process outside
    the package's folder never counts, whatever family it carries (a shell the app started may inherit it), and a
    file called codex.exe never does, whatever its case, but where the main is (`_main_slot`): an engine - the
    package's own among them (#58, in a folder below), which a terminal may run - is not one of the app's own
    processes, and a main renamed Codex.exe, the likeliest name for a package called OpenAI.Codex, still is (review
    K7)."""
    if not isinstance(row, dict) or not isinstance(row.get("path"), str):
        return False
    if PureWindowsPath(row["path"]).name.lower() == "codex.exe" and not _main_slot(row["path"]):
        return False
    if _package_app(row["path"]):
        return True
    family = row.get("family")
    return (isinstance(family, str) and family.casefold() == CODEX_APP_FAMILY.casefold()
            and _package_file(row["path"]))


# A row with no creation time at all: a list made before v0.6.26 (as many tests make one), not a time unread.
_UNTIMED = object()


def _born(row):
    """`row`'s creation time as the inventory read it (a FILETIME): an int, None where it could not be read, or
    _UNTIMED where the row carries no time at all."""
    if not isinstance(row, dict) or "created" not in row:
        return _UNTIMED
    value = row.get("created")
    return value if type(value) is int and value > 0 else None


def _started(parent, child, *, to_main) -> bool:
    """Whether the process of row `parent` can be the one that started the process of row `child` (v0.6.26, update
    resilience #2, closing audit-core C1): a parent created after its child is not its parent - Windows gave the dead
    parent's id to a later process - the rule win/kernel.py decide_host holds to. A time that could not be read
    fails. Rows that carry no time at all are taken as they always were only for the step that ends at the main,
    which desktop_pair holds to both processes' own identities; a step through a helper needs both times."""
    up, down = _born(parent), _born(child)
    if up is _UNTIMED or down is _UNTIMED:
        return to_main
    return up is not None and down is not None and up <= down


def _main_place(path) -> bool:
    """Whether `path` is where the app's main can be (v0.6.26, fourth round A1): directly in the package's `app` folder
    (`_main_slot`: its ChatGPT.exe, or a main an update renamed) or directly in the package's own folder (a renamed
    main moved up). The package's other programs sit in folders below `app` - its engine and tools in resources, the
    Chrome native host in plugins, node in cua_node - and are never a main."""
    if _main_slot(path):
        return True
    pattern = re.compile(re.escape(str(_windows_apps())) + r"\\OpenAI\.Codex_[^\\]+__" + CODEX_APP_PUBLISHER +
                         r"\\[^\\]+", re.I)
    return _package_file(path) and bool(pattern.fullmatch(path))


def app_mains(rows) -> list:
    """Every row that may be the Windows Store app main: a process of the app's package (`app_process`) where a main
    can be (`_main_place`) whose parent is none of the package's own processes - or (v0.6.26) whose listed package
    parent was created after it, so its own parent is gone. Pure; `_app_main` takes exactly one.

    v0.6.26 (fourth round A1): a package program of another folder is the app's only under a main (`under_app`), never
    a main itself. Measured 2026-11-23 with the app closed: the package's Chrome native host (an app execution alias,
    `...\\extension-host.exe`, of the package's family, started by cmd.exe for Chrome) was the inventory's one row and
    was read as the main - the app read as running when it was closed, and as two mains, every recovery waiting, when
    it was open."""
    apps = [row for row in rows if app_process(row)]
    by_pid = {}
    for row in apps:
        by_pid.setdefault(row["pid"], []).append(row)
    return [row for row in apps if _main_place(row["path"])
            and not any(_started(up, row, to_main=True) for up in by_pid.get(row.get("parent"), ()))]


def _app_main(rows):
    """The one Windows Store app main among the inventory's rows (`app_mains`). None, or several, fails closed."""
    mains = app_mains(rows)
    if len(mains) != 1:
        raise AdapterError("desktop_main_missing_or_ambiguous")
    return mains[0]


def under_app(rows, row, main) -> bool:
    """v0.6.25 (#67): whether the process `row` is one the app main whose pid is `main` runs itself: every process
    between them - none, or any number - is one of the app package's own processes (`app_process`: its ChatGPT.exe
    processes, and since v0.6.26 any other file of its folder of its family), as the inventory's rows list them. The
    one rule the pairing (`desktop_pair`), the served engines (`server_engines`) and the other-session test
    (`session_kind`) ask, so it cannot drift between them.

    Codex desktop 26.1117 starts its app server under the package's `--type=utility` ChatGPT.exe (NodeService), whose
    parent is the main, and its exec-server under the main itself; 26.930 started both under the main. Anything else
    in between - a terminal, a shell, another program's process, a codex.exe, a pid the rows do not list or list
    twice, a loop - is not the app's: a TUI started from a shell the app opened stays another session. v0.6.26 (update
    resilience #2, audit-core C1): nor is a step to a parent created after its child (`_started`): a shell that ended
    leaves its id to Windows, and a helper given that id later is not the parent of the TUI the shell started. Only
    ids, paths and creation times are read, as `inventory` lists them; whoever acts on the answer still holds each
    process to its own identity."""
    if not isinstance(row, dict):
        return False
    listed = {}
    for each in rows:
        if isinstance(each, dict):
            listed[each.get("pid")] = None if each.get("pid") in listed else each    # a pid listed twice is no one
    child, at, seen = row, row.get("parent"), set()
    while at not in seen:
        seen.add(at)
        up = listed.get(at)
        if at == main:
            return up is None or _started(up, child, to_main=True)
        if main is None or up is None or not app_process(up) or not _started(up, child, to_main=False):
            return False
        child, at = up, up.get("parent")
    return False


def server_engines(rows) -> frozenset:
    """The image path of every codex.exe the one Windows Store app main runs (`under_app`), as the
    inventory read it: a path and a parent, and nothing else of those processes - no command line
    and no process memory. None, or several, mains fail closed, as the pairing does.

    v0.6.13: what the watcher asks where the engine it found no longer names the app's server. A
    Codex update can start the app's server from a build in another bin/<hex> folder and leave the
    old one on disk, which then still passes every engine check (runtime/app.py, engine_moved).

    v0.6.21 (#58): the app can run its engine from its own package. Whoever reads these asks `official_engine` of
    each before it counts: discovery through the engine check (E1), the watcher in runtime/app.py `_served_elsewhere`
    and the compatibility readers in compat/probes.py `_served_engines`.

    v0.6.25 (#67): the main's children and those of the package's own ChatGPT.exe processes under it (`under_app`):
    Codex desktop 26.1117 runs its app server under the package's utility process.
    """
    main = _app_main(rows)
    return frozenset(row["path"] for row in rows if engine_row(row) and under_app(rows, row, main["pid"]))


def app_engines() -> frozenset:
    """`server_engines` of the processes running now: what discovery asks where more than one
    official build passes the engine checks, where none in the official folder does, or after the app was
    seen serving from another engine (config.discover_codex_exe), and only then."""
    return server_engines(inventory())


# How deep below a package's folder a codex.exe is looked for: `app\resources\codex.exe` is three names down (#58).
PACKAGE_ENGINE_DEPTH = 4


def package_engines() -> list:
    """Every file called codex.exe in the folders of the Codex app's package installed for this account
    (win/kernel.py package_roots), up to `PACKAGE_ENGINE_DEPTH` names below a folder, that may be an engine
    (`engine_row`, `_main_place`: not where the app's main can be, beside which its update trampoline sits) and is a
    file of the package's own folder in WindowsApps, as written and as resolved (`_package_file`): whether or not the
    app runs. Only folder names are read; nothing is opened, hashed or started, and whoever reads these asks
    `official_engine` of each, as it asks of `server_engines`. Nothing where the package manager cannot answer.

    v0.6.26 final (live acceptance R2b): the watcher takes up the engine the app runs from its package (#58) and keeps
    driving it after the app closes, for the file is still there. A compatibility reader bound the watcher's report
    only to an engine in bin or one the app runs now (compat/views.py `_binding_holds`), so with the app closed every
    reader - and the advanced edition's arming read the watcher makes itself - read every capability UNKNOWN, and held
    off every capability kept on that stands on Codex until the app opened again."""
    try:
        roots = package_roots(CODEX_APP_FAMILY)
    except (AdapterError, OSError):
        return []
    found = []
    for root in roots:
        level = [str(root)]
        for _depth in range(PACKAGE_ENGINE_DEPTH):
            below = []
            for folder in level:
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
                                below.append(entry.path)
                            elif entry.name.lower() == "codex.exe" and entry.is_file(follow_symlinks=False):
                                found.append(entry.path)
                except OSError:
                    continue
            level = below
    engines = []
    for path in found:
        try:
            resolved = str(Path(path).resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        if all(_package_file(each) and engine_row({"path": each}) and not _main_place(each)
               for each in (path, resolved)):
            engines.append(Path(resolved))
    return engines


def engines_instead(rows, codex_exe) -> frozenset:
    """The codex.exe paths the app main runs (`server_engines`) where none of them is `codex_exe`, and
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
    # v0.6.26 (fourth round A1): of the package's programs, its ChatGPT.exe and codex.exe, which v0.6.25 listed, and a
    # main an update renamed - never another program of its folders on its own (the Chrome native host Chrome keeps).
    root, names = str(_windows_apps()).lower() + "\\openai.codex_", {name.lower() for name in INVENTORY_NAMES}
    return any(isinstance(row, dict) and isinstance(row.get("path"), str) and row["path"].lower().startswith(root)
               and (PureWindowsPath(row["path"]).name.lower() in names or (app_process(row) and _main_place(row["path"])))
               for row in rows)


def app_running_now():
    """Whether any process of the Codex app's package runs now: True, False, or None where the process list could not be
    read. Each caller says what unknown means for it (advanced codex/swap: running; engine/opentarget: not known to be)."""
    try:
        return app_running(inventory())
    except Exception:
        return None


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
    forget_inventory()
    return mark


def own_server_gone(mark) -> None:
    """The app server `own_server` counted, shut: it no longer counts."""
    with _OWN_LOCK:
        _OWN.discard(mark)
    forget_inventory()


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
    headless app server is this process's child and never counts; v0.6.25 #67: the main runs it where `under_app`
    says so - a codex.exe under a shell or anything else but the package's own processes is still another
    session), or (b) the VS Code extension's own engine
    (`_extension_engine`); and the process is still that image, created when the holder says - a reused pid fails
    closed, as the app's server does. Anything else - another install, two rows, an unreadable path or a pid gone -
    is no. Paths are compared, never kept (D2)."""
    if not isinstance(user, dict) or not isinstance(rows, list):
        return False
    found = [row for row in rows if engine_row(row) and row.get("pid") == user.get("pid")]
    if len(found) != 1 or found[0].get("parent") == os.getpid():
        return False
    row = found[0]
    try:
        main = _app_main(rows)["pid"]
    except (AdapterError, KeyError, TypeError):
        main = None
    configured = row["path"].lower() == str(codex_exe).lower() and not under_app(rows, row, main)
    if not (configured or _extension_engine(row["path"])):
        return False
    try:
        held = process_identity(row["pid"])
    except (AdapterError, OSError):
        return False
    return held["path"] == row["path"].lower() and held["created"] == user.get("created")


def desktop_pair(rows, codex_exe, codex_home=None, require_holder=False, seen=None):
    """Bind the configured official engine to exactly one Windows Store app main.

    The app's Codex server is the one process of that main's running the configured engine - its
    child, or (v0.6.25, #67) the child of a package process under it (`under_app`); where
    the main has several such, the one of them holding Codex's queue or state database
    in `codex_home` open (`_state_holder`), and without a `codex_home` none. With `require_holder`
    (v0.6.15-beta, a Codex home other than the default), even one such child must hold that home's
    database open: an app started on another home holds none of this one's, and its recoveries wait.

    v0.6.26 (update resilience #2): on the default home too, one such child is asked of the Restart Manager
    (`_database_holders`). Where a Codex engine holds the home's newest queue or state database, the child must be
    one of its holders; and where another codex.exe the app runs (of another path) holds one, which is the server
    cannot be told - both fail closed, `desktop_server_missing_or_ambiguous`, as two children holding always did. Where
    no Codex engine holds either - the app had closed its state database, and the queue is not yet open - the one
    child is the server, as it always was. A Restart Manager that cannot be asked fails closed.

    `seen`, a dict where given, is told whether the paired server was among the holders (`server_holds`): what
    `session_kind`'s caller asks before it calls a conversation another session's (codex/transport.py).
    """
    main = _app_main(rows)
    engines = [row for row in rows if engine_row(row) and under_app(rows, row, main["pid"])]
    servers = [row for row in engines if row["path"].lower() == str(codex_exe).lower()]
    others = [row for row in engines if row["path"].lower() != str(codex_exe).lower()]
    holder = None
    if len(servers) > 1 or (require_holder and servers):
        row, holder = _state_holder(servers, codex_home, others)
        servers = [row]
    elif len(servers) == 1 and codex_home is not None:
        holders = _database_holders(codex_home)
        held = _held(servers, holders)
        codex_pids = {row.get("pid") for row in rows if engine_row(row)}
        if _held(others, holders) or (not held and any(each.get("pid") in codex_pids for each in holders)):
            raise AdapterError("desktop_server_missing_or_ambiguous")
        holder = held[0][1] if held else None
    if len(servers) != 1:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    app = process_identity(main["pid"])
    server = process_identity(servers[0]["pid"])
    if app["path"] != main["path"].lower() or server["path"] != str(codex_exe).lower():
        raise AdapterError("process_identity_changed")
    if holder is not None and holder.get("created") != server["created"]:
        raise AdapterError("process_identity_changed")
    if server["created"] < app["created"]:
        raise AdapterError("process_parent_identity_invalid")
    if isinstance(seen, dict):
        seen["server_holds"] = holder is not None
    return {**app, "server": server}

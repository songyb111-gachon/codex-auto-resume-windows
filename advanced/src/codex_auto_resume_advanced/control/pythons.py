# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Run this installation on another official Python (python_choice, v0.6.23): the card, its work, and how it is taken back.

What it offers: the newest final release of each line in LINES that has a Windows embeddable package, read live from
python.org (courier/pythonorg.offered) when a person presses Check, and the bundled runtime, always. A line in its
security-only phase publishes source alone, so the release before its newest is offered (3.13.17 beside 3.13.18 on
2026-11-11); a line with no such release at all is named on the card as one that cannot be chosen (`missing`). Nothing of a
version but its line is pinned here.

What `use` does, on a thread of the Dashboard's process, after the window asked first. Each step that fails deletes what
it unpacked, leaves the runtime in use alone and says which step it was (STEPS):

  download   the Windows embeddable package from the one exact address, its size bounded;
  digest     SHA-256 of the bytes kept on disk against what python.org published;
  unpack     into a new folder of its own, <home>\\runtimes\\<version>: flat, plain files of plain names, size bounded;
  signature  every *.exe, *.dll and *.pyd unpacked - python.exe, pythonw.exe and python3XX.dll among them - signed by
             the Python Software Foundation (Microsoft only on the Visual C++ runtime), as Windows judges (core's
             win/authenticode.py, the check #58 made for OpenAI's engine);
  import     for the first time, it runs: every shipped module imported under it, leaving no bytecode (pythoncheck.py);
  start      the record is written (chosen_runtime.py), and the watcher restarted; the launcher takes the record away by
             itself if it does not come up under that Python (scripts/watcher_launcher.py, `supervised` below).

Only the chosen runtime is kept: a previous one is deleted after a new one has succeeded (`_sweep`, also from each read of
the card, since a folder a running Dashboard or MCP server has open cannot go until they have ended).

Back to the bundled version (`back`) takes the record away first, and needs nothing of the chosen runtime. Turning the
capability off does the same (`back_when_off`). Nothing here touches Codex or sends anything to it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile

from codex_auto_resume import chosen_runtime
from codex_auto_resume.domain.plug import DEFER
from codex_auto_resume.domain.plugwords import Alternative
from codex_auto_resume.win import authenticode
from codex_auto_resume.domain.errors import AdapterError

from ..vocabulary import ArmingState, Refusal

CAPABILITY = "python_choice"
# The lines this version of the program may run under: a new line needs a release of the program. No patch is named.
LINES = ("3.13", "3.14", "3.15")
# Shown as a preview: the bundled runtime moves to it only in a later version.
PREVIEW = frozenset({"3.15"})
PYTHON_SIGNER = "Python Software Foundation"
# What must be signed before anything runs: every program file of the package (`_signed`). The Visual C++ runtime the
# package ships beside the interpreter is Microsoft's own: measured on 2026-11-13 on a python.org 3.13 installation, its
# vcruntime140.dll and vcruntime140_1.dll carry "Microsoft Windows Software Compatibility Publisher" and its 43 other
# *.exe, *.dll and *.pyd the Foundation's. Microsoft's names are taken for those files alone, the Foundation's as well.
SIGNED_KINDS = (".exe", ".dll", ".pyd")
VC_RUNTIME = re.compile(r"vcruntime140(?:_[0-9])?\.dll", re.IGNORECASE)
SIGNERS_OF_VC_RUNTIME = (PYTHON_SIGNER, "Microsoft Corporation", "Microsoft Windows Software Compatibility Publisher")
# The steps a person is told of, in the order they run.
LIST, SOURCE, DOWNLOAD, DIGEST, UNPACK, SIGNATURE, IMPORT, START = (
    "list", "source", "download", "digest", "unpack", "signature", "import", "start")
STEPS = (LIST, SOURCE, DOWNLOAD, DIGEST, UNPACK, SIGNATURE, IMPORT, START)
# What the job is doing now, for the card; and how it ended.
CHECKING, DOWNLOADING, VERIFYING, RESTARTING = "checking", "downloading", "verifying", "restarting"
CHOSEN_DONE, NEXT_START, BACK_DONE, FAILED = "chosen", "next_start", "back", "failed"
# What restarting the watcher came to (Hands.restart), beyond control.await_watcher's own words.
NOT_RUNNING, STILL_RUNNING, RUNNING = "not_running", "still_running", "running"
# The launcher's two questions (scripts/watcher_launcher.py) and the answer it carries out; why a choice was taken back.
PHASE_RUNTIME, PHASE_RUNTIME_FAILED, USE_CHOSEN = "runtime", "runtime_failed", Alternative.SUPERVISE
PHASES = frozenset({PHASE_RUNTIME, PHASE_RUNTIME_FAILED})
WHY_START, WHY_LINE, WHY_OFF = "start", "line", "off"
RETURNED = "returned.json"
INCOMING = ".incoming-"
NOTICE = "python_returned"
MEMBER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_+-]*(?:\.[A-Za-z0-9_+-]+)+", re.ASCII)
RESERVED = frozenset({"con", "prn", "aux", "nul"} | {"com%d" % n for n in range(1, 10)} | {"lpt%d" % n for n in range(1, 10)})
UNPACKED_MOST = 256 * 1024 * 1024           # bytes unpacked at most (2026-11-10: 23 MB for 3.14.10)
MEMBERS_MOST = 512
IMPORT_SECONDS = 180
VERSION_SECONDS = 15
# How long the Dashboard waits for the restart it asked for, before it takes the choice back itself. The launcher is the one
# that judges the chosen Python: it waits WATCHER_WAIT from its child's start, after its own question, and starts the bundled
# runtime after that. Its question took 41 and 48 s on the owner's PC on 2026-11-11 (LAUNCHER_ASKS_SEEN), before children
# that came up; with 90 s here, a child that came up after 43 of its 45 s would still have been taken back from here - a
# healthy start undone by the wrong clock. Twice the longest question seen and the whole wait: room for a bundled start too.
WATCHER_WAIT = 45.0                         # scripts/watcher_launcher.WATCHER_WAIT, control.WATCHER_START_TIMEOUT
LAUNCHER_ASKS_SEEN = 48.0
RESTART_SECONDS = 2 * (LAUNCHER_ASKS_SEEN + WATCHER_WAIT)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# What tells the launcher it was started to follow a stop (scripts/watcher_launcher.AFTER_STOP_MARK, kept there as this name).
AFTER_STOP_MARK = "CODEX_AUTO_RESUME_AFTER_STOP"
CODES = ("checked", "check_failed", "asked", "chosen", "next_start", "refused", "returned", "back")

_LOCK = threading.Lock()
_JOBS = {}                                  # {home: what is running now}
_OUTCOMES = {}                              # {home: how the last one ended}
_OFFERS = {}                                # {home: what Check found: [{"version", "line", "release"}]}
_BUNDLED = {}                               # {python.exe: (its mtime, its version)}


class _Failed(Exception):
    def __init__(self, step):
        self.step = step
        super().__init__(step)


class Hands:
    """What reaches outside this process, each in one place for a test to replace: python.org, Windows' judgement of a
    signature, the new interpreter, and the watcher."""

    @staticmethod
    def newest(lines):
        from ..courier import pythonorg
        return pythonorg.offered(lines)

    @staticmethod
    def embeddable(release, version):
        from ..courier import pythonorg
        return pythonorg.embeddable(release, version)

    @staticmethod
    def download(found, target, progress):
        from ..courier import pythonorg
        return pythonorg.download(found, target, progress=progress)

    @staticmethod
    def signer(path):
        return authenticode.signer(path)

    @staticmethod
    def imports(python, paths):
        return imports_under(python, paths)

    @staticmethod
    def restart(paths):
        return restart_watcher(paths)


class PythonChoice:
    """The action's object: nothing is asked of it at any point. Its card and buttons are `view`, `check`, `use`, `back`."""

    def __init__(self, paths):
        self.paths = paths


def make(paths) -> PythonChoice:
    return PythonChoice(paths)


def _home(runtime) -> Path:
    return Path(runtime.paths.home)


def _count(runtime, code) -> None:
    try:
        runtime.state.counted(CAPABILITY, code)
    except Exception:
        pass


def _refused(refusal) -> dict:
    return {"done": False, "refusal": Refusal(refusal)}


def _standing(runtime, capability) -> bool:
    return runtime.states(fresh=True).get(capability, ArmingState.OFF) in (ArmingState.ARMED, ArmingState.SHADOW)


def offered(runtime) -> bool:
    """Whether its buttons are: the capability on, and watched is not on."""
    try:
        return runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) == ArmingState.ARMED
    except Exception:
        return False


# ---------------------------------------------------------------------------- the card
def bundled_version(paths) -> str | None:
    """The version of the runtime this installation came with, asked of it once per file (`python.exe -V`)."""
    python = Path(paths.home) / chosen_runtime.BUNDLED / "python.exe"
    try:
        if Path(sys.executable).resolve() == python.resolve():
            return "%d.%d.%d" % sys.version_info[:3]
        stamp = python.stat().st_mtime_ns
        kept = _BUNDLED.get(python)
        if kept is not None and kept[0] == stamp:
            return kept[1]
        said = subprocess.run([str(python), "-I", "-V"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=VERSION_SECONDS,
                              creationflags=NO_WINDOW, stdin=subprocess.DEVNULL).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    found = re.fullmatch(r"Python (3\.[0-9]+\.[0-9]+)\s*", said or "")
    if found is None:
        return None
    _BUNDLED[python] = (stamp, found.group(1))
    return found.group(1)


def in_use(paths, bundled) -> str | None:
    """Which Python the running watcher is on, read from its own process; None where no watcher runs."""
    from codex_auto_resume.control import Control
    from codex_auto_resume.store import Store
    from codex_auto_resume.win.kernel import process_identity
    try:
        if Control(paths).watcher_running() is not True:
            return None
        store = Store(paths.state_dir, check=False)
        try:
            pid = (store.watcher_status() or {}).get("pid")
        finally:
            store.close()
        where = process_identity(pid)["path"]
    except Exception:
        return None
    found = re.search(r"\\runtimes\\(3\.[0-9]+\.[0-9]+)\\pythonw?\.exe$", where)
    return found.group(1) if found else bundled


def _returned(home) -> dict | None:
    try:
        with (chosen_runtime.root(home) / RETURNED).open("rb") as stream:
            found = json.loads(stream.read(chosen_runtime.RECORD_MOST).decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(found, dict) or found.get("why") not in (WHY_START, WHY_LINE, WHY_OFF):
        return None
    version = found.get("version")
    return {"why": found["why"], "version": version if chosen_runtime.shaped(version) else None}


def view(runtime) -> dict:
    """advanced-python: {bundled, chosen, in_use, button, checked, offers, missing, job, outcome, returned}. Reads this PC
    alone; python.org is asked only by `check`, after a person pressed it. `missing`: after a Check, the lines python.org
    has no release with a Windows embeddable package of. NOT_ON while the capability is off."""
    if not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    paths, home = runtime.paths, _home(runtime)
    bundled = bundled_version(paths)
    named = chosen_runtime.recorded(home)
    with _LOCK:
        job, outcome, offers = _JOBS.get(home), _OUTCOMES.get(home), _OFFERS.get(home)
        job = dict(job) if job else None
    if job is None:
        _sweep(home, named)
    return {"done": True, "refusal": None, "bundled": bundled, "chosen": named, "in_use": in_use(paths, bundled),
            "button": offered(runtime), "checked": offers is not None,
            "offers": [{"version": each["version"], "line": each["line"], "preview": each["line"] in PREVIEW}
                       for each in offers or ()],
            "missing": [] if offers is None else [line for line in LINES if line not in {each["line"] for each in offers}],
            "job": job, "outcome": dict(outcome) if outcome else None, "returned": _returned(home)}


def _begin(home, job) -> bool:
    with _LOCK:
        if home in _JOBS:
            return False
        _JOBS[home] = dict(job, got=0, total=0)
        _OUTCOMES.pop(home, None)
        return True


def _end(home, outcome) -> None:
    with _LOCK:
        _JOBS.pop(home, None)
        _OUTCOMES[home] = outcome


def _run(home, target, start, name) -> bool:
    """`target` on a thread of its own, however it ends leaving the job over; False where the thread could not start."""
    def guarded():
        try:
            target()
        except Exception:
            _end(home, {"word": FAILED, "step": START, "version": None})
    try:
        (start or (lambda job: threading.Thread(target=job, name=name, daemon=True).start()))(guarded)
    except Exception:
        _end(home, {"word": FAILED, "step": START, "version": None})
        return False
    return True


def check(runtime, *, start=None, hands=Hands) -> dict:
    """advanced-python-check: python.org's newest final release of each line that has a Windows embeddable package, on a
    thread of its own."""
    if not offered(runtime):
        return _refused(Refusal.NOT_ON)
    home = _home(runtime)
    if not _begin(home, {"stage": CHECKING, "version": None}):
        return _refused(Refusal.PYTHON_BUSY)

    def work():
        from ..courier import pythonorg
        try:
            found = hands.newest(LINES)
        except (pythonorg.Refused, OSError):
            _count(runtime, "check_failed")
            _end(home, {"word": FAILED, "step": LIST, "version": None})
            return
        offers = [{"version": found[line]["version"], "line": line, "release": found[line]["release"]}
                  for line in LINES if line in found]
        with _LOCK:
            _OFFERS[home] = offers
        _count(runtime, "checked")
        _end(home, None)
    if not _run(home, work, start, "python-check"):
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None}


def use(runtime, argument, *, start=None, hands=Hands) -> dict:
    """advanced-python-use {"version"}: one of the versions the last Check offered, and only those."""
    version = argument.get("version") if isinstance(argument, dict) else None
    if not offered(runtime):
        return _refused(Refusal.NOT_ON)
    home = _home(runtime)
    with _LOCK:
        offer = next((each for each in _OFFERS.get(home) or () if each["version"] == version), None)
    if offer is None or offer["line"] not in LINES or version == chosen_runtime.recorded(home):
        return _refused(Refusal.INVALID_REQUEST)
    if not _begin(home, {"stage": DOWNLOADING, "version": version}):
        return _refused(Refusal.PYTHON_BUSY)
    _count(runtime, "asked")

    def work():
        _end(home, _installed(runtime, offer, hands))
    if not _run(home, work, start, "python-use"):
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None}


def back(runtime, *, start=None, hands=Hands) -> dict:
    """advanced-python-back: the record taken away first, then the watcher restarted on the bundled runtime. Needs nothing
    of the chosen runtime, so it works however broken that is. Answered while the capability stands or a record does."""
    home = _home(runtime)
    if chosen_runtime.recorded(home) is None and not _standing(runtime, CAPABILITY):
        return _refused(Refusal.NOT_ON)
    if not _begin(home, {"stage": RESTARTING, "version": None}):
        return _refused(Refusal.PYTHON_BUSY)

    def work():
        _forget(home)
        _clear_returned(home)
        hands.restart(runtime.paths)
        _count(runtime, "back")
        _sweep(home, None)
        _end(home, {"word": BACK_DONE, "step": None, "version": None})
    if not _run(home, work, start, "python-back"):
        return _refused(Refusal.STATE_UNAVAILABLE)
    return {"done": True, "refusal": None}


def back_when_off(runtime, *, restart=True, start=None, hands=Hands) -> None:
    """The capability was turned off, and so nothing may stay on a chosen Python: as Back, but only where one is chosen.
    `restart` False (the Codex tool's path, a process that has no business restarting the watcher) leaves that to the
    watcher's next start."""
    try:
        home = _home(runtime)
        if chosen_runtime.recorded(home) is None or offered(runtime):
            return
        if restart:
            back(runtime, start=start, hands=hands)
        else:
            _forget(home)
    except Exception:
        pass


# ---------------------------------------------------------------------------- the launcher's question
def supervised(runtime, facts):
    """P13, for the launcher (scripts/watcher_launcher.py): PHASE_RUNTIME - USE_CHOSEN where the watcher is to run under the
    Python the record names, DEFER for the bundled one, a record no longer good being taken away here: on the line of a
    version this one no longer allows (after an update), or left by a capability that is off. PHASE_RUNTIME_FAILED - it
    did not come up: the record taken away and a person told, once. With no record nothing is read at all."""
    home = _home(runtime)
    phase = facts.get("phase")
    named = chosen_runtime.recorded(home)
    if named is None:
        return DEFER
    if phase == PHASE_RUNTIME_FAILED:
        _taken_back(runtime, named, WHY_START)
        return DEFER
    if phase != PHASE_RUNTIME:
        return DEFER
    if chosen_runtime.line_of(named) not in LINES:
        _taken_back(runtime, named, WHY_LINE)
        return DEFER
    if runtime.states(fresh=True).get(CAPABILITY, ArmingState.OFF) != ArmingState.ARMED:
        _taken_back(runtime, named, WHY_OFF, tell=False)
        return DEFER
    if chosen_runtime.chosen(home) is None:
        _taken_back(runtime, named, WHY_START)
        return DEFER
    return USE_CHOSEN


def _taken_back(runtime, version, why, *, tell=True, notify=None) -> None:
    home = _home(runtime)
    try:
        _write(chosen_runtime.root(home) / RETURNED, {"version": version, "why": why})
    except OSError:
        pass
    _forget(home)
    _count(runtime, "returned")
    if tell:
        try:
            (notify or returned_notice)(runtime.paths, version, why)
        except Exception:
            pass


def notice_content(version, why) -> dict:
    """The notice's words: which Python the watcher came back from, and why. Only a version's shape reaches them."""
    from codex_auto_resume import l10n, notify
    named = version if chosen_runtime.shaped(version) else "3"
    body = "toast_python_returned_line" if why == WHY_LINE else "toast_python_returned_start"
    return notify._content(l10n.message("toast_python_returned"), l10n.message(body).replace("{version}", named),
                           more=[(l10n.message("toast_button_open"), notify.open_uri("overview"))])


def returned_notice(paths, version, why) -> bool:
    """That the watcher is back on the bundled Python: core's notifier, as Windows' toast, under the notifications switch,
    as crash restart's notice is raised (engine/supervise.py). Whether it was shown."""
    from codex_auto_resume import config, l10n, notice_kinds, notifier, settings
    values = config.load_settings(paths)
    if not settings.notification_enabled(values, NOTICE):
        return False
    l10n.set_preference(values.get("interface_language"))
    notice = notifier.build(NOTICE, {"content": notice_content(version, why)}, destination=notifier.click_destination(values),
                            stay=notice_kinds.chosen(values))
    if notice is None:
        return False
    return bool(notifier.deliver(notice, inbox=None, setting=False)[1])


# ---------------------------------------------------------------------------- the work
def _installed(runtime, offer, hands) -> dict:
    """Everything `use` does: how it came out, for the card. Whatever fails leaves the current runtime in use."""
    home, version = _home(runtime), offer["version"]

    def failed(step):
        _count(runtime, "refused")
        return {"word": FAILED, "step": step, "version": version}
    root = chosen_runtime.root(home)
    incoming = root / (INCOMING + version + ".zip")
    target = chosen_runtime.folder(home, version)
    try:
        _ready(root)
        _prepared(incoming, target)
        _downloaded(offer, version, incoming, target, home, hands)
        _set_stage(home, VERIFYING)
        _unpack(incoming, target, version)
        _signed(target, version, hands)
        _imports(target, runtime.paths, hands)
    except _Failed as refused:
        _remove(target)
        _unlink(incoming)
        return failed(refused.step)
    except Exception:
        _remove(target)
        _unlink(incoming)
        return failed(UNPACK)
    _unlink(incoming)
    return _switched(runtime, version, target, hands, failed)


def _set_stage(home, stage) -> None:
    with _LOCK:
        if home in _JOBS:
            _JOBS[home]["stage"] = stage


def _downloaded(offer, version, incoming, target, home, hands) -> None:
    from ..courier import pythonorg

    def progress(got, total):
        with _LOCK:
            if home in _JOBS:
                _JOBS[home].update(got=got, total=total)
    try:
        found = hands.embeddable(offer["release"], version)
        hands.download(found, incoming, progress)
    except pythonorg.Refused as refused:
        raise _Failed(refused.step) from None
    except OSError:
        raise _Failed(DOWNLOAD) from None
    if _digest(incoming) != found["sha256"]:
        raise _Failed(DIGEST)


def _digest(path) -> str:
    made = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            piece = stream.read(1 << 20)
            if not piece:
                return made.hexdigest()
            made.update(piece)


def _unpack(archive, target, version) -> None:
    """Into a new folder of its own. Only flat, plain files of plain names, bounded in number and size, none of them twice,
    and every file the runtime cannot run without: anything else is refused before the first byte is written."""
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            _members_allowed(members, version)
            target.mkdir(parents=False, exist_ok=False)
            left = UNPACKED_MOST
            for member in members:
                with bundle.open(member) as source, open(target / member.filename, "xb") as sink:
                    while True:
                        piece = source.read(1 << 20)
                        if not piece:
                            break
                        left -= len(piece)
                        if left < 0:
                            raise _Failed(UNPACK)
                        sink.write(piece)
    except (OSError, ValueError, zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError):
        raise _Failed(UNPACK) from None


def _members_allowed(members, version) -> None:
    seen = set()
    total = 0
    if not 0 < len(members) <= MEMBERS_MOST:
        raise _Failed(UNPACK)
    for member in members:
        name = member.filename
        kind = stat.S_IFMT(member.external_attr >> 16)
        if (MEMBER.fullmatch(name) is None or member.is_dir() or kind not in (0, stat.S_IFREG)
                or name.split(".")[0].lower() in RESERVED or name.lower() in seen):
            raise _Failed(UNPACK)
        seen.add(name.lower())
        total += member.file_size
        if total > UNPACKED_MOST:
            raise _Failed(UNPACK)
    if not {name.lower() for name in chosen_runtime.required(version)} <= seen:
        raise _Failed(UNPACK)


def _signed(target, version, hands) -> None:
    """Every program file unpacked - each *.exe, *.dll and *.pyd - signed by the Python Software Foundation, as Windows
    judges it, before the import step runs any of them; Microsoft is allowed only on the Visual C++ runtime the package
    ships (VC_RUNTIME). The interpreters and the library are among them, and must be there.

    v0.6.23 final (S3 of the second round's security audit): only those three were checked, and every extension module
    and other DLL the import step then loads rested on a SHA-256 read from the same host as the package."""
    stem = "python3" + version.split(".")[1]
    try:
        names = sorted(entry.name for entry in target.iterdir() if entry.suffix.lower() in SIGNED_KINDS)
    except OSError:
        raise _Failed(SIGNATURE) from None
    if not {"python.exe", "pythonw.exe", stem + ".dll"} <= {name.lower() for name in names}:
        raise _Failed(SIGNATURE)
    for name in names:
        allowed = SIGNERS_OF_VC_RUNTIME if VC_RUNTIME.fullmatch(name) else (PYTHON_SIGNER,)
        try:
            if hands.signer(target / name) not in allowed:
                raise _Failed(SIGNATURE)
        except AdapterError:
            raise _Failed(SIGNATURE) from None


def _imports(target, paths, hands) -> None:
    try:
        if hands.imports(target / "python.exe", paths) is not True:
            raise _Failed(IMPORT)
    except (OSError, subprocess.SubprocessError):
        raise _Failed(IMPORT) from None


def imports_under(python, paths) -> bool:
    """Whether every shipped module imports under `python`: the first time that interpreter runs. In isolated mode, from
    its own folder, with no bytecode left behind and no window."""
    package = Path(__file__).resolve().parents[1]
    source = package.parent
    folders = [str(source)]
    scripts = source.parent / "scripts"
    if scripts.is_dir():
        folders.append(str(scripts))
    done = subprocess.run([str(python), "-I", "-B", "-X", "disable-remote-debug", str(package / "pythoncheck.py"), *folders],
                          cwd=str(Path(python).parent), capture_output=True, timeout=IMPORT_SECONDS,
                          creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    return done.returncode == 0


def _switched(runtime, version, target, hands, failed) -> dict:
    """The runtime is verified: named in the record, and the watcher restarted so it takes it. The launcher takes the record
    back away if the watcher does not come up, and that is how this knows."""
    home = _home(runtime)
    _set_stage(home, RESTARTING)
    _clear_returned(home)
    try:
        _write(chosen_runtime.root(home) / chosen_runtime.RECORD, {"version": version})
    except OSError:
        _remove(target)
        return failed(START)
    came = hands.restart(runtime.paths)
    if chosen_runtime.recorded(home) != version:
        _remove(target)
        return failed(START)
    if came in (RUNNING, NOT_RUNNING):
        _sweep(home, version)
        _count(runtime, "chosen")
        return {"word": CHOSEN_DONE if came == RUNNING else NEXT_START, "step": None, "version": version}
    if came == STILL_RUNNING:
        _count(runtime, "next_start")
        return {"word": NEXT_START, "step": None, "version": version}
    # Neither up nor refused by the launcher in time: taken back here, and started on the bundled runtime.
    _forget(home)
    hands.restart(runtime.paths)
    _remove(target)
    return failed(START)


def restart_watcher(paths) -> str:
    """Stop the watcher and start it again through its launcher, on the bundled runtime, which is where the launcher does
    its own check. NOT_RUNNING where none runs: it takes the choice at its next start, and nothing is started for it.

    The new launcher is started first, detached, and the stop asked after it (v0.6.23 final, R10 of the second round's
    limits audit): this runs on a daemon thread of the Dashboard's bridge process, which ends with the window, and a window
    closed between the stop and the start left the watcher stopped with none started. The launcher, told so by
    AFTER_STOP_MARK, waits for the watcher it follows to end and then starts it as ever, whatever became of this process; a
    watcher that does not stop is left running, and it takes the choice at its next start."""
    from codex_auto_resume import startup
    from codex_auto_resume.control import Control, await_watcher
    layer = Control(paths)
    if layer.watcher_running() is not True:
        return NOT_RUNNING
    home = Path(paths.home)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    interpreter = home / chosen_runtime.BUNDLED / "pythonw.exe"
    script = home / "watcher-launcher.py"
    process = subprocess.Popen([str(interpreter), *startup.NO_REMOTE_DEBUG, str(script), "run"],
                               cwd=str(home), close_fds=True, creationflags=flags, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env=dict(os.environ, **{AFTER_STOP_MARK: "1"}))
    if layer.stop_watcher().get("stopped") is not True:
        return STILL_RUNNING
    return await_watcher(layer.watcher_running, process, timeout=RESTART_SECONDS)["state"]


# ---------------------------------------------------------------------------- the folder
def _ready(root) -> None:
    """`runtimes` exists and is a real folder: never one that is a link or a junction."""
    try:
        root.mkdir(exist_ok=True)
        if root.is_symlink() or root.is_junction() or not root.is_dir():
            raise _Failed(UNPACK)
    except OSError:
        raise _Failed(UNPACK) from None


def _prepared(incoming, target) -> None:
    _unlink(incoming)
    _remove(target)
    if target.exists() or incoming.exists():
        raise _Failed(UNPACK)


def _unlink(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove(folder) -> None:
    try:
        if folder.is_symlink() or folder.is_junction():
            return
        shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass


def _sweep(home, keep) -> None:
    """Every runtime but `keep` and whatever was left half done. One a running program has open stays until it has ended."""
    root = chosen_runtime.root(home)
    try:
        if root.is_symlink() or root.is_junction() or not root.is_dir():
            return
        entries = list(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(INCOMING):
            _unlink(entry)
        elif chosen_runtime.shaped(entry.name) and entry.name != keep:
            _remove(entry)


def _write(path, payload) -> None:
    """One small JSON file, replaced whole."""
    path.parent.mkdir(exist_ok=True)
    staging = path.with_name(path.name + ".%d.tmp" % os.getpid())
    staging.write_text(json.dumps(dict(payload, at=int(time.time())), allow_nan=False), encoding="utf-8")
    os.replace(staging, path)


def _forget(home) -> None:
    _unlink(chosen_runtime.root(home) / chosen_runtime.RECORD)


def _clear_returned(home) -> None:
    _unlink(chosen_runtime.root(home) / RETURNED)

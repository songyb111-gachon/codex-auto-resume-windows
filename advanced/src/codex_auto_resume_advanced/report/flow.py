# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The compatibility report as the Dashboard drives it: write, save, check, send - each the person's.

The capability's code (registry.COMPAT_REPORT, an action: core never asks it anything). The bridge's
report commands (surfaces.py) are its only way in, and only the Dashboard's long-lived bridge reaches
them. Writing, checking and sending are jobs - each on a thread of this process, its status read with
advanced-report-job - because the Dashboard ends a call after thirty seconds and asks the one-shot
bridge instead, which never reaches the plug; saving is a call of its own.

Every command is answered in one order (design C.5): a job's status first, whatever stands - it reads
no file, asks nothing and starts nothing, so a send stopped by a turn-off, a policy or a pause still
shows what it wrote; then an administrator's policy; then where the capability stands - off refuses
everything, watched allows writing and saving and refuses checking and sending; then, for checking and
sending, the pause (K5); then the arguments; then one job at a time; then, for sending, the typed word
and the writes the person read.

One check or send runs at a time for each home, across every Dashboard window and process: its thread
holds the home's report mutex (ReportMutex) from its first question to GitHub to its last write, so the
re-check a send starts with and the writes it makes are one step.

A send that ends part way with nothing left to say so - its process ended while it wrote: the window
closed or reopened, or a call passed thirty seconds - is told by the next check here (`interrupted`).
The send leaves a mark beside the mutex's name (SENDING, an empty file in config/advanced) from just
before its first write until it ends, and the check that finds it takes it away. Windows hands the
mutex on abandoned only while another process has it open, so the mutex alone tells this only with a
second window; that, too, is still `interrupted`. What is on GitHub then is what that check reads,
whatever the mark or the mutex could tell.

A send asks GitHub again first and writes nothing unless what sending would write is still exactly
what the person read; before every write it reads again where the capability stands, the policy and
the pause, and stops with what it had written. Only the word `send`, exactly, sends.

What a report holds, its bytes and every status are kept in this process's memory and nowhere else -
the mark holds none of them, only that a send was writing;
the journal gets one closed code a step (`rpt.<code>`) and is never read to decide anything. A fault
of this code - anything but a refusal - turns the capability off (hook_exception).
"""
from __future__ import annotations

from collections import OrderedDict
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import threading
import time

from ..vocabulary import (ArmingState, BridgeCommand, OffReason, Refusal, ReportRefusal, ReportStatus,
                          WebReason)
from . import document, github, records

WORD = "send"                                    # what the person types to send, exactly: no trim, no case fold
MAX_BUILDS = 4                                   # reports kept to be saved, checked or sent
MAX_JOBS = 16                                    # statuses kept to be read
START_SECONDS = 10.0                             # how long a command waits for its job to take the mutex
MUTEX_NAME = "compat-report"
SENDING = "compat-report.sending"                # in config/advanced while a send is writing (the mark above)


class Stopped(Exception):
    """A send stopped before its next write: `code` is why - a turn-off, a policy or a pause."""

    def __init__(self, code):
        self.code = str(code)
        super().__init__(self.code)


@dataclass
class Build:
    raw: bytes
    document: dict
    login: str
    sha256: str


def refused(code) -> dict:
    return {"done": False, "refusal": str(code)}


class Busy(Exception):
    """Another check or send of this home holds the report mutex."""


class ReportMutex:
    """The home's report mutex: one check or send at a time, across every process of this user.

    Named as core names every mutex of the product (win.sync.Mutex: per user and per path, in the
    session's namespace) and refused if a lower-integrity process made it first. Its handle is opened
    once and kept for the life of this process, so that when another process dies holding it, the
    object outlives it - Windows hands it on as abandoned, and the next check here is told so. A mutex
    nobody else had open is gone with its holder instead: a send's mark (SENDING) tells that one."""

    def __init__(self, paths):
        from codex_auto_resume.win.sync import Mutex
        self.name = Mutex(str(paths.advanced_dir / MUTEX_NAME)).name
        self._handle = None
        self._lock = threading.Lock()

    def take(self) -> bool:
        """Takes it on the calling thread, without waiting; whether the holder before let it go by
        dying (abandoned). Busy where another holds it now."""
        from codex_auto_resume.win.kernel import ERROR_ALREADY_EXISTS, _kernel, _refuse_if_squatted
        k = _kernel()
        with self._lock:
            if self._handle is None:
                k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                k.CreateMutexW.restype = wintypes.HANDLE
                handle = k.CreateMutexW(None, False, self.name)
                existed = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
                if not handle:
                    raise Busy()
                try:
                    _refuse_if_squatted(handle, existed)
                except Exception:
                    k.CloseHandle(handle)
                    raise Busy() from None
                self._handle = handle
        result = k.WaitForSingleObject(self._handle, 0)
        if result not in (0, 128):
            raise Busy()
        return result == 128

    def give(self) -> None:
        """Lets it go, on the thread that took it; the handle stays open."""
        from codex_auto_resume.win.kernel import _kernel
        k = _kernel()
        k.ReleaseMutex.argtypes = [wintypes.HANDLE]
        k.ReleaseMutex.restype = wintypes.BOOL
        k.ReleaseMutex(self._handle)


class Flow:
    """One installation's report jobs, for the life of this process."""

    def __init__(self, paths, *, runner=github.run_process, find_gh=None, mutex=ReportMutex, sleep=time.sleep,
                 clock=time.time, product_version=None, windows=None, codex_home=None, view=None):
        self.paths = paths
        self.runner = runner
        self._find = find_gh
        self._make_mutex = mutex
        self._mutex = None
        self.sleep = sleep
        self.clock = clock
        self.product_version = product_version
        self.windows = windows
        self._codex_home = codex_home
        self._view = view
        self._lock = threading.Lock()
        self._builds = OrderedDict()             # sha256 -> Build
        self._checked = {}                       # sha256 -> the writes the last check of it named
        self._jobs = OrderedDict()               # job id -> status
        self._running = None                     # the job id under way, or None

    # ------------------------------------------------------------------ the commands
    def answer(self, runtime, definition, command, argument) -> dict:
        """One report command (surfaces.REPORT_COMMANDS) for the Dashboard, in the order above."""
        if command == BridgeCommand.ADVANCED_REPORT_JOB:
            return self.job(argument.get("job"))
        sending = command in (BridgeCommand.ADVANCED_REPORT_CHECK, BridgeCommand.ADVANCED_REPORT_SEND)
        why = self.standing(runtime, definition, sending=sending)
        if why is None and sending:
            why = self.pause()
        if why is not None:
            return refused(why)
        if command == BridgeCommand.ADVANCED_REPORT_BUILD:
            return self.build(runtime, definition, argument.get("login"))
        if command == BridgeCommand.ADVANCED_REPORT_SAVE:
            return self.save(runtime, definition, argument.get("sha256"), argument.get("path"))
        build = self._build_of(argument.get("sha256"))
        if build is None:
            return refused(ReportRefusal.UNKNOWN_BUILD)
        if command == BridgeCommand.ADVANCED_REPORT_CHECK:
            return self._start(runtime, definition, lambda context: self._check(runtime, definition, build, context),
                               mutex=True)
        if self._running is not None:
            return refused(ReportRefusal.BUSY)
        if argument.get("word") != WORD:
            return refused(ReportRefusal.WORD)
        writes = argument.get("writes")
        with self._lock:
            shown = self._checked.get(build.sha256)
        if shown is None or not isinstance(writes, list) or writes != shown:
            return refused(ReportRefusal.CHANGED)
        return self._start(runtime, definition,
                           lambda context: self._send(runtime, definition, build, shown, context), mutex=True)

    def job(self, job) -> dict:
        """How the job `job` is getting on: memory alone, whatever stands now. `lost` for one this
        process does not hold - it ended with another process, or was never started."""
        with self._lock:
            status = self._jobs.get(job) if isinstance(job, str) else None
            return dict(status, done=True, job=job) if status is not None else {"done": True,
                                                                                 "status": str(ReportStatus.LOST)}

    # ------------------------------------------------------------------ standing
    def standing(self, runtime, definition, *, sending):
        """Why nothing of the kind may be done now, or None: a policy, off, or - to check or send -
        watched. A policy is looked at first, since under one a capability reads as off."""
        policy = runtime.arming.policy()
        if policy.forbid:
            return Refusal.FORBIDDEN_BY_POLICY
        if not policy.admits(definition.id):
            return Refusal.NOT_ALLOWED_BY_POLICY
        state = runtime.states(fresh=True).get(definition.id, ArmingState.OFF)
        if state == ArmingState.OFF:
            return ReportRefusal.NOT_ON
        if sending and state != ArmingState.ARMED:
            try:
                stored = (runtime.state.arming().get(definition.id) or {}).get("state")
            except Exception:
                stored = None
            return (Refusal.SHADOW_FORCED_BY_POLICY if policy.force_shadow and stored == ArmingState.ARMED
                    else ReportRefusal.WATCHED)
        return None

    def pause(self):
        """Why nothing may be checked or sent, or None: recovery paused, or a switch that cannot be read
        - a pull request cannot be taken back, so not knowing is no."""
        found = records.paused(self.paths)
        if found is None:
            return ReportRefusal.STATE_UNREADABLE
        return ReportRefusal.PAUSED if found else None

    # ------------------------------------------------------------------ writing and saving
    def build(self, runtime, definition, login) -> dict:
        try:
            login = document.check_login(login)
        except document.DocumentRefused as refusal:
            return refused(refusal.code)
        return self._start(runtime, definition, lambda context: self._write(runtime, definition, login), mutex=False)

    def _write(self, runtime, definition, login) -> dict:
        from ..codex import inuse
        home = inuse.home(self.paths) if self._codex_home is None else self._codex_home
        try:
            found = records.read(self.paths, home, now=self.clock(), view=self._view)
        except records.ReadRefused as refusal:
            return self._refused(runtime, definition, refusal.code)
        try:
            made = document.assemble(found["body"], login, product_version=self.product_version,
                                     windows=self.windows, now=self.clock())
            raw = document.check(made)
        except document.DocumentRefused as refusal:
            return self._refused(runtime, definition, refusal.code)
        sha = hashlib.sha256(raw).hexdigest()
        with self._lock:
            self._builds[sha] = Build(raw=raw, document=made, login=login, sha256=sha)
            self._builds.move_to_end(sha)
            while len(self._builds) > MAX_BUILDS:
                self._builds.popitem(last=False)
        target, branch = github.destination(made["codex_version"], login)
        self._note(runtime, definition, "built")
        return {"status": str(ReportStatus.BUILT), "sha256": sha, "bytes": len(raw), "text": raw.decode("ascii"),
                "codex_version": made["codex_version"], "records": len(made["records"]), "verdict": made["verdict"],
                "left_out": found["left_out"], "login": login, "file_name": target.rsplit("/", 1)[1],
                "branch": branch}

    def save(self, runtime, definition, sha, path) -> dict:
        """The report `sha` written to `path`, which the person chose, and never over a file."""
        build = self._build_of(sha)
        if build is None:
            return refused(ReportRefusal.UNKNOWN_BUILD)
        if not isinstance(path, str) or not path or not Path(path).is_absolute():
            return refused(ReportRefusal.SAVE_FAILED)
        try:
            with open(path, "xb") as handle:
                handle.write(build.raw)
        except FileExistsError:
            return refused(ReportRefusal.FILE_EXISTS)
        except OSError:
            return refused(ReportRefusal.SAVE_FAILED)
        self._note(runtime, definition, "saved")
        return {"done": True, "status": str(ReportStatus.SAVED)}

    def _build_of(self, sha):
        with self._lock:
            return self._builds.get(sha) if isinstance(sha, str) else None

    # ------------------------------------------------------------------ checking and sending
    def _gh(self):
        if self._find is not None:
            return self._find()
        import codex_auto_resume
        return github.find_gh(unsafe=(self.paths.home, Path(codex_auto_resume.__file__).resolve().parents[1]))

    def _inspect(self, build):
        return github.inspect(build.raw, build.document, build.login, exe=self._gh(), cwd=self.paths.advanced_dir,
                              runner=self.runner, sleep=self.sleep)

    # ------------------------------------------------------------------ the mark of a send writing
    def _mark(self) -> None:
        """Leaves the mark that a send is writing; one a send before left is kept as it is. Never
        through a link: the file is made new, or is there already. A mark that cannot be made leaves
        the mutex alone to tell (a second window's), and the send goes on."""
        try:
            with open(self.paths.advanced_dir / SENDING, "xb"):
                pass
        except OSError:
            pass

    def _marked(self) -> bool:
        return os.path.lexists(self.paths.advanced_dir / SENDING)

    def _unmark(self) -> None:
        try:
            os.unlink(self.paths.advanced_dir / SENDING)
        except OSError:
            pass

    def _check(self, runtime, definition, build, context) -> dict:
        # Read under the mutex, so a send under way in another window is never taken for a cut-off one.
        cut_off = self._marked()
        interrupted = context["abandoned"] or cut_off
        if interrupted:
            self._note(runtime, definition, "lost")
        try:
            found = self._inspect(build)
        except github.ReportRefused as refusal:
            return self._refused(runtime, definition, refusal.code)
        if isinstance(found, github.Web):
            return self._web(build, found)
        if cut_off:
            self._unmark()                       # told now, by the status the person is shown
        if isinstance(found, github.Sent):
            self._note(runtime, definition, "sent")
            return {"status": str(ReportStatus.SENT), "url": found.url, "already": True}
        writes = found.writes()
        with self._lock:
            self._checked[build.sha256] = writes
        self._note(runtime, definition, "checked")
        return {"status": str(ReportStatus.CHECKED), "gh": found.exe, "who": found.who, "writes": writes,
                "interrupted": interrupted}

    def _web(self, build, found) -> dict:
        target, branch = github.destination(build.document["codex_version"], build.login)
        return {"status": str(ReportStatus.WEB), "why": str(WebReason(found.why)), "login": build.login,
                "who": found.who, "branch": branch, "target": target, "file_name": target.rsplit("/", 1)[1],
                "project_page": github.PROJECT_PAGE}

    def _send(self, runtime, definition, build, shown, context) -> dict:
        try:
            found = self._inspect(build)
        except github.ReportRefused as refusal:
            return self._refused(runtime, definition, refusal.code)
        if isinstance(found, github.Sent):
            self._note(runtime, definition, "sent")
            return {"status": str(ReportStatus.SENT), "url": found.url, "already": True}
        if not isinstance(found, github.Ready) or found.writes() != shown:
            return self._refused(runtime, definition, ReportRefusal.CHANGED)
        context["written"] = found.written
        marked = []

        def before():
            why = self.standing(runtime, definition, sending=True) or self.pause()
            if why is not None:
                raise Stopped(why)
            if not marked:                       # just before the first write: from here it can end part way
                self._mark()
                marked.append(True)
        try:
            url = github.publish(found, build.raw, build.document, before=before, runner=self.runner,
                                 sleep=self.sleep)
        except (github.ReportRefused, Stopped) as refusal:
            if not found.written:
                return self._refused(runtime, definition, refusal.code)
            self._note(runtime, definition, "partial")
            return {"status": str(ReportStatus.PARTIAL), "written": list(found.written), "refusal": str(refusal.code)}
        finally:
            if marked:                           # it ended here, whatever came of it: its status says so
                self._unmark()
        self._note(runtime, definition, "sent")
        return {"status": str(ReportStatus.SENT), "url": url, "already": False}

    # ------------------------------------------------------------------ jobs
    def _start(self, runtime, definition, work, *, mutex) -> dict:
        """`work` on a thread of its own, as this process's one job; with `mutex`, holding the home's
        report mutex throughout, or `busy` - without starting anything - where another holds it."""
        with self._lock:
            if self._running is not None:
                return refused(ReportRefusal.BUSY)
            job = secrets.token_hex(8)
            self._running = job
            self._jobs[job] = {"status": str(ReportStatus.RUNNING)}
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)
        taken = threading.Event()
        context = {"abandoned": False, "busy": False, "written": None}

        def run():
            lock = None
            try:
                if mutex:
                    try:
                        with self._lock:
                            if self._mutex is None:
                                self._mutex = self._make_mutex(self.paths)
                            lock = self._mutex
                        context["abandoned"] = bool(lock.take())
                    except Exception:
                        lock = None
                        context["busy"] = True
                        return
                taken.set()
                try:
                    status = work(context)
                except Exception:
                    # A fault of this code, never a refusal: the capability turns itself off.
                    runtime.arming.trip(definition.id, OffReason.HOOK_EXCEPTION)
                    written = context["written"]
                    status = ({"status": str(ReportStatus.PARTIAL), "written": list(written),
                               "refusal": str(ReportRefusal.NOT_ON)} if written
                              else {"status": str(ReportStatus.REFUSED), "refusal": str(ReportRefusal.NOT_ON)})
                with self._lock:
                    self._jobs[job] = status
            finally:
                if lock is not None:
                    lock.give()
                with self._lock:
                    if context["busy"]:
                        self._jobs.pop(job, None)
                    if self._running == job:
                        self._running = None
                taken.set()

        threading.Thread(target=run, name="compat-report", daemon=True).start()
        taken.wait(START_SECONDS)
        if context["busy"]:
            return refused(ReportRefusal.BUSY)
        return {"done": True, "job": job}

    def wait(self, job, seconds=30.0) -> dict:
        """The job's status once it is no longer running, or as it stands after `seconds`: for tests."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = self.job(job)
            if found["status"] != ReportStatus.RUNNING:
                return found
            time.sleep(0.01)
        return self.job(job)

    # ------------------------------------------------------------------ the journal
    def _refused(self, runtime, definition, code) -> dict:
        self._note(runtime, definition, "refused")
        return {"status": str(ReportStatus.REFUSED), "refusal": str(code)}

    def _note(self, runtime, definition, code) -> None:
        try:
            runtime.state.note(definition.code(code), capability=definition.id, at=self.clock())
        except Exception:
            pass

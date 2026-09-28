"""Starting with Codex, and the one line it writes about what happened.

v0.6.9 measured this rather than assuming it: Codex runs each MCP server in a job object with
KILL_ON_JOB_CLOSE and no breakaway, so a watcher started there dies with the server. The
refusal and the note are what is left, and they say which of those two things happened.

The refusal is where the edition's plug is asked for a route of its own (P9). The standard
edition has none, and no plug's route is carried out yet, so the refusal is what it was.
"""
from __future__ import annotations

import os
import time

from .. import startup, windows
from ..domain.plug import DEFER
from .errors import ControlError


CODEX_START_LOG_LINES = 50


def _context_words(context) -> str:
    """windows.process_context as a few fixed words: "in a job (kill on close, may leave)",
    "not in a job", "job unknown", with ", packaged" when the process has a package identity."""
    if not context or context.get("in_job") is None:
        words = "job unknown"
    elif not context["in_job"]:
        words = "not in a job"
    else:
        flags = [name for key, name in (("kill_on_close", "kill on close"),
                                        ("breakaway_ok", "may leave"),
                                        ("silent_breakaway_ok", "children leave"))
                 if context.get(key)]
        unknown = context.get("kill_on_close") is None
        words = "in a job (%s)" % ("limits unknown" if unknown else ", ".join(flags) or "no limits read")
    if context.get("packaged"):
        words += ", packaged"
    return words


def ends_with_job(context, *, leaving: bool = False):
    """Whether a process this one starts is ended when the job holding this one closes, read from
    windows.process_context: True, False, or None where Windows would not say.

    `leaving` is whether the start asks to leave the job (CREATE_BREAKAWAY_FROM_JOB, which a job
    grants only with BREAKAWAY_OK). A job with SILENT_BREAKAWAY_OK lets every child go anyway, and
    one without KILL_ON_JOB_CLOSE ends none of them. One reading, shared by the start with Codex,
    which refuses where it is True, and by the MCP server's Start watcher, which says so (v0.6.10).
    """
    if not context or context.get("in_job") is None:
        return None
    if not context["in_job"] or leaving or context.get("silent_breakaway_ok"):
        return False
    kill = context.get("kill_on_close")
    return None if kill is None else bool(kill)


def _note_line(path: Path, text: str) -> None:
    """Append one timestamped line to a trimmed log, keeping the last CODEX_START_LOG_LINES.
    Best effort: a log that cannot be written costs nothing but the line."""
    try:
        if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
            return
        lines = []
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-(CODEX_START_LOG_LINES - 1):]
        lines.append(time.strftime("[%Y-%m-%d %H:%M:%S] ") + text)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        pass


class CodexStartMixin:
    """The launch Codex asks for, and why it is refused."""

    def launch_ends_with_job(self):
        """Whether a watcher Start watcher launches from this process ends when this process's job
        closes: True, False, or None where Windows would not say. Never raises.

        Start watcher asks nothing of the job, so a job that ends what it holds ends that watcher.
        The MCP server asks this after a start (v0.6.10): Codex 26.915 runs it in a job with
        KILL_ON_JOB_CLOSE and no breakaway (measured, v0.6.9-alpha), so a watcher started from the
        panel or the start_watcher tool stops when Codex ends that server - when Codex closes, if not
        sooner - and its reply has to say so rather than report a lasting start.
        """
        try:
            return ends_with_job(windows.process_context())
        except Exception:        # noqa: BLE001 - a question Windows cannot answer is not an error here
            return None

    def start_for_codex(self) -> str:
        """Start the watcher because Codex has just started this plugin's MCP server - if asked to.

        v0.6.9, `start_with_codex`, off by default. Codex starts every plugin's MCP server
        whenever it opens - measured on 26.915: three short starts about twenty seconds after
        launch, each cancelled within seconds of listing the tools - so this runs in the first
        moment of each server's life and waits for nothing. It launches exactly what Start
        watcher launches, only while the setting is on, no watcher runs, and no installation
        holds its lock; the watcher's own single-instance mutex answers any launch that races
        another. A job that lets a child leave it is left, so the watcher does not end with the
        Codex that started it.

        Never raises, and returns the one line it records in logs/codex-start.log: what Windows
        wrapped this process in (windows.process_context) and what was decided. The line carries
        no path, name or content.
        """
        context = {}
        try:
            context = windows.process_context()
            decision = self._start_for_codex(context)
        except Exception as exc:     # noqa: BLE001 - a failure here must never cost Codex the panel
            decision = "failed: %s" % type(exc).__name__
        line = "pid %d; %s; %s" % (os.getpid(), _context_words(context), decision)
        _note_line(self.paths.codex_start_log, line)
        return line

    def _start_for_codex(self, context) -> str:
        setting_on = bool(self.get_settings().get("start_with_codex"))
        breakaway = bool(context.get("in_job") and context.get("breakaway_ok")
                         and not context.get("silent_breakaway_ok"))
        # Measured on Codex 26.915 (v0.6.9-alpha, 2026-09-23): Codex runs each plugin's MCP server in a
        # job object with KILL_ON_JOB_CLOSE and no BREAKAWAY_OK, and cancels that server a few seconds
        # after it has listed its tools. A watcher started there is killed with it - six starts, six
        # watchers, each dead within about six seconds - and a watcher killed mid-tick is exactly what
        # this product does not do.
        job_ends = ends_with_job(context, leaving=breakaway) is True
        # Whether "start with Codex" is on: the standard edition's setting (held back in
        # NOT_YET_OFFERED), or an armed advanced start-with-Codex capability, which names a route
        # at P9 (domain/plug.py). With the setting off we ask the plug once - the only way to
        # learn the capability is armed, since the plug points are the one seam core has to it -
        # and with no route named the answer is "off", exactly the standard edition's, before a
        # single probe. NULL names no route, so the standard edition is unchanged; an advanced
        # installation with nothing armed reads its own empty state and answers "off" too. With
        # the setting on the plug is not asked here: core is starting on its own account, and the
        # job branch below asks for the route in its own place, as it always has.
        route = DEFER
        if not setting_on:
            route = self.plug.start_route(dict(context))
            if route is DEFER:
                return "off"
        # A pause stops start-with-Codex, as it stops every capability and core's own recovery:
        # nothing is started, WMI route or core's own launch, while recovery is paused.
        if self._paused():
            return "not started: recovery is paused"
        running = self.watcher_running()
        if running is True:
            return "already running"
        if running is None:
            return "not started: the watcher could not be asked"
        if windows.install_in_progress() is not False:
            return "not started: an installation is in progress"
        # Uninstalling from Codex removes the launcher and leaves the program files; a start
        # through anything but the launcher would bring back a watcher that was just removed.
        if not (self.paths.home / "watcher-launcher.py").is_file():
            return "not started: not installed"
        if job_ends:
            # P9: asked here, after every existing refusal - nothing running, no install, the
            # launcher present - and only where the job would end the watcher. The standard
            # edition's plug has no route (DEFER), so its refusal stands; the advanced edition,
            # with start-with-Codex armed, names a route that starts the watcher outside this job
            # through WMI, and core carries it out.
            if route is DEFER:
                route = self.plug.start_route(dict(context))
            if route is DEFER:
                return "not started: this Codex ends what its plugins start"
            return self._start_through_route(route)
        # The job would not end the watcher: core starts it itself, out of the job if it may
        # leave. Reached with the setting on, or with an armed capability that has turned the
        # start on the way the setting does - "start with Codex" starts the watcher whenever
        # Codex starts, and only where the job would end it does the route take over.
        # Looked at once more, as late as it can be: an installation may have begun meanwhile.
        if windows.install_in_progress() is not False:
            return "not started: an installation is in progress"
        try:
            process = self._launch_watcher(windows.CREATE_BREAKAWAY_FROM_JOB if breakaway else 0,
                                           launcher_only=True)
        except OSError:
            if not breakaway:
                raise
            # The job refused to let it go after all; a watcher inside it is still a watcher.
            process = self._launch_watcher(0, launcher_only=True)
            breakaway = False
        return "started pid %d%s" % (process.pid, ", out of the job" if breakaway else
                                     ", inside the job" if context.get("in_job") else "")

    def _paused(self) -> bool:
        """Whether recovery is paused: the global switch turned off in a state that already
        exists. Never raises.

        A state that was never written is not a pause - a fresh installation has not turned
        recovery on yet, and a start-with-Codex refused there would never start at all - so the
        file is read only where it is there. A state that cannot be read is not read as a pause
        either: refusing a start over a store that will not open is worse than making one.
        """
        if not (self.paths.state_dir / "state.sqlite").is_file():
            return False
        try:
            with self._open(legacy_ok=True) as store:
                return not bool(store.settings()["enabled"])
        except ControlError:
            return False

    def _start_through_route(self, route) -> str:
        """Carry out a plug's start route: start the watcher outside this job and say what happened.

        Core builds the command line, from the same two pieces `_launch_watcher` uses - the
        windowless interpreter (startup.python_launcher) and this installation's stable launcher,
        which already knows its home - so nothing derived from anything else reaches the route.
        The install lock is looked at once more, as late as it can be, immediately before the
        launch. The route runs the launch and hands back a pid, a refusal code, or - where it
        could not tell whether the create ran - an uncertain outcome; core writes the one line,
        which carries no path, name or content. The route never sends and never claims.
        """
        if windows.install_in_progress() is not False:
            return "not started: an installation is in progress"
        command = startup.command_line(self.paths.home / "watcher-launcher.py")
        outcome = route.start(command)
        outcome = outcome if isinstance(outcome, dict) else {}
        pid = outcome.get("pid")
        if isinstance(pid, int) and pid > 0:
            return "started through WMI pid %d" % pid
        if "uncertain" in outcome:
            # The create may have run and a watcher may be up; the mutex settles any race. Not a
            # refusal, so the line does not claim the watcher was not started.
            return "start uncertain: WMI did not answer (%s)" % outcome["uncertain"]
        code = outcome.get("code")
        return "not started: WMI refused (%s)" % (code if code is not None else "no pid")

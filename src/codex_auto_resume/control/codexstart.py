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

from .. import windows


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
        if not self.get_settings().get("start_with_codex"):
            return "off"
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
        breakaway = bool(context.get("in_job") and context.get("breakaway_ok")
                         and not context.get("silent_breakaway_ok"))
        # Measured on Codex 26.915 (v0.6.9-alpha, 2026-09-23): Codex runs each plugin's MCP server in a
        # job object with KILL_ON_JOB_CLOSE and no BREAKAWAY_OK, and cancels that server a few seconds
        # after it has listed its tools. A watcher started there is killed with it - six starts, six
        # watchers, each dead within about six seconds - and a watcher killed mid-tick is exactly what
        # this product does not do. So where the job would end it and will not let it leave, nothing is
        # started: the line below is the whole answer for that Codex, and the switch is not offered.
        if ends_with_job(context, leaving=breakaway) is True:
            # P9: asked only here, with the setting on and nothing running - after every
            # consent this start has. Core carries out no route of a plug's yet (domain/plug.py,
            # ALTERNATIVES), so whatever it answers, the refusal stands.
            self.plug.start_route(dict(context))
            return "not started: this Codex ends what its plugins start"
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

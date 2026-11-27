"""What the watcher is doing, what is wrong with it, and what Codex it is running against.

`status` is the short answer, `doctor` the long one, and `compat` the Compatibility Registry's
view of the engine in force.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import compat, compatio, config, machine, startup
from ..app import EXIT_ERROR, EXIT_OK
from ..codex.errors import HistoryNotYet
from ..codex.pairing import app_running_now
from ..domain.plug import Surface
from ..logbook import format_local
from ..store import StoreError
from ..windows import AdapterError, WakeEvent, resource_users
from .base import _app, _now, _print, progress
from .records import _record_view


def _edition_line(plug):
    """The edition badge for the status line, or None in the standard edition.

    The standard edition's plug is NULL, so this returns None and the status prints no edition
    line at all - it is exactly what it was. An advanced installation shows its badge and, when
    its package loaded, how many capabilities are armed, read from the plug's own status surface
    (the `on` field get_status carries under `advanced`); one whose package could not be loaded
    shows only its badge, which already says so.
    """
    if plug.null:
        return None
    fields = plug.surface(Surface.STATUS, {})
    on = fields.get("on") if isinstance(fields, dict) else None
    return "%s (%d armed)" % (plug.badge, on) if isinstance(on, int) else plug.badge


def cmd_status(args) -> int:
    app = _app(args)
    with app.open_store() as store:
        settings = store.settings()
        counts = store.status_counts()
        pending = store.pending()
    running = app.watcher_running()
    _print("auto-resume      : %s" % ("ENABLED" if settings["enabled"] else "disabled"))
    if settings["enabled"]:
        _print("enabled since    : %s" % format_local(settings["armed_at"]))
    _print("watcher          : %s" % {True: "running", False: "not running", None: "unknown"}[running])
    # The edition badge, only where it says something: the standard edition's plug is NULL and
    # adds no line, so a standard status is exactly what it always was (decision C12).
    edition_line = _edition_line(app.plug)
    if edition_line is not None:
        _print("edition          : %s" % edition_line)
    try:
        value = startup.current_value()
        _print("login autostart  : %s" % ("registered" if value else "not registered"))
    except startup.StartupError:
        _print("login autostart  : unavailable")
    try:
        backend = app.backend()
        _print("codex engine     : %s" % backend.codex_exe)
        _print("engine version   : %s  (%s)" % (backend.engine_version, _engine_words(app, backend)[0]))
        identity, looked = _app_paired(app, backend)
        elsewhere = "; %s" % ELSEWHERE_SHORT if identity and looked.codex_exe != backend.codex_exe else ""
        _print("ChatGPT app      : %s" % ("running (pid %d, codex server pid %d%s)"
                                          % (identity["pid"], identity["server"]["pid"], elsewhere) if identity
                                          else UNMATCHED_APP if looked.app_look == "unmatched" else "not running / not paired"))
    except (config.ConfigError, AdapterError) as exc:
        _print("codex engine     : unavailable (%s)" % exc)
    view = compatio.reader_view(app.paths, settings=app.settings)
    _print("compatibility    : %s (%s)" % (view["overall"], _view_status(view)))
    _print("pending          : %d" % len(pending))
    for state in sorted(counts):
        _print("  %-22s %d" % (state, counts[state]))
    _print("lookback         : %.1f h" % app.settings["detection_lookback_hours"])
    _print("state file       : %s" % (app.paths.state_dir / "state.sqlite"))
    _print("log file         : %s" % app.paths.log_file)
    return EXIT_OK


# #58's follow-up: the app runs, and the look found no server of its at the configured engine.
UNMATCHED_APP = "running, but its Codex server could not be matched"
# v0.6.24 final: the app serves from another official engine than the one found first, which the watcher takes up.
ELSEWHERE_SHORT = "its server runs from another official Codex engine, which the watcher takes up"
# The health check's checks, counted for the setup window's bar while install.ps1 runs it (progress).
DOCTOR_CHECKS = 8
# v0.6.26 (update resilience, proposal 8): the app simply closed is no failure - the watcher finds its server, and an
# engine the app carries, when it opens - and the line that says so says it is not a problem.
CLOSED_APP = "not running (not a problem: recoveries wait until it opens)"
CLOSED_ENGINE = "not found while the ChatGPT app is closed (not a problem: it is looked for again when the app opens)"
# v0.6.26 final: a fresh home's history - none yet, and no conversation in its state - is no failure: Codex makes it with
# the first conversation it saves (codex/errors.py HistoryNotYet). A home with a conversation and no history still fails.
HISTORY_NOT_YET = "not created yet (Codex makes it with the first saved conversation)"
# The health check's last line where a check failed, which the installer's last word repeats (install.ps1).
PROBLEM = "health check     : problem - "


def _app_closed():
    """Whether no process of the Codex app's package runs now - False too where that cannot be told."""
    return app_running_now() is False


def _autostart_line():
    """(ok, line) for the Run value that starts the watcher at sign-in: not registered (a choice, not a failure),
    registered, or registered with its interpreter or its launcher gone - which starts nothing at the next sign-in."""
    try:
        value = startup.current_value()
        if not value:
            return True, "autostart        : not registered"
        argv = startup.parse_command(value)
        script = startup.script_index(argv)
        missing = [part for part in (argv[:1] + argv[script:script + 1]) if not Path(part).exists()]
        if missing:
            return False, "autostart        : registered, but %s is missing (run install again)" % (
                "its interpreter" if argv and missing[0] == argv[0] else "its launcher")
        return True, "autostart        : registered"
    except (startup.StartupError, OSError, IndexError) as exc:
        return True, "autostart        : unavailable (%s)" % type(exc).__name__


def _app_paired(app, backend):
    """(identity, backend): the app's pairing as the watcher reaches it, and the backend whose look that was.

    v0.6.24 final: right after a restart the app can run its server from another official Codex engine (in bin, or in
    its own package and signed by OpenAI, #58) than the one discovery found first - on the owner's PC the package's
    0.169.1 beside bin's 0.167.0-alpha.4.1 - and the watcher then looks for its engine again (App.engine_moved) and
    pairs with that one. A check that judged the first pairing alone said "could not be matched" after every install
    and repair, of an app the watcher recovers with a moment later. So it takes the same look again first: the same
    rule (official_engine; a named engine is never second-guessed), the same discovery, every engine check included.
    A server it does not find that way - not official, unsigned, unreadable, failing its checks - stays unmatched."""
    identity = backend.app_identity()
    if identity or not app.engine_moved():
        return identity, backend
    try:
        again = app.backend()
    except (config.ConfigError, AdapterError):
        return None, backend
    return again.app_identity(), again


def cmd_doctor(args) -> int:
    app = _app(args)
    # v0.6.26: every failing line, so the last one can name the first (PROBLEM), which the installer's last word repeats.
    failed = []

    def fail(line):
        failed.append(line)
        _print(line)
    try:
        backend = app.backend()
        _print("codex.exe        : %s" % backend.codex_exe)
        _print("engine version   : %s (%s)" % (backend.engine_version, _engine_words(app, backend)[1]))
    except (config.ConfigError, AdapterError) as exc:
        if not _app_closed():
            fail("codex.exe        : FAIL (%s)" % exc)
            _print(PROBLEM + " ".join(failed[0].split()))
            return EXIT_ERROR
        # v0.6.26: an engine the app carries is found when the app opens (E1); the checks of an engine wait for it.
        backend = None
        _print("codex.exe        : " + CLOSED_ENGINE)
    if backend is not None:
        progress("check", 1, DOCTOR_CHECKS)
        # Checked now, against the backend just probed; never written - the report on disk is
        # the watcher's alone. Read-only against Codex's state, like everything here.
        try:
            live = compatio.live_view(app.paths, app.codex_home, backend=backend, discovery={},
                                      source=app.source())
        except Exception as exc:
            live = None
            _print("compatibility    : unavailable (%s)" % type(exc).__name__)
        if live is not None:
            _print("compatibility    : %s (checked now)" % live["overall"])
            for line in _capability_lines(live, only_problems=True):
                _print(line)
            if live["overall"] in ("incompatible", "failed_here"):
                failed.append("compatibility    : %s (checked now)" % live["overall"])
        progress("check", 2, DOCTOR_CHECKS)
        report = compatio.reader_view(app.paths, settings=app.settings)
        _print("watcher's report : %s (%s)" % (report["overall"], _view_status(report)))
        # Beside the version, and never a verdict: `failed` is not touched by it.
        _print("reported         : %s" % _reported_words(live if live is not None else report))
        progress("check", 3, DOCTOR_CHECKS)
        _print("codex home       : %s" % app.codex_home)
        identity, looked = _app_paired(app, backend)
        if identity:
            _print("ChatGPT app      : main pid %d, codex app-server pid %d" % (identity["pid"], identity["server"]["pid"]))
            if looked.codex_exe != backend.codex_exe:
                # Not a problem: the engine the watcher pairs with on its next look, named as codex.exe names the first.
                _print("                   %s: %s (%s)" % (ELSEWHERE_SHORT, looked.codex_exe, looked.engine_version))
        elif looked.app_look == "closed":
            # v0.6.26: the look just taken found no process of the app's package at all - no failure (U4).
            _print("ChatGPT app      : " + CLOSED_APP)
        else:
            fail("ChatGPT app      : %s" % (UNMATCHED_APP if looked.app_look == "unmatched"
                                            else "not running or not paired with the configured engine"))
        progress("check", 4, DOCTOR_CHECKS)
    running = app.watcher_running()
    _print("watcher mutex    : %s" % {True: "held by a running watcher", False: "free", None: "unavailable"}[running])
    progress("check", 5, DOCTOR_CHECKS)
    try:
        lock_dir = app.codex_home / "thread-writer-locks"
        probe = lock_dir / ".coordination.lock"
        if probe.exists():
            resource_users(probe)
            _print("restart manager  : ok")
        else:
            _print("restart manager  : skipped (no coordination lock file)")
    except AdapterError as exc:
        fail("restart manager  : FAIL (%s)" % exc)
    progress("check", 6, DOCTOR_CHECKS)
    try:
        app.source().latest_failures(_now() - 60)
        _print("local history    : readable")
    except HistoryNotYet:
        _print("local history    : " + HISTORY_NOT_YET)
    except Exception as exc:
        fail("local history    : FAIL (%s)" % type(exc).__name__)
    progress("check", 7, DOCTOR_CHECKS)
    # The notification's button goes through a registered URL protocol. If its target has
    # gone - an installation moved, or a temporary home that no longer exists - the button
    # silently does nothing, and nothing else in the product would ever mention it.
    try:
        registered = startup.protocol_value()
        if not registered:
            _print("notification action: not registered (the button would do nothing)")
        else:
            argv = startup.parse_command(registered)
            script = startup.script_index(argv)
            target = Path(argv[script]) if len(argv) > script else None
            if target is not None and not target.exists():
                fail("notification action: registered, but its target is missing")
                _print("                     re-run install to point it at this installation")
            else:
                _print("notification action: registered")
    except startup.StartupError as exc:
        _print("notification action: unavailable (%s)" % exc)
    # v0.6.26, with the other registration: whether the watcher starts at the next sign-in (U5) - a Run value whose
    # interpreter or launcher is gone starts nothing, and nothing else would say so.
    good, line = _autostart_line()
    (_print if good else fail)(line)
    progress("check", 8, DOCTOR_CHECKS)
    if failed:
        _print(PROBLEM + " ".join(failed[0].split()))
    return EXIT_ERROR if failed else EXIT_OK


# What `status` (short) and `doctor` (long) say about an engine that passed its local checks, in the
# word the watcher's gate reads for it - so the engine line never contradicts the compatibility line.
_ENGINE_WORDS = {
    "verified": ("verified by the registry data in force: a real recovery on this build confirmed it",
                 "verified: its local checks pass, and the registry data in force verifies this build"),
    "checked": ("checked: local checks pass, and the maintainer's checks passed on this build",
                "checked: its local checks pass, and the registry data in force records the maintainer's "
                "checks passing on this build; no real recovery has verified it yet"),
    "structurally_compatible": (
        "compatible: local checks pass; the registry data in force does not verify this build",
        "compatible: its local checks pass - `codex queue` still offers --thread/--message - "
        "and the registry data in force does not verify this build"),
    "incompatible": ("local checks pass, but the registry data in force marks this build incompatible",
                     "its local checks pass, but the registry data in force marks this build incompatible; "
                     "nothing is sent while that data is in force"),
    "failed_here": ("a local check failed here, on a build the registry data in force vouches for",) * 2,
}
# When the registry data could not be read at all: only what the checks themselves showed.
_ENGINE_CHECKS_ONLY = ("local checks pass",
                       "its local checks pass - `codex queue` still offers --thread/--message")


def _engine_words(app, backend):
    try:
        word = compatio.engine_word(app.paths, backend.engine_version)
    except Exception:
        word = None
    return _ENGINE_WORDS.get(word, _ENGINE_CHECKS_ONLY)


def _view_status(view) -> str:
    status = view.get("status")
    words = {"ok": "report ok", "absent": "no report yet - is the watcher running?",
             "invalid": "report unreadable", "stale": "report too old - is the watcher ticking?",
             "engine_changed": "the engine changed since the last check"}
    text = words.get(status, "report unreadable")
    if status == "ok" and view.get("checked_at"):
        text += ", checked %s" % format_local(view["checked_at"])
    if view.get("acting") and view.get("acting") != view.get("overall"):
        text += "; the watcher is still acting on %s - restart it to re-check" % view["acting"]
    return text


# Said after every Reported line that says something, whichever state it is in.
_REPORTED_QUALIFIER = " (others' reports; changes nothing)"


def _reported_words(view) -> str:
    """What other people's filed reports add up to for the Codex version a view names (v0.6.10), in
    one line. Counts of reports, beside the version and never a verdict: nothing reads them to
    decide, and the line says so.

    The words are the Dashboard's (gui/DashboardCompat.cs, ReportedLine; compat.reported.* in the
    catalogs): the counts, "none yet", "could not be read", or "-" where there is nothing to say -
    a view that cannot be used or found no engine - and the dash, saying nothing, needs no
    qualifier."""
    reported = view.get("reported") if isinstance(view, dict) else None
    reported = reported if isinstance(reported, dict) else {}
    state = reported.get("state")
    if state == "reported":
        counts = {name: reported.get(name) if isinstance(reported.get(name), int) else 0
                  for name in ("worked", "failed", "neither", "both")}
        text = "worked %(worked)d, failed %(failed)d, neither %(neither)d" % counts
        if counts["both"] > 0:
            text += ", counted in both %(both)d" % counts
        return text + _REPORTED_QUALIFIER
    if state == "none_yet":
        return "none yet" + _REPORTED_QUALIFIER
    if state == "rejected":
        return "could not be read" + _REPORTED_QUALIFIER
    return "-"


def _capability_lines(view, *, only_problems=False) -> list:
    lines = []
    for name, entry in view["capabilities"].items():
        if entry["reason"] == "not_implemented":
            continue
        if only_problems and entry["state"] in (compat.COMPATIBLE, compat.CHECKED, compat.VERIFIED):
            continue
        detail = entry["reason"] + (" (%s)" % entry["registry_reason"]
                                    if entry.get("registry_reason") else "")
        lines.append("  %-26s %-12s %s" % (name, entry["state"], detail))
    return lines


def cmd_compat(args) -> int:
    """The Compatibility Registry, read-only; or an offline import into its cache."""
    app = _app(args)
    if args.import_file:
        result = compatio.import_document(app.paths, args.import_file, origin="file")
        if result["imported"]:
            try:
                WakeEvent(str(app.paths.state_dir)).signal()
            except Exception:
                pass
            _print("imported registry data #%d (cache %s)" % (result["sequence"], result["cache"]))
            return EXIT_OK
        _print("refused: %s; the existing cache was left as it was" % result["reason"])
        return EXIT_ERROR
    if args.live:
        explicit = app._codex_exe_override or os.environ.get(config.ENV_CODEX_EXE) or None
        view = compatio.live_view(app.paths, app.codex_home, explicit=explicit)
    else:
        view = compatio.reader_view(app.paths, settings=app.settings)
    if args.json:
        _print(json.dumps(view, indent=2, ensure_ascii=False, allow_nan=False))
        return EXIT_OK
    _print("compatibility    : %s (%s)" % (view["overall"], "checked now" if view.get("live")
                                             else _view_status(view)))
    _print("engine version   : %s" % (view["engine"]["version"] or "not found"))
    _print("reported         : %s" % _reported_words(view))
    data = view.get("data") or {}
    if data:
        _print("registry data    : %s (bundled %s #%s, cache %s%s)" % (
            data["source"], data["bundled"], data["bundled_sequence"], data["cache"],
            " #%s" % data["cache_sequence"] if data.get("cache_sequence") is not None else ""))
    for line in _capability_lines(view):
        _print(line)
    return EXIT_OK

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
from ..logbook import format_local
from ..store import StoreError
from ..windows import AdapterError, WakeEvent, resource_users
from .base import _app, _now, _print
from .records import _record_view


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
    try:
        value = startup.current_value()
        _print("login autostart  : %s" % ("registered" if value else "not registered"))
    except startup.StartupError:
        _print("login autostart  : unavailable")
    try:
        backend = app.backend()
        _print("codex engine     : %s" % backend.codex_exe)
        _print("engine version   : %s  (%s)" % (backend.engine_version, _engine_words(app, backend)[0]))
        identity = backend.app_identity()
        _print("ChatGPT app      : %s" % ("running (pid %d, codex server pid %d)" % (identity["pid"], identity["server"]["pid"]) if identity else "not running / not paired"))
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


def cmd_doctor(args) -> int:
    app = _app(args)
    ok = True
    try:
        backend = app.backend()
        _print("codex.exe        : %s" % backend.codex_exe)
        _print("engine version   : %s (%s)" % (backend.engine_version, _engine_words(app, backend)[1]))
    except (config.ConfigError, AdapterError) as exc:
        _print("codex.exe        : FAIL (%s)" % exc)
        return EXIT_ERROR
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
            ok = False
    report = compatio.reader_view(app.paths, settings=app.settings)
    _print("watcher's report : %s (%s)" % (report["overall"], _view_status(report)))
    # Beside the version, and never a verdict: `ok` is not touched by it.
    _print("reported         : %s" % _reported_words(live if live is not None else report))
    _print("codex home       : %s" % app.codex_home)
    identity = backend.app_identity()
    if identity:
        _print("ChatGPT app      : main pid %d, codex app-server pid %d" % (identity["pid"], identity["server"]["pid"]))
    else:
        ok = False
        _print("ChatGPT app      : not running or not paired with the configured engine")
    running = app.watcher_running()
    _print("watcher mutex    : %s" % {True: "held by a running watcher", False: "free", None: "unavailable"}[running])
    try:
        lock_dir = app.codex_home / "thread-writer-locks"
        probe = lock_dir / ".coordination.lock"
        if probe.exists():
            resource_users(probe)
            _print("restart manager  : ok")
        else:
            _print("restart manager  : skipped (no coordination lock file)")
    except AdapterError as exc:
        ok = False
        _print("restart manager  : FAIL (%s)" % exc)
    try:
        app.source().latest_failures(_now() - 60)
        _print("local history    : readable")
    except Exception as exc:
        ok = False
        _print("local history    : FAIL (%s)" % type(exc).__name__)
    # The notification's button goes through a registered URL protocol. If its target has
    # gone - an installation moved, or a temporary home that no longer exists - the button
    # silently does nothing, and nothing else in the product would ever mention it.
    try:
        registered = startup.protocol_value()
        if not registered:
            _print("notification action: not registered (the button would do nothing)")
        else:
            argv = startup.parse_command(registered)
            target = Path(argv[1]) if len(argv) >= 2 else None
            if target is not None and not target.exists():
                ok = False
                _print("notification action: registered, but its target is missing")
                _print("                     re-run install to point it at this installation")
            else:
                _print("notification action: registered")
    except startup.StartupError as exc:
        _print("notification action: unavailable (%s)" % exc)
    return EXIT_OK if ok else EXIT_ERROR


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


def _reported_words(view) -> str:
    """What other people's filed reports add up to for the Codex version a view names (v0.6.10), in
    one line. Counts of reports, beside the version and never a verdict: nothing reads them to
    decide, and the line says so."""
    reported = view.get("reported") if isinstance(view, dict) else None
    reported = reported if isinstance(reported, dict) else {}
    state = reported.get("state")
    if state == "reported":
        counts = {name: reported.get(name) if isinstance(reported.get(name), int) else 0
                  for name in ("worked", "failed", "neither", "both")}
        text = "worked %(worked)d, failed %(failed)d, neither %(neither)d" % counts
        if counts["both"] > 0:
            text += ", counted in both %(both)d" % counts
        return text + " (others' reports; changes nothing)"
    if state == "none_yet":
        return "none yet (others' reports; changes nothing)"
    if state == "rejected":
        return "the counts this version carries could not be read"
    return "unavailable"


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

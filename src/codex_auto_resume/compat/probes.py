"""The local checks: the source's schema and the App Server's methods, and which engine
is in force.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

from .. import config
from .. import compat
from ..codex import appserver
from .files import (path_digest)
from .cache import (_coerce, _columns, _newest)

def source_checks(source) -> dict:
    """E6/E7 and the two directories, through the read-only source adapter's own connection.

    Column names only. A database that is not there, or cannot be opened, is UNAVAILABLE - but a history not made yet,
    in a home whose state holds no conversation, is NOT_APPLICABLE (v0.6.26 final); one that opens but lacks a column
    the adapter reads is a FAIL - Codex's schema moved.
    """
    checks = {name: compat.UNAVAILABLE for name in
              ("state_schema", "history_schema", "queue_schema", "projection_table",
               "sessions_directory", "lock_directory")}
    try:
        home = Path(source.home)
        if not home.is_dir():
            return checks
    except (AttributeError, TypeError, OSError, ValueError):
        return checks
    threads = None
    for kind, check in (("state", "state_schema"), ("history", "history_schema"),
                        ("queue", "queue_schema")):
        connection = None
        try:
            path, tables = _newest(home, kind)
            if path is None:
                if kind == "history" and threads is False:
                    # v0.6.26 final: Codex makes its history with the first conversation it saves, so a home whose
                    # newest state database was read and holds none has no history yet - "not yet", as a lock folder
                    # is. With a conversation it stays unavailable: there Codex moved, renamed or dropped it.
                    checks["history_schema"] = checks["projection_table"] = compat.NOT_APPLICABLE
                continue
            connection = source._connect(Path(path).resolve())
            missing = any(not required <= _columns(connection, table)
                          for table, required in tables.items())
            checks[check] = compat.FAIL if missing else compat.PASS
            if kind == "state" and not missing:
                # Whether the newest state database holds a conversation - a home that has one has opened it, so its
                # lock folder is expected (below). Only whether a row exists is read, never a column of one; a read
                # that fails leaves it unknown (None), the check as it always was.
                try:
                    threads = connection.execute("SELECT 1 FROM threads LIMIT 1").fetchone() is not None
                except Exception:
                    threads = None
            if kind == "history":
                found = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='thread_history_projection_state'").fetchone()
                checks["projection_table"] = (
                    compat.PASS if found and "next_rollout_byte_offset" in
                    _columns(connection, "thread_history_projection_state") else compat.FAIL)
        except Exception:
            checks[check] = compat.UNAVAILABLE
            if kind == "history":
                checks["projection_table"] = compat.UNAVAILABLE
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
    for name, directory in (("sessions_directory", "sessions"),
                            ("lock_directory", "thread-writer-locks")):
        try:
            # Absent is not a failure: a Codex that has never opened a conversation has
            # neither. It only means the capability cannot be established yet.
            # v0.6.26 (update resilience #4): but a home whose newest state database holds a conversation and keeps no
            # lock folder is one where Codex moved, renamed or dropped it, and whether a conversation is open can no
            # longer be read there (codex/transport.py loaded answers unknown): a FAIL, not "not yet".
            there = (home / directory).is_dir()
            checks[name] = (compat.PASS if there else
                            compat.FAIL if name == "lock_directory" and threads else compat.NOT_APPLICABLE)
        except OSError:
            checks[name] = compat.UNAVAILABLE
    return checks


def protocol_check(method) -> str:
    """v0.6.26 (update resilience, proposal 7): what Codex's helper last met for `method` in this process
    (codex/appserver.py last_result), where it has been asked: FAIL where Codex answered in a way this version does
    not know or said it does not know the method (appserver.BROKEN), PASS where it answered - a refusal of a method it
    knows (appserver.REFUSED: a signed-out account, its backend failing) included, which says nothing of the method
    and must not fail what stands on it (review K2). Where it has not been asked here yet - a reader of its own, a
    watcher that has had no usage to read - or did not answer at all, the method this product may ask is a PASS as it
    always was, and one it may not ask a FAIL: a report says no less than it said before."""
    if method not in appserver.PROTOCOL_METHODS:
        return compat.FAIL
    return compat.FAIL if appserver.last_result(method) in appserver.BROKEN else compat.PASS


def api_checks() -> dict:
    from .. import windows
    return {
        "restart_manager": compat.PASS if windows.restart_manager_available() else compat.UNAVAILABLE,
        "protocol_usage_method": protocol_check("account/rateLimits/read"),
        "protocol_delete_method": protocol_check("thread/queue/delete"),
    }


def _engine_part(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {name: _coerce(raw.get(name)) for name in ("official_location", "version_runs", "queue_flags")}


def server_check(backend) -> str:
    """#58's follow-up: the app_server_matched check, read off the last look `backend` already took (Backend.app_look),
    so it starts no process and asks nothing: PASS on a server paired, FAIL on an app that runs with none, and otherwise
    UNAVAILABLE, "not checked": the app is not running, nothing has looked yet (a backend the watcher has not needed the
    app for, or a per-call reader's), or the look is older than a report may be."""
    look, at = getattr(backend, "app_look", None), getattr(backend, "app_looked_at", None)
    if look not in ("matched", "unmatched") or not isinstance(at, (int, float)):
        return compat.UNAVAILABLE
    if time.monotonic() - at > compat.REPORT_MAX_AGE:
        return compat.UNAVAILABLE
    return compat.PASS if look == "matched" else compat.FAIL


def engine_from_backend(backend):
    """(checks, engine) for the backend the watcher is driving."""
    try:
        raw = backend.engine_checks()
    except Exception:
        raw = None
    checks = _engine_part(raw)
    checks["single_candidate"] = compat.PASS
    checks["app_server_matched"] = server_check(backend)
    raw = raw if isinstance(raw, dict) else {}
    signature = raw.get("signature")
    if not (isinstance(signature, (list, tuple)) and len(signature) == 2
            and all(isinstance(part, int) and not isinstance(part, bool) and part >= 0
                    for part in signature)):
        signature = None
    try:
        exe = backend.codex_exe
    except Exception:
        exe = None
    digest = path_digest(exe) if isinstance(exe, (str, os.PathLike)) else None
    engine = {"found": digest is not None, "version": compat.safe_version(raw.get("version")),
              "signature": list(signature) if signature else None,
              "path_digest": digest, "candidates": 1}
    return checks, engine


def engine_from_discovery(discovery, *, candidates=None):
    """(checks, engine) when discovery refused every candidate - so a refusal by a failed
    local check can finally be reported as INCOMPATIBLE instead of UNKNOWN."""
    probed = {path: _engine_part(result) for path, result in (discovery or {}).items()}
    raw = {path: result if isinstance(result, dict) else {} for path, result in (discovery or {}).items()}
    count = len(probed) if candidates is None else candidates
    if not probed:
        checks = {name: compat.UNAVAILABLE for name in
                  ("official_location", "version_runs", "queue_flags", "single_candidate")}
        return checks, {"found": False, "version": None, "signature": None, "path_digest": None,
                        "candidates": count}
    if len(probed) == 1:
        path, checks = next(iter(probed.items()))
        checks = dict(checks, single_candidate=compat.PASS)
        signature = raw[path].get("signature")
        return checks, {"found": True, "version": compat.safe_version(raw[path].get("version")),
                        "signature": list(signature) if isinstance(signature, (list, tuple)) else None,
                        "path_digest": path_digest(path), "candidates": count}
    # Several candidates, and not exactly one usable: per check, PASS only if every one
    # passed, FAIL only if every one failed, and otherwise it cannot be established.
    checks = {}
    for name in ("official_location", "version_runs", "queue_flags"):
        results = {entry[name] for entry in probed.values()}
        checks[name] = (compat.PASS if results == {compat.PASS} else
                        compat.FAIL if results == {compat.FAIL} else compat.UNAVAILABLE)
    checks["single_candidate"] = compat.UNAVAILABLE
    versions = {raw[path].get("version") for path in probed}
    version = versions.pop() if len(versions) == 1 else None
    return checks, {"found": False, "version": compat.safe_version(version), "signature": None,
                    "path_digest": None, "candidates": count}


def _candidate_paths(explicit=None) -> list:
    found = []
    if explicit:
        try:
            found.append(Path(explicit).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            pass
    try:
        found += config.candidate_codex_exes()
    except (config.ConfigError, OSError):
        pass
    return found


def _served_engines():
    """v0.6.21 (#58): the official engines the ChatGPT app main runs as its children (codex/pairing.py app_engines,
    official_engine), which can sit outside bin, signed by OpenAI. A generator, so that the process list is read
    only where the candidates searched before it did not answer; nothing where it cannot be read."""
    from .. import windows
    try:
        served = list(windows.app_engines())
    except Exception:
        return
    yield from (Path(path) for path in served if windows.official_engine(path)[0])


def _package_engines():
    """v0.6.26 final (live acceptance R2b): the official engines in the folders of the Codex app's package installed
    for this account (codex/pairing.py package_engines, official_engine), whether or not the app runs - the one the
    watcher took up from the app (#58) is still the one it drives after the app closes. A generator, as
    `_served_engines` is, so that a signature is read only where the candidates searched before did not answer, and of
    nothing but the engine a report could name; nothing where the package manager cannot answer."""
    from .. import windows
    try:
        found = list(windows.package_engines())
    except Exception:
        return
    yield from (Path(path) for path in found if windows.official_engine(path)[0])


def discover(codex_home, explicit=None):
    """Discovery as the watcher does it, recording every candidate's checks. For per-call
    readers that have no watcher backend to ask. Returns (backend or None, discovery).

    As the watcher does it since v0.6.13 too: of several builds that pass, the one the ChatGPT
    app runs as its Codex server, if exactly one is (config.discover_codex_exe)."""
    from .. import windows
    record = {}

    def compatible(path):
        probe = windows.Backend(codex_home, path)
        try:
            probe._compatible()
        finally:
            record[str(path)] = probe.last_checks()

    try:
        chosen = config.discover_codex_exe(explicit, compatible, running=windows.app_engines)
    except Exception:
        return None, record
    backend = windows.Backend(codex_home, chosen)
    backend._compatible()
    return backend, record

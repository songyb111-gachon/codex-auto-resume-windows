"""The local checks: the source's schema and the App Server's methods, and which engine
is in force.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import config
from .. import compat
from .files import (path_digest)
from .cache import (_coerce, _columns, _newest)

def source_checks(source) -> dict:
    """E6/E7 and the two directories, through the read-only source adapter's own connection.

    Column names only. A database that is not there, or cannot be opened, is UNAVAILABLE;
    one that opens but lacks a column the adapter reads is a FAIL - Codex's schema moved.
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
    for kind, check in (("state", "state_schema"), ("history", "history_schema"),
                        ("queue", "queue_schema")):
        connection = None
        try:
            path, tables = _newest(home, kind)
            if path is None:
                continue
            connection = source._connect(Path(path).resolve())
            missing = any(not required <= _columns(connection, table)
                          for table, required in tables.items())
            checks[check] = compat.FAIL if missing else compat.PASS
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
            checks[name] = compat.PASS if (home / directory).is_dir() else compat.NOT_APPLICABLE
        except OSError:
            checks[name] = compat.UNAVAILABLE
    return checks


def api_checks() -> dict:
    from .. import windows
    return {
        "restart_manager": compat.PASS if windows.restart_manager_available() else compat.UNAVAILABLE,
        "protocol_usage_method": (compat.PASS if "account/rateLimits/read" in windows.PROTOCOL_METHODS
                                  else compat.FAIL),
        "protocol_delete_method": (compat.PASS if "thread/queue/delete" in windows.PROTOCOL_METHODS
                                   else compat.FAIL),
    }


def _engine_part(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {name: _coerce(raw.get(name)) for name in ("official_location", "version_runs", "queue_flags")}


def engine_from_backend(backend):
    """(checks, engine) for the backend the watcher is driving."""
    try:
        raw = backend.engine_checks()
    except Exception:
        raw = None
    checks = _engine_part(raw)
    checks["single_candidate"] = compat.PASS
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


def discover(codex_home, explicit=None):
    """Discovery as the watcher does it, recording every candidate's checks. For per-call
    readers that have no watcher backend to ask. Returns (backend or None, discovery)."""
    from .. import windows
    record = {}

    def compatible(path):
        probe = windows.Backend(codex_home, path)
        try:
            probe._compatible()
        finally:
            record[str(path)] = probe.last_checks()

    try:
        chosen = config.discover_codex_exe(explicit, compatible)
    except Exception:
        return None, record
    backend = windows.Backend(codex_home, chosen)
    backend._compatible()
    return backend, record

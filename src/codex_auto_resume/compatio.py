"""Codex Compatibility Registry: its files, its local checks, and the watcher's evaluator.

`compat.py` is the model and knows nothing about disks or processes; this is everything
around it. Three files, each with one rule:

* the **bundled baseline**, `data/codex_compat.json`, ships inside the release and is
  authenticated by the release itself (the pinned archive digest and its attestation);
* the **cache**, `<home>/config/compat-cache.json`, holds registry data a person asked for -
  the Diagnostics refresh or an update check. It has exactly one writer, `import_document`,
  which is the validator: `scripts/bootstrap.ps1` downloads to a temporary file and hands it
  here, so no unvalidated byte ever lands beside the settings. It is validated again on every
  read and never trusted because it was written here. A cache that fails is ignored, never
  deleted, so a person can look at it;
* the **report**, `<home>/config/compatibility.json`, is derived and regenerable. Its one
  writer is the watcher, under the home lock it already holds, written atomically. Every
  reader - the Dashboard through the bridge, the command line, MCP, the diagnostics bundle -
  validates it on read exactly as the cache is validated, and checks that it still describes
  the engine on disk: a report bound to a binary that has since changed or vanished, or one
  older than a ticking watcher could leave it, is UNKNOWN for every capability.

Nothing here opens a socket. The only fetch is the bootstrap's, and it happens only when a
person asks (`run_refresh` starts it for the Diagnostics button). Codex's own state is read
through the read-only source adapter's connection (`mode=ro`, `query_only`), for its schema
only - column names, never a row.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from . import compat, config, machine
from . import source as codex_source

BUNDLED = Path(__file__).resolve().parent / "data" / "codex_compat.json"
REFRESH_TIMEOUT_SECONDS = 150
# What `bootstrap.ps1 -Compatibility` answers with, beside its one `compatibility:` line.
REFRESH_EXIT = {"refreshed": 0, "unavailable": 12, "refused": 13}
REFRESH_ANSWERS = ("refreshed", "refused", "unavailable", "incomplete", "failed")


# ------------------------------------------------------------------------------ helpers
def _read_capped(path: Path, limit: int) -> bytes:
    """The file's bytes, refusing a link or anything over `limit` before reading it."""
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            raise compat.DocumentError("unreadable")
        if path.stat().st_size > limit:
            raise compat.DocumentError("too_large")
        data = path.read_bytes()
    except OSError:
        raise compat.DocumentError("unreadable") from None
    if len(data) > limit:
        raise compat.DocumentError("too_large")
    return data


def _stamp(path: Path):
    try:
        status = Path(path).stat()
    except OSError:
        return None
    return (status.st_size, status.st_mtime_ns)


def write_json_atomic(path: Path, value, prefix: str) -> None:
    """temp + fsync + os.replace, the settings file's pattern: a reader sees the old file or
    the new one, never half of one, and a planted link at a predictable name is never
    followed. Raises OSError; the caller decides what a failed write costs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=prefix,
                                             suffix=".json.tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def path_digest(path):
    """SHA-256 of the resolved, case-folded path: enough to tell which binary a report
    describes without writing the path - which holds the Windows user name - anywhere."""
    try:
        resolved = os.path.normcase(str(Path(path).resolve()))
    except (OSError, TypeError, ValueError, RuntimeError):
        return None
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def _signature(path):
    stamp = _stamp(path)
    return list(stamp) if stamp else None


def product_version() -> str:
    version = config.version()
    return version if compat.product_key(version) else "unknown"


# ------------------------------------------------------------------------------ bundled
def load_bundled(path: Path = BUNDLED, *, product=None, now=None):
    """(document or None, one of compat.BUNDLED_STATES).

    A missing file is `missing`, not a failure: the bundled data can only ever restrict or
    label, so without it every capability falls back to the local checks alone - which is
    what the product did before the registry existed.
    """
    if not Path(path).is_file():
        return None, "missing"
    try:
        document = compat.parse_document(_read_capped(path, compat.MAX_DOCUMENT_BYTES))
    except compat.DocumentError:
        return None, "rejected"
    standing = compat.document_standing(document, product=product or product_version(),
                                        now=now, role="bundled")
    return (document, "ok") if standing == "ok" else (None, "rejected")


def bundled_verified_versions() -> tuple:
    document, state = load_bundled()
    return compat.verified_versions(document) if state == "ok" else ()


# ------------------------------------------------------------------------------ the cache
def _cache_empty(state="absent") -> dict:
    return {"document": None, "state": state, "sequence": None, "fetched_at": None,
            "origin": None, "raw": None, "validated": None}


def read_cache(path: Path, *, bundled=None, product=None, now=None) -> dict:
    """The cache as a reader may use it: validated whole, then judged against the bundled
    baseline, the product version and the clock. `document` is set only when its data may
    apply (compat.RESTRICTING_STATES: `ok`; `expired` and `from_the_future`, whose
    INCOMPATIBLE data still applies); `validated` keeps the document for `judge_cache`."""
    if not Path(path).exists():
        return _cache_empty("absent")
    try:
        envelope = compat.decode(_read_capped(path, compat.MAX_CACHE_BYTES), compat.MAX_CACHE_BYTES)
        if (not isinstance(envelope, dict) or envelope.get("format") != compat.CACHE_FORMAT
                or envelope.get("origin") not in compat.CACHE_ORIGINS):
            return _cache_empty("rejected")
        fetched = envelope.get("fetched_at")
        if not machine.epoch(fetched, compat.EPOCH_MIN, compat.EPOCH_MAX, finite=False):
            return _cache_empty("rejected")
        document = compat.validate_document(envelope.get("document"))
    except compat.DocumentError:
        return _cache_empty("rejected")
    cache = {"document": None, "state": None, "sequence": document["sequence"],
             "fetched_at": float(fetched), "origin": envelope["origin"],
             "raw": envelope.get("document"), "validated": document}
    return judge_cache(cache, bundled=bundled, product=product, now=now)


def judge_cache(cache, *, bundled=None, product=None, now=None) -> dict:
    """A cache `read_cache` returned, judged again at `now`.

    A cache's standing depends on the clock as well as the file: it expires, and a document
    dated after a clock that was behind comes into force once the clock is right. A reader
    that keeps a cache - the watcher, for weeks - asks this on every tick instead of waiting
    for the file to change, which it never does on its own."""
    validated = cache.get("validated") if isinstance(cache, dict) else None
    if validated is None:
        return cache
    now = time.time() if now is None else now
    standing = compat.document_standing(validated, product=product or product_version(),
                                        bundled=bundled, now=now)
    return dict(cache, state=standing,
                document=validated if standing in compat.RESTRICTING_STATES else None)


def _sources_of(bundled, cache) -> list:
    """The documents in force, as compat.evidence_for weighs them: every one restricts;
    only the bundled baseline and a cache in a trusting standing may verify."""
    return [("bundled", bundled, True),
            ("cache", cache.get("document"), cache.get("state") in compat.TRUSTING_STATES)]


def data_in_force(paths, *, product=None, now=None) -> list:
    """The bundled baseline and the cache, read and judged now, as the watcher weighs them."""
    now = time.time() if now is None else now
    product = product or product_version()
    bundled, _ = load_bundled(product=product, now=now)
    cache = read_cache(paths.compat_cache_file, bundled=bundled, product=product, now=now)
    return _sources_of(bundled, cache)


def engine_word(paths, version, *, now=None) -> str:
    """What the registry data in force says about an engine that passed its local checks:
    the same word the watcher's gate reads for it (compat.accepted_word). For `status`,
    `doctor` and the start-up log, which used to read the bundled baseline alone."""
    return compat.accepted_word(version, data_in_force(paths, now=now))


def import_document(paths, file, *, origin="file", product=None, now=None) -> dict:
    """Validate one downloaded or hand-supplied registry document and, only if it passes,
    make it the cache. The only writer of `compat-cache.json`.

    Returns ``{"imported", "reason", "sequence", "cache"}`` - codes and numbers only. A
    refusal leaves the existing cache exactly as it was.
    """
    now = time.time() if now is None else now
    product = product or product_version()
    refused = lambda reason, sequence=None: {"imported": False, "reason": reason,  # noqa: E731
                                             "sequence": sequence, "cache": None}
    if origin not in compat.CACHE_ORIGINS:
        return refused("invalid_field")
    source = Path(file) if isinstance(file, (str, os.PathLike)) else None
    if source is None or source.suffix.lower() != ".json":
        return refused("not_a_json_file")
    try:
        raw = compat.decode(_read_capped(source, compat.MAX_DOCUMENT_BYTES))
        document = compat.validate_document(raw)
    except compat.DocumentError as exc:
        return refused(exc.code)
    bundled, _ = load_bundled(product=product, now=now)
    standing = compat.document_standing(document, product=product, bundled=bundled, now=now)
    if standing == "from_newer_product":
        return refused("from_newer_product", document["sequence"])
    if standing == "superseded":
        return refused("rollback", document["sequence"])
    if standing == "from_the_future":
        # Not taken in: what is in force now stays in force. A reader keeps restricting on
        # a cache that only looks future-dated because its clock was later set back.
        return refused("from_the_future", document["sequence"])
    if standing == "rejected":
        return refused("invalid_field", document["sequence"])
    current = read_cache(paths.compat_cache_file, bundled=bundled, product=product, now=now)
    if current["sequence"] is not None and current["state"] != "rejected" \
            and document["sequence"] < current["sequence"]:
        return refused("rollback", document["sequence"])
    envelope = {"format": compat.CACHE_FORMAT, "fetched_at": float(now), "origin": origin,
                "document": raw}
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    if len(encoded.encode("utf-8")) > compat.MAX_CACHE_BYTES:
        return refused("too_large", document["sequence"])
    try:
        paths.ensure()
        write_json_atomic(paths.compat_cache_file, envelope, "compat-cache.")
    except (OSError, config.ConfigError):
        return refused("write_failed", document["sequence"])
    return {"imported": True, "reason": None, "sequence": document["sequence"], "cache": standing}


# ------------------------------------------------------------------------------ local checks
def _coerce(result):
    return result if result in compat.RESULTS else compat.UNAVAILABLE


def _newest(home: Path, kind: str):
    pattern, tables = codex_source.DB_KINDS[kind]
    candidates = []
    for entry in home.iterdir():
        match = pattern.fullmatch(entry.name)
        if match and entry.is_file() and not entry.is_symlink():
            candidates.append((int(match.group(1)), entry))
    if not candidates:
        return None, tables
    return sorted(candidates, key=lambda item: -item[0])[0][1], tables


def _columns(connection, table):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        return set()
    return {row[1] for row in connection.execute("PRAGMA table_info(%s)" % table)}


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
    from . import windows
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
    from . import windows
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


# ------------------------------------------------------------------------------ the report
def assemble(*, engine_checks, engine, other_checks, bundled, bundled_state, cache,
             product, now, acting=None) -> dict:
    checks = dict(other_checks)
    checks.update(engine_checks)
    capabilities = compat.evaluate(checks, version=engine.get("version"),
                                   sources=_sources_of(bundled, cache))
    in_force = cache.get("state") in compat.RESTRICTING_STATES
    data = {"bundled": bundled_state,
            "bundled_sequence": bundled["sequence"] if bundled else None,
            "cache": cache.get("state", "absent"), "cache_sequence": cache.get("sequence"),
            "cache_origin": cache.get("origin"), "fetched_at": cache.get("fetched_at"),
            "source": "cache" if in_force else "bundled" if bundled else "none",
            "expired": cache.get("state") == "expired"}
    engine = {key: engine.get(key) for key in ("found", "version", "signature", "path_digest",
                                               "candidates")}
    return compat.build_report(checked_at=now, product=product, engine=engine, data=data,
                               checks=checks, capabilities=capabilities, acting=acting)


def live_report(paths, codex_home, *, backend=None, discovery=None, explicit=None,
                source=None, now=None) -> dict:
    """A fresh evaluation for a reader with no watcher to ask. Never written anywhere:
    the report file has one writer, and it is the watcher."""
    now = time.time() if now is None else now
    product = product_version()
    if backend is None and discovery is None:
        backend, discovery = discover(codex_home, explicit)
    if backend is not None:
        engine_checks, engine = engine_from_backend(backend)
    else:
        engine_checks, engine = engine_from_discovery(discovery,
                                                      candidates=len(_candidate_paths(explicit)))
    if source is None:
        source = codex_source.LocalSource(codex_home)
    bundled, bundled_state = load_bundled(product=product, now=now)
    cache = read_cache(paths.compat_cache_file, bundled=bundled, product=product, now=now)
    return assemble(engine_checks=engine_checks, engine=engine,
                    other_checks={**source_checks(source), **api_checks()},
                    bundled=bundled, bundled_state=bundled_state, cache=cache,
                    product=product, now=now)


def live_view(*args, **kwargs) -> dict:
    view = compat.view_of(live_report(*args, **kwargs))
    view["live"] = True
    return view


def read_report(paths, *, now=None):
    """(report or None, status). Validated on read: byte cap, hardened parse, key allowlist,
    closed vocabulary - a report that fails any of it is `invalid`, not rendered."""
    path = Path(paths.compat_report_file)
    if not path.exists():
        return None, "absent"
    try:
        value = compat.decode(_read_capped(path, compat.MAX_REPORT_BYTES), compat.MAX_REPORT_BYTES)
    except compat.DocumentError:
        return None, "invalid"
    report = compat.validate_report(value, now=time.time() if now is None else now)
    return (report, "ok") if report is not None else (None, "invalid")


def _binding_holds(report, explicit=None) -> bool:
    engine = report["engine"]
    if engine["found"]:
        if not engine["path_digest"] or engine["signature"] is None:
            return False
        for candidate in _candidate_paths(explicit):
            if path_digest(candidate) == engine["path_digest"]:
                return _signature(candidate) == engine["signature"]
        return False
    # Nothing was found when the report was made; if something is there now, the report
    # no longer describes this machine.
    return len(_candidate_paths(explicit)) == (engine.get("candidates") or 0)


def read_view(paths, *, now=None, explicit=None) -> dict:
    """The report as every front end shows it: validated, still bound to the engine on disk,
    and fresh - or UNKNOWN for every capability, with the reason it could not be used."""
    now = time.time() if now is None else now
    report, status = read_report(paths, now=now)
    if report is None:
        view = compat.unusable_view(status)
    elif now - report["checked_at"] > compat.REPORT_MAX_AGE:
        view = compat.unusable_view("stale", data=report["data"], checked_at=report["checked_at"],
                                    engine=report["engine"])
    elif not _binding_holds(report, explicit):
        view = compat.unusable_view("engine_changed", data=report["data"],
                                    checked_at=report["checked_at"], engine=report["engine"])
    else:
        view = compat.view_of(report)
    view["live"] = False
    return view


def reader_view(paths, *, now=None, settings=None) -> dict:
    """`read_view` with the engine a reader should bind against: the one the settings name,
    or the environment, or discovery."""
    explicit = None
    try:
        explicit = (settings or {}).get("codex_exe") or os.environ.get(config.ENV_CODEX_EXE) or None
    except AttributeError:
        explicit = None
    return read_view(paths, now=now, explicit=explicit)


# ------------------------------------------------------------------------------ the watcher
class Evaluator:
    """The watcher's side: recompute when something changed, write the report, and answer
    the one word the engine's gate reads.

    The word the gate reads - `acting` - is evaluated for the backend the watcher is driving,
    from the checks that backend passed when it was accepted, plus the registry data in
    force. That is deliberate. The engine has always decided on the verdict it started
    with, and a gate that changed its answer under a running engine (a binary that vanished
    mid-update, say) would move decisions - supersessions and budget stops - that happen
    after it. So the gate's answer moves only with the registry data a person imported,
    while the report says what is true now, and says so when the two differ.
    """

    def __init__(self, paths, codex_home, *, product=None, log=None, clock=time.time,
                 recompute=compat.RECOMPUTE_SECONDS, source=None, explicit=None):
        self.paths = paths
        self.explicit = explicit
        self.codex_home = Path(codex_home)
        self.product = product or product_version()
        self.log = log or (lambda *args: None)
        self.clock = clock
        self.recompute = recompute
        self.source = source
        self.bundled, self.bundled_state = load_bundled(product=self.product, now=clock())
        self.cache = _cache_empty()
        self._cache_stamp = ("never",)
        self._engine_key = None
        self._backend_seen = None
        self._last_at = None
        self.report = None
        self.acting = None
        self._said = None
        self._write_failed = False

    def _sources(self):
        return _sources_of(self.bundled, self.cache)

    def acting_for(self, backend) -> str:
        """The gate's word for a backend that exists: its accepted checks all passed."""
        return compat.accepted_word(getattr(backend, "engine_version", None), self._sources())

    def _engine_key_of(self, backend, discovery):
        if backend is not None:
            try:
                return ("backend", id(backend), _stamp(backend.codex_exe))
            except Exception:
                return ("backend", id(backend), None)
        items = []
        for path, result in sorted((discovery or {}).items()):
            result = result if isinstance(result, dict) else {}
            items.append((path, repr(result.get("signature")),
                          tuple(_coerce(result.get(name)) for name in
                                ("official_location", "version_runs", "queue_flags"))))
        return ("discovery", tuple(items))

    def tick(self, backend, discovery=None) -> str:
        """Called once per watcher tick, before the engine ticks. Returns the gate's word."""
        now = self.clock()
        stamp = _stamp(self.paths.compat_cache_file)
        cache_changed = stamp != self._cache_stamp
        if cache_changed:
            self.cache = read_cache(self.paths.compat_cache_file, bundled=self.bundled,
                                    product=self.product, now=now)
            self._cache_stamp = stamp
        else:
            # The file did not change, but time did: the cache may have expired, or a clock
            # that was behind may have caught up with it. Judged in memory, every tick, so
            # the gate never keeps trusting data past its expiry.
            judged = judge_cache(self.cache, bundled=self.bundled, product=self.product, now=now)
            if judged.get("state") != self.cache.get("state"):
                self.cache = judged
                cache_changed = True
        engine_key = self._engine_key_of(backend, discovery)
        due = (self.report is None or cache_changed or engine_key != self._engine_key
               or self._last_at is None or now - self._last_at >= self.recompute)
        if due:
            if backend is not None:
                engine_checks, engine = engine_from_backend(backend)
            else:
                engine_checks, engine = engine_from_discovery(
                    discovery, candidates=len(_candidate_paths(self.explicit)))
            source = self.source or codex_source.LocalSource(self.codex_home)
            report = assemble(engine_checks=engine_checks, engine=engine,
                              other_checks={**source_checks(source), **api_checks()},
                              bundled=self.bundled, bundled_state=self.bundled_state,
                              cache=self.cache, product=self.product, now=now)
            acting = self.acting_for(backend) if backend is not None else report["overall"]
            self.report = dict(report, acting=acting)
            self._engine_key, self._last_at = engine_key, now
            self._write()
        else:
            acting = self.acting_for(backend) if backend is not None else self.report["overall"]
            if acting != self.report.get("acting"):
                self.report = dict(self.report, acting=acting)
                self._write()
        self.acting = acting
        self._say()
        return acting

    def _write(self):
        try:
            write_json_atomic(self.paths.compat_report_file, self.report, "compatibility.")
            self._write_failed = False
        except OSError:
            if not self._write_failed:
                self.log("compatibility report could not be written; readers will show unknown")
            self._write_failed = True

    def _say(self):
        """One log line whenever what is known changes: codes and the version string only."""
        report = self.report
        failing = sorted("%s=%s/%s" % (name, entry["state"], entry["reason"])
                         for name, entry in report["capabilities"].items()
                         if entry["state"] in (compat.INCOMPATIBLE, compat.UNKNOWN)
                         and entry["reason"] != "not_implemented")
        said = (report.get("acting"), report["overall"], report["engine"]["version"],
                report["data"]["cache"], tuple(failing))
        if said == self._said:
            return
        self._said = said
        self.log("compatibility: acting %s, checked %s (engine %s; data %s, cache %s)%s" % (
            report.get("acting"), report["overall"], report["engine"]["version"] or "not found",
            report["data"]["source"], report["data"]["cache"],
            "; not established: " + ", ".join(failing) if failing else ""))


# ------------------------------------------------------------------------------ the refresh
def run_refresh(home, *, script=None, timeout=REFRESH_TIMEOUT_SECONDS, runner=None) -> dict:
    """Start the one fetch there is: `scripts/bootstrap.ps1 -Compatibility`, for the
    Diagnostics button. The script downloads from its one constant URL to a temporary file
    and hands it to `import_document` through the bridge; this reads back its one line.

    The line and the exit code have to agree, as the update check's do; a disagreement is
    `failed`, never guessed into an answer.
    """
    runner = runner or subprocess.run
    script = Path(script) if script else config.PROJECT_ROOT / "scripts" / "bootstrap.ps1"
    powershell = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
                  / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    answer = {"answer": "failed", "sequence": None, "reason": None}
    if not script.is_file() or not powershell.is_file():
        return dict(answer, answer="incomplete")
    environment = dict(os.environ, CODEX_AUTO_RESUME_PLUGIN_HOME=str(Path(home)))
    try:
        done = runner([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                       "Bypass", "-File", str(script), "-Compatibility"],
                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                      text=True, encoding="utf-8", errors="replace", timeout=timeout,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False,
                      env=environment)
    except subprocess.TimeoutExpired:
        return dict(answer, answer="unavailable")
    except (OSError, ValueError, subprocess.SubprocessError):
        return answer
    line = None
    for raw in (done.stdout or "").splitlines():
        if raw.strip().startswith("compatibility: "):
            line = raw.strip()[len("compatibility: "):].split()
    if not line:
        return answer
    said = line[0]
    if said not in REFRESH_EXIT or REFRESH_EXIT[said] != done.returncode:
        return answer
    result = dict(answer, answer=said)
    if said == "refreshed" and len(line) > 1 and line[1].isdigit():
        result["sequence"] = int(line[1])
    if said == "refused" and len(line) > 1 and line[1] in compat.IMPORT_REASONS:
        result["reason"] = line[1]
    return result

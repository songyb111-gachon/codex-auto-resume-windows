"""A live report on request, and the view a reader - the window, the panel - may see.
"""
from __future__ import annotations

import os
from pathlib import Path
import time

from .. import config
from .. import compat
from .. import codex as codex_source
from . import files, probes
from .files import (_read_capped, _signature, path_digest, product_version)
from .cache import (_sources_of, read_cache)
from .probes import (_candidate_paths, discover, engine_from_backend, engine_from_discovery)

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
    bundled, bundled_state = files.load_bundled(product=product, now=now)
    cache = read_cache(paths.compat_cache_file, bundled=bundled, product=product, now=now)
    return assemble(engine_checks=engine_checks, engine=engine,
                    other_checks={**probes.source_checks(source), **probes.api_checks()},
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

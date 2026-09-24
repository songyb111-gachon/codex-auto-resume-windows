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

Since v0.6.10-alpha this is a front, and the io half of the registry is in compat/:
files.py, cache.py, probes.py, views.py and evaluator.py. Every name the module had is
re-exported here, so `compatio.X` reads as it did - but a patch on one of these names
reaches the module that looks it up, not this one.
"""
from __future__ import annotations

from .compat.files import (BUNDLED, REFRESH_ANSWERS, REFRESH_EXIT, REFRESH_TIMEOUT_SECONDS,
                           _read_capped, _signature, _stamp, bundled_verified_versions,
                           load_bundled, path_digest, product_version, write_json_atomic)  # noqa: F401
from .compat.cache import (_cache_empty, _coerce, _columns, _newest, _sources_of, data_in_force,
                           engine_word, import_document, judge_cache, read_cache)  # noqa: F401
from .compat.probes import (_candidate_paths, _engine_part, api_checks, discover,
                            engine_from_backend, engine_from_discovery, source_checks)  # noqa: F401
from .compat.views import (_binding_holds, assemble, live_report, live_view, read_report,
                           read_view, reader_view)  # noqa: F401
from .compat.evaluator import (Evaluator, run_refresh)  # noqa: F401

__all__ = ["BUNDLED", "Evaluator", "REFRESH_ANSWERS", "REFRESH_EXIT", "REFRESH_TIMEOUT_SECONDS",
           "_binding_holds", "_cache_empty", "_candidate_paths", "_coerce", "_columns",
           "_engine_part", "_newest", "_read_capped", "_signature", "_sources_of", "_stamp",
           "api_checks", "assemble", "bundled_verified_versions", "data_in_force", "discover",
           "engine_from_backend", "engine_from_discovery", "engine_word", "import_document",
           "judge_cache", "live_report", "live_view", "load_bundled", "path_digest",
           "product_version", "read_cache", "read_report", "read_view", "reader_view",
           "run_refresh", "source_checks", "write_json_atomic"]

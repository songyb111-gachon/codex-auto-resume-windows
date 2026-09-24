"""The fetched copy of the data: read, judged against the bundled baseline, imported.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from .. import machine
from .. import config
from .. import compat
from .. import codex as codex_source
from . import files
from .files import (_read_capped, product_version, write_json_atomic)

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
    bundled, _ = files.load_bundled(product=product, now=now)
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
    bundled, _ = files.load_bundled(product=product, now=now)
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

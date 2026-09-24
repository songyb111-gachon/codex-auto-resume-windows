"""The registry's files: the bundled baseline, the product version, and atomic writes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .. import config
from .. import compat


BUNDLED = Path(__file__).resolve().parent.parent / "data" / "codex_compat.json"
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
    """This product's version as the registry reads one: MAJOR.MINOR.PATCH, or "unknown".

    A planned pre-release (0.6.9-alpha) answers as its release: the registry's documents name
    releases, and an alpha that read as "unknown" would skip their min_product guard.
    """
    version = config.version()
    if version.endswith("-alpha"):
        version = version[:-len("-alpha")]
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

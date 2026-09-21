"""The registry data that tests of behaviour, and the documentation's pictures, run against.

`src/codex_auto_resume/data/codex_compat.json` on main is live data: it changes whenever
compatibility data is published, between releases, and a refresh serves it to installations as
soon as it is merged. What the product does with a given document must not move with it - a
publication that verified one more Codex version would otherwise turn the suite red and mark every
picture stale. So those tests and `build/make_screenshots.py` read `fixtures/codex_compat_frozen.json`
instead: v0.6.6's bundled document, byte for byte. The live file is held to its own rules by
`tests/test_compat.py:BundledBaselineTests`, which still reads it.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

FROZEN = Path(__file__).resolve().parent / "fixtures" / "codex_compat_frozen.json"


@contextmanager
def frozen():
    """Every read of the bundled document gets the frozen one, including the adapter's cached
    list of verified versions, which is read again on the way in and put back on the way out."""
    from codex_auto_resume import compatio, windows
    real = compatio.load_bundled

    def load_bundled(path=None, **options):
        return real(FROZEN if path is None or Path(path) == compatio.BUNDLED else path, **options)

    cached = windows._VERIFIED
    windows._VERIFIED = None
    try:
        with patch.object(compatio, "load_bundled", load_bundled):
            yield FROZEN
    finally:
        windows._VERIFIED = cached


_held = []


def hold():
    """For a module's setUpModule: the frozen document until `release()`."""
    manager = frozen()
    manager.__enter__()
    _held.append(manager)


def release():
    while _held:
        _held.pop().__exit__(None, None, None)

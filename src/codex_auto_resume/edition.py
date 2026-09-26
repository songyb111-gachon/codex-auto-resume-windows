"""Which edition this installation is, and the plug it runs with.

The advanced edition is the standard edition with one more package beside this one, in the
same `src` directory: `app/src` in an installation, the payload's `app/src` in the advanced
archive. Nothing is stamped or configured to say which edition a copy is; this module looks.

It is the one module of the package that spells that package's name, and the one that imports
a module by name at run time (tests/test_edition.py). Everything else in core reaches advanced
code only through the plug `plug()` returns, so the standard edition holds no reference to it at
all - not even one that is switched off.

Where it looks is the point. A package of that name somewhere else on the path is not this
installation's - a checkout's, a copy in site-packages - and does not turn a standard
installation into an advanced one. An advanced installation whose package cannot be taken as it
is - Python would import some other copy, its plug module fails, it was written for another plug
interface, its factory fails - runs exactly as the standard edition does, with a badge that says
"Advanced - not loaded" and one line in the log. It is never half loaded.
"""
from __future__ import annotations

import importlib
from importlib.machinery import ModuleSpec, PathFinder
import importlib.util
import logging
from pathlib import Path

from .domain.plug import NULL, PLUG_API, DamagedPlug, Edition, Plug, PlugFailure

ADVANCED_PACKAGE = "codex_auto_resume_advanced"
# The directory this package sits in, which is where the advanced package has to sit too.
SRC = Path(__file__).resolve().parent.parent
EDITIONS = tuple(Edition)
PLUG_FAILURES = tuple(PlugFailure)
# The log's word for an advanced installation that runs as the standard edition, followed by
# the PlugFailure that says why. Nothing else is written.
NOT_LOADED = "advanced_not_loaded"

_log = logging.getLogger(__name__)
# One plug per home for the life of the process, so an edition cannot change under a running
# watcher: the package is looked for once, before anything asks the plug a question.
_plugs: dict = {}


def _beside(src) -> ModuleSpec | None:
    """The advanced package's spec if it sits in `src`, else None. Imports nothing.

    A package, with its `__init__.py`: a directory of that name holding only a bytecode cache,
    or nothing, is what Python would call a namespace package, and is no edition."""
    spec = PathFinder.find_spec(ADVANCED_PACKAGE, [str(src)])
    if spec is None or not spec.origin or Path(spec.origin).name != "__init__.py":
        return None
    return spec


def _same(first, second) -> bool:
    try:
        return bool(first and second) and Path(first).resolve() == Path(second).resolve()
    except (OSError, ValueError):
        return False


def name(src=SRC) -> Edition:
    """ADVANCED when the advanced package sits beside this one, else STANDARD.

    The package's presence alone - the one fact the installer and the bootstrap can read too -
    so all three can agree, even about an installation whose package cannot be loaded."""
    return Edition.ADVANCED if _beside(src) is not None else Edition.STANDARD


def _damaged(reason) -> DamagedPlug:
    _log.warning("%s %s", NOT_LOADED, reason)
    return DamagedPlug(reason)


def load(paths, src=SRC) -> Plug:
    """The plug for the installation whose home is `paths`: NULL for the standard edition, the
    advanced package's own plug, or a DamagedPlug when that package cannot be taken as it is.

    Every step that can fail is a named PlugFailure, and none of them raises."""
    own = _beside(src)
    if own is None:
        return NULL
    try:
        found = importlib.util.find_spec(ADVANCED_PACKAGE)
    except (ImportError, ValueError):
        found = None
    # The copy Python would import has to be this one. A stray copy earlier on the path would
    # otherwise be loaded in its place, and be taken for this installation's.
    if found is None or not _same(found.origin, own.origin):
        return _damaged(PlugFailure.SHADOWED)
    try:
        module = importlib.import_module(ADVANCED_PACKAGE + ".plug")
    except Exception:
        return _damaged(PlugFailure.IMPORT_FAILED)
    api = getattr(module, "PLUG_API", None)
    if type(api) is not int or api != PLUG_API:
        return _damaged(PlugFailure.API_MISMATCH)
    try:
        made = module.create(paths)
    except Exception:
        return _damaged(PlugFailure.FACTORY_FAILED)
    if not isinstance(made, Plug) or isinstance(made, DamagedPlug) or made.edition != Edition.ADVANCED:
        return _damaged(PlugFailure.FACTORY_FAILED)
    return made


def plug(paths) -> Plug:
    """The plug for this process and home: loaded the first time it is asked for, and the same
    object every time after."""
    home = Path(paths.home)
    if home not in _plugs:
        _plugs[home] = load(paths)
    return _plugs[home]

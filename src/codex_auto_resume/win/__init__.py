"""Windows itself: the handles, the declarations, and the few structures shared across modules.

Only what more than one module needs lives here. A module that talks to a corner of Win32 nobody
else touches keeps its own declarations, which is the point of `library()`.
"""
from __future__ import annotations

from .dll import GUID, LRESULT, WNDCLASSW, WNDPROC, library  # noqa: F401

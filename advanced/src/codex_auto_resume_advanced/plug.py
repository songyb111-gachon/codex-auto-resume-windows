# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The one module core imports from this package: the interface it was written for, and its plug.

`codex_auto_resume/edition.py` imports this, takes the plug only when PLUG_API is the number
core was built with, and calls `create` once for each home. Anything that goes wrong on the way
leaves the installation running as the standard edition, with a badge that says so.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import Edition, Plug

# Written out rather than read from core. The check is whether this package was written for the
# core beside it, and a number taken from that core would agree with any core at all.
PLUG_API = 1


class AdvancedPlug(Plug):
    """The advanced edition's plug.

    Every capability is off until a person turns it on, and there is none yet, so every hook
    still answers as NULL does: an advanced installation with nothing on is the standard one
    (advanced/tests/test_advanced_package.py holds that at every point)."""
    __slots__ = ("paths",)
    edition = Edition.ADVANCED
    badge = "Advanced"

    def __init__(self, paths):
        self.paths = paths

    def edition_changed(self, previous):
        """Entering from the standard edition turns every capability off, whatever an earlier
        advanced installation left on. There is no capability to turn off yet; the registry
        that holds them brings that reset with it."""
        return None


def create(paths) -> AdvancedPlug:
    """The plug for the installation whose home is `paths`."""
    return AdvancedPlug(paths)

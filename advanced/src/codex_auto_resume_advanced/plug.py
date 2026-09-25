# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The one module core imports from this package: the interface it was written for, and its plug.

`codex_auto_resume/edition.py` imports this, takes the plug only when PLUG_API is the number
core was built with, and calls `create` once for each home. Anything that goes wrong on the way
leaves the installation running as the standard edition, with a badge that says so.

Every hook hands its question to the runtime (runtime.py), which asks the registry's
capabilities in the state each one is in; the claim ledger (P11) and the surfaces (P10) are the
plug's own. Nothing is opened, read or written until a hook needs it, and with no capability -
as this version ships - every decision point answers as NULL does.
"""
from __future__ import annotations

from codex_auto_resume.domain.plug import Edition, Plug, Point

# Written out rather than read from core. The check is whether this package was written for the
# core beside it, and a number taken from that core would agree with any core at all.
PLUG_API = 1


class AdvancedPlug(Plug):
    """The advanced edition's plug.

    Every capability is off until a person turns it on, and there is none yet, so every decision
    still answers as NULL does: an advanced installation with nothing on is the standard one
    (advanced/tests/test_advanced_package.py holds that at every point). What it adds is on its
    surfaces: the Dashboard's bridge commands and a model's MCP tools, which list the
    capabilities and turn them off."""
    __slots__ = ("paths", "_options", "_runtime")
    edition = Edition.ADVANCED
    badge = "Advanced"

    def __init__(self, paths, **options):
        self.paths = paths
        self._options = options
        self._runtime = None

    @property
    def runtime(self):
        if self._runtime is None:
            from .runtime import Runtime
            self._runtime = Runtime(self.paths, **self._options)
        return self._runtime

    def records(self, view):
        return self.runtime.ask(Point.RECORDS, view)

    def gate(self, name, record, facts):
        return self.runtime.ask(Point.GATES, name, record, facts)

    def text(self, record, text):
        return self.runtime.ask(Point.TEXT, record, text)

    def sender(self, record, backend):
        return self.runtime.ask(Point.SENDER, record, backend)

    def outcome(self, record, outcome):
        return self.runtime.ask(Point.OUTCOME, record, outcome)

    def schedule(self, record, due):
        return self.runtime.ask(Point.SCHEDULE, record, due)

    def tick(self, view):
        return self.runtime.tick(view)

    def start_route(self, request):
        return self.runtime.ask(Point.START_ROUTE, request)

    def surface(self, name, facts):
        from . import surfaces
        return surfaces.answer(self.runtime, name, facts)

    def claim_ledger(self, connection, record, now):
        return self.runtime.claim(connection, record, now)

    def partition(self, records):
        return self.runtime.ask(Point.CONCURRENCY, records)

    def supervise(self, facts):
        return self.runtime.ask(Point.SUPERVISION, facts)

    def edition_changed(self, previous):
        """Entering from the standard edition turns every capability off, whatever an earlier
        advanced installation of this home left on - arming never carries across an edition
        change. Where no advanced state was ever written, nothing can be on, and nothing is
        written now."""
        self.runtime.arming.edition_entered()
        return None


def create(paths) -> AdvancedPlug:
    """The plug for the installation whose home is `paths`."""
    return AdvancedPlug(paths)

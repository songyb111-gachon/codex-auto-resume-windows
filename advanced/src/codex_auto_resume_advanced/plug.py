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
PLUG_API = 6


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
        return self.runtime.records(view)

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
        return self.runtime.start_route(request)

    def start_held(self):
        """Why the start route just asked named none (core's Plug.start_held, runtime.Runtime.start_held)."""
        return self.runtime.start_held()

    def surface(self, name, facts):
        from . import surfaces
        return surfaces.answer(self.runtime, name, facts)

    def claim_ledger(self, connection, record, now, carried):
        return self.runtime.claim(connection, record, now, carried)

    def partition(self, records):
        return self.runtime.partition(records)

    def supervise(self, facts):
        return self.runtime.supervise(facts)

    def moved(self, record, state):
        return self.runtime.moved(record, state)

    def delivery(self, record):
        return self.runtime.ask(Point.DELIVERY, record)

    def unloaded(self, record):
        return self.runtime.ask(Point.UNLOADED, record)

    def admission(self, failure):
        return self.runtime.ask(Point.ADMISSION, failure)

    def sessions(self):
        return self.runtime.sessions()

    def eligibility(self):
        return self.runtime.eligibility()

    def wants(self, point):
        """Whether a capability may answer at `point` now (core's Plug.wants), so core makes the
        reads that point needs only then (runtime.py)."""
        return self.runtime.wants(point)

    def codex(self, codex_exe, codex_home):
        """The Codex this installation's watcher drives (core's Plug.codex), kept for the
        capabilities' own sessions and reads (codex/inuse.py). Nothing is opened or read."""
        from .codex import inuse
        inuse.tell(self.paths, codex_exe, codex_home)
        return None

    def conversation_off(self, thread_id):
        """A person switched a conversation off (core's Plug.conversation_off): every message of a person's
        own still waiting there ends, its words with it (runtime.py)."""
        self.runtime.conversation_off(thread_id)
        return None

    def edition_changed(self, previous):
        """Entering from the standard edition turns every capability off, whatever an earlier
        advanced installation of this home left on - arming never carries across an edition
        change. Where no advanced state was ever written, nothing can be on, and nothing is
        written now."""
        self.runtime.arming.edition_entered()
        return None


# v0.6.16: this edition's kinds of notice a person can keep on screen until clicked, as core's registry takes an
# edition's (codex_auto_resume.notice_kinds.register): an id, the notifier kinds it covers, and its words in every
# language. Every notice this edition raises is one: the usage meter's warning (issue #29), and the forced stop's three
# (v0.6.16-beta.4) - a turn it could not stop, a queue to Resume in Codex, a conversation it could not continue after
# the reset - and (v0.6.18) the weekly update check's offer of a newer version. Each is named by its notice's own title. Its other capabilities raise no notice of their own: a turn run
# here, a compaction or another model ends as core's own notices say (resumed, failed, stopped).
NOTICE_KINDS = (("near_limit", ("near_limit",), "msg.toast_near_limit"),
                ("near_limit_not_stopped", ("near_limit_not_stopped",), "msg.toast_near_limit_not_stopped"),
                ("near_limit_press_resume", ("near_limit_press_resume",), "msg.toast_near_limit_press_resume"),
                ("near_limit_not_continued", ("near_limit_not_continued",), "msg.toast_near_limit_not_continued"),
                # v0.6.18: the weekly update check's offer of a newer version.
                ("update_offered", ("update_offered",), "msg.toast_update_offered"),
                # v0.6.19: the crash restart left the watcher stopped after its third restart in an hour.
                ("restart_gave_up", ("restart_gave_up",), "msg.toast_restart_gave_up"))


def register_notice_kinds():
    """Register NOTICE_KINDS with core, which then lists them in Settings and keeps their notices on screen when a
    person chose to. Registering again replaces, so a second plug in one process changes nothing."""
    from codex_auto_resume import l10n, notice_kinds
    for kind_id, notices, key in NOTICE_KINDS:
        notice_kinds.register(kind_id, notices, {locale: l10n.text(key, locale) for locale in l10n.LOCALES})


def create(paths) -> AdvancedPlug:
    """The plug for the installation whose home is `paths` - and this edition's kinds of notice, registered with core
    as the plug is made (register_notice_kinds)."""
    register_notice_kinds()
    return AdvancedPlug(paths)

"""The part that decides: what to recover, when, and what became of it.

`engine.py` was 1,083 lines and one class of forty-one methods. It is the same class, composed
here from the mixins beside this file, so `from .engine import Engine` and every call read as
they did:

    options     what it was given, and the policy it was last told
    detect      turning what Codex recorded into records this product owns
    freshness   whether Codex is in a state worth reading
    dispatch    sending one continuation
    delivery    how it is carried, the last look before it goes, and what proves it arrived
    routes      a conversation the app does not hold, continued by a route the plug names (P16)
    kinds       which conversations besides the app's are watched (P18)
    reconcile   what became of a continuation that was sent
    outcome     how the recovered turn ended, and what it costs the budgets
    announce    moving a record, and saying so
    guard       the waits and the two guards of v0.6.11, each asking nothing at the defaults
    relaxed     what the edition's plug may relax (v0.6.14), within core's own bounds
    resend      an uncertain continuation sent once more, where the plug asks and core may (v0.6.14)
    plugrecords records of the edition's own, tried like core's: gates, the one claim, the one send (v0.6.14)
    notices     the needs-you notices of v0.6.11, told once, and off at the defaults

`tick` is here rather than in any of them: one pass of the loop is the whole of what this
package does, and reading it should not mean opening seven files.
"""
from __future__ import annotations

from contextlib import nullcontext

from ..domain import skips
from ..domain.plug import DEFER
from .announce import NOTIFY_ON_STATE, AnnounceMixin  # noqa: F401
from .delivery import DeliveryMixin
from .detect import DetectMixin
from .dispatch import DispatchMixin
from .foropen import ForOpenMixin
from .freshness import FreshnessMixin
from .guard import GuardMixin
from .launches import LaunchPool
from .notices import NoticeMixin
from .options import (BACKOFF_LADDER, TRANSIENT_BACKOFF, OptionsMixin,  # noqa: F401
                      backoff_delay, transient_delay)
from .outcome import OutcomeMixin
from .plugrecords import PlugRecordsMixin
from .reconcile import SETTLED, UNSENT, ReconcileMixin, _UNDETERMINED  # noqa: F401
from .relaxed import RelaxedMixin
from .resend import ResendMixin
from .tosession import ToSessionMixin
from .compaction import CompactionMixin
from .recordchannel import RecordChannelMixin
from .kinds import KindsMixin
from .routes import RoutesMixin
from .storeview import StoreView


class Engine(OptionsMixin, AnnounceMixin, FreshnessMixin, DetectMixin, ReconcileMixin, OutcomeMixin, DispatchMixin,
             DeliveryMixin, GuardMixin, NoticeMixin, RelaxedMixin, ResendMixin, PlugRecordsMixin,
             ForOpenMixin, RoutesMixin, KindsMixin, ToSessionMixin, CompactionMixin,
             RecordChannelMixin):
    """The part that decides.
    """

    # ------------------------------------------------------------------ tick
    def tick(self):
        # The watch and outcome observation continue when recovery is paused: taking
        # back a queued continuation is exactly what a Pause asks for.
        try:
            self.observe_projections()
        except Exception:
            self.log(None, "projection_check_unavailable", None)
        self.watch()
        self.observe_all()
        self.watch_resent()             # v0.6.14: a resend found twice; nothing for the standard edition
        self._prune_once_words()        # v0.6.16-beta.3: words of a recovery no longer waiting, deleted
        # v0.6.15-beta: a Codex home taken out of Settings only watches what it sent until that settles.
        if self.retiring:
            return
        # v0.6.11: an administrator's DisableAutoResume is a Pause here too, even before the watcher
        # has written it into the state (runtime/app.py), so a write that failed sends nothing.
        if not self.store.settings()["enabled"] or self.managed.disable_auto_resume:
            # v0.6.16-beta.3: said once each time recovery is found off - no failed turn is read meanwhile.
            if not self._off_told:
                self._off_told = True
                self.log(None, skips.RECOVERY_OFF, None)
            # v0.6.15-beta: what the plug sent that Codex still holds is taken back, the plug asked nothing.
            self.paused_records()
            return
        self._off_told = False
        # The plug is asked nothing more while recovery is paused: a Pause beats every
        # capability, as it beats core. P8 is once a tick, after everything is observed; what it
        # answers to run (v0.6.14, an errand) runs last, after P2, whatever the tick met before it.
        # P19 (v0.6.16-beta.3): which of the app's conversations detection takes up from here on - a person's own
        # alone where the plug names nothing, which is the standard edition's always (NULL answers the empty set).
        self.source.widened = self.plug.eligibility()
        self.session_kinds()            # P18 (v0.6.16-beta.4): and which conversations besides the app's (engine/kinds.py)
        view = StoreView(self.store, self.clock(), self.last_usage, home_key=self.home_key)
        errand = self.plug.tick(view)
        try:
            try:
                self.collect()
            except Exception:
                self.log(None, "detection_unavailable_no_submission", None)
                return
            due = self._records(UNSENT)
            # P12 (v0.6.15-beta): how many sends may wait for their receipts at once - 1, one after another in
            # this thread, unless the plug answers 2 to 4. Every claim and look stays here; a worker only waits for
            # a receipt, and every one is joined and settled before the tick goes on (engine/launches.py).
            workers = self._workers(due)
            with LaunchPool(workers, self.open_store, self._settle_launch) if workers > 1 else nullcontext() as pool:
                self._pool = pool
                try:
                    for row in due:
                        try:
                            self.attempt(row)
                        except Exception:
                            self.log(row["thread_id"], "eligibility_check_failed_no_submission", None)
                finally:
                    self._pool = None
            # v0.6.14: what the watch found no trace of, put to the plug for one more send (P7).
            if not self.plug.null:
                self.resend_uncertain()
            # P2: the records of the advanced store that are due, after core's own, each carried out
            # by core - its gates, its one claim, the one send - and those in flight watched
            # (engine/plugrecords.py, v0.6.14). The standard edition's plug hands over none.
            self.plug_records(view)
        finally:
            if errand is not DEFER:
                self._errand(errand)

    def _errand(self, errand):
        """P8's errand (v0.6.14): run once, last in the tick, handed a way to ask for the store's errand
        guards (store/claims.py), each of which also asks what the engine knows and the store does not
        (errand_held). One that raises is logged from the fixed table and costs itself alone."""
        try:
            errand.run(lambda: self.store.errand_guard(held=self.errand_held))
        except Exception:
            self.log(None, "plug_errand_failed", None)

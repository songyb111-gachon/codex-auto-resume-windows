"""The part that decides: what to recover, when, and what became of it.

`engine.py` was 1,083 lines and one class of forty-one methods. It is the same class, composed
here from the mixins beside this file, so `from .engine import Engine` and every call read as
they did:

    options     what it was given, and the policy it was last told
    detect      turning what Codex recorded into records this product owns
    freshness   whether Codex is in a state worth reading
    dispatch    sending one continuation, and the last look before it goes
    reconcile   what became of a continuation that was sent
    outcome     how the recovered turn ended, and what it costs the budgets
    announce    moving a record, and saying so

`tick` is here rather than in any of them: one pass of the loop is the whole of what this
package does, and reading it should not mean opening seven files.
"""
from __future__ import annotations

from .announce import NOTIFY_ON_STATE, AnnounceMixin  # noqa: F401
from .detect import DetectMixin
from .dispatch import DispatchMixin
from .freshness import FreshnessMixin
from .options import (BACKOFF_LADDER, TRANSIENT_BACKOFF, OptionsMixin,  # noqa: F401
                      StoreView, backoff_delay, transient_delay)
from .outcome import OutcomeMixin
from .reconcile import SETTLED, UNSENT, ReconcileMixin, _UNDETERMINED  # noqa: F401


class Engine(OptionsMixin, AnnounceMixin, FreshnessMixin, DetectMixin, ReconcileMixin, OutcomeMixin, DispatchMixin):
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
        if not self.store.settings()["enabled"]:
            return
        # The plug is asked nothing more while recovery is paused: a Pause beats every
        # capability, as it beats core. P8 is once a tick, after everything is observed.
        view = StoreView(self.store, self.clock())
        self.plug.tick(view)
        try:
            self.collect()
        except Exception:
            self.log(None, "detection_unavailable_no_submission", None)
            return
        due = self.store.records_in(UNSENT)
        # P12: how the due records are divided for dispatch. Core carries out no division but
        # its own - one record after another, in this thread - so nothing is taken from the
        # answer yet (domain/plug.py, ALTERNATIVES).
        self.plug.partition(due)
        for row in due:
            try:
                self.attempt(row)
            except Exception:
                self.log(row["thread_id"], "eligibility_check_failed_no_submission", None)
        # P2: the records of the advanced store that are due, after core's own. None is tried
        # yet: an advanced record reaches the one claim only once core has learned to carry it
        # through it (domain/plug.py, ALTERNATIVES).
        self.plug.records(view)

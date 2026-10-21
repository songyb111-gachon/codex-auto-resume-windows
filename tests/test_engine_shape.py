"""The engine is one class, however many files it is written in.

The same check the store gets (`tests/test_store_shape.py`), for the same reason: composition
is the one way to split a class without touching a call site, and its way to go wrong is two
mixins defining the same method, where which one answers depends on the order they are named
in - which no test would otherwise notice.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import engine as package  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402

MIXINS = (package.OptionsMixin, package.AnnounceMixin, package.FreshnessMixin,
          package.DetectMixin, package.ReconcileMixin, package.OutcomeMixin,
          package.DispatchMixin, package.NoticeMixin,
          # v0.6.11: how a continuation is carried and proven (P15), and the look before it goes.
          package.DeliveryMixin,
          # v0.6.14: what the edition's plug may relax, within core's own bounds.
          package.RelaxedMixin,
          # and an uncertain continuation sent once more, where the plug asks and core may.
          package.ResendMixin,
          # and records of the edition's plug's own, tried like core's (P2).
          package.PlugRecordsMixin,
          package.ForOpenMixin,
          # v0.6.16-beta.4: a route the plug names for a conversation not held (P16), out of engine/delivery.py.
          package.RoutesMixin,
          # and which conversations besides the app's are watched (P18).
          package.KindsMixin,
          # a continuation sent to a conversation another Codex session holds (P16's TO_SESSION),
          package.ToSessionMixin,
          # and a full context window's record, which a compaction turn supersedes nothing of,
          package.CompactionMixin,
          # and a person's message of the plug's, marker-free through its channel.
          package.RecordChannelMixin)

# The forty-one methods the one class had, counted the day it was split.
METHODS = {
    "__init__", "_after_send", "_cut_off", "_delete", "_legacy_carry", "_owner", "_projection_now",
    "_refused", "_stop_for_budget", "_usage_wait", "_wait", "allowed", "announce",
    "apply_policy", "attempt", "collect", "correlate", "delay_for", "dispatch",
    "first_delay", "fresh_throughout", "guard_queued", "limits", "loaded", "observe",
    "observe_all", "observe_projections", "presend_problem", "projection_fresh", "recovers",
    "settle", "supersede_reason", "tick", "transition", "usage", "valid_interruption",
    "waiting_state", "watch", "watch_needed", "watch_record", "withdraw", "withdraw_reason",
    # v0.6.11: the edition's plug asked at a gate core has passed (P3, P7), and for the words
    # before the claim (P4).
    "_held", "_plugged", "_plugged_text",
    # v0.6.11: the plug told of each move the engine writes (P14), and giving a claim back,
    # which is one of them.
    "moved", "_release",
    # v0.6.11: quiet hours and a conversation's tier as the policy says them, a record parked in
    # quiet hours, and the objection window before a first send.
    "quiet_until", "tier", "_quiet", "_objection",
    # v0.6.11: observe only - the switch, whether a refused consent is only observed, and the record
    # that would have been sent; and the hold an interruption is detected with.
    "observing", "observes", "_would_send", "admission",
    # v0.6.11: the needs-you notices, each raised once (engine/notices.py), and the last usage reading
    # the watcher's heartbeat keeps, which reads nothing (engine/freshness.py).
    "tell_needs_you", "_notice", "last_usage",
    # v0.6.16-beta.3: why a failed turn is not taken up, decided once and said once (issue #27).
    "detection_since", "not_taken_up", "_skip", "_say_passed_over",
    # v0.6.11: whether Windows reports no internet and the wait that follows, and what a wake forgets
    # and a long sleep holds (engine/freshness.py) - each asked of nothing at the defaults.
    "offline", "_offline", "after_sleep",
    # v0.6.11: how a continuation is carried and what proves it arrived - the marker, or the client
    # id a marker-free one was queued under (P15, engine/delivery.py).
    "proof", "_delivery",
    # v0.6.11 stage 3b: a route the plug names for a conversation the app does not hold (P16),
    # taken where core would wait, carried out through the one claim, and what came of it.
    "_unloaded", "_resume_unloaded", "_after_resume",
    # v0.6.12: what may still run in Codex, for the power action after usage-limit recoveries - counts
    # and sizes only, asked only once its own checks pass (engine/freshness.py).
    "activity",
    # v0.6.14: a failure core never recovers alone put to the plug (P17) and how long one taken up
    # waits; when its task first failed, on the clock; and known_failure, where it goes on only while
    # the plug takes it up again, and otherwise ends unsent (engine/relaxed.py).
    "chain_started_at", "_unadmit", "_taken_up", "_admitted_wait", "_known_failure", "_chained",
    "_not_recovered",
    # v0.6.14: and every kind of failure a task has had, which P17 is told with the task (`chain`).
    "chain_categories",
    # and a capacity error the plug vouches for: its budgets, its twelve hours, its waits.
    "capacity_limits", "capacity_open", "_capacity_wait",
    # and a usage-limited record looked at early (EARLY): the look, its waits, what the ledger pays.
    "_attempt", "_early", "_parked", "relaxed_points",
    # and an uncertain submission sent once more (RESEND, engine/resend.py): its window, the watch's
    # sightings and looks that found no trace, the checks and the plug's holds, the send's outcome,
    # and a resend that ran found twice.
    "resend_window", "_sighted", "_traceless", "_resendable", "_holds", "resend_uncertain", "_resend",
    "_after_resend", "watch_resent",
    # and a person's Send now (SEND_NOW, engine/relaxed.py): the schedule it passes, an attempt budget
    # of the person's own, and the administrator's ceiling the claim is told.
    "_send_now", "_own_budget", "forced_limits",
    # v0.6.15-beta: a conversation's day and spacing, read by the gates and again in the claim, and how
    # long a record the claim refused for them waits.
    "caps", "_cap_delay",
    # and the engine's own Codex home: its records, its claimed ones and its ids (engine/detect.py).
    "_records", "_claimed", "_keyed",
    # and several receipts waited for at once (P12, engine/delivery.py): how many, the worker taken and freed, whether
    # the send goes to it, the hand-over and what came of it.
    "_workers", "_take_slot", "_pooled", "_launched", "_free_slot", "_settle_launch",
    # and P8's errand of the plug, run last in the tick, and what holds back its one write.
    "_errand", "errand_held",
    # and P2 carried out: the records of the plug's own, their words, their gates and moves, their claim
    # and the look before their send, what came of it, and those in flight watched (engine/plugrecords.py).
    "plug_records", "_worded", "_record_told", "_record_waits", "_try_record", "_record_would_send", "_not_ones_own", "_take_back", "_flying", "paused_records",
    # v0.6.15-beta: one queued for when its conversation is opened (engine/foropen.py).
    "for_open", "_open_reason", "_for_open_rests", "_not_for_open",
    "_record_claim", "_record_problem", "_record_sent", "_watch_record",
    # v0.6.16-beta.3: the turns a wrap-up started are the product's own, never the person's work.
    "_wrap_up_markers", "persons_turns", "_only_wrap_ups_after",
    # v0.6.16-beta.3: the words for this time, added once, spent at the send, deleted when not waiting.
    "_once_words", "_spend_once_words", "_prune_once_words",
    # v0.6.16-beta.4: P16 asked with the app closed and nothing holding the conversation, and the look made again.
    "_unheld", "_unheld_now", "_holder", "_route", "_still_where",
    # and which conversations besides the app's are watched, asked once a tick (P18, engine/kinds.py), and whether
    # one of them a newer Codex wrote than the engine here (the version skew guard, design-4 4.3);
    "session_kinds", "newer_than_engine",
    # the identity gate - Codex's history caught up, and no newer Codex than the engine's - out of dispatch.py at
    # its size (engine/freshness.py);
    "_identity_waits",
    # a continuation sent to another Codex session (P16's TO_SESSION, engine/tosession.py);
    "to_session", "_session", "_session_reason",
    # and the compaction turns after a full context window (engine/compaction.py).
    "compacted_since", "compaction", "foreign",
    # and P15's SILENT for a route that takes words (engine/routes.py), proven by the turn id it returned (M3B).
    "_silent", "_silent_proven",
    # and a person's message of the plug's carried marker-free (engine/recordchannel.py).
    "_marker_free", "_record_carried", "_record_client", "_record_proof", "_record_words", "_record_carrying",
}

# What `from codex_auto_resume.engine import ...` has to keep answering (app.py, the tests).
SURFACE = {"Engine", "BACKOFF_LADDER", "TRANSIENT_BACKOFF", "NOTIFY_ON_STATE", "SETTLED",
           "UNSENT", "backoff_delay", "transient_delay"}


def own(mixin) -> set:
    return {name for name, value in vars(mixin).items()
            if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod))}


class ShapeTests(unittest.TestCase):
    def test_no_two_mixins_define_the_same_method(self):
        seen = {}
        for mixin in MIXINS:
            for name in own(mixin):
                with self.subTest(name=name):
                    self.assertNotIn(name, seen, "%s is defined by both %s and %s"
                                     % (name, seen.get(name), mixin.__name__))
                seen[name] = mixin.__name__

    def test_the_class_has_the_methods_it_had(self):
        found = {name for name in vars(Engine) if not name.startswith("__")}
        for mixin in MIXINS:
            found |= {name for name in own(mixin) if not name.startswith("__")}
        expected = {name for name in METHODS if not name.startswith("__")}
        self.assertEqual(sorted(found - expected), [], "a method appeared; name it in METHODS")
        self.assertEqual(sorted(expected - found), [], "a method is gone; take it out of METHODS")

    def test_every_method_is_callable_on_the_class(self):
        for name in sorted(METHODS):
            with self.subTest(name):
                self.assertTrue(hasattr(Engine, name), "Engine lost %s in the split" % name)

    def test_the_loop_stayed_on_the_front_page(self):
        """`tick` is what the package does; it is not hidden in one of the seven."""
        self.assertIn("tick", vars(Engine))

    def test_everything_reachable_through_the_module_still_is(self):
        for name in sorted(SURFACE):
            with self.subTest(name):
                self.assertTrue(hasattr(package, name),
                                "%s was reachable as engine.%s before the split" % (name, name))

    def test_each_part_is_small_enough_to_read(self):
        folder = Path(package.__file__).parent
        for path in sorted(folder.glob("*.py")):
            with self.subTest(path.name):
                length = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(length, 350, "%s is growing back" % path.name)


if __name__ == "__main__":
    unittest.main()

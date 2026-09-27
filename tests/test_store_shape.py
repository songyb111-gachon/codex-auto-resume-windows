"""The store is one class, however many files it is written in.

v0.6.10-alpha split `store.py` into `store/`, and composition is the one way to do that
without changing a single call site - but it brings its own way to go wrong: two mixins
defining the same method, where which one wins depends on the order they are named in.

So the shape is held here. Every method belongs to exactly one mixin, the class has exactly
the methods it had, and everything that could be reached as `store.<name>` before the split
still can.
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

from codex_auto_resume import store  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

MIXINS = (store.SessionMixin, store.SchemaMixin, store.MigrationsMixin, store.JournalMixin,
          store.PolicyMixin, store.RecordsMixin, store.ClaimsMixin, store.LedgerMixin,
          store.ActionsMixin, store.ScheduleMixin, store.WatcherMixin, store.ReportingMixin,
          store.NoticesMixin)

# What `Store` has, as the one class had it. Sixty-one methods, counted the day the file was
# split; a method added or taken away is a decision, and this is where it is made.
METHODS = {
    "__enter__", "__exit__", "__init__", "_add_schema_3", "_begin", "_create_interruptions",
    "_create_interruptions_named", "_create_schema", "_event", "_forensic_copy", "_migrate",
    "_migrate_1_to_2", "_migrate_2_to_3", "_now", "_others_in_flight", "_parent", "_prune",
    "_read", "_read_settings", "_row", "_tables", "_thread_enabled", "_transaction",
    "_validate_schema", "all_records", "cancel_interruption", "cancel_thread",
    "claimed_on_thread", "close", "correlate", "disabled_threads", "events", "failure_marks",
    "get", "heartbeat", "hide_history", "history", "others_in_flight", "pending",
    "recent_claim_count", "recent_claims", "record_gates", "records_in", "register",
    "release_claim", "release_withdrawn", "request_retry_now", "reserve", "reserve_detailed",
    "restore_budget", "restore_budget_detailed", "schema_version", "set_enabled",
    "set_thread_enabled", "settings", "status_counts", "statistics", "submission_guard",
    "thread_enabled", "update", "watcher_status",
    # v0.6.11: the edition's claim ledger, asked inside the claim (P11) - store/ledger.py.
    "_ledger_holds",
    # v0.6.11: schema 4, made fresh and reached from schema 3 - store/migrations.py.
    "_add_schema_4", "_migrate_3_to_4",
    # v0.6.11: a record postponed, held and let go, a conversation's tier, and the objection
    # window - store/actions.py and store/policy.py.
    "_bound", "_not_waiting", "postpone", "release_hold", "open_objection_window",
    # v0.6.11: a person's own postponement taken away (Don't postpone) - store/schedule.py, which the
    # four above moved into with it, out of store/actions.py at its 300 lines.
    "unpostpone",
    "_thread_tier", "thread_tier", "thread_tiers", "set_thread_tier",
    # v0.6.11: observe only's switch and its "would have been sent", a conversation first seen given
    # Only notify me, and a project's waiting records held - store/policy.py and store/claims.py.
    "set_observe_only", "record_would_send", "enrol_conversation", "hold_waiting",
    # v0.6.11: the task-changed guard's hold, which takes the digest it found in the same write.
    "hold_changed",
    # v0.6.11: a needs-you notice raised once - store/notices.py - and the last usage reading the
    # heartbeat keeps (store/watcher.py).
    "raise_notice", "_reading",
    # v0.6.11: a watcher that stops on purpose says how - clean, or the memory guard (store/watcher.py).
    "watcher_ended",
}

# Reachable as `store.<name>` before the split, and still.
SURFACE = {
    "CLAIMED", "ENGINE_STATES", "EVENT_LIMIT", "EVENT_MAX_AGE", "EXHAUSTED", "IN_FLIGHT",
    "LegacyStore", "MAX_BUDGET_RESETS", "OBSERVING", "RecordSchemaMismatch", "SCHEMA_VERSION",
    "STATES", "StateFromNewerVersion", "Store", "StoreError", "TERMINAL", "UNKNOWN_WINDOW",
    "UpgradePending", "WAITING", "WATCHED", "downgrade_to_v2", "is_usage", "sqlite3",
    "_MUTABLE", "_PRUNE_EVERY", "_RECORD_COLUMNS", "_claim_cost", "_finite", "_flag",
    "_integer", "_short_text", "_sql", "_timestamp", "_uuid", "_validated_record",
}


def own(mixin) -> set:
    return {name for name, value in vars(mixin).items()
            if inspect.isfunction(value) or isinstance(value, (staticmethod, classmethod))}


class ShapeTests(unittest.TestCase):
    def test_no_two_mixins_define_the_same_method(self):
        """Otherwise which one answers depends on the order they are named in."""
        seen = {}
        for mixin in MIXINS:
            for name in own(mixin):
                with self.subTest(name=name):
                    self.assertNotIn(name, seen,
                                     "%s is defined by both %s and %s" % (name, seen.get(name),
                                                                          mixin.__name__))
                seen[name] = mixin.__name__

    def test_the_class_has_the_methods_it_had(self):
        found = {name for name, value in vars(Store).items() if not name.startswith("__")}
        for mixin in MIXINS:
            found |= {name for name in own(mixin) if not name.startswith("__")}
        expected = {name for name in METHODS if not name.startswith("__")}
        self.assertEqual(sorted(found - expected), [], "a method appeared; name it in METHODS")
        self.assertEqual(sorted(expected - found), [], "a method is gone; take it out of METHODS")

    def test_every_method_is_callable_on_the_class(self):
        for name in sorted(METHODS):
            with self.subTest(name):
                self.assertTrue(hasattr(Store, name), "Store lost %s in the split" % name)

    def test_everything_reachable_through_the_module_still_is(self):
        for name in sorted(SURFACE):
            with self.subTest(name):
                self.assertTrue(hasattr(store, name),
                                "%s was reachable as store.%s before the split" % (name, name))

    def test_each_part_is_small_enough_to_read(self):
        """The point of the split, stated as a number rather than a hope."""
        folder = Path(store.__file__).parent
        for path in sorted(folder.glob("*.py")):
            with self.subTest(path.name):
                length = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLess(length, 300, "%s is growing back" % path.name)


if __name__ == "__main__":
    unittest.main()

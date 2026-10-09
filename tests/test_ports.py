"""Every call a layer makes across its own boundary, named.

The engine is handed a store, a source and a backend, and reaches Codex and the state through
nothing else; the control layer opens a store and calls it. Those calls are the seams the
v0.6.10 split moves code around - `store.py` becomes a package, `source.py` moves into
`codex/`, the engine's own module becomes one too - and a seam nobody has written down is a
seam a move can widen without anybody noticing. A new call from the engine into the store is
not a bug, but it is a decision, and this file is where it is made.

So each crossing is a table of method names, read out of the source rather than out of a test
run: a runtime proxy records only what the tests happen to exercise, while the reader below
sees the call whether or not anything runs it. Adding a name to a table is the whole cost of
adding a call; the test says which name and where.

`tests/test_layers.py` says which module may import which. This says what it may ask of it.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import textwrap
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402


def module_source(name: str) -> str:
    """The module's source - or, once it is a package, the source of all of it.

    A seam is about what a layer asks of another, not about which file holds the call, so a
    layer that becomes a package is read whole and the tables below do not move.
    """
    found = [srcscan.read(path) for path in srcscan.package_files()
             if srcscan.relative(path).endswith("/%s.py" % name)
             or "/%s/" % name in srcscan.relative(path)]
    if not found:
        raise AssertionError("no module named %s in the package" % name)
    return "\n".join(found)


def names_on(source: str, receivers: tuple) -> set:
    """Every attribute read off one of `receivers`, however it is spelled.

    `self.store.get(...)`, `store.get(...)` and `getattr(store, "get")` all count; a name
    built at run time is refused by test_no_name_is_computed below, so the tables are whole.
    """
    found = set()

    def receiver_of(node) -> str | None:
        if isinstance(node, ast.Name) and node.id in receivers:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in receivers:
            inner = node.value
            if isinstance(inner, ast.Name) and inner.id in ("self", "cls"):
                return node.attr
        return None

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and receiver_of(node.value):
            found.add(node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and node.args and receiver_of(node.args[0])
              and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
            found.add(node.args[1].value)
    return found


# ------------------------------------------------------------------ the seams, name by name
# What the engine asks of the state it is given. Reading a record and the rules around it,
# claiming the right to send, writing what happened, and the counters the budgets are made of.
ENGINE_TO_STORE = {
    "get", "register", "update", "settings", "record_gates", "records_in", "correlate",
    "reserve_detailed", "claimed_on_thread", "others_in_flight", "recent_claims",
    "recent_claim_count", "release_claim", "release_withdrawn", "submission_guard",
    "thread_enabled",
    # v0.6.11: a conversation's tier, read when a failure is detected and before a first send,
    # and the objection window that tier opens.
    "thread_tier", "open_objection_window",
    # and observe only's "would have been sent", and a conversation first seen given Only notify me.
    "record_would_send", "enrol_conversation",
    # and a record the task-changed guard holds for a person when it falls due (engine/guard.py) -
    # never at the defaults, where the guard is off.
    "hold_changed",
    # and a needs-you notice kept so it is told once (engine/notices.py) - never at the defaults.
    "raise_notice",
    # and what fell due during a long sleep, held for a person (engine/freshness.py) - never at the
    # defaults, where Ask after a long sleep is off.
    "hold_waiting",
    # v0.6.14: the record of a task a failure continues, read before P17 asks about it - and only
    # while the edition's plug wants P17 (engine/detect.py).
    "chain_parent",
    # and the guard of the plug's errand at P8, asked only for an errand the plug answered.
    "errand_guard",
    # and a record of the plug's own claimed, and launched in its guard (P2) - only for one it handed over.
    "reserve_record", "record_guard",
}
# What it asks of Codex itself, through the backend: is the app there, what is my usage, send
# this, take it back, is the thread loaded. Five, and the split must not make it six by accident.
# Since v0.6.11 the send is asked of `sender`, the one name dispatch binds to the backend - or to
# a channel the edition's plug names at P5 (tests/test_structural_invariants.py) - so both names
# are read as this seam.
ENGINE_TO_BACKEND = {"app_identity", "delete_queue", "loaded", "send", "usage"}
BACKEND_NAMES = ("backend", "sender")
# What it reads out of Codex's own files, through the source: the turns, the markers that say a
# continuation of ours is in the queue, what a recovered turn produced, and the projection's age.
ENGINE_TO_SOURCE = {
    "latest", "later_turns", "latest_failures", "turn_markers", "turn_observation",
    "turn_progress", "progress", "projection", "marker_presence", "marker_rows", "queue_row",
    "queued_rows", "foreign_queued", "reset_hint",
    # v0.6.11: the key of a conversation's project, asked only when Settings let some projects
    # resume and not others (projects.asks) - never at the defaults.
    "project_key",
    # and what the task-changed and context-cost guards read, asked only while one is on.
    "task_facts",
    # and the turns that stopped moving, asked only while a needs-you notice waits for one.
    "stalled_turns",
    # v0.6.12: whether Codex's history has caught up and how many turns run and items wait, asked only
    # for an armed power action whose own checks have passed - counts and sizes, never content.
    "activity",
}
# v0.6.11: what core asks the edition's plug, which it holds as `Guarded` (domain/plug.py). The
# engine asks at the points of a tick, a dispatch and an ended turn; the claim asks the ledger,
# and first whether it is NULL's, which is never asked; the control layer asks for what a surface
# adds and for a start route.
# `null` is not a point: it is how the engine skips the two consent reads P6 needs when there is
# no plug to ask (engine/announce.py), so the standard edition reads what v0.6.10 read.
# `moved` is P14: core tells the plug of each move of a record as it writes it, so a plug learns
# what became of a record from core itself - a paid send that went through submission_unknown
# included, though the watch settled it before P8 looked - and never by reading the journal
# back, which no decision may (tests/test_surface_properties.py). Never told to NULL.
# `delivery` is P15: how a continuation is carried and proven - its marker, or no marker and the
# client id core derives, which core takes only for a send it hands to the plug's channel.
# `unloaded` is P16: a route for a conversation the app does not hold, which core carries out
# through its own claim, pre-send look and launch guard where it would otherwise wait (A11).
# `admission` is P17: whether a failure core never recovers alone is taken up (v0.6.14). `wants` is
# not a point: whether the plug may answer at one now, so core makes that point's reads only then.
ENGINE_TO_PLUG = {"admission", "delivery", "gate", "moved", "null", "outcome", "partition", "records",
                  "schedule", "sender", "text", "tick", "unloaded", "wants"}
# `claim_ledger_checked` is how the claim asks: it says whether that one call raised, so a
# failure on another thread holding the same plug is not read as this claim's (domain/plug.py).
STORE_TO_LEDGER = {"claim_ledger_checked", "null"}
CONTROL_TO_PLUG = {"start_route", "surface"}
# What the one layer a front end calls asks of the state: what to show, and the four things a
# person can ask for - pause, cancel, retry now, give the attempts back.
CONTROL_TO_STORE = {
    "get", "pending", "all_records", "history", "hide_history", "events", "statistics",
    "status_counts", "settings", "watcher_status", "failure_marks", "disabled_threads",
    "thread_enabled", "set_thread_enabled", "set_enabled", "cancel_interruption",
    "cancel_thread", "request_retry_now", "restore_budget_detailed",
    # v0.6.11: postpone one record, let a held one continue, and a conversation's tier.
    "postpone", "release_hold", "set_thread_tier", "thread_tiers",
    # and observe only written as the settings say it, and a project's waiting records held.
    "set_observe_only", "hold_waiting",
    # and a person's own postponement taken away (Don't postpone).
    "unpostpone",
}


class SeamTests(unittest.TestCase):
    def check(self, module: str, receivers: tuple, expected: set, seam: str):
        found = names_on(module_source(module), receivers)
        new, gone = sorted(found - expected), sorted(expected - found)
        self.assertEqual(new, [], "%s asks the %s for something this table does not name. A new "
                                  "call across a seam is a decision: make it here, in the table."
                         % (module, seam))
        self.assertEqual(gone, [], "%s no longer asks the %s for these; take them out of the "
                                   "table in the same commit" % (module, seam))

    def test_the_engine_asks_the_store_for_exactly_these(self):
        self.check("engine", ("store",), ENGINE_TO_STORE, "store")

    def test_the_engine_asks_the_backend_for_exactly_these(self):
        self.check("engine", BACKEND_NAMES, ENGINE_TO_BACKEND, "backend")

    def test_core_asks_the_plug_for_exactly_these(self):
        self.check("engine", ("plug",), ENGINE_TO_PLUG, "plug")
        self.check("store", ("ledger",), STORE_TO_LEDGER, "plug")
        self.check("control", ("plug",), CONTROL_TO_PLUG, "plug")

    def test_the_engine_asks_codex_for_exactly_these(self):
        self.check("engine", ("source",), ENGINE_TO_SOURCE, "source")

    def test_the_control_layer_asks_the_store_for_exactly_these(self):
        self.check("control", ("store",), CONTROL_TO_STORE, "store")

    def test_no_seam_is_wider_than_the_layer_below_it(self):
        """A name in a table that the thing it is asked of does not have is a table gone stale."""
        from codex_auto_resume.store import Store
        for seam, table in (("store", ENGINE_TO_STORE), ("store", CONTROL_TO_STORE)):
            for name in sorted(table):
                with self.subTest(seam=seam, name=name):
                    self.assertTrue(hasattr(Store, name), "Store has no %s" % name)


class ReaderTests(unittest.TestCase):
    """The reader itself, on planted sources: a table is only as good as what fills it."""

    def test_it_finds_a_call_however_it_is_spelled(self):
        source = textwrap.dedent("""
            def f(self, store):
                self.store.one()
                store.two()
                getattr(self.store, 'three')()
                rows = self.store.four
        """)
        self.assertEqual(names_on(source, ("store",)), {"one", "two", "three", "four"})

    def test_it_does_not_take_a_call_on_something_else(self):
        source = textwrap.dedent("""
            def f(self, other):
                other.one()
                self.other.two()
                self.store.three()
        """)
        self.assertEqual(names_on(source, ("store",)), {"three"})


class NoComputedNameTests(unittest.TestCase):
    """A call whose name is built at run time cannot be read out of the source, so none is made."""

    def test_no_name_is_computed(self):
        for module, receivers in (("engine", ("store", "source", "backend")),
                                  ("control", ("store",))):
            source = ast.parse(module_source(module))
            for node in ast.walk(source):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "getattr" and len(node.args) >= 2):
                    continue
                target = node.args[0]
                named = (isinstance(target, ast.Name) and target.id in receivers) or (
                    isinstance(target, ast.Attribute) and target.attr in receivers)
                if named:
                    with self.subTest(module=module, line=node.lineno):
                        self.assertIsInstance(node.args[1], ast.Constant,
                                              "a call built at run time cannot be named in a table")


if __name__ == "__main__":
    unittest.main()

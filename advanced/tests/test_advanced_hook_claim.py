"""Continue inside the turn (stop_hook_continuation, v0.6.20): the claim the Stop hook shares with the watcher
(engine/hookclaims.py), held against core's own store, claim and engine - and the capability hidden until M4 and M4B pass.

Held here: the watcher first, the hook passes and spends nothing; the hook first, core is held from a second
continuation of the same interruption at P3 (the capability's gate) and at P11 (the ledger, whatever the capability's
state), and the hold ends with core's own spacing; once a turn, once an interruption; nothing written with recovery
or the capability off; the hook's continuation is a claim to the caps on one conversation, and core's are to it; and
the two claims serialise on core's claim's lock.
"""
from __future__ import annotations

import contextlib
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, guard  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import hookclaims  # noqa: E402
from codex_auto_resume_advanced.hook.handler import turn_key  # noqa: E402
from codex_auto_resume_advanced.measured import MEASURED  # noqa: E402
from codex_auto_resume_advanced.registry import STOP_HOOK, Registry, offered, problems  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, HookOutcome, Measurement, Verdict  # noqa: E402
from test_advanced_ledger import LedgerCase  # noqa: E402
from test_engine import TURN_A  # noqa: E402

CAPABILITY = "stop_hook_continuation"
ENGINE = "codex-cli 0.163.0-alpha.10.2"


class HiddenTests(unittest.TestCase):
    def test_hidden_until_mhk_m4_and_m4b_all_pass(self):
        """Fails with the WAITING row taken out: a capability no Codex measured to work would be offered."""
        self.assertIsNone(registry.REGISTRY.get(CAPABILITY))
        self.assertNotIn(STOP_HOOK, registry.DEFINITIONS)
        self.assertEqual(MEASURED[Measurement.M4][0], Verdict.FAIL)
        passed = (Verdict.PASS, ENGINE)
        every = {Measurement.MHK: passed, Measurement.M4: passed, Measurement.M4B: passed}
        self.assertNotIn(STOP_HOOK, offered({}))
        for missing in every:
            with self.subTest(missing=missing):
                self.assertNotIn(STOP_HOOK, offered({k: v for k, v in every.items() if k != missing}))
                self.assertNotIn(STOP_HOOK, offered(dict(every, **{missing: (Verdict.FAIL, ENGINE)})))
        self.assertIn(STOP_HOOK, offered(every))

    def test_its_place_is_held_after_the_marker_free_continuation(self):
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index("marker_free_continuation") + 1], CAPABILITY)
        self.assertNotIn(CAPABILITY, [d.id for d in registry.shown(registry.REGISTRY)])
        made = Registry(registry.DEFINITIONS + (STOP_HOOK,))
        shown = [d.id for d in registry.shown(made)]
        self.assertEqual(shown[shown.index("marker_free_continuation") + 1], CAPABILITY)

    def test_its_definition_and_statement_are_whole(self):
        self.assertEqual(problems(STOP_HOOK), [])
        self.assertEqual(statement.CATALOGS.missing(STOP_HOOK), [])
        self.assertEqual(STOP_HOOK.measurements, (Measurement.M4, Measurement.M4B, Measurement.MHK))
        self.assertEqual(set(STOP_HOOK.departs_from), {"A2", "A5", "A26", "B3", "F6"})
        self.assertLessEqual(STOP_HOOK.ceilings.per_conversation, registry.CORE_DAILY_CAP)


class HookClaimCase(LedgerCase):
    EXTRA = (STOP_HOOK,)

    def setUp(self):
        super().setUp()
        self.plug = self.advanced()
        runtime = self.plug.runtime
        result = runtime.arming.arm(CAPABILITY, state="armed", revision=STOP_HOOK.revision,
                                    generation=runtime.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=list(runtime.arming.warnings(STOP_HOOK)), actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        # The hook's own view of the installation: this edition's state where the plug keeps it, and core's file where
        # the harness keeps it - in production one home holds both.
        self.paths = config.Paths(self.where / "home")
        self.paths.state_dir = Path(self.h.store.state_dir)

    def failure(self, row=None):
        row = row or self.h.record()
        return {"interruption_id": row["interruption_id"], "thread_id": row["thread_id"], "turn_id": TURN_A}

    def hook(self, failure=None, *, turn=TURN_A, now=None, busy=hookclaims.BUSY_SECONDS):
        return hookclaims.claim(self.paths, failure or self.failure(), turn_key(turn),
                                self.h.now if now is None else now, registry=self.plug.runtime.registry, busy=busy)

    def ledger(self, row=None, now=None):
        row = row or self.h.record()
        with self.h.store._transaction() as connection:
            return guard(self.plug).claim_ledger(connection, row, self.h.now if now is None else now, frozenset())

    def rows(self):
        with contextlib.closing(sqlite3.connect(self.plug.runtime.state.path)) as connection:
            return connection.execute("SELECT interruption_id, outcome FROM hook_claims ORDER BY at").fetchall()


class ClaimTests(HookClaimCase):
    def test_the_hook_first_holds_core_at_p3_and_p11_until_core_s_own_spacing_ends(self):
        """Fails with both reverted: core sends a second continuation of the same turn. Each is held on its own too -
        the gate's answer below, and the ledger's after the capability is turned off, when no gate of it is asked."""
        self.due()
        self.assertEqual(self.hook(), HookOutcome.BLOCKED)
        code = ac.code_of(self.plug.runtime, CAPABILITY)
        self.assertEqual(code.gate("schedule", self.h.record(), {}), Alternative.HOLD)
        self.assertIs(code.gate("schedule", dict(self.h.record(), interruption_id="%064x" % 3), {}), DEFER)
        self.assertEqual(self.spends(self.plug), [(CAPABILITY, self.h.record()["thread_id"],
                                                   self.h.record()["interruption_id"])])
        self.plugged(self.plug)
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(self.ledger(), Alternative.HOLD)
        self.plug.runtime.arming.disarm(CAPABILITY, actor=Actor.DASHBOARD)
        self.assertEqual(self.ledger(), Alternative.HOLD, "a turn off since does not undo a continuation sent")
        self.assertIs(self.ledger(now=self.h.now + hookclaims.HOLD_SECONDS + 1), DEFER)

    def test_the_watcher_first_the_hook_passes_and_spends_nothing(self):
        row = self.send_and_hold()
        self.assertEqual(self.hook(self.failure(row)), HookOutcome.PASSED)
        self.assertEqual(self.spends(self.plug), [])
        self.assertIsNone(hookclaims.blocked_at(self.paths, row["interruption_id"]))

    def test_once_an_interruption_and_once_a_turn(self):
        self.due()
        self.assertEqual(self.hook(), HookOutcome.BLOCKED)
        self.assertIsNone(self.hook(), "the same interruption again: nothing new written")
        other = dict(self.failure(), interruption_id="%064x" % 7)
        self.assertEqual(self.hook(other), HookOutcome.REFUSED, "the same turn under another id")
        self.assertEqual([outcome for _key, outcome in self.rows()], [HookOutcome.BLOCKED, HookOutcome.REFUSED])

    def test_nothing_is_written_with_recovery_or_the_capability_off(self):
        self.due()
        self.h.store.set_enabled(False, self.h.now)
        self.assertIsNone(self.hook())
        self.h.store.set_enabled(True, self.h.now)
        self.h.store.set_thread_enabled(self.h.record()["thread_id"], False, at=self.h.now)
        self.assertIsNone(self.hook())
        self.h.store.set_thread_enabled(self.h.record()["thread_id"], True, at=self.h.now)
        self.plug.runtime.arming.disarm(CAPABILITY, actor=Actor.DASHBOARD)
        self.assertIsNone(self.hook())
        self.assertEqual(self.rows(), [])

    def test_core_s_claims_on_the_conversation_hold_the_hook_and_the_hook_s_hold_core(self):
        """The caps on one conversation count both ways (standard A20): a claim of core's fifteen minutes ago or less
        refuses the hook, and the hook's unit is a claim core's next one waits fifteen minutes for."""
        self.due()
        thread = self.h.record()["thread_id"]
        with self.h.store._transaction() as connection:
            connection.execute("UPDATE interruptions SET last_claim_at=?, attempt_count=1", (self.h.now - 600,))
        self.assertEqual(self.hook(), HookOutcome.REFUSED)
        self.assertEqual(self.spends(self.plug), [])
        with self.h.store._transaction() as connection:
            connection.execute("UPDATE interruptions SET last_claim_at=?", (self.h.now - 3 * 3600,))
        other = dict(self.failure(), interruption_id="%064x" % 9)
        self.assertEqual(self.hook(other, turn="44444444-4444-4444-8444-444444444444"), HookOutcome.BLOCKED)
        self.assertEqual(self.ledger(), Alternative.HOLD, "fifteen minutes after the hook's continuation")
        self.assertIs(self.ledger(now=self.h.now + 901), DEFER)
        self.assertEqual(hookclaims.spent_on(self._attached(), "advanced", thread, self.h.now)[0], 1)

    def _attached(self):
        connection = sqlite3.connect(self.h.store.state_dir / "state.sqlite")
        self.addCleanup(connection.close)
        connection.execute("ATTACH DATABASE ? AS advanced", (str(self.plug.runtime.state.path),))
        return connection

    def test_the_two_claims_take_turns_on_core_s_claim_s_lock(self):
        """Core's claim holds its file's lock and moves its record on; the hook, asking meanwhile, waits for it and then
        passes - never a continuation of each."""
        self.due()
        key = self.h.record()["interruption_id"]
        failure, found = self.failure(), {}
        with self.h.store._transaction() as connection:
            asking = threading.Thread(target=lambda: found.update(outcome=self.hook(failure, busy=10)))
            asking.start()
            asking.join(0.5)
            self.assertTrue(asking.is_alive(), "the hook waits for core's claim")
            connection.execute("UPDATE interruptions SET state='submitting' WHERE interruption_id=?", (key,))
        asking.join(15)
        self.assertEqual(found.get("outcome"), HookOutcome.PASSED)

    def test_a_lock_not_had_in_time_writes_nothing(self):
        self.due()
        failure, found = self.failure(), {}
        with self.h.store._transaction():
            asking = threading.Thread(target=lambda: found.update(outcome=self.hook(failure, busy=0.2)))
            asking.start()
            asking.join(15)
        self.assertIsNone(found.get("outcome", "unset"))
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()

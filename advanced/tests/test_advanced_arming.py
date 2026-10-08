"""Turning capabilities on and off: only the Dashboard turns one on, anything turns one off,
shadow never promotes itself, a policy only reads one down, and the tripwires.

And the owner's rule of 2026-09-26, which replaced decision C7: a failed measurement, a low
compatibility grade or a route never measured is a warning the person confirms, never a refusal;
only the three policy keys refuse; a tripwire still turns a capability off; and whatever turned
it off, it can always be turned on again.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import edition  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Edition, Point  # noqa: E402
from codex_auto_resume_advanced import policy  # noqa: E402
from codex_auto_resume_advanced.arming import standing, warnings_for  # noqa: E402
from codex_auto_resume_advanced.state import StateError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning,  # noqa: E402
                                                   Measurement, OffReason, Refusal, Verdict)

RECORD = {"interruption_id": ac.KEY, "thread_id": ac.THREAD}


class ArmingCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.rt = self.runtime()

    def stored(self, capability="test_wake"):
        return self.rt.state.arming().get(capability)

    def state_now(self, capability="test_wake"):
        return self.rt.arming.current()[capability]


class DashboardOnlyTests(ArmingCase):
    def test_a_point_is_wanted_while_a_capability_there_is_on_or_watched(self):
        """v0.6.14 (core's Plug.wants): never at a point the capability has no code at, never
        while it is off, and while it is on or only watched, at each of its points."""
        plug = self.plug()
        self.assertFalse(any(plug.wants(point) for point in Point))
        for state in ("shadow", "armed"):
            with self.subTest(state):
                self.assertTrue(self.arm(plug.runtime, state=state)["done"])
                plug.runtime.states(fresh=True)
                self.assertEqual({point for point in Point if plug.wants(point)},
                                 set(ac.definition().points))
        plug.runtime.arming.disarm("test_wake", actor=Actor.DASHBOARD)
        plug.runtime.states(fresh=True)
        self.assertFalse(any(plug.wants(point) for point in Point))

    def test_every_capability_starts_off(self):
        self.assertEqual(self.rt.arming.current(), {"test_wake": ArmingState.OFF})
        self.assertIsNone(self.stored())

    def test_with_nothing_on_it_reads_no_policy_view_or_measurement(self):
        """A capability that is off is off whatever a policy, a compatibility view or a
        measurement says, so an installation that never turned one on reads none of them - it is
        the standard edition, down to what it touches. Only a stored-on row makes it read them."""
        reads = []
        for name in ("_view", "_policy", "_measured"):
            real = getattr(self.rt.arming, name)
            key = name[1:]
            setattr(self.rt.arming, name,
                    (lambda k, f: (lambda: (reads.append(k), f())[1]))(key, real))
        self.assertEqual(self.rt.arming.current(), {"test_wake": ArmingState.OFF})
        self.assertEqual(reads, [], "an all-off registry read a policy, view or measurement")
        # A stored-on row makes it read them: the optimization only skips where nothing is on.
        self.assertTrue(self.arm(self.rt)["done"])
        reads.clear()
        self.rt.arming.current()
        self.assertEqual(set(reads), {"view", "policy", "measured"})

    def test_only_the_dashboard_turns_one_on_or_to_watch(self):
        for actor in (Actor.MCP, Actor.TRAY, Actor.CARD, Actor.TRIPWIRE, Actor.EDITION_ENTRY,
                      Actor.ENGINE_CHANGE, "model", None):
            for state in ("armed", "shadow"):
                with self.subTest(actor=actor, state=state):
                    result = self.arm(self.rt, state=state, actor=actor)
                    self.assertEqual((result["done"], result["refusal"]),
                                     (False, Refusal.NOT_THE_DASHBOARD))
        self.assertIsNone(self.stored())
        self.assertTrue(self.arm(self.rt)["done"])
        self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_it_needs_the_statement_revision_the_person_read(self):
        result = self.arm(self.rt, revision=2)
        self.assertEqual(result["refusal"], Refusal.STALE_REVISION)
        self.assertEqual(self.arm(self.rt, revision="1")["refusal"], Refusal.INVALID_REQUEST)

    def test_it_needs_the_generation_the_dashboard_read_and_a_turn_off_since_wins(self):
        seen = self.rt.state.meta()["generation"]
        self.assertTrue(self.arm(self.rt, state="shadow")["done"])
        self.rt.arming.disarm("test_wake", actor=Actor.MCP)          # somewhere else, since
        result = self.arm(self.rt, generation=seen + 1)
        self.assertEqual(result["refusal"], Refusal.STALE_GENERATION)
        self.assertEqual(result["generation"], seen + 2)
        self.assertEqual(self.stored()["state"], ArmingState.OFF)
        self.assertTrue(self.arm(self.rt, generation=seen + 2)["done"])

    def test_on_needs_the_codex_version_the_dashboard_showed(self):
        """The acknowledgement is part of the person's confirmation: for the Codex in force, and
        a string or none. One for another version, or none while one is known, is stale."""
        for acknowledged in ("0.154.0", None):
            with self.subTest(acknowledged=acknowledged):
                result = self.arm(self.rt, acknowledged_version=acknowledged)
                self.assertEqual((result["done"], result["refusal"]), (False, Refusal.STALE_CONFIRMATION))
        self.assertEqual(self.arm(self.rt, acknowledged_version=155)["refusal"], Refusal.INVALID_REQUEST)
        self.assertIsNone(self.stored())
        self.assertTrue(self.arm(self.rt)["done"])
        self.assertEqual(self.stored()["engine_version"], ac.ENGINE)

    def test_the_package_asks_compat_permits_nothing(self):
        """Decision C7's gate is gone: no grade is a refusal, so nothing here asks permits."""
        package = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
        for path in sorted(package.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {getattr(node, "attr", None) or getattr(node, "id", None) for node in ast.walk(tree)}
            names |= {alias.name for node in ast.walk(tree)
                      if isinstance(node, ast.ImportFrom) for alias in node.names}
            self.assertNotIn("permits", names, path.name)

    def test_watching_needs_no_acknowledgement_and_stores_none(self):
        self.compat = ac.view("UNKNOWN")
        self.assertTrue(self.arm(self.rt, state="shadow", acknowledged_version=None,
                                 warnings=["compat_unknown"])["done"])
        self.assertEqual((self.stored()["state"], self.stored()["engine_version"]), ("shadow", None))
        self.assertEqual(self.stored()["warnings"], (ArmingWarning.COMPAT_UNKNOWN,))

    def test_a_statement_missing_in_english_cannot_have_been_read(self):
        self.catalogs = ac.catalogs(self.home.parent / "partial", ac.definition(),
                                    leave_out={("en", "risks")})
        runtime = self.runtime()
        self.assertEqual(self.arm(runtime)["refusal"], Refusal.STATEMENT_INCOMPLETE)

    def test_an_unknown_capability_or_state_is_refused(self):
        result = self.rt.arming.arm("not_there", state="armed", revision=1, generation=0,
                                    acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.UNKNOWN_CAPABILITY)
        for state in ("off", "on", None):
            self.assertEqual(self.arm(self.rt, state=state)["refusal"], Refusal.INVALID_REQUEST)


class OffTests(ArmingCase):
    def test_any_surface_turns_one_off_with_nothing_but_its_id(self):
        for actor in (Actor.DASHBOARD, Actor.MCP, Actor.TRAY, Actor.CARD):
            with self.subTest(actor):
                self.assertTrue(self.arm(self.rt)["done"])
                result = self.rt.arming.disarm("test_wake", actor=actor)
                self.assertEqual((result["done"], result["changed"]), (True, True))
                self.assertEqual((self.stored()["state"], self.stored()["actor"], self.stored()["reason"]),
                                 ("off", actor, "disarmed"))
        self.assertEqual(self.rt.arming.disarm("test_wake", actor=Actor.MCP)["changed"], False)
        self.assertEqual(self.rt.arming.disarm("nope", actor=Actor.MCP)["refusal"], Refusal.UNKNOWN_CAPABILITY)
        self.assertEqual(self.rt.arming.disarm("test_wake", actor=Actor.TRIPWIRE)["refusal"],
                         Refusal.INVALID_REQUEST)

    def test_all_advanced_features_off_turns_every_one_off_at_once(self):
        second = ac.definition(id="test_sleep", journal_prefix="ts")
        runtime = self.runtime(ac.definition(), second)
        self.catalogs = ac.catalogs(self.home.parent / "two", ac.definition(), second)
        runtime.arming.catalogs = self.catalogs
        self.assertTrue(self.arm(runtime)["done"])
        self.assertTrue(self.arm(runtime, "test_sleep", state="shadow")["done"])
        result = runtime.arming.all_off(actor=Actor.CARD)
        self.assertEqual((result["done"], result["count"]), (True, 2))
        self.assertEqual({row["state"] for row in runtime.state.arming().values()}, {ArmingState.OFF})
        self.assertEqual(runtime.arming.all_off(actor=Actor.MCP)["count"], 0)

    def test_where_nothing_was_ever_on_turning_off_writes_nothing(self):
        self.assertTrue(self.rt.arming.all_off(actor=Actor.MCP)["done"])
        self.assertTrue(self.rt.arming.disarm("test_wake", actor=Actor.MCP)["done"])
        self.assertFalse(self.home.exists())


class ShadowTests(ArmingCase):
    def test_shadow_never_promotes_itself(self):
        """Whatever a watched capability answers, and however long, it stays watched: only a
        person arming it moves it."""
        self.assertTrue(self.arm(self.rt, state="shadow")["done"])
        code = ac.code_of(self.rt)
        chooser = random.Random(611)
        answers = [Alternative.HOLD, "Go on.", "hold", 42, None, object(), DEFER]
        for step in range(300):
            code.answers = {hook: chooser.choice(answers) for hook in ("gate", "text", "schedule", "tick")}
            point = chooser.choice((Point.GATES, Point.TEXT, Point.SCHEDULE))
            arguments = {Point.GATES: ("usage", RECORD, {}), Point.TEXT: (RECORD, "core"),
                         Point.SCHEDULE: (RECORD, self.now)}[point]
            self.assertIs(self.rt.ask(point, *arguments), DEFER)
            if step % 50 == 0:
                self.rt.tick(None)
            self.now += 61
        self.assertEqual(self.stored()["state"], ArmingState.SHADOW)
        codes = {line["code"] for line in self.rt.state.journal(limit=5000)}
        self.assertLessEqual(codes, {"watched", "would_have"})
        self.assertEqual(self.rt.state.spent("test_wake", ac.THREAD)["capability_day"], 0)

    def test_nothing_in_the_package_moves_a_capability_to_on_but_the_dashboards_arm(self):
        """Read from the source: the one call that stores ARMED is `Arming.arm`'s move."""
        package = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
        found = []
        for path in sorted(package.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "move":
                    found.append((path.name, ast.unparse(node.args[1]) if len(node.args) > 1 else None))
        self.assertEqual(sorted(found), [("arming.py", "ArmingState.OFF"), ("arming.py", "ArmingState.OFF"),
                                         ("arming.py", "state")])


class PolicyTests(ArmingCase):
    def test_forbidden_reads_every_capability_off_and_refuses_arming(self):
        self.assertTrue(self.arm(self.rt)["done"])
        self.policy = policy.Policy(forbid=True)
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual(self.stored()["state"], ArmingState.ARMED)      # nothing stored changes
        self.assertEqual(self.arm(self.rt, generation=1)["refusal"], Refusal.FORBIDDEN_BY_POLICY)
        self.policy = policy.NONE
        self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_a_list_allows_only_its_ids(self):
        self.assertTrue(self.arm(self.rt)["done"])
        self.policy = policy.Policy(allowed=frozenset({"test_sleep"}))
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual(self.arm(self.rt, state="shadow")["refusal"], Refusal.NOT_ALLOWED_BY_POLICY)
        self.policy = policy.Policy(allowed=frozenset({"test_wake"}))
        self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_forced_shadow_watches_what_is_on_and_refuses_on(self):
        self.assertTrue(self.arm(self.rt)["done"])
        self.policy = policy.Policy(force_shadow=True)
        self.assertEqual(self.state_now(), ArmingState.SHADOW)
        self.assertEqual(self.arm(self.rt)["refusal"], Refusal.SHADOW_FORCED_BY_POLICY)
        self.assertTrue(self.arm(self.rt, state="shadow")["done"])

    def test_both_hives_count_and_together_are_the_stricter(self):
        def reader(values):
            return lambda hive, name: values.get((hive, name))
        dword, text, listed = policy.DWORD, policy.TEXT, policy.LIST
        cases = [
            ({}, policy.NONE),
            ({("HKCU", "ForbidAdvanced"): (1, dword)}, policy.Policy(forbid=True)),
            ({("HKLM", "ForbidAdvanced"): (0, dword)}, policy.NONE),
            ({("HKLM", "ForceShadow"): ("1", text)}, policy.Policy(force_shadow=True)),
            ({("HKLM", "ForbidAdvanced"): (2, dword)}, policy.Policy(forbid=True)),
            ({("HKLM", "AllowedCapabilities"): (["a, b", "c"], listed),
              ("HKCU", "AllowedCapabilities"): ("b;c d", text)},
             policy.Policy(allowed=frozenset({"b", "c"}))),
            ({("HKCU", "AllowedCapabilities"): (7, dword)}, policy.Policy(allowed=frozenset())),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(policy.read(reader(values)), expected)

        def unreadable(hive, name):
            raise policy.Unreadable("denied")
        self.assertEqual(policy.read(unreadable), policy.STRICTEST)

    def test_the_windows_reader_opens_the_key_for_reading_and_nothing_else(self):
        opened = []

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        class FakeWinreg:
            HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER, KEY_READ = "HKLM", "HKCU", 0x20019
            REG_DWORD, REG_SZ, REG_EXPAND_SZ, REG_MULTI_SZ = 4, 1, 2, 7

            def OpenKey(self, root, key, reserved, access):
                opened.append((root, key, access))
                if root == "HKLM":
                    raise FileNotFoundError(key)
                return Key()

            def QueryValueEx(self, key, name):
                if name == "ForbidAdvanced":
                    return 1, 4
                raise FileNotFoundError(name)

        with patch.dict(sys.modules, {"winreg": FakeWinreg()}), patch.object(policy.os, "name", "nt"):
            found = policy.read()
        self.assertEqual(found, policy.Policy(forbid=True))
        self.assertTrue(opened)
        self.assertEqual({(key, access) for _root, key, access in opened},
                         {(r"Software\Policies\CodexAutoResume", 0x20019)})

    def test_the_package_writes_the_registry_nowhere(self):
        package = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
        writes = {"CreateKey", "CreateKeyEx", "SetValue", "SetValueEx", "DeleteKey", "DeleteKeyEx",
                  "DeleteValue", "KEY_WRITE", "KEY_SET_VALUE", "KEY_ALL_ACCESS"}
        users = set()
        for path in sorted(package.rglob("*.py")):
            names = {getattr(node, "attr", None) or getattr(node, "id", None)
                     for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))}
            self.assertEqual(names & writes, set(), path.name)
            if "winreg" in names:
                users.add(path.name)
        self.assertEqual(users, {"policy.py"})


class TripwireTests(ArmingCase):
    def armed(self):
        self.assertTrue(self.arm(self.rt)["done"])
        self.assertEqual(self.state_now(), ArmingState.ARMED)

    def assert_tripped(self, reason, actor=Actor.TRIPWIRE):
        row = self.stored()
        self.assertEqual((row["state"], row["actor"], row["reason"]), (ArmingState.OFF, actor, reason))

    def test_a_new_statement_revision_turns_it_off_until_the_new_one_is_read(self):
        for state in ("armed", "shadow"):
            with self.subTest(state):
                self.assertTrue(self.arm(self.rt, state=state)["done"])
                runtime = self.runtime(ac.definition(revision=2))
                self.assertEqual(runtime.arming.current()["test_wake"], ArmingState.OFF)
                self.assert_tripped(OffReason.STATEMENT_CHANGED)
                self.assertEqual(self.arm(runtime, revision=1)["refusal"], Refusal.STALE_REVISION)

    def test_the_compatibility_it_stands_on_failing_turns_it_off(self):
        for state, reason, tripped in (("FAILED_HERE", "local_check_failed_here", OffReason.FAILED_HERE),
                                       ("INCOMPATIBLE", "local_check_failed", OffReason.LOCAL_CHECK_FAILED),
                                       ("INCOMPATIBLE", "registry_incompatible", OffReason.INCOMPATIBLE)):
            with self.subTest(state=state, reason=reason):
                self.compat = ac.view()
                self.armed()
                self.compat = ac.view(state, reason=reason)
                self.assertEqual(self.state_now(), ArmingState.OFF)
                self.assert_tripped(tripped)
                self.compat = ac.view()
                self.assertEqual(self.state_now(), ArmingState.OFF, "a trip is not undone by itself")

    def test_a_hook_that_raises_trips_its_own_capability_and_costs_its_answer(self):
        self.armed()
        ac.code_of(self.rt).answers["gate"] = RuntimeError("broken")
        self.assertIs(self.rt.ask(Point.GATES, "usage", RECORD, {}), DEFER)
        self.assert_tripped(OffReason.HOOK_EXCEPTION)
        ac.code_of(self.rt).answers["gate"] = Alternative.HOLD
        self.assertIs(self.rt.ask(Point.GATES, "usage", RECORD, {}), DEFER, "off, so not asked")

    def test_a_send_it_paid_for_that_became_submission_unknown_turns_it_off(self):
        self.armed()
        self.now += 10
        with self.rt.state._transaction() as connection:
            self.rt.state.record_spend(connection, "main", "test_wake", ac.THREAD, ac.KEY, self.now)

        class CoreView:
            def __init__(self, state):
                self.state = state

            def get(self, key):
                return {"interruption_id": key, "state": self.state}

        self.rt.tick(CoreView("queued"))
        self.assertEqual(self.stored()["state"], ArmingState.ARMED)
        self.rt.tick(CoreView("submission_unknown"))
        self.assert_tripped(OffReason.SUBMISSION_UNKNOWN)
        # Turned on again afterwards, an older send does not turn it off a second time.
        self.now += 10
        self.armed()
        self.rt.tick(CoreView("submission_unknown"))
        self.assertEqual(self.stored()["state"], ArmingState.ARMED)

    def test_core_moving_a_send_it_paid_for_into_submission_unknown_turns_it_off(self):
        """P14: told as core writes the move, whatever the record's state is by the next tick."""
        self.armed()
        self.now += 10
        with self.rt.state._transaction() as connection:
            self.rt.state.record_spend(connection, "main", "test_wake", ac.THREAD, ac.KEY, self.now)
        unpaid = dict(RECORD, interruption_id="b" * 64, state="submitting")
        for record, state in ((dict(RECORD, state="submitting"), "queued"),
                              (unpaid, "submission_unknown")):
            with self.subTest(record=record["interruption_id"][:4], state=state):
                self.assertIs(self.rt.moved(record, state), DEFER)
                self.assertEqual(self.stored()["state"], ArmingState.ARMED,
                                 "not a move into submission_unknown, or not a send it paid for")
        self.assertIs(self.rt.moved(dict(RECORD, state="submitting"), "submission_unknown"), DEFER)
        self.assert_tripped(OffReason.SUBMISSION_UNKNOWN)
        self.assertEqual(self.rt.states()["test_wake"], ArmingState.OFF, "off from here, not next tick")
        # Turned on again afterwards, an older send moving again does not turn it off a second time.
        self.now += 10
        self.armed()
        self.rt.moved(dict(RECORD, state="queued"), "submission_unknown")
        self.assertEqual(self.stored()["state"], ArmingState.ARMED)

    def test_only_the_send_it_paid_for_going_unknown_turns_it_off(self):
        """A unit is spent inside the claim it pays for, at the claim's time. A later send of the
        same record that core made alone - claimed later, with nothing of the capability's in it -
        going unknown is not the capability's doing, whether core tells the move (P14) or holds the
        record so at a tick; the send it did pay for is, and so is one whose claim cannot be read."""
        class CoreView:
            def __init__(self, record):
                self.record = record

            def get(self, key):
                return dict(self.record, interruption_id=key)

        for how in ("told", "held"):
            for send, later, trips in (("core's own, later", 900.0, False), ("the one it paid for", 0.0, True),
                                       ("a claim that cannot be read", None, True)):
                with self.subTest(how=how, send=send):
                    self.setUp()
                    self.armed()
                    self.now += 10
                    paid = self.now
                    with self.rt.state._transaction() as connection:
                        self.rt.state.record_spend(connection, "main", "test_wake", ac.THREAD, ac.KEY, paid)
                    self.now += 1000
                    record = dict(RECORD, state="submitting",
                                  last_claim_at=None if later is None else paid + later)
                    if how == "told":
                        self.rt.moved(record, "submission_unknown")
                    else:
                        self.rt.tick(CoreView(dict(record, state="submission_unknown")))
                    if trips:
                        self.assert_tripped(OffReason.SUBMISSION_UNKNOWN)
                    else:
                        self.assertEqual(self.stored()["state"], ArmingState.ARMED)

    def test_a_trip_that_could_not_be_written_as_core_told_it_is_written_at_the_next_tick(self):
        """Core tells a move once. Where the trip cannot be written then - the state locked past
        its timeout, or not to be opened - it is owed, and the next tick writes it though the
        record has settled and its state says nothing any more. Once written it is not owed."""
        class CoreView:
            def get(self, key):
                return {"interruption_id": key, "state": "turn_started"}

        for failing in ("move", "arming"):
            with self.subTest(failing):
                self.setUp()
                self.armed()
                self.now += 10
                with self.rt.state._transaction() as connection:
                    self.rt.state.record_spend(connection, "main", "test_wake", ac.THREAD, ac.KEY,
                                               self.now)
                with patch.object(self.rt.state, failing, side_effect=StateError("locked")):
                    self.rt.moved(dict(RECORD, state="submitting"), "submission_unknown")
                self.assertEqual(self.stored()["state"], ArmingState.ARMED, "not written")
                self.rt.tick(CoreView())
                self.assert_tripped(OffReason.SUBMISSION_UNKNOWN)
                self.now += 10
                self.armed()
                self.rt.tick(CoreView())
                self.assertEqual(self.stored()["state"], ArmingState.ARMED, "owed no longer")

    def test_a_move_is_read_only_when_it_is_into_submission_unknown(self):
        """Every other move is told too, and costs nothing: no state is read for it."""
        self.armed()
        with patch.object(self.rt.state, "arming", side_effect=AssertionError("read")):
            for state in ("submitting", "queued", "turn_started", "recovered", "cancelled"):
                self.assertIs(self.rt.moved(RECORD, state), DEFER)

    def test_a_new_codex_version_turns_on_off_and_leaves_watching_alone(self):
        self.armed()
        self.compat = ac.view(version="0.156.0")
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assert_tripped(OffReason.ENGINE_CHANGED, Actor.ENGINE_CHANGE)
        self.assertTrue(self.arm(self.rt, state="shadow", generation=self.rt.state.meta()["generation"])["done"])
        self.assertEqual(self.state_now(), ArmingState.SHADOW)

    def test_an_unknown_compatibility_holds_it_back_without_turning_it_off(self):
        self.armed()
        self.compat = ac.view("UNKNOWN")
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual(self.stored()["state"], ArmingState.ARMED)
        self.compat = ac.view()
        self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_standing_is_pure(self):
        row = {"state": ArmingState.ARMED, "statement_revision": 1, "engine_version": ac.ENGINE}
        self.assertEqual(standing(ac.definition(), row, policy.NONE, ac.view()),
                         (ArmingState.ARMED, None, None, None))
        self.assertEqual(standing(ac.definition(), None, policy.NONE, ac.view()),
                         (ArmingState.OFF, None, None, None))
        failed = {Measurement.M2: (Verdict.FAIL, ac.ENGINE)}
        measured = ac.definition(measurements=(Measurement.M2,))
        self.assertEqual(standing(measured, row, policy.NONE, ac.view(), failed),
                         (ArmingState.OFF, OffReason.MEASUREMENT_FAILED, None, None))
        confirmed = dict(row, warnings=(ArmingWarning.MEASUREMENT_FAILED,))
        self.assertEqual(standing(measured, confirmed, policy.NONE, ac.view(), failed),
                         (ArmingState.ARMED, None, None, None))
        self.assertEqual(standing(ac.definition(), row, policy.NONE, ac.view(version=None)),
                         (ArmingState.OFF, None, ArmingWarning.ENGINE_UNKNOWN, None))


class WarningCase(ArmingCase):
    """A capability whose route rests on M2, whatever its grade and its measurement say."""

    def setUp(self):
        super().setUp()
        self.definition = ac.definition(measurements=(Measurement.M2,))
        self.rt = self.runtime(self.definition)
        self.measured = {Measurement.M2: (Verdict.PASS, ac.ENGINE)}

    def shown(self):
        """What the Dashboard would show and send back: the statement's warnings and version."""
        statement = self.rt.arming.statement(self.definition, "en")
        return [item["warning"] for item in statement["warnings"]["items"]], statement["engine_version"]

    def fresh(self):
        """Off, in a world where nothing is wrong: what setUp leaves, without making it again."""
        self.rt.arming.all_off(actor=Actor.DASHBOARD)
        self.compat, self.policy = ac.view(), policy.NONE
        self.measured = {Measurement.M2: (Verdict.PASS, ac.ENGINE)}

    def confirm(self, state="armed", **changes):
        warnings, version = self.shown()
        request = dict(state=state, warnings=warnings, acknowledged_version=version,
                       generation=self.rt.state.meta()["generation"])
        request.update(changes)
        return self.arm(self.rt, **request)


class WarningTests(WarningCase):
    # What is so, and the warnings the statement shows for it.
    PATHS = {
        "a measurement that failed": (dict(measured={Measurement.M2: (Verdict.FAIL, ac.ENGINE)}),
                                      ["measurement_failed"]),
        "a measurement that failed on another Codex": (
            dict(measured={Measurement.M2: (Verdict.FAIL, "0.150.0")}), ["measurement_failed"]),
        "a route never measured": (dict(measured={}), ["unmeasured"]),
        "a pass on another Codex only": (dict(measured={Measurement.M2: (Verdict.PASS, "0.150.0")}),
                                         ["unmeasured"]),
        "a blocked measurement nobody completed": (
            dict(measured={Measurement.M2: (Verdict.BLOCKED, ac.ENGINE)}), ["unmeasured"]),
        "FAILED_HERE": (dict(compat=ac.view("FAILED_HERE", reason="local_check_failed_here")),
                        ["failed_here"]),
        "INCOMPATIBLE by the registry": (
            dict(compat=ac.view("INCOMPATIBLE", reason="registry_incompatible")), ["incompatible"]),
        "INCOMPATIBLE by a local check": (
            dict(compat=ac.view("INCOMPATIBLE", reason="local_check_failed")), ["local_check_failed"]),
        "a grade nobody knows": (dict(compat=ac.view("UNKNOWN")), ["compat_unknown"]),
        "a grade the view does not name": (dict(compat=ac.view("SPLENDID")), ["compat_unknown"]),
        "no Codex version": (dict(compat=ac.view(version=None)), ["unmeasured", "engine_unknown"]),
        "no view at all": (dict(compat={}), ["unmeasured", "compat_unknown", "engine_unknown"]),
        "two at once": (dict(compat=ac.view("FAILED_HERE"), measured={}), ["unmeasured", "failed_here"]),
    }

    def given(self, measured=None, compat=None):
        self.measured = self.measured if measured is None else measured
        self.compat = self.compat if compat is None else compat

    def test_every_warning_is_shown_and_none_refuses_once_it_is_confirmed(self):
        for name, (world, expected) in self.PATHS.items():
            with self.subTest(name):
                self.fresh()
                self.given(**world)
                warnings, version = self.shown()
                self.assertEqual(warnings, expected)
                for state in ("shadow", "armed"):
                    result = self.confirm(state)
                    self.assertEqual((result["done"], result["refusal"], result["warnings"]),
                                     (True, None, expected), state)
                    self.assertEqual(self.stored()["warnings"],
                                     tuple(ArmingWarning(word) for word in expected))
                self.assertEqual(self.stored()["engine_version"], version)
                for _ in range(3):
                    self.rt.tick(None)
                    self.now += 61
                    self.assertEqual(self.state_now(), ArmingState.ARMED,
                                     "a warning the person confirmed never turns it off")

    def test_a_warning_not_confirmed_is_a_stale_confirmation_that_hands_back_what_holds_now(self):
        for name, (world, expected) in self.PATHS.items():
            with self.subTest(name):
                self.fresh()
                self.given(**world)
                _warnings, version = self.shown()
                for state in ("shadow", "armed"):
                    result = self.arm(self.rt, state=state, warnings=[], acknowledged_version=version)
                    self.assertEqual((result["done"], result["refusal"], result["warnings"]),
                                     (False, Refusal.STALE_CONFIRMATION, expected))
                self.assertEqual((self.stored() or {}).get("state", ArmingState.OFF), ArmingState.OFF)
                self.assertTrue(self.confirm(warnings=result["warnings"])["done"])

    def test_confirming_what_does_not_hold_is_stale_too_and_a_word_nobody_has_is_invalid(self):
        self.given(measured={})
        self.assertEqual(self.confirm(warnings=["unmeasured", "failed_here"])["refusal"],
                         Refusal.STALE_CONFIRMATION)
        for warnings in (["unmeasured", "fine_really"], "unmeasured", [7], {"unmeasured": True}):
            with self.subTest(warnings=warnings):
                self.assertEqual(self.confirm(warnings=warnings)["refusal"], Refusal.INVALID_REQUEST)
        self.assertIsNone(self.stored())
        self.assertTrue(self.confirm(warnings=["unmeasured", "unmeasured"])["done"])

    def test_nothing_shown_is_nothing_to_confirm(self):
        self.assertEqual(self.shown(), ([], ac.ENGINE))
        self.assertTrue(self.arm(self.rt)["done"])
        self.assertEqual(self.stored()["warnings"], ())

    def test_warnings_for_is_pure_and_in_the_vocabularys_order(self):
        found = warnings_for(self.definition, ac.view("INCOMPATIBLE", version=None), {})
        self.assertEqual(found, (ArmingWarning.UNMEASURED, ArmingWarning.INCOMPATIBLE,
                                 ArmingWarning.ENGINE_UNKNOWN))
        self.assertEqual(warnings_for(ac.definition(), ac.view("VERIFIED"), {}), ())
        self.assertEqual(warnings_for(ac.definition(), ac.view("CHECKED"), "not a table"), ())

    def test_a_measurement_table_that_cannot_be_read_is_every_route_unmeasured(self):
        def broken():
            raise OSError("gone")
        self.rt.arming._measured = broken
        self.assertEqual(self.shown()[0], ["unmeasured"])

    def test_on_while_no_codex_version_is_known_turns_off_once_one_is(self):
        """Confirmed without a version, "on" holds only while none is known: the version that
        then appears is one nobody acknowledged."""
        self.given(compat=ac.view(version=None))
        self.assertTrue(self.confirm()["done"])
        self.assertIsNone(self.stored()["engine_version"])
        self.assertEqual(self.state_now(), ArmingState.ARMED)
        self.compat = ac.view()
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual((self.stored()["actor"], self.stored()["reason"]),
                         (Actor.ENGINE_CHANGE, OffReason.ENGINE_CHANGED))
        self.assertTrue(self.confirm()["done"], "and it is turned on again for the one now known")

    def test_a_version_or_grade_that_cannot_be_read_holds_on_back_unless_it_was_confirmed(self):
        self.assertTrue(self.confirm()["done"])
        for unreadable in ({}, ac.view(version=None), ac.view("UNKNOWN")):
            with self.subTest(unreadable=unreadable):
                self.compat = unreadable
                self.assertEqual(self.state_now(), ArmingState.OFF)
                self.assertEqual(self.stored()["state"], ArmingState.ARMED, "nothing stored changes")
                self.compat = ac.view()
                self.assertEqual(self.state_now(), ArmingState.ARMED)


class WarningTripwireTests(WarningCase):
    def assert_tripped(self, reason):
        row = self.stored()
        self.assertEqual((row["state"], row["actor"], row["reason"]),
                         (ArmingState.OFF, Actor.TRIPWIRE, reason))

    def test_a_failure_the_person_did_not_confirm_trips_it_on_or_watched(self):
        cases = (
            (dict(compat=ac.view("FAILED_HERE")), OffReason.FAILED_HERE),
            (dict(compat=ac.view("INCOMPATIBLE", reason="registry_incompatible")), OffReason.INCOMPATIBLE),
            (dict(compat=ac.view("INCOMPATIBLE", reason="local_check_failed")),
             OffReason.LOCAL_CHECK_FAILED),
            (dict(measured={Measurement.M2: (Verdict.FAIL, ac.ENGINE)}), OffReason.MEASUREMENT_FAILED),
        )
        for world, reason in cases:
            for state in ("armed", "shadow"):
                with self.subTest(reason=reason, state=state):
                    self.fresh()
                    self.assertTrue(self.confirm(state)["done"])
                    self.compat = world.get("compat", self.compat)
                    self.measured = world.get("measured", self.measured)
                    self.assertEqual(self.state_now(), ArmingState.OFF)
                    self.assert_tripped(reason)
                    self.compat = ac.view()
                    self.measured = {Measurement.M2: (Verdict.PASS, ac.ENGINE)}
                    self.assertEqual(self.state_now(), ArmingState.OFF, "a trip is not undone by itself")

    def test_a_confirmed_failure_that_gets_worse_trips_it(self):
        """Confirmed FAILED_HERE; a local check then finds it incompatible - a new failure."""
        self.compat = ac.view("FAILED_HERE")
        self.assertTrue(self.confirm()["done"])
        self.compat = ac.view("INCOMPATIBLE", reason="local_check_failed")
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assert_tripped(OffReason.LOCAL_CHECK_FAILED)

    def test_a_route_unmeasured_on_a_new_codex_is_a_new_codex_for_on_and_nothing_for_watching(self):
        self.assertTrue(self.confirm("shadow")["done"])
        self.compat = ac.view(version="0.156.0")
        self.assertEqual(self.state_now(), ArmingState.SHADOW)
        self.assertTrue(self.confirm()["done"])
        self.compat = ac.view(version="0.157.0")
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual(self.stored()["reason"], OffReason.ENGINE_CHANGED)


class RemainingRefusalTests(WarningCase):
    """Only the three policy keys refuse a capability, whatever its warnings; every other
    refusal is about the request, and the same request made current is done."""

    def given_everything_wrong(self):
        self.measured = {Measurement.M2: (Verdict.FAIL, ac.ENGINE)}
        self.compat = ac.view("INCOMPATIBLE", reason="registry_incompatible")

    def test_the_three_policy_keys_refuse_even_with_every_warning_confirmed(self):
        self.given_everything_wrong()
        for found, state, refusal in (
                (policy.Policy(forbid=True), "armed", Refusal.FORBIDDEN_BY_POLICY),
                (policy.Policy(forbid=True), "shadow", Refusal.FORBIDDEN_BY_POLICY),
                (policy.Policy(allowed=frozenset({"test_sleep"})), "armed", Refusal.NOT_ALLOWED_BY_POLICY),
                (policy.Policy(allowed=frozenset()), "shadow", Refusal.NOT_ALLOWED_BY_POLICY),
                (policy.Policy(force_shadow=True), "armed", Refusal.SHADOW_FORCED_BY_POLICY),
                (policy.STRICTEST, "shadow", Refusal.FORBIDDEN_BY_POLICY)):
            with self.subTest(policy=found, state=state):
                self.policy = found
                self.assertEqual(self.confirm(state)["refusal"], refusal)
        self.assertIsNone(self.stored())
        self.policy = policy.Policy(force_shadow=True)
        self.assertTrue(self.confirm("shadow")["done"], "forced to watch, watching is allowed")
        self.policy = policy.NONE
        self.assertTrue(self.confirm()["done"])

    def test_a_policy_that_cannot_be_read_is_the_strictest(self):
        def unreadable():
            raise OSError("denied")
        self.rt.arming._policy = unreadable
        self.assertEqual(self.confirm("shadow")["refusal"], Refusal.FORBIDDEN_BY_POLICY)

    def test_no_grade_and_no_measurement_is_ever_a_refusal(self):
        """Every grade the view can hold, with every reason, against every measurement outcome
        and a Codex version known or not: confirmed as shown, it is done."""
        from codex_auto_resume.compat.model import STATES
        outcomes = ({}, {Measurement.M2: (Verdict.PASS, ac.ENGINE)},
                    {Measurement.M2: (Verdict.PASS, "0.1.0")}, {Measurement.M2: (Verdict.FAIL, ac.ENGINE)})
        for grade in STATES:
            for reason in ("local_check_failed", "registry_incompatible", "local_checks_passed"):
                for measured in outcomes:
                    for version in (ac.ENGINE, None):
                        with self.subTest(grade=grade, reason=reason, measured=measured, version=version):
                            self.fresh()
                            self.compat = ac.view(grade, reason=reason, version=version)
                            self.measured = measured
                            result = self.confirm()
                            self.assertEqual((result["done"], result["refusal"]), (True, None))
                            self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_the_refusals_arm_can_give_are_the_policys_and_the_requests(self):
        """Read from the source: every Refusal `arm` names. None of them is about a grade or a
        measurement - those are warnings - and NOT_PERMITTED, C7's word, is gone."""
        import inspect
        import textwrap
        from codex_auto_resume_advanced import arming
        tree = ast.parse(textwrap.dedent(inspect.getsource(arming.Arming.arm)))
        named = {node.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "Refusal"}
        self.assertEqual(named, {"NOT_THE_DASHBOARD", "UNKNOWN_CAPABILITY", "INVALID_REQUEST",
                                 "FORBIDDEN_BY_POLICY", "NOT_ALLOWED_BY_POLICY",
                                 "SHADOW_FORCED_BY_POLICY", "STALE_REVISION", "STATEMENT_INCOMPLETE",
                                 "STALE_CONFIRMATION", "STALE_GENERATION", "STATE_UNAVAILABLE"})
        self.assertNotIn("not_permitted", {str(word) for word in Refusal})


class ReArmTests(WarningCase):
    """Whatever turned a capability off, the Dashboard can turn it on again."""

    def test_after_every_way_off_it_can_be_turned_on_again(self):
        ways = {
            "a person, in the Dashboard": lambda: self.rt.arming.disarm("test_wake", actor=Actor.DASHBOARD),
            "a model, through MCP": lambda: self.rt.arming.disarm("test_wake", actor=Actor.MCP),
            "all advanced features off": lambda: self.rt.arming.all_off(actor=Actor.TRAY),
            "a failure here": lambda: setattr(self, "compat", ac.view("FAILED_HERE")),
            "a failed measurement": lambda: setattr(
                self, "measured", {Measurement.M2: (Verdict.FAIL, ac.ENGINE)}),
            "a hook that raised": lambda: self.rt.arming.trip("test_wake", OffReason.HOOK_EXCEPTION),
            "a send left unknown": lambda: self.rt.arming.trip("test_wake", OffReason.SUBMISSION_UNKNOWN),
            "a new Codex": lambda: setattr(self, "compat", ac.view(version="0.156.0")),
            "entering the edition": lambda: self.rt.arming.edition_entered(),
        }
        for name, way in ways.items():
            with self.subTest(name):
                self.fresh()
                self.assertTrue(self.confirm()["done"])
                way()
                self.assertEqual(self.state_now(), ArmingState.OFF)
                self.assertEqual(self.stored()["state"], ArmingState.OFF)
                result = self.confirm()
                self.assertEqual((result["done"], result["refusal"]), (True, None))
                self.assertEqual(self.state_now(), ArmingState.ARMED)

    def test_a_new_statement_is_read_and_then_turned_on_again(self):
        self.assertTrue(self.confirm()["done"])
        self.definition = ac.definition(measurements=(Measurement.M2,), revision=2)
        self.catalogs = ac.catalogs(self.home.parent / "second", self.definition)
        self.rt = self.runtime(self.definition)
        self.assertEqual(self.state_now(), ArmingState.OFF)
        self.assertEqual(self.confirm(revision=1)["refusal"], Refusal.STALE_REVISION)
        self.assertTrue(self.confirm(revision=2)["done"])

class EditionEntryTests(ArmingCase):
    def test_entering_the_edition_turns_every_capability_off(self):
        self.assertTrue(self.arm(self.rt)["done"])
        plug = self.plug()
        self.assertIsNone(plug.edition_changed(Edition.STANDARD))
        self.assertEqual((self.stored()["state"], self.stored()["actor"], self.stored()["reason"]),
                         (ArmingState.OFF, Actor.EDITION_ENTRY, OffReason.EDITION_ENTERED))
        self.assertEqual(self.rt.state.journal()[-1]["code"], "reset")

    def test_through_the_installers_own_call(self):
        """`install --edition-from standard` tells the plug edition.py loads (commands/install.py)."""
        self.assertTrue(self.arm(self.rt)["done"])
        from codex_auto_resume.commands import install
        app = type("App", (), {"paths": self.paths, "logger": type("L", (), {"info": lambda *a: None})()})()
        with patch.object(edition, "plug", return_value=self.plug()), \
                patch.object(install, "_print", lambda *_: None):
            install._edition_changed(app, Edition.STANDARD)
        self.assertEqual(self.stored()["reason"], OffReason.EDITION_ENTERED)


class CeilingTests(ArmingCase):
    def test_the_global_ceiling_is_lowered_in_the_dashboard_and_never_raised_past_twelve(self):
        arming = self.rt.arming
        self.assertEqual(arming.set_global_hourly(3, generation=0, actor=Actor.MCP)["refusal"],
                         Refusal.NOT_THE_DASHBOARD)
        for value in (0, 13, 12.0, True, "5"):
            self.assertEqual(arming.set_global_hourly(value, generation=0, actor=Actor.DASHBOARD)["refusal"],
                             Refusal.INVALID_REQUEST)
        self.assertTrue(arming.set_global_hourly(3, generation=0, actor=Actor.DASHBOARD)["done"])
        self.assertEqual(self.rt.state.meta(), {"generation": 1, "global_hourly": 3})
        self.assertEqual(arming.set_global_hourly(4, generation=0, actor=Actor.DASHBOARD)["refusal"],
                         Refusal.STALE_GENERATION)


if __name__ == "__main__":
    unittest.main()

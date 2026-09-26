"""Turning capabilities on and off: only the Dashboard turns one on, anything turns one off,
shadow never promotes itself, a policy only reads one down, and the tripwires.

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
from codex_auto_resume_advanced.arming import standing  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, OffReason,  # noqa: E402
                                                   Refusal)

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
    def test_every_capability_starts_off(self):
        self.assertEqual(self.rt.arming.current(), {"test_wake": ArmingState.OFF})
        self.assertIsNone(self.stored())

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

    def test_on_needs_permits_at_the_experimental_tier_for_the_acknowledged_version(self):
        cases = (("UNKNOWN", ac.ENGINE, "unknown"), ("COMPATIBLE", "0.154.0", "not_acknowledged_for_this_engine"),
                 ("CHECKED", None, "invalid"))
        for compat, acknowledged, permit in cases:
            with self.subTest(compat=compat, acknowledged=acknowledged):
                self.compat = ac.view(compat)
                result = self.arm(self.rt, acknowledged_version=acknowledged)
                if permit == "invalid":
                    self.assertEqual(result["refusal"], Refusal.INVALID_REQUEST)
                else:
                    self.assertEqual((result["refusal"], result["permit"]), (Refusal.NOT_PERMITTED, permit))
        for compat in ("INCOMPATIBLE", "FAILED_HERE"):
            with self.subTest(compat=compat):
                self.compat = ac.view(compat)
                for state in ("armed", "shadow"):
                    self.assertEqual(self.arm(self.rt, state=state)["refusal"], Refusal.NOT_PERMITTED)
        self.compat = {}
        self.assertEqual(self.arm(self.rt)["permit"], "unknown")
        self.assertIsNone(self.stored())
        with patch("codex_auto_resume_advanced.arming.permits", wraps=__import__(
                "codex_auto_resume.compat", fromlist=["permits"]).permits) as asked:
            self.compat = ac.view("VERIFIED")
            self.assertTrue(self.arm(self.rt)["done"])
        self.assertEqual(asked.call_args.kwargs, {"tier": "experimental", "opt_in": True,
                                                  "engine_version": ac.ENGINE,
                                                  "acknowledged_version": ac.ENGINE})
        self.assertEqual(self.stored()["engine_version"], ac.ENGINE)

    def test_watching_needs_no_acknowledgement_and_stores_none(self):
        self.compat = ac.view("UNKNOWN")
        self.assertTrue(self.arm(self.rt, state="shadow", acknowledged_version=None)["done"])
        self.assertEqual((self.stored()["state"], self.stored()["engine_version"]), ("shadow", None))

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
                         (ArmingState.ARMED, None, None))
        self.assertEqual(standing(ac.definition(), None, policy.NONE, ac.view()),
                         (ArmingState.OFF, None, None))


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

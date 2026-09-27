"""v0.6.11: observe only, delivery receipts, and which conversations and projects may resume.

Observe only runs every gate but consent and sends nothing: the engine refuses on the setting or
the state's switch, and the claim refuses on the switch, so each stops a send the other missed. A
record every other gate passed is parked at the conservative poll and journaled `would_send` once
each time it comes to that, never on every poll it spends there.

Which conversations and projects may resume can only hold an interruption back, when it is
detected: a conversation this state has never seen may get Only notify me as its own tier, and a
project the policy does not allow - or one that cannot be read, under either list policy - is held
for a person (notify_only), never dropped. A project is a key, the digest of Codex's project id or
of its folder, and only the key is ever stored. At the defaults nothing here asks or writes
anything, and the watcher makes the calls to Codex v0.6.10 made (tests/test_defaults_golden.py
holds the defaults, and every scenario below at the defaults sends as before).
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, machine, managed, mcpserver, projects, settings  # noqa: E402
from codex_auto_resume.control.records import receipts  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402
from test_control import KEY, OTHER_KEY, THREAD, ControlTestCase, detection  # noqa: E402
from test_engine import T1, T2, TURN_A, TURN_B, EngineCase  # noqa: E402
from test_mcp import McpTestCase  # noqa: E402

OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000009"


def file_under(h, thread_id, folder=None, project_id=None):
    """The synthetic Codex home files a conversation under a folder, or a project of its own."""
    with h.home._db("state_5.sqlite") as db:
        db.execute("UPDATE threads SET cwd=?, project_id=? WHERE id=?", (folder, project_id, thread_id))


class Spy:
    """A source that counts what is asked of it, and answers with the real one."""

    def __init__(self, real):
        self.real, self.asked = real, []

    def __getattr__(self, name):
        method = getattr(self.real, name)

        def call(*args, **kwargs):
            self.asked.append(name)
            return method(*args, **kwargs)
        return call


# ------------------------------------------------------------------------------ projects.py
class ProjectKeyTests(unittest.TestCase):
    def test_a_key_is_a_digest_and_never_the_folder(self):
        key = projects.key_for(None, r"C:\Users\someone\work\alpha")
        self.assertTrue(projects.is_key(key))
        self.assertNotIn("alpha", key)

    def test_one_folder_is_one_project_however_windows_writes_it(self):
        key = projects.key_for(None, r"C:\Work\Alpha")
        for spelling in (r"c:\work\alpha", "C:/Work/Alpha/", "\\\\?\\C:\\Work\\Alpha", r"C:\Work\Alpha\\"):
            with self.subTest(spelling):
                self.assertEqual(projects.key_for(None, spelling), key)
        self.assertNotEqual(projects.key_for(None, r"C:\Work\Beta"), key)

    def test_codex_project_id_comes_first_and_is_never_a_folder(self):
        by_id = projects.key_for("proj-1", r"C:\work\alpha")
        self.assertEqual(by_id, projects.key_for("proj-1", None))
        self.assertNotEqual(by_id, projects.key_for(None, r"C:\work\alpha"))
        self.assertNotEqual(projects.key_for(None, "proj-1"), by_id, "an id is not read as a folder")

    def test_nothing_to_read_is_no_key(self):
        for project_id, cwd in ((None, None), ("", "  "), (None, "a\nb"), (7, 8)):
            self.assertIsNone(projects.key_for(project_id, cwd))

    def test_a_list_is_keys_in_order_and_nothing_else(self):
        a, b = "a" * 64, "b" * 64
        self.assertEqual(projects.parse_keys(""), ())
        self.assertEqual(projects.parse_keys(a + "," + b), (a, b))
        self.assertEqual(projects.coerce_keys(b + "," + a, ""), "", "not its one written form")
        for bad in ("A" * 64, a + "," + a, "x", a + ",", None, 5, ",".join(["%064x" % n for n in range(51)])):
            with self.subTest(bad=bad):
                self.assertEqual(projects.coerce_keys(bad, ""), "")

    def test_the_policies(self):
        a, b = "a" * 64, "b" * 64
        every = settings.defaults()
        self.assertTrue(projects.allows(every, None), "the default reads nothing and holds nothing")
        self.assertFalse(projects.asks(every))
        only = dict(every, project_policy="only_listed", project_keys_always=a)
        self.assertTrue(projects.allows(only, a))
        self.assertFalse(projects.allows(only, b))
        self.assertFalse(projects.allows(only, None), "a project that cannot be read is held")
        but = dict(every, project_policy="except_listed", project_keys_never=a)
        self.assertFalse(projects.allows(but, a))
        self.assertTrue(projects.allows(but, b))
        self.assertFalse(projects.allows(but, None), "a project that cannot be read is held")
        self.assertEqual(projects.hold_for(but, a), "notify_only")
        self.assertIsNone(projects.hold_for(but, b))

    def test_the_two_lists_are_kept_apart_and_never_turns_the_default_to_every_but_those(self):
        a = "a" * 64
        every = settings.defaults()
        never = projects.rule(every, a, False)
        self.assertEqual(never, {"project_keys_always": "", "project_keys_never": a,
                                 "project_policy": "except_listed"})
        always = projects.rule(dict(every, **never), a, True)
        self.assertEqual(always, {"project_keys_always": a, "project_keys_never": ""})
        self.assertNotIn("project_policy", projects.rule(every, a, True), "Always never widens")
        full = dict(every, project_keys_never=",".join("%064x" % n for n in range(50)))
        with self.assertRaises(ValueError):
            projects.rule(full, "f" * 64, False)
        with self.assertRaises(ValueError):
            projects.rule(every, "not a key", True)

    def test_the_settings_take_them_and_refuse_what_is_not(self):
        a = "a" * 64
        self.assertEqual(settings.validate_update({"project_policy": "only_listed", "project_keys_always": a,
                                                   "new_conversation_policy": "notify_only",
                                                   "observe_only": True})["project_keys_always"], a)
        for bad in ({"project_policy": "some"}, {"new_conversation_policy": "ask_first"},
                    {"project_keys_never": "C:\\work"}, {"observe_only": 1}):
            with self.subTest(bad=bad), self.assertRaises(settings.SettingsError):
                settings.validate_update(bad)
        described = {entry["name"] for entry in settings.describe()}
        self.assertTrue({"observe_only", "new_conversation_policy", "project_policy"} <= described)
        self.assertFalse(settings.ROW_ACTION_FIELDS & described, "no editor draws the lists")


# --------------------------------------------------------------------------- observe only
class ObserveOnlyEngineTests(EngineCase):
    def observe(self, h=None, *, switch=True, setting=False):
        h = h or self.h
        if switch:
            h.store.set_observe_only(True)
        if setting:
            h.engine.apply_policy(dict(settings.defaults(), observe_only=True))

    def test_every_other_gate_is_asked_and_nothing_is_sent(self):
        self.observe()
        self.ready_after_reset()
        self.h.tick()
        self.assert_no_send()
        record = self.h.record()
        gates = machine.decode_gates(record["gate_eval"])
        self.assertEqual(gates["consent"], ("BLOCK", "observe_only"))
        self.assertTrue(all(gates[name][0] == "PASS" for name in machine.GATES if name != "consent"))
        self.assertEqual(machine.would_send_at(record), self.h.now)
        self.assertEqual(record["next_retry_at"], self.h.now + 900, "parked at the conservative poll")
        self.assertEqual((record["attempt_count"], record["submitted_at"], record["state"]),
                         (0, None, "waiting_reset"), "nothing was claimed")
        self.assertIn("would_send", self.h.codes())

    def test_would_send_is_journaled_once_while_it_stays_that_way(self):
        self.observe()
        self.ready_after_reset()
        for _ in range(4):
            self.h.tick(advance=901)
        self.assert_no_send()
        events = self.h.events(self.h.record()["interruption_id"])
        self.assertEqual(events.count("would_send"), 1)
        [event] = [event for event in self.h.store.events(self.h.record()["interruption_id"])
                   if event["code"] == "would_send"]
        self.assertEqual((event["from_state"], event["to_state"], event["reason"]),
                         ("waiting_reset", "waiting_reset", None))

    def test_once_more_only_after_it_had_to_wait_for_something_else(self):
        self.observe()
        self.ready_after_reset()
        self.h.tick()
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick(advance=901)
        self.assertIsNone(machine.would_send_at(self.h.record()))
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        self.assert_no_send()
        self.assertEqual(self.h.events(self.h.record()["interruption_id"]).count("would_send"), 2)

    def test_a_continuation_already_queued_is_taken_back_as_a_pause_takes_it(self):
        """Observe only promises nothing goes to Codex; one left in its queue would be delivered. The
        switch, the setting and an administrator's ForceObserveOnly each take it back, and it goes
        back to waiting with its attempt, as after a Pause (H4) - under words of its own, so nothing
        says recovery was paused when it was not."""
        for how in ("switch", "setting", "key"):
            with self.subTest(how=how):
                h = self.fresh()
                self.send_and_hold(h)
                if how == "key":
                    h.engine.apply_policy(settings.defaults(), managed.Managed(force_observe_only=True))
                else:
                    self.observe(h, switch=how == "switch", setting=how == "setting")
                h.tick(advance=1)
                withdrawn = h.record()
                self.assertEqual((withdrawn["state"], withdrawn["withdraw_reason"]),
                                 ("withdrawn_unconfirmed", "observe_only"))
                self.assertEqual(h.home.queued(T1), [], "nothing of ours is left in Codex's queue")
                h.tick(advance=181)
                row = h.record()
                self.assertIn(row["state"], machine.WAITING)
                self.assertIsNone(row["submitted_at"])
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertIn("release_withdrawn", h.events(row["interruption_id"]))

    def test_one_taken_back_for_it_that_ran_anyway_says_observe_only_not_pause(self):
        """The timeline's words for a continuation Codex started as it was taken back: Observe only
        was on, and recovery was never paused (event.dispatched_while_observing)."""
        h = self.fresh()
        self.send_and_hold(h)
        key = h.record()["interruption_id"]
        self.dispatch_then_report_deleted(h)
        self.observe(h)
        h.tick(advance=1)
        h.tick(advance=1)
        self.assertIn(h.record()["state"], machine.OBSERVING)
        events = h.events(key)
        self.assertIn("dispatched_while_observing", events)
        self.assertNotIn("dispatched_while_paused", events)

    def test_a_pause_as_well_takes_it_back_as_a_pause(self):
        """Paused and only observed at once: the Pause's words, which say the stronger thing."""
        h = self.fresh()
        self.send_and_hold(h)
        self.observe(h)
        h.store.set_enabled(False, h.now)
        h.tick(advance=1)
        self.assertEqual(h.record()["withdraw_reason"], "paused")

    def test_an_uncertain_submission_still_queued_is_taken_back_and_ends_final(self):
        self.unknown_but_queued()
        self.observe()
        self.h.watch(advance=1)
        self.assertEqual(self.h.record()["withdraw_reason"], "observe_only_unknown")
        self.assertEqual(self.h.home.queued(T1), [])

    def test_the_setting_alone_is_enough_for_the_engine(self):
        self.observe(switch=False, setting=True)
        self.ready_after_reset()
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(machine.decode_gates(self.h.record()["gate_eval"])["consent"], ("BLOCK", "observe_only"))

    def test_the_switch_alone_is_enough_for_the_claim(self):
        """The engine that has not heard of it yet still cannot claim: the store refuses."""
        self.ready_after_reset()
        self.h.engine.observing = lambda settings: False
        self.h.store.set_observe_only(True)
        self.h.tick()
        self.assert_no_send()
        record = self.h.record()
        self.assertEqual((record["attempt_count"], record["submitted_at"]), (0, None))
        self.assertEqual(machine.decode_gates(record["gate_eval"])["consent"], ("BLOCK", "observe_only"))

    def test_turned_off_it_sends_as_before(self):
        self.observe()
        self.ready_after_reset()
        self.h.tick()
        self.h.store.set_observe_only(False)
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_pause_a_hold_or_a_cancel_still_ends_it_at_consent(self):
        for setup, reason in ((lambda h: h.store.set_enabled(False, h.now), "paused"),
                              (lambda h: h.store.set_thread_enabled(T1, False), "thread_disabled"),
                              (lambda h: h.store.set_thread_tier(T1, "ask_first", h.now), "held")):
            with self.subTest(reason):
                h = self.fresh()
                self.observe(h)
                self.ready_after_reset(h)
                setup(h)
                h.tick()
                self.assert_no_send(h)
                record = h.record()
                self.assertIsNone(machine.would_send_at(record))
                self.assertNotIn("would_send", h.events(record["interruption_id"]))

    def test_no_objection_window_opens_and_no_plug_is_asked_at_a_gate(self):
        from codex_auto_resume.domain.plug import Point, guard
        from neutral import DeferringPlug
        plug = DeferringPlug()
        self.h.engine.plug = guard(plug)
        self.h.engine.apply_policy(dict(settings.defaults(), default_tier="objection_window"))
        self.observe()
        self.ready_after_reset()
        self.h.tick()
        self.assert_no_send()
        self.assertIsNotNone(machine.would_send_at(self.h.record()))
        self.assertFalse({Point.GATES, Point.SCHEDULE, Point.TEXT, Point.SENDER, Point.CLAIM_LEDGER} & plug.asked,
                         "the plug is asked at a gate only once consent has passed")
        self.assertIsNone(self.h.record()["not_before"], "no objection window")
        self.assertNotIn("objection", [event for event, _ in self.h.notifications])

    def test_several_kinds_of_interruption_all_send_nothing(self):
        for fail in ("usage", "transient"):
            with self.subTest(fail):
                h = self.fresh()
                self.observe(h)
                if fail == "usage":
                    self.ready_after_reset(h)
                else:
                    h.home.fail_transient(T2, TURN_B)
                    h.backend.loaded_map[T2] = "loaded"
                    h.tick()
                for _ in range(6):
                    h.tick(advance=901)
                self.assert_no_send(h)
                self.assertEqual(h.backend.deleted, [], "nothing to take back either")


class ObserveOnlyControlTests(ControlTestCase):
    def test_the_setting_is_written_into_the_state_and_restore_takes_it_away(self):
        self.register()
        self.control.update_settings({"observe_only": True})
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.settings()["observe_only"])
        self.assertTrue(self.control.get_status()["observe_only"])
        self.control.restore_defaults()
        with Store(self.paths.state_dir) as store:
            self.assertFalse(store.settings()["observe_only"])
        self.assertFalse(self.control.get_status()["observe_only"])

    def test_the_status_says_it_from_either_the_switch_or_the_setting(self):
        self.register()
        self.assertFalse(self.control.get_status()["observe_only"])
        with Store(self.paths.state_dir) as store:
            store.set_observe_only(True)
        self.assertTrue(self.control.get_status()["observe_only"])

    def test_a_record_only_observed_says_when_it_would_have_been_sent(self):
        self.register()
        vector = {name: ("PASS", "ok") for name in machine.GATES}
        vector["consent"] = ("BLOCK", "observe_only")
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 100.0)
            self.assertTrue(store.record_would_send(KEY, vector, 200.0, 1100.0))
            self.assertFalse(store.record_would_send(KEY, vector, 300.0, 1200.0), "once")
            with self.assertRaises(StoreError):
                store.set_observe_only("yes")
        [row] = self.control.list_pending()
        self.assertEqual(row["would_send_at"], 300.0)
        codes = [event["code"] for event in self.control.timeline(KEY)["events"]]
        self.assertEqual(codes.count("would_send"), 1)

    def test_nothing_else_says_it_would_have_been_sent(self):
        self.register()
        [row] = self.control.list_pending()
        self.assertIsNone(row["would_send_at"])


# ------------------------------------------------------------------------ delivery receipts
class ReceiptTests(unittest.TestCase):
    def row(self, **values):
        base = {"interruption_id": "a" * 64, "detected_at": 1.0, "state": "waiting_reset",
                "recovery_turn_id": None, "turn_started_at": None, "submitted_at": None,
                "last_claim_at": None, "first_queued_at": None}
        return dict(base, **values)

    def test_each_kind_from_the_records_own_columns(self):
        found = receipts([
            self.row(interruption_id="c" * 64, detected_at=3.0, state="submission_unknown", submitted_at=30.0),
            self.row(interruption_id="a" * 64, state="recovered", recovery_turn_id=TURN_A,
                     turn_started_at=12.0, first_queued_at=11.0),
            self.row(interruption_id="b" * 64, detected_at=2.0, state="queued", first_queued_at=21.0),
            self.row(interruption_id="d" * 64, detected_at=4.0)])
        self.assertEqual(found, [{"interruption_id": "a" * 64, "kind": "seen", "at": 12.0},
                                 {"interruption_id": "b" * 64, "kind": "queued", "at": 21.0},
                                 {"interruption_id": "c" * 64, "kind": "uncertain", "at": 30.0}])

    def test_receipts_carry_no_content(self):
        found = receipts([self.row(state="recovered", recovery_turn_id=TURN_A, turn_started_at=12.0)])
        self.assertEqual(set(found[0]), {"interruption_id", "kind", "at"})


class ReceiptTimelineTests(EngineCase):
    def test_a_recovery_seen_in_its_conversation_says_when(self):
        self.running()
        key = self.h.record()["interruption_id"]
        with tempfile.TemporaryDirectory() as name:
            from codex_auto_resume import config
            paths = config.Paths(Path(name))
            paths.ensure()
            layer = control.Control(paths)
            layer._open = lambda **kwargs: _Borrowed(self.h.store)
            timeline = layer.timeline(key)
        [receipt] = timeline["receipts"]
        self.assertEqual((receipt["kind"], receipt["at"]), ("seen", self.h.record()["turn_started_at"]))


class _Borrowed:
    """The harness's own store, lent to a control layer for one call and not closed by it."""

    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self.store

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------------------ who may resume (engine)
class AdmissionEngineTests(EngineCase):
    def policy(self, h=None, **values):
        (h or self.h).engine.apply_policy(dict(settings.defaults(), **values))

    def test_at_the_defaults_nothing_is_read_written_or_held(self):
        spy = Spy(self.h.source)
        self.h.engine.source = spy
        self.ready_after_reset()
        self.h.tick()
        self.assertNotIn("project_key", spy.asked)
        self.assertIsNone(self.h.record()["hold"])
        self.assertEqual(self.h.store.thread_tiers(), {})
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_conversation_never_seen_gets_only_notify_me_of_its_own(self):
        self.policy(new_conversation_policy="notify_only")
        self.ready_after_reset()
        record = self.h.record()
        self.assertEqual(record["hold"], "notify_only")
        self.assertEqual(self.h.store.thread_tier(T1), "notify_only")
        detected = [detail for event, detail in self.h.notifications if event == "interruption"]
        self.assertEqual(detected[0]["hold"], "notify_only", "it says it waits for you")
        self.h.tick(advance=3600)
        self.assert_no_send()
        self.assertEqual(self.h.store.release_hold(record["interruption_id"], T1, self.h.now)[0], True)
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1, "let continue, it goes")

    def test_a_conversation_already_seen_is_not_new(self):
        self.ready_after_reset()                       # seen once, at the defaults
        self.h.tick()
        self.policy(new_conversation_policy="notify_only")
        self.assertFalse(self.h.store.enrol_conversation(T1, "notify_only", self.h.now))
        self.h.store.set_thread_tier(T2, "automatic", self.h.now)
        self.assertFalse(self.h.store.enrol_conversation(T2, "notify_only", self.h.now),
                         "a person's own choice is never written over")
        self.assertEqual(self.h.store.thread_tier(T2), "automatic")
        self.assertTrue(self.h.store.enrol_conversation("33333333-3333-7333-8333-333333333333",
                                                        "notify_only", self.h.now))

    def test_only_listed_lets_a_listed_project_resume_and_holds_the_rest(self):
        self.h.home.add_thread(T1)
        file_under(self.h, T1, r"C:\work\alpha")
        key = projects.key_for(None, r"C:\work\alpha")
        self.policy(project_policy="only_listed", project_keys_always=key)
        self.ready_after_reset()
        self.assertIsNone(self.h.record()["hold"])
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        h = self.fresh()
        h.home.add_thread(T1)
        file_under(h, T1, r"C:\work\beta")
        self.policy(h, project_policy="only_listed", project_keys_always=key)
        self.ready_after_reset(h)
        self.assertEqual(h.record()["hold"], "notify_only")
        h.tick(advance=3600)
        self.assert_no_send(h)

    def test_except_listed_holds_a_project_set_to_never(self):
        self.h.home.add_thread(T1)
        file_under(self.h, T1, project_id="proj-7")
        self.policy(project_policy="except_listed", project_keys_never=projects.key_for("proj-7"))
        self.ready_after_reset()
        self.assertEqual(self.h.record()["hold"], "notify_only")
        self.h.tick(advance=3600)
        self.assert_no_send()
        self.assertIsNotNone(self.h.record(), "held, never dropped")

    def test_a_project_that_cannot_be_read_is_held_in_either_list_policy(self):
        for policy in ("only_listed", "except_listed"):
            with self.subTest(policy):
                h = self.fresh()
                self.policy(h, project_policy=policy)
                self.ready_after_reset(h)                 # the simulation files it under nothing
                self.assertEqual(h.record()["hold"], "notify_only")
                h.tick(advance=3600)
                self.assert_no_send(h)

    def test_a_tier_that_asks_first_holds_as_it_did(self):
        self.h.store.set_thread_tier(T1, "ask_first", self.h.now)
        self.policy(project_policy="except_listed")
        self.ready_after_reset()
        self.assertEqual(self.h.record()["hold"], "ask", "its own tier first")

    def test_the_state_holds_a_key_and_never_a_folder(self):
        self.h.home.add_thread(T1)
        file_under(self.h, T1, r"C:\Users\someone\secret-project")
        self.policy(project_policy="except_listed")
        self.ready_after_reset()
        raw = (self.root / "state.sqlite").read_bytes()
        self.assertNotIn(b"secret-project", raw)
        self.assertNotIn("secret-project".encode("utf-16-le"), raw)


# ---------------------------------------------------------------- who may resume (control)
class FakeSource:
    def __init__(self, keys):
        self.keys = keys

    def project_key(self, thread_id):
        return self.keys.get(thread_id)


class ProjectRuleControlTests(ControlTestCase):
    def setUp(self):
        super().setUp()
        with Store(self.paths.state_dir) as store:
            store.set_enabled(True, 90.0)
            store.register(detection(), 100.0)
            store.register(detection(key=OTHER_KEY, thread_id=OTHER_THREAD), 100.0)
        self.project = projects.key_for(None, r"C:\work\alpha")

    def test_never_holds_what_its_project_has_waiting_and_nothing_else(self):
        source = FakeSource({THREAD: self.project, OTHER_THREAD: projects.key_for(None, r"C:\b")})
        result = self.control.set_project_rule(KEY, THREAD, False, source=source)
        self.assertEqual(result, {"thread_id": THREAD, "always": False, "project_policy": "except_listed",
                                  "allowed": False, "held": 1})
        values = self.control.get_settings()
        self.assertEqual(values["project_keys_never"], self.project)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["hold"], "notify_only")
            self.assertIsNone(store.get(OTHER_KEY)["hold"])
        text = self.paths.settings_file.read_text(encoding="utf-8")
        self.assertNotIn("alpha", text)

    def test_always_lets_nothing_go_that_is_held(self):
        source = FakeSource({THREAD: self.project})
        self.control.set_project_rule(KEY, THREAD, False, source=source)
        result = self.control.set_project_rule(KEY, THREAD, True, source=source)
        self.assertEqual((result["allowed"], result["held"]), (True, 0))
        self.assertEqual(self.control.get_settings()["project_keys_always"], self.project)
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.get(KEY)["hold"], "notify_only", "only Let it continue lets it go")

    def test_refusals(self):
        for arguments, code in (((KEY, THREAD, False), "project_unreadable"),
                                ((KEY, OTHER_THREAD, False), "thread_mismatch"),
                                (("f" * 64, THREAD, False), "no_such_interruption"),
                                ((KEY, THREAD, "no"), "invalid_enabled")):
            with self.subTest(code), self.assertRaises(control.ControlError) as caught:
                self.control.set_project_rule(*arguments, source=FakeSource({}))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.control.get_settings(), settings.defaults(), "a refusal changes nothing")

    def test_a_full_list_is_refused(self):
        full = ",".join("%064x" % n for n in range(50))
        self.control.update_settings({"project_keys_never": full})
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_project_rule(KEY, THREAD, False, source=FakeSource({THREAD: self.project}))
        self.assertEqual(caught.exception.code, "too_many_projects")

    def test_the_popup_asks_the_same_call_bound_to_its_row(self):
        from codex_auto_resume.ui import popup
        calls = []

        class Layer:
            def set_project_rule(self, *args, **kwargs):
                calls.append((args, kwargs))
                return {}
        source = object()
        self.assertEqual(popup.perform(("project", KEY, THREAD, False), Layer(), source=source), ("ok", {}))
        self.assertEqual(calls, [((KEY, THREAD, False), {"source": source})])
        self.assertEqual(popup.busy_key(("project", KEY, THREAD, True)), ("row", KEY))


class McpSurfaceTests(McpTestCase):
    def test_the_lists_are_not_codex_to_write_but_the_policies_are(self):
        schema = mcpserver.settings_schema()["properties"]
        self.assertTrue({"observe_only", "new_conversation_policy", "project_policy"} <= set(schema))
        self.assertFalse(settings.ROW_ACTION_FIELDS & set(schema))
        reply = self.call("update_settings", {"project_keys_never": "a" * 64})
        self.assertTrue(reply["result"]["isError"])
        self.assertEqual(self.control.get_settings()["project_keys_never"], "")

    def test_observe_only_from_codex_reaches_the_state(self):
        self.register()
        reply = self.call("update_settings", {"observe_only": True})
        self.assertFalse(reply["result"].get("isError"))
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.settings()["observe_only"])


if __name__ == "__main__":
    unittest.main()

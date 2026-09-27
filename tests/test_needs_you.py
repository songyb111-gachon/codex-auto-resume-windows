"""v0.6.11: needs-you notices - a conversation that needs a person, said once.

A failure this product never resumes (terminal_invalid, _policy, _auth, _failure; never
terminal_user) raises one notice, kept in the notices table under the id `detect` would have given
it, and one NEEDS_YOU event through the engine's own announce; a turn that has recorded nothing new
for a chosen time raises one too, read from lifecycle columns and the time of its newest item only.
Neither is ever a record, a claim or a send. The notice's card and toast carry one next step from
the catalog and one button - Open Dashboard, at Settings, where a kind is switched off - so their
actions stay within {cancel URI, open-page URI} (A28). An optional sound is the toast's own audio
element, which Windows' Do not disturb holds back with the toast. Off by default: nothing is read,
kept or raised for a notice until a person turns it on.
"""
from __future__ import annotations

import ast
from contextlib import closing
import inspect
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import failures, needsyou, notifier, notify, settings  # noqa: E402
from codex_auto_resume.codex import history  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.store import Store, StoreError  # noqa: E402
from test_engine import T1, T2, TURN_A, TURN_B, EngineCase  # noqa: E402

CONTEXT_FULL = json.dumps({"codexErrorInfo": "contextWindowExceeded"})
SIGNED_OUT = json.dumps({"codexErrorInfo": "unauthorized"})
ON = dict(settings.defaults(), notify_needs_you=True)


class Asked:
    """A source that writes down each call's name and keywords, and answers with the real one."""

    def __init__(self, real):
        self.real, self.asked = real, []

    def __getattr__(self, name):
        method = getattr(self.real, name)

        def call(*args, **kwargs):
            self.asked.append((name, tuple(sorted(kwargs))))
            return method(*args, **kwargs)
        return call


def notices(h) -> list:
    with closing(sqlite3.connect(h.root / "state.sqlite")) as db:
        return db.execute("SELECT interruption_id, thread_id, category FROM notices ORDER BY raised_at").fetchall()


def needs_you(h) -> list:
    return [detail for event, detail in h.notifications if event == "needs_you"]


# ------------------------------------------------------------------------------ the policy
class PolicyTests(unittest.TestCase):
    def test_at_the_defaults_nothing_is_told(self):
        values = settings.defaults()
        self.assertIs(values["notify_needs_you"], False)
        self.assertEqual(needsyou.kinds(values), frozenset())
        self.assertIsNone(needsyou.stall_seconds(values))
        self.assertFalse(settings.notification_enabled(values, "needs_you"))

    def test_the_kinds_are_four_terminal_ones_and_never_the_persons_own_stop(self):
        self.assertEqual(set(needsyou.KINDS), {"terminal_invalid", "terminal_policy", "terminal_auth",
                                               "terminal_failure"})
        self.assertLessEqual(set(needsyou.KINDS), failures.TERMINAL)
        self.assertNotIn("terminal_user", needsyou.NOTICE_KINDS)
        # Whatever a settings file says, a person's own stop is never told.
        crafted = dict(ON, notify_needs_you_user=True, **{"terminal_user": True})
        self.assertNotIn("terminal_user", needsyou.kinds(settings.coerce(crafted)))
        self.assertNotIn("terminal_user", needsyou.kinds(crafted))

    def test_each_kind_and_the_stall_are_chosen_in_settings(self):
        values = dict(ON, notify_needs_you_policy=False, stall_after="m30")
        self.assertEqual(needsyou.kinds(values), {"terminal_invalid", "terminal_auth", "terminal_failure"})
        self.assertEqual(needsyou.stall_seconds(values), 1800)
        self.assertEqual(needsyou.kinds(dict(values, notifications=False)), frozenset())
        self.assertIsNone(needsyou.stall_seconds(dict(values, notifications=False)))
        self.assertIsNone(needsyou.stall_seconds(dict(values, notify_needs_you=False)))

    def test_every_setting_is_offered_under_notifications_and_refused_when_wrong(self):
        described = {entry["name"]: entry for entry in settings.describe()}
        for name in ("notify_needs_you", "stall_after", "needs_you_sound", *needsyou.KIND_FIELDS.values()):
            with self.subTest(name):
                self.assertEqual(described[name]["group"], "notifications")
                self.assertFalse(described[name].get("master"))
        self.assertEqual(described["stall_after"]["choices"], list(needsyou.STALL_WAITS))
        for bad in ({"stall_after": "m20"}, {"stall_after": 10}, {"needs_you_sound": 1}):
            with self.subTest(bad), self.assertRaises(settings.SettingsError):
                settings.validate_update(bad)

    def test_each_kind_and_its_stall_have_a_next_step_in_the_catalog(self):
        from codex_auto_resume import l10n
        english = l10n.catalog("en")
        for kind in needsyou.NOTICE_KINDS:
            with self.subTest(kind):
                self.assertIn(needsyou.NEXT_STEPS[kind], english)
        self.assertIn("{minutes}", english["msg.needs_you_stalled"])


# ------------------------------------------------------------------------------ the engine
class EngineTests(EngineCase):
    def fail(self, h, thread_id=T1, turn_id=TURN_A, error=CONTEXT_FULL, completed=None):
        h.home.add_turn(thread_id, turn_id, "failed", completed=int(h.now) if completed is None else completed,
                        error_json=error, progress=False)

    def test_at_the_defaults_the_read_is_v0_6_10s_and_nothing_is_kept_or_told(self):
        asked = Asked(self.h.source)
        self.h.engine.source = asked
        self.fail(self.h)
        self.h.tick()
        self.assertIn(("latest_failures", ()), asked.asked, "the same read, with nothing added to it")
        self.assertNotIn("stalled_turns", [name for name, _ in asked.asked])
        self.assertEqual((notices(self.h), needs_you(self.h), self.h.store.all_records()), ([], [], []))

    def test_a_failure_that_needs_a_person_is_told_once_and_never_recorded(self):
        self.h.engine.apply_policy(ON)
        asked = Asked(self.h.source)
        self.h.engine.source = asked
        self.fail(self.h)
        self.h.tick()
        self.h.tick(advance=60)
        key = ids.interruption_id(T1, TURN_A, int(self.h.home.turns(T1)[0]["completed_at"]),
                                  self.h.home.turns(T1)[0]["rollout_ordinal"])
        self.assertIn(("latest_failures", ("needs_you",)), asked.asked, "one read brings both")
        self.assertEqual(notices(self.h), [(key, T1, "terminal_invalid")])
        self.assertEqual(self.h.store.all_records(), [], "never a record: never recovered (A14)")
        self.assertEqual(needs_you(self.h), [{"thread_id": T1, "interruption_id": key,
                                              "category": "terminal_invalid", "reset_at": None}])
        self.assert_no_send()

    def test_a_restarted_watcher_does_not_tell_it_again(self):
        self.h.engine.apply_policy(ON)
        self.fail(self.h)
        self.h.tick()
        told = []
        again = Engine(self.h.store, self.h.source, self.h.backend, clock=lambda: self.h.now,
                       notify=lambda *args: told.append(args), options=self.h.options)
        again.apply_policy(ON)
        again.tick()
        self.assertEqual(len(needs_you(self.h)), 1)
        self.assertEqual(told, [])

    def test_a_kind_switched_off_or_a_conversation_switched_off_is_not_told(self):
        self.h.engine.apply_policy(dict(ON, notify_needs_you_invalid=False))
        self.fail(self.h)
        self.fail(self.h, T2, TURN_B, SIGNED_OUT)
        self.h.store.set_thread_enabled(T2, False)
        self.h.tick()
        self.assertEqual((notices(self.h), needs_you(self.h)), ([], []))
        self.h.store.set_thread_enabled(T2, True)
        self.h.tick()
        self.assertEqual([row[2] for row in notices(self.h)], ["terminal_auth"])

    def test_a_failure_older_than_a_week_is_not_told(self):
        self.h.store.set_enabled(True, self.h.now - 30 * 86400)
        self.h.engine.apply_policy(ON)
        self.fail(self.h, completed=int(self.h.now - 8 * 86400))
        self.h.tick()
        self.assertEqual(notices(self.h), [])

    def test_a_recoverable_failure_is_recovered_as_before_and_never_a_notice(self):
        self.h.engine.apply_policy(ON)
        self.h.home.fail_transient(T1, TURN_A, completed=int(self.h.now))
        self.h.tick()
        self.assertEqual(notices(self.h), [])
        self.assertEqual([row["category"] for row in self.h.store.all_records()], ["server_5xx"])

    def test_paused_recovery_tells_nothing(self):
        self.h.engine.apply_policy(ON)
        self.h.store.set_enabled(False, self.h.now)
        self.fail(self.h)
        self.h.tick()
        self.assertEqual(notices(self.h), [])

    def test_a_notice_that_cannot_be_kept_costs_the_notice_and_nothing_else(self):
        self.h.engine.apply_policy(ON)
        self.h.home.fail_transient(T2, TURN_B, completed=int(self.h.now))
        self.fail(self.h)

        def refuse(*_args):
            raise StoreError("no room")
        self.h.store.raise_notice = refuse
        self.h.tick()
        self.assertEqual([row["thread_id"] for row in self.h.store.all_records()], [T2])
        self.assertIn((None, "needs_you_unavailable", None), self.h.logs)

    # -- a turn that stopped moving ---------------------------------------------------------
    def still(self, h, minutes_ago, thread_id=T1, turn_id=TURN_B):
        h.home.add_turn(thread_id, turn_id, "inProgress", started=int(h.now) - 7200)
        with closing(sqlite3.connect(h.home.root / "thread_history_1.sqlite")) as db, db:
            db.execute("UPDATE thread_items SET created_at_ms=? WHERE turn_id=?",
                       (int((h.now - 60 * minutes_ago) * 1000), turn_id))

    def test_a_turn_that_has_not_moved_is_told_once_with_its_minutes(self):
        self.h.engine.apply_policy(dict(ON, stall_after="m15"))
        self.still(self.h, 20)
        self.h.tick()
        self.h.tick(advance=600)
        key = ids.stalled_id(T1, TURN_B)
        self.assertEqual(notices(self.h), [(key, T1, needsyou.STALLED)])
        self.assertEqual(needs_you(self.h), [{"thread_id": T1, "interruption_id": key,
                                              "category": needsyou.STALLED, "reset_at": None, "minutes": 15}])
        self.assertEqual(self.h.store.all_records(), [])

    def test_a_turn_that_moved_lately_or_the_stall_off_says_nothing(self):
        self.h.engine.apply_policy(dict(ON, stall_after="m30"))
        self.still(self.h, 20)
        self.h.tick()
        self.assertEqual(notices(self.h), [])
        asked = Asked(self.h.source)
        self.h.engine.source = asked
        self.h.engine.apply_policy(ON)
        self.h.tick(advance=3600)
        self.assertNotIn("stalled_turns", [name for name, _ in asked.asked])
        self.assertEqual(notices(self.h), [])


# ------------------------------------------------------------------------------ the reader
class ReaderTests(unittest.TestCase):
    def test_the_stalled_turns_query_reads_no_content(self):
        """Lifecycle columns and the time of the newest item: never item_json or payload_json (B7, B9)."""
        tree = ast.parse(inspect.getsource(history.HistoryMixin.stalled_turns).lstrip())
        text = " ".join(node.value for node in ast.walk(tree)
                        if isinstance(node, ast.Constant) and isinstance(node.value, str))
        self.assertIn("created_at_ms", text)
        for column in ("item_json", "payload_json", "error_json", "title", "preview", "first_user_message"):
            self.assertNotIn(column, text)

    def test_the_failures_a_notice_is_for_never_pass_detect(self):
        row = {"thread_id": T1, "turn_id": TURN_A, "status": "failed", "started_at": 1788627900,
               "completed_at": 1788628000, "rollout_ordinal": 5, "error_json": CONTEXT_FULL}
        needed = history._needing(dict(row), frozenset(needsyou.KINDS))
        self.assertEqual(needed["category"], "terminal_invalid")
        self.assertEqual(needed["interruption_id"], ids.interruption_id(T1, TURN_A, 1788628000, 5))
        from codex_auto_resume.codex import detect
        self.assertIsNone(detect(dict(row)))
        self.assertIsNone(detect(needed))
        self.assertIsNone(history._needing(dict(row), frozenset({"terminal_auth"})))

    def test_a_stall_key_is_never_an_interruptions(self):
        key = ids.stalled_id(T1, TURN_A)
        self.assertTrue(ids.is_interruption_id(key))
        self.assertNotEqual(key, ids.interruption_id(T1, TURN_A, 0, 0))
        self.assertEqual(key, ids.stalled_id(T1, TURN_A))


# ------------------------------------------------------------------------------- the store
class StoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(Path(folder.name) / "state")
        self.addCleanup(self.store.close)

    def test_a_notice_is_kept_once(self):
        key = "ab" * 32
        self.assertTrue(self.store.raise_notice(key, T1, "terminal_policy", 1788628000.0))
        self.assertFalse(self.store.raise_notice(key, T1, "terminal_policy", 1788628100.0))

    def test_only_a_notice_kind_is_kept(self):
        for kind in ("terminal_user", "usage_limit", "unknown", "nonsense"):
            with self.subTest(kind), self.assertRaises(StoreError):
                self.store.raise_notice("cd" * 32, T1, kind, 1788628000.0)
        self.assertTrue(self.store.raise_notice("ef" * 32, T1, needsyou.STALLED, 1788628000.0))

    def test_a_notice_nothing_could_raise_again_is_let_go(self):
        self.store.raise_notice("ab" * 32, T1, "terminal_auth", 1788628000.0)
        later = 1788628000.0 + needsyou.KEEP_SECONDS + 1
        self.store.raise_notice("cd" * 32, T1, "terminal_auth", later)
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual([row[0] for row in db.execute("SELECT interruption_id FROM notices")], ["cd" * 32])
        self.assertGreater(needsyou.KEEP_SECONDS, needsyou.WINDOW_SECONDS)


# ------------------------------------------------------------------------------ the notice
class NoticeTests(unittest.TestCase):
    def setUp(self):
        from codex_auto_resume import l10n
        previous = l10n.preference()
        l10n.set_preference("en")
        self.addCleanup(l10n.set_preference, previous)

    def build(self, kind="terminal_invalid", **detail):
        sound = detail.pop("sound", False)
        return notifier.build("needs_you", dict({"thread_id": T1, "interruption_id": "ab" * 32,
                                                 "category": kind}, **detail),
                              {"name": "example-project"}, sound=sound)

    def test_its_one_button_opens_settings_and_nothing_else(self):
        for kind in needsyou.NOTICE_KINDS:
            notice = self.build(kind, minutes=20)
            with self.subTest(kind):
                self.assertEqual(notice.actions, (("Open Dashboard", notify.open_uri("settings")),))
                for _label, uri in notice.actions:
                    self.assertTrue(notify.parse_open_uri(uri) == "settings"
                                    or notify.parse_cancel_uri(uri) is not None)
                self.assertEqual((notice.kind, notice.status, notice.chip_tone), ("needs_you", "attention", "attention"))

    def test_it_says_the_kind_and_one_next_step_in_three_lines(self):
        notice = self.build("terminal_auth")
        self.assertEqual(notice.chip, "Sign-in needed")
        self.assertEqual(notice.line, "Sign in to Codex again, then ask the conversation to continue.")
        content = notice.toast_content()
        xml = notify._toast_xml(content["title"], content["body"], extra=content["extra"],
                                more=content["more"], sound=content["sound"])
        self.assertEqual(xml.count("<text>"), 3)
        self.assertIn("Sign-in needed · Sign in to Codex again", xml)
        self.assertEqual(self.build(needsyou.STALLED, minutes=20).line,
                         "Nothing new in this turn for 20 minutes. Look at it in Codex.")
        self.assertEqual(self.build(needsyou.STALLED).chip, "Not moving")

    def test_its_line_leaves_the_toast_room_for_the_conversation_id_in_every_language(self):
        """Windows wraps the toast's text in four lines at most under its title, and the last line must
        stay whole: it ends in the exact conversation id (D6). The kind and the next step keep to about
        what the detection toast says in German, the longest of its lines."""
        from codex_auto_resume import l10n
        # Every catalog, the held ones (l10n.HELD) as if offered: offering one later must not bring a
        # line that breaks the toast.
        with patch.object(l10n, "OFFERED", l10n.LOCALES), \
                patch.object(l10n, "CHOICES", (l10n.SYSTEM,) + l10n.LOCALES):
            for locale in l10n.LOCALES:
                l10n.set_preference(locale)
                self.assertEqual(l10n.current(), locale)
                for kind in needsyou.NOTICE_KINDS:
                    with self.subTest(locale=locale, kind=kind):
                        line = self.build(kind, minutes=120).toast_content()["extra"][0]
                        self.assertLessEqual(len(line), 90)
                        self.assertNotIn(chr(10), line)

    def test_the_sound_is_the_toasts_own_and_only_when_chosen(self):
        quiet, loud = self.build().toast_content(), self.build(sound=True).toast_content()
        self.assertIn('<audio silent="true"/>', notify._toast_xml("t", "b", sound=quiet["sound"]))
        self.assertIn('<audio src="%s"/>' % notify.NEEDS_YOU_SOUND, notify._toast_xml("t", "b", sound=loud["sound"]))
        # Every other toast is byte for byte what it was: no audio element of its own.
        self.assertNotIn("<audio", notify._toast_xml("t", "b"))
        self.assertEqual(notify._toast_xml("t", "b", silent=True, sound=True).count("<audio"), 1)

    def test_a_notice_with_a_sound_is_windows_toast_and_never_the_card(self):
        class Inbox:
            attached = True

            def post(self, _notice):
                return True
        shown = []
        allowed = dict.fromkeys(notifier.PROBES)
        allowed.update(notification_state=5, notification_mode=0, app_notifications=0, screen_reader=False,
                       remote_session=False, session_locked=False)
        route = notifier.deliver(self.build(sound=True), inbox=Inbox(), setting=True, probe=lambda: allowed,
                                 show=lambda content: shown.append(content) or True)
        self.assertEqual(route, ("toast", True))
        self.assertIs(shown[0]["sound"], True)
        self.assertEqual(notifier.deliver(self.build(), inbox=Inbox(), setting=True, probe=lambda: allowed,
                                          show=lambda content: True), ("card", True))

    def test_the_watcher_tells_it_only_while_it_is_on(self):
        self.assertFalse(settings.notification_enabled(settings.defaults(), "needs_you"))
        self.assertTrue(settings.notification_enabled(ON, "needs_you"))
        self.assertFalse(settings.notification_enabled(dict(ON, notifications=False), "needs_you"))


if __name__ == "__main__":
    unittest.main()

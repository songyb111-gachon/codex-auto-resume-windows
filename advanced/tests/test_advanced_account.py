"""Switch the Codex account (v0.6.20, plans/v0619-design/D-account.md): the watcher's side.

While account_switch stands on, the watcher reads which account is signed in at its start and every 30 minutes and
keeps only a keyed digest of it - never the address, never the mask - under a salt of its own in Credential Manager;
another account signed in holds every recovery of core's still waiting for a usage limit (core's hold
`account_changed`) and every reset rule still counting, and one notice says how many wait. A plan that changed is the
same account; a read that failed, or found no one signed in, changes nothing. Turned off, the digest and the salt go.

Every read, Credential Manager and core's hold are fakes here - no Codex runs, no real credential is read or written -
but for the last class, which holds a record in a real core store of the test's own.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import config, l10n, notice_kinds, notifier, notify  # noqa: E402
from codex_auto_resume.domain import ids, states  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402
from codex_auto_resume.runtime.app import App  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import account, protocol  # noqa: E402
from codex_auto_resume_advanced.credentials import SecretError  # noqa: E402
from codex_auto_resume_advanced.engine import account as watch  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH, RESET_MESSAGE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, CapabilityKind, Measurement, RuleReason,  # noqa: E402
                                                   RuleState)

CAP = "account_switch"
ONE = {"account": {"type": "chatgpt", "email": "Someone@Example.com", "planType": "plus"}, "requiresOpenaiAuth": True}
ONE_PRO = {"account": {"type": "chatgpt", "email": "someone@example.com", "planType": "pro"}}
OTHER = {"account": {"type": "chatgpt", "email": "another.person@example.org", "planType": "plus"}}
SIGNED_OUT = {"account": None, "requiresOpenaiAuth": True}
T1 = "0a1b2c3d-0001-7000-8000-000000000001"
T2 = "0a1b2c3d-0001-7000-8000-000000000002"


class Secrets:
    """Credential Manager as credentials.Secrets is used: a dict, and what was asked of it."""

    def __init__(self):
        self.kept, self.asked = {}, []

    def read(self, capability, name):
        self.asked.append(("read", capability, name))
        return self.kept.get((capability, name))

    def write(self, capability, name, secret):
        self.asked.append(("write", capability, name))
        self.kept[(capability, name)] = secret

    def delete(self, capability, name):
        self.asked.append(("delete", capability, name))
        return self.kept.pop((capability, name), None) is not None


class View:
    """What core shows a plug at P8, as far as this capability reads it: the records in some states."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    def records_in(self, wanted):
        return [row for row in self.rows if row["state"] in wanted]


def row(key, category="usage_limit", state="waiting_reset"):
    return {"interruption_id": key, "category": category, "state": state}


class DefinitionTests(unittest.TestCase):
    def test_a_route_at_p8_resting_on_ma_and_mal_shown_among_the_expert_settings(self):
        self.assertEqual((ACCOUNT_SWITCH.kind, ACCOUNT_SWITCH.points, ACCOUNT_SWITCH.compat),
                         (CapabilityKind.ROUTE, frozenset({Point.TICK}), "usage_probe"))
        self.assertEqual(ACCOUNT_SWITCH.measurements, (Measurement.MA, Measurement.MAL))
        for standard in ("B4", "B10", "B11", "D2", "F6"):
            self.assertIn(standard, ACCOUNT_SWITCH.departs_from)
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index(CAP) - 1:order.index(CAP) + 2],
                         ("idle_update_check", CAP, "structured_rules"))
        self.assertEqual(statement.CATALOGS.missing(ACCOUNT_SWITCH), [])

    def test_its_session_may_ask_account_read_and_never_a_sign_in_method(self):
        self.assertEqual(protocol.CAPABILITY_METHODS[CAP], ("account/read",))
        allowed = protocol.methods_for_capability(CAP)
        self.assertEqual(allowed, frozenset({"account/read", "initialize", "initialized"}))
        self.assertEqual(protocol.FORBIDDEN_METHODS, frozenset({
            "account/login/start", "account/login", "account/logout", "account/chatgptAuthTokens/refresh",
            "chatgptAuthTokens/refresh", "attestation/generate", "item/tool/call"}), "unchanged")
        self.assertFalse(allowed & protocol.FORBIDDEN_METHODS)


class ReadingTests(unittest.TestCase):
    """What a reading is made into: words and a digest, the address only in this process."""

    def test_an_account_is_present_with_its_plan_word_and_address(self):
        self.assertEqual(account.parse(ONE), {"present": True, "plan_word": "plus", "email": "Someone@Example.com",
                                              "kind": "chatgpt"})
        self.assertEqual(account.parse({"account": {"type": "chatgpt", "email": "a@b.c", "planType": "Weird"}})
                         ["plan_word"], "other")
        self.assertEqual(account.parse({"account": {"type": "apiKey"}}),
                         {"present": True, "plan_word": None, "email": None, "kind": "apikey"})

    def test_signed_out_is_false_and_anything_else_is_unknown(self):
        self.assertIs(account.parse(SIGNED_OUT)["present"], False)
        for odd in (None, {}, {"error": "x"}, {"account": "someone"}, [], "account"):
            with self.subTest(odd=odd):
                self.assertIsNone(account.parse(odd)["present"])

    def test_a_reading_that_raises_is_unknown_never_signed_out(self):
        class Broken:
            def __enter__(self):
                raise OSError("no codex")

            def __exit__(self, *_):
                return False
        self.assertIsNone(account.read(None, session=Broken())["present"])

    def test_the_mask_shows_two_first_letters_and_the_last_label(self):
        dots = account.HIDDEN
        self.assertEqual(account.mask("someone@example.com"), "s" + dots + "@e" + dots + ".com")
        self.assertEqual(account.mask("a@mail.example.co.uk"), "a" + dots + "@m" + dots + ".uk")
        for odd in (None, "", "no-at", "@example.com", "a@", "a@b@c", "a@.com", 7):
            with self.subTest(odd=odd):
                self.assertIsNone(account.mask(odd))

    def test_the_digest_is_keyed_by_the_salt_and_never_the_address(self):
        salt, other = "11" * 32, "22" * 32
        first = account.digest("someone@example.com", salt)
        self.assertRegex(first, r"\A[0-9a-f]{16}\Z")
        self.assertEqual(first, account.digest("someone@example.com", salt))
        self.assertNotEqual(first, account.digest("someone@example.com", other))
        self.assertNotEqual(first, account.digest("another@example.com", salt))
        self.assertEqual(account.identity(account.parse(ONE)), "someone@example.com", "the address in lower case")
        self.assertEqual(account.identity(account.parse({"account": {"type": "apiKey"}})), "kind:apikey")
        self.assertIsNone(account.identity(account.parse(SIGNED_OUT)))
        self.assertEqual(len(account.new_salt()), 64)


class AccountCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="usage_probe")
        self.rt = self.runtime(ACCOUNT_SWITCH, RESET_MESSAGE)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets()
        self.rt.arming.secrets = self.secrets
        self.reads, self.answer, self.holds = [], ONE, []
        self.view = View([row("a" * 64), row("b" * 64, category="network_transient"),
                          row("c" * 64, state="recovered")])
        self.code = self.rt._code_of(ACCOUNT_SWITCH)
        self.code._read = lambda paths: self.reads.append(paths) or account.parse(self.answer)
        self.code._secrets = self.secrets
        self.code._hold = lambda paths, keys, now: self.holds.append(list(keys)) or len(keys)

    def on(self, capability=CAP, state="armed"):
        definition = self.rt.registry.get(capability)
        result = self.rt.arming.arm(capability, state=state, revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def look(self, after=watch.LOOK_EVERY):
        """Time passes, then one tick, its errand run - what core does with the answer at P8."""
        self.now += after
        answer = self.rt.tick(self.view)
        if answer is not DEFER:
            answer.run(lambda: None)

    def codes(self):
        with self.rt.state._read() as connection:
            return [found[0] for found in connection.execute("SELECT code FROM journal")]

    def file_bytes(self):
        self.rt.state.close()
        return Path(self.rt.state.path).read_bytes()


class OffTests(AccountCase):
    def test_off_the_account_is_never_read(self):
        for _ in range(3):
            self.look()
        self.assertEqual((self.reads, self.holds, self.secrets.asked), ([], [], []))

    def test_watched_it_is_only_journalled_and_nothing_is_read(self):
        self.on(state="shadow")
        self.look()
        self.assertEqual(self.reads, [])


class OnTests(AccountCase):
    def test_the_first_reading_keeps_a_digest_under_a_new_salt_and_holds_nothing(self):
        self.on()
        self.look()
        self.assertEqual(len(self.reads), 1)
        salt = self.secrets.kept[(CAP, "salt")]
        self.assertEqual(len(salt), 64)
        seen = self.rt.state.account_seen()
        self.assertEqual((seen["identity_digest"], seen["plan"]),
                         (account.digest("someone@example.com", salt), "plus"))
        self.assertEqual(self.holds, [])

    def test_it_reads_on_the_first_tick_and_then_at_most_every_thirty_minutes(self):
        self.on()
        self.look(0)
        self.look(watch.LOOK_EVERY - 1)
        self.assertEqual(len(self.reads), 1)
        self.look(1)
        self.assertEqual(len(self.reads), 2)

    def test_the_same_account_again_holds_nothing_and_a_plan_alone_is_the_same_account(self):
        self.on()
        self.look()
        self.look()
        self.answer = ONE_PRO
        self.look()
        self.assertEqual(self.holds, [])
        self.assertEqual(self.rt.state.account_seen()["plan"], "pro")
        self.assertNotIn("account.changed", self.codes())

    def test_another_account_holds_only_the_records_waiting_for_a_usage_limit(self):
        self.on()
        self.look()
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [["a" * 64]])
        salt = self.secrets.kept[(CAP, "salt")]
        self.assertEqual(self.rt.state.account_seen()["identity_digest"],
                         account.digest("another.person@example.org", salt))
        codes = self.codes()
        self.assertEqual((codes.count("account.changed"), codes.count("account.held")), (1, 1))
        notice = surfaces.account_view(self.rt)["account"]["notices"]
        self.assertEqual(notice, [{"key": "account:%d" % int(self.now), "count": 1}])
        self.look()
        self.assertEqual(len(self.holds), 1, "the new account is the one seen now")

    def test_a_failed_read_or_no_one_signed_in_changes_nothing(self):
        self.on()
        self.look()
        before = self.rt.state.account_seen()
        for answer in (None, {"error": 1}, SIGNED_OUT):
            self.answer = answer
            self.look()
        self.assertEqual(self.holds, [])
        self.assertEqual(self.rt.state.account_seen(), before)
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [["a" * 64]], "a sign-in after a sign-out is compared with the account before")

    def test_nothing_waiting_holds_nothing_and_shows_no_notice(self):
        self.view = View([row("b" * 64, category="network_transient")])
        self.on()
        self.look()
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [])
        self.assertEqual(surfaces.account_view(self.rt), {})
        self.assertIn("account.changed", self.codes())

    def test_neither_the_address_nor_its_mask_is_ever_written(self):
        self.on()
        self.look()
        self.answer = OTHER
        self.look()
        written = self.file_bytes().lower()
        for text in ("someone@example.com", "another.person@example.org", "example",
                     account.mask("someone@example.com"), account.mask("another.person@example.org")):
            for encoding in ("utf-8", "utf-16-le"):
                self.assertNotIn(text.lower().encode(encoding), written)
        self.assertNotIn(self.secrets.kept[(CAP, "salt")].encode(), written, "the salt is Credential Manager's")

    def test_credential_manager_not_there_holds_nothing_and_keeps_it_on(self):
        self.on()
        self.look()

        def broken(*_):
            raise SecretError("locked")
        self.secrets.read = broken
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [])
        self.assertEqual(self.rt.states(fresh=True)[CAP], "armed")

    def test_a_salt_that_is_gone_is_a_first_reading_again(self):
        self.on()
        self.look()
        del self.secrets.kept[(CAP, "salt")]
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [])
        self.assertIn((CAP, "salt"), self.secrets.kept)

    def test_turned_off_the_digest_and_the_salt_go_and_turned_on_again_it_starts_afresh(self):
        self.on()
        self.look()
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.look()
        self.assertIsNone(self.rt.state.account_seen())
        self.assertNotIn((CAP, "salt"), self.secrets.kept)
        self.assertIn(("delete", CAP, "salt"), self.secrets.asked)
        self.on()
        self.answer = OTHER
        self.look()
        self.assertEqual(self.holds, [], "what was seen before it was off is not compared with")

    def test_off_with_nothing_kept_credential_manager_is_not_asked(self):
        self.look()
        self.rt.arming.all_off(actor=Actor.DASHBOARD)
        self.look()
        self.assertEqual(self.secrets.asked, [])


class ResetRuleTests(AccountCase):
    """Beside a reset message (capability pairs: COMPOSE): its rule, counting the windows of the account that was
    signed in, is held as over a gap in the count - Go on counting is the person's - and core's records are held."""

    def test_a_counting_rule_is_held_with_what_it_had_left_to_count(self):
        self.on("reset_message")
        self.on()
        rule = self.rt.state.add_reset_rule("reset_message", "codex", 300, 3, thread_id=T1, words="go on",
                                            record_id="d" * 64, at=self.now)
        self.rt.state.save_windows([{"bucket": "codex", "minutes": 300, "open_reset_at": None, "open_full": 0,
                                     "last_closed_at": None, "resets": 5, "hits": 0, "seen_at": self.now,
                                     "misses": 0}])
        self.rt.state.change_rule(rule, base=4, adopted_at=self.now)
        self.look()
        self.answer = OTHER
        self.look()
        held = self.rt.state.reset_rule(rule)
        self.assertEqual((held["state"], held["reason"], held["ordinal"], held["base"]),
                         (RuleState.HELD, RuleReason.COUNT_GAP, 2, None))
        self.assertEqual(self.holds, [["a" * 64]])
        self.assertEqual(surfaces.account_view(self.rt)["account"]["notices"][0]["count"], 2)


class CoreHoldTests(unittest.TestCase):
    """core's own store: only a record still waiting unsent with no hold is held, as `account_changed`."""

    def test_a_waiting_record_is_held_as_the_account_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = config.Paths(Path(folder) / "home")
            paths.ensure()
            keys = []
            with Store(paths.state_dir) as store:
                for thread, turn in ((T1, "0a1b2c3d-0001-7000-8000-0000000000aa"),
                                     (T2, "0a1b2c3d-0001-7000-8000-0000000000bb")):
                    key = ids.interruption_id(thread, turn, ac.NOW, 1)
                    self.assertTrue(store.register(
                        {"thread_id": thread, "turn_id": turn, "completed_at": ac.NOW, "started_at": ac.NOW - 60,
                         "ordinal": 1, "interruption_id": key, "reset_at": None, "limit_type": "unknown",
                         "uncertain": True, "category": "usage_limit"}, ac.NOW, state="waiting_poll",
                        next_retry_at=ac.NOW + 900))
                    keys.append(key)
                store.hold_waiting([keys[1]], "ask", ac.NOW)
            self.assertEqual(watch._hold_core(paths, keys, ac.NOW + 1), 1)
            with Store(paths.state_dir) as store:
                self.assertEqual([store.get(key)["hold"] for key in keys], ["account_changed", "ask"])
                self.assertTrue(all(store.get(key)["state"] in states.WAITING for key in keys))


class NoticeTests(unittest.TestCase):
    def setUp(self):
        held = patch.dict(notice_kinds._registered, clear=True)
        held.start()
        self.addCleanup(held.stop)

    def test_its_notice_is_a_kind_of_its_own_listed_with_the_others(self):
        self.assertIsNone(notice_kinds.kind_of("account_changed"))
        with tempfile.TemporaryDirectory() as folder:
            advanced.create(config.Paths(Path(folder) / "home"))
        kind = notice_kinds.kind_of("account_changed")
        self.assertEqual((kind.id, kind.notices), ("account_changed", ("account_changed",)))
        for locale in l10n.LOCALES:
            with self.subTest(locale=locale):
                self.assertEqual(kind.label(locale), l10n.text("msg.toast_account_changed", locale))

    def test_its_one_button_opens_pending_and_it_says_how_many_wait(self):
        notice = notifier.build("account_changed", {"count": 3})
        self.assertEqual((notice.kind, notice.key), ("account_changed", None))
        self.assertEqual([uri for _label, uri in notice.actions], [notify.open_uri("pending")])
        self.assertIn("3", " ".join(str(value) for value in notice.toast_content().values()))
        self.assertEqual(notifier.STATUS["account_changed"], "paused")

    def test_the_watcher_shows_each_change_once_in_its_life(self):
        class Watcher:
            def __init__(self):
                self.shown = []

            def _watcher_notice(self, event, detail):
                self.shown.append((event, detail))
        watcher = Watcher()
        added = {"account": {"notices": [{"key": "account:1800000000", "count": 2}]}}
        for _tick in range(3):
            App._account_changed(watcher, added)
        self.assertEqual(watcher.shown, [("account_changed", {"count": 2})])
        for said in ({}, {"account": "x"}, DEFER, None):
            App._account_changed(watcher, said)
        self.assertEqual(len(watcher.shown), 1)

    def test_pending_says_why_a_record_held_this_way_waits(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale=locale):
                self.assertTrue(l10n.text("why.account_changed", locale))
        source = (ac.ROOT / "gui" / "DashboardActions.cs").read_text(encoding="utf-8")
        self.assertIn('hold == "account_changed"', source)


if __name__ == "__main__":
    unittest.main()

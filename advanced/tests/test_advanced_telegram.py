"""Remote control over Telegram (telegram_remote, telegram_continue, v0.6.22, plans/v0619-design/D-remote.md;
courier/telegram.py, control/remote.py, courier/channels.pair).

It obeys only the paired chat and ignores every other in silence, reads only the design's commands, never reaches a
conversation, refuses a stale `task N` with "list again", and five wrong codes during a pairing turn it off.

Telegram is a stand-in: no test reaches the network. Credential Manager is a fake, the home a temporary folder.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from test_advanced_courier_channels import BOT_INK, Secrets  # noqa: E402
from codex_auto_resume.control.errors import ControlError  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import remote  # noqa: E402
from codex_auto_resume_advanced.courier import channels, keep, resident, telegram  # noqa: E402
from codex_auto_resume_advanced.courier import __main__ as courier  # noqa: E402
from codex_auto_resume_advanced.engine import remote as engine_remote  # noqa: E402
from codex_auto_resume_advanced.registry import PUSH_NOTICES, TELEGRAM_CONTINUE, TELEGRAM_REMOTE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, OffReason, Refusal, TRIPWIRES  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Point  # noqa: E402

CHAT = 1234567
OTHER = 7654321
KEY = "a" * 64
KEY_2 = "b" * 64
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
# The design's table (D-remote.md): each command and what allows it.
DESIGN = {"/status": "telegram_remote", "/list": "telegram_remote", "/cancel": "telegram_remote",
          "/pause": "telegram_remote", "/continue": "telegram_continue", "/recovery-on": "telegram_continue"}
NEVER = ("/send", "/send_now", "/sendnow", "/chat", "/message", "/prompt", "/steer", "/give_back", "/attempts", "/settings",
         "/set", "/arm", "/disarm", "/on", "/off", "/resume", "/token", "/start", "/help")


class Reply:
    status = 200

    def __init__(self, body):
        self.body = body

    def read(self, limit):
        return self.body[:limit]

    def close(self):
        pass


class Bot:
    """Telegram, as urllib's opener sees it: each getUpdates answers the next batch, and each sendMessage is noted."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.reads, self.answers = [], []

    def open(self, request, timeout=None):
        if request.full_url.endswith("/getMe"):
            return Reply(b'{"ok":true,"result":{"id":1,"is_bot":true,"username":"My_Bot"}}')
        if request.full_url.endswith("/sendMessage"):
            self.answers.append(json.loads(request.data.decode("utf-8")))
            return Reply(b'{"ok":true}')
        self.reads.append(request.full_url)
        batch = self.batches.pop(0) if self.batches else []
        if isinstance(batch, Exception):
            raise batch
        return Reply(json.dumps({"ok": True, "result": batch}).encode())


class Layer:
    """Core's control layer as Telegram's commands use it, noting what it is asked."""

    def __init__(self):
        self.calls = []

    def set_enabled(self, enabled):
        self.calls.append(("set_enabled", enabled))
        return {"enabled": enabled}

    def cancel_interruption(self, key, *, actor="gui"):
        self.calls.append(("cancel", key, actor))
        return {"changed": True}

    def release_hold(self, key, thread, *, actor="gui"):
        self.calls.append(("release", key, thread, actor))
        return {}


def row(key=KEY):
    return {"interruption_id": key, "thread_id": THREAD, "state": "waiting_reset", "category": "usage_limit",
            "reset_at": ac.NOW + 60, "title": "a title that must never be sent", "cwd": "C:/never/sent"}


DOCUMENT = {"watcher": "running", "recovery": "on", "pending": 2}


class TelegramCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.catalogs = statement.CATALOGS
        self.rt = self.runtime(PUSH_NOTICES, TELEGRAM_REMOTE, TELEGRAM_CONTINUE)
        self.rt.arming.catalogs = statement.CATALOGS
        self.secrets = Secrets(telegram_token=BOT_INK, telegram_chat=str(CHAT))
        self.layer = Layer()
        self.rows = [row(), row(KEY_2)]
        for target, value in ((remote, {"pending_rows": lambda layer: list(self.rows),
                                        "status_document": lambda layer, now: dict(DOCUMENT)}),):
            for name, replaced in value.items():
                patcher = patch.object(target, name, replaced)
                patcher.start()
                self.addCleanup(patcher.stop)
        self.update = 100

    def on(self, *capabilities):
        for capability in capabilities:
            self.assertTrue(self.arm(self.rt, capability)["done"], capability)

    def message(self, text, chat=CHAT, age=1):
        self.update += 1
        return {"update_id": self.update, "message": {"chat": {"id": chat}, "text": text, "date": int(self.now - age)}}

    def poller(self, bot):
        return telegram.Poller(self.rt, secrets=self.secrets, opener=bot, layer=self.layer, clock=lambda: self.now,
                               locale="en")

    def said(self, *texts, poller=None, chat=CHAT):
        """Each of `texts` sent by `chat` and read in one go each: what the bot answered, in order."""
        bot = Bot(*[[self.message(text, chat)] for text in texts])
        made = poller or self.poller(bot)
        made._opener = bot
        for _ in texts:
            self.assertEqual(made.once(), 0)
        return [answer["text"] for answer in bot.answers]


class TableTests(unittest.TestCase):
    def test_every_command_is_the_designs(self):
        """Fails when a command is added without the design saying so."""
        self.assertEqual(telegram.COMMANDS, DESIGN)

    def test_nothing_that_would_send_chat_or_change_a_setting_is_a_command(self):
        for word in NEVER:
            self.assertEqual(telegram.parse(word), (None, None), word)
            self.assertEqual(telegram.parse(word + " task 1"), (None, None), word)

    def test_the_two_that_take_a_task_take_only_a_task(self):
        for text, expected in (("/cancel task 2", ("/cancel", "task 2")), ("/cancel 2", ("/cancel", "task 2")),
                               ("/CANCEL TASK 2", ("/cancel", "task 2")), ("/continue task 9999", ("/continue", "task 9999")),
                               ("/status@my_bot", ("/status", None)), ("  /pause  ", ("/pause", None))):
            self.assertEqual(telegram.parse(text), expected, text)
        for text in ("/cancel", "/cancel task", "/cancel task 0", "/cancel task 01", "/cancel 10000", "/cancel task 1 2",
                     "/cancel " + KEY, "/cancel task one", "/cancel ٣", "/status now", "/pause please", "/list 1",
                     "/recovery-on now", "status", "", "   ", None, 5, "/cancel " + "1" * 100):
            self.assertEqual(telegram.parse(text), (None, None), text)


class PairedChatTests(TelegramCase):
    def setUp(self):
        super().setUp()
        self.on("push_notices", "telegram_remote")

    def test_another_chat_is_never_answered_and_nothing_happens(self):
        """Fails with the chat's check reverted: anyone who finds the bot could pause recovery."""
        for text in ("/pause", "/status", "/list", "/cancel task 1", "hello"):
            bot = Bot([self.message(text, OTHER)])
            self.assertEqual(self.poller(bot).once(), 0)
            self.assertEqual(bot.answers, [], text)
        self.assertEqual(self.layer.calls, [])
        self.assertIn("tgram.ignored", [line["code"] for line in self.rt.state.journal(capability="telegram_remote")])

    def test_a_flood_from_strangers_is_journalled_once_an_hour(self):
        """R4 (the security review of 2026-11-06): fails with a line per read - someone sending the bot a message a second
        would push every capability's history out of the journal's 5,000 rows within an hour and a half."""
        poller = self.poller(Bot())
        for _ in range(300):
            poller._opener = Bot([self.message("spam", OTHER)])
            poller.once()
            self.now += 1
        lines = [line["code"] for line in self.rt.state.journal(capability="telegram_remote")]
        self.assertEqual(lines.count("tgram.ignored"), 1)
        self.now += telegram.IGNORED_EVERY
        poller._opener = Bot([self.message("spam", OTHER)])
        poller.once()
        lines = [line["code"] for line in self.rt.state.journal(capability="telegram_remote")]
        self.assertEqual(lines.count("tgram.ignored"), 2)

    def test_a_command_named_for_another_bot_is_passed_over_and_one_for_this_bot_obeyed(self):
        """R5 (the security review of 2026-11-06): fails with the name dropped unread - in a group, /pause@OtherBot, meant
        for another bot, would pause recovery here."""
        for text in ("/pause@OtherBot", "/cancel@OtherBot 1", "/status@my_bot_not"):
            self.assertEqual(self.said(text), [], text)
        self.assertEqual(self.layer.calls, [])
        self.assertEqual(self.said("/pause@my_bot"), ["Recovery is paused."], "its own name, in any case")
        self.assertEqual(self.said("/status@MY_BOT"), ["Watcher running, recovery on, 2 waiting."])

    def test_with_its_name_unread_a_named_command_is_passed_over(self):
        bot = Bot([self.message("/pause@my_bot")])
        real = bot.open
        bot.open = lambda request, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("no")) \
            if request.full_url.endswith("/getMe") else real(request, timeout)
        self.poller(bot).once()
        self.assertEqual((bot.answers, self.layer.calls), ([], []))

    def test_one_message_with_no_chat_or_a_chat_that_is_no_number_is_another_chat(self):
        for update in ({"update_id": 1}, {"update_id": 2, "message": {"text": "/pause", "date": int(self.now)}},
                       {"update_id": 3, "message": {"chat": {"id": str(CHAT)}, "text": "/pause", "date": int(self.now)}},
                       {"update_id": 4, "message": {"chat": CHAT, "text": "/pause", "date": int(self.now)}},
                       {"update_id": 5, "edited_message": {"chat": {"id": CHAT}, "text": "/pause", "date": int(self.now)}},
                       {"update_id": 6, "channel_post": {"chat": {"id": CHAT}, "text": "/pause", "date": int(self.now)}}):
            bot = Bot([update])
            self.poller(bot).once()
            self.assertEqual(bot.answers, [], update)
        self.assertEqual(self.layer.calls, [])

    def test_a_command_older_than_five_minutes_is_not_obeyed(self):
        """Fails with the age check reverted: a /pause sent while this PC was off pauses it hours later."""
        old = self.message("/pause", age=telegram.FRESH + 1)
        bot = Bot([old])
        self.poller(bot).once()
        self.assertEqual((bot.answers, self.layer.calls), ([], []))
        undated = self.message("/pause")
        del undated["message"]["date"]
        bot = Bot([undated])
        self.poller(bot).once()
        self.assertEqual((bot.answers, self.layer.calls), ([], []))
        self.assertEqual(self.said("/pause"), ["Recovery is paused."], "at its age it is")

    def test_a_command_dated_ahead_of_this_pc_s_clock_is_obeyed(self):
        """R1 (the second advanced review of v0.6.23): fails with no room ahead - Telegram's `date` is its own clock, and
        on a PC a second or two behind it every command looked newer than now and was ignored, with no answer."""
        for ahead in (1, 2, 60, telegram.AHEAD):
            with self.subTest(ahead=ahead):
                bot = Bot([self.message("/status", age=-ahead)])
                self.poller(bot).once()
                self.assertEqual(len(bot.answers), 1, "a clock %d s behind Telegram's" % ahead)

    def test_a_command_dated_further_ahead_than_that_is_still_ignored(self):
        bot = Bot([self.message("/pause", age=-(telegram.AHEAD + 1))])
        self.poller(bot).once()
        self.assertEqual((bot.answers, self.layer.calls), ([], []))

    def test_with_no_bot_or_no_chat_kept_nothing_is_asked(self):
        for kept in ({}, {"telegram_token": BOT_INK}, {"telegram_chat": str(CHAT)},
                     {"telegram_token": "not a token", "telegram_chat": str(CHAT)},
                     {"telegram_token": BOT_INK, "telegram_chat": "not a chat"}):
            self.secrets.kept = dict(kept)
            bot = Bot()
            self.assertEqual(self.poller(bot).once(), telegram.IDLE)
            self.assertEqual(bot.reads, [])

    def test_while_a_pairing_is_under_way_it_waits_so_the_pairing_reads_the_bot(self):
        keep.begin_pairing(self.rt.state, "123456", self.now)
        bot = Bot()
        self.assertEqual(self.poller(bot).once(), telegram.IDLE)
        self.assertEqual(bot.reads, [])
        self.now += keep.PAIR_SECONDS + 1
        self.assertEqual(self.poller(bot).once(), 0)
        self.assertEqual(len(bot.reads), 1)


class CommandTests(TelegramCase):
    def setUp(self):
        super().setUp()
        self.on("push_notices", "telegram_remote")

    def test_status_says_closed_words_and_a_count(self):
        self.assertEqual(self.said("/status"), ["Watcher running, recovery on, 2 waiting."])
        self.assertEqual(self.layer.calls, [])

    def test_list_says_task_n_a_state_and_a_time_never_a_name(self):
        """Fails where a row's id, thread, title or path reaches the chat."""
        text = self.said("/list")[0]
        self.assertTrue(text.startswith("task 1: "), text)
        self.assertIn("\ntask 2: ", text)
        for secret in (KEY, KEY_2, THREAD, "a title", "C:/never"):
            self.assertNotIn(secret, text)

    def test_nothing_waits(self):
        self.rows = []
        self.assertEqual(self.said("/list"), ["Nothing waits."])

    def test_pause_is_core_s_pause(self):
        self.assertEqual(self.said("/pause"), ["Recovery is paused."])
        self.assertEqual(self.layer.calls, [("set_enabled", False)])

    def test_cancel_goes_by_the_list_last_sent(self):
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.assertEqual(self.said("/cancel task 2", poller=poller), ["task 2 is cancelled."])
        self.assertEqual(self.layer.calls, [("cancel", KEY_2, "cli")])

    def test_a_list_whose_answer_did_not_arrive_is_not_what_task_n_means(self):
        """R6 (the security review of 2026-11-06): fails with the snapshot moved as the answer is made - after a /list
        whose answer failed, `task 1` would be resolved against a list the person never saw, and another recovery
        cancelled."""
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.rows = [row(KEY_2), row()]
        bot = Bot([self.message("/list")])
        real = bot.open

        def failing(request, timeout=None):
            if request.full_url.endswith("/sendMessage"):
                raise urllib.error.URLError("no way there")
            return real(request, timeout)
        bot.open = failing
        poller._opener = bot
        poller.once()
        self.assertEqual(self.said("/cancel task 1", poller=poller), ["The list has changed. Send /list again."])
        self.assertEqual(self.layer.calls, [])

    def test_cancel_with_no_list_sent_says_list_again(self):
        self.assertEqual(self.said("/cancel task 1"), ["The list has changed. Send /list again."])
        self.assertEqual(self.layer.calls, [])

    def test_a_stale_alias_is_refused_with_list_again_and_nothing_is_cancelled(self):
        """Fails with the snapshot's check reverted: task 1 is now another recovery, and that one would be cancelled."""
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.rows = [row(KEY_2)]
        self.assertEqual(self.said("/cancel task 1", poller=poller), ["The list has changed. Send /list again."])
        self.assertEqual(self.layer.calls, [])
        self.assertIn("tgram.list_again", [line["code"] for line in self.rt.state.journal(capability="telegram_remote")])

    def test_a_place_past_the_list_is_refused_too(self):
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.assertEqual(self.said("/cancel task 3", poller=poller), ["The list has changed. Send /list again."])
        self.assertEqual(self.layer.calls, [])

    def test_anything_else_is_answered_with_what_may_be_sent_and_reaches_nothing(self):
        """Fails if a message's words ever reach a layer call: free text goes nowhere."""
        for text in ("please continue the work", "/send do it", "/chat hello", "x" * 500):
            said = self.said(text)[0]
            self.assertTrue(said.startswith("Commands: "), said)
            self.assertNotIn(text, said)
        self.assertEqual(self.layer.calls, [])
        self.assertEqual(said, "Commands: /status, /list, /cancel, /pause", "the two of telegram_continue are not offered")

    def test_a_failure_says_one_closed_sentence_and_no_detail(self):
        self.layer.set_enabled = lambda enabled: (_ for _ in ()).throw(ControlError("secret detail", code="x"))
        self.assertEqual(self.said("/pause"), ["That could not be done."])

    def test_a_failed_answer_does_not_stop_it_or_repeat_the_command(self):
        """The offset is kept before the command is carried out: at most once."""
        bot = Bot([self.message("/pause")])
        real = bot.open

        def failing(request, timeout=None):
            if request.full_url.endswith("/sendMessage"):
                raise urllib.error.URLError("no way there")
            return real(request, timeout)
        bot.open = failing
        poller = self.poller(bot)
        self.assertEqual(poller.once(), 0)
        self.assertEqual(self.layer.calls, [("set_enabled", False)])
        self.assertTrue(bot.reads[0].endswith("offset=0&limit=%d" % telegram.UPDATES))
        poller.once()
        self.assertIn("offset=%d" % (self.update + 1), bot.reads[1])
        self.assertEqual(self.layer.calls, [("set_enabled", False)], "not again")

    def test_the_offset_survives_a_new_process(self):
        self.said("/status")
        bot = Bot()
        self.poller(bot).once()
        self.assertIn("offset=%d" % (self.update + 1), bot.reads[0])

    def test_turned_off_while_a_read_was_held_open_nothing_it_brought_is_obeyed(self):
        stop = threading.Event()
        stop.set()
        bot = Bot([self.message("/pause")])
        self.assertEqual(self.poller(bot).once(stop), 0)
        self.assertEqual((bot.answers, self.layer.calls), ([], []))

    def test_a_read_asks_for_few_so_no_reply_outgrows_what_is_read(self):
        """Fails with `limit` dropped: a stranger's long messages make a reply past http.MAX_REPLY that never parses, and
        the offset never moves: a bot stuck for good."""
        bot = Bot()
        self.poller(bot).once()
        self.assertIn("&limit=%d" % telegram.UPDATES, bot.reads[0])
        self.assertLess(telegram.UPDATES * 4096 * 6 + 2048, channels.http.MAX_REPLY)

    def test_what_telegram_refuses_waits_longer_than_what_it_did_not_answer(self):
        for error, wait in ((urllib.error.HTTPError("u", 401, "m", {}, None), telegram.AFTER_REFUSAL),
                            (urllib.error.HTTPError("u", 409, "m", {}, None), telegram.AFTER_FAILURE),
                            (urllib.error.HTTPError("u", 500, "m", {}, None), telegram.AFTER_FAILURE),
                            (urllib.error.URLError("no way there"), telegram.AFTER_FAILURE)):
            self.assertEqual(self.poller(Bot(error)).once(), wait, error)

    def test_a_reply_that_is_no_list_of_updates_is_none(self):
        for body in (b"", b"not json", b"[]", b'{"ok":false,"result":[{"update_id":1}]}', b'{"ok":true,"result":5}'):
            self.assertEqual(telegram.updates(body), [], body)
        self.assertEqual(telegram.updates(None), [])

    def test_the_token_is_only_in_the_request_s_path_never_the_state(self):
        self.said("/status", "/list")
        self.said("/pause", chat=OTHER)
        self.rt.state.close()
        for path in Path(self.paths.state_dir).rglob("*"):
            if path.is_file():
                self.assertNotIn(BOT_INK.encode(), path.read_bytes(), path.name)

    def test_every_answer_is_in_every_language(self):
        keys = [key for key in statement.PAGE_KEYS if key.startswith("page.remote.answer.")
                or key.startswith("page.remote.word.")]
        self.assertGreater(len(keys), 10)
        from codex_auto_resume import l10n
        for locale in l10n.LOCALES:
            table = statement.CATALOGS.own(locale)
            with self.subTest(locale):
                self.assertEqual([key for key in keys if not isinstance(table.get(key), str)], [])


class ContinueTests(TelegramCase):
    def setUp(self):
        super().setUp()
        self.on("push_notices", "telegram_remote")

    def test_off_both_are_refused_and_nothing_happens(self):
        """Fails with the capability's check reverted: the second arming would mean nothing."""
        self.assertEqual(self.said("/recovery-on"), ["That command is not turned on."])
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.assertEqual(self.said("/continue task 1", poller=poller), ["That command is not turned on."])
        self.assertEqual(self.layer.calls, [])

    def test_on_continue_is_core_s_release_by_the_list_and_lifting_the_pause_core_s(self):
        self.on("telegram_continue")
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        said = self.said("/continue task 2", poller=poller)
        self.assertEqual(said, ["task 2 goes on. Nothing is sent until every check passes."])
        self.assertEqual(self.layer.calls, [("release", KEY_2, THREAD, "cli")])
        self.assertEqual(self.said("/recovery-on"), ["Recovery is on again."])
        self.assertEqual(self.layer.calls[-1], ("set_enabled", True))
        self.assertTrue(self.said("hello")[0].endswith("/continue, /recovery-on"))

    def test_continue_goes_stale_as_cancel_does(self):
        self.on("telegram_continue")
        poller = self.poller(Bot())
        self.said("/list", poller=poller)
        self.rows = [row(KEY_2)]
        self.assertEqual(self.said("/continue task 1", poller=poller), ["The list has changed. Send /list again."])
        self.assertEqual(self.layer.calls, [])

    def test_a_policy_that_holds_the_pause_still_holds_it(self):
        self.on("telegram_continue")

        def refuse(enabled):
            raise ControlError("recovery is paused by your administrator", code="managed_by_policy")
        self.layer.set_enabled = refuse
        self.assertEqual(self.said("/recovery-on"), ["That could not be done."])


class ArmingTests(TelegramCase):
    def also(self, *capabilities):
        return [{"capability": capability, "revision": 1, "warnings": [], "engine_version": ac.ENGINE}
                for capability in capabilities]

    def test_all_are_off_until_a_person_turns_them_on(self):
        states = self.rt.states(fresh=True)
        for capability in ("telegram_remote", "telegram_continue"):
            self.assertEqual(states.get(capability, ArmingState.OFF), ArmingState.OFF)

    def test_the_second_and_third_arming_go_through_requires(self):
        """Fails with `requires` dropped: Telegram could be on with no notices, and /continue with no Telegram."""
        for capability in ("telegram_remote", "telegram_continue"):
            self.assertEqual(self.arm(self.rt, capability)["refusal"], Refusal.REQUIREMENT_REFUSED)
        self.assertEqual(self.rt.registry.requires("telegram_continue"), ("push_notices", "telegram_remote"))
        self.assertTrue(self.arm(self.rt, "telegram_continue", also=self.also("push_notices", "telegram_remote"))["done"])
        states = self.rt.states(fresh=True)
        self.assertEqual([states[name] for name in ("push_notices", "telegram_remote", "telegram_continue")],
                         [ArmingState.ARMED] * 3)

    def test_turning_one_off_turns_off_what_requires_it(self):
        self.assertTrue(self.arm(self.rt, "telegram_continue", also=self.also("push_notices", "telegram_remote"))["done"])
        self.rt.arming.disarm("push_notices", actor="dashboard")
        states = self.rt.states(fresh=True)
        for capability in ("telegram_remote", "telegram_continue"):
            self.assertEqual(states.get(capability, ArmingState.OFF), ArmingState.OFF, capability)

    def test_the_last_off_leaves_the_others(self):
        self.assertTrue(self.arm(self.rt, "telegram_continue", also=self.also("push_notices", "telegram_remote"))["done"])
        self.rt.arming.disarm("telegram_continue", actor="dashboard")
        self.assertEqual(self.rt.states(fresh=True)["telegram_remote"], ArmingState.ARMED)

    def test_each_says_the_standards_it_departs_from(self):
        self.assertEqual(TELEGRAM_REMOTE.departs_from, ("C1", "C2", "C3", "C8", "D1", "F6", "F8"))
        self.assertEqual(TELEGRAM_CONTINUE.departs_from, ("H4",))


class PairingTests(TelegramCase):
    def pairing_run(self, *batches):
        keep.begin_pairing(self.rt.state, "123456", self.now)
        clock = itertools.count(0, 5)

        def now():
            return self.now + next(clock)
        return channels.pair(self.rt, self.secrets, opener=Bot(*batches), clock=now, sleep=lambda seconds: None)

    def wrong(self, how_many):
        return [{"update_id": number, "message": {"chat": {"id": OTHER}, "text": "%06d" % number}}
                for number in range(how_many)]

    def test_five_wrong_codes_turn_it_off_and_what_requires_it(self):
        """Fails with the tripwire reverted: someone guessing at the chat it obeys would go on guessing at no cost."""
        self.on("push_notices", "telegram_remote", "telegram_continue")
        self.assertEqual(self.pairing_run(self.wrong(5)), courier.EXIT_NOT_PAIRED)
        row_ = self.rt.state.arming()["telegram_remote"]
        self.assertEqual((row_["state"], row_["reason"]), (ArmingState.OFF, OffReason.BAD_CODES))
        states = self.rt.states(fresh=True)
        self.assertEqual(states.get("telegram_continue", ArmingState.OFF), ArmingState.OFF)
        self.assertEqual(states["push_notices"], ArmingState.ARMED, "the notices are not what was guessed at")

    def test_four_do_not(self):
        self.on("push_notices", "telegram_remote")
        self.pairing_run(self.wrong(4))
        self.assertEqual(self.rt.states(fresh=True)["telegram_remote"], ArmingState.ARMED)

    def test_keep_on_does_not_hold_it_back(self):
        self.on("push_notices")
        self.assertTrue(self.arm(self.rt, "telegram_remote", keep_on=True)["done"])
        self.pairing_run(self.wrong(5))
        self.assertEqual(self.rt.state.arming()["telegram_remote"]["state"], ArmingState.OFF)

    def test_off_there_is_nothing_to_trip_and_the_notices_pairing_ends_as_ever(self):
        self.on("push_notices")
        self.assertEqual(self.pairing_run(self.wrong(5)), courier.EXIT_NOT_PAIRED)
        self.assertIsNone((self.rt.state.arming().get("telegram_remote") or {}).get("reason"))

    def test_it_is_a_tripwire_and_says_so_in_every_language(self):
        self.assertIn(OffReason.BAD_CODES, TRIPWIRES)
        self.assertIn("page.tripped.bad_codes", statement.PAGE_KEYS)

    def test_a_409_is_the_long_poll_still_open_and_the_pairing_goes_on(self):
        """Fails with 409 taken as a refusal: pairing while it stands on would fail for up to fifty seconds' worth of reads."""
        self.on("push_notices", "telegram_remote")
        conflict = urllib.error.HTTPError("u", 409, "m", {}, None)
        right = [{"update_id": 5, "message": {"chat": {"id": CHAT}, "text": "123456"}}]
        self.assertEqual(self.pairing_run(conflict, right), courier.EXIT_DONE)
        self.assertEqual(self.secrets.kept["telegram_chat"], str(CHAT))

    def test_a_401_still_ends_it(self):
        self.on("push_notices")
        self.assertEqual(self.pairing_run(urllib.error.HTTPError("u", 401, "m", {}, None)), courier.EXIT_REFUSED)


class ResidentTests(TelegramCase):
    def poller_stub(self, runtime, stop):
        self.polled.set()
        stop.wait(30)
        self.ended.set()

    def setUp(self):
        super().setUp()
        self.polled, self.ended = threading.Event(), threading.Event()

    def test_off_there_is_no_thread_and_the_process_ends(self):
        before = threading.active_count()
        self.assertEqual(resident.serve(self.rt, poller=self.poller_stub, sleep=self.fail), courier.EXIT_DONE)
        self.assertFalse(self.polled.is_set())
        self.assertEqual(threading.active_count(), before)

    def test_watched_there_is_no_thread_either(self):
        self.on("push_notices")
        self.assertTrue(self.arm(self.rt, "telegram_remote", state="shadow")["done"])
        self.assertEqual(resident.serve(self.rt, poller=self.poller_stub, sleep=self.fail), courier.EXIT_DONE)
        self.assertFalse(self.polled.is_set())

    def test_on_it_reads_and_turned_off_it_stops(self):
        self.on("push_notices", "telegram_remote")
        roles = resident.Roles(self.rt, poller=self.poller_stub)
        self.addCleanup(roles.close)
        self.assertTrue(roles.follow())
        self.assertTrue(self.polled.wait(10))
        self.assertTrue(roles.follow())
        self.rt.arming.disarm("telegram_remote", actor="dashboard")
        self.assertFalse(roles.follow())
        self.assertTrue(self.ended.wait(10))
        lines = [line["code"] for line in self.rt.state.journal(capability="telegram_remote")]
        self.assertLess(lines.index("tgram.started"), lines.index("tgram.stopped"))

    def test_one_that_died_is_started_again_at_the_next_look(self):
        self.on("push_notices", "telegram_remote")
        ran = []
        roles = resident.Roles(self.rt, poller=lambda runtime, stop: ran.append(1))
        self.addCleanup(roles.close)
        roles.follow()
        roles.thread.join(5)
        roles.follow()
        roles.thread.join(5)
        self.assertEqual(len(ran), 2)

    def test_run_ends_when_it_is_told_and_survives_a_failure(self):
        stop = threading.Event()
        calls = []

        class Stand:
            def __init__(self, runtime, **seams):
                pass

            def once(self, stop_):
                calls.append(1)
                stop.set()
                raise RuntimeError("no")
        with patch.object(telegram, "Poller", Stand):
            telegram.run(self.rt, stop)
        self.assertEqual(calls, [1])

    def test_both_capabilities_share_one_resident_and_one_cap(self):
        """Fails with a cap of each its own: both on, a dying resident would be started twice as often."""
        self.on("push_notices", "telegram_remote")
        self.assertEqual(engine_remote.RESIDENT, ("local_api", "telegram_remote"))
        starts = []
        code = self.rt._code_of(self.rt.registry.get("telegram_remote"))
        code._running = lambda paths: False
        code._launch = lambda paths: starts.append(1) or True
        for _ in range(8):
            answer = self.rt.tick({})
            if hasattr(answer, "run"):
                answer.run(None)
            self.now += engine_remote.STARTING
        self.assertEqual(len(starts), 1 + engine_remote.RESTARTS)
        said = remote.pair_state(self.rt, secrets=self.secrets, running=lambda runtime: False)
        self.assertEqual(said["state"], "stopped")


class CardTests(TelegramCase):
    def test_the_card_says_what_is_kept_and_never_a_secret(self):
        self.on("push_notices", "telegram_remote")
        said = remote.pair_state(self.rt, secrets=self.secrets, running=lambda runtime: True)
        self.assertEqual({key: said[key] for key in ("done", "paired", "token_saved", "pairing", "state", "continue")},
                         {"done": True, "paired": True, "token_saved": True, "pairing": False, "state": "running",
                          "continue": False})
        self.assertNotIn(BOT_INK, json.dumps(said))
        self.assertNotIn(str(CHAT), json.dumps(said))

    def test_a_pairing_needs_both_standing_and_keeps_only_a_digest(self):
        self.assertEqual(remote.pair_start(self.rt, secrets=self.secrets)["refusal"], Refusal.NOT_ON)
        self.on("push_notices")
        self.assertEqual(remote.pair_start(self.rt, secrets=self.secrets)["refusal"], Refusal.NOT_ON)
        self.on("telegram_remote")
        started = []
        found = remote.pair_start(self.rt, secrets=self.secrets, start=lambda paths, *extra: started.append(extra) or True)
        self.assertTrue(found["done"])
        self.assertRegex(found["code"], r"\A[0-9]{6}\Z")
        self.assertEqual(started, [("--pair",)])
        row_ = keep.pairing(self.rt.state)
        self.assertEqual(row_["code_digest"], keep.digest(found["code"]))
        self.assertNotIn(found["code"], json.dumps(row_))

    def test_no_mcp_tool_reaches_a_pairing_or_a_command(self):
        names = {tool["name"] for tool in surfaces.TOOLS}
        for word in ("telegram", "pair", "remote"):
            self.assertEqual([name for name in names if word in name], [], word)

    def test_the_bridge_answers_both_and_no_more_is_passed_over_than_the_other_pcs(self):
        # The other PCs' two are answered too since fleet_view joined (v0.6.22 beta.2): nothing is passed over.
        self.assertEqual(sorted(str(command) for command in surfaces.UNANSWERED), [])


class PausedTests(TelegramCase):
    """R3, as the owner decided on 2026-11-06 ("기다리게 해"): while recovery is paused core asks P22, and only of the residents
    that declare they send nothing to Codex - so Telegram keeps waiting for commands after a watcher restart too."""

    def setUp(self):
        super().setUp()
        self.on("push_notices", "telegram_remote", "telegram_continue")
        from codex_auto_resume import control as core_control
        self.paths.ensure()
        self.control = core_control.Control(self.paths)
        self.control.set_enabled(False)

    def restarted(self, *definitions):
        """A watcher that started again: a runtime of its own, its resident's mutex free, its starts noted."""
        made = self.runtime(*(definitions or (PUSH_NOTICES, TELEGRAM_REMOTE, TELEGRAM_CONTINUE)))
        made.arming.catalogs = statement.CATALOGS
        self.started = []
        for definition in made.registry.at(Point.RESIDENT):
            code = made._code_of(definition)
            code._running = lambda paths: False
            code._launch = lambda paths: self.started.append(paths) or True
        return made

    def test_after_a_restart_while_paused_the_poller_is_started_and_recovery_on_lifts_the_pause(self):
        """Fails with P22 reverse-applied: the new watcher asks nothing while paused, no resident starts, and the pause
        made from the phone can only be lifted at the PC."""
        made = self.restarted()
        answer = made.resident({})
        self.assertTrue(callable(getattr(answer, "run", None)))
        answer.run(None)
        self.assertEqual(len(self.started), 1, "one resident for both")
        poller = telegram.Poller(made, secrets=self.secrets, opener=Bot(), layer=self.control, clock=lambda: self.now,
                                 locale="en")
        self.assertEqual(self.said("/recovery-on", poller=poller), ["Recovery is on again."])
        with self.control._open() as store:
            self.assertTrue(store.settings()["enabled"])

    def test_the_edition_s_plug_answers_p22_and_wants_it_while_a_resident_stands_on(self):
        """Through the plug core holds (Guarded over AdvancedPlug): fails where the plug leaves P22 to NULL's answer."""
        from codex_auto_resume.domain.plug import guard
        made = self.plug(PUSH_NOTICES, TELEGRAM_REMOTE, TELEGRAM_CONTINUE)
        self.started = []
        code = made.runtime._code_of(made.runtime.registry.get("telegram_remote"))
        code._running = lambda paths: False
        code._launch = lambda paths: self.started.append(paths) or True
        held = guard(made)
        self.assertTrue(held.wants(Point.RESIDENT))
        answer = held.resident({})
        self.assertTrue(callable(getattr(answer, "run", None)))
        answer.run(lambda: None)
        self.assertEqual(len(self.started), 1)

    def test_while_paused_no_other_capability_s_errand_runs(self):
        """Only what answers at P22 is asked: a capability that sends - or any that only answers at P8 - is not."""
        sends = ac.definition(points=frozenset({Point.TICK, Point.GATES}))
        made = self.restarted(PUSH_NOTICES, TELEGRAM_REMOTE, TELEGRAM_CONTINUE, sends)
        made.arming.catalogs = ac.catalogs(Path(self.home).parent / "with-sends", sends)
        warned = [str(word) for word in made.arming.warnings(sends)]
        self.assertTrue(self.arm(made, "test_wake", warnings=warned)["done"])
        asked = []
        ac.code_of(made).answers["tick"] = lambda view: asked.append("tick") or Errand()
        ac.code_of(made).answers["resident"] = lambda view: asked.append("resident") or Errand()
        answer = made.resident({})
        self.assertEqual([definition.id for definition, _errand in answer.errands], ["telegram_remote"])
        self.assertEqual(asked, [])

    def test_a_resident_that_does_not_declare_is_refused_and_one_that_declares_little_else(self):
        """A capability answering at P22 says it sends nothing: the registry refuses one that also answers where core
        decides or sends."""
        from codex_auto_resume_advanced.registry import problems
        self.assertIn("a resident answers at P8 and P22 alone: it sends nothing to Codex",
                      problems(ac.definition(points=frozenset({Point.RESIDENT, Point.SENDER}))))
        self.assertEqual(problems(ac.definition(points=frozenset({Point.RESIDENT, Point.TICK}))), [])

    def test_watched_it_is_journalled_and_nothing_starts(self):
        self.rt.arming.disarm("telegram_remote", actor="dashboard")
        self.on("telegram_remote")
        self.rt.arming.disarm("telegram_remote", actor="dashboard")
        self.assertTrue(self.arm(self.rt, "telegram_remote", state="shadow")["done"])
        made = self.restarted()
        self.assertIs(made.resident({}), DEFER)
        self.assertEqual(self.started, [])

    def test_off_nothing_is_asked(self):
        self.rt.arming.disarm("push_notices", actor="dashboard")
        made = self.restarted()
        self.assertIs(made.resident({}), DEFER)
        self.assertEqual(self.started, [])


class Errand:
    def run(self, guard):
        return None


if __name__ == "__main__":
    unittest.main()

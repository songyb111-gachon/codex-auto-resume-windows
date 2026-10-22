"""A record born stopped although nothing gave up is said as that, never as "stopped trying".

The owner's case (2026-10-22, plans/notif-check.md rank 1): our continuation was delivered and worked; a
message the person had queued in the Codex app then entered that turn, so the person took the conversation
over; the next usage limit's record was born `superseded (parent_handed_over)` - rightly, nothing is sent on
top of the person's work - and was announced with the words of a recovery that ran out of retries
("재시도를 중단했습니다 / 이 작업의 자동 복구를 중단했습니다"). A record born `cancelled (parent_cancelled)` was
said the same way. Both now say why nothing will be sent, under the new failure's reason; the retry budgets'
stops keep their words.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from test_outcomes import SERVER_5XX, World  # noqa: E402

from codex_auto_resume import l10n, notifier, notify, reasons  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
IDENTITY = {"name": "ExampleUser's task"}
WORDS = {
    "parent_handed_over": {"ko": "직접 이어가고 계신 대화라 자동으로 재개하지 않습니다.",
                           "en": "You are continuing this conversation yourself, so it will not be resumed "
                                 "automatically."},
    "parent_cancelled": {"ko": "자동 복구를 취소한 작업이라 자동으로 재개하지 않습니다.",
                         "en": "Automatic recovery was cancelled for this task, so it will not be resumed "
                               "automatically."},
}
BORN = {"parent_handed_over": "superseded", "parent_cancelled": "cancelled"}


class Language(unittest.TestCase):
    def speak(self, locale):
        before = l10n.preference()
        l10n.set_preference(locale)
        self.addCleanup(l10n.set_preference, before)

    @staticmethod
    def stopped(state, reason, category="usage_limit"):
        return notifier.build("stopped", {"thread_id": THREAD, "interruption_id": "ab" * 32, "state": state,
                                          "reason": reason, "category": category}, IDENTITY)


class NotResumedWordsTests(Language):
    def test_a_child_of_a_conversation_the_person_took_over_says_so(self):
        for locale in ("ko", "en"):
            for reason, state in BORN.items():
                with self.subTest(locale=locale, reason=reason):
                    self.speak(locale)
                    notice = self.stopped(state, reason)
                    content = dict(notice.content)
                    label = l10n.text(reasons.label_key("usage_limit"), locale)
                    self.assertEqual(notice.kind, "stopped", "the notify_stopped switch still governs it")
                    self.assertEqual(content["title"], IDENTITY["name"])
                    self.assertEqual(list(content["extra"]), [label + " · " + WORDS[reason][locale]])
                    self.assertEqual((notice.chip, notice.line), (label, WORDS[reason][locale]))
                    said = " ".join([content["title"], content["body"]] + list(content["extra"]))
                    for stop in ("toast_exhausted_title", "toast_stopped_body"):
                        self.assertNotIn(l10n.message(stop), said)
                    self.assertNotIn("button", content, "no button, as the stop's notice")

    def test_its_reason_is_the_new_failure_s(self):
        self.speak("en")
        notice = self.stopped("superseded", "parent_handed_over", category="server_5xx")
        self.assertEqual(notice.chip, l10n.text(reasons.label_key("server_5xx"), "en"))

    def test_a_retry_budget_s_stop_keeps_its_words(self):
        self.speak("ko")
        cases = {("retry_budget_exhausted", "chain_cap"): "toast_exhausted_body",
                 ("retry_budget_exhausted", "recovery_budget"): "toast_exhausted_body",
                 ("retry_budget_exhausted", "chain_time_cap"): "toast_time_cap_body",
                 ("no_progress_exhausted", "no_progress_budget"): "toast_no_progress_body",
                 ("terminal_failure", "terminal"): "toast_stopped_body"}
        for (state, reason), body in cases.items():
            with self.subTest(state=state, reason=reason):
                content = dict(self.stopped(state, reason).content)
                self.assertEqual(content["title"], "재시도를 중단했습니다")
                self.assertEqual(list(content["extra"]), [l10n.message(body)])

    def test_every_language_has_both_sentences(self):
        for key in notify.NOT_RESUMED.values():
            for locale in l10n.LOCALES:
                with self.subTest(key=key, locale=locale):
                    self.assertTrue(l10n.text("msg." + key, locale).strip())
                    if locale != "en":
                        self.assertNotEqual(l10n.text("msg." + key, locale), l10n.text("msg." + key, "en"))


class BornStoppedEndToEndTests(Language):
    """Through the real Engine: a person's message in our recovery turn, then that turn fails."""

    def test_the_child_of_a_handed_over_turn_is_announced_with_the_hand_over_words(self):
        self.speak("ko")
        w = World(self)
        w.enable()
        thread, key = w.queued()
        turn = w.home.dispatch(thread, status="inProgress", progress=False)
        w.home.add_item(thread, turn, "userMessage", "typed while it ran")
        w.tick(1)
        self.assertTrue(w.get(key)["user_joined"])
        w.finish(thread, turn, "failed", SERVER_5XX)
        w.tick(1)
        child = w.records(thread)[-1]
        self.assertEqual((child["state"], child["last_error"]), ("superseded", "parent_handed_over"))
        said = [detail for event, detail in w.notes if event == "stopped"
                and detail.get("interruption_id") == child["interruption_id"]]
        self.assertEqual(len(said), 1)
        content = dict(notifier.build("stopped", said[0], IDENTITY).content)
        self.assertEqual(list(content["extra"]), [l10n.text(reasons.label_key(child["category"]), "ko") + " · "
                                            + WORDS["parent_handed_over"]["ko"]])
        self.assertEqual(w.sends(thread), 1, "and nothing is sent on top of the person's work")


if __name__ == "__main__":
    unittest.main()

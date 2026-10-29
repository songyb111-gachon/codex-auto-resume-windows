"""v0.6.20 (the owner, 2026-10-28): Open Codex on a notice is not a button - the notice itself opens Codex.

A white button under a notice's text looked out of place, so where an edition asks that a notice about one
conversation open Codex (the advanced edition's capability; notifier.with_open_codex) the card's face and the toast's
body go to the conversation's Codex link, and the buttons are exactly what they were:

* a resumed notice has no button, and its card's face - the view's `click` - is the Codex link; its toast has no Open
  Codex action and launches the link (`CardTests`, `ToastTests`);
* a notice with Open Dashboard still has that button and Cancel its own, and its face opens Codex (`ButtonsStayTests`);
* where the in-app chat is on and its setting chose the chat or Codex, that choice is the click (`ChoiceTests`);
* a notice about no conversation, and an edition that does not ask, are exactly as before (`ElseTests`);
* the click is opened by the same `activate` that read the link when it was a button (`OpenTests`).

Nothing here opens a window or reads the registry: the opener is a stand-in.
"""
from __future__ import annotations

import unittest

from codex_auto_resume import notice_card, notifier, notify

from test_notice_card import EVENTS, FULL, THREAD, build, fake_measure  # noqa: E402  (the fixtures)

LINK = notify.codex_thread_uri(THREAD)


def buttons(notice):
    """A notice's buttons by label and what they do - a cancel by its interruption, a page by its name."""
    return [(label, notify.parse_cancel_uri(uri), notify.parse_open_uri(uri), notify.parse_power_stop_uri(uri))
            for label, uri in notice.actions]


def resumed(**kwargs):
    return notifier.build("result", {"thread_id": THREAD, "state": "turn_started"}, FULL, **kwargs)


def interruption(**kwargs):
    return notifier.build("interruption", {"thread_id": THREAD, "interruption_id": "a1" * 32, "reset_at": None,
                                           "category": "usage_limit"}, FULL, **kwargs)


class CardTests(unittest.TestCase):
    def test_a_resumed_card_has_no_button_and_its_face_opens_codex(self):
        """Fails with with_open_codex put back to adding a button: the card would draw one and its face stay."""
        plain = resumed()
        self.assertEqual(plain.actions, ())
        shown = notifier.with_open_codex(plain, True)
        vm = notice_card.view(shown)
        self.assertEqual(vm["actions"], [])
        self.assertEqual(vm["click"], LINK)
        buttons = [item for item in notice_card.layout(vm, 1.0, fake_measure(1.0))["items"]
                   if item["kind"] == "button"]
        self.assertEqual(buttons, [])

    def test_its_words_are_the_notice_s_own(self):
        plain = resumed()
        shown = notifier.with_open_codex(plain, True)
        self.assertEqual(notice_card.texts(notice_card.view(shown)), notice_card.texts(notice_card.view(plain)))


class ToastTests(unittest.TestCase):
    def test_a_resumed_toast_has_no_open_codex_action_and_its_body_launches_the_link(self):
        shown = notifier.with_open_codex(resumed(), True)
        content = shown.toast_content()
        self.assertEqual(content["launch"], LINK)
        self.assertEqual(notifier.toast_actions(content), ())
        xml = notify._toast_xml(**{name: content[name] for name in ("title", "body", "extra", "launch")
                                   if name in content})
        self.assertIn('launch="%s" activationType="protocol"' % LINK, xml)
        self.assertNotIn("<actions>", xml)

    def test_the_toast_after_a_cancel_pressed_on_a_toast_launches_it_too(self):
        shown = notifier.with_open_codex(notifier.build_cancelled(THREAD), True)
        self.assertEqual(shown.toast_content()["launch"], LINK)
        self.assertEqual(shown.click, LINK)


class ButtonsStayTests(unittest.TestCase):
    def test_open_dashboard_and_cancel_are_exactly_the_notice_s_and_the_face_opens_codex(self):
        plain = interruption()
        shown = notifier.with_open_codex(plain, True)
        self.assertEqual(buttons(shown), buttons(plain))
        self.assertTrue(any(notify.parse_open_uri(uri) is not None for _label, uri in shown.actions),
                        "Open Dashboard is still there")
        self.assertTrue(any(notify.parse_cancel_uri(uri) for _label, uri in shown.actions), "and Cancel")
        self.assertEqual(shown.click, LINK)
        self.assertEqual([action["label"] for action in notice_card.view(shown)["actions"]],
                         [label for label, _uri in plain.actions])
        self.assertEqual(notifier.toast_actions(shown.toast_content()), shown.actions, "card and toast: one list")

    def test_the_cancel_button_still_carries_the_decision(self):
        shown = notifier.with_open_codex(interruption(), True)
        cancel = next(uri for _label, uri in shown.actions if notify.parse_cancel_uri(uri))
        self.assertTrue(notify.cancel_asks_open_codex(cancel))


class ChoiceTests(unittest.TestCase):
    """The advanced edition's choice of where a click goes (v0.6.19) composes with it: a click it sent to the chat or
    to Codex is that; the page - its default - is the click that opens Codex when the capability is on."""

    def test_the_chat_choice_wins(self):
        chosen = interruption(destination="chat")
        shown = notifier.with_open_codex(chosen, True)
        self.assertEqual(chosen.click, notify.chat_uri(THREAD))
        self.assertEqual((shown.click, shown.toast_content()["launch"]), (chosen.click, chosen.click))

    def test_the_codex_choice_is_the_same_link(self):
        chosen = interruption(destination="codex")
        shown = notifier.with_open_codex(chosen, True)
        self.assertEqual(shown.click, LINK)
        self.assertEqual(shown.toast_content()["launch"], LINK)

    def test_the_page_default_gives_way_with_the_chat_off_and_with_it_on(self):
        for chat in (False, True):
            with self.subTest(chat=chat):
                destination = notifier.click_destination({"notice_click": "page"}, chat)
                self.assertEqual(notifier.with_open_codex(interruption(destination=destination), True).click, LINK)


class ElseTests(unittest.TestCase):
    def test_an_edition_that_does_not_ask_leaves_every_notice_as_it_was(self):
        for event, detail, identity in EVENTS:
            with self.subTest(event=event):
                notice = build(event, detail, identity)
                if notice is None:
                    continue
                for off in (False, None, "yes", 1):
                    self.assertIs(notifier.with_open_codex(notice, off), notice)

    def test_a_notice_about_no_conversation_keeps_its_page(self):
        notice = notifier.build("after_sleep", {"slept": 7200, "count": 2})
        self.assertIsNone(notice.key)
        self.assertIs(notifier.with_open_codex(notice, True), notice)

    def test_every_notice_about_a_conversation_goes_to_codex_and_none_gains_a_button(self):
        for event, detail, identity in EVENTS:
            with self.subTest(event=event):
                notice = build(event, detail, identity)
                if notice is None or notice.key is None:
                    continue
                shown = notifier.with_open_codex(notice, True)
                self.assertEqual(buttons(shown), buttons(notice))
                self.assertEqual(shown.click, LINK)


class OpenTests(unittest.TestCase):
    def test_the_click_is_opened_through_the_opener_with_exactly_that_link(self):
        opened = []
        click = notifier.with_open_codex(resumed(), True).click
        said = notifier.activate(click, open_link=lambda link: opened.append(link) or True)
        self.assertEqual((said, opened), ("opened", [LINK]))


if __name__ == "__main__":
    unittest.main()

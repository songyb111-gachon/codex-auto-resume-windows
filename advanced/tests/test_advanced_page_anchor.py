# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""Start the 5-hour window early on the Advanced features page, in the window itself (v0.6.20, window_anchor).

Its card says the reset its last start fixed, right under where it stands, while the status carries one ahead; its
choices are the page's own controls: three times of day, each a drop-down of Off and every half hour with Custom...
opening the Settings page's clock dialog for any minute, and Start right after a reset a switch - each choice sent at
once as advanced-option. Driven through the page's own hooks with the real bridge's answers, made in a home of its own;
nothing here reads the real installation or a real Codex, and the window is never shown.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_anchor.py
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced.engine import anchor  # noqa: E402
from pagecase import CSC, POWERSHELL, PageCase, ok, sent, snapshot  # noqa: E402

CAP = "window_anchor"
TIMES = ["anchor_at_1", "anchor_at_2", "anchor_at_3"]


def with_anchor(reply, **shown):
    made = copy.deepcopy(reply)
    made["status"]["advanced"][CAP] = dict({"started_at": None, "fixed_at": None}, **shown)
    return made


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def scenario_on(cls, bridge):
        """On, with a reset its start fixed an hour ahead: its card read; 07:00 chosen for the first time; Start right
        after a reset switched off; 07:45 typed in the clock dialog for the second time; then no fixed reset ahead."""
        cls.watched(bridge, CAP, state="armed")
        script = cls.opening(bridge, "en")
        generation = script["advanced-list"][0]["result"]["generation"]
        reply = snapshot(on=1)
        done = ok({"done": True, "generation": generation})
        steps = [{"do": "snapshot", "reply": with_anchor(reply, started_at=ac.NOW - 60, fixed_at=ac.NOW + 3600)},
                 {"do": "show"}, {"do": "choose", "id": CAP}, {"do": "look"},
                 {"do": "reply", "key": "advanced-option", "with": [done, done, done]},
                 {"do": "set_option", "key": "anchor_at_1", "value": anchor.encode_time(7, 0)},
                 {"do": "set_option", "key": "anchor_after_reset", "value": 2},
                 {"do": "custom_option", "key": "anchor_at_2", "value": 7, "minute": 45},
                 {"do": "snapshot", "reply": with_anchor(reply, started_at=ac.NOW - 60, fixed_at=None)},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "words": script["advanced-words"][0]["result"]["words"], "generation": generation}

    def test_its_times_are_drop_downs_of_off_and_every_half_hour_with_custom(self):
        result, expected = self.of("scenario_on")
        words = expected["words"]
        first = result["looks"][0]
        times = [choice for choice in first["choices"] if choice["key"] in TIMES]
        self.assertEqual([choice["key"] for choice in times], TIMES)
        halves = ["%02d:%02d" % divmod(minute, 60) for minute in range(0, 1440, 30)]
        for choice in times:
            with self.subTest(choice["key"]):
                self.assertEqual(choice["items"], [words["page.option.off"]] + halves + [words["page.option.custom"]])
                self.assertEqual(choice["value"], words["page.option.off"])
                self.assertTrue(choice["enabled"])
        options_card = first["cards"][-1] if first["cards"][-1][0] == words["page.options"] else \
            next(card for card in first["cards"] if card[0] == words["page.options"])
        for key in TIMES:
            self.assertIn(words["page.option." + key], options_card)

    def test_start_right_after_a_reset_is_a_switch_on_by_default(self):
        """Fails with anchor_after_reset left out of IsSwitchChoice: it is a drop-down of 1 and 2."""
        result, expected = self.of("scenario_on")
        first = result["looks"][0]
        (switch,) = [each for each in first["switches"] if each["key"] == "anchor_after_reset"]
        self.assertEqual((switch["on"], switch["enabled"], switch["name"], switch["role"]),
                         (True, True, expected["words"]["page.option.anchor_after_reset"], "CheckButton"))
        self.assertFalse([choice for choice in first["choices"] if choice["key"] == "anchor_after_reset"])

    def test_each_choice_is_sent_at_once_and_a_minute_of_ones_own_comes_from_the_clock(self):
        result, expected = self.of("scenario_on")
        generation = expected["generation"]
        self.assertEqual(sent(result, "advanced-option"),
                         [{"capability": CAP, "key": "anchor_at_1", "value": 422, "generation": generation},
                          {"capability": CAP, "key": "anchor_after_reset", "value": 2, "generation": generation},
                          {"capability": CAP, "key": "anchor_at_2", "value": 7 * 60 + 45 + 2,
                           "generation": generation}])
        (dialog,) = result["dialogs"]
        self.assertEqual(dialog["hint"], "From 00:00 to 23:59.")
        self.assertEqual(dialog["findings"], [])

    def test_its_card_says_the_reset_it_fixed_right_under_where_it_stands(self):
        """Fails with BuildAnchorLine's call removed: the card says nothing of the reset."""
        result, expected = self.of("scenario_on")
        words = expected["words"]
        head_words, _, tail = words["page.anchor.fixed"].partition("{time}")
        first, last = result["looks"][0], result["looks"][-1]
        head = first["cards"][0]
        at = head.index(words["page.col_state"])
        self.assertEqual(head[at + 1], words["state.armed"])
        self.assertTrue(head[at + 2].startswith(head_words) and head[at + 2].endswith(tail), head)
        self.assertFalse([text for text in last["cards"][0] if text.startswith(head_words)],
                         "no reset ahead: no line")


if __name__ == "__main__":
    unittest.main()

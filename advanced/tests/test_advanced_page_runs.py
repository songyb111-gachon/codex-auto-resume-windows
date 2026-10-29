"""The Advanced features page's card of the turns run here, and what Pending and History say of a row this edition
had a hand in (v0.6.16-beta.4, advanced/gui/AdvancedRuns.cs).

While Run a conversation here while Codex is closed (or Compact a full conversation, or the model fallback) is on, its
column has a card "Turns run here now": each run the status carries (surfaces.runs), a line naming its conversation
and the time its cap ends it, and Stop... under it, which asks first and sends advanced-headless-stop with that run's
interruption id; a Stop already asked reads "Stopping..." and offers no button. Turned off, there is no card. Pending's
and History's rows join this edition's words to their own lines (CellsWritten): the kind of a terminal's or VS Code's
conversation after its label, the /compact hint and a model not put back after its status, and a continuation with
no words after History's outcome. The window is driven as the other page modules drive it (pagecase.py).

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from pagecase import PageCase, sent, snapshot  # noqa: E402

RUNNING = "headless_run"


def runs(reply):
    """The status's runs (surfaces.runs) for the first two waiting recoveries of `reply`, the second one stopping."""
    first, second = (row["interruption_id"] for row in reply["pending"][:2])
    return [{"interruption_id": first, "capability": RUNNING, "started_at": ac.NOW - 60, "ends_by": ac.NOW + 3540,
             "stopping": False},
            {"interruption_id": second, "capability": RUNNING, "started_at": ac.NOW - 120, "ends_by": ac.NOW + 3480,
             "stopping": True}]


class PageTests(PageCase):
    @classmethod
    def scenario_runs(cls, bridge):
        """On: the card lists both runs; Stop... on the first asks, then sends its id; the second offers none."""
        cls.watched(bridge, RUNNING, state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot()
        reply["status"]["advanced"]["runs"] = runs(reply)
        first, second = (row["interruption_id"] for row in reply["pending"][:2])
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": RUNNING}, {"do": "look"},
                 {"do": "reply", "key": "advanced-headless-stop", "with": [{"ok": True, "result": {"done": True,
                                                                                                    "refusal": None}}]},
                 {"do": "run_stop", "key": first}, {"do": "look"}, {"do": "run_stop", "key": second}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {
            "pending": reply["pending"], "words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_runs_busy(cls, bridge):
        """On, while another action is under way: Stop... is greyed and cannot be pressed; over, it can (v0.6.19-beta.3,
        the controls audit: it stayed live and a click was silently ignored)."""
        cls.watched(bridge, RUNNING, state="armed")
        script = cls.opening(bridge, "en")
        reply = snapshot()
        reply["status"]["advanced"]["runs"] = runs(reply)
        first = reply["pending"][0]["interruption_id"]
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": RUNNING},
                 {"do": "busy", "on": True}, {"do": "run_stop", "key": first}, {"do": "busy", "on": False},
                 {"do": "reply", "key": "advanced-headless-stop", "with": [{"ok": True, "result": {"done": True,
                                                                                                    "refusal": None}}]},
                 {"do": "run_stop", "key": first}]
        return "en", {"answers": [True], "script": script, "steps": steps}, {"first": first}

    @classmethod
    def scenario_runs_off(cls, bridge):
        """Off: no card, whatever the status carries."""
        script = cls.opening(bridge, "en")
        reply = snapshot()
        reply["status"]["advanced"]["runs"] = runs(reply)
        steps = [{"do": "snapshot", "reply": reply}, {"do": "show"}, {"do": "choose", "id": RUNNING}, {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {"words": script["advanced-words"][0]["result"]["words"]}

    @classmethod
    def scenario_rows(cls, bridge):
        """Pending's and History's rows, with what the status says of four of them (surfaces.rows)."""
        script = cls.opening(bridge, "en")
        reply = snapshot()
        # The snapshot's History lists the waiting recoveries too (test_gui_layout.fullest_snapshot): the finished
        # ones are those it has beside them.
        pending = reply["pending"]
        history = [row for row in reply["history"]
                   if row["interruption_id"] not in {each["interruption_id"] for each in pending}]
        reply["status"]["advanced"].update({
            "kinds": {pending[0]["interruption_id"]: "cli", history[0]["interruption_id"]: "ide"},
            "compacting": [pending[1]["interruption_id"]],
            "model_not_restored": [history[1]["interruption_id"]],
            "silent": [history[0]["interruption_id"]]})
        steps = [{"do": "snapshot", "reply": reply}, {"do": "page", "name": "pending"}, {"do": "page", "name": "history"},
                 {"do": "look"}]
        return "en", {"script": script, "steps": steps}, {
            "pending": pending, "history": history, "words": script["advanced-words"][0]["result"]["words"]}

    # ---------------------------------------------------------------- the runs card
    def card(self, look, words):
        return next((card for card in look["cards"] if card[0] == words["page.runs.title"]), None)

    def test_the_card_lists_each_run_with_its_cap_and_a_stop_that_asks_first(self):
        result, expected = self.of("scenario_runs")
        words, pending = expected["words"], expected["pending"]
        shown, after = result["looks"]
        card = self.card(shown, words)
        self.assertIsNotNone(card, "the runs card is shown while the capability is on")
        lines = [text for text in card if text.startswith(pending[0]["name"] + " · ")]
        self.assertEqual(len(lines), 1, card)
        self.assertIn(words["page.runs.until"].split("{time}")[0].strip(), lines[0])
        self.assertIn(words["page.runs.stopping"], card, "a Stop already asked")
        self.assertEqual(shown["run_stops"], [pending[0]["interruption_id"]], "no Stop for one stopping")
        self.assertEqual(result["asked"], [words["page.confirm.run_stop"]])
        self.assertEqual(sent(result, "advanced-headless-stop"), [{"interruption_id": pending[0]["interruption_id"]}])
        self.assertEqual(after["note"], words["page.done.run_stop"])
        self.assertEqual(result["disabled"], ["run_stop"])

    def test_stop_is_greyed_while_another_action_is_under_way(self):
        """Fails with the runs' Stop... left out of the page's buttons again: pressed while busy, it was live."""
        result, expected = self.of("scenario_runs_busy")
        self.assertEqual(result["disabled"], ["run_stop"])
        self.assertEqual(sent(result, "advanced-headless-stop"), [{"interruption_id": expected["first"]}])

    def test_turned_off_there_is_no_card(self):
        result, expected = self.of("scenario_runs_off")
        (shown,) = result["looks"]
        self.assertIsNone(self.card(shown, expected["words"]))
        self.assertEqual(shown["run_stops"], [])
        self.assertEqual(sent(result, "advanced-headless-stop"), [])

    # ---------------------------------------------------------------- Pending's and History's rows
    def test_each_word_joins_its_cells_own_line(self):
        result, expected = self.of("scenario_rows")
        words, pending, history = expected["words"], expected["pending"], expected["history"]
        (shown,) = result["looks"]
        rows, done = shown["pending_rows"], shown["history_rows"]
        self.assertEqual(len(rows), len(pending))
        self.assertEqual(len(done), len(pending) + len(history))
        labels = [row[0] for row in rows]
        self.assertIn(pending[0]["name"] + " · " + words["page.row.kind.cli"], labels)
        self.assertTrue(any(row[1].endswith(" · " + words["page.row.compact"]) for row in rows), rows)
        self.assertIn(history[0]["name"] + " · " + words["page.row.kind.ide"], [row[0] for row in done])
        self.assertTrue(any(row[1].endswith(" · " + words["page.row.model_not_restored"]) for row in done), done)
        self.assertTrue(any(row[1].endswith(" · " + words["page.row.silent"]) for row in done), done)
        self.assertFalse(any(words["page.row.compact"] in row[1] for row in done), "the /compact hint is Pending's")
        self.assertFalse(any(words["page.row.silent"] in row[1] for row in rows), "a continuation with no words is History's")
        self.assertEqual(len(rows[0]), len(rows[1]), "no cell of its own")


if __name__ == "__main__":
    unittest.main()

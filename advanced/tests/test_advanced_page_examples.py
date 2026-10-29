# ADVANCED-EDITION-CODE: in the advanced edition's tree, never the standard one's.
"""See an example in the window itself (v0.6.20; the owner's decision of 2026-10-29): the open capability's About this
feature card ends with See an example..., and pressing it builds a dialog whose two panes, Without it and With it, the
window draws from sample data through the code its pages draw with (advanced/gui/AdvancedExamples.cs). Driven through the
page's own hooks with the real bridge's answers made in a home of its own: every capability chosen in turn and its button
pressed, the dialog built and never shown (GUI probes never show dialogs), what it showed read back - each pane's caption,
each list's columns and cells, what is sent, the lines, and how much ink each part drew when the window drew it into a
bitmap.

GUI test module: compiles real executables, so it runs on its own (gui_lock.sh, one module at a time).

    PYTHONPATH=src;advanced/src;tests python -m unittest advanced/tests/test_advanced_page_examples.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume_advanced import statement  # noqa: E402
from pagecase import CSC, POWERSHELL, SHOWN, PageCase, snapshot  # noqa: E402

FIXTURES = ("example-project", "example-service", "example-app", "example-docs")
KOREAN = ("other_sessions", "keep_going", "usage_meter", "capacity_retry")


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class PageTests(PageCase):
    @classmethod
    def run_through(cls, bridge, locale, ids):
        script = cls.opening(bridge, locale)
        steps = [{"do": "snapshot", "reply": snapshot()}, {"do": "show"}]
        for capability in ids:
            steps.append({"do": "choose", "id": capability})
            steps.append({"do": "example"})
        words = script["advanced-words"][0]["result"]["words"]
        return locale, {"script": script, "steps": steps}, {"words": words, "ids": list(ids)}

    @classmethod
    def scenario_every(cls, bridge):
        """Every capability in the page's order, its See an example... pressed."""
        return cls.run_through(bridge, "en", SHOWN)

    @classmethod
    def scenario_korean(cls, bridge):
        return cls.run_through(bridge, "ko", KOREAN)

    # ---------------------------------------------------------------- helpers
    def views(self, name="scenario_every"):
        result, expected = self.of(name)
        looks = {look["capability"]: look for look in result["dialogs"]}
        return looks, expected

    @staticmethod
    def parts(look, index, kind=None):
        return [part for part in look["panes"][index]["parts"] if kind is None or part["kind"] == kind]

    # ---------------------------------------------------------------- tests
    def test_every_capability_s_about_card_ends_with_see_an_example_and_it_opens_its_view(self):
        """Fails with the button taken out of the About card: nothing is pressed, for any capability."""
        looks, expected = self.views()
        words = expected["words"]
        self.assertEqual(sorted(looks), sorted(expected["ids"]), "one view for every capability on the page")
        for capability, look in looks.items():
            with self.subTest(capability):
                self.assertTrue(look["pressed"], "the button was there and opened the view")
                self.assertEqual(look["button"], words["page.example.button"])
                self.assertTrue(look["button_in_about"], "in About this feature, its one place")
                self.assertTrue(look["button_enabled"], "it reads nothing and sends nothing, so it is never greyed")
                self.assertEqual(look["title"], words["page.example.title"].replace("{name}", words["name." + capability]))
                self.assertEqual(look["note"], words["page.example.note"])
                self.assertEqual([pane["caption"] for pane in look["panes"]],
                                 [words["page.example.before"], words["page.example.after"]])
                self.assertEqual(look["close"], "Close")
                self.assertTrue(look["accept"], "Enter and Esc both close it")

    def test_both_panes_are_drawn_for_every_capability(self):
        """Each pane has its parts, each list its rows with every cell written, each line its words - and each part drew
        ink when the window drew it into a bitmap."""
        looks, _expected = self.views()
        for capability, look in looks.items():
            for index in (0, 1):
                with self.subTest(capability=capability, pane=index):
                    pane = look["panes"][index]
                    self.assertTrue(pane["parts"], "something is shown")
                    for part in pane["parts"]:
                        self.assertGreater(part["ink"], 0, "the %s part drew" % part["kind"])
                        if "rows" in part:
                            self.assertTrue(part["rows"])
                            self.assertEqual(part["on_card"], "", "the list stands on History's card")
                            for row in part["rows"]:
                                self.assertEqual(len(row), len(part["columns"]))
                                self.assertTrue(row[1], "the state is said")
                                self.assertNotIn("_", row[1], "in words, never a code")
                        else:
                            self.assertTrue(part["text"].strip())

    def test_the_lists_are_written_by_the_window_s_own_cells_in_core_s_and_the_page_s_words(self):
        looks, expected = self.views()
        words = expected["words"]
        core = l10n.catalog("en")
        history = [core["pending.col_conversation"], core["history.col_outcome"], core["pending.col_category"],
                   core["history.col_finished"]]
        pending = [core["pending.col_conversation"], core["pending.col_status"], core["pending.col_category"]]
        (before,) = self.parts(looks["capacity_retry"], 0, "history")
        (after,) = self.parts(looks["capacity_retry"], 1, "history")
        self.assertEqual(before["columns"], history)
        self.assertEqual(before["rows"][0][:3], ["example-project", core["code.exhausted"], core["reason.server_5xx"]])
        self.assertEqual(after["rows"][0][:3], ["example-project", core["code.recovered"], core["reason.server_5xx"]])
        self.assertRegex(after["rows"][0][3], r"^\d{4}-\d\d-\d\d \d\d:\d\d$", "finished, as History writes it")
        # This edition's notes on a row (CellsWritten), read from the sample's own status while the view is built.
        (others,) = self.parts(looks["other_sessions"], 1, "history")
        self.assertEqual([row[0] for row in others["rows"]],
                         ["example-project", "example-service · " + words["page.row.kind.cli"],
                          "example-app · " + words["page.row.kind.ide"]])
        (silent,) = self.parts(looks["silent_continuation"], 1, "history")
        self.assertIn(words["page.row.silent"], silent["rows"][0][1])
        (compact,) = self.parts(looks["compact_continue"], 1, "pending")
        self.assertEqual(compact["columns"], pending)
        self.assertIn(words["page.row.compact"], compact["rows"][0][1])
        (crash,) = self.parts(looks["crash_restart"], 0, "pending")
        self.assertIn(core["overlay.engine_unavailable"], crash["rows"][0][1])
        # The compatibility report's rows: no conversation column at all.
        (report,) = self.parts(looks["compat_report"], 1, "report")
        self.assertEqual(report["columns"], history[1:])
        self.assertEqual(report["rows"][0][:2], [core["code.recovered"], core["reason.usage_limit"]])
        # This edition's own rows, made as Pending makes them (RuleRow, PromptRow), named by the sample's conversations.
        (rules,) = self.parts(looks["reset_message"], 1, "pending")
        self.assertEqual(rules["rows"][1][0], "example-project")
        self.assertEqual(rules["rows"][1][2], words["page.pending.kind.rule"])
        (queued,) = self.parts(looks["prompt_queue"], 1, "pending")
        self.assertEqual([row[2] for row in queued["rows"]], [words["page.pending.kind.message"]] * 2)
        self.assertEqual(self.parts(looks["prompt_queue"], 0)[0]["text"], core["pending.empty"])

    def test_what_is_sent_and_the_lines_are_the_window_s_own_words(self):
        looks, expected = self.views()
        words = expected["words"]
        core = l10n.catalog("en")
        sent = [part["text"] for part in self.parts(looks["marker_free_continuation"], 0, "sent")]
        self.assertEqual(sent, [core["continuation.standard.usage_limit"] + "\r\n\r\n[codex-auto-resume:0a1b2c3d4e5f6a7b]"])
        self.assertEqual([part["text"] for part in self.parts(looks["marker_free_continuation"], 1, "sent")],
                         [core["continuation.standard.usage_limit"]])
        self.assertEqual([part["text"] for part in self.parts(looks["keep_going"], 1, "sent")], [words["continue.keep_going"]])
        self.assertEqual([part["text"] for part in self.parts(looks["empty_response"], 1, "sent")],
                         [words["continue.empty_response"]])
        meter = self.parts(looks["usage_meter"], 1, "line")[0]["text"]
        self.assertTrue(meter.startswith(core["usage.line"].split("{")[0]), meter)
        self.assertIn("88%", meter)
        # Where nothing on screen differs, the statement's own field, as the page shows it.
        field = self.parts(looks["idle_update_check"], 0, "line")[0]["text"]
        self.assertEqual(field, statement.CATALOGS.text("statement.idle_update_check.instead", "en"))

    def test_the_samples_name_nothing_real(self):
        looks, _expected = self.views()
        for capability, look in looks.items():
            for pane in look["panes"]:
                for part in pane["parts"]:
                    for row in (part.get("rows", []) if part["kind"] != "report" else []):
                        with self.subTest(capability=capability, row=row):
                            self.assertIn(row[0].split(" · ")[0], FIXTURES + ("",))
                    self.assertNotRegex(part.get("text", ""), r"(?i)[a-z]:\\|\\users\\")

    def test_the_view_asks_the_bridge_nothing_and_sends_nothing(self):
        """Nothing is asked of the bridge from the press of See an example... to the view's closing, for any capability -
        no read and no request - and nothing is told or asked of the person."""
        looks, _expected = self.views()
        result, _expected = self.of("scenario_every")
        for capability, look in looks.items():
            with self.subTest(capability):
                self.assertEqual(look["asked"], [])
        self.assertEqual(result["asked"], [])
        self.assertEqual(result["told"], [])

    def test_the_view_is_in_the_person_s_language(self):
        looks, expected = self.views("scenario_korean")
        words = expected["words"]
        ko = l10n.catalog("ko")
        self.assertEqual(sorted(looks), sorted(KOREAN))
        for look in looks.values():
            self.assertEqual([pane["caption"] for pane in look["panes"]],
                             [words["page.example.before"], words["page.example.after"]])
            self.assertEqual(look["close"], ko["action.close"])
        (others,) = self.parts(looks["other_sessions"], 1, "history")
        self.assertEqual(others["rows"][1][0], "example-service · " + words["page.row.kind.cli"])
        self.assertEqual([part["text"] for part in self.parts(looks["keep_going"], 1, "sent")], [words["continue.keep_going"]])
        (retry,) = self.parts(looks["capacity_retry"], 1, "history")
        self.assertEqual(retry["rows"][0][1:3], [ko["code.recovered"], ko["reason.server_5xx"]])
        self.assertTrue(self.parts(looks["usage_meter"], 1, "line")[0]["text"].startswith(ko["usage.line"].split("{")[0]))


if __name__ == "__main__":
    unittest.main()

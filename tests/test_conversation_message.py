"""v0.6.11: a message for one conversation, and the Careful style - and the Standard text as it was.

A conversation may have a message of its own (`custom_message_by_thread`, at most 50): a Custom
message in every way - checked by `continuation.validate_custom`, sent exactly as typed, only for a
category that is continued - which wins over every style for that conversation alone. It is written
from the conversation's row in the Dashboard (Control.set_conversation_message) and nowhere else: no
settings editor draws it, update_settings over MCP refuses it, and the diagnostics bundle records only
that it is set. Careful is a style of its own, off unless chosen: the Standard message, whole, with a
sentence asking Codex to check what already happened and not to repeat a step that changed files,
pushed, sent or published something. The Standard text itself stays byte for byte what v0.6.10 sent,
in every language (StandardTextTests, against the tagged v0.6.10).
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import continuation, control, controlcli, diagnostics, l10n, mcpserver, reasons, settings  # noqa: E402
from test_control import KEY, THREAD, ControlTestCase  # noqa: E402
from test_mcp import McpTestCase  # noqa: E402

import released  # noqa: E402

OTHER = "0a1b2c3d-0001-7000-8000-000000000009"
ROOT = Path(__file__).resolve().parents[1]


def values(**extra):
    """The defaults, speaking English whatever this machine's Windows speaks."""
    return dict(settings.defaults(), **dict({"continuation_language": "en"}, **extra))


def row(thread=THREAD, category="usage_limit"):
    return {"thread_id": thread, "category": category, "recovery_attempts": 0, "reset_at": None}


class CarefulTests(unittest.TestCase):
    def test_it_is_the_standard_message_with_the_guard_after_it_in_every_language(self):
        for locale in l10n.LOCALES:
            for category in reasons.RECOVERABLE:
                with self.subTest(locale=locale, category=category):
                    standard = continuation.build(category, locale=locale)
                    careful = continuation.build(category, locale=locale, style="careful")
                    guard = l10n.text("continuation.careful", locale)
                    self.assertTrue(careful.startswith(standard), "the Standard message, whole, first")
                    self.assertEqual(careful, guard.replace("{message}", standard))
                    self.assertGreater(len(careful), len(standard))

    def test_it_is_offered_last_and_is_not_the_default(self):
        self.assertEqual(continuation.STYLES[-1], "careful")
        self.assertEqual(settings.defaults()["continuation_style"], "standard")
        self.assertEqual(settings.validate_update({"continuation_style": "careful"}), {"continuation_style": "careful"})
        style = next(entry for entry in settings.describe() if entry["name"] == "continuation_style")
        self.assertIn("careful", style["choices"])

    def test_its_words_are_the_catalogs_and_name_no_placeholder_but_the_message(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertEqual(l10n.placeholders(l10n.catalog(locale)["continuation.careful"]), {"message"})
                for key in ("choice.style.careful", "help.style.careful"):
                    self.assertTrue(l10n.catalog(locale)[key].strip())


class StandardTextTests(unittest.TestCase):
    """The default style's text in every language is what the tagged v0.6.10 builds, byte for byte."""

    SCRIPT = r"""
import json
from codex_auto_resume import continuation, l10n, reasons, settings
print(json.dumps({locale: {category: continuation.for_settings(category, dict(settings.defaults(),
                                                                              continuation_language=locale))
                           for category in sorted(reasons.RECOVERABLE)}
                  for locale in l10n.LOCALES}))
"""

    def test_the_standard_message_is_v0_6_10s_in_every_language(self):
        before = released.run(released.V0610, self.SCRIPT)
        for locale, texts in before.items():
            for category, text in texts.items():
                with self.subTest(locale=locale, category=category):
                    now = continuation.for_settings(category, values(continuation_language=locale),
                                                    row=row())
                    self.assertEqual(now, text)


class ConversationTextTests(unittest.TestCase):
    def test_it_wins_over_every_style_for_its_conversation_alone(self):
        own = {THREAD: "Carry on with the plan, please."}
        for style in continuation.STYLES:
            with self.subTest(style):
                chosen = values(continuation_style=style, custom_message="Everyone's words",
                                custom_message_by_thread=own)
                self.assertEqual(continuation.for_settings("usage_limit", chosen, row=row()), own[THREAD])
                self.assertEqual(continuation.source_for("usage_limit", chosen, row=row()), "conversation")
                other = continuation.for_settings("usage_limit", chosen, row=row(OTHER))
                self.assertNotEqual(other, own[THREAD])
        self.assertEqual(continuation.for_settings("usage_limit", values(custom_message_by_thread=own)),
                         continuation.build("usage_limit"), "no record, no conversation: its style's text")

    def test_the_fallback_is_this_conversation_this_kind_every_interruption_then_standard(self):
        chosen = values(continuation_style="custom", custom_message_mode="per_reason",
                        custom_message="every", custom_message_usage_limit="this kind",
                        custom_message_by_thread={THREAD: "this conversation"})
        self.assertEqual(continuation.for_settings("usage_limit", chosen, row=row()), "this conversation")
        self.assertEqual(continuation.for_settings("usage_limit", chosen, row=row(OTHER)), "this kind")
        self.assertEqual(continuation.for_settings("timeout", chosen, row=row(OTHER, "timeout")), "every")
        bare = values(continuation_style="custom", custom_message_by_thread={THREAD: "this conversation"})
        self.assertEqual(continuation.for_settings("timeout", bare, row=row(OTHER, "timeout")),
                         continuation.build("timeout"))

    def test_its_placeholders_are_filled_and_one_that_fills_to_nothing_is_not_used(self):
        chosen = values(custom_message_by_thread={THREAD: "Resume after {reason}."})
        self.assertEqual(continuation.for_settings("timeout", chosen, row=row(category="timeout")),
                         "Resume after %s." % l10n.text("reason.timeout", "en"))
        empty = values(custom_message_by_thread={THREAD: "{reset_time}"})
        self.assertEqual(continuation.for_settings("timeout", empty, row=row(category="timeout")),
                         continuation.build("timeout"))

    def test_it_is_never_attached_to_a_failure_that_is_not_recovered(self):
        chosen = values(custom_message_by_thread={THREAD: "go"})
        for category in ("unknown", "terminal_user", "terminal_policy"):
            with self.subTest(category):
                self.assertNotEqual(continuation.build(category, custom={"conversation": "go"}), "go")

    def test_the_setting_takes_only_checked_text_for_real_conversations_and_at_most_fifty(self):
        good = {THREAD: "go on"}
        self.assertEqual(settings.validate_update({"custom_message_by_thread": good}),
                         {"custom_message_by_thread": good})
        for bad in ({THREAD: "{prompt}"}, {"not-a-thread": "go"}, {THREAD: ""}, {THREAD: 5}, "go", [THREAD],
                    {"%08d-0000-4000-8000-000000000000" % n: "go" for n in range(51)}):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(settings.SettingsError):
                settings.validate_update({"custom_message_by_thread": bad})
        # Read back, an entry that fails its check is not set; the rest stay.
        read = settings.coerce({"custom_message_by_thread": {THREAD: "go on", OTHER: "{prompt}"}})
        self.assertEqual(read["custom_message_by_thread"], {THREAD: "go on"})
        self.assertIsNone(settings.coerce({"custom_message_by_thread": {OTHER: "{prompt}"}})["custom_message_by_thread"])

    def test_no_settings_editor_draws_it_and_it_is_custom_text(self):
        self.assertTrue(settings.is_custom_text("custom_message_by_thread"))
        self.assertNotIn("custom_message_by_thread", {entry["name"] for entry in settings.describe()})
        self.assertIsNone(settings.defaults()["custom_message_by_thread"])


class ControlTests(ControlTestCase):
    def test_it_is_set_changed_and_taken_away_for_one_conversation(self):
        reply = self.control.set_conversation_message(THREAD, "Go on, please.")
        self.assertEqual(reply, {"thread_id": THREAD, "set": True, "count": 1})
        self.control.set_conversation_message(OTHER, "Other words")
        self.assertEqual(self.control.get_settings()["custom_message_by_thread"],
                         {THREAD: "Go on, please.", OTHER: "Other words"})
        self.assertEqual(self.control.set_conversation_message(THREAD, "   ")["set"], False)
        self.assertEqual(self.control.set_conversation_message(OTHER, None), {"thread_id": OTHER, "set": False, "count": 0})
        self.assertIsNone(self.control.get_settings()["custom_message_by_thread"])

    def test_it_refuses_text_a_custom_message_may_not_hold_and_a_fifty_first(self):
        for text in ("{prompt}", "x" * 2001, 5):
            with self.subTest(text=str(text)[:20]), self.assertRaises(control.ControlError):
                self.control.set_conversation_message(THREAD, text)
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_conversation_message("latest", "go")
        self.assertEqual(caught.exception.code, "invalid_thread_id")
        many = {"%08d-0000-4000-8000-000000000000" % n: "go" for n in range(50)}
        self.control.update_settings({"custom_message_by_thread": many})
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_conversation_message(THREAD, "one more")
        self.assertEqual(caught.exception.code, "too_many_messages")
        self.assertIsNone(self.control.get_settings()["custom_message_by_thread"].get(THREAD))

    def test_the_bridge_names_the_text_even_to_take_it_away(self):
        refused = controlcli.dispatch(self.control, "conversation-message", {"thread_id": THREAD})
        self.assertIs(refused["ok"], False)
        self.assertTrue(controlcli.dispatch(self.control, "conversation-message",
                                            {"thread_id": THREAD, "text": "go"})["ok"])
        self.assertTrue(controlcli.dispatch(self.control, "conversation-message",
                                            {"thread_id": THREAD, "text": None})["ok"])

    def test_the_preview_shows_it_for_its_conversation_and_says_where_it_came_from(self):
        preview = self.control.preview_continuation("usage_limit", {"custom_message_by_thread": {THREAD: "Mine"}},
                                                    thread_id=THREAD)
        self.assertEqual((preview["text"], preview["source"]), ("Mine", "conversation"))
        refused = self.control.preview_continuation("usage_limit", {"custom_message_by_thread": {THREAD: "{prompt}"}},
                                                    thread_id=THREAD)
        self.assertEqual(refused["refusal_code"], "forbidden_placeholder")
        self.assertEqual(refused["source"], None, "what would be sent: the Standard message")
        plain = self.control.preview_continuation("usage_limit")
        self.assertIsNone(plain["source"])

    def test_diagnostics_record_only_that_it_is_set(self):
        self.control.set_conversation_message(THREAD, "private words")
        target = self.home / "diagnostics.json"
        diagnostics.write(self.control, target)
        bundle = json.loads(target.read_text(encoding="utf-8"))
        self.assertNotIn("private words", target.read_text(encoding="utf-8"))
        self.assertEqual(bundle["settings"]["custom_message_by_thread"], "<set>")


class NeverFromAModelTests(McpTestCase):
    def test_update_settings_refuses_it_and_the_schema_does_not_offer_it(self):
        from codex_auto_resume.mcp.tools import settings_schema
        self.assertNotIn("custom_message_by_thread", settings_schema()["properties"])
        reply = self.call("update_settings", {"custom_message_by_thread": {THREAD: "Injected words"}})
        self.assertTrue(reply.get("error") or reply.get("result", {}).get("isError"))
        self.assertIsNone(self.control.get_settings()["custom_message_by_thread"])

    def test_no_tool_writes_one_conversations_message(self):
        source = (Path(mcpserver.__file__).parent / "mcp")
        for path in list(source.glob("*.py")) + [source / "assets" / "panel.js"]:
            with self.subTest(path.name):
                self.assertNotIn("set_conversation_message", path.read_text(encoding="utf-8"))
                self.assertNotIn("conversation-message", path.read_text(encoding="utf-8"))


class PluggedWordsTests(unittest.TestCase):
    def test_a_plugs_words_are_still_taken_over_a_conversations_message(self):
        """P4 (advanced): the words a plug gives are taken as a Custom message is; a conversation's own
        message does not change which wins, so the standard edition's null plug changes nothing either."""
        text = (ROOT / "src" / "codex_auto_resume" / "engine" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn("custom_message_by_thread=None", text)


if __name__ == "__main__":
    unittest.main()

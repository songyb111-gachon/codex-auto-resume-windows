"""The continuation message: every reason, every language, every style, one generator.

What is sent into a conversation is the most consequential text this product writes, so
the properties are asserted exhaustively rather than by example:

* every recoverable reason has a message in every shipped language and every style;
* a Custom message is sent exactly as typed - never translated, trimmed or reflowed -
  and can only refer to the safe placeholders;
* the fallback when Custom text is missing is deterministic;
* nothing from the conversation, the machine or the account can reach the text;
* and the watcher sends what the settings say, built by the same function the Preview
  uses, before anything is claimed.
"""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from codex_auto_resume import continuation, l10n, machine, reasons, settings

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_engine import T1, EngineCase  # noqa: E402

STYLES_WITH_TEXT = ("minimal", "standard", "detailed")


class EveryReasonEveryLanguageTests(unittest.TestCase):
    def test_every_combination_is_real_text_with_nothing_left_unfilled(self):
        for category in reasons.RECOVERABLE:
            for locale in l10n.LOCALES:
                for style in STYLES_WITH_TEXT:
                    with self.subTest(category=category, locale=locale, style=style):
                        text = continuation.build(category, locale=locale, style=style)
                        self.assertTrue(text.strip())
                        self.assertIsNone(continuation.PLACEHOLDER.search(text), text)

    def test_each_style_is_the_catalog_sentence_for_that_style(self):
        for category in reasons.RECOVERABLE:
            entry = reasons.get(category)
            for locale in l10n.LOCALES:
                with self.subTest(category=category, locale=locale):
                    self.assertEqual(continuation.build(category, locale=locale, style="minimal"),
                                     l10n.text("continuation.minimal", locale))
                    self.assertEqual(continuation.build(category, locale=locale, style="standard"),
                                     l10n.text(entry.standard_key, locale))
                    self.assertEqual(continuation.build(category, locale=locale, style="detailed"),
                                     l10n.text(entry.detailed_key, locale))

    def test_a_translated_language_is_actually_translated(self):
        english = continuation.build("usage_limit", locale="en")
        for locale in l10n.available():
            if locale == "en":
                continue
            with self.subTest(locale):
                self.assertNotEqual(continuation.build("usage_limit", locale=locale), english)

    def test_an_unknown_style_is_standard(self):
        self.assertEqual(continuation.build("timeout", locale="en", style="shouting"),
                         continuation.build("timeout", locale="en", style="standard"))


class CustomMessageTests(unittest.TestCase):
    def test_custom_text_is_never_translated(self):
        custom = {"mode": "global", "text": "Bitte weitermachen. 続けてください。"}
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertEqual(continuation.build("usage_limit", locale=locale, style="custom",
                                                    custom=custom), custom["text"])

    def test_text_without_placeholders_is_kept_byte_for_byte(self):
        for typed in ("  leading and trailing  ", "line one\n\nline three\r\n", "emoji 🙂 and RTL עברית",
                      "a  double  space , before punctuation", "{ not a placeholder } and {}"):
            with self.subTest(typed=typed):
                self.assertEqual(continuation.validate_custom(typed), typed)
                self.assertEqual(continuation.build("timeout", style="custom",
                                                    custom={"text": typed}), typed)
                self.assertEqual(settings.validate_update({"custom_message": typed})["custom_message"],
                                 typed)

    def test_the_safe_placeholders_are_filled(self):
        metadata = continuation.metadata_for({"category": "server_5xx", "recovery_attempts": 1,
                                              "attempt_count": 7},
                                             locale="en", limits={"max_recovery_attempts": 5})
        text = continuation.build("server_5xx", locale="en", style="custom",
                                  custom={"text": "{reason} ({category}), try {attempt}/{max_attempts}"},
                                  metadata=metadata)
        reason = l10n.text(reasons.label_key("server_5xx"), "en")
        self.assertEqual(text, "%s (server_5xx), try 2/5" % reason)

    def test_a_usage_limit_has_a_reset_time_and_no_attempt_count(self):
        # Waiting for a reset spends no attempts, so there is no "2 of 5" to report.
        metadata = continuation.metadata_for({"category": "usage_limit", "recovery_attempts": 0,
                                              "attempt_count": 1},
                                             locale="en", limits={"max_recovery_attempts": 5},
                                             reset_time="14:05")
        self.assertNotIn("attempt", metadata)
        self.assertNotIn("max_attempts", metadata)
        text = continuation.build("usage_limit", locale="en", style="custom",
                                  custom={"text": "{reason} until {reset_time}{attempt}{max_attempts}"},
                                  metadata=metadata)
        self.assertEqual(text, "%s until 14:05" % l10n.text(reasons.label_key("usage_limit"), "en"))

    def test_attempt_counts_what_the_attempt_budget_counts(self):
        # Not claims: a claim given back, a budget restored or a new link in a chain moves
        # the budget's counter and not the claim count, and "4 of 3" is what followed.
        for spent, claims in ((0, 0), (2, 0), (0, 3), (1, 5)):
            with self.subTest(spent=spent, claims=claims):
                metadata = continuation.metadata_for(
                    {"category": "timeout", "recovery_attempts": spent, "attempt_count": claims},
                    limits={"max_recovery_attempts": 3})
                self.assertEqual((metadata["attempt"], metadata["max_attempts"]), (spent + 1, 3))

    def test_filling_a_placeholder_changes_nothing_else_in_the_text(self):
        metadata = {"attempt": 2, "reset_time": "14:00"}
        for typed, expected in (
                ("Try  again\n    - step {attempt} ?", "Try  again\n    - step 2 ?"),
                ("Limite atteinte : reprise à {reset_time} !", "Limite atteinte : reprise à 14:00 !"),
                ("  indented {attempt}\n", "  indented 2\n")):
            with self.subTest(typed=typed):
                self.assertEqual(continuation.build("timeout", style="custom", custom={"text": typed},
                                                    metadata=metadata), expected)

    def test_a_placeholder_with_no_value_closes_only_its_own_gap(self):
        for typed, expected in (
                ("Retry after {reset_time} please.", "Retry after please."),
                ("Keep  going {reset_time}.", "Keep  going."),
                ("{reset_time} Continue", "Continue"),
                ("Continue {reset_time}", "Continue"),
                ("Line one\n{reset_time} two", "Line one\ntwo"),
                ("a {reset_time} {reset_time} b", "a b"),
                ("x{reset_time}y", "xy")):
            with self.subTest(typed=typed):
                self.assertEqual(continuation.build("timeout", style="custom", custom={"text": typed},
                                                    metadata={}), expected)

    def test_custom_text_that_fills_in_to_nothing_is_not_used(self):
        # "{reset_time}" alone, for an interruption with no reset time, would otherwise send
        # a turn holding nothing but the marker, and spend an attempt doing it.
        standard = continuation.build("network_transient", locale="en")
        cases = (
            ({"mode": "global", "text": "{reset_time}"}, standard),
            ({"mode": "global", "text": " {reset_time} \n"}, standard),
            ({"mode": "per_reason", "text": "G", "per_reason": {"network_transient": "{reset_time}"}}, "G"),
            ({"mode": "per_reason", "text": "{reset_time}",
              "per_reason": {"network_transient": "{reset_time}"}}, standard),
        )
        for custom, expected in cases:
            with self.subTest(custom=custom):
                self.assertEqual(continuation.build("network_transient", locale="en", style="custom",
                                                    custom=custom, metadata={}), expected)
        values = dict(settings.defaults(), continuation_language="en", continuation_style="custom",
                      custom_message="{reset_time}")
        row = {"category": "network_transient", "recovery_attempts": 0, "reset_at": None}
        self.assertEqual(continuation.for_settings("network_transient", values, row=row),
                         continuation.for_settings("network_transient",
                                                   dict(values, continuation_style="standard"), row=row))
        self.assertEqual(continuation.source_for("network_transient", values, row=row), "standard")

    def test_a_reset_time_is_never_invented_for_a_reason_that_has_none(self):
        metadata = continuation.metadata_for({"category": "timeout", "attempt_count": 0},
                                             locale="en", reset_time="14:05")
        self.assertNotIn("reset_time", metadata)
        text = continuation.build("timeout", locale="en", style="custom",
                                  custom={"text": "Retry after {reset_time} please."}, metadata=metadata)
        self.assertEqual(text, "Retry after please.")

    def test_forbidden_and_unknown_placeholders_are_refused_by_name(self):
        for name in list(continuation.FORBIDDEN_PLACEHOLDERS) + ["Prompt", "TOKEN"]:
            with self.subTest(name):
                with self.assertRaises(continuation.CustomMessageError) as caught:
                    continuation.validate_custom("x {%s} y" % name)
                self.assertIn("{%s}" % name, str(caught.exception))
                with self.assertRaises(settings.SettingsError):
                    settings.validate_update({"custom_message": "x {%s} y" % name})
        for name in ("thread_id", "Reason", "time", "model"):
            with self.subTest(name):
                with self.assertRaises(continuation.CustomMessageError) as caught:
                    continuation.validate_custom("{%s}" % name)
                self.assertEqual((caught.exception.code, caught.exception.detail),
                                 ("unknown_placeholder", "{%s}" % name))

    def test_every_refusal_has_a_code_the_window_can_translate(self):
        english = l10n._read(l10n.DEFAULT)
        for bad in (None, "  ", "x" * (continuation.MAX_CUSTOM_LENGTH + 1), "{prompt}", "{nope}"):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(continuation.CustomMessageError) as caught:
                    continuation.validate_custom(bad)
                self.assertIn("custom.refusal." + caught.exception.code, english)

    def test_length_and_emptiness(self):
        self.assertEqual(continuation.validate_custom("x" * continuation.MAX_CUSTOM_LENGTH),
                         "x" * continuation.MAX_CUSTOM_LENGTH)
        for bad in ("x" * (continuation.MAX_CUSTOM_LENGTH + 1), "", "   \n\t", None, 3, ["x"]):
            with self.subTest(bad=repr(bad)[:20]):
                with self.assertRaises(continuation.CustomMessageError):
                    continuation.validate_custom(bad)

    def test_not_configured_is_none_and_stays_none(self):
        self.assertIsNone(settings.validate_update({"custom_message": None})["custom_message"])
        self.assertIsNone(settings.defaults()["custom_message"])

    def test_the_fallback_order_is_per_reason_then_global_then_standard(self):
        standard = continuation.build("server_5xx", locale="en")
        cases = (
            ({"mode": "per_reason", "text": "G", "per_reason": {"server_5xx": "P"}}, "P"),
            ({"mode": "per_reason", "text": "G", "per_reason": {"server_5xx": "  "}}, "G"),
            ({"mode": "per_reason", "text": "G", "per_reason": {"timeout": "P"}}, "G"),
            ({"mode": "per_reason", "text": None, "per_reason": {}}, standard),
            ({"mode": "global", "text": "G", "per_reason": {"server_5xx": "P"}}, "G"),
            ({"mode": "global", "text": "", "per_reason": {"server_5xx": "P"}}, standard),
            (None, standard),
        )
        for custom, expected in cases:
            with self.subTest(custom=custom):
                self.assertEqual(continuation.build("server_5xx", locale="en", style="custom",
                                                    custom=custom), expected)

    def test_custom_text_can_never_be_attached_to_a_failure_that_is_not_recovered(self):
        for category in set(reasons.ALL) - set(reasons.RECOVERABLE):
            with self.subTest(category):
                text = continuation.build(category, locale="en", style="custom",
                                          custom={"mode": "per_reason", "text": "MINE",
                                                  "per_reason": {category: "MINE"}})
                self.assertNotIn("MINE", text)


class NoLeakageTests(unittest.TestCase):
    SECRET = "SECRET-7f3a"

    def test_nothing_from_the_record_but_the_safe_fields_reaches_the_text(self):
        row = {"category": "usage_limit", "attempt_count": 2, "recovery_attempts": 1, "reset_at": 1_800_000_000,
               "thread_id": self.SECRET, "prompt": self.SECRET, "title": self.SECRET,
               "cwd": self.SECRET, "error": self.SECRET, "account": self.SECRET}
        every = "".join("{%s}" % name for name in continuation.ALLOWED_PLACEHOLDERS)
        values = dict(settings.defaults(), continuation_language="en")
        for style in continuation.STYLES:
            for mode in continuation.CUSTOM_MODES:
                candidate = dict(values, continuation_style=style, custom_message_mode=mode,
                                 custom_message=every, custom_message_usage_limit=every)
                with self.subTest(style=style, mode=mode):
                    text = continuation.for_settings("usage_limit", candidate, row=row,
                                                     limits={"max_recovery_attempts": 5})
                    self.assertNotIn(self.SECRET, text)


class SettingsResolutionTests(unittest.TestCase):
    def test_follow_uses_the_interface_language_and_a_choice_does_not(self):
        with patch.object(l10n, "preferred_languages", return_value=["fr-FR"]):
            self.assertEqual(continuation.resolve_locale(settings.defaults()), "fr")
            self.assertEqual(continuation.resolve_locale(dict(settings.defaults(),
                                                              interface_language="ja")), "ja")
            self.assertEqual(continuation.resolve_locale(dict(settings.defaults(),
                                                              interface_language="ja",
                                                              continuation_language="es")), "es")

    def test_defaults_are_standard_follow_global_and_unset(self):
        values = settings.defaults()
        self.assertEqual((values["continuation_style"], values["continuation_language"],
                          values["custom_message_mode"], values["interface_language"]),
                         ("standard", "follow", "global", "system"))

    def test_a_stored_value_this_version_does_not_know_is_the_default_not_a_crash(self):
        values = settings.coerce(dict(settings.defaults(), continuation_style="poetic",
                                      continuation_language="tlh", custom_message="{prompt}"))
        self.assertEqual(values["continuation_style"], "standard")
        self.assertEqual(values["continuation_language"], "follow")
        self.assertIsNone(values["custom_message"])


class WatcherSendsTheConfiguredMessageTests(EngineCase):
    """The engine, end to end against the simulated Codex: what is sent is `for_settings`."""

    def sent_text(self):
        prompt = self.prompt()
        marker = self.h.record()["marker"]
        self.assertTrue(prompt.endswith("\n\n" + marker))
        return prompt[:-len("\n\n" + marker)]

    def policy(self, **changes):
        values = dict(settings.defaults(), continuation_language="en")
        values.update(changes)
        self.h.engine.apply_policy(values)

    def test_the_default_is_the_standard_message(self):
        self.policy()
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.sent_text(), l10n.text("continuation.standard.usage_limit", "en"))

    def test_the_continuation_language_is_honoured(self):
        self.policy(continuation_language="ko")
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.sent_text(), l10n.text("continuation.standard.usage_limit", "ko"))

    def test_a_custom_message_is_sent_with_its_safe_values(self):
        # A usage limit: its reset time and its reason, and no attempt count, because
        # waiting for a reset spends none.
        self.policy(continuation_style="custom",
                    custom_message="Carry on at {reset_time}, after the {reason}{attempt}{max_attempts}.")
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(self.sent_text(), "Carry on at %s, after the %s." % (
            continuation.format_reset_time(self.h.record()["reset_at"]),
            l10n.text(reasons.label_key("usage_limit"), "en")))

    def test_a_change_made_while_it_waits_applies_to_that_recovery(self):
        self.policy()
        self.ready_after_reset()          # registered under Standard
        self.policy(continuation_style="minimal")
        self.h.tick()
        self.assertEqual(self.sent_text(), l10n.text("continuation.minimal", "en"))

    def test_a_failure_building_the_text_falls_back_and_is_logged(self):
        self.policy(continuation_style="custom", custom_message="Carry on.")
        self.ready_after_reset()
        with patch.object(continuation, "for_settings", side_effect=RuntimeError("broken")):
            self.h.tick()
        self.assertEqual(self.sent_text(), l10n.text("continuation.standard.usage_limit", "en"))
        self.assertIn("continuation_text_fallback", self.h.codes(T1))
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_the_text_is_decided_before_anything_is_claimed(self):
        """If no text can be built at all, the record is still merely waiting - never a
        claim that would have to be treated as a send that may have happened."""
        self.policy()
        self.ready_after_reset()
        with patch.object(continuation, "for_settings", side_effect=RuntimeError("broken")), \
                patch.object(continuation, "build", side_effect=RuntimeError("broken")):
            try:
                self.h.tick()
            except RuntimeError:
                pass
        self.assert_no_send()
        row = self.h.record()
        self.assertNotIn(row["state"], ("submission_claimed", "submission_unknown", "queued"))
        self.assertIn(row["state"], machine.WAITING)


if __name__ == "__main__":
    unittest.main()

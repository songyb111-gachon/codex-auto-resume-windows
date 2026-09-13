"""The control layer's v0.6.3 surface: the message Preview, the per-task switch, Cancel all.

Three front ends draw these - the Dashboard, the notification-area popup and the panel in
Codex - so what they may and may not do is asserted here, once, against the layer they
all call.
"""
from __future__ import annotations

import time
import unittest

from codex_auto_resume import continuation, control, l10n, reasons, settings
from codex_auto_resume.store import Store

from test_control import KEY, OTHER_KEY, THREAD, ControlTestCase, detection

OTHER_THREAD = "0a1b2c3d-0001-7000-8000-000000000009"


class PreviewTests(ControlTestCase):
    def test_the_preview_is_the_text_the_watcher_builds(self):
        """One generator. The preview must be `for_settings` itself, not a lookalike."""
        now = 1_800_000_000.0
        for category in reasons.RECOVERABLE:
            with self.subTest(category):
                preview = self.control.preview_continuation(category, now=now)
                values = self.control.get_settings()
                sample = {"category": category, "recovery_attempts": 0,
                          "reset_at": now + 3600 if reasons.has_reset_time(category) else None}
                expected = continuation.for_settings(
                    category, values, row=sample,
                    limits={"max_recovery_attempts": values["max_recovery_attempts"]})
                self.assertEqual(preview["text"], expected)
                self.assertEqual(preview["style"], "standard")
                self.assertIsNone(preview["source"])
                self.assertIsNone(preview["refusal"])

    def test_unsaved_choices_are_previewed_and_nothing_is_saved(self):
        before = self.control.get_settings()
        preview = self.control.preview_continuation("usage_limit", {
            "continuation_language": "ko", "continuation_style": "minimal"})
        self.assertEqual(preview["locale"], "ko")
        self.assertEqual(preview["text"], l10n.text("continuation.minimal", "ko"))
        self.assertEqual(self.control.get_settings(), before)
        self.assertFalse(self.paths.settings_file.exists())

    def test_a_custom_message_is_previewed_verbatim_with_its_placeholders_filled(self):
        preview = self.control.preview_continuation("network_transient", {
            "continuation_language": "en", "continuation_style": "custom",
            "custom_message": "Keep going  after the {reason}."})
        self.assertEqual(preview["source"], "global")
        # Filled, and nothing else changed: the double space typed by the person stays.
        self.assertEqual(preview["text"], "Keep going  after the %s."
                         % l10n.text(reasons.label_key("network_transient"), "en"))

    def test_custom_text_that_fills_in_to_nothing_previews_the_standard_message(self):
        preview = self.control.preview_continuation("network_transient", {
            "continuation_language": "en", "continuation_style": "custom",
            "custom_message": "{reset_time}"})
        self.assertIsNone(preview["refusal"])
        self.assertEqual(preview["source"], "standard")
        self.assertEqual(preview["text"], self.control.preview_continuation(
            "network_transient", {"continuation_language": "en"})["text"])

    def test_a_message_without_placeholders_is_sent_byte_for_byte(self):
        typed = "  계속 진행해 주세요.\n\n(자동)  "
        preview = self.control.preview_continuation("timeout", {
            "continuation_style": "custom", "custom_message": typed})
        self.assertEqual(preview["text"], typed)

    def test_a_refused_custom_message_shows_what_would_really_be_sent(self):
        preview = self.control.preview_continuation("server_5xx", {
            "continuation_language": "en", "continuation_style": "custom",
            "custom_message": "Here is my prompt: {prompt}"})
        self.assertIsNotNone(preview["refusal"])
        self.assertIn("{prompt}", preview["refusal"])
        self.assertEqual((preview["refusal_code"], preview["refusal_detail"]),
                         ("forbidden_placeholder", "{prompt}"))
        self.assertEqual(preview["source"], "standard")
        self.assertEqual(preview["text"], l10n.text("continuation.standard.server_5xx", "en"))
        self.assertNotIn("prompt", preview["text"])

    def test_per_reason_falls_back_to_global_then_to_standard(self):
        base = {"continuation_language": "en", "continuation_style": "custom",
                "custom_message_mode": "per_reason"}
        own = dict(base, custom_message_usage_limit="Limit reset; carry on.",
                   custom_message="Carry on.")
        self.assertEqual(self.control.preview_continuation("usage_limit", own)["source"], "per_reason")
        self.assertEqual(self.control.preview_continuation("timeout", own)["source"], "global")
        self.assertEqual(self.control.preview_continuation("timeout", own)["text"], "Carry on.")
        bare = dict(base)
        self.assertEqual(self.control.preview_continuation("timeout", bare)["source"], "standard")

    def test_a_category_that_is_never_recovered_has_no_preview(self):
        for category in ("unknown", "terminal_auth", "terminal_policy", "made_up"):
            with self.subTest(category):
                with self.assertRaises(control.ControlError):
                    self.control.preview_continuation(category)

    def test_malformed_changes_are_refused(self):
        for changes in (["style"], "custom", {"not_a_setting": 1}):
            with self.subTest(changes=changes):
                with self.assertRaises(control.ControlError):
                    self.control.preview_continuation("usage_limit", changes)

    def test_the_interface_language_carries_the_continuation_only_while_it_follows(self):
        follows = self.control.preview_continuation("usage_limit", {
            "interface_language": "ko", "continuation_language": "follow"})
        self.assertEqual(follows["locale"], "ko")
        chosen = self.control.preview_continuation("usage_limit", {
            "interface_language": "ko", "continuation_language": "de"})
        self.assertEqual(chosen["locale"], "de")


class InterruptionSwitchTests(ControlTestCase):
    def test_off_and_on_again_for_the_exact_task(self):
        self.register()
        result = self.control.set_interruption_recovery(KEY, THREAD, False)
        self.assertEqual((result["interruption_id"], result["thread_id"], result["enabled"]),
                         (KEY, THREAD, False))
        with Store(self.paths.state_dir) as store:
            self.assertFalse(store.thread_enabled(THREAD))
        self.assertTrue(self.control.set_interruption_recovery(KEY, THREAD, True)["enabled"])

    def test_a_click_for_another_conversation_changes_nothing(self):
        """A list re-sorted between drawing and clicking must not move a click to another task."""
        self.register()
        self.register(key=OTHER_KEY, thread_id=OTHER_THREAD)
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_interruption_recovery(KEY, OTHER_THREAD, False)
        self.assertEqual(caught.exception.code, "thread_mismatch")
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.thread_enabled(THREAD))
            self.assertTrue(store.thread_enabled(OTHER_THREAD))

    def test_a_record_that_is_gone_or_finished_is_refused(self):
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_interruption_recovery(KEY, THREAD, False)
        self.assertEqual(caught.exception.code, "no_such_interruption")
        self.register()
        self.control.cancel_interruption(KEY)
        with self.assertRaises(control.ControlError) as caught:
            self.control.set_interruption_recovery(KEY, THREAD, True)
        self.assertEqual(caught.exception.code, "already_finished")

    def test_identities_and_the_value_are_validated_before_anything_is_read(self):
        for arguments, code in (((KEY[:10], THREAD, True), "invalid_id"),
                                ((KEY, THREAD.upper(), True), "invalid_thread_id"),
                                ((KEY, THREAD, "false"), "invalid_enabled"),
                                ((KEY, THREAD, 0), "invalid_enabled")):
            with self.subTest(arguments=arguments):
                with self.assertRaises(control.ControlError) as caught:
                    self.control.set_interruption_recovery(*arguments)
                self.assertEqual(caught.exception.code, code)

    def test_switching_on_sends_nothing_and_changes_no_schedule(self):
        self.register()
        with Store(self.paths.state_dir) as store:
            before = dict(store.get(KEY))
        self.control.set_interruption_recovery(KEY, THREAD, False)
        self.control.set_interruption_recovery(KEY, THREAD, True)
        with Store(self.paths.state_dir) as store:
            after = dict(store.get(KEY))
        for field in ("state", "attempt_count", "next_attempt_at", "reset_at"):
            if field in before:
                self.assertEqual(after[field], before[field], field)


class CancelAllTests(ControlTestCase):
    def test_every_pending_recovery_is_cancelled_by_its_own_id(self):
        self.register()
        self.register(key=OTHER_KEY, thread_id=OTHER_THREAD)
        result = self.control.cancel_all_pending()
        self.assertEqual((result["requested"], result["cancelled"], result["failed"]), (2, 2, 0))
        with Store(self.paths.state_dir) as store:
            self.assertEqual(store.pending(), [])

    def test_nothing_pending_is_not_an_error(self):
        self.assertEqual(self.control.cancel_all_pending(),
                         {"requested": 0, "cancelled": 0, "already_finished": 0, "failed": 0})

    def test_it_never_turns_a_conversation_off(self):
        """Cancel all stops what is waiting; it is not a way to disable conversations."""
        self.register()
        self.control.cancel_all_pending()
        with Store(self.paths.state_dir) as store:
            self.assertTrue(store.thread_enabled(THREAD))

    def test_the_layer_offers_no_bulk_retry(self):
        names = [name for name in dir(control.Control) if not name.startswith("_")]
        self.assertFalse([name for name in names if "all" in name and "retry" in name])


class BridgeCommandTests(ControlTestCase):
    def run_bridge(self, command, payload=None):
        import io
        import json
        from unittest.mock import patch
        from codex_auto_resume import controlcli
        argv = ["--home", str(self.home), command]
        if payload is not None:
            argv.append(json.dumps(payload))
        stream = io.StringIO()
        with patch("sys.stdout", stream):
            controlcli.main(argv)
        return json.loads(stream.getvalue())

    def test_the_window_reaches_all_three(self):
        self.register()
        preview = self.run_bridge("preview-continuation", {"category": "usage_limit"})
        self.assertTrue(preview["ok"])
        self.assertTrue(preview["result"]["text"])
        switched = self.run_bridge("interruption-recovery",
                                   {"interruption_id": KEY, "thread_id": THREAD, "enabled": False})
        self.assertTrue(switched["ok"])
        self.assertFalse(switched["result"]["enabled"])
        refused = self.run_bridge("interruption-recovery",
                                  {"interruption_id": KEY, "thread_id": THREAD, "enabled": "no"})
        self.assertFalse(refused["ok"])
        cancelled = self.run_bridge("cancel-all")
        self.assertTrue(cancelled["ok"])
        self.assertEqual(cancelled["result"]["cancelled"], 1)

    def test_strings_follow_the_stored_interface_language(self):
        self.control.update_settings({"interface_language": "ko"})
        try:
            reply = self.run_bridge("strings")
        finally:
            l10n.set_preference(l10n.SYSTEM)
        self.assertEqual(reply["language"], "ko")
        self.assertEqual(reply["preference"], "ko")
        self.assertEqual(reply["endonyms"]["ja"], "日本語")


if __name__ == "__main__":
    unittest.main()

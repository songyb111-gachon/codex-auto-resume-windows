"""v0.6.11: a message for one conversation, the Careful style folded into Detailed - and the texts as they were.

A conversation may have a message of its own (`custom_message_by_thread`, at most 50): a Custom
message in every way - checked by `continuation.validate_custom`, sent exactly as typed, only for a
category that is continued - which wins over every style for that conversation alone. It is written
from the conversation's row in the Dashboard (Control.set_conversation_message) and nowhere else: no
settings editor draws it, update_settings over MCP refuses it, and the diagnostics bundle records only
that it is set. v0.6.11-beta's Careful style asked what Detailed already asks, so the final has four
styles again - Minimal, Standard, Detailed, Custom last - and a stored "careful" is Detailed, on load and
in the migration (FoldedStyleTests). The Standard text stays byte for byte what v0.6.10 sent, in every
language (StandardTextTests, against the tagged v0.6.10), and every style's words stay byte for byte
what they were at 9678fd68, where Careful was folded (StyleTextTests).
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
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


class FoldedStyleTests(unittest.TestCase):
    """Careful is gone: four styles, Custom last, and a stored "careful" reads as Detailed."""

    def test_the_styles_are_minimal_standard_detailed_and_custom_last(self):
        self.assertEqual(tuple(continuation.STYLES), ("minimal", "standard", "detailed", "custom"))
        self.assertEqual(settings.defaults()["continuation_style"], "standard")
        style = next(entry for entry in settings.describe() if entry["name"] == "continuation_style")
        self.assertEqual(style["choices"], ["minimal", "standard", "detailed", "custom"])

    def test_a_stored_careful_is_detailed_on_load_and_in_the_migration(self):
        self.assertEqual(continuation.FOLDED_STYLES, {"careful": "detailed"})
        for stored in ({"config_version": 2, "continuation_style": "careful"},
                       {"continuation_style": "careful"}):
            with self.subTest(marked="config_version" in stored):
                self.assertEqual(settings._migrate(stored)["continuation_style"], "detailed")
                with tempfile.TemporaryDirectory() as scratch:
                    path = Path(scratch) / "settings.json"
                    path.write_text(json.dumps(stored), encoding="utf-8")
                    self.assertEqual(settings.load(path)["continuation_style"], "detailed")
                    # The next save writes the style it became, which every earlier version reads.
                    settings.update(path, {"max_recovery_attempts": 5})
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["continuation_style"], "detailed")
        self.assertEqual(settings.coerce({"continuation_style": "careful"})["continuation_style"], "detailed")
        self.assertEqual(continuation.style_from({"continuation_style": "careful"}), "detailed")
        # Anything else that is not a style is still the default, and folds nothing on the way.
        for other in (["careful"], {"careful": 1}, 5, None, "Careful"):
            with self.subTest(other=other):
                self.assertEqual(settings.coerce(settings._migrate({"continuation_style": other}))
                                 ["continuation_style"], "standard")

    def test_it_sends_the_detailed_message_wherever_it_is_read(self):
        for locale in l10n.LOCALES:
            for category in reasons.RECOVERABLE:
                with self.subTest(locale=locale, category=category):
                    detailed = continuation.build(category, locale=locale, style="detailed")
                    self.assertEqual(continuation.build(category, locale=locale, style="careful"), detailed)
                    chosen = values(continuation_language=locale, continuation_style="careful")
                    self.assertEqual(continuation.for_settings(category, chosen, row=row(category=category)),
                                     continuation.for_settings(category, dict(chosen, continuation_style="detailed"),
                                                               row=row(category=category)))

    def test_a_write_that_names_it_is_refused_with_the_styles_there_are(self):
        with self.assertRaises(settings.SettingsError) as caught:
            settings.validate_update({"continuation_style": "careful"})
        self.assertEqual(str(caught.exception),
                         "invalid value for continuation_style: expected one of minimal, standard, detailed, custom")

    def test_no_catalog_has_its_words(self):
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                table = l10n.catalog(locale)
                for key in ("continuation.careful", "choice.style.careful", "help.style.careful"):
                    self.assertNotIn(key, table)


class StyleTextTests(unittest.TestCase):
    """Every style's words, in every catalog, are byte for byte what they were at 9678fd68 - the commit
    Careful was folded from - and so is every message `build` makes of them.

    Pinned as digests, since a shallow checkout has no 9678fd68 to read. They are `digest()` of each
    catalog as `git show 9678fd68:src/codex_auto_resume/locales/<locale>.json` has it, and `built()` as
    9678fd68's own code made it."""

    STYLES = ("minimal", "standard", "detailed", "custom")
    # locale -> (how many keys, SHA-256 of them as sorted JSON), at 9678fd68.
    PINNED = {
        "en": (21, "9e261dd88ae6d36baecae8ccfc0df72f2a38aad4f6bd3b79abb2727b8c2fc189"),
        "ko": (21, "3e9a433ed6fed077ec0ad354ebb3bb1928081fee03e683c4bd9488c83f825f9b"),
        "ja": (21, "ad8fd555e3c74fe3b548db87127c042ef3d8911e8260eac7a1ae837020a3a00e"),
        "zh-CN": (21, "38b2bd45267d6f0ea04a345d044d59fa917aae52966aa448127c8f3389333970"),
        "zh-TW": (21, "84acc7c1bda29c5acf32d903684d6b37cfea6081a065162741239ff75a8af63d"),
        "es": (21, "bb466762ebd70300bfa7b698cfae25a904e31ada65782d0dac627adbe7111eb9"),
        "de": (21, "32fe24c1c71a487fd934e9f1ba62d00847e9b57937031d44ccc4acb1eff50d94"),
        "fr": (21, "c55c41441eb6dffa0012f8a0d4979c21d81cc447c6087c7f3718b79a0895af6f"),
        "pt-BR": (21, "69c43933afdd5c43e2dbd51cdc6aac8fc808338579aed4c2ae02e4c38eafdc2d"),
        "ru": (21, "293e4f4624ef50b4877c590b773685e649569ab4612410f3542a4d0aee2eabd6"),
        "it": (21, "38939104b17d36fd5f9fe9865fcb0cb6f27b2cca31a5bbe91e65478464a0dde4"),
        "tr": (21, "04ea4bdfaf5ddafc2616e0336a6634529601a193caa03c6f331770ad18c25a12"),
        "pl": (21, "3b519e07787402f180de43e3ffdb2cdd087135da82b144a13f793f1d4bcbf8d4"),
        "uk": (21, "75a8d14f5cc16f1813131a0169644fd3608579271df5d286ea3c9da95f33da7e"),
        "vi": (21, "032b9922ef974c3fc61550673643d83897f6fc9278f78a9ed598dbbb38ada887"),
        "id": (21, "9be5552253fc82eb6f75513d8343b44a8b1dcda18d147d73a715dd5f22c55d33"),
        "ar": (21, "fa298a044ab678cce44b5f00470a3ab46e6007ff6cf4e3bd29851613c11224d5"),
        "he": (21, "84036925d8835461b2c12f4c3e2042050ca961bab24d38f0941164693558b1fd"),
    }
    # Every locale x recoverable category x style `build` makes, in that order, at 9678fd68.
    BUILT = (432, "6128c4b647ba0664c7310534da60142549738eddccef11a9d2960790680f003f")

    @classmethod
    def keys(cls, table):
        """The style keys a catalog has: the messages, and each style's name and help."""
        named = {"%s.style.%s" % (kind, style) for kind in ("choice", "help") for style in cls.STYLES}
        return sorted(key for key in table if key == "continuation.minimal" or key in named
                      or key.startswith(("continuation.standard.", "continuation.detailed.")))

    @classmethod
    def digest(cls, table):
        chosen = {key: table[key] for key in cls.keys(table)}
        return len(chosen), hashlib.sha256(json.dumps(chosen, ensure_ascii=False, sort_keys=True)
                                           .encode("utf-8")).hexdigest()

    @classmethod
    def built(cls):
        made, count = hashlib.sha256(), 0
        for locale in l10n.LOCALES:
            for category in sorted(reasons.RECOVERABLE):
                for style in cls.STYLES:
                    made.update(("%s|%s|%s|" % (locale, category, style)).encode())
                    made.update(continuation.build(category, locale=locale, style=style).encode("utf-8"))
                    made.update(b"\n")
                    count += 1
        return count, made.hexdigest()

    def test_every_catalogs_style_words_are_9678fd68s(self):
        self.assertEqual(set(self.PINNED), set(l10n.LOCALES))
        folder = ROOT / "src" / "codex_auto_resume" / "locales"
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                table = json.loads((folder / ("%s.json" % locale)).read_text(encoding="utf-8"))
                self.assertEqual(self.digest(table), self.PINNED[locale])

    def test_every_message_the_styles_build_is_9678fd68s(self):
        self.assertEqual(self.built(), self.BUILT)


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
        message does not change which wins, so the standard edition's null plug changes nothing either.
        Read from the method that takes them, wherever it lives (engine/delivery.py since v0.6.14)."""
        from codex_auto_resume.engine import Engine
        self.assertIn("custom_message_by_thread=None", inspect.getsource(Engine._plugged_text))


if __name__ == "__main__":
    unittest.main()

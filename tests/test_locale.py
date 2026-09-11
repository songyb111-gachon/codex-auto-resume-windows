"""One language decision, and every surface obeying it.

Until v0.5.6 the product spoke two languages at once. The plugin layer resolved a locale
and used it for notifications and setup output; the settings window and the Codex panel
carried their own English literals, so a machine whose Windows is Korean got Korean toasts
and an English settings window. The rule that fixes it is not "translate more strings" -
it is that the decision is made once and handed to everything.

So there are two kinds of test here:

* **The decision.** Korean when, and only when, the *most preferred* UI language is
  Korean. A locale that merely lists Korean after another language is not a request for
  Korean, and nothing infers a language from an IP address, a time zone, a user name or a
  keyboard layout - the tags below are the whole input.
* **The reach.** The same decision arriving at the toast, the setup output, the standalone
  window's bridge and the Codex panel's markup. Asserted by resolving each surface for the
  same environment and comparing, because "they all call the same function" is a property
  that survives exactly until someone adds a fourth surface.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_auto_resume import controlcli, interface, mcpui, messages   # noqa: E402


def env(*tags, override=None):
    """An environment with no Windows probe and no override unless one is given."""
    environ = {}
    if override is not None:
        environ[messages.ENV_LANG] = override
    if tags:
        environ["LANG"] = tags[0].replace("-", "_")
    return environ


class DecisionTests(unittest.TestCase):
    """What language, for a given machine."""

    def resolve(self, tags, override=None):
        # `preferred_languages` reads the Windows API first; on a developer machine that
        # would answer for the developer rather than for the case under test, so the tag
        # list is injected directly.
        original = messages._windows_preferred
        messages._windows_preferred = lambda: list(tags)
        try:
            environ = {} if override is None else {messages.ENV_LANG: override}
            return messages.language(environ)
        finally:
            messages._windows_preferred = original

    def test_korean_when_korean_is_the_primary_preference(self):
        for tags in (["ko-KR"], ["ko"], ["ko-KR", "en-US"], ["ko-Kore-KR"]):
            with self.subTest(tags):
                self.assertEqual(self.resolve(tags), "ko")

    def test_english_for_every_other_primary_preference(self):
        for tags in (["en-US"], ["en-GB"], ["ja-JP"], ["zh-CN"], ["zh-Hant-TW"],
                     ["fr-FR"], ["de-DE"], ["es-ES"], ["pt-BR"], ["ru-RU"]):
            with self.subTest(tags):
                self.assertEqual(self.resolve(tags), "en")

    def test_korean_listed_second_is_not_a_request_for_korean(self):
        """The case the rule exists for.

        Windows lists every language a user has added. Someone whose interface is English
        and who also reads Korean has both, in that order, and would be surprised by a
        Korean settings window.
        """
        for tags in (["en-US", "ko-KR"], ["ja-JP", "ko"], ["fr-FR", "ko-KR", "en-US"]):
            with self.subTest(tags):
                self.assertEqual(self.resolve(tags), "en")

    def test_no_preference_at_all_is_english(self):
        self.assertEqual(self.resolve([]), "en")

    def test_the_explicit_override_wins_in_both_directions(self):
        self.assertEqual(self.resolve(["en-US"], override="ko"), "ko")
        self.assertEqual(self.resolve(["ko-KR"], override="en"), "en")

    def test_an_unsupported_override_is_english_rather_than_an_error(self):
        self.assertEqual(self.resolve(["ko-KR"], override="ja"), "en")


class CatalogTests(unittest.TestCase):
    """The strings themselves."""

    def test_every_key_exists_in_every_language(self):
        english = set(interface.STRINGS["en"])
        for language, table in interface.STRINGS.items():
            with self.subTest(language):
                self.assertEqual(set(table), english,
                                 "a key missing here reaches a user as a blank label or "
                                 "as an English word inside a Korean sentence")

    def test_no_string_is_empty(self):
        for language, table in interface.STRINGS.items():
            for key, value in table.items():
                with self.subTest(language + ":" + key):
                    self.assertTrue(value.strip(), "empty string")

    def test_the_languages_match_the_message_catalog(self):
        self.assertEqual(set(interface.STRINGS), set(messages.MESSAGES),
                         "a language the product speaks in one catalog and not the other")

    def test_placeholders_survive_translation(self):
        """`{n}` and `{reason}` are substituted, so losing one loses the number."""
        for key, english in interface.STRINGS["en"].items():
            wanted = {piece.split("}")[0] for piece in english.split("{")[1:]}
            for language, table in interface.STRINGS.items():
                got = {piece.split("}")[0] for piece in table[key].split("{")[1:]}
                with self.subTest(language + ":" + key):
                    self.assertEqual(got, wanted)

    def test_every_setting_the_panels_show_has_a_label(self):
        from codex_auto_resume import settings as policy
        shown = {entry["name"] for entry in policy.describe()
                 if entry.get("group") in ("recovery", "limits", "notifications")}
        missing = sorted(name for name in shown
                         if "field." + name not in interface.STRINGS["en"])
        self.assertEqual(missing, [],
                         "a setting with no label falls back to a humanised English name, "
                         "in the middle of a Korean card")


class ReachTests(unittest.TestCase):
    """The same decision, at every surface."""

    def surfaces(self, language):
        """What each surface resolves to, for one environment."""
        environ = {messages.ENV_LANG: language}
        window = json.loads(_capture(["--home", "x", "strings"], environ))
        panel = mcpui.settings_page(theme="light")
        return {
            "toast": messages.text("setup_done", environ),
            "catalog": interface.catalog(environ),
            "window_language": window["language"],
            "window_strings": window["strings"],
            "panel": panel,
        }

    def test_one_language_reaches_all_four(self):
        for language in ("en", "ko"):
            with self.subTest(language):
                import os
                original = os.environ.get(messages.ENV_LANG)
                os.environ[messages.ENV_LANG] = language
                try:
                    surfaces = self.surfaces(language)
                finally:
                    if original is None:
                        os.environ.pop(messages.ENV_LANG, None)
                    else:
                        os.environ[messages.ENV_LANG] = original

                expected = interface.STRINGS[language]
                self.assertEqual(surfaces["window_language"], language)
                self.assertEqual(surfaces["window_strings"], expected,
                                 "the standalone window is served a different catalog")
                self.assertEqual(surfaces["catalog"], expected)
                # The panel carries its strings in the page, so the page must contain a
                # word only that language uses.
                marker = expected["status.watching"]
                self.assertIn(marker, surfaces["panel"],
                              "the panel's embedded catalog is in the wrong language")
                self.assertEqual(surfaces["toast"], messages.MESSAGES[language]["setup_done"])

    def test_the_two_languages_actually_differ(self):
        """A guard against the catalogs being accidentally identical."""
        english = interface.STRINGS["en"]
        korean = interface.STRINGS["ko"]
        same = [key for key in english if english[key] == korean[key]]
        # `Windows` and the product's own name are names and stay. Anything else matching
        # is a missed string.
        self.assertEqual(sorted(same), ["group.windows", "tray.title"],
                         "these are identical in both languages")


def _capture(argv, environ):
    """Run the bridge command and return its single line of JSON."""
    import io
    import os
    from unittest.mock import patch
    stream = io.StringIO()
    merged = dict(os.environ)
    merged.update(environ)
    with patch("sys.stdout", stream), patch.dict(os.environ, merged, clear=True):
        controlcli.main(argv)
    return stream.getvalue()


if __name__ == "__main__":
    unittest.main()

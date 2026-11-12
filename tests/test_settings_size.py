"""The settings file holds everything the product's own limits allow, and one it cannot read is never the defaults
(v0.6.23, the second core audit's K1).

Until v0.6.23 the settings were written with every character outside ASCII as a six-byte \\u escape (an emoji twelve),
and a file over 256 KiB was read as the defaults without a word: 28 Korean messages of 2,000 characters on 28
conversations passed it. The watcher then dropped Observe only and every other choice, and the next save wrote the
defaults over the file - every message, the Always and Never lists, the extra Codex homes, quiet hours. Now the file
is written as UTF-8 with the characters themselves, the bound is set from the largest file the limits allow (computed
here, from the limits themselves), a file the product cannot read - too large, or no JSON - is Unreadable to every
reader (the watcher keeps what is in force, or builds nothing; a save is refused; Restore defaults sets it aside), and
the Diagnostics check says so. Its own module: the scenario modules are frozen (tests/neutral.py MODULES).

Scratch settings files only; the policy keys are a stand-in that holds nothing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume import (config, continuation, homefind, homes, managed, notice_kinds, ownvalues,  # noqa: E402
                               projects, settings)
from codex_auto_resume.control import Control, ControlError, policy  # noqa: E402

# A character of each kind a value may hold, the costliest last in each written form: ASCII (1 byte), a quote (2: \"),
# Hangul (3 as UTF-8, 6 escaped), an emoji (4 as UTF-8, 12 escaped: two \u escapes) and a control character (6:
# \u0001, in either form) - which a Custom message takes and a path does not.
CHARACTERS = ("a", '"', "\uac00", "\U0001F600", "\x01")
# A person's own value of each kind (ownvalues.py), the longest spelling of it that could be within its bounds.
OWN_CANDIDATES = ("mon,tue,wed,thu,fri,sat", "23:30", "s9999999", "m9999999", "h9999999", "999999999", "999999999k",
                  "999999999m", "above_999999999k", "mb999999999", ownvalues.UNLIMITED)


def _size(value, ascii_only: bool) -> int:
    return len(json.dumps(value, ensure_ascii=ascii_only).encode("utf-8"))


def _widest(make, field, ascii_only):
    """Of `make(character)` for each character, the value `field` keeps as it is that is longest written."""
    best = None
    for character in CHARACTERS:
        value = make(character)
        if settings.coerce({field: value})[field] != value:
            continue
        if best is None or _size(value, ascii_only) > _size(best, ascii_only):
            best = value
    return best


def _thread(number: int) -> str:
    return str(uuid.UUID(int=number + 1))


def maximal(ascii_only: bool = False) -> dict:
    """Every field at the most its limits allow, in the widest characters each takes, for the written form asked:
    the characters themselves (this version) or every one escaped (what earlier versions wrote)."""
    values = {}
    text = continuation.MAX_CUSTOM_LENGTH
    for name in settings.FIELDS:
        if name == continuation.BY_THREAD_FIELD:
            values[name] = _widest(lambda c: {_thread(n): c * text for n in range(continuation.MAX_CONVERSATIONS)},
                                   name, ascii_only)
        elif settings.is_custom_text(name):
            values[name] = _widest(lambda c: c * text, name, ascii_only)
        elif name == "codex_exe":
            values[name] = _widest(lambda c: "C:\\" + c * (settings.CODEX_EXE_MAX - 3), name, ascii_only)
        elif name == homes.FIELD:
            values[name] = _widest(lambda c: [{"path": "C:\\%d" % n + c * (homes.PATH_MAX - 4),
                                               "alias": "%d" % n + c * (homes.ALIAS_MAX - 1)}
                                              for n in range(homes.MAX_EXTRA)], name, ascii_only)
        elif name == homefind.DISMISSED:
            values[name] = _widest(lambda c: ["C:\\%02d" % n + c * (homes.PATH_MAX - 5)
                                              for n in range(homefind.DISMISSED_MAX)], name, ascii_only)
        elif name in (projects.ALWAYS, projects.NEVER):
            values[name] = projects.format_keys("%064x" % n for n in range(projects.MAX_KEYS))
        elif name == "notice_click":
            values[name] = max(settings.NOTICE_CLICKS, key=len)
        elif name == notice_kinds.FIELD:
            values[name] = ["k%02d" % n + "_" * 29 for n in range(notice_kinds.LIMIT)]
        else:
            choices = [value for value in (settings.RANGES.get(name) or {}).get("choices", [])]
            candidates = choices + (list(OWN_CANDIDATES) if name in settings.OWN else [])
            kept = [value for value in candidates if settings.coerce({name: value})[name] == value]
            default = settings.DEFAULTS[name]
            if isinstance(default, bool):
                values[name] = default
            elif isinstance(default, (int, float)) and name in settings.RANGES:
                values[name] = type(default)(settings.RANGES[name]["max"])
            else:
                values[name] = max(kept, key=lambda value: _size(value, ascii_only)) if kept else default
    return values


class BoundTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "settings.json"

    def test_every_free_field_is_at_its_most_here(self):
        """A field that holds a person's words, a path or a list is built at its limit above, never left at its
        default - so a new one cannot make a file larger than the bound without this test knowing it."""
        free = {name for name in settings.FIELDS
                if name not in settings.RANGES and settings.field_type(name) not in ("boolean", "integer", "number")}
        for ascii_only in (False, True):
            values = maximal(ascii_only)
            self.assertEqual(settings.coerce(values), values, "every value is one the settings keep")
            for name in free:
                self.assertNotEqual(values[name], settings.DEFAULTS[name], name)

    def test_the_largest_file_this_version_writes_fits_with_room(self):
        settings.save(self.path, maximal())
        written = self.path.stat().st_size
        self.assertLessEqual(written * 2, settings.MAX_SETTINGS_BYTES,
                             "%d bytes at most, the bound %d keeps it twice over" % (written, settings.MAX_SETTINGS_BYTES))
        self.assertEqual(settings.read(self.path), maximal(), "read back whole")

    def test_a_file_an_earlier_version_wrote_escaped_still_reads(self):
        """Every character escaped, as json.dump wrote them until v0.6.23 - the Custom messages, the conversations'
        messages, the homes and the folders set aside at their most (an earlier version bound no Codex path, so a
        path of the longest Windows takes stands in for it)."""
        payload = dict(maximal(ascii_only=True), config_version=settings.CONFIG_VERSION)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self.assertLessEqual(self.path.stat().st_size, settings.MAX_SETTINGS_BYTES)
        self.assertEqual(settings.read(self.path), maximal(ascii_only=True))

    def test_the_file_holds_the_characters_themselves(self):
        settings.save(self.path, dict(settings.defaults(), custom_message="\uacc4\uc18d\ud574 \U0001F600"))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("\uacc4\uc18d\ud574 \U0001F600", text)
        self.assertNotIn("\\u", text)

    def test_twenty_eight_korean_messages_keep_every_choice(self):
        """The audit's repro: Observe only on, then a 2,000-character Korean message on one conversation after
        another - all 50 now, and every choice is still read."""
        settings.save(self.path, dict(settings.defaults(), observe_only=True))
        for number in range(continuation.MAX_CONVERSATIONS):
            held = dict(settings.kept(self.path).get(continuation.BY_THREAD_FIELD) or {})
            held[_thread(number)] = "\uac00" * continuation.MAX_CUSTOM_LENGTH
            settings.update(self.path, {continuation.BY_THREAD_FIELD: held})
        values = settings.read(self.path)
        self.assertIs(values["observe_only"], True)
        self.assertEqual(len(values[continuation.BY_THREAD_FIELD]), continuation.MAX_CONVERSATIONS)

    def test_a_save_past_the_bound_is_refused_and_writes_nothing(self):
        settings.save(self.path, dict(settings.defaults(), observe_only=True))
        before = self.path.read_bytes()
        with patch.object(settings, "MAX_SETTINGS_BYTES", 4096), self.assertRaises(settings.SettingsError) as raised:
            settings.update(self.path, {"custom_message": "a" * continuation.MAX_CUSTOM_LENGTH,
                                        "custom_message_timeout": "b" * continuation.MAX_CUSTOM_LENGTH,
                                        "custom_message_server_5xx": "c" * continuation.MAX_CUSTOM_LENGTH})
        self.assertIn("4096", str(raised.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [], "no temporary file is left")

    def test_the_window_reads_under_the_same_bound(self):
        source = (Path(_HERE).parent / "gui" / "SoftTheme.cs").read_text(encoding="utf-8")
        found = re.search(r"const int MaxSettingsBytes = ([0-9 *]+);", source)
        self.assertIsNotNone(found)
        self.assertEqual(math.prod(int(factor) for factor in found.group(1).split("*")), settings.MAX_SETTINGS_BYTES)

    def test_a_codex_path_past_the_longest_windows_takes_is_refused(self):
        with self.assertRaises(settings.SettingsError):
            settings.validate_update({"codex_exe": "C:\\" + "a" * settings.CODEX_EXE_MAX})
        self.assertEqual(settings.validate_update({"codex_exe": "C:\\codex.exe"}), {"codex_exe": "C:\\codex.exe"})


class UnreadableFileTests(unittest.TestCase):
    """A file the product cannot read is never the defaults to a reader that acts, and no save writes over it."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.paths = config.Paths(self.root / "home")
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.state_dir / config.OWNER_MARKER).write_text(config.OWNER_TEXT, encoding="utf-8")
        self.path = self.paths.settings_file
        keys = patch("codex_auto_resume.control.policy.managed_policy", return_value=managed.NONE)
        keys.start()
        self.addCleanup(keys.stop)

    def oversized(self):
        """The person's own settings, Observe only on, grown past the bound."""
        payload = dict(settings.defaults(), observe_only=True, config_version=settings.CONFIG_VERSION,
                       padding="x" * (settings.MAX_SETTINGS_BYTES + 10))
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        return self.path.read_bytes()

    def test_a_file_past_the_bound_is_unreadable_never_the_defaults(self):
        self.oversized()
        with self.assertRaises(settings.Unreadable) as raised:
            settings.read(self.path)
        self.assertEqual(raised.exception.reason, "too_large")
        self.assertFalse(raised.exception.transient)

    def test_no_save_writes_over_a_file_past_the_bound(self):
        before = self.oversized()
        with self.assertRaises(settings.Unreadable) as raised:
            settings.update(self.path, {"theme": "dark"})
        self.assertIn("nothing was saved", str(raised.exception))
        self.assertEqual(self.path.read_bytes(), before, "the person's file is left as it was")

    def test_no_save_writes_over_a_file_that_holds_no_json(self):
        self.path.write_text('{"observe_only": true,', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(settings.SettingsError):
            settings.update(self.path, {"observe_only": False})
        self.assertEqual(self.path.read_bytes(), before)

    def test_the_dashboard_save_is_refused_in_words_a_person_reads(self):
        before = self.oversized()
        control = Control(self.paths)
        with self.assertRaises(ControlError) as raised:
            control.update_settings({"theme": "dark"})
        self.assertIn("Restore defaults", str(raised.exception))
        with self.assertRaises(ControlError):
            control.set_conversation_message(_thread(1), "keep going")
        self.assertEqual(self.path.read_bytes(), before)

    def test_restore_defaults_sets_the_file_aside_first(self):
        before = self.oversized()
        control = Control(self.paths)
        saved = control.restore_defaults()
        self.assertEqual(saved["observe_only"], False, "the defaults, as the person asked")
        aside = sorted(self.paths.state_dir.glob(policy.SET_ASIDE_GLOB))
        self.assertEqual(len(aside), 1, aside)
        self.assertEqual(aside[0].read_bytes(), before, "the unreadable file is kept, byte for byte")
        self.assertIn(aside[0], self.paths.owned_state_files(), "and an uninstall that purges takes it")
        self.assertEqual(settings.read(self.path), settings.defaults())

    def test_the_watcher_keeps_what_it_has_and_builds_nothing_on_the_defaults(self):
        from codex_auto_resume import app
        self.oversized()
        instance = app.App(self.paths, codex_home=self.root, enable_logging=False)
        self.assertIsNone(instance._read_settings(), "no settings, never the defaults")
        with self.assertRaises(settings.Unreadable):
            instance.engine(None)

    def test_the_diagnostics_check_says_so(self):
        from codex_auto_resume import checkup
        self.oversized()
        control = Control(self.paths)
        with patch.object(checkup, "_presence", return_value={"route": None, "do_not_disturb": None,
                                                               "app_allowed": None}):
            result = checkup.run(control, sources=[], locale="en")
        self.assertIn("settings file", result["lines"][1])
        self.assertIn("too_large", result["lines"][1])


if __name__ == "__main__":
    unittest.main()

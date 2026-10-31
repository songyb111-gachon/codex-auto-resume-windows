"""The advanced edition's windows with a list wear the product's icon, as the standard edition's do (v0.6.20 final, A7).

v0.6.15 settled it (tests/test_gui_dialog_icons.py): the small dialogs - a question, a message to write, a name to give -
hide their icon, and the windows with a list - Timeline, the log, Install another version... - take the Dashboard's own
(`dialog.Icon = Icon`). The advanced edition's three windows of that kind hid theirs: the v0.6.20 final's live acceptance
(2026-11-01) found "See an example..." with no icon in its title bar while Timeline had one, and Find a conversation and
Follow-through were the same. Each takes the window's icon now; the small dialogs stay as they were.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted(list((ROOT / "gui").glob("*.cs")) + list((ROOT / "advanced" / "gui").glob("*.cs")))
MEMBER = re.compile(r"\n        (?:private|internal|protected|public)\b[^\n]*\(")


def builder(path: Path, name: str) -> str:
    """The body of the method `name` builds its dialog in, up to the next member."""
    text = path.read_text(encoding="utf-8")
    start = re.search(r"\n        (?:private|internal) Form %s\(" % re.escape(name), text)
    if start is None:
        raise AssertionError("%s has no %s" % (path.name, name))
    rest = text[start.end():]
    after = MEMBER.search(rest)
    return rest[:after.start()] if after else rest


def dialogs() -> list:
    """(source, line, builder text) of every dialog the window builds."""
    found = []
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        for made in re.finditer(r"\b(?:var|Form)\s+dialog\s*=\s*new Form\(\)", text):
            rest = text[made.end():]
            after = MEMBER.search(rest)
            found.append((path.relative_to(ROOT).as_posix(), text[:made.start()].count("\n") + 1,
                          rest[:after.start()] if after else rest))
    return found


class ListDialogIconTests(unittest.TestCase):
    def test_the_advanced_windows_with_a_list_take_the_windows_icon(self):
        for source, name in (("AdvancedExamples.cs", "BuildExample"), ("AdvancedFind.cs", "BuildFind"),
                             ("AdvancedFollow.cs", "BuildFollow")):
            with self.subTest(source=source):
                body = builder(ROOT / "advanced" / "gui" / source, name)
                self.assertIn("dialog.Icon = Icon;", body)
                self.assertNotIn("dialog.ShowIcon = false;", body)

    def test_every_dialog_with_a_list_on_its_card_wears_the_icon(self):
        listed = [(source, line) for source, line, body in dialogs() if "DialogListCard(" in body]
        self.assertGreaterEqual(len(listed), 4, "Timeline, the log, Install another version, Find a conversation, ...")
        for source, line, body in dialogs():
            if "DialogListCard(" not in body:
                continue
            with self.subTest(source=source, line=line):
                self.assertIn("dialog.Icon = Icon;", body)

    def test_a_window_either_wears_the_icon_or_hides_it_never_both(self):
        for source, line, body in dialogs():
            with self.subTest(source=source, line=line):
                self.assertNotEqual("dialog.Icon = Icon;" in body, "dialog.ShowIcon = false;" in body)


if __name__ == "__main__":
    unittest.main()

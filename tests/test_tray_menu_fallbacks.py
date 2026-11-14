"""The icon's menu says what the English catalog says when it has no catalog (v0.6.23, the reachability audit's M2).

Show what is waiting's fallback was "Show what is waiting", without the "({n})" the catalog's sentence has, so the
`.replace("{n}", ...)` after it changed nothing and a menu built with no words had no count. Every literal fallback
the menu writes (ui/tray/menu.py, `strings.get("key", "...")`) is now the English catalog's sentence for its key.

Pure: menu_items as a value, and the module's source as text; no window.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

from codex_auto_resume import l10n
from codex_auto_resume.ui.tray import menu as tray_menu

MENU = Path(tray_menu.__file__)
NOW = 1_800_000_000.0


class MenuFallbackTests(unittest.TestCase):
    def test_show_what_is_waiting_has_its_count_with_no_catalog(self):
        """Fails with the fallback reverted: the item reads "Show what is waiting", no count."""
        items = tray_menu.menu_items({"enabled": True, "waiting": 2, "running": 1}, {}, NOW, pending=True)
        shown = [item["text"] for item in items if item and item["id"] == tray_menu.MENU_PENDING]
        self.assertEqual(shown, [l10n.catalog("en")["menu.pending"].replace("{n}", "3")])
        self.assertEqual(shown, ["Show what is waiting (3)"])

    def test_every_fallback_of_the_menu_is_the_english_sentence(self):
        english = l10n.catalog("en")
        literal = r'"(?:[^"\\\r\n]|\\.)*"'
        found = re.findall(r'strings\.get\(\s*"([\w.\-]+)"\s*,\s*(%s)\s*\)' % literal, MENU.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(found), 6)
        for key, said in found:
            with self.subTest(key=key):
                self.assertEqual(ast.literal_eval(said), english[key])


if __name__ == "__main__":
    unittest.main()

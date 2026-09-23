"""The icon is one module and one class, however many files they are written in.

v0.6.10-alpha split `tray.py` - 1,171 lines - into `tray/`, eleven files behind the name the
rest of the product already used. `Tray` is composed from five mixins, the way `Store` and
`Engine` are, so no call site changed.

What every front is held to - it gives every name it gave, no import of it names a module that
is not there, a patch on it must reach something outside it - is in `tests/test_reexports.py`
and `tests/test_names.py`, for all of them at once. What is here is the icon's own shape: the
eleven files, the order they layer in, which of them may call Windows, and that no two mixins
define the same method.

That last one is the failure composition brings with it. Two mixins defining the same name is
not an error; it is a silent choice made by the order they are listed in, and moving a method
between files would change which one wins.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import re
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import srcscan  # noqa: E402
from codex_auto_resume import tray  # noqa: E402
from codex_auto_resume.tray import animation, cards, clicks, icon, menu, stored  # noqa: E402

PACKAGE = "codex_auto_resume.tray"

# The eleven, in the order `__init__` imports them, which is their dependency order.
MODULES = ("words", "model", "motion", "win32", "menu", "stored", "cards", "clicks",
           "animation", "icon", "dashboard")

# The four that reach Win32, directly or through `win32`. The other seven are why the icon's
# frames can be drawn with no icon, no window and no shell.
CALLS_WINDOWS = ("win32", "menu", "animation", "icon")

MIXINS = (menu.MenuMixin, stored.StoredMixin, cards.CardsMixin, clicks.ClicksMixin,
          animation.AnimationMixin)

# What `Tray` has, as the one class had it. Thirty-nine methods, counted the day the file was
# split; one added or taken away is a decision, and this is where it is made.
METHODS = {
    "__init__", "_act", "_adopt_reduce_motion", "_adopt_settings", "_animate",
    "_build_frames_later", "_card_look", "_create", "_data", "_double_click", "_drop_cards",
    "_failure_seen", "_failure_unseen", "_frame_for", "_frames_built", "_hide_popup",
    "_host_cards", "_load_icon", "_menu", "_notify", "_notify_icon", "_observe", "_overflowed",
    "_popup_broke", "_popup_for_click", "_refresh", "_run", "_select", "_session_changed",
    "_set_version", "_shown", "_stored_settings", "_sync_motion", "_theme_menu",
    "_watch_session", "_wndproc", "set_strings", "start", "stop", "update",
}


def siblings(module: str) -> set:
    """The modules of this package that `module` imports from, at any depth of dot."""
    path = srcscan.modules()[PACKAGE + "." + module]
    found = set()
    for node in ast.walk(srcscan.package_asts()[path]):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in MODULES:
            found.add(node.module)
    return found


class ShapeTests(unittest.TestCase):
    def test_the_eleven_are_all_there_and_nothing_else_is(self):
        listed = {srcscan.module_name(path).split(".")[-1] for path in srcscan.files_of(PACKAGE)}
        self.assertEqual(listed, set(MODULES) | {"tray"})

    def test_each_file_uses_only_what_is_above_it(self):
        """Not decoration: it is what says the icon has no cycle in it, and how a reader knows
        that opening `words.py` will not send them to `icon.py`."""
        above = set()
        for module in MODULES:
            with self.subTest(module):
                self.assertLessEqual(siblings(module), above, "it uses a file below it")
            above.add(module)

    def test_the_order_in_the_file_is_the_order_here(self):
        """The front names the seven files that give a name, in this order.

        The other four hold a mixin and nothing else, so there is nothing for the front to
        re-export from them; they are loaded because `icon.py` composes `Tray` out of them.
        """
        source = srcscan.read(srcscan.modules()[PACKAGE])
        named = re.findall(r"^from \.(\w+) import", source, re.M)
        self.assertEqual(named, [module for module in MODULES if module in named])
        self.assertEqual([module for module in MODULES if module not in named],
                         ["stored", "cards", "clicks", "animation"])

    def test_only_the_four_call_windows(self):
        for module in MODULES:
            with self.subTest(module):
                text = srcscan.read(srcscan.modules()[PACKAGE + "." + module])
                touches = "ctypes" in text or "win32" in siblings(module)
                self.assertEqual(touches, module in CALLS_WINDOWS)

    def test_the_process_is_started_in_one_file(self):
        holders = {name for name in MODULES
                   if "subprocess" in srcscan.read(srcscan.modules()[PACKAGE + "." + name])}
        self.assertEqual(holders, {"dashboard"})


class CompositionTests(unittest.TestCase):
    def test_every_method_belongs_to_exactly_one_mixin(self):
        owners: dict[str, list[str]] = {}
        for mixin in MIXINS:
            for name, value in vars(mixin).items():
                if inspect.isfunction(value):
                    owners.setdefault(name, []).append(mixin.__name__)
        self.assertEqual({name: where for name, where in owners.items() if len(where) > 1}, {})

    def test_the_class_has_the_methods_it_had(self):
        have = {name for name, value in inspect.getmembers(tray.Tray, inspect.isfunction)
                if value.__module__.startswith(PACKAGE)}
        self.assertEqual(have, METHODS)

    def test_the_mixins_are_named_in_the_order_the_front_lists_them(self):
        """`Tray`'s bases in MRO order, so which mixin wins a name is written down, not chanced."""
        self.assertEqual([base.__name__ for base in tray.Tray.__bases__],
                         [mixin.__name__ for mixin in MIXINS])
        self.assertIs(tray.Tray.__mro__[-1], object)

    def test_the_composition_is_in_icon_not_in_the_front(self):
        self.assertEqual(tray.Tray.__module__, PACKAGE + ".icon")
        self.assertIn("class Tray(", srcscan.read(srcscan.modules()[PACKAGE + ".icon"]))
        self.assertNotIn("class Tray(", srcscan.read(srcscan.modules()[PACKAGE]))

    def test_each_mixin_holds_the_methods_its_file_is_named_for(self):
        """Not vacuous: a method moved to another file would show up here before anywhere else."""
        for mixin, expected in ((menu.MenuMixin, {"_menu", "_act", "_theme_menu"}),
                                (cards.CardsMixin, {"_host_cards", "_card_look", "_drop_cards"}),
                                (stored.StoredMixin, {"_stored_settings", "_adopt_settings",
                                                      "_adopt_reduce_motion"})):
            with self.subTest(mixin.__name__):
                have = {name for name, value in vars(mixin).items() if inspect.isfunction(value)}
                self.assertEqual(have, expected)
        self.assertIs(icon.Tray, tray.Tray)


if __name__ == "__main__":
    unittest.main()

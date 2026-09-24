"""The control layer is one module and one class, however many files they are written in.

v0.6.10-alpha split `control.py` - 1,083 lines - into `control/`, ten files behind the name
every surface already used. `Control` is composed from eight mixins, the way `Store`, `Engine`
and `Tray` are, so no call site changed.

What every front is held to - it gives every name it gave, no import of it names a module that
is not there, a patch on it must reach something outside it - is in `tests/test_reexports.py`
and `tests/test_names.py`. What is here is this layer's own shape.

The two rules worth reading for what they say rather than what they check:

* **No two mixins define the same method.** That is not an error in Python; it is a silent
  choice made by the order the bases are listed in, and moving a method between files would
  change which one wins.
* **`actions.py` sends nothing.** The layer's whole safety claim is that a person asking for
  something changes a flag, a schedule or a budget, and that the watcher remains the only
  thing that hands anything to Codex. `preview.py` builds the message and does not send it,
  which is why it is its own file and not part of `actions`.
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
from codex_auto_resume import control  # noqa: E402
from codex_auto_resume.control import (actions, codexstart, layer, policy,  # noqa: E402
                                       preview, records, seen, state, watcher)

PACKAGE = "codex_auto_resume.control"

# The ten, in the order `__init__` imports them, which is their dependency order - and
# `wire`, the eleventh, which `__init__` does not import: the shapes the layer hands every
# surface, written down as types, imported by the tests that hold them to the goldens and by
# nothing that runs.
MODULES = ("errors", "state", "seen", "policy", "records", "preview", "actions",
           "codexstart", "watcher", "layer", "wire")

MIXINS = (state.StateMixin, seen.SeenMixin, policy.SettingsMixin, records.RecordsMixin,
          preview.PreviewMixin, actions.ActionsMixin, codexstart.CodexStartMixin,
          watcher.WatcherMixin)

# What `Control` has, as the one class had it. Thirty-eight methods, counted the day the file
# was split; one added or taken away is a decision, and this is where it is made.
METHODS = {
    "__init__", "_confirm_watcher", "_described", "_launch_watcher", "_newest_failure", "_open",
    "_seen_file", "_start_for_codex", "_watcher", "acknowledge_failure", "cancel_all_pending",
    "cancel_interruption", "cancel_thread", "clear_history", "describe_settings",
    "failure_seen_at", "failure_unseen", "get_settings", "get_status", "history",
    "list_pending", "preview_continuation", "request_retry_now", "reset_recovery_budget",
    "restore_defaults", "set_enabled", "set_interruption_recovery", "set_startup_enabled",
    "set_thread_enabled", "settings_path", "start_for_codex", "start_watcher",
    "startup_enabled", "statistics", "stop_watcher", "timeline", "update_settings",
    "watcher_running",
}


def siblings(module: str) -> set:
    path = srcscan.modules()[PACKAGE + "." + module]
    found = set()
    for node in ast.walk(srcscan.package_asts()[path]):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in MODULES:
            found.add(node.module)
    return found


class ShapeTests(unittest.TestCase):
    def test_the_eleven_are_all_there_and_nothing_else_is(self):
        listed = {srcscan.module_name(path).split(".")[-1] for path in srcscan.files_of(PACKAGE)}
        self.assertEqual(listed, set(MODULES) | {"control"})

    def test_each_file_uses_only_what_is_above_it(self):
        above = set()
        for module in MODULES:
            with self.subTest(module):
                self.assertLessEqual(siblings(module), above, "it uses a file below it")
            above.add(module)

    def test_the_order_in_the_file_is_the_order_here(self):
        source = srcscan.read(srcscan.modules()[PACKAGE])
        named = re.findall(r"^from \.(\w+) import", source, re.M)
        self.assertEqual(named, [module for module in MODULES if module in named])

    def test_nothing_here_is_called_settings(self):
        """`codex_auto_resume/settings.py` is the module this layer calls. A `control/
        settings.py` beside it would make every `from .. import settings` in the package a
        puzzle for a reader, whatever Python resolves it to - so the file is `policy.py`."""
        self.assertNotIn("settings", MODULES)
        self.assertFalse((Path(srcscan.modules()[PACKAGE]).parent / "settings.py").exists())
        self.assertIn("settings", srcscan.read(srcscan.modules()[PACKAGE + ".policy"]))

    def test_the_process_is_launched_in_one_file(self):
        holders = {name for name in MODULES
                   if "subprocess" in srcscan.read(srcscan.modules()[PACKAGE + "." + name])}
        self.assertEqual(holders, {"watcher"})


class CompositionTests(unittest.TestCase):
    def test_every_method_belongs_to_exactly_one_mixin(self):
        owners: dict[str, list[str]] = {}
        for mixin in MIXINS:
            for name, value in vars(mixin).items():
                if inspect.isfunction(value):
                    owners.setdefault(name, []).append(mixin.__name__)
        self.assertEqual({name: where for name, where in owners.items() if len(where) > 1}, {})

    def test_the_class_has_the_methods_it_had(self):
        have = {name for name, value in inspect.getmembers(control.Control, inspect.isfunction)
                if value.__module__.startswith(PACKAGE)}
        self.assertEqual(have, METHODS)

    def test_the_mixins_are_named_in_the_order_written_down(self):
        self.assertEqual([base.__name__ for base in control.Control.__bases__],
                         [mixin.__name__ for mixin in MIXINS])

    def test_the_composition_is_in_layer_not_in_the_front(self):
        self.assertEqual(control.Control.__module__, PACKAGE + ".layer")
        self.assertIs(layer.Control, control.Control)
        self.assertNotIn("class Control(", srcscan.read(srcscan.modules()[PACKAGE]))


class SafetyTests(unittest.TestCase):
    """What the split must not have loosened."""

    def imports_of(self, module: str) -> set:
        return {entry.target for entry in
                srcscan.imports(srcscan.modules()[PACKAGE + "." + module])}

    def test_only_preview_reaches_what_writes_a_message(self):
        """`continuation` builds the text the watcher sends. One file of this layer may import
        it, and that file's whole point is that it returns the text instead of handing it
        anywhere. Asked as an import rather than as a word, because half these files mention
        continuations in prose and none of the others may call one."""
        readers = {name for name in MODULES
                   if "codex_auto_resume.continuation" in self.imports_of(name)}
        self.assertEqual(readers, {"preview"})

    def test_the_actions_file_reaches_no_backend(self):
        """The file that holds every change a person can ask for imports nothing that could
        carry one to Codex."""
        for forbidden in ("continuation", "source", "engine"):
            with self.subTest(forbidden):
                self.assertNotIn("codex_auto_resume." + forbidden, self.imports_of("actions"))
        self.assertNotIn("subprocess", self.imports_of("actions"))
        # It does reach `windows`, for one name: `WakeEvent`, so that a change a person just
        # made is looked at on the next tick rather than in a minute. Waking the watcher is
        # not sending anything, and it is the only thing taken from there.
        taken = set()
        for node in ast.walk(srcscan.package_asts()[srcscan.modules()[PACKAGE + ".actions"]]):
            if isinstance(node, ast.ImportFrom) and node.module == "windows":
                taken |= {alias.name for alias in node.names}
        self.assertEqual(taken, {"WakeEvent"})

    def test_every_refusal_code_is_raised_from_the_file_that_owns_the_words(self):
        """`errors.py` holds the codes and the two refusal tables; a file that raises without
        them would be inventing a refusal no catalogue has a sentence for."""
        source = srcscan.read(srcscan.modules()[PACKAGE + ".errors"])
        self.assertIn("ERROR_CODES", source)
        self.assertIn("FALLBACK_CODE", source)
        for name in MODULES:
            text = srcscan.read(srcscan.modules()[PACKAGE + "." + name])
            if "ControlError(" in text and name != "errors":
                with self.subTest(name):
                    self.assertIn("from .errors import", text)


if __name__ == "__main__":
    unittest.main()

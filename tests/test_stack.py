"""Where every module goes when the core is Rust, and what may call what once it is.

`docs/ROADMAP.md` names the stack v0.6.13 is planned to arrive at: the Windows interface in
C# and the core in Rust, in eight parts -

    Watcher · Recovery engine · Classifier / Policy · State machine ·
    Scheduler / Reconciliation · Persistence · Codex adapters · Control / MCP backend

and the rule for getting there is "replace the implementation, not the behavior". That rule is
only keepable if each part's behaviour is in one place first. A module that does two parts' work
has to be read twice, ported twice and kept in step twice, and the second port is where the
behaviour quietly changes.

So this places every module on exactly one item, and holds the placement three ways:

  * `HOMELESS` - items with no package of their own. Every one is a port that would begin by
    gathering code out of several files.
  * `STRADDLING` - packages whose modules are not all one item.
  * `DOUBLE` - single modules that do two items' work, each with what the second half is.

All three only shrink. An entry that no longer holds fails, the same discipline
`tests/test_layers.py` uses for its exceptions, so the lists cannot go stale while the tree
moves under them. And `EDGES` is the crate graph: which item may call which, as the imports
actually run today. A call this file does not allow is a call the Rust side would have to
invent an interface for, found here rather than during the port.

This is not `test_layers.py` a second time. Layers are about direction - nothing may call
upwards - and hold today. Items are about ownership: which binary this code ends up inside.
A module can sit in the right layer and still belong to two items, and `windows.py` did.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import srcscan  # noqa: E402

PACKAGE = srcscan.PACKAGE

# The Rust core, as the roadmap names its parts.
RUST = ("watcher", "engine", "policy", "machine", "scheduler", "store", "codex", "control")
# The Windows interface, which stays native and becomes C#.
NATIVE = ("tray", "popup", "notifications")
# What is neither: the words, the palette, the platform calls and the deployment helpers. Each
# is either generated into both sides already, or a thin wrapper over something the host has.
SHARED = ("words", "brand", "platform", "config")

ITEMS = RUST + NATIVE + SHARED


def _q(name: str) -> str:
    # "" is the package itself; `auto_resume` is the command's entry script, which sits beside
    # the package rather than inside it and is named as it is spelled.
    return PACKAGE if name == "" else name if name == "auto_resume" else PACKAGE + "." + name


# Every module, placed. A new module is given an item here before anything else.
ITEM = {_q(name): item for item, names in {
    "watcher": ("app", "runtime", "runtime.app", "runtime.loop", "runtime.toasts"),
    "engine": ("engine", "engine.announce", "engine.detect", "engine.dispatch", "engine.freshness",
               "engine.options", "engine.outcome"),
    "policy": ("failures", "reasons", "settings", "continuation", "openstate", "domain.gates",
               # what may be done at a tier, and with whose word: policy, not registry data
               "compat.permits"),
    "machine": ("machine", "domain", "domain.errors", "domain.ids", "domain.public",
                "domain.states", "domain.vocabulary"),
    "scheduler": ("engine.reconcile",),
    "store": ("store", "store.actions", "store.claims", "store.columns", "store.downgrade",
              "store.errors", "store.journal", "store.legacy", "store.migrations", "store.policy",
              "store.records", "store.reporting", "store.schema", "store.session",
              "store.validate", "store.watcher"),
    "codex": ("codex", "codex.appserver", "codex.errors", "codex.history", "codex.labels",
              "codex.pairing", "codex.paths", "codex.payload", "codex.schema", "codex.transport",
              "codex.usage", "codex.values", "compat", "compatio", "windows",
              "compat.model", "compat.standing", "compat.report", "compat.files", "compat.cache", "compat.probes", "compat.views", "compat.evaluator",
              # v0.6.10: what others report, read beside the registry and never by it.
              "compat.reported"),
    "control": ("control", "control.actions", "control.codexstart", "control.errors",
                "control.layer", "control.policy", "control.preview", "control.records",
                "control.seen", "control.state", "control.watcher", "control.wire",
                "auto_resume", "cli", "controlcli", "diagnostics",
                "commands", "commands.base", "commands.install", "commands.records",
                "commands.status", "commands.watcher",
                "mcp", "mcp.panel", "mcp.server", "mcp.tools", "mcpserver"),
    "tray": ("ui", "ui.tray", "ui.tray.animation", "ui.tray.cards", "ui.tray.clicks",
             "ui.tray.dashboard", "ui.tray.icon", "ui.tray.menu", "ui.tray.model",
             "ui.tray.motion", "ui.tray.stored", "ui.tray.win32", "ui.tray.words", "tray_place"),
    "popup": ("ui.popup", "ui.popup.elevation", "ui.popup.fonts", "ui.popup.gdiplus",
              "ui.popup.layout", "ui.popup.model", "ui.popup.motion", "ui.popup.placement",
              "ui.popup.renderer", "ui.popup.theme", "ui.popup.win32", "ui.popup.window",
              "ui.popup.words", "ui.popup.messages"),
    "notifications": ("notice_card", "notice_presence", "notice_window", "notifier", "notify",
                      "ui.card", "ui.card.win32", "ui.card.surfaces", "ui.card.card", "ui.card.stack"),
    "words": ("l10n", "messages", "interface", "ui.words"),
    "brand": ("brand", "brand.checkbox", "brand.colour", "brand.css", "brand.design", "brand.elevation",
              "brand.light", "brand.mark", "brand.motion", "brand.scale", "brand.tokens"),
    "platform": ("win", "win.dll", "win.homelock", "win.inventory", "win.kernel", "win.sync",
                 "pwsh", "shortcut", "startup"),
    "config": ("", "config", "logbook"),
}.items() for name in names}


# Items with no package of their own: their code is spread over modules placed elsewhere, so
# the port begins by gathering it. Only shrinks.
HOMELESS = {
    "engine": "engine/ is the recovery engine's in every file but one, and that one is the "
              "scheduler's - so taking the package takes two items, and the engine has no "
              "package that is only its own",
    "scheduler": "engine/reconcile.py is what became of a send; the backoff ladders, the poll "
                 "intervals, the due times and the cooldowns are in engine/, domain/ and "
                 "settings.py, and no file gathers them",
    "policy": "failures.py classifies and reasons.py names, but what may be sent, when, and "
              "under which edition is decided across settings.py, control/policy.py and the "
              "domain/gates.py",
    "machine": "domain/ is the state machine in every file but one, and that one - the gates "
               "a record passes before anything is sent - is the classifier's; so taking the "
               "package takes two items",
}

# Packages whose modules are not all one item. Only shrinks.
STRADDLING = {
    "compat": "compat/permits.py is the classifier's policy - what may be done at a tier - and "
              "every other file of it is the registry the Codex adapter reads",
    "domain": "domain/gates.py is the classifier's policy, not the state machine's",
    "engine": "engine/reconcile.py is the scheduler's, not the recovery engine's",
    "ui": "ui/ holds the icon and the popup, which are two of the C# side's parts, and "
          "ui/words.py, which is neither",
}

# Single modules doing two items' work, and what the second half is. Only shrinks.
DOUBLE = {
}


def short(name: str) -> str:
    if name.startswith(PACKAGE + "."):
        return name[len(PACKAGE) + 1:]
    return "" if name == PACKAGE else name


def packages() -> dict:
    """Every package under the product, by dotted name, to the items its modules are on.

    A package is any name another module is written inside: `ui`, `ui.popup`, `store`. Asked at
    every depth rather than only at the top, because `ui/` holds two of the C# side's parts and
    `ui/popup/` holds one - so the popup has a home and `ui` is a straddle, which is both true.
    """
    found = {}
    names = [short(module) for module in ITEM if short(module)]
    for name in names:
        for other in names:
            if other.startswith(name + "."):
                found.setdefault(name, set()).add(ITEM[_q(other)])
                found[name].add(ITEM[_q(name)])
    return found


def edges() -> dict:
    """(item, item) -> the module edges that make it, for every import this product runs."""
    found: dict = {}
    for module, path in srcscan.modules().items():
        for entry in srcscan.imports(path):
            if not entry.internal or entry.target not in srcscan.modules() or entry.target == module:
                continue
            pair = (ITEM.get(module), ITEM.get(entry.target))
            if pair[0] is None or pair[1] is None or pair[0] == pair[1]:
                continue
            found.setdefault(pair, set()).add((short(module), short(entry.target)))
    return found


# Which item calls which, as the imports run today. Read as the crate graph the Rust side would
# be built with: an edge here is an interface that has to exist across a binary boundary. The
# list holds both ways - a call it does not allow fails, and an edge nothing makes any more
# fails too, so it says what the tree is rather than what it once was.
EDGES = {
    ("watcher", "codex"), ("watcher", "config"), ("watcher", "control"), ("watcher", "engine"),
    ("watcher", "notifications"), ("watcher", "policy"), ("watcher", "popup"),
    ("watcher", "store"), ("watcher", "tray"), ("watcher", "words"),

    ("engine", "codex"), ("engine", "machine"), ("engine", "policy"), ("engine", "scheduler"),
    ("engine", "words"),

    ("scheduler", "machine"), ("scheduler", "policy"),

    ("policy", "codex"), ("policy", "machine"), ("policy", "store"), ("policy", "words"),

    ("machine", "policy"),

    ("store", "machine"), ("store", "policy"),

    # v0.6.10-alpha: windows.py was both of these, so this call was inside one module and
    # invisible. Splitting it is what made the adapter's use of the platform an edge.
    ("codex", "config"), ("codex", "machine"), ("codex", "platform"), ("codex", "policy"),

    ("control", "brand"), ("control", "codex"), ("control", "config"), ("control", "machine"),
    ("control", "notifications"), ("control", "platform"), ("control", "policy"),
    ("control", "store"), ("control", "tray"), ("control", "watcher"), ("control", "words"),

    ("tray", "brand"), ("tray", "machine"), ("tray", "notifications"), ("tray", "platform"),
    ("tray", "popup"), ("tray", "words"),

    ("popup", "brand"), ("popup", "machine"), ("popup", "platform"), ("popup", "policy"),
    ("popup", "words"),

    ("notifications", "brand"), ("notifications", "machine"), ("notifications", "platform"),
    ("notifications", "policy"), ("notifications", "popup"), ("notifications", "tray"),
    ("notifications", "words"),

    ("words", "machine"),

    # The one refusal both the adapter and the platform under it raise, which carries a static
    # reason code and is therefore a domain value.
    ("platform", "machine"),

    ("config", "machine"), ("config", "policy"),
}

# The edges above that the port must not carry across, and what each one is. An edge that is
# gone fails this test, so the list only shrinks - the same discipline as HOMELESS above.
UNWANTED = {
    ("machine", "policy"): "the `machine` front re-exports domain/gates.py, so the name that "
                           "means the state machine hands out the classifier's gates too; it is "
                           "what is left of machine.py having been both",
    ("config", "machine"): "logbook.py reads domain.ids and machine to write a reason code; the "
                           "log is below everything and should be handed the words",
    ("config", "policy"): "config.py reads settings for the home directory, which is the one "
                          "setting that has to be known before settings can be loaded",
    ("watcher", "popup"): "app.py builds the popup's model to decide whether a card is worth "
                          "raising - a C#-side question answered on the Rust side",
    ("notifications", "tray"): "the card is hosted on the icon's thread, so the two Windows "
                               "surfaces know about each other; both are C#'s",
    ("control", "watcher"): "the command line runs every command through the watcher's App - "
                            "commands/base.py builds it - and takes its exit codes from there, so "
                            "the command line, placed on control, reaches the composition root",
    ("control", "tray"): "commands/watcher.py's `activate` opens the Dashboard through the icon's "
                         "helper (ui.tray), for a click on a notification",
    ("control", "notifications"): "commands/watcher.py parses a toast's activation and "
                                  "commands/install.py registers the notification protocol, both "
                                  "through notify",
}


class PlacementTests(unittest.TestCase):
    def test_every_module_is_on_one_item(self):
        modules = set(srcscan.modules())
        self.assertEqual(sorted(short(name) for name in modules - set(ITEM)), [],
                         "place the new module on a stack item")
        self.assertEqual(sorted(short(name) for name in set(ITEM) - modules), [],
                         "the table names a module that is gone")

    def test_every_item_is_one_the_roadmap_names(self):
        self.assertEqual(sorted(set(ITEM.values())), sorted(ITEMS),
                         "an item nothing is placed on, or one the roadmap does not name")

    def test_the_items_with_no_package_are_the_listed_ones(self):
        """A package is an item's home only when every module in it is that item's.

        `engine/` is not the scheduler's home although `engine/reconcile.py` is the scheduler's:
        a port that took the package would take the recovery engine with it.
        """
        homed = {items.copy().pop() for items in packages().values() if len(items) == 1}
        homeless = sorted(set(RUST + NATIVE) - homed)
        self.assertEqual(homeless, sorted(HOMELESS),
                         "an item gained or lost a package of its own; update HOMELESS")

    def test_the_packages_that_straddle_are_the_listed_ones(self):
        straddling = sorted(name for name, items in packages().items() if len(items) > 1)
        self.assertEqual(straddling, sorted(STRADDLING),
                         "a package gained or lost a second item; update STRADDLING")

    def test_each_module_said_to_do_two_items_work_is_still_there(self):
        """And still holds code. A module split into a front keeps its name and holds nothing,
        so an entry for it would go on claiming a straddle that is gone - which is how
        `machine` stayed on this list for a commit after domain/ took it apart."""
        modules = {short(name) for name in srcscan.modules()}
        for name in sorted(DOUBLE):
            with self.subTest(name):
                self.assertIn(name, modules, "DOUBLE names a module that is gone")
                tree = srcscan.package_asts()[srcscan.modules()[_q(name)]]
                self.assertTrue(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                      ast.ClassDef)) for node in tree.body),
                                "DOUBLE names a module that is only a front now")


class CrateGraphTests(unittest.TestCase):
    def test_no_item_calls_one_this_file_does_not_allow(self):
        found = edges()
        unexpected = sorted(pair for pair in found if pair not in EDGES)
        detail = "\n".join(
            "%s -> %s: %s" % (a, b, ", ".join("%s -> %s" % edge for edge in sorted(found[(a, b)])[:4]))
            for a, b in unexpected)
        self.assertEqual(unexpected, [], "a call across items that no crate edge allows\n" + detail)

    def test_every_allowed_call_is_one_that_happens(self):
        """An edge nothing makes is an interface the port would build and nobody would use."""
        found = set(edges())
        self.assertEqual(sorted(EDGES - found), [],
                         "EDGES allows a call nothing makes any more")

    def test_the_edges_the_port_must_not_carry_are_the_listed_ones(self):
        found = set(edges())
        self.assertEqual(sorted(set(UNWANTED) - found), [],
                         "an unwanted edge is gone; take it off UNWANTED")
        for pair in sorted(UNWANTED):
            with self.subTest("%s -> %s" % pair):
                self.assertIn(pair, EDGES, "an unwanted edge must be an edge")

    def test_persistence_calls_nothing_that_is_not_the_domain(self):
        """The one item with a clean boundary today, and the shape every other one is aimed at.

        `policy` here is `settings`, for the one value the store is given rather than told: how
        long a claim may be held. `machine` is the states themselves.
        """
        called = {pair[1] for pair in edges() if pair[0] == "store"}
        self.assertEqual(sorted(called), ["machine", "policy"],
                         "the store reached past the domain")


if __name__ == "__main__":
    unittest.main()

"""The package's layers, and the one direction its imports point.

    domain          pure rules: failures, reasons, the status mapping
      |
    policy, i18n    settings, the continuation builder, catalogs, paths and version, the log
      |
    adapters        the store, Codex's files and processes, Windows, the compatibility registry
      |
    engine          decides and schedules; reaches Codex and the store through what it is given
      |
    control         the one layer a front end calls
      |
    front ends      the command line, the bridge, the MCP server and panel, the runtime, the icon,
                    the popup and the card

A module may import from its own layer or from any layer below it, never from one above.
The rules below are the v0.6.5 target (the modularization plan, section 3.1). Those that
already hold are enforced as they stand. Those that do not hold yet are enforced too, with
the real edges that break them today listed as exceptions - and an exception that no longer
exists fails the test, so the lists only shrink as the split lands.

Every import is read from the source through srcscan, including the ones inside functions:
a lazy import is still an edge, and a cycle through one is still a cycle the day someone
moves it to the top of a file.

A role - the store, Codex's readers, Windows, the UI, the MCP server - is a set of module
names, and a module belongs to it when it is one of them *or lies inside one of them*. So
`store` covers `store/claims.py` the day `store.py` becomes a package, and the packages the
split creates (`codex/`, `win/`, `ui/`, `mcp/`) are in their roles before they exist. Matched
by exact name instead, the engine could import `codex.history` once `source.py` had moved
there, and the edge would drop off the exception list while it still existed.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

PACKAGE = srcscan.PACKAGE
ORDER = ("domain", "policy", "adapters", "engine", "control", "front")


def _q(name):
    return PACKAGE if name == "" else "auto_resume" if name == "auto_resume" else PACKAGE + "." + name


# Every module, placed. A new module has to be given a layer here before anything else.
LAYER = {_q(name): layer for layer, names in {
    # v0.6.10-alpha: machine.py became domain/{states,gates,public}.py, which is what its own
    # docstring called "three layers, kept apart on purpose", said in the tree.
    "domain": ("failures", "reasons", "machine", "domain", "domain.errors", "domain.gates",
               "domain.ids", "domain.public", "domain.states", "domain.vocabulary"),
    "policy": ("", "settings", "continuation", "l10n", "messages", "interface", "config", "logbook"),
    "adapters": ("store", "openstate", "codex", "windows", "compat", "compatio", "startup", "shortcut",
                 "pwsh", "notify", "notice_presence", "tray_place",
                 # v0.6.10-alpha: store.py became store/. Every part of it is the same layer
                 # the one module was, and `STORE` below covers them by prefix.
                 "store.actions", "store.claims", "store.columns", "store.downgrade",
                 "store.errors", "store.journal", "store.legacy", "store.migrations",
                 "store.policy", "store.records", "store.reporting", "store.schema",
                 "store.session", "store.validate", "store.watcher",
                 # v0.6.10-alpha: the Win32 the product calls, which windows.py was half of.
                 "win", "win.dll", "win.homelock", "win.inventory", "win.kernel", "win.sync",
                 # v0.6.10-alpha: source.py became source/, and every part of it reads Codex;
                 # windows.py's other half - the CLI, the App Server, the pairing - joined it.
                 "codex.appserver", "codex.errors", "codex.history", "codex.labels",
                 "codex.pairing", "codex.paths", "codex.payload", "codex.schema",
                 "codex.transport", "codex.usage", "codex.values"),
    "engine": ("engine", "engine.announce", "engine.detect", "engine.dispatch",
               "engine.freshness", "engine.options", "engine.outcome", "engine.reconcile"),
    # v0.6.10-alpha: control.py became control/, ten files, `Control` composed from eight
    # mixins. `layer` is where the composition lives, so that the front holds no code.
    "control": ("control", "control.actions", "control.codexstart", "control.errors",
                "control.layer", "control.policy", "control.preview", "control.records",
                "control.seen", "control.state", "control.watcher", "diagnostics"),
    "front": ("auto_resume", "cli", "controlcli", "mcpserver", "mcp.panel", "app", "ui.tray",
              # v0.6.10-alpha: app.py became runtime/ - the wiring, the loop and the toasts.
              "runtime", "runtime.app", "runtime.loop", "runtime.toasts",
              # v0.6.10-alpha: mcpserver.py's body became mcp/, beside the panel's own files.
              "mcp", "mcp.server", "mcp.tools",
              "ui.popup", "brand",
              "notice_card", "notice_window", "notifier",
              # v0.6.10-alpha: brand.py became brand/ - one palette in nine files.
              "brand.checkbox", "brand.colour", "brand.css", "brand.elevation", "brand.light",
              "brand.mark", "brand.motion", "brand.scale", "brand.tokens",
              # v0.6.10-alpha: tray.py became tray/ - the same icon in eleven files, all of
              # them the front. `UI` below covers them by prefix.
              "ui.tray.animation", "ui.tray.cards", "ui.tray.clicks", "ui.tray.dashboard", "ui.tray.icon",
              "ui.tray.menu", "ui.tray.model", "ui.tray.motion", "ui.tray.stored", "ui.tray.win32",
              "ui.tray.words",
              # v0.6.10-alpha: what every surface writes the same way.
              "ui", "ui.words",
              # v0.6.10-alpha: tray_popup.py became tray_popup/ - the same popup in twelve
              # files, all of them the front. `UI` below covers them by prefix.
              "ui.popup.elevation", "ui.popup.fonts", "ui.popup.gdiplus",
              "ui.popup.layout", "ui.popup.model", "ui.popup.motion",
              "ui.popup.placement", "ui.popup.renderer", "ui.popup.theme",
              "ui.popup.win32", "ui.popup.window", "ui.popup.words"),
}.items() for name in names}

# The roles the target rules speak of: today's modules, and the packages the split moves them
# into (PLANNED, which need not exist yet). Each name covers itself and everything inside it.
PLANNED = {_q(name) for name in ("codex", "win", "ui", "mcp", "domain.public")}
STORE = {_q("store"), _q("openstate")}              # openstate moves into store/ as store/open.py
CODEX = {_q("codex"), _q("windows"), _q("codex")}         # Codex's files and processes
WIN = {_q(name) for name in ("windows", "startup", "shortcut", "pwsh", "notify", "notice_presence",
                             "tray_place", "win")}
UI = {_q(name) for name in ("brand", "notice_card", "notice_window", "ui")}
MCP = {_q("mcpserver"), _q("mcp")}
# What the UI may reach: the control layer, the public status mapping (machine, until it is
# split into domain/), the i18n layer and the brand - and itself.
# v0.6.10-alpha adds win/: the Win32 declarations a surface registers its window with, which
# the icon used to own and the other two imported out of it - the cycle that is now gone.
UI_MAY_IMPORT = ({_q("control"), _q("machine"), _q("domain.public"), _q("l10n"), _q("interface"),
                  _q("win"), _q("win.dll")} | UI)
PURE_STDLIB = {"__future__", "abc", "collections", "dataclasses", "decimal", "enum", "fractions", "functools",
               "hashlib", "itertools", "json", "math", "numbers", "operator", "re", "string", "textwrap",
               "types", "typing", "uuid"}

# Target rules that do not hold yet: the real edges that break them. Each fails the test the
# day it no longer exists, so these only shrink.
ENGINE_EXCEPTIONS = {
    (_q("engine.detect"), _q("codex")): "source.detect() is imported and called directly rather than "
                                          "reached through the source the engine is given "
                                          "(engine/ports.py, step 8)",
}
UI_EXCEPTIONS = {
    (_q("ui.popup.model"), _q("reasons")): "the popup asks the reason registry for a label key, whether a "
                                       "category is recoverable and whether it has a reset time",
    (_q("notice_window"), _q("notice_presence")): "the card reads battery saver and the message duration "
                                                  "from the presence probes, which are Windows adapters",
    (_q("ui.tray.animation"), _q("tray_place")): "the icon asks where Windows keeps it and whether battery "
                                              "saver is on before it moves; both are Windows adapters "
                                              "(win/ takes them at step 9)",
}

# Import cycles, which exist only through imports made inside functions. Each is removed by
# the split (win/dll.py for the icon's shared Win32 structures, compat/ and win/ for the
# registry and the adapter), and until then is listed here exactly.
LAZY_CYCLES = {
    frozenset({_q("codex.transport"), _q("compatio"), _q("windows")}):
        "codex.transport.verified_versions reads the bundled baseline through compatio, and "
        "compatio's probes read the adapter through the `windows` front - which is what puts "
        "three modules in the cycle rather than two",
}

# Every import made inside a function, with what it is for. Three kinds, and the test checks
# each claim against the import graph:
#   cost       it defers loading a module the importer would not otherwise load;
#   redundant  the module is loaded with the importer anyway, so the import belongs at the top
#              of the file (the ten there were have been moved there; none is left);
#   cycle      it closes one of LAZY_CYCLES above.
LAZY_IMPORTS = {(_q(importer), _q(imported)): (kind, reason) for (importer, imported), (kind, reason) in {
    ("", "config"): ("cost", "__version__ is resolved on demand, so importing the package reads no manifest"),
    ("runtime.app", "control"): ("cost", "only a card's button and the icon's thread use the control layer"),
    ("runtime.loop", "control"): ("cost", "only a card's button and the icon's thread use the control layer"),
    ("runtime.app", "interface"): ("cost", "the icon's catalogue, when the icon starts or the language changes"),
    ("runtime.app", "ui.tray"): ("cost", "the notification-area icon, only in a watcher that shows one"),
    # Reaching `ui.tray` loads `ui/__init__.py` with it, and since v0.6.10-alpha the icon
    # is inside `ui/`, so the package above it is an edge these two did not have before.
    ("runtime.app", "ui"): ("cost", "the package above the icon, loaded with it"),
    ("cli", "ui"): ("cost", "the package above the icon, loaded with it"),
    ("runtime.app", "ui.popup"): ("cost", "the popup's theme and motion, adopted only by a running watcher"),
    ("cli", "control"): ("cost", "the diagnostics command is the only one that goes through control"),
    ("cli", "diagnostics"): ("cost", "only the diagnostics command writes the export"),
    ("cli", "ui.tray"): ("cost", "activate opens the settings window through the icon's helper"),
    ("compatio", "windows"): ("cycle", "the registry's API and discovery checks read the adapter"),
    ("config", "settings"): ("cost", "nearly everything imports config; the settings schema, and the "
                                     "catalogs behind it, load only when settings are read or written"),
    ("controlcli", "compatio"): ("cost", "the three compatibility commands only"),
    ("controlcli", "diagnostics"): ("cost", "the diagnostics command only"),
    ("controlcli", "interface"): ("cost", "the strings request only: the window's catalogue"),
    ("diagnostics", "compatio"): ("cost", "the compatibility section of the export only"),
    ("mcp.server", "compat"): ("cost", "the compatibility summary in get_status only"),
    ("mcp.server", "compatio"): ("cost", "the compatibility summary in get_status only"),
    ("mcp.server", "mcp.panel"): ("cost", "the panel's page, only when Codex reads the resource"),
    ("notify", "reasons"): ("cost", "a reason's label, for a transient toast only"),
    ("notify", "startup"): ("cost", "the AUMID only: startup owns every per-user registration, and a "
                                    "process that only formats a message should not load it"),
    ("shortcut", "startup"): ("cost", "the default AUMID only, as for notify"),
    # Since v0.6.10-alpha neither closes a cycle - the Win32 declarations and the countdown
    # moved to win/ and ui/ - so both are what they always looked like: a window the icon opens
    # only when somebody asks for it.
    ("ui.tray.animation", "ui.popup"): ("cost", "a frame's drawing, only while the icon moves"),
    ("ui.tray.cards", "ui.popup"): ("cost", "the card's look, only when one is shown"),
    ("ui.tray.cards", "notice_window"): ("cost", "the card's window, only when one is shown"),
    ("ui.tray.clicks", "ui.popup"): ("cost", "the popup, built when the icon is clicked"),
    ("ui.tray.menu", "ui.popup"): ("cost", "the theme the menu is drawn in, only when it opens"),
    ("ui.tray.motion", "ui.popup"): ("cost", "whether the popup asks for attention"),
    ("ui.tray.stored", "ui.popup"): ("cost", "the popup's theme and motion, adopted with the settings"),
    ("codex.transport", "compatio"): ("cycle", "the versions the bundled registry verifies are "
                                                "read from the bundled baseline"),
    ("codex.appserver", "config"): ("cost", "the product version for the App Server's clientInfo, "
                                            "when a Protocol opens"),
}.items()}


def within(name, roles):
    """True when `name` is one of `roles` or a module inside one of them.

    `codex_auto_resume.store.claims` is within `store`; `codex_auto_resume.codexry` is not
    within `source`."""
    return any(name == role or name.startswith(role + ".") for role in roles)


def members(roles):
    """Today's modules that lie within `roles`: the modules, and every module of a package."""
    return {module for module in srcscan.modules() if within(module, roles)}


def edges(*, lazy):
    """(importer, imported) -> the lines, for this product's imports; lazy or not as asked."""
    found = {}
    for module, path in srcscan.modules().items():
        for entry in srcscan.imports(path):
            if entry.internal and entry.target in srcscan.modules() and entry.target != module \
                    and entry.lazy == lazy:
                found.setdefault((module, entry.target), []).append(entry.line)
    return found


def strongly_connected(graph):
    """The import cycles of a graph, as sets of modules (Tarjan)."""
    index, low, stack, on_stack, found = {}, {}, [], set(), []

    def visit(node):
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for other in sorted(graph.get(node, ())):
            if other not in index:
                visit(other)
                low[node] = min(low[node], low[other])
            elif other in on_stack:
                low[node] = min(low[node], index[other])
        if low[node] == index[node]:
            component = set()
            while True:
                other = stack.pop()
                on_stack.discard(other)
                component.add(other)
                if other == node:
                    break
            if len(component) > 1:
                found.append(frozenset(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return found


def short(pair):
    return tuple(name.replace(PACKAGE + ".", "") for name in pair)


class LayerTests(unittest.TestCase):
    def test_every_module_has_a_layer(self):
        modules = set(srcscan.modules())
        self.assertEqual(sorted(modules - set(LAYER)), [], "place the new module in a layer")
        self.assertEqual(sorted(set(LAYER) - modules), [], "the table names a module that is gone")
        for name in STORE | CODEX | WIN | UI | MCP | UI_MAY_IMPORT:
            with self.subTest(name):
                self.assertTrue(name in modules or name in PLANNED,
                                "a role names a module that is neither here nor planned")

    def test_a_role_covers_the_package_its_modules_move_into(self):
        """The shapes the split produces, each in the role the flat module had."""
        for moved, role in (("store.claims", STORE), ("codex.history", CODEX), ("codex", CODEX),
                            ("win.dll", WIN), ("ui.popup.layout", UI), ("ui", UI),
                            ("mcp.panel", MCP), ("control.commands", UI_MAY_IMPORT),
                            ("domain.public", UI_MAY_IMPORT)):
            with self.subTest(moved):
                self.assertTrue(within(_q(moved), role))
        for outside, role in (("sourcery", CODEX), ("stores", STORE), ("window", WIN),
                              ("uix", UI), ("mcpx", MCP), ("domain.ids", UI_MAY_IMPORT)):
            with self.subTest(outside):
                self.assertFalse(within(_q(outside), role))
        self.assertEqual(members(UI) & members(MCP), set())

    def test_imports_point_down_or_sideways(self):
        upward, unplaced = [], set()
        for importer, targets in srcscan.import_graph().items():
            for imported in targets:
                if importer not in LAYER or imported not in LAYER:
                    unplaced.update(name for name in (importer, imported) if name not in LAYER)
                elif ORDER.index(LAYER[imported]) > ORDER.index(LAYER[importer]):
                    upward.append("%s (%s) -> %s (%s)" % (importer, LAYER[importer], imported, LAYER[imported]))
        self.assertEqual(sorted(unplaced), [], "place the new module in a layer first")
        self.assertEqual(sorted(upward), [])

    def test_the_domain_imports_only_itself_and_the_pure_standard_library(self):
        domain = {name for name, layer in LAYER.items() if layer == "domain"}
        for module in sorted(domain):
            for entry in srcscan.imports(srcscan.modules()[module]):
                with self.subTest(module=module, imports=entry.target):
                    if entry.internal:
                        self.assertIn(entry.target, domain)
                    else:
                        self.assertIn(entry.target.split(".")[0], PURE_STDLIB, "no clock, no I/O, no ctypes")

    def assert_exceptions(self, found, exceptions):
        found, listed = {short(pair) for pair in found}, {short(pair) for pair in exceptions}
        self.assertEqual(sorted(found - listed), [], "a new edge that breaks the rule")
        self.assertEqual(sorted(listed - found), [], "an exception has gone: delete it")

    def test_the_engine_names_no_store_codex_or_windows(self):
        engine = {name for name, layer in LAYER.items() if layer == "engine"} | members({_q("engine")})
        found = set()
        for module in sorted(engine):
            for entry in srcscan.imports(srcscan.modules()[module]):
                if entry.target.split(".")[0] in ("sqlite3", "ctypes", "subprocess"):
                    self.fail("%s imports %s" % (module, entry.target))
                if within(entry.target, STORE | CODEX | WIN):
                    found.add((module, entry.target))
        self.assert_exceptions(found, ENGINE_EXCEPTIONS)

    def test_the_ui_imports_only_control_the_public_domain_i18n_and_brand(self):
        found = set()
        for module in sorted(members(UI)):
            for entry in srcscan.imports(srcscan.modules()[module]):
                if entry.internal and not within(entry.target, UI_MAY_IMPORT):
                    found.add((module, entry.target))
        self.assert_exceptions(found, UI_EXCEPTIONS)

    def test_neither_the_mcp_server_nor_the_ui_imports_codex(self):
        importers = members(MCP | UI)
        self.assertLessEqual({_q("ui.popup"), _q("mcp.panel"), _q("mcpserver")}, importers)
        for module in sorted(importers):
            for entry in srcscan.imports(srcscan.modules()[module]):
                with self.subTest(module=module, imports=entry.target):
                    self.assertFalse(within(entry.target, CODEX), "the UI and the MCP server never read Codex")


class CycleTests(unittest.TestCase):
    def test_no_cycle_among_the_imports_that_run_at_load(self):
        graph = srcscan.import_graph(lazy=False)
        self.assertEqual(strongly_connected(graph), [])

    def test_the_only_cycles_are_the_listed_lazy_ones(self):
        found = strongly_connected(srcscan.import_graph())
        self.assertEqual(sorted(sorted(short(cycle)) for cycle in found),
                         sorted(sorted(short(cycle)) for cycle in LAZY_CYCLES),
                         "a cycle has gone (delete it) or a new one appeared")
        for cycle, reason in LAZY_CYCLES.items():
            self.assertTrue(reason.strip())


class LazyImportTests(unittest.TestCase):
    def test_every_lazy_import_is_listed_with_its_reason(self):
        found = set(edges(lazy=True))
        self.assertEqual(sorted(short(pair) for pair in found - set(LAZY_IMPORTS)), [],
                         "an import inside a function that LAZY_IMPORTS does not list")
        self.assertEqual(sorted(short(pair) for pair in set(LAZY_IMPORTS) - found), [],
                         "LAZY_IMPORTS lists an import that is gone")
        for pair, (kind, reason) in LAZY_IMPORTS.items():
            self.assertIn(kind, ("cost", "redundant", "cycle"), short(pair))
            self.assertTrue(reason.strip(), short(pair))

    def test_each_lazy_import_is_the_kind_it_says(self):
        cycles = [set(cycle) for cycle in LAZY_CYCLES]
        for (importer, imported), (kind, _) in LAZY_IMPORTS.items():
            with self.subTest(importer=importer, imported=imported):
                if imported in srcscan.closure(importer, lazy=False):
                    actual = "redundant"
                elif importer in srcscan.closure(imported):
                    actual = "cycle"
                    self.assertTrue(any({importer, imported} <= cycle for cycle in cycles))
                else:
                    actual = "cost"
                self.assertEqual(kind, actual)


if __name__ == "__main__":
    unittest.main()

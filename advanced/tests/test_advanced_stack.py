"""Where every module of advanced/src goes when the core is Rust, and what may call what once it does.

`tests/test_stack.py` places every module of `src/` on one item and holds the crate graph the imports make.
This is that test for `advanced/src`, which it does not read (it places `srcscan.modules()`, and that is `src/`
only). The v0.6.27 port gives the advanced edition one crate in the alpha, `car-adv` (D19), because the nine groups
its modules fall into make one cycle through seven of them: `arming.py` reads `engine.usage`, `state/schema.py`
reads `registry`, `engine/push.py` reads `report.records`, `courier/api.py` reads `control.remote`, `ledger.py` reads
`engine.hookclaims`. Splitting it is v0.6.27 final work, and starts by cutting that cycle - which this holds, so the
cuts are listed here, each with the modules that make it, before any of them is made.

So it places, holds and lists, the way test_stack does:

  * `ITEM` - every module on exactly one item: the nine groups crate-map.md names for them (machine, policy, store,
    codex, platform, engine, control, courier, hook - the first six are core's items too), and two items that are no
    crate: `retired` (the Pythons page's backend and the python.org downloads, which the Rust edition does not have,
    D8) and `tooling` (the measurement harness and the evidence writer, which a person runs from a checkout, D10).
  * `EDGES` - which item calls which, as the imports run today, held both ways.
  * `CYCLES` - the strongly connected groups of the graph, as it is. A cycle that is gone fails: take it off.
  * `UNWANTED` - the edges that make the cycles, read against `ORDER` (lowest layer first: an edge may call down).
    Every edge not listed points down, so the graph without them is a DAG - the crate graph a split would build.
    Only shrinks: an entry that stops being an edge, or stops pointing up, fails.

Nothing here imports the advanced package; it reads the files with `ast`, like srcscan, edge by edge: the imports of a
function body count as the others do (a lazy import is still a call across the seam), and so do the packages a
statement loads without naming them (`import a.b.c` runs `a/__init__.py` and `a/b/__init__.py`).
"""
from __future__ import annotations

import ast
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "advanced" / "src"
PACKAGE = "codex_auto_resume_advanced"


def _q(name: str) -> str:
    return PACKAGE if name == "" else PACKAGE + "." + name


def short(name: str) -> str:
    if name.startswith(PACKAGE + "."):
        return name[len(PACKAGE) + 1:]
    return "" if name == PACKAGE else name


# The groups a split would make. Lowest layer first, as ORDER reads: what an item may call is below it.
MACHINE, PLATFORM, CODEX, COURIER, STORE, ENGINE, HOOK, CONTROL, POLICY = (
    "machine", "platform", "codex", "courier", "store", "engine", "hook", "control", "policy")
RETIRED, TOOLING = "retired", "tooling"
CRATES = (MACHINE, PLATFORM, CODEX, COURIER, STORE, ENGINE, HOOK, CONTROL, POLICY)
ITEMS = CRATES + (RETIRED, TOOLING)

# Every module, placed. A new module is given an item here before anything else.
ITEM = {_q(name): item for item, names in {
    # Every word the rest of it stores, journals or answers with.
    MACHINE: ("vocabulary",),
    # Windows calls and where a secret goes.
    PLATFORM: ("credentials", "win", "win.appclose", "win.dpapi", "win.stopflag", "win.waketimer"),
    # The App Server methods that live only here, the one-turn session, and what is read of Codex's own files.
    CODEX: ("codex", "codex.account", "codex.authfile", "codex.conversation", "codex.credits", "codex.goals",
            "codex.headless", "codex.inuse", "codex.ipc", "codex.lineage", "codex.protocol", "codex.restart",
            "codex.sessions", "codex.swap", "codex.threads", "codex.tokens", "codex.turns", "codex.wmi_escape",
            "autocheck", "compatdata"),
    # The channel's own process and what it speaks: Telegram, the local page, the outbox.
    COURIER: ("courier", "courier.__main__", "courier.address", "courier.api", "courier.channels", "courier.feed",
              "courier.http", "courier.keep", "courier.launch", "courier.outbox", "courier.page",
              "courier.resident", "courier.telegram"),
    # config/advanced/advanced.sqlite, the claim ledger over both editions' records, the account profiles,
    # the images and the watcher's own log.
    STORE: ("state", "state.account", "state.analytics", "state.arming", "state.chat", "state.choices",
            "state.continuations", "state.journal", "state.meter", "state.opens", "state.prompts", "state.records",
            "state.resets", "state.restarts", "state.runs", "state.schema", "state.session", "state.spend",
            "state.steers", "ledger", "profiles", "images", "watchlog"),
    # What the plug's points ask of it, one module per capability, and the runtime that asks the registry.
    ENGINE: ("", "plug", "runtime", "engine", "engine.account", "engine.admitted", "engine.analytics",
             "engine.anchor", "engine.autoswitch", "engine.capacity", "engine.chat", "engine.compact",
             "engine.continued", "engine.credits", "engine.earlyreset", "engine.emptyreply",
             "engine.everyconversation", "engine.fallback", "engine.feed", "engine.fleet", "engine.foropen",
             "engine.goal", "engine.headless", "engine.hookclaims", "engine.keepgoing", "engine.markerfree",
             "engine.oncemore", "engine.opentarget", "engine.parallel", "engine.powertasks", "engine.promptqueue",
             "engine.push", "engine.remote", "engine.resetmessage", "engine.resetwatch", "engine.retries",
             "engine.sessions", "engine.silent", "engine.steer", "engine.subagent", "engine.supervise",
             "engine.updatecheck", "engine.usage", "engine.usagestop", "engine.wake", "engine.wrapwords"),
    # The hook Codex runs, read and answered.
    HOOK: ("hook", "hook.format", "hook.handler"),
    # The Dashboard's bridge commands and a model's MCP tools (P10), the commands behind them, and the
    # compatibility report this PC's records make.
    CONTROL: ("surfaces", "control", "control.account", "control.analytics", "control.autoswitch", "control.chat",
              "control.codexstart", "control.conversations", "control.courier", "control.earlycheck",
              "control.fleet", "control.follow", "control.hookplugin", "control.keepgoing", "control.opencodex",
              "control.powertasks", "control.prompts", "control.remote", "control.resets", "control.sendnow",
              "control.steer", "report", "report.document", "report.flow", "report.github", "report.records"),
    # What a capability is and who turns it on: the registry, the arming, the statements, the standards a
    # capability may depart from, what an administrator's keys allow, and the build-time table of measurements.
    POLICY: ("registry", "arming", "policy", "standards", "statement", "measured"),
    # D8: no Python picker in the Rust edition.
    RETIRED: ("control.pythons", "courier.pythonorg", "pythoncheck"),
    # D10: run from a checkout by a person.
    TOOLING: ("measure", "evidence"),
}.items() for name in names}

# Lowest layer first. An item may call the items before it, and no other - bar UNWANTED. The words and the Windows
# calls are the foundation; the seven groups of the cycle are in the order, of all 5,040 there are, that leaves the
# fewest module imports pointing up (50); the two items that are no crate are on top, so that nothing a crate holds
# may call them and they may call anything.
ORDER = (MACHINE, PLATFORM, CODEX, COURIER, STORE, ENGINE, HOOK, CONTROL, POLICY, RETIRED, TOOLING)

# The strongly connected groups of the graph today, among the nine groups that are crates (the two that are no crate
# join them only through the four edges into them listed below, which go when their importers stop). Only shrinks:
# a group that is no longer one fails.
CYCLES = {
    frozenset((CODEX, CONTROL, COURIER, ENGINE, HOOK, POLICY, STORE)):
        "seven of the nine groups reach one another: the capability's own work (engine) reads the registry and the "
        "statements (policy), the registry reads the courier's outbox and the Pythons page, the store's ledger reads "
        "the engine and the bridge commands, the courier reads the bridge's remote and the engine's, and the "
        "bridge reads all of them",
}

# The edges that make the cycle, against ORDER, and the modules that make each. Only shrinks.
UNWANTED = {
    (CODEX, CONTROL): "codex/account and codex/swap read the compatibility report's GitHub reader (report, report.github)",
    (CODEX, POLICY): "compatdata reads the build-time table of measurements (measured)",
    (CODEX, STORE): "codex/swap reads the account profiles (profiles)",
    (COURIER, CONTROL): "courier/api and courier/telegram read the bridge's remote commands (control.remote); "
                        "courier/__main__ reads the report's records",
    (COURIER, ENGINE): "courier/resident reads the engine's remote (engine.remote); courier/__main__ reads runtime",
    (COURIER, POLICY): "the three channels read their statement (statement)",
    (STORE, CONTROL): "ledger reads the bridge's send-now command (control.sendnow)",
    (STORE, ENGINE): "ledger reads the hook claims (engine.hookclaims), P11: the claim counted inside core's BEGIN IMMEDIATE",
    (STORE, POLICY): "ledger and state/{__init__,arming,records,schema,session} read the registry's capabilities and words",
    (ENGINE, CONTROL): "engine/hookclaims, engine/opentarget and engine/push read the bridge's hook plug, opening and "
                       "report; plug reads control and surfaces",
    (ENGINE, POLICY): "ten of the engine's capabilities read their statement or the registry, and runtime reads "
                      "the registry and the arming",
    (HOOK, POLICY): "hook/handler reads the arming",
    (CONTROL, POLICY): "surfaces reads the registry, which it presents",
    # The two items that are no crate: nothing a crate holds may import them.
    (CONTROL, RETIRED): "surfaces reads the Pythons page's backend (control.pythons)",
    (ENGINE, RETIRED): "plug reads the Pythons page's backend (control.pythons)",
    (POLICY, RETIRED): "registry reads the Pythons page's backend (control.pythons)",
    (ENGINE, TOOLING): "runtime reads the measurement harness (measure)",
}

# Which item calls which, as the imports run today, both ways like test_stack's EDGES: a call this does not
# allow fails, and an edge nothing makes fails too.
EDGES = {
    (CODEX, CONTROL), (CODEX, MACHINE), (CODEX, PLATFORM), (CODEX, POLICY), (CODEX, STORE),
    (CONTROL, CODEX), (CONTROL, COURIER), (CONTROL, ENGINE), (CONTROL, HOOK), (CONTROL, MACHINE),
    (CONTROL, PLATFORM), (CONTROL, POLICY), (CONTROL, RETIRED), (CONTROL, STORE),
    (COURIER, CODEX), (COURIER, CONTROL), (COURIER, ENGINE), (COURIER, MACHINE), (COURIER, PLATFORM),
    (COURIER, POLICY),
    (ENGINE, CODEX), (ENGINE, CONTROL), (ENGINE, COURIER), (ENGINE, MACHINE), (ENGINE, PLATFORM),
    (ENGINE, POLICY), (ENGINE, RETIRED), (ENGINE, STORE), (ENGINE, TOOLING),
    (HOOK, ENGINE), (HOOK, MACHINE), (HOOK, POLICY), (HOOK, STORE),
    (POLICY, CODEX), (POLICY, CONTROL), (POLICY, COURIER), (POLICY, ENGINE), (POLICY, MACHINE),
    (POLICY, RETIRED), (POLICY, STORE),
    (RETIRED, COURIER), (RETIRED, MACHINE),
    (STORE, CODEX), (STORE, CONTROL), (STORE, COURIER), (STORE, ENGINE), (STORE, MACHINE), (STORE, PLATFORM),
    (STORE, POLICY),
    (TOOLING, CODEX), (TOOLING, CONTROL), (TOOLING, ENGINE), (TOOLING, MACHINE), (TOOLING, POLICY),
    (TOOLING, STORE),
}


# ------------------------------------------------------------------------------------------ the scan
@lru_cache(maxsize=None)
def modules() -> dict:
    """Dotted module name -> its file, for every tracked `.py` file under advanced/src. Loud: no git, or a
    listing with no package in it, raises rather than returning nothing, because a scan over nothing passes."""
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "advanced/src"],
                             capture_output=True, timeout=120)
    if listing.returncode != 0:
        raise RuntimeError("git ls-files failed: %s" % listing.stderr.decode("utf-8", "replace").strip())
    found = {}
    for name in sorted(entry for entry in listing.stdout.decode("utf-8").split("\0") if entry.endswith(".py")):
        path = ROOT / name
        if not path.is_file():
            continue
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    if PACKAGE not in found:
        raise RuntimeError("git lists no file of the advanced package")
    return found


def _targets(node, module: str, is_package: bool) -> list:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        parts = module.split(".") if is_package else module.split(".")[:-1]
        if node.level > 1:
            parts = parts[:len(parts) - (node.level - 1)]
        target = ".".join(part for part in (".".join(parts), node.module) if part)
    else:
        target = node.module or ""
    known = modules()
    submodules = [target + "." + alias.name for alias in node.names if target + "." + alias.name in known]
    # `from . import config` names the module `config`, not the package's __init__.
    if len(submodules) == len(node.names):
        return submodules
    return [target] + submodules


def _ancestors(name: str, importer: str) -> list:
    """The packages above `name` that run on their own when `importer` imports it, outermost first."""
    parts = name.split(".")
    return [package for package in (".".join(parts[:end]) for end in range(1, len(parts)))
            if package in modules() and package != importer and not importer.startswith(package + ".")]


@lru_cache(maxsize=None)
def imports(module: str) -> tuple:
    """The modules of advanced/src that a module imports, named or loaded with what it names; itself excluded."""
    path = modules()[module]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for target in _targets(node, module, path.name == "__init__.py"):
                if target in modules() and target != module and target not in found:
                    found.append(target)
                    found.extend(package for package in _ancestors(target, module)
                                 if package not in found and package != module)
    return tuple(found)


def edges() -> dict:
    """(item, item) -> the module edges that make it, for every import this edition runs."""
    found: dict = defaultdict(set)
    for module in modules():
        for target in imports(module):
            pair = (ITEM.get(module), ITEM.get(target))
            if pair[0] is None or pair[1] is None or pair[0] == pair[1]:
                continue
            found[pair].add((short(module), short(target)))
    return dict(found)


def cycles(graph, among=CRATES) -> set:
    """The strongly connected groups of more than one item, among the items `among` and the edges between them."""
    below = defaultdict(set)
    for first, second in graph:
        if first in among and second in among:
            below[first].add(second)

    def reach(start):
        seen, pending = set(), [start]
        while pending:
            for nxt in below[pending.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    pending.append(nxt)
        return seen

    found = set()
    for item in among:
        group = frozenset([item] + [other for other in among if other in reach(item) and item in reach(other)])
        if len(group) > 1:
            found.add(group)
    return found


class PlacementTests(unittest.TestCase):
    def test_every_module_is_on_one_item(self):
        names = set(modules())
        self.assertEqual(sorted(short(name) for name in names - set(ITEM)), [],
                         "place the new module on an advanced stack item")
        self.assertEqual(sorted(short(name) for name in set(ITEM) - names), [],
                         "the table names a module that is gone")

    def test_a_module_is_written_on_one_item_only(self):
        every = [name for item_names in _written() for name in item_names]
        self.assertEqual(sorted(every), sorted(set(every)), "a module is written on two items")

    def test_every_item_has_a_module_and_the_order_names_every_item(self):
        self.assertEqual(sorted(set(ITEM.values())), sorted(ITEMS))
        self.assertEqual(sorted(ORDER), sorted(ITEMS))

    def test_the_package_is_the_one_whose_marker_stays_in_the_archive(self):
        # The marker stub (`__init__`, D9) is the engine's: it names nothing and imports nothing.
        self.assertEqual(ITEM[PACKAGE], ENGINE)
        self.assertEqual(imports(PACKAGE), ())


class CrateGraphTests(unittest.TestCase):
    def test_no_item_calls_one_this_file_does_not_allow(self):
        found = edges()
        unexpected = sorted(pair for pair in found if pair not in EDGES)
        detail = "\n".join(
            "%s -> %s: %s" % (a, b, ", ".join("%s -> %s" % edge for edge in sorted(found[(a, b)])[:4]))
            for a, b in unexpected)
        self.assertEqual(unexpected, [], "a call across items that no crate edge allows\n" + detail)

    def test_every_allowed_call_is_one_that_happens(self):
        """An edge nothing makes is an interface the split would build and nobody would use."""
        self.assertEqual(sorted(EDGES - set(edges())), [], "EDGES allows a call nothing makes any more")

    def test_the_cycles_are_the_listed_ones(self):
        self.assertEqual(sorted(sorted(group) for group in cycles(edges())),
                         sorted(sorted(group) for group in CYCLES),
                         "a cycle among the groups appeared or went; update CYCLES")

    def test_each_unwanted_edge_is_still_one_and_still_points_up(self):
        found = set(edges())
        self.assertEqual(sorted(set(UNWANTED) - found), [], "an unwanted edge is gone; take it off UNWANTED")
        for pair in sorted(UNWANTED):
            with self.subTest("%s -> %s" % pair):
                self.assertGreater(ORDER.index(pair[1]), ORDER.index(pair[0]),
                                   "an edge listed as unwanted that already points down; take it off")

    def test_every_edge_not_listed_points_down(self):
        """So without UNWANTED the graph is a DAG, and ORDER is a build order for the crates a split makes."""
        up = sorted(pair for pair in edges()
                    if pair not in UNWANTED and ORDER.index(pair[1]) > ORDER.index(pair[0]))
        self.assertEqual(up, [], "an edge that points up and is not listed in UNWANTED")

    def test_without_the_unwanted_edges_there_is_no_cycle(self):
        self.assertEqual(cycles(set(edges()) - set(UNWANTED), among=ITEMS), set())

    def test_what_is_no_crate_is_called_by_no_crate_but_the_listed(self):
        """retired and tooling are at the top of ORDER: a crate importing one is UNWANTED, so none does but the listed."""
        for pair in edges():
            if pair[1] in (RETIRED, TOOLING):
                self.assertIn(pair, UNWANTED)

    def test_the_foundations_call_nothing(self):
        called = {pair[1] for pair in edges() if pair[0] in (MACHINE, PLATFORM)}
        self.assertEqual(sorted(called), [], "the words and the Windows calls reached up")


def _written() -> list:
    """Each item's names as ITEM was written, to see a module written twice (a dict comprehension keeps the last)."""
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ITEM" for t in node.targets):
            comprehension = node.value
            mapping = comprehension.generators[0].iter.func.value        # the dict literal before .items()
            return [[ast.literal_eval(element) for element in value.elts] for value in mapping.values]
    raise AssertionError("ITEM is not written as a dict literal's comprehension")


if __name__ == "__main__":
    unittest.main()

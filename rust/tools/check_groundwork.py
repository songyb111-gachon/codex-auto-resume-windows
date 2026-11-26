"""Holds the Rust groundwork to what PLAN.md 1.1-1.3 and 2 say it is. Python standard library only; run from anywhere:

    python rust/tools/check_groundwork.py

It checks, and exits 1 with every finding if one fails:

* the two workspaces' shared files agree (rust-toolchain.toml, .cargo/config.toml, deny.toml, tools/rustflags.sh, the
  [profile.*] tables), because a config file and a profile belong to the workspace root they sit in;
* tools/rustflags.sh repeats every rustflag of the config (RUSTFLAGS replaces the config's list whole);
* nothing under rust/ names the advanced edition (D2: deleting advanced/ must change nothing the standard workspace
  reads): the names the Python product's edition audit looks for (build/edition_audit.py: the advanced package, the skill
  and the sentinel), a crate `car-adv*` and the path `advanced/`. The word "advanced" alone is not a name: the tier
  "advanced" of the compatibility vocabulary, the logbook's sentences and gui/Brand.cs's comment hold it, as the Python
  product's standard files do;
* `cargo metadata` shows exactly the crates of PLAN.md 1.2 and exactly the edges of EXPECTED below, both ways, in
  each workspace (cargo itself refuses a cycle; this refuses an edge nobody decided);
* the two Cargo.lock files give every crate they share the same version.

EXPECTED is test_stack.EDGES read as crates, minus the cuts C1-C6 of PLAN.md 1.3. A seat that fills a crate and
needs an edge changes EXPECTED in the same commit and says why; an edge is added only when the Python import it
stands for exists.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STD = ROOT / "rust"
ADV = ROOT / "advanced" / "rust"

# crate -> the crates it depends on, inside the standard workspace.
STANDARD = {
    "car-machine": set(),
    "car-words": {"car-machine"},                       # words -> machine
    "car-brand": set(),
    "car-config": {"car-machine"},                      # config -> machine (C2 cut config -> policy)
    "car-platform": {"car-machine"},                    # platform -> machine
    "car-policy": {"car-machine", "car-words"},         # C3/C4 cut policy -> codex, policy -> store
    "car-store": {"car-machine", "car-policy"},
    "car-codex": {"car-config", "car-machine", "car-platform", "car-policy"},
    "car-scheduler": {"car-machine", "car-policy"},
    "car-engine": {"car-codex", "car-machine", "car-policy", "car-scheduler", "car-words"},
    # tray, popup and notifications are C#; what the watcher reads of them is car-surface (PLAN.md 1.5)
    "car-surface": {"car-brand", "car-machine", "car-platform", "car-policy", "car-words"},
    # C5 cut control -> watcher, C6 cut control -> tray; control -> notifications is control -> car-surface
    "car-control": {"car-brand", "car-codex", "car-config", "car-machine", "car-platform", "car-policy",
                    "car-store", "car-surface", "car-words"},
    "car-watcher": {"car-codex", "car-config", "car-control", "car-engine", "car-machine", "car-platform",
                    "car-policy", "car-store", "car-surface", "car-words"},
    # the entry points sit above control and watcher (C5)
    # S8.2: the stub core's test-double forward and the setup program start their child through car-platform's starter
    "car-bin": {"car-control", "car-platform", "car-watcher"},
    # P6 step 0: the host contracts write their replies with car-machine's JSON and take an edition's plug (car-policy Guarded)
    "car-host": {"car-control", "car-machine", "car-policy", "car-watcher"},
    "car-legacy": {"car-platform"},
    # dev only: it writes its replies through car-machine's Python-compatible JSON writer (S0.2) instead of an inline copy;
    # S1.1: it calls the leaf crates it holds to the reference (src/leaves/), car-brand's edge added with car-brand's calls;
    # S1.2: it runs the store's calls through car-store, which replaced its state.rs stand-in;
    # Integration 2: it wires car-platform's link probe (the one `Path.is_symlink()`) into car-store's and car-config's `Links`;
    # S3.2: it runs car-codex's readers (src/codex.rs: `codex.script` and the `codex.*` cases of `leaves.batch`);
    # S4.1: it drives car-engine's engine and car-scheduler's watch (src/engine.rs: `engine.open`, `engine.step`);
    # S5.1a: it runs car-control's bridge over a scratch home (src/bridge.rs: `bridge.run`);
    # S6.0: it runs car-surface's models and decisions (src/surface.rs: `surface.batch`)
    "car-harness": {"car-brand", "car-codex", "car-config", "car-control", "car-engine", "car-machine", "car-platform",
                    "car-policy", "car-scheduler", "car-store", "car-surface", "car-words"},
}
# The advanced workspace: its three crates, and for car-adv every library of the standard one, the superset the
# alpha's single advanced crate may reach through the plug; the S7 seats trim it to what is used.
LIBS = {name for name, deps in STANDARD.items()} - {"car-bin", "car-host", "car-legacy", "car-harness"}
ADVANCED = {
    "car-adv": set(LIBS),
    "car-adv-bin": {"car-adv", "car-bin"},
    "car-adv-host": {"car-adv", "car-host"},
}

SHARED_FILES = ["rust-toolchain.toml", ".cargo/config.toml", "deny.toml", "tools/rustflags.sh"]
PROFILE = re.compile(r"(?ms)^\[profile\..*\Z")

findings: list[str] = []


def fail(text: str) -> None:
    findings.append(text)


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def check_shared_files() -> None:
    for name in SHARED_FILES:
        if read(STD / name) != read(ADV / name):
            fail("rust/%s and advanced/rust/%s differ" % (name, name))
    profiles = [PROFILE.search(read(root / "Cargo.toml")) for root in (STD, ADV)]
    if not all(profiles) or profiles[0].group(0) != profiles[1].group(0):
        fail("the [profile.*] tables of the two workspace manifests differ")
    for root in (STD, ADV):
        text = read(root / "Cargo.toml")
        if 'panic = "unwind"' not in text:
            fail("%s: panic = \"unwind\" (D15) is not stated in the profiles" % root.relative_to(ROOT))
        toolchain = read(root / "rust-toolchain.toml")
        for needle in ('channel = "1.100.0"', '"rustfmt"', '"clippy"', '"x86_64-pc-windows-msvc"'):
            if needle not in toolchain:
                fail("%s/rust-toolchain.toml lacks %s" % (root.relative_to(ROOT), needle))


def check_rustflags() -> None:
    config = read(STD / ".cargo" / "config.toml")
    found = re.search(r"(?m)^rustflags = \[(.*)\]\s*$", config)
    if not found:
        fail("rust/.cargo/config.toml has no rustflags list")
        return
    flags = re.findall(r'"([^"]*)"', found.group(1))
    script = read(STD / "tools" / "rustflags.sh")
    for flag in flags:
        if flag != "-C" and flag not in script:
            fail("tools/rustflags.sh does not repeat the config's flag %s" % flag)
    for needle in ("--remap-path-prefix=", "/Brepro", "/PDBALTPATH:%_PDB%"):
        if needle not in script:
            fail("tools/rustflags.sh lacks %s" % needle)


def advanced_names() -> tuple[tuple[str, ...], "re.Pattern[str]"]:
    """What the standard workspace may not spell: the names `build/edition_audit.py` `check_names` looks for in the
    standard archive - the advanced package's, the skill's and the sentinel's, as they are (one rule, read from the audit,
    not copied) - and the two ways Rust names the advanced edition: a crate `car-adv*` (`car_adv*` in a path of code) and
    the folder `advanced/` (a path dependency or a workspace member that reaches it)."""
    sys.path.insert(0, str(ROOT / "build"))
    try:
        import edition_audit
    finally:
        sys.path.pop(0)
    strong = (edition_audit.PACKAGE, edition_audit.SKILL, edition_audit.SENTINEL)
    rust = re.compile(r"(?<![A-Za-z0-9_])car[-_]adv(?![a-z0-9])|(?<![A-Za-z0-9_])advanced[/\\]")
    return strong, rust


def names_advanced(line: str, strong: tuple[str, ...], rust: "re.Pattern[str]") -> str | None:
    """The name of the advanced edition `line` spells, or None."""
    for name in strong:
        if name in line:
            return name
    found = rust.search(line)
    return found.group(0) if found else None


def allowed_names() -> dict:
    """The lines of the standard workspace that have to spell an advanced name, keyed by the file and the name, as
    `build/edition_audit.py` ALLOWED keys its own: an allowance for one is no allowance for another, and one nothing uses
    fails. The one entry is car-policy's edition look (S2.2), which tells an installation's edition by whether the
    package's folder is there, as `edition.py` does - the line edition_audit allows `edition.py` itself. A standard
    binary that links it holds the package's name, so the audit's (d) will need the same allowance for the Rust core's
    executables (S8.1)."""
    strong, _rust = advanced_names()
    return {("rust/crates/car-policy/src/plug/edition.rs", strong[0]):
            "the one module of core that looks for the package, by its name (edition.py's allowance)"}


def check_standard_never_names_advanced(root: Path = STD) -> None:
    strong, rust = advanced_names()
    allowed, used = allowed_names(), set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "target" in path.relative_to(root).parts:
            continue
        if path.suffix not in (".toml", ".rs", ".sh", ".lock"):
            continue
        where = path.relative_to(root.parent).as_posix()
        for number, line in enumerate(read(path).splitlines(), 1):
            name = names_advanced(line, strong, rust)
            if name and (where, name) in allowed:
                used.add((where, name))
            elif name:
                fail("%s:%d names advanced (%s): %s" % (where, number, name, line.strip()))
    for where, name in sorted(set(allowed) - used):
        if root == STD:
            fail("%s: an allowance for %s that nothing uses" % (where, name))


def metadata(root: Path) -> dict:
    done = subprocess.run(["cargo", "metadata", "--format-version", "1", "--locked", "--manifest-path",
                           str(root / "Cargo.toml")], capture_output=True, text=True, encoding="utf-8")
    if done.returncode:
        fail("cargo metadata failed in %s: %s" % (root.relative_to(ROOT), done.stderr.strip()))
        return {}
    return json.loads(done.stdout)


def graph(meta: dict) -> dict[str, set[str]]:
    by_id = {package["id"]: package["name"] for package in meta["packages"]}
    out: dict[str, set[str]] = {}
    for node in meta["resolve"]["nodes"]:
        name = by_id[node["id"]]
        if name.startswith("car-"):
            out[name] = {by_id[dep["pkg"]] for dep in node["deps"] if by_id[dep["pkg"]].startswith("car-")}
    return out


def check_graph(root: Path, members: set[str], expected: dict[str, set[str]]) -> None:
    meta = metadata(root)
    if not meta:
        return
    got = graph(meta)
    named = {name for name in got}
    members_found = {package["name"] for package in meta["packages"]
                     if package["id"] in set(meta["workspace_members"])}
    # the advanced graph also holds the standard crates it reaches; compare only the edges of `expected`
    if members_found != members:
        fail("%s workspace members differ: extra %s, missing %s" % (
            root.relative_to(ROOT), sorted(members_found - members), sorted(members - members_found)))
    for name, deps in expected.items():
        if name not in got:
            fail("%s: crate %s is not in the graph" % (root.relative_to(ROOT), name))
        elif got[name] != deps:
            fail("%s: %s depends on %s, expected %s (extra %s, missing %s)" % (
                root.relative_to(ROOT), name, sorted(got[name]), sorted(deps),
                sorted(got[name] - deps), sorted(deps - got[name])))
    if root == ADV:
        # the standard crates reached by path must have exactly the standard edges
        for name in named - set(expected):
            if got[name] != STANDARD[name]:
                fail("advanced graph: %s has edges %s, the standard workspace says %s" % (
                    name, sorted(got[name]), sorted(STANDARD[name])))


def lock_versions(root: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for block in read(root / "Cargo.lock").split("[[package]]")[1:]:
        name = re.search(r'name = "([^"]+)"', block)
        version = re.search(r'version = "([^"]+)"', block)
        if name and version:
            versions[name.group(1)] = version.group(1)
    return versions


def check_locks() -> None:
    standard, advanced = lock_versions(STD), lock_versions(ADV)
    for name in sorted(set(standard) & set(advanced)):
        if standard[name] != advanced[name]:
            fail("Cargo.lock: %s is %s in rust/ and %s in advanced/rust/" % (name, standard[name], advanced[name]))


# D3 (the owner's): every Windows call lives in car-platform. Only it may declare an `extern "system"` function or depend
# on the `windows` or `windows-sys` crate; a tiny binary where size and build time matter may take `windows-sys`, and is
# named here when there is one (none yet). Integration 6: the C runtime is held the same way - its `localtime` and
# `mktime` read Windows' zone - so only car-platform declares `extern "C"`, but for the C library's pure math named in
# C_MATH (a file and the one function it declares, with no state of Windows behind it).
WINDOWS_CALLERS = {"car-platform"}
# P6 step 0: car-host defines the six `extern "C" fn` exports of car_core.dll (abi.rs `export_core!`) and its tests name
# their types (`unsafe extern "C" fn(...)`). A definition is the DLL's own export, called by the C# host, and a fn type
# calls nothing; neither is a call into Windows. An `extern "C" { ... }` block (an import) stays car-platform's there as
# everywhere. The export table itself is held by car-host's tests/abi_exports.rs.
EXPORTERS = {"car-host"}
EXTERN_DEFINITION = re.compile(r'extern\s+"C"\s+fn\b')
TINY_BINARIES: set[str] = set()
EXTERN_SYSTEM = re.compile(r'extern\s+"(system|C)"')
# math.erfc: CPython calls the C library's, and so does car-brand's elevation colour (pyfmt.rs).
C_MATH = {"rust/crates/car-brand/src/pyfmt.rs": {"erfc"}}
LINK_NAME = re.compile(r'#\[link_name\s*=\s*"([^"]+)"\]')
FUNCTION = re.compile(r'\bfn\s+([A-Za-z_][A-Za-z0-9_]*)')


def c_math_only(source: Path, text: str, start: int) -> bool:
    """Whether the `extern "C"` block opening on line `start` (1-based) of `source` links only C_MATH's functions:
    each `fn` by its `#[link_name]` where it has one, else by its own name."""
    allowed = C_MATH.get(source.relative_to(ROOT).as_posix())
    if not allowed:
        return False
    linked, named = set(), None
    for line in text.splitlines()[start:]:
        if line.strip() == "}":
            break
        link = LINK_NAME.search(line)
        if link:
            named = link.group(1)
        function = FUNCTION.search(line)
        if function:
            linked.add(named or function.group(1))
            named = None
    return bool(linked) and linked <= allowed


WINDOWS_DEPENDENCY = re.compile(r'^\s*(windows|windows-sys)\s*[=.]', re.M)


def check_windows_calls_in_platform() -> None:
    """D3: no crate but car-platform declares a Windows function or links a Windows API crate."""
    for root in (STD, ADV):
        crates = root / "crates"
        if not crates.is_dir():
            continue
        for crate in sorted(path for path in crates.iterdir() if (path / "Cargo.toml").is_file()):
            name = crate.name
            if name in WINDOWS_CALLERS:
                continue
            manifest = read(crate / "Cargo.toml")
            for found in WINDOWS_DEPENDENCY.finditer(manifest):
                if not (found.group(1) == "windows-sys" and name in TINY_BINARIES):
                    fail("%s depends on %s: Windows calls live in car-platform (D3)" % (name, found.group(1)))
            for source in sorted(crate.rglob("*.rs")):
                if "target" in source.parts:
                    continue
                text = read(source)
                for number, line in enumerate(text.splitlines(), 1):
                    found = EXTERN_SYSTEM.search(line)
                    if not found or line.lstrip().startswith("//"):
                        continue
                    if found.group(1) == "C" and c_math_only(source, text, number):
                        continue
                    if name in EXPORTERS and EXTERN_DEFINITION.search(line):
                        continue
                    fail('%s:%d declares extern "%s": Windows calls live in car-platform (D3)'
                         % (source.relative_to(ROOT).as_posix(), number, found.group(1)))


def main() -> int:
    check_rustflags()
    check_windows_calls_in_platform()
    check_standard_never_names_advanced()
    check_graph(STD, set(STANDARD), STANDARD)
    if ADV.is_dir():
        check_shared_files()
        check_graph(ADV, set(ADVANCED), ADVANCED)
        check_locks()
    else:
        print("note: no advanced/rust here; the cross-workspace checks are skipped")
    if findings:
        print("\n".join("FAIL " + item for item in findings))
        return 1
    print("rust groundwork: OK (%d standard crates, %d advanced crates)" % (len(STANDARD), len(ADVANCED)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Holds the Rust groundwork to what PLAN.md 1.1-1.3 and 2 say it is. Python standard library only; run from anywhere:

    python rust/tools/check_groundwork.py

It checks, and exits 1 with every finding if one fails:

* the two workspaces' shared files agree (rust-toolchain.toml, .cargo/config.toml, deny.toml, tools/rustflags.sh, the
  [profile.*] tables), because a config file and a profile belong to the workspace root they sit in;
* tools/rustflags.sh repeats every rustflag of the config (RUSTFLAGS replaces the config's list whole);
* nothing under rust/ names advanced/ (D2: deleting advanced/ must change nothing the standard workspace reads);
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
    "car-bin": {"car-control", "car-watcher"},
    "car-host": {"car-control", "car-watcher"},
    "car-legacy": {"car-platform"},
    # dev only: it writes its replies through car-machine's Python-compatible JSON writer (S0.2) instead of an inline copy;
    # S1.1: and it calls the leaf crates it holds to the reference (src/leaves/), car-brand's edge added with car-brand's calls
    "car-harness": {"car-brand", "car-config", "car-machine", "car-words"},
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


def check_standard_never_names_advanced() -> None:
    for path in sorted(STD.rglob("*")):
        if not path.is_file() or "target" in path.relative_to(STD).parts:
            continue
        if path.suffix not in (".toml", ".rs", ".sh", ".lock"):
            continue
        for number, line in enumerate(read(path).splitlines(), 1):
            if "advanced" in line.lower():
                fail("%s:%d names advanced: %s" % (path.relative_to(ROOT).as_posix(), number, line.strip()))


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


def main() -> int:
    check_rustflags()
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

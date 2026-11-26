"""The edition audit over the Rust-shaped archives (PLAN 1.1, seat S8.1): build/edition_audit.py's checks, unchanged,
with the Rust payload's executables read as (d) reads ours.

build/edition_audit.py proves from the Python release's bytes that the standard archive holds nothing of the advanced
edition. Its checks (a) to (g) are this module's too, called as they are; what differs is only what the Rust payload
is made of, and each difference is the same allowance the Python audit already makes, in the Rust payload's own form:

  * (d) reads every executable of ours - the window and the MCP launcher as before, and the Rust binaries
    (app/bin, and car-legacy in runtime/) - for the advanced window's names and literals, in UTF-8 and UTF-16.
    RUST_EXECUTABLE_ALLOWED lets three of them spell the package's name and nothing else:
      - codex-auto-resume.exe and car_core.dll link car-policy's edition look (plug/edition.rs), which tells an
        installation's edition by whether the package's folder is beside the core, as edition.py does: the allowance
        ALLOWED gives edition.py itself (rust/tools/check_groundwork.py allows the same line in the source);
      - codex-auto-resume-setup.exe refuses an edition change without -AllowEditionChange (BRIDGE.md section 4) and
        so tells which edition is installed by the package's folder, as install.ps1 and the installer window do: the
        allowance EXECUTABLE_ALLOWED gives the window and SETUP_ALLOWED the C# setup program.
    car-legacy (runtime/) has none: it names no edition. In a Rust binary - app/bin, car-legacy and, since D18, the
    MCP launcher (rust_release.RUST_BUILT) - (d) leaves out the window's literals that are one plain lowercase word,
    which the standard library's own messages carry (`plain_word`), by the rule edition_audit.one_word gives (c); the
    C# window is read for every literal as before.
  * (f) lets the editions differ where each builds its own: the window and the manifest's display name as before, and
    (D2) the three binaries of app/bin, and the handover marker's `edition` (BRIDGE.md: the edition the archive is).
    The advanced archive adds only in its own places, and has the package's __init__.py, which is all an old
    Test-Archive and edition reader look for (the Rust core has no plug.py to require).
  * (g) and (c) read every other entry as they always do. The stubs of D9 are text and spell no advanced name.
  * (e) builds the standard archive again from `git archive HEAD` with advanced/ deleted - the Rust workspace, the C#
    window and this archive - in another folder, and needs the same bytes (`--rebuild`; slow). That is also the
    reproducibility proof: two builds, two folders, one archive.
  * (h) reads the one-file Setup exes around the two archives where they are in the dist folder (S8.2's choice:
    build/make_setup.py's C# program, unchanged, which `rust_release.py --setup` builds): each carries its own
    edition's archive byte for byte with its SHA-256, and the standard one holds nothing of the advanced edition
    outside it - edition_audit.check_setups, as the Python audit reads them; with --rebuild, the standard one is built
    again around (e)'s rebuilt archive and must be the same file. `--setups` makes them required.

    python build/rust_edition_audit.py --dist build/dist/rust --version 0.6.27-alpha [--rebuild] [--setups]
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import edition_audit as audit  # noqa: E402
import make_release  # noqa: E402
import make_setup  # noqa: E402
import rust_release  # noqa: E402

CORE = "payload/app/bin/codex-auto-resume.exe"
DLL = "payload/app/bin/car_core.dll"
SETUP = rust_release.SETUP
RUST_EXECUTABLES = audit.EXECUTABLES + rust_release.BINARIES
EDITION_LOOK = audit.ALLOWED[("payload/app/src/codex_auto_resume/edition.py", audit.PACKAGE)]
RUST_EXECUTABLE_ALLOWED = dict(audit.EXECUTABLE_ALLOWED)
RUST_EXECUTABLE_ALLOWED.update({
    (CORE, audit.PACKAGE): "car-policy's edition look (plug/edition.rs) - " + EDITION_LOOK,
    (DLL, audit.PACKAGE): "car-policy's edition look (plug/edition.rs) - " + EDITION_LOOK,
    (SETUP, audit.PACKAGE): "the setup program refuses an edition change by install.ps1's rule - "
                            + audit.SETUP_ALLOWED[audit.PACKAGE],
})
# (f): what each edition builds for itself.
PER_EDITION = (audit.WINDOW,) + tuple(rust_release.EDITION_BINARIES.values())
REQUIRED_ADVANCED = ("payload/app/src/%s/__init__.py" % make_release.ADVANCED_PACKAGE,)


def plain_word(literal: str) -> bool:
    """One plain lowercase word (`capacity`, `returned`): every Rust binary carries such words in the standard
    library's own messages ("capacity overflow"), as every program has `create` and `records` - the words
    edition_audit.one_word leaves out of (c) for that reason. The advanced window's other literals are still looked for."""
    return literal.isascii() and literal.isalpha() and literal.islower()


def check_executables(standard: dict, tree: audit.Inventory) -> tuple[list, set]:
    """(d) over every executable of ours in the Rust payload; the findings and the allowances that were needed."""
    found, used = [], set()
    for entry in RUST_EXECUTABLES:
        data = standard.get(entry)
        if data is None:
            found.append("(d) the standard archive has no %s to read" % entry)
            continue
        for name in sorted(tree.window):
            if not audit._holds(data, name, word=name not in (audit.PACKAGE, audit.SKILL, audit.SENTINEL)):
                continue
            if (entry, name) in RUST_EXECUTABLE_ALLOWED:
                used.add((entry, name))
            else:
                found.append("(d) %s holds %s" % (entry, name))
        for literal in sorted(tree.literals):
            if entry in rust_release.RUST_BUILT and plain_word(literal):
                continue
            if audit._holds(data, literal, word=False):
                found.append("(d) %s holds the literal %r" % (entry, literal))
    return found, used


def _markers(standard: bytes, advanced: bytes) -> list:
    try:
        ours, theirs = json.loads(standard), json.loads(advanced)
    except ValueError:
        return ["(f) the handover marker cannot be read"]
    if ours.get("edition") != "standard" or theirs.get("edition") != "advanced":
        return ["(f) the handover markers do not name their own editions"]
    if dict(ours, edition="advanced") != theirs or standard.replace(b'"standard"', b'"advanced"') != advanced:
        return ["(f) the handover markers differ in more than the edition"]
    return []


def check_superset(standard: dict, advanced: dict) -> list:
    """(f) for the Rust payload."""
    found = []
    for name, data in standard.items():
        if name not in advanced:
            found.append("(f) %s is missing from the advanced archive" % name)
        elif name in PER_EDITION:
            continue
        elif name == audit.MANIFEST:
            found += audit._manifests(data, advanced[name])
        elif name == rust_release.MARKER:
            found += _markers(data, advanced[name])
        elif advanced[name] != data:
            found.append("(f) %s differs in the advanced archive" % name)
    for name in advanced:
        if name not in standard and not any(name.startswith(place) for place in audit.PLACEMENTS):
            found.append("(f) the advanced archive adds %s outside its own places" % name)
    for name in REQUIRED_ADVANCED:
        if name not in advanced:
            found.append("(f) the advanced archive has no %s" % name)
    return found


def rebuild_standard(root: Path, work: Path, release: str, setup: bool = False) -> Path:
    """(e): the standard Rust-shaped archive built again from `git archive HEAD` with advanced/ deleted first, in
    another folder: its Rust workspace, its window, its archive."""
    tree = work / "tree"
    with tarfile.open(fileobj=io.BytesIO(audit._git(root, "archive", "--format=tar", "HEAD"))) as exported:
        exported.extractall(tree, filter="data")
    shutil.rmtree(tree / "advanced", ignore_errors=True)
    if (tree / "advanced").exists():
        raise SystemExit("(e) advanced/ could not be deleted from the exported tree")
    bash = shutil.which("bash")
    environment = dict(os.environ, CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", "2"))
    steps = (("cargo build", [bash, "-c", ". tools/rustflags.sh release && cargo build --release --locked"],
              tree / "rust"),
             ("make_gui.ps1", [audit._powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(tree / "build" / "make_gui.ps1"), "-Root", str(tree)], tree),
             ("rust_release.py", [sys.executable, str(tree / "build" / "rust_release.py"), "--edition", "standard",
                                  "--version", release, "--output", str(work / "dist")] + (["--setup"] if setup else []),
              tree))
    for step, command, folder in steps:
        done = subprocess.run(command, cwd=folder, env=environment, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=3600, creationflags=audit.NO_WINDOW)
        if done.returncode != 0:
            raise SystemExit("(e) the rebuild's %s failed:\n%s" % (step, (done.stderr or done.stdout)[-3000:]))
    return work / "dist" / rust_release.archive_name("standard", release)


def run(standard: Path, advanced: Path, release: str, rebuild: bool, root: Path = ROOT,
        tree: audit.Inventory | None = None, setups: tuple | None = None) -> tuple[list, set]:
    """Every finding, and the allowances that were needed. `tree` is the repository's advanced inventory, when the
    caller has it already; `setups`, the standard and the advanced one-file Setup exe for (h)."""
    tree = tree or audit.inventory(root)
    ours, theirs = audit.entries(standard), audit.entries(advanced)
    opened = audit.expand(ours)
    found = audit.check_paths(opened) + audit.check_digests(opened, tree)
    names, used_names = audit.check_names(opened, tree)
    found += names
    executables, used = check_executables(ours, tree)
    found += executables
    found += audit.check_binaries({name: data for name, data in opened.items() if name not in RUST_EXECUTABLES})
    found += check_superset(ours, theirs)
    if setups:
        found += audit.check_setups(standard.read_bytes(), advanced.read_bytes(), setups[0].read_bytes(),
                                    setups[1].read_bytes(), tree)
    if rebuild:
        with tempfile.TemporaryDirectory(prefix="rust-edition-audit-") as work:
            rebuilt = rebuild_standard(root, Path(work), release, setup=bool(setups))
            found += audit.check_rebuild(standard, rebuilt)
            if setups:
                found += audit.check_setup_rebuild(setups[0], rebuilt.parent / setups[0].name)
    return found, used | used_names


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="The edition audit over the Rust-shaped archives.")
    parser.add_argument("--dist", default=str(rust_release.OUT))
    parser.add_argument("--version", default=None)
    parser.add_argument("--rebuild", action="store_true", help="(e): build the standard archive again without advanced/")
    parser.add_argument("--setups", action="store_true", help="(h): the two one-file Setup exes must be there")
    args = parser.parse_args(argv)
    release = args.version or rust_release.version()
    standard = Path(args.dist) / rust_release.archive_name("standard", release)
    advanced = Path(args.dist) / rust_release.archive_name("advanced", release)
    for archive in (standard, advanced):
        if not archive.is_file():
            raise SystemExit("missing %s - build both editions with build/rust_release.py" % archive)
    setups = tuple(Path(args.dist) / make_setup.setup_name(edition, release) for edition in ("standard", "advanced"))
    if not all(setup.is_file() for setup in setups):
        if args.setups:
            raise SystemExit("missing %s - build them with build/rust_release.py --setup" % " or ".join(map(str, setups)))
        setups = None
    print("edition audit of %s and %s%s%s" % (standard.name, advanced.name,
                                            ", and their Setup exes" if setups else "",
                                            " (with (e)'s rebuild)" if args.rebuild else ""))
    found, used = run(standard, advanced, release, args.rebuild, setups=setups)
    for entry, name in sorted(used):
        print("  allowed: %s spells %s" % (entry, name))
    for line in found:
        print("  " + line)
    if found:
        print("the standard archive is not proven free of the advanced edition")
        return 1
    print("  (a)-(%s)%s found nothing: the standard archive holds none of the advanced edition"
          % ("h" if setups else "g", "" if args.rebuild else " but (e)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

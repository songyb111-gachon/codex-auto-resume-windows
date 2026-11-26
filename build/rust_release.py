"""Assemble a Rust-shaped release archive: the packaging skeleton (PLAN 6.1, seat S8.1).

The Python release is build/make_release.py, and nothing here changes it or what it builds. This is the shape every
Rust release keeps, built now on the stub core so the parts that cannot change later - what an installed Python
version's updater requires of an archive, and what v0.6.26's setup handover reads - are proved before the core lands:

  payload/CodexAutoResumeSettings.exe, payload/codex-auto-resume.ico   the window (C#), as today
  payload/app/bin/codex-auto-resume.exe                                the Rust core's console program (car-bin)
  payload/app/bin/codex-auto-resume-setup.exe                          its setup program, GUI subsystem (BRIDGE.md)
  payload/app/bin/car_core.dll                                         the core the watcher host loads (car-host)
  payload/app/mcp/codex-auto-resume-mcp.exe, payload/app/.mcp.json     the MCP launcher and its declaration, as today
  payload/app/.codex-plugin, .agents, skills, assets, docs, README...  the plugin tree Codex reads, as today
  payload/app/src/codex_auto_resume/{data,locales,mcp/assets}/...      the data the core reads, at the same paths
  payload/app/scripts/bootstrap.ps1, release.json                      the updater, as today
  payload/runtime/python.exe, pythonw.exe                              car-legacy, the stand-ins (D9 means 1)
  payload/app/src/codex_auto_resume/mcpserver.py                       content-free stubs every published
  payload/app/scripts/plugin_setup.py                                    Test-Archive requires (D9 means 1)
  install/install.ps1, Install.cmd, Uninstall.cmd, README.txt          the installer and its launchers
  setup-handover.json                                                  v0.6.26's marker (D9 means 2, BRIDGE.md)

and in the advanced edition, besides: payload/app/src/codex_auto_resume_advanced/__init__.py (a stub that carries the
sentinel line, which old Test-Archives and edition readers look for), the package's data files at their paths, and
payload/app/skills/codex-auto-resume-advanced/.

`install/install.ps1` is build/rust_install/install.ps1 (seat S8.2): v0.6.26's installer on the Rust core, with the
migration from a Python installation (PLAN 6.2-6.5). Every route ends in it - an earlier version's updater that accepted
the archive, the one-file Setup exe's Install.cmd, and v0.6.26's setup handover through codex-auto-resume-setup.exe.
The window is
the C# one build/make_gui.ps1 compiles (`--window` takes another); the MCP launcher is car-bin's codex-auto-resume-mcp.exe
from the standard workspace's cargo build (D18; `--mcp-launcher` takes another); the watcher host
(CodexAutoResume.exe, seat S6.2) is not built yet and is not in the archive.

    python build/rust_release.py --edition standard [--version 0.6.27-alpha] [--build] [--setup] [--output DIR]

`--setup` also builds the one-file Setup exe around the archive just written (seat S8.2's choice): build/make_setup.py's,
unchanged - the C# setup window around the archive's bytes, which runs the archive's Install.cmd and so the same
install\\install.ps1 every other route ends in. The setup program inside the archive (codex-auto-resume-setup.exe) is
v0.6.26's handover's; the one-file Setup exe is what a person downloads, as for every Python release.

`--build` builds the edition's workspace first, the way every checked build is made (tools/rustflags.sh release,
--locked); otherwise the binaries are taken from each workspace's target/release. The same inputs give the same bytes:
file order, timestamps and compression are fixed as in make_release, and the Rust binaries are reproducible
(rust/GROUNDWORK.md).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import make_release  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Inside the folders make_release uses (and .gitignore leaves out), never over what it writes there.
OUT = ROOT / "build" / "dist" / "rust"
STAGES = ROOT / "build" / "stage"
EDITIONS = make_release.EDITIONS
WORKSPACES = {"standard": ROOT / "rust", "advanced": ROOT / "advanced" / "rust"}

# The marker v0.6.26's bootstrap reads (BRIDGE.md section 1): at the archive's root, beside Install.cmd.
MARKER = "setup-handover.json"
MARKER_FORMAT = "codex-auto-resume/setup-handover/1"
SETUP = "payload/app/bin/codex-auto-resume-setup.exe"

# What each edition's Rust workspace builds into the archive's app/bin (PLAN 1.7): built per edition (D2).
EDITION_BINARIES = {"codex-auto-resume.exe": "payload/app/bin/codex-auto-resume.exe",
                    "codex-auto-resume-setup.exe": SETUP,
                    "car_core.dll": "payload/app/bin/car_core.dll"}
# car-legacy, from the standard workspace in both editions: one stand-in for every installation (D9).
LEGACY_BINARIES = {"python.exe": "payload/runtime/python.exe", "pythonw.exe": "payload/runtime/pythonw.exe"}
BINARIES = tuple(EDITION_BINARIES.values()) + tuple(LEGACY_BINARIES.values())
# car-bin's MCP launcher, from the standard workspace in both editions like car-legacy (D18): where the C# one was.
MCP_LAUNCHER = "payload/app/mcp/" + make_release.MCP_EXE
# Every executable of the payload that cargo builds (the window is the C# one).
RUST_BUILT = BINARIES + (MCP_LAUNCHER,)
# The installer proofs' test forward, by the variable it reads, and the stub core, by the line only it says (car-bin).
TEST_HOOK = b"CODEX_AUTO_RESUME_TEST_CORE"
STUB_CORE = b"is not ported yet (stub core); nothing was done"

# The Python trees' files the Rust product still ships: the data the core reads at their paths (PLAN 6.1), and the
# plugin tree Codex reads. Every .py file is left out; the stubs below take the places old updaters require.
DATA_TREES = ("src/codex_auto_resume",)
PLUGIN_TREES = ("skills", ".codex-plugin", ".agents")
SHIPPED_SCRIPTS = ("bootstrap.ps1", "release.json")
ADVANCED_DATA = ("advanced/src/" + make_release.ADVANCED_PACKAGE, "src/" + make_release.ADVANCED_PACKAGE)
ADVANCED_SKILL = ("advanced/skills/" + make_release.ADVANCED_SKILL, "skills/" + make_release.ADVANCED_SKILL)

# The content-free stubs (D9 means 1): every published Test-Archive requires the first two, and an advanced archive is
# told by the third (Test-Archive -Edition advanced, Get-Edition, gui/InstallerFlow.cs EditionOfSource). Nothing runs
# them; car-legacy reads only the path an updater names. The same bytes in both editions.
STUB_NOTE = ("# Codex Auto Resume is not Python from v0.6.27. The updater of every earlier version requires this file in "
             "the archive (D9); nothing reads or runs it.\n")
STUBS = {
    "payload/app/src/codex_auto_resume/mcpserver.py": STUB_NOTE,
    "payload/app/scripts/plugin_setup.py": STUB_NOTE + (
        "# Such an updater starts runtime\\python.exe with this path and a command; runtime\\python.exe is car-legacy, "
        "which hands the command to app\\bin\\codex-auto-resume.exe.\n"),
}
# The sentinel line every shipped advanced file begins with (build/edition_audit.py SENTINEL), then the stub's note.
ADVANCED_STUB = ("payload/app/src/%s/__init__.py" % make_release.ADVANCED_PACKAGE,
                 "# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.\n" + STUB_NOTE)

# The installer (seat S8.2): every route into a Rust archive ends in it, and an earlier version's updater runs it after
# its Test-Archive accepted the archive. Shipped as the working tree has it (CRLF, as .gitattributes checks *.ps1 out).
INSTALLER = ROOT / "build" / "rust_install" / "install.ps1"
LAUNCHERS = ("Install.cmd", "Uninstall.cmd", "README.txt")


def version() -> str:
    return make_release.version()


def archive_name(edition: str, release: str) -> str:
    """The name every bootstrap builds from its release.json: the Python release's, unchanged."""
    return make_release.archive_name(edition, release)


def built(edition: str) -> Path:
    return WORKSPACES[edition] / "target" / "release"


def build(edition: str) -> None:
    """The edition's workspace, and the standard one for car-legacy, built as every checked build is."""
    workspaces = [WORKSPACES["standard"]] + ([WORKSPACES[edition]] if edition != "standard" else [])
    environment = dict(os.environ, CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", "2"))
    bash = shutil.which("bash")
    if not bash:
        raise SystemExit("bash is needed to source tools/rustflags.sh")
    for workspace in workspaces:
        done = subprocess.run([bash, "-c", ". tools/rustflags.sh release && cargo build --release --locked"],
                              cwd=workspace, env=environment, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", creationflags=NO_WINDOW)
        if done.returncode != 0:
            raise SystemExit("cargo build in %s failed:\n%s" % (workspace, done.stderr[-3000:]))


def copy(source: Path, stage: Path, entry: str) -> None:
    if not source.is_file():
        raise SystemExit("missing %s" % source)
    destination = stage / entry
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def write(stage: Path, entry: str, data: bytes) -> None:
    destination = stage / entry
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def subsystem(image: bytes) -> int | None:
    """The PE image's subsystem (2 GUI, 3 console), or None for no executable image."""
    if len(image) < 64 or image[:2] != b"MZ":
        return None
    offset = int.from_bytes(image[60:64], "little")
    if offset < 64 or offset + 94 > len(image) or image[offset:offset + 4] != b"PE\0\0":
        return None
    return int.from_bytes(image[offset + 92:offset + 94], "little")


def collect_binaries(stage: Path, edition: str, bins: Path | None, legacy: Path | None) -> None:
    bins = bins or built(edition)
    legacy = legacy or built("standard")
    for name, entry in EDITION_BINARIES.items():
        copy(bins / name, stage, entry)
    for name, entry in LEGACY_BINARIES.items():
        copy(legacy / name, stage, entry)
    # PLAN 6.7 and BRIDGE.md 2.4: what Windows starts with no console is GUI, what a program reads the streams of is
    # console. A swapped pair would open a console window at sign-in, or be refused by the handover.
    wanted = {SETUP: 2, "payload/runtime/pythonw.exe": 2, "payload/runtime/python.exe": 3,
              "payload/app/bin/codex-auto-resume.exe": 3}
    for entry, kind in wanted.items():
        found = subsystem((stage / entry).read_bytes())
        if found != kind:
            raise SystemExit("%s is of subsystem %s, not %d" % (entry, found, kind))
    # The installer proofs' test forward (car-bin `test_double`, CODEX_AUTO_RESUME_TEST_CORE) is the stub core's alone
    # (review 9, note 8): the stub never ships as a release (it answers every command with 3), and the real core (P5)
    # has no forward. A core that names the forward but is not the stub stops the build, so a test hook can never reach
    # a release archive.
    for name, entry in EDITION_BINARIES.items():
        data = (stage / entry).read_bytes()
        if TEST_HOOK in data and STUB_CORE not in data:
            raise SystemExit("%s carries the installer proofs' test forward (%s) and is not the stub core"
                             % (entry, TEST_HOOK.decode("ascii")))


def collect_tree(stage: Path, source: str, placed: str, data_only: bool) -> int:
    """A tracked tree's files under payload/app/<placed>, by make_release's rule of what is wanted; with `data_only`,
    none of its Python."""
    count = 0
    for entry in sorted((ROOT / source).rglob("*")):
        relative = entry.relative_to(ROOT)
        if not entry.is_file() or not make_release._wanted(relative):
            continue
        if data_only and entry.suffix.lower() in (".py", ".pyw"):
            continue
        destination = stage / "payload" / "app" / placed / entry.relative_to(ROOT / source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry, destination)
        count += 1
    return count


def collect_app(stage: Path, edition: str, release: str) -> None:
    app = stage / "payload" / "app"
    for tree in DATA_TREES:
        collect_tree(stage, tree, tree, data_only=True)
    for tree in PLUGIN_TREES:
        collect_tree(stage, tree, tree, data_only=False)
    for name in make_release.SHIPPED_ASSETS:
        copy(ROOT / "assets" / name, stage, "payload/app/assets/" + name)
    for name in SHIPPED_SCRIPTS:
        copy(ROOT / "scripts" / name, stage, "payload/app/scripts/" + name)
    for name in make_release.APP_FILES:
        source = ROOT / make_release.APP_SOURCES.get(name, name)
        if name == make_release.CHANGELOG:
            text = source.read_bytes().decode("utf-8")
            try:
                entry = make_release.newest_changelog(text, release)
            except SystemExit:
                if release == version():
                    raise
                # A skeleton build under another version than the tree's: its own one-line entry.
                entry = "# Changelog\n\n## v%s\n\nA packaging skeleton build on the stub core; not a release.\n" % release
            write(stage, "payload/app/" + name, entry.encode("utf-8"))
        else:
            copy(source, stage, "payload/app/" + name)
    readme = app / "README.md"
    carried = {path.relative_to(app).as_posix() for path in app.rglob("*") if path.is_file()}
    readme.write_bytes(make_release.absolute_links(readme.read_bytes().decode("utf-8"), release, carried).encode("utf-8"))
    for entry, text in STUBS.items():
        write(stage, entry, text.encode("utf-8"))
    if edition == "advanced":
        collect_tree(stage, ADVANCED_DATA[0], ADVANCED_DATA[1], data_only=True)
        collect_tree(stage, ADVANCED_SKILL[0], ADVANCED_SKILL[1], data_only=False)
        write(stage, ADVANCED_STUB[0], ADVANCED_STUB[1].encode("utf-8"))
    for name in make_release.REQUIRED_APP_FILES:
        if not (app / name).is_file():
            raise SystemExit("missing %s in the payload" % name)


def collect_window(stage: Path, edition: str, window: Path | None, launcher: Path | None,
                   legacy: Path | None = None) -> None:
    """The C# window make_gui.ps1 built from this tree (its stamp checked) and car-bin's MCP launcher from the standard
    workspace's build (`legacy`'s folder, where car-legacy is: one launcher for both editions, D18), or the ones given."""
    if window is None:
        window = (make_release.BUILT / "advanced" if edition == "advanced" else make_release.BUILT) / make_release.GUI_EXE
        make_release.check_built_for_this_tree(window, edition, "window")
    if launcher is None:
        launcher = (legacy or built("standard")) / make_release.MCP_EXE
    copy(window, stage, "payload/" + make_release.GUI_EXE)
    copy(ROOT / "assets" / "codex-auto-resume.ico", stage, "payload/codex-auto-resume.ico")
    copy(launcher, stage, MCP_LAUNCHER)


def collect_launchers(stage: Path) -> None:
    for name in LAUNCHERS:
        copy(ROOT / "build" / "install" / name, stage, name)
    copy(INSTALLER, stage, "install/install.ps1")


def declare(stage: Path, edition: str, release: str) -> None:
    """The payload's manifest as make_release writes it (mcpServers, the advanced display name), at `release`."""
    make_release.declare_mcp_server(stage, edition)
    path = stage / "payload" / "app" / ".codex-plugin" / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["version"] != release:
        manifest["version"] = release
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def marker(edition: str, release: str) -> bytes:
    return (json.dumps({"format": MARKER_FORMAT, "version": release, "edition": edition, "setup": SETUP}) + "\n"
            ).encode("utf-8")


def stage_edition(stage: Path, edition: str, release: str, bins=None, legacy=None, window=None, launcher=None) -> Path:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    collect_binaries(stage, edition, bins, legacy)
    collect_app(stage, edition, release)
    collect_window(stage, edition, window, launcher, legacy)
    collect_launchers(stage)
    declare(stage, edition, release)
    write(stage, MARKER, marker(edition, release))
    return stage


def deflated(data: bytes) -> int:
    """What one file weighs in the archive: raw deflate at level 9, as write_archive packs it."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    return len(packer.compress(data) + packer.flush())


def weights(stage: Path) -> dict:
    """The packed bytes by group: the binaries of the edition (app/bin), car-legacy (runtime), the rest of the app (the
    app payload as release_budget.json counts it, binaries aside), and the archive's root and window."""
    groups = {"binaries": 0, "legacy": 0, "app": 0, "other": 0}
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        entry = path.relative_to(stage).as_posix()
        size = deflated(path.read_bytes())
        if entry.startswith("payload/app/bin/"):
            groups["binaries"] += size
        elif entry.startswith("payload/runtime/"):
            groups["legacy"] += size
        elif entry.startswith("payload/app/"):
            groups["app"] += size
        else:
            groups["other"] += size
    return groups


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a Rust-shaped release archive (the packaging skeleton).")
    parser.add_argument("--edition", choices=EDITIONS, default="standard")
    parser.add_argument("--version", default=None, help="the release's version (default: .codex-plugin/plugin.json's)")
    parser.add_argument("--output", default=str(OUT))
    parser.add_argument("--stage", default=None, help="where to stage (default: build/stage/rust-<edition>)")
    parser.add_argument("--build", action="store_true", help="build the Rust workspaces first")
    parser.add_argument("--bins", default=None, help="the edition's built binaries (default: its target/release)")
    parser.add_argument("--legacy-bins", default=None, help="car-legacy's (default: rust/target/release)")
    parser.add_argument("--window", default=None, help="a settings window other than make_gui.ps1's")
    parser.add_argument("--mcp-launcher", default=None, help="an MCP launcher other than make_gui.ps1's")
    parser.add_argument("--setup", action="store_true",
                        help="also build the one-file Setup exe around the archive (build/make_setup.py's)")
    args = parser.parse_args(argv)
    release = args.version or version()
    if args.build:
        build(args.edition)
    stage = Path(args.stage) if args.stage else STAGES / ("rust-" + args.edition)
    stage_edition(stage, args.edition, release,
                  bins=Path(args.bins) if args.bins else None,
                  legacy=Path(args.legacy_bins) if args.legacy_bins else None,
                  window=Path(args.window) if args.window else None,
                  launcher=Path(args.mcp_launcher) if args.mcp_launcher else None)
    target = make_release.write_archive(stage, Path(args.output) / archive_name(args.edition, release))
    digest = make_release.write_sidecar(target)
    setup = None
    if args.setup:
        import make_setup  # noqa: E402  (the C# compiler, only where it is asked for)
        setup = make_setup.build(target, Path(args.output), args.edition, release)
        make_release.write_sidecar(setup)
    groups = weights(stage)
    print("version        : %s" % release)
    print("edition        : %s" % args.edition)
    print("archive        : %s" % target)
    print("size           : %d bytes" % target.stat().st_size)
    print("sha256         : %s" % digest)
    if setup is not None:
        print("setup program  : %s (%d bytes)" % (setup, setup.stat().st_size))
    for group, size in groups.items():
        print("packed %-8s: %d bytes (%.3f MiB)" % (group, size, size / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())

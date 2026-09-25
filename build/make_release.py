"""Assemble the self-contained Windows release archive.

The result is one ZIP a person downloads, unpacks and double-clicks. It carries its own
Python, so a clean Windows machine with no system Python and no developer tooling can
install and run the watcher.

Two decisions worth stating, both learned the hard way:

* Our code ships as **loose .py files**, never zipped onto the path. ``PROJECT_ROOT`` is
  ``parents[2]`` of config.py, so packing src into an archive silently redirects it to
  the runtime directory, points ``entry_script`` at a file that does not exist and
  breaks the ``shutil.copyfile`` that installs the launcher. Loose files are also
  exactly how Codex's own plugin cache delivers us, so there is one layout, not two.
* The payload doubles as a **local Codex marketplace**, so installing the plugin needs
  no network and installs the same bytes that were verified here.

What is fixed here: file order, entry timestamps, compression level, and the absence of
any build-host path. The two C# executables are made repeatable separately: the in-box
compiler stamps every assembly with a fresh timestamp and module version GUID, and
build/normalize_pe.py replaces both with values derived from the rest of the file (see
build/make_gui.ps1). Two builds from fresh clones of one commit, on one machine with the
same compiler, produced a byte-identical archive. That is all that has been shown: a
build on another machine, or with another compiler build, has not been compared. Every
archive published up to v0.5.7 was built before this and is not reproducible.

Two editions, one build. `--edition standard` - the default - is the build as it always was,
and reads nothing of the repository's `advanced/` tree: APP_TREES does not name it, and nothing
is filtered out, so there is no exclusion anyone could forget. `--edition advanced` is that same
build with ADVANCED_TREES added, its own settings window, and one display name changed in the
payload manifest. Each edition is staged in a directory of its own under build/stage/, so
building one never wipes the other. build/edition_audit.py proves from the two archives' bytes
that the standard one holds nothing of the advanced edition, and that the advanced one differs
from it only there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "cache"
OUT = ROOT / "build" / "dist"
# Where build/make_gui.ps1 leaves the executables, and where each edition's payload is staged.
BUILT = ROOT / "build"
STAGES = ROOT / "build" / "stage"

# Pinned so the bundled runtime is a known build rather than whatever python.org serves
# today. Verified against the published sigstore/spdx artefacts.
PYTHON_VERSION = "3.13.15"
PYTHON_ZIP = "python-%s-embed-amd64.zip" % PYTHON_VERSION
PYTHON_URL = "https://www.python.org/ftp/python/%s/%s" % (PYTHON_VERSION, PYTHON_ZIP)
PYTHON_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"

# Everything the installed product needs, and nothing else. Listed explicitly rather
# than filtered, so a stray file in the working tree cannot reach a release.
APP_TREES = ("src", "scripts", "skills", ".codex-plugin", ".agents", "assets")
# Data files inside those trees that the product reads at run time. The trees are copied by
# walking them, so nothing would notice one going missing until a user's machine did: the
# bundled Compatibility Registry baseline would silently become "missing", and every
# capability would fall back to the local checks alone. Checked after the copy, and the
# baseline is also parsed by the validator that will read it, so a build cannot ship data
# the product would refuse.
REQUIRED_APP_FILES = ("src/codex_auto_resume/data/codex_compat.json",
                      # Without these the panel in Codex is an empty white rectangle.
                      "src/codex_auto_resume/mcp/assets/panel.css",
                      "src/codex_auto_resume/mcp/assets/panel.js")
# Built, not copied from the working tree: see build/make_gui.ps1.
GUI_EXE = "CodexAutoResumeSettings.exe"
# Codex only accepts a plugin MCP command that is a bare executable name or a path
# inside the plugin, so the launcher ships in the plugin payload and finds the bundled
# interpreter itself. `.mcp.json` names it by that contained path.
MCP_EXE = "codex-auto-resume-mcp.exe"
# Every top-level document the shipped README links to, so the installed copy does not
# promise a privacy policy that is not beside it. Asserted by tests/test_plugin.py.
#
# English only: a release is built from a tag on main, and main holds no Korean document
# (they are written on dev and read on the generated ko branch). The three Korean ones this
# used to ship left with them; no published bootstrap requires any of them.
APP_FILES = ("LICENSE", "README.md", "docs/PRIVACY.md", "docs/SECURITY.md", "docs/SUPPORT.md",
             "docs/CONTRIBUTING.md", "docs/CONTRIBUTORS.md", "docs/CHANGELOG.md", ".mcp.json")
# Where an APP_FILES entry comes from when it is not at its own path in the repository. The
# payload keeps `.mcp.json` at its root - every published bootstrap requires
# payload/app/.mcp.json - while the repository keeps its source in build/, off the front page
# and out of sight of tools that read a `.mcp.json` at a project's root and try to start a
# server this checkout does not have.
APP_SOURCES = {".mcp.json": "build/plugin-mcp.json"}
LAUNCHER_FILES = ("Install.cmd", "Uninstall.cmd", "README.txt", "install.ps1")

# The editions (src/codex_auto_resume/domain/plug.py, Edition). The advanced one is the standard
# one plus what follows, and nothing is ever taken away from either.
EDITIONS = ("standard", "advanced")
# The advanced package and skill. Core takes the package only from beside itself, in the same
# `src` directory (src/codex_auto_resume/edition.py), so that is where the payload puts it; the
# skill goes beside the standard one, where Codex reads the plugin's skills.
ADVANCED_PACKAGE = "codex_auto_resume_advanced"
ADVANCED_SKILL = "codex-auto-resume-advanced"
# What the advanced build adds, from where in the repository to where under payload/app. In the
# repository both live under `advanced/`, outside every tree above: a plugin added from GitHub
# never loads the skill (.codex-plugin/plugin.json reads ./skills/), and the standard build has
# no path that reaches either.
ADVANCED_TREES = (("advanced/src/" + ADVANCED_PACKAGE, "src/" + ADVANCED_PACKAGE),
                  ("advanced/skills/" + ADVANCED_SKILL, "skills/" + ADVANCED_SKILL))
# Without the package the archive is the standard edition under the advanced name, and without
# its plug an installation of it runs as the standard edition with a badge that says so.
REQUIRED_ADVANCED_FILES = ("src/%s/__init__.py" % ADVANCED_PACKAGE,
                           "src/%s/plug.py" % ADVANCED_PACKAGE)
# The word the advanced edition adds to the name Codex shows for the plugin: the badge its plug
# carries (advanced/src/codex_auto_resume_advanced/plug.py).
ADVANCED_WORD = "Advanced"

EXCLUDE_DIRS = {"__pycache__", ".git", ".github", "node_modules", ".pytest_cache",
                "comparison", "config", "logs", "build", "tests", ".venv", "venv"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite-wal", ".sqlite-shm"}
EXCLUDE_NAMES = {".owned-by-codex-auto-resume", "runtime.json", "settings.json",
                 "state.sqlite", ".DS_Store", "Thumbs.db"}

# A fixed timestamp removes one source of build-to-build variation. The module docstring
# says what else is needed, and how far the result has been checked.
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def version() -> str:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
    return str(manifest["version"])


def archive_name(edition: str, release: str) -> str:
    """The archive's file name, from the template scripts/release.json holds for its edition.

    Every bootstrap builds the name it downloads from that same file, so the name a build writes
    and the name an installation asks for cannot drift apart. The top-level `archive` is the
    standard edition's, as it always was; the advanced one is a constant of its own."""
    templates = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8"))
    template = templates["archive"] if edition == "standard" else templates[edition]["archive"]
    return template.replace("{version}", release)


def fetch_runtime() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / PYTHON_ZIP
    if not archive.is_file():
        print("downloading %s" % PYTHON_URL)
        with urllib.request.urlopen(PYTHON_URL, timeout=180) as response:
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        raise SystemExit("runtime checksum mismatch: expected %s, got %s" % (PYTHON_SHA256, digest))
    return archive


def _wanted(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES or path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    return not any(part in EXCLUDE_DIRS for part in path.parts)


def collect_app(stage: Path) -> int:
    """Copy the application payload, which is also a valid local Codex marketplace."""
    app = stage / "payload" / "app"
    copied = 0
    for tree in APP_TREES:
        source = ROOT / tree
        if not source.is_dir():
            continue
        for entry in sorted(source.rglob("*")):
            if not entry.is_file() or not _wanted(entry.relative_to(ROOT)):
                continue
            destination = app / entry.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, destination)
            copied += 1
    for name in APP_FILES:
        source = ROOT / APP_SOURCES.get(name, name)
        if source.is_file():
            # Some ship from docs/ since v0.6.10-alpha, and copyfile makes no folders.
            (app / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, app / name)
            copied += 1
    return copied


def collect_advanced(stage: Path) -> int:
    """Add the advanced edition's package and skill to a payload collect_app has filled.

    Copied the way collect_app copies a tree, by the same rule for what is wanted, and only
    ever added: nothing already in the payload is replaced or removed here."""
    app = stage / "payload" / "app"
    copied = 0
    for tree, placed in ADVANCED_TREES:
        source = ROOT / tree
        if not source.is_dir():
            raise SystemExit("missing %s - the advanced edition is built from it" % tree)
        for entry in sorted(source.rglob("*")):
            if not entry.is_file() or not _wanted(entry.relative_to(ROOT)):
                continue
            destination = app / placed / entry.relative_to(source)
            if destination.exists():
                raise SystemExit("%s would replace a file of the standard payload" % destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry, destination)
            copied += 1
    return copied


def check_app_files(stage: Path, edition: str = "standard") -> None:
    """Every required data file is in the payload, and the registry baseline validates."""
    app = stage / "payload" / "app"
    required = REQUIRED_APP_FILES + (REQUIRED_ADVANCED_FILES if edition == "advanced" else ())
    for name in required:
        if not (app / name).is_file():
            raise SystemExit("missing %s in the payload" % name)
    source = str(ROOT / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from codex_auto_resume import compat
    try:
        compat.parse_document((app / REQUIRED_APP_FILES[0]).read_bytes())
    except compat.DocumentError as exc:
        raise SystemExit("the bundled compatibility data does not validate: %s" % exc.code)


def collect_runtime(stage: Path, archive: Path) -> int:
    runtime = stage / "payload" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(runtime)
    # The embeddable build ships isolated by design. Leave python313._pth exactly as
    # published: our entry points do their own sys.path.insert, so no edit is needed,
    # and editing it is how people accidentally enable site-packages.
    return sum(1 for _ in runtime.rglob("*") if _.is_file())


def collect_gui(stage: Path, edition: str = "standard") -> int:
    r"""Place the settings window beside the runtime it drives.

    It resolves ``runtime\python.exe`` and ``app\src`` relative to its own directory,
    so it must sit at the root of the installed home - which is where the installer
    copies the whole payload folder.

    Each edition has a window of its own: `make_gui.ps1 -Edition advanced` compiles the
    advanced one into build/advanced/, beside the standard one and never over it. The MCP
    launcher is one file, the same in both editions.
    """
    built = BUILT / "advanced" if edition == "advanced" else BUILT
    source = built / GUI_EXE
    if not source.is_file():
        raise SystemExit("missing %s - run build/make_gui.ps1 -Edition %s first"
                         % (source, edition))
    shutil.copyfile(source, stage / "payload" / GUI_EXE)
    # Required, not optional. The bootstrap's archive check names both files at the payload
    # root and refuses an archive carrying either a missing one or an extra one, so building
    # without the icon produces a release that every install would reject - and it would say
    # so at the user's machine rather than here.
    icon = ROOT / "assets" / "codex-auto-resume.ico"
    if not icon.is_file():
        raise SystemExit("missing assets/codex-auto-resume.ico - the payload root needs it")
    shutil.copyfile(icon, stage / "payload" / "codex-auto-resume.ico")

    launcher = BUILT / MCP_EXE
    if not launcher.is_file():
        raise SystemExit("missing %s - run build/make_gui.ps1 first" % MCP_EXE)
    destination = stage / "payload" / "app" / "mcp" / MCP_EXE
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(launcher, destination)
    return 3


def declare_mcp_server(stage: Path, edition: str = "standard") -> None:
    """Wire the MCP server into the payload's manifest, and only the payload's.

    The server cannot run without the bundled interpreter, and only this installer puts
    that on disk. If the repository's own manifest declared the server, adding this
    repository as a Codex marketplace would register a command that is not there:
    measured, and it does not fail loudly - `plugin add` succeeds and the user is left
    with a permanently failing server in their list.

    So the declaration is added here, to the copy that ships beside the runtime it
    needs. `.mcp.json` itself stays in the repository (as build/plugin-mcp.json, see
    APP_SOURCES), because a security-relevant
    declaration should be reviewable as source rather than assembled out of a string in
    a build script.

    The advanced edition's one difference in the manifest is made here too, in the one step
    that rewrites it: its display name gains ADVANCED_WORD, so Codex's list of plugins says
    which edition is installed. `name` and `version` stay as they are, because every bootstrap
    checks both before it installs an archive (scripts/bootstrap.ps1, Test-Archive).
    """
    app = stage / "payload" / "app"
    companion = app / ".mcp.json"
    if not companion.is_file():
        raise SystemExit("missing .mcp.json - it is the source of the MCP declaration")
    manifest_path = app / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "mcpServers" in manifest:
        raise SystemExit("the repository manifest must not declare mcpServers")
    ordered = {}
    for key, value in manifest.items():
        ordered[key] = value
        if key == "skills":
            ordered["mcpServers"] = "./.mcp.json"
    if edition == "advanced":
        interface = dict(ordered["interface"])
        interface["displayName"] = "%s %s" % (interface["displayName"], ADVANCED_WORD)
        ordered["interface"] = interface
    manifest_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")


def collect_launchers(stage: Path) -> int:
    count = 0
    for name in LAUNCHER_FILES:
        source = ROOT / "build" / "install" / name
        if not source.is_file():
            raise SystemExit("missing installer file: %s" % source)
        destination = stage / name if name != "install.ps1" else stage / "install" / "install.ps1"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        count += 1
    return count


def write_archive(stage: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in stage.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in files:
            info = zipfile.ZipInfo(str(path.relative_to(stage)).replace("\\", "/"), ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes())
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows release archive.")
    parser.add_argument("--output", default=str(OUT))
    parser.add_argument("--edition", choices=EDITIONS, default="standard",
                        help="the edition to build; standard, the default, is the build as it always was")
    args = parser.parse_args(argv)
    edition = args.edition

    release = version()
    stage = STAGES / edition
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    archive = fetch_runtime()
    runtime_files = collect_runtime(stage, archive)
    app_files = collect_app(stage)
    if edition == "advanced":
        app_files += collect_advanced(stage)
    check_app_files(stage, edition)
    gui_files = collect_gui(stage, edition)
    launcher_files = collect_launchers(stage)
    declare_mcp_server(stage, edition)

    name = archive_name(edition, release)
    target = write_archive(stage, Path(args.output) / name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / (name + ".sha256")).write_text(
        "%s  %s\n" % (digest, name), encoding="utf-8")

    print("version        : %s" % release)
    print("edition        : %s" % edition)
    print("runtime files  : %d" % runtime_files)
    print("app files      : %d" % app_files)
    print("gui files      : %d" % gui_files)
    print("launcher files : %d" % launcher_files)
    print("archive        : %s" % target)
    print("size           : %.2f MB" % (target.stat().st_size / 1024 / 1024))
    print("sha256         : %s" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

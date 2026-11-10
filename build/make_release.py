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

Each archive also goes out as a one-file installer: right after writing it, main() compiles that very file
into CodexAutoResume[-Advanced]-Setup-v<version>.exe beside it (build/make_setup.py), with a .sha256 of its
own. The archive is written first and not touched again, so it is what it was without the setup program.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build" / "cache"
OUT = ROOT / "build" / "dist"
# Where build/make_gui.ps1 leaves the executables, and where each edition's payload is staged.
BUILT = ROOT / "build"
STAGES = ROOT / "build" / "stage"

# Pinned so the bundled runtime is a known build rather than whatever python.org serves
# today, by version and SHA-256 (standard I10). The digest is the one python.org's release
# file list publishes for this archive, compared with the file it served (3.14.10: 2026-10-30).
# 3.14 since v0.6.19-beta.3: the 3.13 line takes security fixes only, as source, from
# October 2026, so no newer 3.13 Windows build will come; 3.14 has them until 2027-10.
PYTHON_VERSION = "3.14.10"
PYTHON_ZIP = "python-%s-embed-amd64.zip" % PYTHON_VERSION
PYTHON_URL = "https://www.python.org/ftp/python/%s/%s" % (PYTHON_VERSION, PYTHON_ZIP)
PYTHON_SHA256 = "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"

# Everything the installed product needs, and nothing else. Listed explicitly rather
# than filtered, so a stray file in the working tree cannot reach a release.
APP_TREES = ("src", "scripts", "skills", ".codex-plugin", ".agents", "assets")
# Of those trees, the two that hold things for the repository as well as for the product: what ships from them is
# named here, file by file, and a new picture or a new script stays out until someone names the program that reads it
# (tests/test_release_size.py holds both). The assets are the icon (the tray, the installer and the payload's root) and
# what Codex's plugin loader reads by .codex-plugin/plugin.json; every other picture is for the README on GitHub, and
# the generators' JSON and sources are the build's. The scripts are what the installation runs or reads; the rest of
# scripts/ is CI's and the maintainers'.
SHIPPED_ASSETS = ("codex-auto-resume.ico", "icon.png", "logo.png", "logo-dark.png", "screenshot-panel.png",
                  "screenshot-settings.png")
SHIPPED_SCRIPTS = ("bootstrap.ps1", "plugin_setup.py", "release.json", "watcher_launcher.py")
LISTED_TREES = {"assets": SHIPPED_ASSETS, "scripts": SHIPPED_SCRIPTS}
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
# The changelog is the one document an archive carries for a program to read: the setup program and the update's notes
# page show the entry of the version the archive holds (InstallerNotes.Section), and nothing reads another entry. So the
# copy in the archive is that entry, and CHANGELOG_PAGE says where the rest is. The file in the repository stays whole;
# build/release_notes.py reads that one.
CHANGELOG = "docs/CHANGELOG.md"
CHANGELOG_PAGE = "https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/CHANGELOG.md"
# What stays of the bundled runtime: see trim_runtime.
RUNTIME_KEEP = "build/runtime_keep.json"
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
# Of those, the ones left out wherever they are. The rest are the repository's own top-level
# folders: matched at any depth, they would silently drop a package named `config` under src/
# or a skill's `tests` folder from every archive, and the first to notice would be a user's import.
EXCLUDE_ANYWHERE = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".venv", "venv"}
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
        # Under another name until it is whole, so a download cut part way is never the cached file.
        partial = archive.with_name(archive.name + ".part")
        with urllib.request.urlopen(PYTHON_URL, timeout=180) as response:
            partial.write_bytes(response.read())
        partial.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        # A proxy's error page or a short read would otherwise be trusted by every later build and
        # fail each one the same way; removed, the next build downloads it again.
        archive.unlink()
        raise SystemExit("runtime checksum mismatch: expected %s, got %s; %s was removed, so the next "
                         "build downloads it again" % (PYTHON_SHA256, digest, archive))
    return archive


def _wanted(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES or path.suffix.lower() in EXCLUDE_SUFFIXES:
        return False
    if any(part in EXCLUDE_ANYWHERE for part in path.parts):
        return False
    return not (path.parts and path.parts[0] in EXCLUDE_DIRS)


def newest_changelog(text: str, release: str) -> str:
    """What the archive carries of the changelog: its title, one line that says where the whole of it is, and the entry
    of `release`, in the file's own line endings. A version with no entry stops the build: the notes page would be empty
    on a person's PC, and release_notes.py refuses the same tag.

    An entry begins as InstallerNotes.Section reads it, `## v<version>` and then the end of the line or a space, so a
    pre-release's heading is not its final's; it ends at the next entry's heading."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    heading = "## v" + release
    begun = next((index for index, line in enumerate(lines) if line == heading or line.startswith(heading + " ")), None)
    if begun is None:
        raise SystemExit("%s has no entry for v%s" % (CHANGELOG, release))
    ended = next((index for index in range(begun + 1, len(lines)) if lines[index].startswith("## v")), len(lines))
    first = next(index for index, line in enumerate(lines) if line.startswith("## "))
    title = [line for line in lines[:first] if line.strip()]
    entry = lines[begun:ended]
    while entry and not entry[-1].strip():
        entry.pop()
    page = "This file holds this release's entry only. The whole changelog is at %s" % CHANGELOG_PAGE
    return newline.join(title + ["", page, ""] + entry + [""])


def collect_runtime(stage: Path, archive: Path) -> int:
    runtime = stage / "payload" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(runtime)
    # The embeddable build ships isolated by design. Leave python3XX._pth (python314._pth) exactly as
    # published: our entry points do their own sys.path.insert, so no edit is needed,
    # and editing it is how people accidentally enable site-packages.
    return sum(1 for _ in runtime.rglob("*") if _.is_file())


def runtime_keep() -> dict:
    """build/runtime_keep.json: what stays of the runtime, and the imports of what went that someone has read."""
    return json.loads((ROOT / RUNTIME_KEEP).read_text(encoding="utf-8"))


def trim_runtime(stage: Path) -> list:
    """Take out of the staged runtime whatever build/runtime_keep.json does not name, and return what went, as modules.

    After the download's digest is checked (fetch_runtime), so what is cut from is the file python.org published. The
    list is pinned to that digest: another runtime has other modules, and a list made for this one proves nothing of it.
    Nothing is decided here that a checked-in file does not say, and the library's members keep their order, names and
    dates at a fixed compression, so the same commit gives the same bytes (build/edition_audit.py (e))."""
    keep = runtime_keep()
    if keep["python"] != PYTHON_VERSION or keep["sha256"] != PYTHON_SHA256:
        raise SystemExit("%s was made for Python %s (%s), and this build bundles %s (%s): set python and sha256 there; "
                         "the build's own check then names whatever the new runtime needs read again"
                         % (RUNTIME_KEEP, keep["python"], keep["sha256"], PYTHON_VERSION, PYTHON_SHA256))
    runtime = stage / "payload" / "runtime"
    files, members = set(keep["files"]), set(keep["library"])
    absent = sorted(files - {path.name for path in runtime.iterdir()})
    if absent:
        raise SystemExit("%s names files the runtime does not have: %s" % (RUNTIME_KEEP, ", ".join(absent)))
    removed = []
    for path in sorted(runtime.iterdir()):
        if path.name not in files:
            path.unlink()
            if path.suffix.lower() == ".pyd":
                removed.append(path.stem)
    library = runtime / keep["library_zip"]
    with zipfile.ZipFile(library) as whole:
        infos = whole.infolist()
        absent = sorted(members - {info.filename for info in infos})
        if absent:
            raise SystemExit("%s names members the runtime's library does not have: %s"
                             % (RUNTIME_KEEP, ", ".join(absent)))
        kept = [(info, whole.read(info)) for info in infos if info.filename in members]
    for info in infos:
        if info.filename not in members and info.filename.endswith(".pyc"):
            module = info.filename[:-len(".pyc")].replace("/", ".")
            removed.append(module[:-len(".__init__")] if module.endswith(".__init__") else module)
    with zipfile.ZipFile(library, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as trimmed:
        for info, data in kept:
            entry = zipfile.ZipInfo(info.filename, info.date_time)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            entry.create_system = 0
            trimmed.writestr(entry, data)
    return sorted(removed)


def check_trimmed_runtime(stage: Path, removed: list, timeout: float = 300) -> None:
    """The staged code still runs under the runtime as trimmed, or the build stops (build/runtime_check.py says how).

    Under the staged interpreter, in a scratch home, from a scratch directory, with no PYTHONPATH: what a person's PC
    has. -B as in check_courier_starts, so the archive holds only what the build put there."""
    payload = stage / "payload"
    runtime = payload / "runtime"
    keep = runtime_keep()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with tempfile.TemporaryDirectory(prefix="car-runtime-check-") as scratch:
        home = Path(scratch) / "home"
        home.mkdir()
        asked = Path(scratch) / "asked.json"
        asked.write_text(json.dumps({"app": str(payload / "app"), "library": str(runtime / keep["library_zip"]),
                                     "removed": removed, "reviewed": keep["reviewed"],
                                     "also": [str(ROOT / "build" / "smoke_archive.py")]}), encoding="utf-8")
        environment = {name: value for name, value in os.environ.items() if name.upper() != "PYTHONPATH"}
        environment.update({name: str(home) for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "CODEX_HOME")})
        try:
            done = subprocess.run([str(runtime / "python.exe"), "-B", "-X", "disable-remote-debug",
                                   str(ROOT / "build" / "runtime_check.py"), str(asked)], cwd=scratch, env=environment,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit("the trimmed runtime could not be checked: %s" % exc)
    if done.returncode != 0:
        raise SystemExit("the staged code does not hold under the trimmed runtime (exit %s):\n%s\n%s"
                         % (done.returncode, done.stdout[-6000:], done.stderr[-2000:]))
    left = sorted(str(path.relative_to(stage)) for path in payload.rglob("__pycache__"))
    if left:
        raise SystemExit("the runtime check left bytecode in the stage: %s" % ", ".join(left[:5]))


def collect_app(stage: Path) -> int:
    """Copy the application payload, which is also a valid local Codex marketplace."""
    app = stage / "payload" / "app"
    copied = 0
    for tree in APP_TREES:
        source = ROOT / tree
        if not source.is_dir():
            continue
        listed = LISTED_TREES.get(tree)
        for name in listed or ():
            if not (source / name).is_file():
                raise SystemExit("missing %s/%s - it is on the list of what the release ships" % (tree, name))
        for entry in ([source / name for name in listed] if listed else sorted(source.rglob("*"))):
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
            if name == CHANGELOG:
                # Bytes both ways, so the file's own line endings survive what Windows would make of them.
                (app / name).write_bytes(newest_changelog(source.read_bytes().decode("utf-8"), version()).encode("utf-8"))
            else:
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


def check_courier_starts(stage: Path, timeout: float = 120) -> None:
    """The advanced courier starts from this payload under its own runtime, or the build stops.

    An installed copy runs the embeddable runtime, whose python3XX._pth makes it ignore the environment: a PYTHONPATH
    reaches nothing there. v0.6.22-beta.2 started the courier with its import roots only in PYTHONPATH, and every start
    from an installation failed on its first import while CI, under a system Python, saw none of it (the live
    acceptance's F7). So the staged runtime is asked for the courier's command line as the staged code builds it, and
    that command is run with `--check` - every module a round can need imported, nothing read, written or sent - in a
    scratch home, from a scratch directory, with no PYTHONPATH. Offline, and seconds. Both runs take -B: an import
    writes no bytecode into the stage, so the archive holds only what the build put there (the release run's edition
    audit (f) found the check's __pycache__ in the advanced archive, v0.6.22's first release run)."""
    payload = stage / "payload"
    runtime = payload / "runtime"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = {name: value for name, value in os.environ.items() if name.upper() != "PYTHONPATH"}
    ask = ("import json, sys; sys.path[:0] = [sys.argv[1]]; from codex_auto_resume import config; "
           "from codex_auto_resume_advanced.courier import launch; "
           "print(json.dumps(launch.argv(config.Paths(sys.argv[2]), '--check')))")
    with tempfile.TemporaryDirectory(prefix="car-courier-check-") as scratch:
        home = Path(scratch) / "home"
        home.mkdir()
        try:
            asked = subprocess.run([str(runtime / "python.exe"), "-B", "-X", "disable-remote-debug", "-c", ask,
                                    str(payload / "app" / "src"), str(home)], cwd=scratch, env=environment,
                                   stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
                                   creationflags=flags)
            command = json.loads(asked.stdout) if asked.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise SystemExit("the staged runtime could not build the courier's command line: %s" % exc)
        if command is None:
            raise SystemExit("the staged runtime could not build the courier's command line:\n%s"
                             % asked.stderr[-2000:])
        try:
            staged = os.path.samefile(command[0], runtime / "pythonw.exe")
        except OSError:
            staged = False
        if not staged:
            raise SystemExit("the courier would start under %s, not the staged pythonw.exe" % command[0])
        try:
            ran = subprocess.run([command[0], "-B", *command[1:]], cwd=scratch, env=environment,
                                 stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
                                 creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit("the courier did not start from the staged payload: %s" % exc)
        if ran.returncode != 0:
            raise SystemExit("the courier does not start from the staged payload (exit %s):\n%s"
                             % (ran.returncode, ran.stderr[-2000:]))
    left = sorted(str(path.relative_to(stage)) for path in payload.rglob("__pycache__"))
    if left:
        raise SystemExit("the courier check left bytecode in the stage: %s" % ", ".join(left[:5]))


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


def build_setup(archive: Path, edition: str, release: str) -> Path:
    """The edition's setup program, compiled around the archive just written and put beside it
    (build/make_setup.py). Imported here rather than at the top, so loading this module to read its
    lists - as the tests do, by path - needs nothing beside it."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import make_setup
    return make_setup.build(archive, archive.parent, edition, release)


def write_sidecar(target: Path) -> str:
    """`<sha256>  <name>` in <name>.sha256 beside the file, as every file of a release has; the digest."""
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    # LF, not the runner's CRLF: `sha256sum -c` reads the name up to the line end, and with a
    # carriage return it looks for "<name>\r" and calls a good download unreadable.
    with open(target.parent / (target.name + ".sha256"), "w", encoding="utf-8", newline="\n") as sidecar:
        sidecar.write("%s  %s\n" % (digest, target.name))
    return digest


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
    removed = trim_runtime(stage)
    runtime_files = sum(1 for path in (stage / "payload" / "runtime").rglob("*") if path.is_file())
    app_files = collect_app(stage)
    if edition == "advanced":
        app_files += collect_advanced(stage)
    check_app_files(stage, edition)
    check_trimmed_runtime(stage, removed)
    if edition == "advanced":
        check_courier_starts(stage)
    gui_files = collect_gui(stage, edition)
    launcher_files = collect_launchers(stage)
    declare_mcp_server(stage, edition)

    name = archive_name(edition, release)
    target = write_archive(stage, Path(args.output) / name)
    digest = write_sidecar(target)
    setup = build_setup(target, edition, release)
    setup_digest = write_sidecar(setup)

    print("version        : %s" % release)
    print("edition        : %s" % edition)
    print("runtime files  : %d" % runtime_files)
    print("app files      : %d" % app_files)
    print("gui files      : %d" % gui_files)
    print("launcher files : %d" % launcher_files)
    print("archive        : %s" % target)
    print("size           : %.2f MB" % (target.stat().st_size / 1024 / 1024))
    print("sha256         : %s" % digest)
    print("setup program  : %s" % setup)
    print("setup size     : %.2f MB" % (setup.stat().st_size / 1024 / 1024))
    print("setup sha256   : %s" % setup_digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

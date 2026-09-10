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
any build-host path. What is *not*, and the claim was previously overstated: the archive
is not byte-reproducible, because the two C# executables in it are not. The in-box
compiler stamps every assembly with a fresh module version GUID, so two builds of
byte-identical source produce different binaries - measured, by building twice and
comparing. The published checksum therefore identifies one build; it does not let anyone
reproduce it. Saying otherwise would invite someone to verify something that cannot hold.
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

# Pinned so the bundled runtime is a known build rather than whatever python.org serves
# today. Verified against the published sigstore/spdx artefacts.
PYTHON_VERSION = "3.13.15"
PYTHON_ZIP = "python-%s-embed-amd64.zip" % PYTHON_VERSION
PYTHON_URL = "https://www.python.org/ftp/python/%s/%s" % (PYTHON_VERSION, PYTHON_ZIP)
PYTHON_SHA256 = "d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf"

# Everything the installed product needs, and nothing else. Listed explicitly rather
# than filtered, so a stray file in the working tree cannot reach a release.
APP_TREES = ("src", "scripts", "skills", ".codex-plugin", ".agents", "assets")
# Built, not copied from the working tree: see build/make_gui.ps1.
GUI_EXE = "CodexAutoResumeSettings.exe"
# Codex only accepts a plugin MCP command that is a bare executable name or a path
# inside the plugin, so the launcher ships in the plugin payload and finds the bundled
# interpreter itself. `.mcp.json` names it by that contained path.
MCP_EXE = "codex-auto-resume-mcp.exe"
# Every top-level document the shipped README links to, so the installed copy does not
# promise a privacy policy that is not beside it. Asserted by tests/test_plugin.py.
APP_FILES = ("LICENSE", "README.md", "README.ko.md", "PRIVACY.md", "SECURITY.md",
             "SUPPORT.md", "CONTRIBUTING.md", "CONTRIBUTORS.md", "CHANGELOG.md",
             ".mcp.json")
LAUNCHER_FILES = ("Install.cmd", "Uninstall.cmd", "README.txt", "install.ps1")

EXCLUDE_DIRS = {"__pycache__", ".git", ".github", "node_modules", ".pytest_cache",
                "comparison", "config", "logs", "build", "tests", ".venv", "venv"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite", ".sqlite-wal", ".sqlite-shm"}
EXCLUDE_NAMES = {".owned-by-codex-auto-resume", "runtime.json", "settings.json",
                 "state.sqlite", ".DS_Store", "Thumbs.db"}

# A fixed timestamp removes one source of build-to-build variation. It does not make the
# archive byte-identical - see the module docstring for what does not.
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def version() -> str:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(manifest["version"])


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
        source = ROOT / name
        if source.is_file():
            shutil.copyfile(source, app / name)
            copied += 1
    return copied


def collect_runtime(stage: Path, archive: Path) -> int:
    runtime = stage / "payload" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(runtime)
    # The embeddable build ships isolated by design. Leave python313._pth exactly as
    # published: our entry points do their own sys.path.insert, so no edit is needed,
    # and editing it is how people accidentally enable site-packages.
    return sum(1 for _ in runtime.rglob("*") if _.is_file())


def collect_gui(stage: Path) -> int:
    r"""Place the settings window beside the runtime it drives.

    It resolves ``runtime\python.exe`` and ``app\src`` relative to its own directory,
    so it must sit at the root of the installed home - which is where the installer
    copies the whole payload folder.
    """
    source = ROOT / "build" / GUI_EXE
    if not source.is_file():
        raise SystemExit("missing %s - run build/make_gui.ps1 first" % GUI_EXE)
    shutil.copyfile(source, stage / "payload" / GUI_EXE)
    icon = ROOT / "assets" / "codex-auto-resume.ico"
    if icon.is_file():
        shutil.copyfile(icon, stage / "payload" / "codex-auto-resume.ico")

    launcher = ROOT / "build" / MCP_EXE
    if not launcher.is_file():
        raise SystemExit("missing %s - run build/make_gui.ps1 first" % MCP_EXE)
    destination = stage / "payload" / "app" / "mcp" / MCP_EXE
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(launcher, destination)
    return 3


def declare_mcp_server(stage: Path) -> None:
    """Wire the MCP server into the payload's manifest, and only the payload's.

    The server cannot run without the bundled interpreter, and only this installer puts
    that on disk. If the repository's own manifest declared the server, adding this
    repository as a Codex marketplace would register a command that is not there:
    measured, and it does not fail loudly - `plugin add` succeeds and the user is left
    with a permanently failing server in their list.

    So the declaration is added here, to the copy that ships beside the runtime it
    needs. `.mcp.json` itself stays in the repository, because a security-relevant
    declaration should be reviewable as source rather than assembled out of a string in
    a build script.
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
    manifest_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")


def collect_launchers(stage: Path) -> int:
    count = 0
    for name in LAUNCHER_FILES:
        source = ROOT / "install" / name
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
    args = parser.parse_args(argv)

    release = version()
    stage = ROOT / "build" / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    archive = fetch_runtime()
    runtime_files = collect_runtime(stage, archive)
    app_files = collect_app(stage)
    gui_files = collect_gui(stage)
    launcher_files = collect_launchers(stage)
    declare_mcp_server(stage)

    name = "CodexAutoResume-v%s-win-x64.zip" % release
    target = write_archive(stage, Path(args.output) / name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / (name + ".sha256")).write_text(
        "%s  %s\n" % (digest, name), encoding="utf-8")

    print("version        : %s" % release)
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

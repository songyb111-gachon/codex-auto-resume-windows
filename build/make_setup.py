"""The one-file installers: CodexAutoResume-Setup-v<version>.exe and CodexAutoResume-Advanced-Setup-v<version>.exe.

    python build/make_setup.py [--edition standard|advanced] [--dist build/dist]
    python build/make_setup.py --check [--edition ...] [--dist ...]

Each is build/setup/Setup.cs compiled around its edition's release archive: the ZIP's bytes, exactly as
build/make_release.py wrote them, as the program's one managed resource, and their SHA-256 as a constant
beside it. Double-clicked, it checks those bytes, unpacks them into a new folder of its own in the user's
temporary folder, runs that archive's own Install.cmd there and removes the folder afterwards - so it installs
what the ZIP installs, asking what the ZIP's Install.cmd asks, and ends with its exit code. make_release.py
builds it right after the archive, from the very file it wrote, and writes a .sha256 beside it as it does for
the archive.

It is compiled the way build/make_gui.ps1 compiles the settings window: by the in-box C# compiler of .NET
Framework 4.8, which every supported Windows has, for x64, with the product's icon and a version resource made
from .codex-plugin/plugin.json, and then build/normalize_pe.py fixes the two fields the compiler stamps anew
each run - so the same archive always gives the same bytes, and anyone can rebuild a published setup program
from the published archive and compare. `--check` does that to what is in the dist folder: builds it again,
compares, and holds the carried archive to the one beside it byte for byte. The manifest is embedded with CRLF
line endings whatever the checkout wrote, since its bytes are part of the program's.

The archive goes in unchanged, so the ZIP, its name and every published bootstrap that takes it are exactly
what they were; this is one more file beside them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import legacy_bootstraps  # noqa: E402  (the version rule, `order`)
import normalize_pe  # noqa: E402

SOURCE = "build/setup/Setup.cs"
MANIFEST = "build/setup/setup.manifest"
ICON = "assets/codex-auto-resume.ico"
# The name of the one managed resource, the carried archive, as Setup.cs asks for it (Embedded.Resource).
RESOURCE = "archive.zip"
REFERENCES = ("System.dll", "System.IO.Compression.dll")
EDITIONS = ("standard", "advanced")
# Each edition's file name, beside its archive's (scripts/release.json holds those). The release workflow
# spells both in its publish job, and tests/test_setup.py holds it to these.
NAMES = {"standard": "CodexAutoResume-Setup-v{version}.exe",
         "advanced": "CodexAutoResume-Advanced-Setup-v{version}.exe"}
WORDS = {"standard": "Standard", "advanced": "Advanced"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def setup_name(edition: str, version: str) -> str:
    return NAMES[edition].replace("{version}", version)


def compiler() -> Path:
    """csc.exe of .NET Framework 4.8, where build/make_gui.ps1 takes it from."""
    windows = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows")
    csc = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not csc.is_file():
        raise SystemExit("The in-box C# compiler was not found (%s)." % csc)
    return csc


def _literal(text: str) -> str:
    """A C# string literal: JSON's escapes are all C#'s too, and it writes nothing but ASCII."""
    return json.dumps(text, ensure_ascii=True)


def version_source(edition: str, version: str, root: Path = ROOT) -> str:
    """The version resource, as C#: what Explorer's Properties and a SmartScreen prompt show of the file.
    The same fields make_gui.ps1 gives the settings window, and the edition in the description."""
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))
    numeric = "%d.%d.%d" % legacy_bootstraps.order(version)[:3]
    publisher = str(manifest["author"]["name"])
    product = str(manifest["interface"]["displayName"])
    description = "%s setup (%s edition)" % (product, WORDS[edition])
    return "\r\n".join([
        "// Made by build/make_setup.py from .codex-plugin/plugin.json. Do not edit.",
        "using System.Reflection;",
        "using System.Runtime.Versioning;",
        "[assembly: AssemblyTitle(%s)]" % _literal(description),
        "[assembly: AssemblyDescription(%s)]" % _literal(description),
        "[assembly: AssemblyProduct(%s)]" % _literal(product),
        "[assembly: AssemblyCompany(%s)]" % _literal(publisher),
        "[assembly: AssemblyCopyright(%s)]" % _literal("Copyright (c) %s. MIT License." % publisher),
        '[assembly: AssemblyVersion("%s.0")]' % numeric,
        '[assembly: AssemblyFileVersion("%s.0")]' % numeric,
        "[assembly: AssemblyInformationalVersion(%s)]" % _literal(version),
        # .NET Framework 4.8's behaviour rather than 4.0's, which it gives a program that names no target.
        '[assembly: TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]',
        "",
    ])


def embedded_source(archive_name: str, data: bytes) -> str:
    """What Setup.cs holds the carried bytes to: the resource's name, the archive's, its length and SHA-256."""
    return "\r\n".join([
        "// Made by build/make_setup.py from the release archive it carries. Do not edit.",
        "namespace CodexAutoResumeSetup",
        "{",
        "    internal static class Embedded",
        "    {",
        "        internal const string Resource = %s;" % _literal(RESOURCE),
        "        internal const string Archive = %s;" % _literal(archive_name),
        "        internal const long Length = %d;" % len(data),
        "        internal const string Sha256 = %s;" % _literal(hashlib.sha256(data).hexdigest()),
        "    }",
        "}",
        "",
    ])


def manifest_bytes(root: Path = ROOT) -> bytes:
    """build/setup/setup.manifest as it is embedded: with CRLF line endings, however it was checked out."""
    return (root / MANIFEST).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def _said(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("mbcs" if os.name == "nt" else "latin-1", errors="replace")


def build(archive: Path, out: Path, edition: str, version: str, root: Path = ROOT) -> Path:
    """Compile the edition's setup program around `archive` into `out`, reproducibly; its path."""
    if edition not in EDITIONS:
        raise SystemExit("no edition named %s" % edition)
    csc = compiler()
    archive, out = Path(archive), Path(out)
    data = archive.read_bytes()
    out.mkdir(parents=True, exist_ok=True)
    exe = out / setup_name(edition, version)
    with tempfile.TemporaryDirectory(prefix="setup-exe-") as work:
        work = Path(work)
        info = work / "Setup.VersionInfo.cs"
        info.write_bytes(version_source(edition, version, root).encode("ascii"))
        embedded = work / "Setup.Embedded.cs"
        embedded.write_bytes(embedded_source(archive.name, data).encode("ascii"))
        manifest = work / "setup.manifest"
        manifest.write_bytes(manifest_bytes(root))
        # csc reads /resource:<file>,<name>: the archive is given from here, under a path with no comma.
        carried_copy = work / RESOURCE
        carried_copy.write_bytes(data)
        if "," in str(carried_copy):
            raise SystemExit("the temporary folder's path holds a comma, which csc would misread: %s" % carried_copy)
        arguments = [str(csc), "/nologo", "/utf8output", "/target:exe", "/platform:x64", "/optimize+",
                     "/warn:4", "/warnaserror+", "/out:" + str(exe), "/win32manifest:" + str(manifest),
                     "/win32icon:" + str(root / ICON), "/resource:%s,%s" % (carried_copy, RESOURCE)]
        arguments += ["/reference:" + reference for reference in REFERENCES]
        arguments += [str(root / SOURCE), str(info), str(embedded)]
        done = subprocess.run(arguments, capture_output=True, stdin=subprocess.DEVNULL, timeout=600,
                              creationflags=NO_WINDOW)
    if done.returncode:
        raise SystemExit("%s did not compile:\n%s%s" % (exe.name, _said(done.stdout), _said(done.stderr)))
    # The in-box compiler has no /deterministic: every build stamps the second it ran into the PE header and a
    # fresh random GUID into the module's metadata, and nothing else varies.
    normalize_pe.normalise_file(exe)
    return exe


def carried_span(image: bytes) -> tuple:
    """Where the archive a setup program carries lies in its bytes, as (start, end): the managed resources
    its CLI header points at, which must be exactly one resource - a length, the bytes, and nothing after
    them but the compiler's alignment to eight. Raises ValueError for anything else."""
    try:
        normalize_pe.locate(image)
        pe = struct.unpack_from("<I", image, 0x3C)[0]
        directories = pe + 24 + (112 if struct.unpack_from("<H", image, pe + 24)[0] == 0x20B else 96)
        sections = normalize_pe._sections(image, pe)
        cli = normalize_pe._rva_to_offset(sections, struct.unpack_from("<I", image, directories + 14 * 8)[0])
        rva, size = struct.unpack_from("<II", image, cli + 24)
        if not rva or size < 4:
            raise ValueError("the program carries no managed resource")
        start = normalize_pe._rva_to_offset(sections, rva)
        length = struct.unpack_from("<I", image, start)[0]
    except (normalize_pe.NotNormalisable, struct.error) as exc:
        raise ValueError("not a setup program this can read: %s" % exc) from None
    rest = size - 4 - length
    if rest < 0 or rest >= 8 or start + size > len(image) or image[start + 4 + length:start + size] != bytes(rest):
        raise ValueError("the program's resources are not exactly one archive")
    return start + 4, start + 4 + length


def carried(image: bytes) -> bytes:
    """The archive a setup program carries, read from its bytes (carried_span)."""
    start, end = carried_span(image)
    return image[start:end]


def check(dist: Path, edition: str, version: str, archive_name: str) -> list:
    """What is wrong with the edition's setup program in `dist`, as sentences; none when it carries the
    archive beside it byte for byte, its sidecar is its digest, and building it again gives the same file."""
    archive, exe = dist / archive_name, dist / setup_name(edition, version)
    for needed in (archive, exe, Path(str(exe) + ".sha256")):
        if not needed.is_file():
            return ["missing %s" % needed]
    found = []
    image = exe.read_bytes()
    try:
        if carried(image) != archive.read_bytes():
            found.append("%s does not carry %s byte for byte" % (exe.name, archive.name))
    except ValueError as exc:
        found.append("%s: %s" % (exe.name, exc))
    recorded = Path(str(exe) + ".sha256").read_text(encoding="utf-8").split(" ")[0].strip()
    if recorded != hashlib.sha256(image).hexdigest():
        found.append("the checksum beside %s is not its digest" % exe.name)
    with tempfile.TemporaryDirectory(prefix="setup-again-") as again:
        if build(archive, Path(again), edition, version).read_bytes() != image:
            found.append("%s differs from a second build of the same archive" % exe.name)
    return found


def main(argv=None) -> int:
    import make_release
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--edition", choices=EDITIONS, default="standard")
    parser.add_argument("--dist", default=str(make_release.OUT),
                        help="where make_release.py wrote the archive (default: build/dist)")
    parser.add_argument("--check", action="store_true",
                        help="build again and compare, rather than build")
    args = parser.parse_args(argv)
    version = make_release.version()
    dist = Path(args.dist)
    archive_name = make_release.archive_name(args.edition, version)
    if args.check:
        found = check(dist, args.edition, version, archive_name)
        for line in found:
            print("  " + line)
        if found:
            return 1
        print("%s carries %s byte for byte and is reproducible" % (setup_name(args.edition, version), archive_name))
        return 0
    if not (dist / archive_name).is_file():
        raise SystemExit("missing %s - run build/make_release.py --edition %s first" % (dist / archive_name,
                                                                                       args.edition))
    exe = build(dist / archive_name, dist, args.edition, version)
    print("%s  %s" % (make_release.write_sidecar(exe), exe))
    return 0


if __name__ == "__main__":
    sys.exit(main())

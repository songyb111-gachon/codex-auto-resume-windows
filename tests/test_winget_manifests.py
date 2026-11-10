"""The winget manifests of both editions: build/winget_manifests.py.

It writes the multi-file manifest the owner submits to microsoft/winget-pkgs - version, installer, the en-US
default locale and a ko-KR locale - for the standard and the advanced edition. Held here, against a sample
release.json and no network:

* every file has the fields the schema (manifest 1.28.0, which 1.12.0 matches for what is written) requires
  of its kind, and no field the schema does not have for it; the values that have a pattern or a list of
  words keep to it;
* the identifiers fit the identifier rule and the files lie where the repository wants them;
* the installer entry points at the edition's one-file Setup program, with the digest it was given;
* nothing is made for a pre-release, for an archive whose pin is missing, or for a Setup program that cannot
  yet install without a person - unless asked for as a draft;
* what is written reads back: the tests read the YAML with a small reader of the shapes the writer emits.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from codex_auto_resume import addremove  # noqa: E402
import winget_manifests as wm  # noqa: E402

SAMPLE = {
    "owner": "example-owner",
    "repo": "example-repo",
    "download": "https://github.com/example-owner/example-repo/releases/download/v{version}/",
    "archive": "CodexAutoResume-v{version}-win-x64.zip",
    "sha256": {"0.6.15": "1" * 64, "0.6.16": "3" * 64},
    "advanced": {"archive": "CodexAutoResume-Advanced-v{version}-win-x64.zip", "since": "0.6.11",
                 "sha256": {"0.6.15": "2" * 64, "0.6.16": "4" * 64}},
}
DIGESTS = {"standard": "ab" * 32, "advanced": "cd" * 32}

# From manifest.<kind>.1.28.0.json (microsoft/winget-cli, schemas/JSON/manifests/v1.28.0), read 2026-10-16.
REQUIRED = {
    "version": {"PackageIdentifier", "PackageVersion", "DefaultLocale", "ManifestType", "ManifestVersion"},
    "installer": {"PackageIdentifier", "PackageVersion", "Installers", "ManifestType", "ManifestVersion"},
    "defaultLocale": {"PackageIdentifier", "PackageVersion", "PackageLocale", "Publisher", "PackageName", "License",
                      "ShortDescription", "ManifestType", "ManifestVersion"},
    "locale": {"PackageIdentifier", "PackageVersion", "PackageLocale", "ManifestType", "ManifestVersion"},
}
INSTALLER_ENTRY_REQUIRED = {"Architecture", "InstallerUrl", "InstallerSha256"}
LOCALE_FIELDS = {"PackageIdentifier", "PackageVersion", "PackageLocale", "Publisher", "PublisherUrl",
                 "PublisherSupportUrl", "PrivacyUrl", "Author", "PackageName", "PackageUrl", "License", "LicenseUrl",
                 "Copyright", "CopyrightUrl", "ShortDescription", "Description", "Tags", "Agreements",
                 "ReleaseNotes", "ReleaseNotesUrl", "PurchaseUrl", "InstallationNotes", "Documentations", "Icons",
                 "ManifestType", "ManifestVersion"}
ALLOWED = {
    "version": REQUIRED["version"],
    "defaultLocale": LOCALE_FIELDS | {"Moniker"},
    "locale": LOCALE_FIELDS,
    "installer": {"PackageIdentifier", "PackageVersion", "Channel", "InstallerLocale", "Platform", "MinimumOSVersion",
                  "InstallerType", "NestedInstallerType", "NestedInstallerFiles", "Scope", "InstallModes",
                  "InstallerSwitches", "InstallerSuccessCodes", "ExpectedReturnCodes", "UpgradeBehavior", "Commands",
                  "Protocols", "FileExtensions", "Dependencies", "PackageFamilyName", "ProductCode", "Capabilities",
                  "RestrictedCapabilities", "Markets", "InstallerAbortsTerminal", "ReleaseDate",
                  "InstallLocationRequired", "RequireExplicitUpgrade", "DisplayInstallWarnings",
                  "UnsupportedOSArchitectures", "UnsupportedArguments", "AppsAndFeaturesEntries",
                  "ElevationRequirement", "InstallationMetadata", "DownloadCommandProhibited", "RepairBehavior",
                  "ArchiveBinariesDependOnPath", "Authentication", "DesiredStateConfiguration", "Installers",
                  "ManifestType", "ManifestVersion"},
}
IDENTIFIER = re.compile(r'^[^\.\s\\/:\*\?"<>\|\x01-\x1f]{1,32}(\.[^\.\s\\/:\*\?"<>\|\x01-\x1f]{1,32}){1,7}$')
KIND_OF_SUFFIX = {"": "version", ".installer": "installer", ".locale.en-US": "defaultLocale", ".locale.ko-KR": "locale"}


def read_yaml(text: str):
    """The shapes the writer emits: `key: "string"`, `key:` over `- "string"` lines, `- key: ...` mappings and
    a nested mapping two spaces further in. Comments are skipped."""
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip() and not line.startswith("#")]

    def scalar(raw: str):
        return json.loads(raw)

    def mapping(index: int, indent: int, first_inline: str | None = None):
        result = {}
        pending = first_inline
        while True:
            if pending is not None:
                line, here = pending, indent
                pending = None
            elif index < len(lines):
                line = lines[index]
                here = len(line) - len(line.lstrip(" "))
                if here != indent or line.lstrip().startswith("- "):
                    return result, index
                line, index = line.strip(), index + 1
            else:
                return result, index
            key, _, rest = line.partition(":")
            rest = rest.strip()
            if rest:
                result[key] = scalar(rest)
                continue
            following = lines[index] if index < len(lines) else ""
            deeper = len(following) - len(following.lstrip(" "))
            if following.lstrip().startswith("- ") and deeper == indent:
                items = []
                while index < len(lines) and lines[index].startswith(" " * indent + "- "):
                    body = lines[index][indent + 2:]
                    index += 1
                    if re.match(r"[A-Za-z]+:( |$)", body) and not body.startswith('"'):
                        item, index = mapping(index, indent + 2, body)
                        items.append(item)
                    else:
                        items.append(scalar(body))
                result[key] = items
            else:
                result[key], index = mapping(index, indent + 2)
        return result, index

    parsed, _ = mapping(0, 0)
    return parsed


class Made(unittest.TestCase):
    """Both editions' files, made once from the sample."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.out = Path(cls.directory.name)
        cls.version = "0.6.15"
        cls.written = wm.build(cls.version, DIGESTS, cls.out, draft=True, release=SAMPLE)
        # By folder: the standard package's name is the start of the advanced one's.
        cls.by_edition = {edition: [p for p in cls.written if p.parent == cls.out / wm.folder(edition, cls.version)]
                          for edition in wm.EDITIONS}

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def files(self, edition):
        found = {}
        for path in self.by_edition[edition]:
            stem = path.name[len(wm.package_id(edition)):-len(".yaml")]
            found[KIND_OF_SUFFIX[stem]] = read_yaml(path.read_bytes().decode("utf-8"))
        return found


class SchemaTests(Made):
    def test_four_files_per_edition_of_the_four_kinds(self):
        for edition in wm.EDITIONS:
            self.assertEqual(set(self.files(edition)), set(KIND_OF_SUFFIX.values()))
            self.assertEqual(len(self.by_edition[edition]), 4)

    def test_required_fields_and_no_others(self):
        for edition in wm.EDITIONS:
            for kind, data in self.files(edition).items():
                with self.subTest(edition=edition, kind=kind):
                    self.assertEqual(data["ManifestType"], kind)
                    self.assertEqual(data["ManifestVersion"], wm.SCHEMA)
                    self.assertFalse(REQUIRED[kind] - set(data), "missing")
                    self.assertFalse(set(data) - ALLOWED[kind], "not in the schema")

    def test_the_installer_entry(self):
        for edition in wm.EDITIONS:
            installer = self.files(edition)["installer"]
            entries = installer["Installers"]
            self.assertEqual(len(entries), 1)
            self.assertFalse(INSTALLER_ENTRY_REQUIRED - set(entries[0]))
            self.assertRegex(entries[0]["InstallerSha256"], r"^[A-Fa-f0-9]{64}$")
            self.assertRegex(entries[0]["InstallerUrl"], r"^[Hh][Tt][Tt][Pp][Ss]?://.+$")
            self.assertIn(entries[0]["Architecture"], ("x86", "x64", "arm", "arm64", "neutral"))
            self.assertIn(installer["InstallerType"], ("msix", "msi", "appx", "exe", "zip", "inno", "nullsoft",
                                                       "wix", "burn", "pwa", "portable", "font"))
            self.assertIn(installer["Scope"], ("user", "machine"))
            self.assertIn(installer["ElevationRequirement"], ("elevationRequired", "elevationProhibited",
                                                              "elevatesSelf"))
            self.assertIn(installer["UpgradeBehavior"], ("install", "uninstallPrevious", "deny"))
            self.assertTrue(set(installer["InstallModes"]) <= {"interactive", "silent", "silentWithProgress"})
            # The community repository requires both silent modes.
            self.assertIn("silent", installer["InstallModes"])
            self.assertIn("silentWithProgress", installer["InstallModes"])
            self.assertTrue(installer["InstallerSwitches"]["Silent"])
            self.assertTrue(installer["InstallerSwitches"]["SilentWithProgress"])
            for code in installer["ExpectedReturnCodes"]:
                self.assertIn(code["ReturnResponse"], ("custom", "alreadyInstalled", "downgrade", "cancelledByUser",
                                                       "contactSupport", "installInProgress", "invalidParameter"))
                self.assertRegex(code["InstallerReturnCode"], r"^-?\d+$")

    def test_value_limits_of_the_locale_files(self):
        for edition in wm.EDITIONS:
            for kind in ("defaultLocale", "locale"):
                data = self.files(edition)[kind]
                self.assertLessEqual(len(data["ShortDescription"]), 256)
                self.assertLessEqual(len(data.get("Description", "")), 10000)
                self.assertRegex(data["PackageLocale"], r"^([a-zA-Z]{2,3})(-[a-zA-Z]{1,8})*$")
                self.assertLessEqual(len(data.get("Tags", [])), 16)
                for tag in data.get("Tags", []):
                    self.assertLessEqual(len(tag), 40)
                for key in ("PublisherUrl", "PublisherSupportUrl", "PrivacyUrl", "PackageUrl", "LicenseUrl",
                            "ReleaseNotesUrl"):
                    if key in data:
                        self.assertRegex(data[key], r"^https://.+$")

    def test_the_version_file_names_the_default_locale(self):
        for edition in wm.EDITIONS:
            data = self.files(edition)
            self.assertEqual(data["version"]["DefaultLocale"], data["defaultLocale"]["PackageLocale"])


class IdentityTests(Made):
    def test_identifiers_follow_the_rule_and_differ(self):
        ids = [wm.package_id(edition) for edition in wm.EDITIONS]
        for ident in ids:
            self.assertRegex(ident, IDENTIFIER)
            self.assertLessEqual(len(ident), 128)
        self.assertEqual(len(set(ids)), 2)
        self.assertTrue(ids[1].startswith(ids[0] + "."))

    def test_every_file_carries_its_own_identifier_and_the_version(self):
        for edition in wm.EDITIONS:
            for kind, data in self.files(edition).items():
                self.assertEqual(data["PackageIdentifier"], wm.package_id(edition))
                self.assertEqual(data["PackageVersion"], self.version)

    def test_the_repository_layout(self):
        # manifests / <first letter, lower case> / <publisher> / <package> / <version> / <identifier>.<kind>.yaml
        for edition in wm.EDITIONS:
            ident = wm.package_id(edition)
            parts = ident.split(".")
            expected = Path("manifests", parts[0][0].lower(), *parts, self.version)
            for path in self.by_edition[edition]:
                self.assertEqual(path.parent.relative_to(self.out), expected)
                self.assertTrue(path.name.startswith(ident + "."))
        self.assertEqual(wm.folder("standard", "1.2.3"),
                         Path("manifests", "s", wm.PUBLISHER, "CodexAutoResume", "1.2.3"))

    def test_names_people_see(self):
        standard = self.files("standard")["defaultLocale"]["PackageName"]
        advanced = self.files("advanced")["defaultLocale"]["PackageName"]
        self.assertEqual(standard, "Codex Auto Resume")
        self.assertEqual(advanced, "Codex Auto Resume Advanced")
        for edition, name in (("standard", standard), ("advanced", advanced)):
            entry = self.files(edition)["installer"]["AppsAndFeaturesEntries"][0]
            self.assertEqual(entry["DisplayName"], name)
            self.assertEqual(entry["Publisher"], self.files(edition)["defaultLocale"]["Publisher"])

    def test_the_publisher_is_the_plugin_author(self):
        author = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8-sig"))["author"]["name"]
        self.assertEqual(wm.PUBLISHER, author)


class InstallerPointTests(Made):
    def test_each_edition_points_at_its_setup_program_and_digest(self):
        for edition in wm.EDITIONS:
            entry = self.files(edition)["installer"]["Installers"][0]
            name = {"standard": "CodexAutoResume-Setup-v0.6.15.exe",
                    "advanced": "CodexAutoResume-Advanced-Setup-v0.6.15.exe"}[edition]
            self.assertEqual(entry["InstallerUrl"],
                             "https://github.com/example-owner/example-repo/releases/download/v0.6.15/" + name)
            self.assertEqual(entry["InstallerSha256"], DIGESTS[edition].upper())

    def test_the_url_is_built_from_the_real_release_json_the_same_way(self):
        release = json.loads((ROOT / "scripts" / "release.json").read_text(encoding="utf-8-sig"))
        url = wm.installer_url(release, "standard", "0.6.15")
        self.assertTrue(url.startswith(release["download"].replace("{version}", "0.6.15")))
        self.assertTrue(url.endswith("/CodexAutoResume-Setup-v0.6.15.exe"))
        # The archives the setup programs carry are pinned for the last release, in both editions.
        self.assertTrue(wm.pinned(release, "standard", "0.6.15"))
        self.assertTrue(wm.pinned(release, "advanced", "0.6.15"))

    def test_the_text_is_crlf_utf8_without_a_byte_order_mark_and_quotes_every_value(self):
        for path in self.written:
            data = path.read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
            text = data.decode("utf-8")
            self.assertTrue(text.startswith("# Created using build/winget_manifests.py\r\n"))
            self.assertIn("# yaml-language-server: $schema=https://aka.ms/winget-manifest.", text)
            for line in text.split("\r\n"):
                if line and not line.startswith(("#", "- ")) and ":" in line and not line.endswith(":"):
                    self.assertRegex(line.split(": ", 1)[1], r'^".*"$')

    def test_the_korean_locale_is_korean_and_the_source_is_ascii(self):
        for edition in wm.EDITIONS:
            korean = self.files(edition)["locale"]
            self.assertRegex(korean["ShortDescription"], "[가-힣]")
            self.assertRegex(korean["Description"], "[가-힣]")
        self.assertTrue((ROOT / "build" / "winget_manifests.py").read_bytes().isascii())
        advanced = self.files("advanced")
        self.assertNotEqual(advanced["locale"]["Description"], self.files("standard")["locale"]["Description"])
        self.assertIn("advanced edition", advanced["defaultLocale"]["Description"])
        self.assertNotIn("advanced edition", self.files("standard")["defaultLocale"]["Description"])


class RefusalTests(unittest.TestCase):
    def build(self, version="0.6.15", digests=None, draft=False, release=None):
        with tempfile.TemporaryDirectory() as directory:
            return wm.build(version, DIGESTS if digests is None else digests, Path(directory), draft=draft,
                            release=release or SAMPLE)

    def test_a_pre_release_is_no_package(self):
        for version in ("0.6.16-beta.3", "0.6.16-alpha", "0.6", "v0.6.15"):
            with self.subTest(version=version), self.assertRaises(SystemExit):
                self.build(version, draft=True)

    def test_an_unpinned_archive_makes_nothing_unless_drafted(self):
        release = json.loads(json.dumps(SAMPLE))
        del release["advanced"]["sha256"]["0.6.15"]
        with self.assertRaises(SystemExit) as raised:
            self.build(release=release)
        self.assertIn("advanced archive", str(raised.exception))
        self.assertTrue(self.build(release=release, draft=True))

    def test_a_setup_program_with_no_unattended_mode_makes_nothing_unless_drafted(self):
        # 0.6.15 is the last release without it.
        with self.assertRaises(SystemExit) as raised:
            self.build()
        self.assertIn("unattended", str(raised.exception))
        self.assertEqual(len(self.build(draft=True)), 8)

    def test_from_the_version_that_has_the_switch_the_manifests_are_made(self):
        self.assertEqual(wm.UNATTENDED_FROM, "0.6.16")
        self.assertEqual(len(self.build("0.6.16")), 8)
        with patch.object(wm, "UNATTENDED_FROM", None), self.assertRaises(SystemExit):
            self.build("0.6.16")
        with patch.object(wm, "UNATTENDED_FROM", "0.6.17"), self.assertRaises(SystemExit):
            self.build("0.6.16")

    def test_the_switch_is_the_one_the_launchers_the_setup_program_and_the_entry_use(self):
        self.assertEqual(wm.UNATTENDED_SWITCH, "-Silent")
        for name in ("Install.cmd", "Uninstall.cmd"):
            text = (ROOT / "build" / "install" / name).read_text(encoding="utf-8")
            self.assertIn('"%%~A"=="' + wm.UNATTENDED_SWITCH + '"', text)
        self.assertIn('"%s"' % wm.UNATTENDED_SWITCH, (ROOT / "build" / "setup" / "Setup.cs").read_text(encoding="utf-8"))
        self.assertIn("[switch]$Silent", (ROOT / "build" / "install" / "install.ps1").read_text(encoding="utf-8"))
        self.assertTrue(addremove.uninstall_command(Path("C:/home"), silent=True).endswith('"' + wm.UNATTENDED_SWITCH + '"'))
        entry = {"standard": "Codex Auto Resume", "advanced": "Codex Auto Resume Advanced"}
        for edition in wm.EDITIONS:
            self.assertEqual(wm.display_name(edition), entry[edition])
        self.assertEqual(wm.PUBLISHER, addremove.PUBLISHER)

    def test_a_digest_that_is_not_a_digest_is_refused(self):
        for bad in ("", "xyz", "a" * 63, "g" * 64):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                self.build(digests={"standard": bad, "advanced": DIGESTS["advanced"]}, draft=True)
        with self.assertRaises(SystemExit):
            self.build(digests={"standard": DIGESTS["standard"]}, draft=True)


class SidecarTests(unittest.TestCase):
    def test_the_digest_is_read_from_the_file_published_beside_the_setup_program(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for edition, digest in DIGESTS.items():
                name = "CodexAutoResume%s-Setup-v0.6.15.exe" % ("-Advanced" if edition == "advanced" else "")
                (folder / (name + ".sha256")).write_text("%s  %s\n" % (digest, name), encoding="utf-8")
                self.assertEqual(wm.read_sidecar(folder, edition, "0.6.15"), digest)
            (folder / "CodexAutoResume-Setup-v0.6.15.exe.sha256").write_text("%s  other.exe\n" % DIGESTS["standard"], encoding="utf-8")
            with self.assertRaises(SystemExit):
                wm.read_sidecar(folder, "standard", "0.6.15")
            with self.assertRaises(SystemExit):
                wm.read_sidecar(folder, "standard", "9.9.9")

    def test_the_command_line_writes_the_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with contextlib.redirect_stdout(io.StringIO()):
                code = wm.main(["--version", "0.6.15", "--draft", "--out", directory,
                                "--sha256", "standard=" + DIGESTS["standard"],
                                "--sha256", "advanced=" + DIGESTS["advanced"]])
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(directory).rglob("*.yaml"))), 8)


class ReaderTests(unittest.TestCase):
    def test_the_small_reader_reads_what_the_writer_writes(self):
        data = {"A": "x", "B": ["p", "q"], "C": {"D": "e", "F": ["g"]}, "H": [{"I": "j", "K": "l"}, {"I": "m"}], "N": "o"}
        self.assertEqual(read_yaml(wm.render(data, "locale")), data)


if __name__ == "__main__":
    unittest.main()

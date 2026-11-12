"""Run on another Python version (python_choice, v0.6.23): python.org's list, what is verified before a byte runs, the card
and its bridge commands, and how a choice is taken back.

With fakes for the network, the signature check and every process: no download, no install, no real home.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests -p test_advanced_python_choice.py
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase  # noqa: E402,F401
from codex_auto_resume import chosen_runtime as chosen, l10n, notifier  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced import registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.control import pythons  # noqa: E402
from codex_auto_resume_advanced.courier import http, pythonorg  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, BridgeCommand, Refusal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "advanced" / "src" / "codex_auto_resume_advanced"
VERSION = "3.15.2"
RELEASE = 1170
URL = pythonorg.PACKAGE % (VERSION, VERSION)


class Reply:
    def __init__(self, body, status=200):
        self.stream, self.status = io.BytesIO(body), status

    def read(self, count=-1):
        return self.stream.read(count)

    def close(self):
        pass


class Opener:
    """Answers each address from a table, and remembers what was asked."""

    def __init__(self, table):
        self.table, self.asked = table, []

    def open(self, request, timeout=None):
        self.asked.append(request.full_url)
        return Reply(self.table[request.full_url])


def release(name, number, pre=False, uri=None):
    return {"name": name, "pre_release": pre,
            "resource_uri": uri or "https://www.python.org/api/v2/downloads/release/%d/" % number}


def file_row(**changed):
    row = {"name": pythonorg.FILE_NAME, "url": URL, "sha256_sum": "a" * 64, "filesize": 1000}
    row.update(changed)
    return row


def good_zip(version=VERSION, extra=(), names=None) -> bytes:
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as bundle:
        for name in (chosen.required(version) if names is None else names):
            bundle.writestr(name, b"bytes of " + name.encode())
        for name in extra:
            bundle.writestr(name, b"more")
    return made.getvalue()


class ListTests(unittest.TestCase):
    def newest(self, rows):
        return pythonorg.newest(pythons.LINES, opener=Opener({pythonorg.RELEASES: json.dumps(rows).encode()}))

    def test_the_newest_patch_of_each_allowed_line(self):
        """Compared as numbers: 3.13.9 is older than 3.13.18. Fails with a string comparison."""
        found = self.newest([release("Python 3.13.9", 1), release("Python 3.13.18", 2), release("Python 3.14.10", 3),
                             release("Python 3.15.0", 4), release("Python 3.15.2", 5), release("Python 3.12.9", 6),
                             release("Python 3.16.0", 7)])
        self.assertEqual(found, {"3.13": {"version": "3.13.18", "release": 2}, "3.14": {"version": "3.14.10", "release": 3},
                                 "3.15": {"version": "3.15.2", "release": 5}})

    def test_pre_releases_and_other_names_are_passed_over(self):
        found = self.newest([release("Python 3.15.2", 5), release("Python 3.15.3", 6, pre=True),
                             release("Python 3.15.4rc1", 7), release("Python 3.15.5 (old)", 8), release("python 3.15.6", 9),
                             release("Python 3.15.7", 10, uri="https://elsewhere.example/api/v2/downloads/release/10/"),
                             {"name": "Python 3.15.8", "resource_uri": "https://www.python.org/api/v2/downloads/release/11/"}])
        self.assertEqual(found["3.15"]["version"], "3.15.2")

    def test_only_python_org_is_asked_and_an_answer_is_bounded(self):
        opener = Opener({pythonorg.RELEASES: b"[]"})
        pythonorg.newest(pythons.LINES, opener=opener)
        self.assertEqual(opener.asked, ["https://www.python.org/api/v2/downloads/release/?version=3&is_published=true"])
        with self.assertRaises(pythonorg.Refused) as refused:
            pythonorg.newest(pythons.LINES, opener=Opener({pythonorg.RELEASES: b"[" * (pythonorg.ANSWER_MOST + 10)}))
        self.assertEqual(refused.exception.step, pythonorg.LIST)

    def test_a_list_that_cannot_be_read(self):
        for body in (b"not json", b"{}"):
            with self.subTest(body), self.assertRaises(pythonorg.Refused):
                pythonorg.newest(pythons.LINES, opener=Opener({pythonorg.RELEASES: body}))


class OfferTests(unittest.TestCase):
    """What a Check offers of each line (v0.6.23 final): its newest release whose files include the Windows embeddable
    package. python.org's answers here are fixtures of the shape its API gives; nothing reaches the network."""

    LIST = [release("Python 3.13.16", 101), release("Python 3.13.17", 102), release("Python 3.13.18", 103),
            release("Python 3.14.10", 201), release("Python 3.15.2", 301)]

    def opener(self, files, rows=None):
        table = {pythonorg.RELEASES: json.dumps(self.LIST if rows is None else rows).encode()}
        table.update({pythonorg.FILES % number: json.dumps(found).encode() for number, found in files.items()})
        return Opener(table)

    @staticmethod
    def source_only(version):
        return [{"name": "Gzipped source tarball", "url": "https://www.python.org/ftp/python/%s/Python-%s.tgz" % (version, version)},
                {"name": "XZ compressed source tarball",
                 "url": "https://www.python.org/ftp/python/%s/Python-%s.tar.xz" % (version, version)}]

    @staticmethod
    def with_package(version):
        return OfferTests.source_only(version) + [file_row(url=pythonorg.PACKAGE % (version, version))]

    def test_a_line_whose_newest_release_is_source_only_offers_the_release_before(self):
        """3.13.18 on 2026-11-11: source alone, so 3.13.17 is offered. Fails with the newest release offered as it was."""
        opener = self.opener({103: self.source_only("3.13.18"), 102: self.with_package("3.13.17"),
                              101: self.with_package("3.13.16"), 201: self.with_package("3.14.10"),
                              301: self.with_package("3.15.2")})
        self.assertEqual(pythonorg.offered(pythons.LINES, opener=opener),
                         {"3.13": {"version": "3.13.17", "release": 102}, "3.14": {"version": "3.14.10", "release": 201},
                          "3.15": {"version": "3.15.2", "release": 301}})
        self.assertNotIn(pythonorg.FILES % 101, opener.asked, "asked newest first, and no further than the first with one")
        self.assertEqual(opener.asked.index(pythonorg.FILES % 103) + 1, opener.asked.index(pythonorg.FILES % 102))

    def test_a_line_with_no_package_at_all_is_left_out(self):
        opener = self.opener({103: self.source_only("3.13.18"), 102: self.source_only("3.13.17"),
                              101: self.source_only("3.13.16"), 201: self.with_package("3.14.10"),
                              301: self.with_package("3.15.2")})
        self.assertEqual(set(pythonorg.offered(pythons.LINES, opener=opener)), {"3.14", "3.15"})

    def test_a_32_bit_or_another_package_is_not_the_embeddable(self):
        opener = self.opener({103: [file_row(name="Windows embeddable package (32-bit)", url="x"),
                                    file_row(name="Windows installer (64-bit)", url="y")],
                              102: self.with_package("3.13.17"), 201: [], 301: self.with_package("3.15.2")},
                             rows=self.LIST[1:])
        found = pythonorg.offered(pythons.LINES, opener=opener)
        self.assertEqual(found["3.13"]["version"], "3.13.17")
        self.assertNotIn("3.14", found)

    def test_a_files_list_that_cannot_be_read_fails_the_check(self):
        """As the list's own failure: a release that could not be asked is not passed over as one with no package."""
        opener = self.opener({103: self.source_only("3.13.18"), 201: self.with_package("3.14.10"),
                              301: self.with_package("3.15.2")})
        opener.table[pythonorg.FILES % 102] = b"not json"
        with self.assertRaises(pythonorg.Refused) as refused:
            pythonorg.offered(pythons.LINES, opener=opener)
        self.assertEqual(refused.exception.step, pythonorg.LIST)

    def test_a_line_s_releases_are_asked_at_most_so_far(self):
        patches = range(pythonorg.RELEASES_MOST + 5)
        rows = [release("Python 3.13.%d" % patch, 1000 + patch) for patch in patches]
        opener = self.opener({1000 + patch: self.source_only("3.13.%d" % patch) for patch in patches}, rows=rows)
        self.assertEqual(pythonorg.offered(pythons.LINES, opener=opener), {})
        self.assertEqual(len([url for url in opener.asked if url != pythonorg.RELEASES]), pythonorg.RELEASES_MOST)

    def test_only_python_org_is_asked(self):
        opener = self.opener({103: self.with_package("3.13.18"), 201: self.with_package("3.14.10"),
                              301: self.with_package("3.15.2")})
        pythonorg.offered(pythons.LINES, opener=opener)
        self.assertEqual({url.split("/")[2] for url in opener.asked}, {"www.python.org"})

    def test_the_check_asks_for_releases_with_a_package(self):
        """Fails with the check asking for the newest release alone (v0.6.23-beta.2)."""
        with patch.object(pythonorg, "offered", return_value={"3.14": {"version": "3.14.10", "release": 201}}) as asked:
            self.assertEqual(pythons.Hands.newest(pythons.LINES), {"3.14": {"version": "3.14.10", "release": 201}})
        asked.assert_called_once_with(pythons.LINES)


class SourceTests(unittest.TestCase):
    def files(self, *rows):
        return Opener({pythonorg.FILES % RELEASE: json.dumps(list(rows)).encode()})

    def refused(self, *rows):
        with self.assertRaises(pythonorg.Refused) as refused:
            pythonorg.embeddable(RELEASE, VERSION, opener=self.files(*rows))
        self.assertEqual(refused.exception.step, pythonorg.SOURCE)

    def test_the_official_file(self):
        self.assertEqual(pythonorg.embeddable(RELEASE, VERSION, opener=self.files(
            file_row(name="Windows embeddable package (32-bit)", url="x"), file_row())),
            {"url": URL, "sha256": "a" * 64, "size": 1000})

    def test_a_wrong_host_or_file_name_is_refused(self):
        """Fails with the exact comparison reverted: an answer could name any address to download from."""
        for url in ("https://evil.example/ftp/python/3.15.2/python-3.15.2-embed-amd64.zip",
                    "http://www.python.org/ftp/python/3.15.2/python-3.15.2-embed-amd64.zip",
                    "https://www.python.org.evil.example/ftp/python/3.15.2/python-3.15.2-embed-amd64.zip",
                    "https://www.python.org/ftp/python/3.15.2/python-3.15.2-embed-arm64.zip",
                    "https://www.python.org/ftp/python/3.15.1/python-3.15.1-embed-amd64.zip",
                    "https://www.python.org/ftp/python/3.15.2/evil.zip", None):
            with self.subTest(url):
                self.refused(file_row(url=url))

    def test_a_digest_or_size_not_of_its_shape(self):
        for changed in ({"sha256_sum": "abc"}, {"sha256_sum": "A" * 64}, {"sha256_sum": None}, {"filesize": 0},
                        {"filesize": "1000"}, {"filesize": pythonorg.PACKAGE_MOST + 1}):
            with self.subTest(changed):
                self.refused(file_row(**changed))

    def test_none_or_two_such_files(self):
        self.refused()
        self.refused(file_row(), file_row())

    def test_the_download_is_bounded_by_the_size_given(self):
        with tempfile.TemporaryDirectory() as folder:
            found = {"url": URL, "size": 4, "sha256": "a" * 64}
            with self.assertRaises(pythonorg.Refused) as refused:
                pythonorg.download(found, Path(folder) / "a.zip", opener=Opener({URL: b"12345"}))
            self.assertEqual(refused.exception.step, pythonorg.DOWNLOAD)
            with self.assertRaises(pythonorg.Refused):
                pythonorg.download(found, Path(folder) / "b.zip", opener=Opener({URL: b"123"}))

    def test_progress_is_the_bytes_written(self):
        with tempfile.TemporaryDirectory() as folder:
            seen = []
            found = {"url": URL, "size": 200000, "sha256": "a" * 64}
            self.assertEqual(pythonorg.download(found, Path(folder) / "a.zip", opener=Opener({URL: b"x" * 200000}),
                                                progress=lambda got, total: seen.append((got, total))), 200000)
            self.assertEqual(seen[-1], (200000, 200000))
            self.assertEqual([got for got, _total in seen], sorted(got for got, _total in seen))
            self.assertGreater(len(seen), 1)

    def test_http_still_refuses_a_redirect_and_keeps_its_default_bound(self):
        self.assertEqual(http.MAX_REPLY, 65536)
        body = b"x" * (http.MAX_REPLY + 5)
        self.assertEqual(len(http.get(URL, opener=Opener({URL: body}))), http.MAX_REPLY)


class FakeRuntime:
    def __init__(self, home, state=ArmingState.ARMED):
        self.paths = type("Paths", (), {"home": Path(home), "state_dir": Path(home) / "config"})()
        self.stand, self.counts, self.arming = state, [], None
        self.state = self
        self.read_states = 0

    def states(self, fresh=False):
        self.read_states += 1
        return {pythons.CAPABILITY: self.stand}

    def counted(self, _capability, code):
        self.counts.append(code)


class Hands:
    """The outside world, answering as a test says, with a log of the order it was asked in."""

    def __init__(self, archive=None, digest=None, signers=None, imports=True, restart=pythons.RUNNING):
        self.archive = good_zip() if archive is None else archive
        self.digest = hashlib.sha256(self.archive).hexdigest() if digest is None else digest
        self.signers, self.importing, self.restarting = signers or {}, imports, restart
        self.log = []

    def newest(self, _lines):
        return {"3.15": {"version": VERSION, "release": RELEASE}, "3.13": {"version": "3.13.18", "release": 1169}}

    def embeddable(self, release_id, version):
        return {"url": pythonorg.PACKAGE % (version, version), "sha256": self.digest, "size": len(self.archive)}

    def download(self, _found, target, progress):
        self.log.append("download")
        Path(target).write_bytes(self.archive)
        progress(len(self.archive), len(self.archive))

    def signer(self, path):
        self.log.append("signer")
        said = self.signers.get(Path(path).name, pythons.PYTHON_SIGNER)
        if isinstance(said, Exception):
            raise said
        return said

    def imports(self, python, _paths):
        self.log.append("imports")
        self.python_run = python
        if isinstance(self.importing, Exception):
            raise self.importing
        return self.importing

    def restart(self, _paths):
        self.log.append("restart")
        if callable(self.restarting):
            return self.restarting()
        return self.restarting

    def bundled(self, _paths):
        return "3.14.10"


def inline(job):
    job()


class Case(unittest.TestCase):
    def setUp(self):
        made = tempfile.TemporaryDirectory()
        self.addCleanup(made.cleanup)
        self.home = Path(made.name) / "home"
        (self.home / "runtime").mkdir(parents=True)
        (self.home / "runtime" / "python.exe").write_bytes(b"bundled")
        self.runtime = FakeRuntime(self.home)
        self.addCleanup(self.forget)
        for name, value in (("bundled_version", lambda _paths: "3.14.10"), ("in_use", lambda _paths, bundled: bundled)):
            patcher = patch.object(pythons, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def forget(self):
        for table in (pythons._JOBS, pythons._OUTCOMES, pythons._OFFERS):
            table.pop(self.home, None)

    def outcome(self):
        return pythons._OUTCOMES.get(self.home)

    def checked(self, hands):
        self.assertTrue(pythons.check(self.runtime, start=inline, hands=hands)["done"])

    def chosen_now(self, hands):
        self.checked(hands)
        return pythons.use(self.runtime, {"version": VERSION}, start=inline, hands=hands)

    def record(self):
        return chosen.recorded(self.home)

    def folder(self, version=VERSION):
        return chosen.folder(self.home, version)

    def give_record(self, version=VERSION, make=True):
        where = chosen.folder(self.home, version)
        where.mkdir(parents=True, exist_ok=True)
        if make:
            for name in chosen.required(version):
                (where / name).write_bytes(b"x")
        pythons._write(chosen.root(self.home) / chosen.RECORD, {"version": version})


class VerifyTests(Case):
    def test_all_that_comes_before_it_runs(self):
        hands = Hands()
        self.assertTrue(self.chosen_now(hands)["done"])
        self.assertEqual(self.outcome(), {"word": pythons.CHOSEN_DONE, "step": None, "version": VERSION})
        self.assertEqual(self.record(), VERSION)
        self.assertEqual(hands.log, ["download", "signer", "signer", "signer", "imports", "restart"])
        self.assertEqual(hands.python_run, self.folder() / "python.exe")
        self.assertTrue(chosen.complete(self.home, VERSION))
        self.assertEqual(list(chosen.root(self.home).glob(".incoming-*")), [], "the download is not kept")

    def assert_refused(self, hands, step):
        self.assertTrue(self.chosen_now(hands)["done"])
        self.assertEqual(self.outcome(), {"word": pythons.FAILED, "step": step, "version": VERSION})
        self.assertIsNone(self.record(), "the runtime in use stays")
        self.assertFalse(self.folder().exists(), "what was unpacked is deleted")
        self.assertEqual(list(chosen.root(self.home).glob(".incoming-*")), [])
        self.assertNotIn("restart", hands.log)

    def test_a_digest_that_does_not_match(self):
        """Fails with the check reverted. Nothing is unpacked, so nothing is signature-checked or run."""
        hands = Hands(digest="b" * 64)
        self.assert_refused(hands, pythons.DIGEST)
        self.assertEqual(hands.log, ["download"])

    def test_the_digest_is_of_the_bytes_on_disk(self):
        hands = Hands()
        original = hands.download

        def tampered(found, target, progress):
            original(found, target, progress)
            Path(target).write_bytes(hands.archive + b"changed after the download")
        hands.download = tampered
        self.assert_refused(hands, pythons.DIGEST)

    def test_every_unsafe_member_is_refused_before_anything_is_written(self):
        for bad in ("../evil.dll", "..\\evil.dll", "/abs.dll", "C:/abs.dll", "C:\\abs.dll", "sub/inner.dll", "sub\\inner.dll",
                    "CON.dll", "nul.txt", ".hidden.dll", "noextension", "a b.dll"):
            with self.subTest(bad):
                self.forget()
                hands = Hands(archive=good_zip(extra=[bad]))
                self.assert_refused(hands, pythons.UNPACK)
                self.assertEqual(hands.log, ["download"])
        self.assertEqual([path.name for path in self.home.parent.iterdir()], ["home"], "nothing outside the home")

    def test_a_link_a_folder_a_duplicate_a_missing_file(self):
        link = io.BytesIO()
        with zipfile.ZipFile(link, "w") as bundle:
            for name in chosen.required(VERSION):
                bundle.writestr(name, b"x")
            entry = zipfile.ZipInfo("link.dll")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(entry, b"elsewhere")
        folder = io.BytesIO()
        with zipfile.ZipFile(folder, "w") as bundle:
            for name in chosen.required(VERSION):
                bundle.writestr(name, b"x")
            bundle.writestr("folder.d/", b"")
        with self.assertWarns(UserWarning):
            twice = good_zip(extra=["python.exe"])
        for label, archive in (("link", link.getvalue()), ("folder", folder.getvalue()), ("twice", twice),
                               ("case", good_zip(extra=["PYTHON.EXE"])),
                               ("missing", good_zip(names=chosen.required(VERSION)[1:])),
                               ("not a zip", b"not a zip file")):
            with self.subTest(label):
                self.forget()
                self.assert_refused(Hands(archive=archive), pythons.UNPACK)

    def test_too_much_is_refused(self):
        with patch.object(pythons, "UNPACKED_MOST", 8):
            self.assert_refused(Hands(), pythons.UNPACK)
        self.forget()
        with patch.object(pythons, "MEMBERS_MOST", 2):
            self.assert_refused(Hands(), pythons.UNPACK)

    def test_each_of_the_three_files_must_be_signed_by_the_foundation(self):
        """Fails with the comparison reverted. Nothing has run: no import check."""
        for name in ("python.exe", "pythonw.exe", "python315.dll"):
            for said in ("OpenAI OpCo, LLC", "python software foundation", AdapterError("unsigned"),
                         AdapterError("signature_invalid"), AdapterError("signature_untrusted")):
                with self.subTest(name=name, said=str(said)):
                    self.forget()
                    hands = Hands(signers={name: said})
                    self.assert_refused(hands, pythons.SIGNATURE)
                    self.assertNotIn("imports", hands.log)

    # A package as python.org ships it: extension modules, the stable ABI's DLL, other DLLs and the Visual C++ runtime.
    PROGRAMS = ("_socket.pyd", "_ssl.pyd", "python3.dll", "libcrypto-3.dll", "sqlite3.dll", "vcruntime140.dll",
                "vcruntime140_1.dll")
    MICROSOFT = {"vcruntime140.dll": "Microsoft Windows Software Compatibility Publisher",
                 "vcruntime140_1.dll": "Microsoft Corporation"}

    def test_the_genuine_set_is_signed_file_by_file_and_passes(self):
        """S3 of the second round: every *.exe, *.dll and *.pyd asked, the Visual C++ runtime as Microsoft's; the stdlib
        zip, the ._pth and other files are not programs and are not asked."""
        hands = Hands(archive=good_zip(extra=self.PROGRAMS + ("LICENSE.txt",)), signers=dict(self.MICROSOFT))
        self.assertTrue(self.chosen_now(hands)["done"])
        self.assertEqual(self.outcome(), {"word": pythons.CHOSEN_DONE, "step": None, "version": VERSION})
        self.assertEqual(hands.log.count("signer"), 3 + len(self.PROGRAMS))
        self.assertLess(hands.log.index("signer"), hands.log.index("imports"))
        self.assertEqual(hands.log[-2:], ["imports", "restart"])

    def test_one_program_file_not_signed_by_the_foundation_refuses_the_version(self):
        """Fails with S3 reverted: a _socket.pyd of anyone's would have been loaded by the import step, and then at every start."""
        for name in ("_socket.pyd", "libcrypto-3.dll", "python3.dll"):
            for said in (AdapterError("unsigned"), AdapterError("signature_invalid"), "Microsoft Corporation",
                         "Microsoft Windows Software Compatibility Publisher", "Someone Else", "python software foundation"):
                with self.subTest(name=name, said=str(said)):
                    self.forget()
                    signers = dict(self.MICROSOFT, **{name: said})
                    hands = Hands(archive=good_zip(extra=self.PROGRAMS), signers=signers)
                    self.assert_refused(hands, pythons.SIGNATURE)
                    self.assertNotIn("imports", hands.log)

    def test_the_visual_c_runtime_is_still_held_to_a_valid_signature(self):
        for said in (AdapterError("unsigned"), "Someone Else", "microsoft corporation"):
            with self.subTest(said=str(said)):
                self.forget()
                signers = dict(self.MICROSOFT, **{"vcruntime140.dll": said})
                self.assert_refused(Hands(archive=good_zip(extra=self.PROGRAMS), signers=signers), pythons.SIGNATURE)

    def test_a_program_whose_name_is_spelt_in_capitals_is_asked_too(self):
        hands = Hands(archive=good_zip(extra=("_EVIL.PYD",)), signers={"_EVIL.PYD": AdapterError("unsigned")})
        self.assert_refused(hands, pythons.SIGNATURE)

    def test_a_refused_signature_reaches_the_card_in_the_existing_words(self):
        """The refusal is the signature step's, whose words already say "a program in the package"."""
        words = json.loads((PACKAGE_DIR / "locales" / "en.json").read_text(encoding="utf-8"))
        self.assertIn("program in the package", words["page.python.failed.signature"])

    def test_the_signature_check_is_core_s_shared_one(self):
        text = (PACKAGE_DIR / "control" / "pythons.py").read_text(encoding="utf-8")
        self.assertIn("from codex_auto_resume.win import authenticode", text)
        self.assertNotIn("WinVerifyTrust(", text)
        with patch.object(pythons.authenticode, "signer", return_value="x") as asked:
            self.assertEqual(pythons.Hands.signer("p"), "x")
        asked.assert_called_once_with("p")

    def test_a_failed_import_check(self):
        for imports in (False, None, subprocess.TimeoutExpired("x", 1), OSError("no")):
            with self.subTest(str(imports)):
                self.forget()
                self.assert_refused(Hands(imports=imports), pythons.IMPORT)

    def test_a_failed_step_leaves_a_runtime_already_chosen(self):
        self.give_record("3.13.18")
        self.assert_refused_keeping(Hands(digest="b" * 64))

    def assert_refused_keeping(self, hands):
        self.assertTrue(self.chosen_now(hands)["done"])
        self.assertEqual(self.record(), "3.13.18")
        self.assertTrue(chosen.complete(self.home, "3.13.18"))

    def test_a_previous_runtime_goes_only_after_a_new_one_succeeded(self):
        self.give_record("3.13.18")
        seen = []
        hands = Hands(restart=lambda: seen.append(self.folder("3.13.18").is_dir()) or pythons.RUNNING)
        self.chosen_now(hands)
        self.assertEqual(seen, [True])
        self.assertFalse(self.folder("3.13.18").exists())
        self.assertEqual(self.record(), VERSION)

    def test_only_what_the_last_check_offered_can_be_used(self):
        """Fails with the offer lookup reverted: the window's word would name what is downloaded."""
        hands = Hands()
        self.assertEqual(pythons.use(self.runtime, {"version": VERSION}, start=inline, hands=hands)["refusal"], Refusal.INVALID_REQUEST)
        self.checked(hands)
        for version in ("3.15.9", "../x", None, 3):
            with self.subTest(version):
                self.assertEqual(pythons.use(self.runtime, {"version": version}, start=inline, hands=hands)["refusal"],
                                 Refusal.INVALID_REQUEST)
        self.assertEqual(hands.log, [])

    def test_the_version_already_chosen_is_not_put_in_again(self):
        hands = Hands()
        self.checked(hands)
        self.give_record()
        self.assertEqual(pythons.use(self.runtime, {"version": VERSION}, start=inline, hands=hands)["refusal"], Refusal.INVALID_REQUEST)

    def test_off_or_watched_nothing_is_pressed(self):
        hands = Hands()
        for stand in (ArmingState.OFF, ArmingState.SHADOW):
            self.runtime.stand = stand
            with self.subTest(stand):
                self.assertEqual(pythons.check(self.runtime, start=inline, hands=hands)["refusal"], Refusal.NOT_ON)
                self.assertEqual(pythons.use(self.runtime, {"version": VERSION}, start=inline, hands=hands)["refusal"], Refusal.NOT_ON)
        self.assertEqual(hands.log, [])

    def test_one_at_a_time(self):
        held = []
        self.assertTrue(pythons.check(self.runtime, start=held.append, hands=Hands())["done"])
        self.assertEqual(pythons.check(self.runtime, start=inline, hands=Hands())["refusal"], Refusal.PYTHON_BUSY)
        self.assertEqual(pythons.back(self.runtime, start=inline, hands=Hands())["refusal"], Refusal.PYTHON_BUSY)
        held[0]()
        self.assertTrue(pythons.check(self.runtime, start=inline, hands=Hands())["done"])


class ReturnTests(Case):
    def setUp(self):
        super().setUp()
        self.told = []
        patcher = patch.object(pythons, "returned_notice", lambda _paths, version, why: self.told.append((version, why)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def supervised(self, phase=pythons.PHASE_RUNTIME):
        return pythons.supervised(self.runtime, {"phase": phase})

    def test_the_launcher_s_words_are_its_own(self):
        text = (ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8")
        self.assertIn('PHASE_RUNTIME, PHASE_RUNTIME_FAILED = "%s", "%s"'
                      % (pythons.PHASE_RUNTIME, pythons.PHASE_RUNTIME_FAILED), text)
        self.assertEqual(pythons.USE_CHOSEN, "supervise")

    def test_with_no_record_nothing_is_read(self):
        self.assertIs(self.supervised(), DEFER)
        self.assertEqual(self.runtime.read_states, 0)

    def test_a_good_choice_is_used(self):
        self.give_record()
        self.assertEqual(self.supervised(), pythons.USE_CHOSEN)
        self.assertEqual(self.told, [])

    def test_the_automatic_return_says_so_once(self):
        """Fails with the taking back reverted: the next start would try the same Python again."""
        self.give_record()
        self.assertIs(self.supervised(pythons.PHASE_RUNTIME_FAILED), DEFER)
        self.assertIsNone(self.record())
        self.assertEqual(self.told, [(VERSION, pythons.WHY_START)])
        self.assertIs(self.supervised(pythons.PHASE_RUNTIME_FAILED), DEFER)
        self.assertIs(self.supervised(), DEFER)
        self.assertEqual(len(self.told), 1, "once")
        self.assertEqual(pythons._returned(self.home), {"why": pythons.WHY_START, "version": VERSION})

    def test_an_update_keeps_a_choice_on_a_line_still_allowed(self):
        self.give_record("3.13.18")
        self.assertEqual(self.supervised(), pythons.USE_CHOSEN)
        self.assertEqual(self.record(), "3.13.18")

    def test_an_update_drops_a_choice_on_a_line_no_longer_allowed_with_a_notice(self):
        self.give_record("3.13.18")
        with patch.object(pythons, "LINES", ("3.14", "3.15")):
            self.assertIs(self.supervised(), DEFER)
        self.assertIsNone(self.record())
        self.assertEqual(self.told, [("3.13.18", pythons.WHY_LINE)])

    def test_a_damaged_runtime_is_taken_back_with_a_notice(self):
        self.give_record()
        (self.folder() / "python315.dll").unlink()
        self.assertIs(self.supervised(), DEFER)
        self.assertIsNone(self.record())
        self.assertEqual(self.told, [(VERSION, pythons.WHY_START)])

    def test_a_capability_that_is_off_leaves_the_record_with_no_notice(self):
        self.give_record()
        self.runtime.stand = ArmingState.OFF
        self.assertIs(self.supervised(), DEFER)
        self.assertIsNone(self.record())
        self.assertEqual(self.told, [])
        self.assertEqual(pythons._returned(self.home)["why"], pythons.WHY_OFF)

    def test_back_works_with_the_chosen_runtime_broken(self):
        """Fails if Back needed the chosen runtime."""
        self.give_record(make=False)
        hands = Hands()
        self.assertTrue(pythons.back(self.runtime, start=inline, hands=hands)["done"])
        self.assertIsNone(self.record())
        self.assertEqual(hands.log, ["restart"])
        self.assertEqual(self.outcome()["word"], pythons.BACK_DONE)

    def test_back_says_back_only_where_the_restart_came_up(self):
        """M2 of the second round. Fails with the outcome reverted: "Back on the bundled version" above an in-use line that
        says the watcher still runs on the chosen one."""
        for came in (pythons.STILL_RUNNING, pythons.NOT_RUNNING, "exited", "unconfirmed"):
            with self.subTest(came=came):
                self.forget()
                self.give_record()
                self.assertTrue(pythons.back(self.runtime, start=inline, hands=Hands(restart=came))["done"])
                self.assertIsNone(self.record())
                self.assertEqual(self.outcome(), {"word": pythons.NEXT_START, "step": None, "version": "3.14.10"},
                                 "the bundled version, taken when the watcher next starts")

    def test_a_watcher_that_did_not_stop_keeps_its_runtime(self):
        self.give_record()
        pythons.back(self.runtime, start=inline, hands=Hands(restart=pythons.STILL_RUNNING))
        self.assertTrue(chosen.complete(self.home, VERSION), "not swept from under the watcher still on it")
        self.forget()
        self.give_record()
        pythons.back(self.runtime, start=inline, hands=Hands(restart=pythons.RUNNING))
        self.assertFalse(self.folder().exists(), "swept once the watcher came up on the bundled runtime")

    def test_with_the_bundled_version_unknown_no_done_line_is_made_up(self):
        self.give_record()
        hands = Hands(restart=pythons.STILL_RUNNING)
        hands.bundled = lambda _paths: None
        pythons.back(self.runtime, start=inline, hands=hands)
        self.assertIsNone(self.outcome())

    def test_the_record_goes_before_the_restart(self):
        self.give_record()
        seen = []
        pythons.back(self.runtime, start=inline, hands=Hands(restart=lambda: seen.append(self.record()) or pythons.RUNNING))
        self.assertEqual(seen, [None])

    def test_a_restart_the_launcher_took_back_is_a_failed_start(self):
        def taken():
            pythons._taken_back(self.runtime, VERSION, pythons.WHY_START)
            return pythons.RUNNING
        hands = Hands(restart=taken)
        self.chosen_now(hands)
        self.assertEqual(self.outcome(), {"word": pythons.FAILED, "step": pythons.START, "version": VERSION})
        self.assertIsNone(self.record())
        self.assertEqual(len(self.told), 1)

    def test_a_restart_with_no_end_in_time_is_taken_back_here(self):
        answers = iter(["unconfirmed", pythons.RUNNING])
        hands = Hands(restart=lambda: next(answers))
        self.chosen_now(hands)
        self.assertEqual(self.outcome()["step"], pythons.START)
        self.assertIsNone(self.record())
        self.assertEqual(hands.log.count("restart"), 2, "once more, on the bundled runtime")

    def test_the_dashboard_waits_past_the_launcher_s_slowest_healthy_start(self):
        """Fails with v0.6.23-beta.2's 90 s: the launcher's question took 48 s on the owner's PC before its child, which then
        has 45 s of its own, so a healthy start could be taken back from here by the wrong clock."""
        launcher = (ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8")
        self.assertIn("WATCHER_WAIT = %r" % pythons.WATCHER_WAIT, launcher)
        from codex_auto_resume import control
        self.assertEqual(pythons.WATCHER_WAIT, control.WATCHER_START_TIMEOUT)
        self.assertGreaterEqual(pythons.LAUNCHER_ASKS_SEEN, 48.0)
        self.assertGreater(pythons.RESTART_SECONDS, pythons.LAUNCHER_ASKS_SEEN + pythons.WATCHER_WAIT + 30.0,
                           "room for a start on the bundled runtime after the launcher took a choice back")

    def test_the_restart_is_waited_for_that_long(self):
        from codex_auto_resume import control
        layer = control.Control
        with patch.object(layer, "watcher_running", return_value=True), \
                patch.object(layer, "stop_watcher", return_value={"stopped": True}), \
                patch.object(pythons.subprocess, "Popen") as started, \
                patch("codex_auto_resume.control.await_watcher", return_value={"state": "running"}) as waited:
            from codex_auto_resume import config
            self.assertEqual(pythons.restart_watcher(config.Paths(self.home)), pythons.RUNNING)
        self.assertEqual(waited.call_args[1]["timeout"], pythons.RESTART_SECONDS)
        self.assertTrue(started.call_args[1]["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0))

    def restart(self, stopped):
        """restart_watcher with a watcher that runs, a stop that answers with `stopped` (or raises it), and every step in order."""
        from codex_auto_resume import config, control
        order = []

        def stop(_layer):
            order.append("stop")
            if isinstance(stopped, BaseException):
                raise stopped
            return {"stopped": stopped}

        def started(*_a, **_k):
            order.append("launcher")
            return object()
        with patch.object(control.Control, "watcher_running", return_value=True), \
                patch.object(control.Control, "stop_watcher", stop), \
                patch.object(pythons.subprocess, "Popen", side_effect=started) as popen, \
                patch("codex_auto_resume.control.await_watcher", return_value={"state": "running"}):
            try:
                said = pythons.restart_watcher(config.Paths(self.home))
            except BaseException as exc:                       # noqa: BLE001 - the asking thread ended mid-restart
                said = exc
        return said, order, popen

    def test_the_new_launcher_is_started_before_the_stop_and_follows_it(self):
        """R10 of the second round. Fails with the old order: stop, then start - a window closed between the two left the
        watcher stopped and none started."""
        said, order, popen = self.restart(True)
        self.assertEqual((said, order), (pythons.RUNNING, ["launcher", "stop"]))
        self.assertEqual(popen.call_args[1]["env"].get(pythons.AFTER_STOP_MARK), "1")
        self.assertEqual(popen.call_args[0][0][-2:], [str(self.home / "watcher-launcher.py"), "run"], "the installed copy")
        self.assertEqual(popen.call_args[0][0][0], str(self.home / "runtime" / "pythonw.exe"))
        launcher = (ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8")
        self.assertIn('AFTER_STOP_MARK = "%s"' % pythons.AFTER_STOP_MARK, launcher)

    def test_the_start_does_not_need_the_asking_process_once_the_stop_is_asked(self):
        """The thread that asked ends as the stop is asked - its window closed: the detached launcher is already there."""
        said, order, popen = self.restart(SystemExit(0))
        self.assertIsInstance(said, SystemExit)
        self.assertEqual(order, ["launcher", "stop"])
        flags = popen.call_args[1]["creationflags"]
        self.assertTrue(flags & getattr(subprocess, "DETACHED_PROCESS", 0) and flags & getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def test_a_watcher_that_will_not_stop_is_still_running_and_its_follower_gives_up_alone(self):
        said, order, _popen = self.restart(False)
        self.assertEqual((said, order), (pythons.STILL_RUNNING, ["launcher", "stop"]))

    def test_with_no_watcher_running_nothing_is_started(self):
        from codex_auto_resume import config, control
        with patch.object(control.Control, "watcher_running", return_value=False), \
                patch.object(pythons.subprocess, "Popen") as popen:
            self.assertEqual(pythons.restart_watcher(config.Paths(self.home)), pythons.NOT_RUNNING)
        popen.assert_not_called()

    def test_with_no_watcher_it_waits_for_the_next_start(self):
        self.chosen_now(Hands(restart=pythons.NOT_RUNNING))
        self.assertEqual(self.outcome()["word"], pythons.NEXT_START)
        self.assertEqual(self.record(), VERSION)

    def test_a_watcher_that_would_not_stop_takes_it_at_its_next_start(self):
        self.chosen_now(Hands(restart=pythons.STILL_RUNNING))
        self.assertEqual(self.outcome()["word"], pythons.NEXT_START)

    def test_turning_it_off_goes_back(self):
        self.give_record()
        self.runtime.stand = ArmingState.OFF
        hands = Hands()
        pythons.back_when_off(self.runtime, start=inline, hands=hands)
        self.assertIsNone(self.record())
        self.assertEqual(hands.log, ["restart"])

    def test_turning_it_off_from_a_tool_leaves_the_restart_to_the_next_start(self):
        self.give_record()
        self.runtime.stand = ArmingState.OFF
        hands = Hands()
        pythons.back_when_off(self.runtime, restart=False, start=inline, hands=hands)
        self.assertIsNone(self.record())
        self.assertEqual(hands.log, [])

    def test_turning_something_else_off_changes_nothing(self):
        self.give_record()
        hands = Hands()
        pythons.back_when_off(self.runtime, start=inline, hands=hands)
        self.assertEqual(self.record(), VERSION)
        self.assertEqual(hands.log, [])

    def test_the_notice_names_the_version_and_why(self):
        made = pythons.notice_content("3.15.2", pythons.WHY_LINE)
        self.assertIn(l10n.message("toast_python_returned_line").replace("{version}", "3.15.2"), json.dumps(made, ensure_ascii=False))
        made = pythons.notice_content("<b>", pythons.WHY_START)
        self.assertNotIn("<b>", json.dumps(made), "only a version's shape reaches a notice")
        self.assertEqual(notifier.STATUS["python_returned"], "paused")
        self.assertIsNotNone(notifier.build("python_returned", {"content": pythons.notice_content("3.15.2", pythons.WHY_START)}))


class CardTests(Case):
    def test_off_nothing_is_read(self):
        self.runtime.stand = ArmingState.OFF
        self.assertEqual(pythons.view(self.runtime)["refusal"], Refusal.NOT_ON)

    def test_its_fields(self):
        found = pythons.view(self.runtime)
        self.assertEqual(found, {"done": True, "refusal": None, "bundled": "3.14.10", "chosen": None, "in_use": "3.14.10",
                                 "button": True, "checked": False, "offers": [], "missing": [], "job": None, "outcome": None,
                                 "returned": None})

    def test_reading_the_card_asks_python_org_nothing(self):
        with patch.object(pythonorg, "newest", side_effect=AssertionError), patch.object(pythonorg.http, "request", side_effect=AssertionError):
            pythons.view(self.runtime)

    def test_the_offers_after_a_check_with_the_preview_marked(self):
        self.checked(Hands())
        found = pythons.view(self.runtime)
        self.assertTrue(found["checked"])
        self.assertEqual(found["offers"], [{"version": "3.13.18", "line": "3.13", "preview": False},
                                           {"version": VERSION, "line": "3.15", "preview": True}])

    def test_a_line_with_no_package_is_named_after_a_check(self):
        """Fails with the card not saying which line python.org has no Windows package of (v0.6.23-beta.2)."""
        self.checked(Hands())
        self.assertEqual(pythons.view(self.runtime)["missing"], ["3.14"])
        hands = Hands()
        hands.newest = lambda _lines: {}
        self.checked(hands)
        self.assertEqual(pythons.view(self.runtime)["missing"], list(pythons.LINES))

    def test_the_card_says_so_in_its_own_sentence(self):
        text = (ROOT / "advanced" / "gui" / "AdvancedPythons.cs").read_text(encoding="utf-8")
        self.assertIn('Items(advancedPython, "missing")', text)
        self.assertIn('Word("page.python.no_package"', text)
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                self.assertIn("{line}", statement.CATALOGS.words(locale)["page.python.no_package"])

    def test_a_list_that_failed_says_so(self):
        hands = Hands()
        hands.newest = lambda _lines: (_ for _ in ()).throw(pythonorg.Refused(pythonorg.LIST))
        self.checked(hands)
        self.assertEqual(pythons.view(self.runtime)["outcome"]["step"], pythons.LIST)

    def test_watched_it_shows_with_no_buttons(self):
        self.runtime.stand = ArmingState.SHADOW
        self.assertFalse(pythons.view(self.runtime)["button"])

    def test_progress_is_real_bytes_while_it_downloads(self):
        seen = []
        hands = Hands()
        original = hands.download

        def looking(found, target, progress):
            original(found, target, progress)
            seen.append(dict(pythons._JOBS[self.home]))
        hands.download = looking
        self.chosen_now(hands)
        self.assertEqual((seen[0]["got"], seen[0]["total"]), (len(hands.archive), len(hands.archive)))
        self.assertEqual(seen[0]["stage"], pythons.DOWNLOADING)

    def test_each_read_clears_what_was_left_behind(self):
        self.give_record()
        chosen.folder(self.home, "3.13.18").mkdir()
        (chosen.root(self.home) / ".incoming-3.14.10.zip").write_bytes(b"x")
        (chosen.root(self.home) / "notes.txt").write_bytes(b"kept")
        pythons.view(self.runtime)
        self.assertFalse(self.folder("3.13.18").exists())
        self.assertTrue(self.folder().is_dir(), "the chosen one stays")
        self.assertEqual(sorted(path.name for path in chosen.root(self.home).iterdir() if not path.is_dir()),
                         ["chosen.json", "notes.txt"], "nothing else is touched")

    def test_while_a_job_runs_nothing_is_cleared(self):
        chosen.folder(self.home, "3.13.18").mkdir(parents=True)
        pythons._begin(self.home, {"stage": pythons.VERIFYING, "version": VERSION})
        pythons.view(self.runtime)
        self.assertTrue(self.folder("3.13.18").exists())

    def test_the_bridge_commands(self):
        for command, arguments in ((BridgeCommand.ADVANCED_PYTHON, frozenset()), (BridgeCommand.ADVANCED_PYTHON_CHECK, frozenset()),
                                   (BridgeCommand.ADVANCED_PYTHON_USE, frozenset({"version"})), (BridgeCommand.ADVANCED_PYTHON_BACK, frozenset())):
            with self.subTest(command):
                self.assertNotIn(command, surfaces.UNANSWERED)
                self.assertEqual(surfaces.ARGUMENTS[command], arguments)
        self.assertEqual(surfaces.bridge(self.runtime, "advanced-python", {})["bundled"], "3.14.10")
        with patch.object(pythons, "check", return_value="checked"):
            self.assertEqual(surfaces.bridge(self.runtime, "advanced-python-check", {}), "checked")
        with patch.object(pythons, "use", return_value="used") as used:
            self.assertEqual(surfaces.bridge(self.runtime, "advanced-python-use", {"version": VERSION}), "used")
        used.assert_called_once_with(self.runtime, {"version": VERSION})
        with patch.object(pythons, "back", return_value="back"):
            self.assertEqual(surfaces.bridge(self.runtime, "advanced-python-back", {}), "back")
        self.assertEqual(surfaces.bridge(self.runtime, "advanced-python-use", {"url": "x"})["refusal"], Refusal.INVALID_REQUEST)

    def test_no_tool_reaches_it(self):
        self.assertFalse([tool for tool in surfaces.TOOLS if "python" in tool["name"]])

    def test_the_card_s_words_exist_in_every_language(self):
        """Fails with a word left out of a catalog or of the page's keys."""
        text = (ROOT / "advanced" / "gui" / "AdvancedPythons.cs").read_text(encoding="utf-8")
        import re
        used = set(re.findall(r'Word\("(page\.[a-z_.]+)"', text))
        self.assertGreater(len(used), 30)
        self.assertLessEqual(used, set(statement.PAGE_KEYS))
        for locale in l10n.LOCALES:
            words = statement.CATALOGS.words(locale)
            with self.subTest(locale):
                self.assertLessEqual(used, set(words))
                self.assertIn("name.python_choice", words)
                for field in statement.FIELDS:
                    self.assertTrue(statement.CATALOGS.catalog(locale)[statement.key("python_choice", field)])

    def test_the_statement_says_what_it_must(self):
        words = statement.CATALOGS.catalog("en")
        does = words[statement.key("python_choice", "does")]
        for said in ("www.python.org", "runtimes\\<version>", "SHA-256", "Python Software Foundation", "only you", "replaces the bundled"):
            self.assertIn(said, does)
        stop = words[statement.key("python_choice", "stop")]
        for said in ("Back to the bundled version", "Uninstalling", "update"):
            self.assertIn(said, stop)

    def test_the_card_shows_bytes_never_a_time(self):
        text = (ROOT / "advanced" / "gui" / "AdvancedPythons.cs").read_text(encoding="utf-8")
        self.assertIn('Number(job, "got")', text)
        self.assertIn('Number(job, "total")', text)
        for word in ("remaining", "Elapsed", "estimate("):
            self.assertNotIn(word, text)


class RegistryTests(unittest.TestCase):
    def test_it_keeps_the_registry_s_rules(self):
        self.assertEqual(registry.problems(registry.PYTHON_CHOICE), [])
        self.assertEqual(registry.PYTHON_CHOICE.points, frozenset())
        made = registry.Registry(registry.DEFINITIONS + registry.INSTALLED_ONLY)
        self.assertIs(registry.shown(made)[-1], registry.PYTHON_CHOICE, "the last of the rare cases and expert settings")

    def test_only_an_installation_offers_it(self):
        """Fails with the gate reverted: a source run has no bundled runtime to come back to."""
        self.assertIsNone(registry.REGISTRY.get("python_choice"), "this is a source run")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(registry.on_an_installation(folder), ())
            (Path(folder) / "runtime").mkdir()
            (Path(folder) / "runtime" / "python.exe").write_bytes(b"x")
            self.assertEqual(registry.on_an_installation(folder), (registry.PYTHON_CHOICE,))

    def test_the_lines_are_all_that_is_pinned(self):
        self.assertEqual(pythons.LINES, ("3.13", "3.14", "3.15"))
        text = (PACKAGE_DIR / "control" / "pythons.py").read_text(encoding="utf-8")
        import re
        code = "\n".join(line.split("#")[0] for line in text.splitlines())
        self.assertEqual(re.findall(r'"3\.[0-9]+\.[0-9]+"', code), [], "no patch is written in the code")

    def test_only_python_org_is_named(self):
        text = (PACKAGE_DIR / "courier" / "pythonorg.py").read_text(encoding="utf-8")
        import re
        self.assertEqual({url.split("/")[2] for url in re.findall(r"https://[^\s\"]+", text) if "." in url.split("/")[2]},
                         {"www.python.org"})


class PlugTests(unittest.TestCase):
    def test_the_launcher_s_two_questions_reach_it_and_nothing_else_does(self):
        """Fails with the plug's branch reverted: the launcher's question would go to the capabilities at P13."""
        from codex_auto_resume_advanced.plug import AdvancedPlug

        class Stub:
            runtime = type("Runtime", (), {"supervise": staticmethod(lambda facts: "theirs")})()
        with patch.object(pythons, "supervised", return_value="mine") as asked:
            for phase in (pythons.PHASE_RUNTIME, pythons.PHASE_RUNTIME_FAILED):
                self.assertEqual(AdvancedPlug.supervise(Stub, {"phase": phase}), "mine")
            self.assertEqual(asked.call_count, 2)
            self.assertEqual(AdvancedPlug.supervise(Stub, {"phase": "start"}), "theirs")
            self.assertEqual(asked.call_count, 2)

    def test_a_registry_with_it_is_a_good_registry(self):
        made = registry.Registry(registry.DEFINITIONS + (registry.PYTHON_CHOICE,))
        self.assertIs(made.get("python_choice"), registry.PYTHON_CHOICE)
        self.assertEqual(registry.shown(made).count(registry.PYTHON_CHOICE), 1)


class ImportCheckTests(unittest.TestCase):
    """pythoncheck.py, run for real by this interpreter on folders of its own: it is what a new Python is first asked."""

    def run_on(self, files):
        with tempfile.TemporaryDirectory() as folder:
            for name, text in files.items():
                (Path(folder) / name).write_text(text, encoding="utf-8")
            done = subprocess.run([sys.executable, "-I", "-B", "-X", "disable-remote-debug", str(PACKAGE_DIR / "pythoncheck.py"), folder],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=pythons.NO_WINDOW)
            return done.returncode, done.stdout, sorted(path.name for path in Path(folder).iterdir())

    def test_all_imported(self):
        code, _said, left = self.run_on({"first_module_here.py": "import json\n", "second_module_here.py": "VALUE = 1\n"})
        self.assertEqual(code, 0)
        self.assertEqual(left, ["first_module_here.py", "second_module_here.py"], "no bytecode left behind")

    def test_one_that_does_not_import(self):
        code, said, _left = self.run_on({"broken_module_here.py": "import a_module_nobody_has\n"})
        self.assertEqual(code, 1)
        self.assertIn("broken_module_here", said)

    def test_one_that_does_something_by_being_imported(self):
        code, said, _left = self.run_on({"busy_module_here.py": "import subprocess\nsubprocess.Popen(['cmd'])\n"})
        self.assertEqual(code, 1)
        self.assertIn("busy_module_here", said)

    def test_nothing_to_import_is_not_a_pass(self):
        self.assertEqual(self.run_on({"notes.txt": ""})[0], 1)

    def test_it_is_run_isolated_with_no_bytecode_and_no_window(self):
        with patch.object(pythons.subprocess, "run") as ran:
            ran.return_value.returncode = 0
            self.assertTrue(pythons.imports_under(Path("C:/x/python.exe"), None))
        argv, keywords = ran.call_args[0][0], ran.call_args[1]
        self.assertEqual(argv[:5], ["C:\\x\\python.exe", "-I", "-B", "-X", "disable-remote-debug"])
        self.assertEqual(keywords["creationflags"], pythons.NO_WINDOW)
        self.assertEqual(keywords["cwd"], "C:\\x")


if __name__ == "__main__":
    unittest.main()

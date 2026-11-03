"""v0.6.21 (#58): an engine is official by its place or by OpenAI's signature, decided in one function.

The reporter's Codex app ran its codex.exe from its own package under WindowsApps, and the product accepted only
%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hex>\\codex.exe. From this version codex/pairing.py official_engine is the one
rule: the official folder, read as a path and no file, or a valid Authenticode signature whose signer is OpenAI,
read by win/authenticode.py through WinVerifyTrust with no network. Anything else - unsigned, another signer, a file
that no longer matches its signature, an untrusted chain, or anything unreadable - is not official, with a reason,
and never an exception. Windows' calls are stubs here, except in the last class, which needs no Codex.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from codex_auto_resume.codex import pairing, transport
from codex_auto_resume.domain.errors import AdapterError
from codex_auto_resume.win import authenticode

PACKAGE_ENGINE = r"\WindowsApps\OpenAI.Codex_26.1027.3384.0_x64__2p2nqsd0c76g0\app\resources\codex.exe"


class Scratch(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-signature-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.local = self.root / "Local"
        self.bin_engine = self.local / "OpenAI" / "Codex" / "bin" / "0123456789abcdef" / "codex.exe"
        self.bin_engine.parent.mkdir(parents=True)
        self.bin_engine.write_bytes(b"MZ-bin")
        self.signed = self.root / "Program Files" / PACKAGE_ENGINE.lstrip("\\")
        self.signed.parent.mkdir(parents=True)
        self.signed.write_bytes(b"MZ-package")
        stub = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        stub.start()
        self.addCleanup(stub.stop)
        pairing._OFFICIAL.clear()
        self.addCleanup(pairing._OFFICIAL.clear)


class OfficialEngineTests(Scratch):
    def test_the_official_folder_is_official_and_no_signature_is_read_for_it(self):
        with patch.object(authenticode, "signer", side_effect=AssertionError("a signature was read")) as signer:
            self.assertEqual(pairing.official_engine(self.bin_engine), (True, "official_location"))
            self.assertEqual(pairing.official_engine(str(self.bin_engine).upper()), (True, "official_location"))
        signer.assert_not_called()

    def test_an_engine_signed_by_openai_elsewhere_is_official(self):
        with patch.object(authenticode, "signer", return_value=pairing.OPENAI_SIGNER):
            self.assertEqual(pairing.official_engine(self.signed), (True, "openai_signature"))
            self.assertEqual(pairing.official_engine(str(self.signed)), (True, "openai_signature"))

    def test_the_signer_is_compared_exactly(self):
        for name in ("OpenAI OpCo, LLC.", "openai opco, llc", "OpenAI", "Microsoft Windows", ""):
            pairing._OFFICIAL.clear()
            with self.subTest(name=name), patch.object(authenticode, "signer", return_value=name):
                self.assertEqual(pairing.official_engine(self.signed), (False, "wrong_signer"))

    def test_every_refusal_is_not_official_with_its_reason_and_never_raises(self):
        for refusal in ("unsigned", "signature_invalid", "signature_untrusted", "signature_unreadable"):
            pairing._OFFICIAL.clear()
            with self.subTest(refusal), patch.object(authenticode, "signer", side_effect=AdapterError(refusal)):
                self.assertEqual(pairing.official_engine(self.signed), (False, refusal))
        pairing._OFFICIAL.clear()
        with patch.object(authenticode, "signer", side_effect=RuntimeError("boom")):
            self.assertEqual(pairing.official_engine(self.signed), (False, "signature_unreadable"))

    def test_a_path_that_cannot_be_read_is_not_official_and_reads_no_signature(self):
        with patch.object(authenticode, "signer", side_effect=AssertionError("a signature was read")):
            for path in (self.root / "gone" / "codex.exe", self.signed.parent, None, 7, "\0"):
                with self.subTest(path=path):
                    self.assertEqual(pairing.official_engine(path), (False, "engine_unreadable"))

    def test_the_answer_is_kept_by_path_size_and_time_and_read_again_when_they_change(self):
        with patch.object(authenticode, "signer", return_value=pairing.OPENAI_SIGNER) as signer:
            for _ in range(3):
                self.assertTrue(pairing.official_engine(self.signed)[0])
            self.assertEqual(signer.call_count, 1, "the signature is read once, not on every ask")
            found = self.signed.stat()
            os.utime(self.signed, ns=(found.st_atime_ns, found.st_mtime_ns + 1_000_000_000))
            self.assertTrue(pairing.official_engine(self.signed)[0])
            self.assertEqual(signer.call_count, 2)
        with patch.object(authenticode, "signer", side_effect=AdapterError("signature_invalid")):
            self.signed.write_bytes(b"MZ-package-changed")
            self.assertEqual(pairing.official_engine(self.signed), (False, "signature_invalid"))


class EngineCheckTests(Scratch):
    """E1 asks the one rule: a signed engine outside the folder passes it, any other fails it and is never run."""

    def checks(self, path):
        backend = transport.Backend(self.root, path)
        with patch.object(transport.S, "run", return_value=MagicMock(returncode=1, stdout="")) as run:
            return backend.engine_checks(), run

    def test_an_engine_signed_by_openai_passes_the_location_check(self):
        with patch.object(authenticode, "signer", return_value=pairing.OPENAI_SIGNER):
            checks, run = self.checks(self.signed)
        self.assertEqual(checks["official_location"], transport.PASS)
        run.assert_called()

    def test_any_other_engine_outside_the_folder_fails_it_and_is_never_run(self):
        for answer in ({"return_value": "Microsoft Windows"}, {"side_effect": AdapterError("unsigned")},
                       {"side_effect": AdapterError("signature_invalid")}):
            pairing._OFFICIAL.clear()
            with self.subTest(answer=answer), patch.object(authenticode, "signer", **answer):
                checks, run = self.checks(self.signed)
            self.assertEqual(checks["official_location"], transport.FAIL)
            run.assert_not_called()


class FakeTrust:
    """wintrust as `signer` calls it, answering `status` and writing down what it was handed."""

    def __init__(self, status):
        self.status, self.handed = status, []

    def WinVerifyTrust(self, window, action, data):
        trust = data._obj
        self.handed.append((window, trust.dwStateAction, trust.dwUIChoice, trust.fdwRevocationChecks,
                            trust.dwProvFlags, trust.pFile.contents.pcwszFilePath))
        return self.status if trust.dwStateAction == authenticode.WTD_STATEACTION_VERIFY else 0

    def WTHelperProvDataFromStateData(self, state):
        return None


class SignerTests(unittest.TestCase):
    def test_reasons(self):
        self.assertIsNone(authenticode.reason(0))
        cases = {-2146762496: "unsigned", 0x800B0003: "unsigned", 0x80096010: "signature_invalid",
                 0x800B0101: "signature_untrusted", 0x800B0109: "signature_untrusted",
                 0x800B0111: "signature_untrusted", 0x80092003: "signature_unreadable", 1: "signature_untrusted"}
        for status, expected in cases.items():
            with self.subTest(status=hex(status & 0xFFFFFFFF)):
                self.assertEqual(authenticode.reason(status), expected)

    def test_windows_is_asked_with_no_network_no_dialog_and_its_state_closed(self):
        for status, expected in ((0x800B0100, "unsigned"), (0x80096010, "signature_invalid"),
                                 (0x800B0101, "signature_untrusted"), (0, "signature_unreadable")):
            trust = FakeTrust(status)
            with self.subTest(status=hex(status)), patch.object(authenticode, "_api", return_value=(trust, None)):
                with self.assertRaises(AdapterError) as raised:
                    authenticode.signer(r"C:\Engines\codex.exe")
                self.assertEqual(str(raised.exception), expected)
                verify, close = trust.handed
                self.assertEqual(verify[0], None)
                self.assertEqual(verify[1:5], (authenticode.WTD_STATEACTION_VERIFY, authenticode.WTD_UI_NONE,
                                               authenticode.WTD_REVOKE_NONE, authenticode.PROVIDER_FLAGS))
                self.assertEqual(verify[5], r"C:\Engines\codex.exe")
                self.assertEqual(close[1], authenticode.WTD_STATEACTION_CLOSE)
        self.assertEqual(authenticode.WTD_REVOKE_NONE, 0)
        self.assertTrue(authenticode.PROVIDER_FLAGS & 0x1000, "WTD_CACHE_ONLY_URL_RETRIEVAL")
        self.assertTrue(authenticode.PROVIDER_FLAGS & 0x10, "WTD_REVOCATION_CHECK_NONE")

    def test_nothing_but_a_reason_code_ever_leaves_it(self):
        for failure in (OSError("no wintrust"), AttributeError("no function"), C.ArgumentError("bad")):
            with self.subTest(failure=failure), patch.object(authenticode, "_api", side_effect=failure):
                with self.assertRaises(AdapterError) as raised:
                    authenticode.signer(r"C:\Engines\codex.exe")
                self.assertEqual(str(raised.exception), "signature_unreadable")


@unittest.skipUnless(sys.platform == "win32", "WinVerifyTrust is Windows'")
class RealWindowsTests(unittest.TestCase):
    """The real call, on files any Windows has: no Codex and no network needed."""

    def setUp(self):
        pairing._OFFICIAL.clear()
        self.addCleanup(pairing._OFFICIAL.clear)

    def test_an_unsigned_file_is_not_official(self):
        with tempfile.TemporaryDirectory(prefix="car-signature-") as folder:
            path = Path(folder) / "codex.exe"
            path.write_bytes(b"MZ" + bytes(510))
            with self.assertRaises(AdapterError) as raised:
                authenticode.signer(path)
            self.assertEqual(str(raised.exception), "unsigned")
            self.assertEqual(pairing.official_engine(path), (False, "unsigned"))

    def test_a_file_signed_by_someone_else_is_the_wrong_signer(self):
        signed = []
        for path in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe", Path(sys.executable)):
            try:
                signed.append((path, authenticode.signer(path)))
            except AdapterError:
                continue
        if not signed:
            self.skipTest("neither explorer.exe nor this Python carries a signature of its own here")
        for path, name in signed:
            with self.subTest(path=path.name):
                self.assertNotEqual(name, pairing.OPENAI_SIGNER)
                self.assertTrue(name)
                self.assertEqual(pairing.official_engine(path), (False, "wrong_signer"))


if __name__ == "__main__":
    unittest.main()

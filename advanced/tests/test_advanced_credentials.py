"""Where a capability's secret would go: Windows Credential Manager under a name of this
edition's own, and nowhere else. No capability has one, so nothing is stored; the seam is held
with a backend of the test's own, and Windows' is held against a stand-in for advapi32, so no
test reaches the real Credential Manager.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import ast
import ctypes
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume_advanced import credentials  # noqa: E402
from codex_auto_resume_advanced.credentials import (SecretError, Secrets,  # noqa: E402
                                                    WindowsCredentials)
from codex_auto_resume_advanced.state import TABLES  # noqa: E402

PACKAGE = ac.ROOT / "advanced" / "src" / "codex_auto_resume_advanced"


class Kept:
    """A backend that keeps what it is given in memory."""

    def __init__(self):
        self.entries = {}

    def read(self, target):
        return self.entries.get(target)

    def write(self, target, secret):
        self.entries[target] = secret

    def delete(self, target):
        return self.entries.pop(target, None) is not None


class Advapi32:
    """A stand-in for advapi32's three credential calls, called as WindowsCredentials calls them."""

    def __init__(self):
        self.written, self.freed, self.deleted = {}, 0, []

    def CredWriteW(self, pointer, flags):
        credential = pointer._obj
        self.written[credential.TargetName] = (
            credential.Type, credential.Persist, credential.UserName,
            ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize))
        return 1

    def CredReadW(self, target, kind, flags, found):
        if target not in self.written:
            ctypes.set_last_error(credentials.ERROR_NOT_FOUND)
            return 0
        blob = self.written[target][3]
        self._buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        self._credential = credentials._CREDENTIAL(
            Type=kind, TargetName=target, CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(self._buffer, ctypes.POINTER(ctypes.c_ubyte)))
        found._obj.contents = self._credential
        return 1

    def CredFree(self, pointer):
        self.freed += 1

    def CredDeleteW(self, target, kind, flags):
        if self.written.pop(target, None) is None:
            ctypes.set_last_error(credentials.ERROR_NOT_FOUND)
            return 0
        self.deleted.append(target)
        return 1


class SeamTests(ac.AdvancedCase):
    def secrets(self, backend=None):
        return Secrets(ac.Registry((ac.definition(),)), backend or Kept())

    def test_a_secret_is_kept_under_a_name_of_this_editions_own(self):
        kept = Kept()
        secrets = self.secrets(kept)
        secrets.write("test_wake", "token", "s3cret")
        self.assertEqual(kept.entries, {"CodexAutoResume/advanced/test_wake/token": "s3cret"})
        self.assertEqual(secrets.read("test_wake", "token"), "s3cret")
        self.assertTrue(secrets.delete("test_wake", "token"))
        self.assertIsNone(secrets.read("test_wake", "token"))
        self.assertFalse(self.home.exists(), "nothing reached the home")

    def test_only_a_capability_of_the_registry_and_a_plain_name(self):
        secrets = self.secrets()
        for capability, name in (("elsewhere", "token"), ("test_wake", "../x"), ("test_wake", ""),
                                 ("test_wake", "Token"), ("test_wake", None)):
            with self.subTest(capability=capability, name=name):
                with self.assertRaises(SecretError):
                    secrets.target(capability, name)
        for secret in ("", None, "x" * (credentials.MAX_SECRET_BYTES + 1)):
            with self.assertRaises(SecretError):
                secrets.write("test_wake", "token", secret)

    def test_the_windows_backend_writes_a_generic_credential_reads_it_and_frees_it(self):
        advapi32 = Advapi32()
        secrets = self.secrets(WindowsCredentials(advapi32))
        secrets.write("test_wake", "token", "s3crët")
        target = "CodexAutoResume/advanced/test_wake/token"
        self.assertEqual(advapi32.written[target],
                         (credentials.CRED_TYPE_GENERIC, credentials.CRED_PERSIST_LOCAL_MACHINE,
                          "codex-auto-resume", "s3crët".encode("utf-8")))
        self.assertEqual(secrets.read("test_wake", "token"), "s3crët")
        self.assertEqual(advapi32.freed, 1)
        self.assertTrue(secrets.delete("test_wake", "token"))
        self.assertIsNone(secrets.read("test_wake", "token"))
        self.assertFalse(secrets.delete("test_wake", "token"))

    def test_the_windows_backend_touches_no_target_but_this_editions(self):
        backend = WindowsCredentials(Advapi32())
        for target in ("git:https://github.com", "OpenAI/Codex", None):
            with self.assertRaises(SecretError):
                backend.read(target)


class NowhereElseTests(unittest.TestCase):
    def test_only_the_seam_calls_credential_manager(self):
        users = set()
        for path in sorted(PACKAGE.rglob("*.py")):
            names = {getattr(node, "attr", None) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))}
            if names & {"CredWriteW", "CredReadW", "CredDeleteW"}:
                users.add(path.name)
        self.assertEqual(users, {"credentials.py"})

    def test_the_state_has_no_column_a_secret_could_be_kept_in(self):
        columns = {column for names in TABLES.values() for column in names}
        for word in ("secret", "token", "password", "credential", "key", "auth", "text", "message"):
            with self.subTest(word):
                self.assertFalse([column for column in columns if word in column])

    def test_nothing_calls_the_seam_yet(self):
        """No capability has a secret: nothing outside the seam and its tests names it."""
        for path in sorted(PACKAGE.rglob("*.py")):
            if path.name == "credentials.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                        for alias in node.names} | {node.module for node in ast.walk(tree)
                                                    if isinstance(node, ast.ImportFrom) and node.module}
            self.assertNotIn("credentials", imported, path.name)
            self.assertNotIn("Secrets", imported, path.name)


if __name__ == "__main__":
    unittest.main()

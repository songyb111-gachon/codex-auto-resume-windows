# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Where a capability's secret would go: Windows Credential Manager, and nowhere else.

No capability has one yet, and nothing here is called, so nothing is stored. This is the seam a
capability that needs one will use, fixed now so that the rule is fixed with it: a secret never
touches advanced.sqlite, a settings file, a log or the journal, and it is never read from
Codex's own credentials either (standard B11) - only from an entry this edition wrote, under a
name of its own:

    CodexAutoResume/advanced/<capability id>/<name>

`Secrets` checks the capability and the name and builds that target; a backend does the
storing. The default backend is Windows' (CredReadW, CredWriteW and CredDeleteW, generic
credentials persisted for this user on this machine); a test hands in its own, so no test ever
reaches the real Credential Manager.
"""
from __future__ import annotations

import ctypes
import re

TARGET_PREFIX = "CodexAutoResume/advanced/"
NAME_SHAPE = re.compile(r"[a-z][a-z0-9_]{0,31}")
MAX_SECRET_BYTES = 2560          # CRED_MAX_CREDENTIAL_BLOB_SIZE: 5 * 512 bytes


class SecretError(RuntimeError):
    """A secret that could not be named, read, written or deleted. Never says what it was."""


class Secrets:
    def __init__(self, registry, backend=None):
        self.registry = registry
        self._backend = backend

    @property
    def backend(self):
        if self._backend is None:
            self._backend = WindowsCredentials()
        return self._backend

    def target(self, capability, name) -> str:
        """The one name a capability's secret is kept under."""
        if self.registry.get(capability) is None:
            raise SecretError("unknown capability")
        if not isinstance(name, str) or not NAME_SHAPE.fullmatch(name):
            raise SecretError("invalid secret name")
        return TARGET_PREFIX + capability + "/" + name

    def read(self, capability, name) -> str | None:
        return self.backend.read(self.target(capability, name))

    def write(self, capability, name, secret) -> None:
        if not isinstance(secret, str) or not secret or len(secret.encode("utf-8")) > MAX_SECRET_BYTES:
            raise SecretError("invalid secret")
        self.backend.write(self.target(capability, name), secret)

    def delete(self, capability, name) -> bool:
        return self.backend.delete(self.target(capability, name))


# ------------------------------------------------------------------------------ Windows
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
                ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
                ("LastWritten", _FILETIME), ("CredentialBlobSize", ctypes.c_uint32),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", ctypes.c_uint32),
                ("AttributeCount", ctypes.c_uint32), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p), ("UserName", ctypes.c_wchar_p)]


class WindowsCredentials:
    """Generic credentials of the signed-in user, under targets `Secrets` built."""

    def __init__(self, library=None):
        self._library = library

    def _advapi32(self):
        if self._library is None:
            self._library = ctypes.WinDLL("advapi32", use_last_error=True)
        return self._library

    @staticmethod
    def _ours(target) -> str:
        if not isinstance(target, str) or not target.startswith(TARGET_PREFIX):
            raise SecretError("not a target of this edition")
        return target

    def read(self, target) -> str | None:
        found = ctypes.POINTER(_CREDENTIAL)()
        library = self._advapi32()
        if not library.CredReadW(self._ours(target), CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise SecretError("the secret could not be read")
        try:
            credential = found.contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        finally:
            library.CredFree(found)
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            raise SecretError("the secret could not be read") from None

    def write(self, target, secret) -> None:
        data = secret.encode("utf-8")
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        credential = _CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=self._ours(target),
                                 CredentialBlobSize=len(data),
                                 CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
                                 Persist=CRED_PERSIST_LOCAL_MACHINE, UserName="codex-auto-resume")
        if not self._advapi32().CredWriteW(ctypes.byref(credential), 0):
            raise SecretError("the secret could not be written")

    def delete(self, target) -> bool:
        if self._advapi32().CredDeleteW(self._ours(target), CRED_TYPE_GENERIC, 0):
            return True
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return False
        raise SecretError("the secret could not be deleted")

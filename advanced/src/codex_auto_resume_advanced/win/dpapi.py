# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Windows' data protection for the current user (account_auto_switch, v0.6.22): CryptProtectData and
CryptUnprotectData with no prompt, no machine scope and a fixed entropy label, so a blob made here opens only for this
Windows user - on another PC only where that user's profile roams with its keys (a domain's roaming profile) - and only
for this product's label; anyone who runs as this user can open it. What it protects is a saved Codex sign-in file
(profiles.py); nothing else in the edition uses it.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# The label every blob is made with: a blob made by another program for the same user does not open with it.
ENTROPY = b"codex-auto-resume/account_auto_switch/1"
_UI_FORBIDDEN = 0x01


class DpapiError(OSError):
    """Windows refused to protect or open a blob: another user's, another label's, or damaged."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buffer = ctypes.create_string_buffer(bytes(data), len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call(name, data) -> bytes:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("bytes")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = getattr(crypt32, name)
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    given, _keep = _blob(data)
    entropy, _keep_entropy = _blob(ENTROPY)
    out = _Blob()
    if not function(ctypes.byref(given), None, ctypes.byref(entropy), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
        raise DpapiError(ctypes.get_last_error(), "%s refused" % name)
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data) -> bytes:
    """`data` sealed for this Windows user and this product's label."""
    return _call("CryptProtectData", data)


def unprotect(blob) -> bytes:
    """What `protect` sealed; DpapiError for anything else."""
    return _call("CryptUnprotectData", blob)

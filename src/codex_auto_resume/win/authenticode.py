"""Who signed a file, as Windows judges its Authenticode signature (v0.6.21, issue #58).

The Codex app can run its engine from its own package rather than from the official folder, and
where it does, the engine is known by its signature instead of its place (codex/pairing.py,
official_engine). WinVerifyTrust is asked the one content-free question: is the signature this file
carries valid, does its chain end in a root this PC trusts, and whose certificate signed it. Nothing
reaches the network: revocation is not checked (WTD_REVOKE_NONE, WTD_REVOCATION_CHECK_NONE) and any
certificate the chain needs comes only from this PC's own caches (WTD_CACHE_ONLY_URL_RETRIEVAL). No
dialog is shown (WTD_UI_NONE), no process is started, and the file is only read.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

from ..domain.errors import AdapterError
from .dll import GUID

WTD_UI_NONE = 2
WTD_REVOKE_NONE = 0
WTD_CHOICE_FILE = 1
WTD_STATEACTION_VERIFY = 1
WTD_STATEACTION_CLOSE = 2
WTD_REVOCATION_CHECK_NONE = 0x10
WTD_CACHE_ONLY_URL_RETRIEVAL = 0x1000
WTD_DISABLE_MD2_MD4 = 0x2000
PROVIDER_FLAGS = WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_DISABLE_MD2_MD4
CERT_NAME_ATTR_TYPE = 3
COMMON_NAME = b"2.5.4.3"

# What WinVerifyTrust answers, by the reason code the product keeps: no signature at all, a signature
# whose digest no longer matches the file (tampered), and a file it could not read. Any other refusal -
# an expired, distrusted or untrusted chain - is `signature_untrusted`.
UNSIGNED = frozenset({0x800B0100, 0x800B0003, 0x800B0001})   # TRUST_E_NOSIGNATURE, _SUBJECT_FORM_UNKNOWN, _PROVIDER_UNKNOWN
TAMPERED = frozenset({0x80096010, 0x80096011})               # TRUST_E_BAD_DIGEST, TRUST_E_NO_SIGNER_CERT
UNREADABLE = frozenset({0x80092003, 0x80070002, 0x80070005, 0x80070020})  # CRYPT_E_FILE_ERROR, not found, denied, in use


def _verify_v2():
    return GUID(0x00AAC56B, 0xCD44, 0x11D0, (C.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))


class _FileInfo(C.Structure):
    _fields_ = [("cbStruct", W.DWORD), ("pcwszFilePath", W.LPCWSTR), ("hFile", W.HANDLE),
                ("pgKnownSubject", C.c_void_p)]


class _TrustData(C.Structure):
    _fields_ = [("cbStruct", W.DWORD), ("pPolicyCallbackData", C.c_void_p), ("pSIPClientData", C.c_void_p),
                ("dwUIChoice", W.DWORD), ("fdwRevocationChecks", W.DWORD), ("dwUnionChoice", W.DWORD),
                ("pFile", C.POINTER(_FileInfo)), ("dwStateAction", W.DWORD), ("hWVTStateData", W.HANDLE),
                ("pwszURLReference", W.LPWSTR), ("dwProvFlags", W.DWORD), ("dwUIContext", W.DWORD),
                ("pSignatureSettings", C.c_void_p)]


class _ProviderCert(C.Structure):
    # CRYPT_PROVIDER_CERT's first two members, the only ones read.
    _fields_ = [("cbStruct", W.DWORD), ("pCert", C.c_void_p)]


def _api():
    trust = C.WinDLL("wintrust", use_last_error=True)
    trust.WinVerifyTrust.argtypes = [W.HWND, C.POINTER(GUID), C.c_void_p]
    trust.WinVerifyTrust.restype = C.c_long
    trust.WTHelperProvDataFromStateData.argtypes = [W.HANDLE]
    trust.WTHelperProvDataFromStateData.restype = C.c_void_p
    trust.WTHelperGetProvSignerFromChain.argtypes = [C.c_void_p, W.DWORD, W.BOOL, W.DWORD]
    trust.WTHelperGetProvSignerFromChain.restype = C.c_void_p
    trust.WTHelperGetProvCertFromChain.argtypes = [C.c_void_p, W.DWORD]
    trust.WTHelperGetProvCertFromChain.restype = C.POINTER(_ProviderCert)
    crypt = C.WinDLL("crypt32", use_last_error=True)
    crypt.CertGetNameStringW.argtypes = [C.c_void_p, W.DWORD, W.DWORD, C.c_void_p, W.LPWSTR, W.DWORD]
    crypt.CertGetNameStringW.restype = W.DWORD
    return trust, crypt


def reason(status) -> str | None:
    """The reason code for WinVerifyTrust's answer `status`; None for a valid, trusted signature."""
    status &= 0xFFFFFFFF
    if status == 0:
        return None
    if status in UNSIGNED:
        return "unsigned"
    if status in TAMPERED:
        return "signature_invalid"
    if status in UNREADABLE:
        return "signature_unreadable"
    return "signature_untrusted"


def _common_name(trust, crypt, state) -> str:
    provider = trust.WTHelperProvDataFromStateData(state)
    signer = trust.WTHelperGetProvSignerFromChain(provider, 0, False, 0) if provider else None
    cert = trust.WTHelperGetProvCertFromChain(signer, 0) if signer else None
    if not cert or not cert.contents.pCert:
        raise AdapterError("signature_unreadable")
    name = C.create_unicode_buffer(256)
    if crypt.CertGetNameStringW(cert.contents.pCert, CERT_NAME_ATTR_TYPE, 0, C.c_char_p(COMMON_NAME),
                                name, len(name)) <= 1:
        raise AdapterError("signature_unreadable")
    return name.value


def signer(path) -> str:
    """The subject common name of the certificate that signed the file at `path`, where Windows finds
    the signature it carries valid and its chain trusted - read with no network and no dialog.

    Raises AdapterError with a reason code, never anything else: `unsigned`, `signature_invalid` (the
    file no longer matches its signature), `signature_untrusted` (expired, distrusted or untrusted) or
    `signature_unreadable` (the file, the API or the certificate could not be read)."""
    try:
        trust, crypt = _api()
        info = _FileInfo(C.sizeof(_FileInfo), str(path), None, None)
        data = _TrustData(cbStruct=C.sizeof(_TrustData), dwUIChoice=WTD_UI_NONE,
                          fdwRevocationChecks=WTD_REVOKE_NONE, dwUnionChoice=WTD_CHOICE_FILE,
                          pFile=C.pointer(info), dwStateAction=WTD_STATEACTION_VERIFY,
                          dwProvFlags=PROVIDER_FLAGS)
        action = _verify_v2()
        status = trust.WinVerifyTrust(None, C.byref(action), C.byref(data))
        try:
            refused = reason(status)
            if refused:
                raise AdapterError(refused)
            return _common_name(trust, crypt, data.hWVTStateData)
        finally:
            data.dwStateAction = WTD_STATEACTION_CLOSE
            trust.WinVerifyTrust(None, C.byref(action), C.byref(data))
    except AdapterError:
        raise
    except Exception:
        raise AdapterError("signature_unreadable") from None

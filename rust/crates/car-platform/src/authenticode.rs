//! Who signed a file, as Windows judges its Authenticode signature (`win/authenticode.py`, issue #58).
//!
//! The Codex app can run its engine from its own package rather than from the official folder, and where it does,
//! the engine is known by its signature instead of its place. `WinVerifyTrust` is asked the one content-free
//! question: is the signature this file carries valid, does its chain end in a root this PC trusts, and whose
//! certificate signed it. Nothing reaches the network: revocation is not checked and any certificate the chain needs
//! comes only from this PC's own caches. No dialog is shown (`WTD_UI_NONE`), no process is started, the file is only
//! read.

use windows::Win32::Foundation::{HANDLE, HWND};
use windows::Win32::Security::Cryptography::{CERT_NAME_ATTR_TYPE, CertGetNameStringW};
use windows::Win32::Security::WinTrust::{
    CRYPT_PROVIDER_DATA, CRYPT_PROVIDER_SGNR, WINTRUST_ACTION_GENERIC_VERIFY_V2, WINTRUST_DATA,
    WINTRUST_DATA_0, WINTRUST_DATA_PROVIDER_FLAGS, WINTRUST_FILE_INFO, WTD_CHOICE_FILE,
    WTD_REVOKE_NONE, WTD_STATEACTION_CLOSE, WTD_STATEACTION_VERIFY, WTD_UI_NONE,
    WTHelperGetProvCertFromChain, WinVerifyTrust,
};
use windows::core::PCWSTR;

use crate::paths::{from_wide, wide_os};
use crate::seams::AdapterError;

// Two helpers of wintrust.dll the `windows` crate carries no declaration for (its metadata lists the others of the
// family, these two not): declared here, the only raw declarations of the crate.
#[link(name = "wintrust")]
unsafe extern "system" {
    fn WTHelperProvDataFromStateData(hstatedata: HANDLE) -> *mut CRYPT_PROVIDER_DATA;
    fn WTHelperGetProvSignerFromChain(
        pprovdata: *mut CRYPT_PROVIDER_DATA,
        idxsigner: u32,
        fcountersigner: i32,
        idxcountersigner: u32,
    ) -> *mut CRYPT_PROVIDER_SGNR;
}

const WTD_REVOCATION_CHECK_NONE: u32 = 0x10;
const WTD_CACHE_ONLY_URL_RETRIEVAL: u32 = 0x1000;
const WTD_DISABLE_MD2_MD4: u32 = 0x2000;
pub const PROVIDER_FLAGS: u32 =
    WTD_REVOCATION_CHECK_NONE | WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_DISABLE_MD2_MD4;
const COMMON_NAME: &[u8] = b"2.5.4.3\0";

// What WinVerifyTrust answers, by the reason code the product keeps.
/// TRUST_E_NOSIGNATURE, _SUBJECT_FORM_UNKNOWN, _PROVIDER_UNKNOWN.
pub const UNSIGNED: [u32; 3] = [0x800B0100, 0x800B0003, 0x800B0001];
/// TRUST_E_BAD_DIGEST, TRUST_E_NO_SIGNER_CERT.
pub const TAMPERED: [u32; 2] = [0x80096010, 0x80096011];
/// CRYPT_E_FILE_ERROR, not found, denied, in use.
pub const UNREADABLE: [u32; 4] = [0x80092003, 0x80070002, 0x80070005, 0x80070020];

/// The reason code for WinVerifyTrust's answer `status`; None for a valid, trusted signature.
pub fn reason(status: i64) -> Option<&'static str> {
    let status = (status & 0xFFFF_FFFF) as u32;
    if status == 0 {
        None
    } else if UNSIGNED.contains(&status) {
        Some("unsigned")
    } else if TAMPERED.contains(&status) {
        Some("signature_invalid")
    } else if UNREADABLE.contains(&status) {
        Some("signature_unreadable")
    } else {
        Some("signature_untrusted")
    }
}

fn common_name(state: HANDLE) -> Result<String, AdapterError> {
    let unreadable = AdapterError("signature_unreadable");
    // SAFETY: the state WinVerifyTrust just produced, not yet closed.
    let provider = unsafe { WTHelperProvDataFromStateData(state) };
    if provider.is_null() {
        return Err(unreadable);
    }
    // SAFETY: a provider data pointer from the call above.
    let signer = unsafe { WTHelperGetProvSignerFromChain(provider, 0, 0, 0) };
    if signer.is_null() {
        return Err(unreadable);
    }
    // SAFETY: a signer pointer from the call above.
    let cert = unsafe { WTHelperGetProvCertFromChain(signer, 0) };
    // SAFETY: a CRYPT_PROVIDER_CERT or null.
    if cert.is_null() || unsafe { (*cert).pCert.is_null() } {
        return Err(unreadable);
    }
    let mut name = vec![0u16; 256];
    // SAFETY: the certificate context is alive until the state is closed; the buffer is ours.
    let length = unsafe {
        CertGetNameStringW(
            (*cert).pCert,
            CERT_NAME_ATTR_TYPE,
            0,
            Some(COMMON_NAME.as_ptr() as *const _),
            Some(&mut name),
        )
    };
    if length <= 1 {
        return Err(unreadable);
    }
    Ok(from_wide(&name))
}

/// The subject common name of the certificate that signed the file at `path`, where Windows finds the signature it
/// carries valid and its chain trusted - read with no network and no dialog.
///
/// Errors with a reason code, never anything else: `unsigned`, `signature_invalid` (the file no longer matches its
/// signature), `signature_untrusted` (expired, distrusted or untrusted) or `signature_unreadable` (the file, the API
/// or the certificate could not be read).
pub fn signer(path: &std::path::Path) -> Result<String, AdapterError> {
    let file = wide_os(path.as_os_str());
    let mut info = WINTRUST_FILE_INFO {
        cbStruct: std::mem::size_of::<WINTRUST_FILE_INFO>() as u32,
        pcwszFilePath: PCWSTR(file.as_ptr()),
        ..Default::default()
    };
    let mut data = WINTRUST_DATA {
        cbStruct: std::mem::size_of::<WINTRUST_DATA>() as u32,
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_FILE,
        Anonymous: WINTRUST_DATA_0 { pFile: &mut info },
        dwStateAction: WTD_STATEACTION_VERIFY,
        dwProvFlags: WINTRUST_DATA_PROVIDER_FLAGS(PROVIDER_FLAGS),
        ..Default::default()
    };
    let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    // SAFETY: structures of our own; the state is closed below whatever happens.
    let status =
        unsafe { WinVerifyTrust(HWND::default(), &mut action, &mut data as *mut _ as *mut _) };
    let outcome = match reason(i64::from(status)) {
        Some(refused) => Err(AdapterError(refused)),
        None => common_name(data.hWVTStateData),
    };
    data.dwStateAction = WTD_STATEACTION_CLOSE;
    // SAFETY: closes the state the verify call made.
    unsafe {
        WinVerifyTrust(HWND::default(), &mut action, &mut data as *mut _ as *mut _);
    }
    outcome
}

//! Windows' data protection for the current user (seat S7.2a; the advanced edition's `win/dpapi.py`):
//! `CryptProtectData` and `CryptUnprotectData` with no prompt (`CRYPTPROTECT_UI_FORBIDDEN`), no machine scope and the
//! caller's entropy label, so a blob made here opens only for this Windows user and only with that label.
//!
//! The label is the caller's (the advanced edition's `ENTROPY`): this crate names nothing of that edition. No test reads
//! a blob anyone else made: the one test seals random bytes it made itself, in memory, and opens them again.

use windows::Win32::Foundation::{HLOCAL, LocalFree};
use windows::Win32::Security::Cryptography::{
    CRYPT_INTEGER_BLOB, CRYPTPROTECT_UI_FORBIDDEN, CryptProtectData, CryptUnprotectData,
};
use windows::core::PCWSTR;

/// Windows refused to protect or open a blob (`DpapiError(winerror, "<name> refused")`, an OSError): another user's,
/// another label's, or damaged. `code` is the Windows error, `name` the call.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DpapiError {
    pub code: u32,
    pub name: &'static str,
}

impl std::fmt::Display for DpapiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[WinError {}] {} refused", self.code, self.name)
    }
}

impl std::error::Error for DpapiError {}

fn blob(data: &[u8]) -> CRYPT_INTEGER_BLOB {
    CRYPT_INTEGER_BLOB {
        cbData: data.len() as u32,
        pbData: data.as_ptr().cast_mut(),
    }
}

fn taken(out: CRYPT_INTEGER_BLOB) -> Vec<u8> {
    if out.pbData.is_null() {
        return Vec::new();
    }
    // SAFETY: Windows handed back `cbData` bytes at `pbData`, allocated with LocalAlloc; copied, then freed once.
    let data = unsafe { std::slice::from_raw_parts(out.pbData, out.cbData as usize) }.to_vec();
    // SAFETY: `pbData` is the LocalAlloc'd buffer of this call's answer, freed once here and never read again.
    unsafe {
        let _ = LocalFree(Some(HLOCAL(out.pbData.cast())));
    }
    data
}

fn refused(error: &windows::core::Error, name: &'static str) -> DpapiError {
    // An HRESULT made from a Win32 error (0x8007xxxx) carries it in its low word, as ctypes.get_last_error() gives it.
    let code = error.code().0 as u32;
    let code = if code & 0xFFFF_0000 == 0x8007_0000 {
        code & 0xFFFF
    } else {
        code
    };
    DpapiError { code, name }
}

/// `protect(data)`: `data` sealed for this Windows user and the label `entropy`.
pub fn protect(data: &[u8], entropy: &[u8]) -> Result<Vec<u8>, DpapiError> {
    let given = blob(data);
    let label = blob(entropy);
    let mut out = CRYPT_INTEGER_BLOB::default();
    // SAFETY: every blob points at a live slice for the whole call; the answer is freed in `taken`.
    let done = unsafe {
        CryptProtectData(
            &given,
            PCWSTR::null(),
            Some(&label),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out,
        )
    };
    match done {
        Ok(()) => Ok(taken(out)),
        Err(error) => Err(refused(&error, "CryptProtectData")),
    }
}

/// `unprotect(blob)`: what `protect` sealed with the label `entropy`; DpapiError for anything else.
pub fn unprotect(sealed: &[u8], entropy: &[u8]) -> Result<Vec<u8>, DpapiError> {
    let given = blob(sealed);
    let label = blob(entropy);
    let mut out = CRYPT_INTEGER_BLOB::default();
    // SAFETY: as in `protect`; no description is asked back.
    let done = unsafe {
        CryptUnprotectData(
            &given,
            None,
            Some(&label),
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            &mut out,
        )
    };
    match done {
        Ok(()) => Ok(taken(out)),
        Err(error) => Err(refused(&error, "CryptUnprotectData")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// P7-DESIGN 4: the one round trip a seat may make - random bytes of the test's own, in memory, no file.
    #[test]
    fn random_bytes_sealed_in_memory_open_with_their_label_alone() {
        let data = crate::random::bytes(48).expect("random");
        let label = b"car-platform/dpapi/test";
        let sealed = protect(&data, label).expect("protect");
        assert_ne!(sealed, data);
        assert_eq!(unprotect(&sealed, label).expect("unprotect"), data);
        let wrong = unprotect(&sealed, b"another label").expect_err("another label");
        assert_eq!(wrong.name, "CryptUnprotectData");
        assert!(unprotect(b"not a blob", label).is_err());
        assert_eq!(
            protect(b"", label).map(|sealed| unprotect(&sealed, label)),
            Ok(Ok(Vec::new()))
        );
    }
}

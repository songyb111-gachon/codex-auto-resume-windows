//! `win/dpapi.py` (seat S7.2a): Windows' data protection for the current user, with this product's label, so a blob
//! made here opens only for this Windows user and only for this label. What it protects is a saved Codex sign-in file
//! (`profiles`, through `state::seam::accounts::Host`, which S7.2b fills); nothing else in the edition uses it. The calls
//! are car-platform's (`car_platform::dpapi`, D3).

pub use car_platform::dpapi::DpapiError;

/// `ENTROPY`: the label every blob is made with; a blob made by another program for the same user does not open with it.
pub const ENTROPY: &[u8] = b"codex-auto-resume/account_auto_switch/1";

/// `protect(data)`: `data` sealed for this Windows user and this product's label.
pub fn protect(data: &[u8]) -> Result<Vec<u8>, DpapiError> {
    car_platform::dpapi::protect(data, ENTROPY)
}

/// `unprotect(blob)`: what `protect` sealed; DpapiError for anything else.
pub fn unprotect(blob: &[u8]) -> Result<Vec<u8>, DpapiError> {
    car_platform::dpapi::unprotect(blob, ENTROPY)
}

//! `os.replace` and `os.rename` as CPython makes them on Windows: `MoveFileExW`, and nothing more (review 5, S2).
//!
//! `std::fs::rename` retries MoveFileExW's ERROR_ACCESS_DENIED with a POSIX-semantics `FileRenameInfoEx` rename,
//! which replaces a target another handle holds open with FILE_SHARE_DELETE; Python stops with PermissionError 5 (the
//! settings save then answers "cannot save settings"). These are the product's: car-codex calls them, and the binaries
//! hand them to car-policy (`settings::os::Os::replace`) and car-config (`Logbook::with_rename`), which cannot reach
//! this crate (PLAN 1.3); car-machine's `pyfile::{replace, rename}` are the std-only defaults where nothing is handed in.

use std::path::Path;

use windows::Win32::Storage::FileSystem::{
    MOVE_FILE_FLAGS, MOVEFILE_REPLACE_EXISTING, MoveFileExW,
};
use windows::core::PCWSTR;

use crate::paths::wide_os;

fn move_file(from: &Path, to: &Path, flags: MOVE_FILE_FLAGS) -> std::io::Result<()> {
    let (from, to) = (wide_os(from.as_os_str()), wide_os(to.as_os_str()));
    // SAFETY: both names are NUL-terminated and outlive the call.
    unsafe { MoveFileExW(PCWSTR(from.as_ptr()), PCWSTR(to.as_ptr()), flags) }
        .map_err(|error| std::io::Error::from_raw_os_error(error.code().0 & 0xFFFF))
}

/// `os.replace(from, to)`: MoveFileExW(MOVEFILE_REPLACE_EXISTING) alone - a target another handle holds open is not
/// replaced (PermissionError 5), whatever that handle shares.
pub fn replace(from: &Path, to: &Path) -> std::io::Result<()> {
    move_file(from, to, MOVEFILE_REPLACE_EXISTING)
}

/// `os.rename(from, to)`: MoveFileExW with no flag - an existing target is not replaced (FileExistsError 183).
pub fn rename(from: &Path, to: &Path) -> std::io::Result<()> {
    move_file(from, to, MOVE_FILE_FLAGS(0))
}

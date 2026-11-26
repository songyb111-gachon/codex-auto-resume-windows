//! `os.replace` and `os.rename` as CPython makes them on Windows: `MoveFileExW`, and nothing more (review 5, S2).
//!
//! `std::fs::rename` retries MoveFileExW's ERROR_ACCESS_DENIED with a POSIX-semantics `FileRenameInfoEx` rename,
//! which replaces a target another handle holds open with FILE_SHARE_DELETE; Python stops with PermissionError 5 (the
//! settings save then answers "cannot save settings"). These are the product's: car-codex calls them, and the binaries
//! hand them to car-policy (`settings::os::Os::replace`) and car-config (`Logbook::with_rename`), which cannot reach
//! this crate (PLAN 1.3); car-machine's `pyfile::{replace, rename}` are the std-only defaults where nothing is handed in.
//! `file_index` is `os.stat(path).st_ino`, which std's stable surface cannot read (car-control's `SystemHost::file_id`).

use std::path::Path;

use windows::Win32::Foundation::CloseHandle;
use windows::Win32::Storage::FileSystem::{
    BY_HANDLE_FILE_INFORMATION, CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAGS_AND_ATTRIBUTES,
    FILE_READ_ATTRIBUTES, FILE_SHARE_DELETE, FILE_SHARE_READ, FILE_SHARE_WRITE,
    GetFileInformationByHandle, MOVE_FILE_FLAGS, MOVEFILE_REPLACE_EXISTING, MoveFileExW,
    OPEN_EXISTING,
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

/// `os.stat(path).st_ino`: the file index of what `path` names (links followed, as `stat` follows them),
/// `nFileIndexHigh << 32 | nFileIndexLow` - read the way `homelock::folder_identity` reads a folder's (CreateFileW for
/// FILE_READ_ATTRIBUTES with every share, GetFileInformationByHandle). A new file is a new index, even where NTFS
/// tunnelling hands it the old file's creation time. None where Windows will not say (no such file, no access).
pub fn file_index(path: &Path) -> Option<u128> {
    file_identity(path).map(|(_, index)| u128::from(index))
}

/// `(os.stat(path).st_dev, os.stat(path).st_ino)` as `os.path.samefile` compares them (store/ledger.py `_same_file`):
/// the volume's serial number and the file index, links followed. None where `stat` would raise OSError.
pub fn file_identity(path: &Path) -> Option<(u32, u64)> {
    let name = wide_os(path.as_os_str());
    // SAFETY: `name` is NUL-terminated and outlives the call.
    let handle = unsafe {
        CreateFileW(
            PCWSTR(name.as_ptr()),
            FILE_READ_ATTRIBUTES.0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAGS_AND_ATTRIBUTES(FILE_FLAG_BACKUP_SEMANTICS.0),
            None,
        )
    }
    .ok()?;
    let mut found = BY_HANDLE_FILE_INFORMATION::default();
    // SAFETY: the handle is ours and the structure too.
    let asked = unsafe { GetFileInformationByHandle(handle, &mut found) };
    // SAFETY: the handle was just opened.
    unsafe {
        let _ = CloseHandle(handle);
    }
    asked.ok()?;
    Some((
        found.dwVolumeSerialNumber,
        (u64::from(found.nFileIndexHigh) << 32) | u64::from(found.nFileIndexLow),
    ))
}

//! `Path.is_symlink()` as the bundled Python reads it on Windows: the one link probe of the core (D3).
//!
//! A link is a reparse point whose tag is `IO_REPARSE_TAG_SYMLINK`, and nothing else. A junction
//! (`IO_REPARSE_TAG_MOUNT_POINT`) - a moved profile, a folder linked elsewhere - is a folder to Python 3.12 and later,
//! and so to the core wherever the reference asks `is_symlink()`: car-store's "State paths must not be symbolic links"
//! and car-config's `Paths.ensure()`, `claim_home()`, `owns_home()` and the Codex folders. Rust's
//! `FileType::is_symlink()` counts every name-surrogate tag, junctions included, and std gives no reparse tag, so
//! the tag is read the way CPython's `os.lstat` reads it (`win32_xstat_slow_impl`): `CreateFileW` with
//! `FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS` and `GetFileInformationByHandleEx(FileAttributeTagInfo)`,
//! falling back to `FindFirstFileW` where the file cannot be opened (access denied, a sharing violation).
//!
//! What the reference's `config.is_link` asks - any reparse point at all - is a different question and is car-config's
//! own (`paths::is_link`, attributes only); it needs no tag.
//!
//! car-store and car-config do not depend on this crate (PLAN 1.3): each defines the trait it takes (`Links`), and the
//! harness and the entry points implement both over [`is_symlink`].

use std::path::Path;

use windows::Win32::Foundation::{
    CloseHandle, ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION, HANDLE,
};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FILE_ATTRIBUTE_REPARSE_POINT, FILE_ATTRIBUTE_TAG_INFO, FILE_FLAG_BACKUP_SEMANTICS,
    FILE_FLAG_OPEN_REPARSE_POINT, FILE_FLAGS_AND_ATTRIBUTES, FILE_READ_ATTRIBUTES,
    FILE_SHARE_DELETE, FILE_SHARE_READ, FILE_SHARE_WRITE, FileAttributeTagInfo, FindClose,
    FindFirstFileW, GetFileInformationByHandleEx, OPEN_EXISTING, WIN32_FIND_DATAW,
};
use windows::core::{HRESULT, PCWSTR};

use crate::paths::wide_os;

/// `IO_REPARSE_TAG_SYMLINK`.
pub const SYMLINK_TAG: u32 = 0xA000_000C;
/// `IO_REPARSE_TAG_MOUNT_POINT`: a junction.
pub const MOUNT_POINT_TAG: u32 = 0xA000_0003;

/// Whether Python's `Path(path).is_symlink()` is true: false for a path that cannot be looked at, for a junction and
/// for any other reparse point that is not a symbolic link.
pub fn is_symlink(path: &Path) -> bool {
    reparse_tag(path) == Some(SYMLINK_TAG)
}

/// The reparse tag of `path` itself, not followed; None for no reparse point or a path that cannot be looked at.
pub fn reparse_tag(path: &Path) -> Option<u32> {
    use std::os::windows::fs::MetadataExt;
    // A path that is no reparse point needs no call: the attributes std reads say so.
    let attributes = std::fs::symlink_metadata(path).ok()?.file_attributes();
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT.0 == 0 {
        return None;
    }
    let name = wide_os(path.as_os_str());
    // SAFETY: `name` is NUL-terminated and outlives the call; the handle is closed below.
    let opened = unsafe {
        CreateFileW(
            PCWSTR(name.as_ptr()),
            FILE_READ_ATTRIBUTES.0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAGS_AND_ATTRIBUTES(
                FILE_FLAG_OPEN_REPARSE_POINT.0 | FILE_FLAG_BACKUP_SEMANTICS.0,
            ),
            None,
        )
    };
    let handle: HANDLE = match opened {
        Ok(handle) => handle,
        Err(error) => {
            let denied = HRESULT::from_win32(ERROR_ACCESS_DENIED.0);
            let busy = HRESULT::from_win32(ERROR_SHARING_VIOLATION.0);
            if error.code() != denied && error.code() != busy {
                return None;
            }
            return found_tag(&name);
        }
    };
    let mut information = FILE_ATTRIBUTE_TAG_INFO::default();
    // SAFETY: `handle` is open and `information` is a FILE_ATTRIBUTE_TAG_INFO of the size given.
    let read = unsafe {
        GetFileInformationByHandleEx(
            handle,
            FileAttributeTagInfo,
            (&mut information as *mut FILE_ATTRIBUTE_TAG_INFO).cast(),
            std::mem::size_of::<FILE_ATTRIBUTE_TAG_INFO>() as u32,
        )
    };
    // SAFETY: the handle was just opened.
    unsafe {
        let _ = CloseHandle(handle);
    }
    (read.is_ok() && information.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT.0 != 0)
        .then_some(information.ReparseTag)
}

/// The tag a directory listing gives (`WIN32_FIND_DATAW.dwReserved0`), for a file that cannot be opened.
fn found_tag(name: &[u16]) -> Option<u32> {
    let mut data = WIN32_FIND_DATAW::default();
    // SAFETY: `name` is NUL-terminated; `data` is a writable WIN32_FIND_DATAW; the search handle is closed below.
    let search = unsafe { FindFirstFileW(PCWSTR(name.as_ptr()), &mut data) }.ok()?;
    // SAFETY: FindFirstFileW gave `search`.
    unsafe {
        let _ = FindClose(search);
    }
    (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT.0 != 0).then_some(data.dwReserved0)
}

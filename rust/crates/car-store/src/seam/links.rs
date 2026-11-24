//! `Path.is_symlink()` as the bundled Python reads it on Windows: a link is a reparse point whose tag is
//! IO_REPARSE_TAG_SYMLINK, and nothing else. A junction (IO_REPARSE_TAG_MOUNT_POINT) - a moved profile, a
//! folder linked elsewhere - is a folder to Python 3.12+ and so to the store. Rust's
//! `FileType::is_symlink()` counts every name-surrogate tag, junctions included, and std gives no reparse
//! tag, so the tag is read here the way CPython's `os.lstat` reads it (`win32_xstat_slow_impl`):
//! `CreateFileW(FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS)` and
//! `GetFileInformationByHandleEx(FileAttributeTagInfo)`, falling back to `FindFirstFileW` where the file
//! cannot be opened (access denied, a sharing violation).
//!
//! SEAM, TO BE REPLACED by car-platform's (S3.1): D3 puts every Windows call there, and car-store does not
//! depend on car-platform (test_stack EDGES store -> machine, policy). Until then this is the one Windows call
//! in car-store, with no crate: three kernel32 functions declared by hand.

use std::path::Path;

/// IO_REPARSE_TAG_SYMLINK.
pub const SYMLINK_TAG: u32 = 0xA000_000C;

/// Whether Python's `Path(path).is_symlink()` is true: False for a path that cannot be looked at.
pub fn is_symlink(path: &Path) -> bool {
    imp::reparse_tag(path) == Some(SYMLINK_TAG)
}

#[cfg(windows)]
mod imp {
    use std::ffi::c_void;
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::fs::MetadataExt;
    use std::path::Path;

    type Handle = *mut c_void;
    const INVALID_HANDLE_VALUE: Handle = -1isize as Handle;
    const FILE_READ_ATTRIBUTES: u32 = 0x80;
    const FILE_SHARE_ALL: u32 = 0x1 | 0x2 | 0x4;
    const OPEN_EXISTING: u32 = 3;
    const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
    const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    const FILE_ATTRIBUTE_TAG_INFO: i32 = 9;
    const ERROR_ACCESS_DENIED: i32 = 5;
    const ERROR_SHARING_VIOLATION: i32 = 32;

    #[repr(C)]
    struct AttributeTagInfo {
        file_attributes: u32,
        reparse_tag: u32,
    }

    #[repr(C)]
    struct FindData {
        file_attributes: u32,
        times: [u32; 6],
        size_high: u32,
        size_low: u32,
        reserved0: u32,
        reserved1: u32,
        file_name: [u16; 260],
        alternate_name: [u16; 14],
        obsolete: [u32; 2],
    }

    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn CreateFileW(
            name: *const u16,
            access: u32,
            share: u32,
            security: *mut c_void,
            disposition: u32,
            flags: u32,
            template: Handle,
        ) -> Handle;
        fn GetFileInformationByHandleEx(
            file: Handle,
            class: i32,
            information: *mut c_void,
            size: u32,
        ) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn FindFirstFileW(name: *const u16, data: *mut FindData) -> Handle;
        fn FindClose(handle: Handle) -> i32;
    }

    /// The reparse tag of `path` itself, not followed; None for no reparse point or a path not looked at.
    pub fn reparse_tag(path: &Path) -> Option<u32> {
        // A path that is no reparse point needs no call: the attributes std reads say so.
        let attributes = std::fs::symlink_metadata(path).ok()?.file_attributes();
        if attributes & FILE_ATTRIBUTE_REPARSE_POINT == 0 {
            return None;
        }
        let wide: Vec<u16> = path.as_os_str().encode_wide().chain([0]).collect();
        // SAFETY: `wide` is NUL-terminated and outlives the call; the handle is closed below.
        let handle = unsafe {
            CreateFileW(
                wide.as_ptr(),
                FILE_READ_ATTRIBUTES,
                FILE_SHARE_ALL,
                std::ptr::null_mut(),
                OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            let error = std::io::Error::last_os_error().raw_os_error();
            if !matches!(error, Some(ERROR_ACCESS_DENIED | ERROR_SHARING_VIOLATION)) {
                return None;
            }
            let mut data = std::mem::MaybeUninit::<FindData>::zeroed();
            // SAFETY: `data` is a writable WIN32_FIND_DATAW; the search handle is closed below.
            let search = unsafe { FindFirstFileW(wide.as_ptr(), data.as_mut_ptr()) };
            if search == INVALID_HANDLE_VALUE {
                return None;
            }
            // SAFETY: FindFirstFileW filled `data`; `search` is a valid search handle.
            let data = unsafe {
                FindClose(search);
                data.assume_init()
            };
            return (data.file_attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
                .then_some(data.reserved0);
        }
        let mut information = AttributeTagInfo {
            file_attributes: 0,
            reparse_tag: 0,
        };
        // SAFETY: `handle` is open and `information` is a FILE_ATTRIBUTE_TAG_INFO of the size given.
        let read = unsafe {
            let read = GetFileInformationByHandleEx(
                handle,
                FILE_ATTRIBUTE_TAG_INFO,
                (&mut information as *mut AttributeTagInfo).cast(),
                std::mem::size_of::<AttributeTagInfo>() as u32,
            );
            CloseHandle(handle);
            read
        };
        (read != 0 && information.file_attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0)
            .then_some(information.reparse_tag)
    }
}

#[cfg(not(windows))]
mod imp {
    use std::path::Path;

    /// Off Windows a link is a link (`S_ISLNK`), as Python's `lstat` says.
    pub fn reparse_tag(path: &Path) -> Option<u32> {
        std::fs::symlink_metadata(path)
            .ok()?
            .file_type()
            .is_symlink()
            .then_some(super::SYMLINK_TAG)
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    #[test]
    fn a_junction_is_a_folder_and_a_folder_is_not_a_link() {
        let base = std::env::temp_dir().join(format!("car-store-links-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(base.join("target")).unwrap();
        use std::os::windows::process::CommandExt;
        let made = std::process::Command::new("cmd")
            .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
            .args(["/c", "mklink", "/J"])
            .arg(base.join("junction"))
            .arg(base.join("target"))
            .output()
            .unwrap();
        assert!(made.status.success(), "mklink /J failed");
        assert!(
            std::fs::symlink_metadata(base.join("junction"))
                .unwrap()
                .file_type()
                .is_symlink(),
            "std counts it"
        );
        assert!(!is_symlink(&base.join("junction")), "Python does not");
        assert!(!is_symlink(&base.join("target")));
        assert!(!is_symlink(&base.join("missing")));
        std::fs::remove_dir(base.join("junction")).unwrap();
        std::fs::remove_dir_all(&base).unwrap();
    }
}

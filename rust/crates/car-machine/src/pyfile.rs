//! Files opened as Python opens them on Windows.
//!
//! CPython's `open()`, `os.open()`, `Path.read_bytes()` and `tempfile.mkstemp()` go through the C runtime's `_wopen`,
//! whose share mode is `FILE_SHARE_READ | FILE_SHARE_WRITE`: while the reference holds a file, nobody can delete or
//! rename it (`install.ps1`'s Remove-HomeLocks counts on that for the watcher's home locks; a rotation of the log by
//! another process fails while a writer holds it). Rust's `std::fs::OpenOptions` shares delete too. Every file the
//! product opens goes through [`options`] (or [`read`]) so that it is held as the reference holds it.

use std::fs::{File, OpenOptions};
use std::io::Read;
use std::path::Path;

/// `FILE_SHARE_READ | FILE_SHARE_WRITE`: the C runtime's `_SH_DENYNO`, which every Python open uses.
pub const PYTHON_SHARE: u32 = 0x1 | 0x2;

/// `OpenOptions::new()` with Python's share mode; the caller sets read, write, append, create as it needs.
pub fn options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(PYTHON_SHARE);
    }
    options
}

/// `File::open` (read only), shared as Python shares.
pub fn open(path: impl AsRef<Path>) -> std::io::Result<File> {
    options().read(true).open(path)
}

/// `std::fs::read`, with the file held as `Path.read_bytes()` holds it.
pub fn read(path: impl AsRef<Path>) -> std::io::Result<Vec<u8>> {
    let mut file = open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(bytes)
}

/// `std::fs::write`, with the file held as `Path.write_bytes()` holds it (created or truncated).
pub fn write(path: impl AsRef<Path>, contents: impl AsRef<[u8]>) -> std::io::Result<()> {
    use std::io::Write;
    let mut file = options()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)?;
    file.write_all(contents.as_ref())
}

// os.replace and os.rename are MoveFileExW and nothing more. `std::fs::rename` retries MoveFileExW's
// ERROR_ACCESS_DENIED with a POSIX-semantics rename, which replaces a target another handle holds open with
// FILE_SHARE_DELETE where Python stops with PermissionError 5 (review 5, S2). D3 puts every Windows call in
// car-platform, but car-policy and car-config cannot reach it (PLAN 1.3's graph) and car-machine is the one crate every
// caller reaches: this one extern declaration (kernel32, which std links already) is the exception, as car-brand's
// erfc is, and every save and rotation of the product goes through it.
#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn MoveFileExW(existing: *const u16, new: *const u16, flags: u32) -> i32;
}

#[cfg(windows)]
const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;

#[cfg(windows)]
fn move_file(from: &Path, to: &Path, flags: u32) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    let wide =
        |path: &Path| -> Vec<u16> { path.as_os_str().encode_wide().chain(Some(0)).collect() };
    let (from, to) = (wide(from), wide(to));
    // SAFETY: both names are NUL-terminated and outlive the call.
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), flags) } == 0 {
        return Err(std::io::Error::last_os_error());
    }
    Ok(())
}

/// `os.replace(from, to)`: `MoveFileExW(MOVEFILE_REPLACE_EXISTING)` alone - a target another handle holds open is not
/// replaced (PermissionError 5), whatever that handle shares.
pub fn replace(from: impl AsRef<Path>, to: impl AsRef<Path>) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        move_file(from.as_ref(), to.as_ref(), MOVEFILE_REPLACE_EXISTING)
    }
    #[cfg(not(windows))]
    {
        std::fs::rename(from, to)
    }
}

/// `os.rename(from, to)`: `MoveFileExW` with no flag - an existing target is not replaced (FileExistsError 183).
pub fn rename(from: impl AsRef<Path>, to: impl AsRef<Path>) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        move_file(from.as_ref(), to.as_ref(), 0)
    }
    #[cfg(not(windows))]
    {
        std::fs::rename(from, to)
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    /// A file held through these opens cannot be deleted or renamed; one held by std's default can.
    #[test]
    fn a_held_file_cannot_be_deleted_or_renamed() {
        let folder =
            std::env::temp_dir().join(format!("car-machine-pyfile-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("held");
        write(&path, b"x").unwrap();
        {
            let _held = options().read(true).write(true).open(&path).unwrap();
            assert!(std::fs::remove_file(&path).is_err(), "deleted while held");
            assert!(
                std::fs::rename(&path, folder.join("moved")).is_err(),
                "renamed while held"
            );
            // Reading and writing beside it are shared, as Python's are.
            assert_eq!(read(&path).unwrap(), b"x");
            write(&path, b"y").unwrap();
        }
        {
            let _held = OpenOptions::new().read(true).open(&path).unwrap();
            assert!(
                std::fs::remove_file(&path).is_ok(),
                "std's default shares delete"
            );
        }
        let _ = std::fs::remove_dir_all(&folder);
    }

    /// `replace` refuses a target held open with share-delete, as os.replace does, where std's rename replaces it;
    /// `rename` refuses an existing target.
    #[test]
    fn a_held_target_is_not_replaced() {
        use std::os::windows::fs::OpenOptionsExt;
        let folder =
            std::env::temp_dir().join(format!("car-machine-replace-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        let (from, to) = (folder.join("new"), folder.join("target"));
        std::fs::write(&from, b"new").unwrap();
        std::fs::write(&to, b"old").unwrap();
        {
            let _held = OpenOptions::new()
                .read(true)
                .share_mode(0x1 | 0x2 | 0x4)
                .open(&to)
                .unwrap();
            let refused = replace(&from, &to).unwrap_err();
            assert_eq!(refused.raw_os_error(), Some(5));
        }
        assert_eq!(std::fs::read(&to).unwrap(), b"old");
        assert_eq!(rename(&from, &to).unwrap_err().raw_os_error(), Some(183));
        replace(&from, &to).unwrap();
        assert_eq!(std::fs::read(&to).unwrap(), b"new");
        assert!(!from.exists());
        let _ = std::fs::remove_dir_all(&folder);
    }
}

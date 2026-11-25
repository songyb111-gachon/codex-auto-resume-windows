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

/// `Path.write_text(text, encoding="utf-8")` on Windows: text mode writes every `\n` as `\r\n` (os.linesep; a `\r\n`
/// in the text becomes `\r\r\n`, as Python writes it), held as `write` holds the file.
pub fn write_text(path: impl AsRef<Path>, text: &str) -> std::io::Result<()> {
    if cfg!(windows) {
        write(path, text.replace('\n', "\r\n"))
    } else {
        write(path, text)
    }
}

// os.replace and os.rename are MoveFileExW and nothing more; `std::fs::rename` retries MoveFileExW's
// ERROR_ACCESS_DENIED with a POSIX-semantics rename, which replaces a target another handle holds open with
// FILE_SHARE_DELETE where Python stops with PermissionError 5 (review 5, S2). The real ones are car-platform's
// `files::{replace, rename}` (D3: every Windows call there), which the binaries hand to car-policy (`settings::os::Os`)
// and car-config (`Logbook::with_rename`). These are the std-only defaults where nothing was handed in: they never let
// std's POSIX retry replace a held target, answering as os.replace and os.rename answer on those cases.

/// Whether another handle holds `path` open: an open asking DELETE access and sharing nothing fails with a sharing
/// violation (32) while any other handle with any access is open, whatever that handle shares.
fn held(path: &Path) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const DELETE: u32 = 0x0001_0000;
        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        let probe = OpenOptions::new()
            .access_mode(DELETE)
            .share_mode(0)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(path);
        matches!(probe, Err(error) if error.raw_os_error() == Some(32))
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        false
    }
}

/// `os.replace(from, to)` with std alone: a target another handle holds open is refused with PermissionError 5, as
/// MoveFileExW(MOVEFILE_REPLACE_EXISTING) refuses it; otherwise std's rename, which then has no held target to retry
/// over. The product's binaries hand car-platform's `files::replace` in instead.
pub fn replace(from: impl AsRef<Path>, to: impl AsRef<Path>) -> std::io::Result<()> {
    if held(to.as_ref()) {
        return Err(std::io::Error::from_raw_os_error(5));
    }
    std::fs::rename(from, to)
}

/// `os.rename(from, to)` with std alone: an existing target is refused with FileExistsError 183, as MoveFileExW with
/// no flag refuses it; otherwise std's rename. The product's binaries hand car-platform's `files::rename` in instead.
pub fn rename(from: impl AsRef<Path>, to: impl AsRef<Path>) -> std::io::Result<()> {
    if std::fs::symlink_metadata(to.as_ref()).is_ok() {
        return Err(std::io::Error::from_raw_os_error(183));
    }
    std::fs::rename(from, to)
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

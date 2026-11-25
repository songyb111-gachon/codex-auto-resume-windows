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
    let mut file = options().write(true).create(true).truncate(true).open(path)?;
    file.write_all(contents.as_ref())
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    /// A file held through these opens cannot be deleted or renamed; one held by std's default can.
    #[test]
    fn a_held_file_cannot_be_deleted_or_renamed() {
        let folder = std::env::temp_dir().join(format!("car-machine-pyfile-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("held");
        write(&path, b"x").unwrap();
        {
            let _held = options().read(true).write(true).open(&path).unwrap();
            assert!(std::fs::remove_file(&path).is_err(), "deleted while held");
            assert!(std::fs::rename(&path, folder.join("moved")).is_err(), "renamed while held");
            // Reading and writing beside it are shared, as Python's are.
            assert_eq!(read(&path).unwrap(), b"x");
            write(&path, b"y").unwrap();
        }
        {
            let _held = OpenOptions::new().read(true).open(&path).unwrap();
            assert!(std::fs::remove_file(&path).is_ok(), "std's default shares delete");
        }
        let _ = std::fs::remove_dir_all(&folder);
    }

}

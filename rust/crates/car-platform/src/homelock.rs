//! Two locks: the installer's, which is waited for, and our own home's, which is held (`win/homelock.py`,
//! `win/folderid.py`).
//!
//! While an installation, a repair or an update holds its lock nothing starts a watcher, and a watcher holds an
//! exclusive lock on the home it is watching for its whole life, so two of them cannot run over one state. The lock
//! is a byte-range lock on the first byte of a file of ours (`LockFileEx`, exclusive, fail at once) - the range
//! `msvcrt.locking` locks - so a Rust watcher and a Python watcher exclude one another.
//!
//! No `LockFileEx`/byte-lock probe exists anywhere in this tool on a file of Codex's, by design: acquiring the
//! thread writer lock, even for microseconds, could make the ChatGPT app's own try-lock fail.

use std::fs::File;
use std::os::windows::io::AsRawHandle;
use std::path::{Path, PathBuf};

use windows::Win32::Foundation::{CloseHandle, ERROR_FILE_NOT_FOUND, HANDLE};
use windows::Win32::Storage::FileSystem::{
    BY_HANDLE_FILE_INFORMATION, CreateFileW, FILE_ATTRIBUTE_DIRECTORY, FILE_FLAG_BACKUP_SEMANTICS,
    FILE_FLAGS_AND_ATTRIBUTES, FILE_READ_ATTRIBUTES, FILE_SHARE_DELETE, FILE_SHARE_READ,
    FILE_SHARE_WRITE, GetFileInformationByHandle, LOCKFILE_EXCLUSIVE_LOCK,
    LOCKFILE_FAIL_IMMEDIATELY, LockFileEx, OPEN_EXISTING, UnlockFileEx,
};
use windows::Win32::System::IO::OVERLAPPED;
use windows::Win32::System::Threading::{OpenMutexW, SYNCHRONIZATION_ACCESS_RIGHTS};
use windows::core::{HRESULT, PCWSTR};

use crate::names::{INSTALL_LOCK, identity_lock_path};
use crate::paths::wide;
use car_machine::domain::errors::AdapterError;

const SYNCHRONIZE: u32 = 0x0010_0000;

/// True while an installation, repair or update holds its lock; it only opens the mutex, never waits on it and
/// never owns it, even for an instant. A name that does not exist is no installation.
pub fn install_in_progress() -> bool {
    let name = wide(INSTALL_LOCK);
    // SAFETY: `name` is NUL-terminated and outlives the call.
    match unsafe {
        OpenMutexW(
            SYNCHRONIZATION_ACCESS_RIGHTS(SYNCHRONIZE),
            false,
            PCWSTR(name.as_ptr()),
        )
    } {
        Ok(handle) => {
            // SAFETY: the handle was just opened.
            unsafe {
                let _ = CloseHandle(handle);
            }
            true
        }
        Err(error) => error.code() != HRESULT::from_win32(ERROR_FILE_NOT_FOUND.0),
    }
}

/// `<volume serial>-<file index>` of the folder `path` names, as 8 and 16 lowercase hex digits - or None where it
/// cannot be told: no such folder, a file, or a folder Windows will not open. It names the folder whatever it is
/// spelled as (a junction, a subst drive, a share of the same disk). Read only.
pub fn folder_identity(path: &Path) -> Option<String> {
    if !path.is_dir() {
        return None;
    }
    let name = crate::paths::wide_os(path.as_os_str());
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
    if found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY.0 == 0 {
        return None;
    }
    let index = (u64::from(found.nFileIndexHigh) << 32) | u64::from(found.nFileIndexLow);
    Some(format!("{:08x}-{:016x}", found.dwVolumeSerialNumber, index))
}

fn locked_range() -> OVERLAPPED {
    OVERLAPPED::default()
}

/// A file of ours with its first byte held exclusively.
struct Held {
    file: File,
}

impl Held {
    fn take(path: &Path) -> Result<Held, AdapterError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|_| AdapterError("home_lock_unavailable"))?;
        }
        // Shared for reading and writing only, as os.open shares: a held lock cannot be deleted (Remove-HomeLocks).
        let file = car_machine::pyfile::options()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .map_err(|_| AdapterError("home_lock_unavailable"))?;
        let mut range = locked_range();
        // SAFETY: the handle belongs to `file`, which outlives the lock.
        let locked = unsafe {
            LockFileEx(
                HANDLE(file.as_raw_handle()),
                LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY,
                None,
                1,
                0,
                &mut range,
            )
        };
        if locked.is_err() {
            return Err(AdapterError("home_lock_busy"));
        }
        Ok(Held { file })
    }
}

impl Drop for Held {
    fn drop(&mut self) {
        let mut range = locked_range();
        // SAFETY: the range this value locked.
        unsafe {
            let _ = UnlockFileEx(HANDLE(self.file.as_raw_handle()), None, 1, 0, &mut range);
        }
    }
}

/// An exclusive lock, for the watcher's whole life, on our own files for one Codex home: the one named by the
/// home's resolved path (as since v0.6.0, so a watcher of an earlier version is still excluded by the same
/// spelling) and one named by the folder's identity, which no spelling changes. Either busy is busy, and nothing is
/// left held. A folder whose identity cannot be read now is locked by its path alone; a home that needs it
/// (`require_identity`) is not locked at all then: "home_unavailable".
pub struct HomeLock {
    pub home: PathBuf,
    pub root: String,
    pub path: PathBuf,
    pub require_identity: bool,
    pub identity: Option<String>,
    path_lock: Option<Held>,
    id_lock: Option<Held>,
}

impl HomeLock {
    pub fn new(
        codex_home: &str,
        base: Option<&str>,
        require_identity: bool,
    ) -> Result<Self, AdapterError> {
        let root = crate::names::lock_root(base).ok_or(AdapterError("windows_required"))?;
        let path = crate::names::home_lock_path(codex_home, base)
            .ok_or(AdapterError("windows_required"))?;
        Ok(HomeLock {
            home: PathBuf::from(codex_home),
            root,
            path,
            require_identity,
            identity: None,
            path_lock: None,
            id_lock: None,
        })
    }

    pub fn held(&self) -> bool {
        self.path_lock.is_some()
    }

    pub fn enter(&mut self) -> Result<(), AdapterError> {
        let identity = folder_identity(&self.home);
        if identity.is_none() && self.require_identity {
            return Err(AdapterError("home_unavailable"));
        }
        let first = Held::take(&self.path)?;
        let second = match &identity {
            Some(identity) => Some(Held::take(&identity_lock_path(&self.root, identity))?),
            None => None,
        };
        self.path_lock = Some(first);
        self.id_lock = second;
        self.identity = identity;
        Ok(())
    }

    pub fn exit(&mut self) {
        self.id_lock = None;
        self.path_lock = None;
    }
}

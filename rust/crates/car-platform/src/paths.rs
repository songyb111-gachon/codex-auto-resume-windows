//! How Python spells a path, and the hash the product names things by (`os.path.normcase`, `Path.resolve`,
//! `Path.home`, `hashlib.sha256`).
//!
//! Every named object, lock file and registration the product derives from a home or a user is named from
//! `normcase(str(Path.home().resolve()))` and a SHA-256 of it. Rust spells the same text here so a name made by
//! this crate and a name made by the Python reference are the same name - a watcher of either one must find the
//! other's mutex (PLAN 6.2). The reference is the bundled Python's (3.14.10) `ntpath` (`normcase` is LCMapStringEx on
//! the invariant locale, `realpath` is car-machine's `winpath::realpath_os` asked natively).

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};

use windows::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, LPARAM};
use windows::Win32::Globalization::{LCMAP_LOWERCASE, LCMapStringEx};
use windows::Win32::Security::Cryptography::{BCRYPT_SHA256_ALG_HANDLE, BCryptHash};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, FindClose,
    FindFirstFileW, GetFinalPathNameByHandleW, OPEN_EXISTING, VOLUME_NAME_DOS, WIN32_FIND_DATAW,
};
use windows::Win32::System::Registry::{HKEY_LOCAL_MACHINE, RRF_RT_REG_DWORD, RegGetValueW};
use windows::core::{PCWSTR, w};

/// A NUL-terminated UTF-16 copy of `text`, for a call that takes `PCWSTR`.
pub fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

/// A NUL-terminated UTF-16 copy of an OS string (a path that may hold what UTF-8 cannot).
pub fn wide_os(text: &OsStr) -> Vec<u16> {
    text.encode_wide().chain(std::iter::once(0)).collect()
}

/// The text of a UTF-16 buffer up to its first NUL.
pub fn from_wide(buffer: &[u16]) -> String {
    let end = buffer
        .iter()
        .position(|&unit| unit == 0)
        .unwrap_or(buffer.len());
    String::from_utf16_lossy(&buffer[..end])
}

/// `ntpath.normcase`: slashes made backslashes, then lower-cased the way Windows lower-cases a file name.
pub fn normcase(text: &str) -> String {
    let replaced = text.replace('/', "\\");
    if replaced.is_empty() {
        return replaced;
    }
    let source: Vec<u16> = replaced.encode_utf16().collect();
    let mut target = vec![0u16; source.len() + 1];
    // SAFETY: both buffers are ours and as long as the lengths we pass.
    let written = unsafe {
        LCMapStringEx(
            w!(""),
            LCMAP_LOWERCASE,
            &source,
            Some(&mut target),
            None,
            None,
            LPARAM(0),
        )
    };
    if written <= 0 {
        return replaced.to_lowercase();
    }
    String::from_utf16_lossy(&target[..written as usize])
}

/// SHA-256 of `data`, as 64 lower-case hex digits (`hashlib.sha256(data).hexdigest()`).
pub fn sha256_hex(data: &[u8]) -> String {
    let mut digest = [0u8; 32];
    // SAFETY: the pseudo handle needs no opening; the buffers are ours.
    let status = unsafe { BCryptHash(BCRYPT_SHA256_ALG_HANDLE, None, data, &mut digest) };
    assert!(status.0 == 0, "BCryptHash failed: {:#x}", status.0);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        hex.push_str(&format!("{byte:02x}"));
    }
    hex
}

/// (drive or share with its root separator, the rest) of a Windows path: `C:\`, `C:`, `\\server\share\`, `\`.
fn split_root(text: &str) -> (String, &str) {
    if let Some(rest) = text.strip_prefix("\\\\?\\") {
        let (inner, tail) = split_root(rest);
        return (format!("\\\\?\\{inner}"), tail);
    }
    let bytes = text.as_bytes();
    if let Some(body) = text.strip_prefix("\\\\") {
        // a share: two separators, the server, one more, the share name
        let mut separators = body.match_indices('\\').map(|(index, _)| index);
        return match (separators.next(), separators.next()) {
            (Some(_), Some(second)) => (text[..2 + second + 1].to_string(), &body[second + 1..]),
            _ => (text.to_string(), ""),
        };
    }
    if bytes.len() >= 2 && bytes[1] == b':' && bytes[0].is_ascii_alphabetic() {
        if bytes.len() >= 3 && bytes[2] == b'\\' {
            return (text[..3].to_string(), &text[3..]);
        }
        return (text[..2].to_string(), &text[2..]);
    }
    if let Some(rest) = text.strip_prefix('\\') {
        return ("\\".to_string(), rest);
    }
    (String::new(), text)
}

/// `str(Path(text))`: slashes made backslashes, repeated separators one, `.` parts and a trailing separator gone
/// (pathlib's own tidying; `..` is left, only `realpath` resolves it).
pub fn pathlib_text(text: &str) -> String {
    let text = text.replace('/', "\\");
    let (prefix, rest) = split_root(&text);
    let parts: Vec<&str> = rest
        .split('\\')
        .filter(|part| !part.is_empty() && *part != ".")
        .collect();
    let joined = parts.join("\\");
    if joined.is_empty() && prefix.is_empty() {
        return ".".to_string();
    }
    format!("{prefix}{joined}")
}

/// `ntpath.normpath`: separators one, `.` and `..` folded lexically, never above a root.
pub fn normpath(text: &str) -> String {
    let text = text.replace('/', "\\");
    if text.is_empty() {
        return ".".to_string();
    }
    let (prefix, rest) = split_root(&text);
    let rooted = prefix.ends_with('\\');
    let mut stack: Vec<&str> = Vec::new();
    for part in rest.split('\\') {
        match part {
            "" | "." => {}
            ".." => {
                if stack.last().is_some_and(|last| *last != "..") {
                    stack.pop();
                } else if !rooted {
                    stack.push("..");
                }
            }
            other => stack.push(other),
        }
    }
    let result = format!("{prefix}{}", stack.join("\\"));
    if result.is_empty() {
        ".".to_string()
    } else {
        result
    }
}

fn is_absolute(text: &str) -> bool {
    let (prefix, _) = split_root(text);
    prefix.ends_with('\\') && prefix != "\\"
}

/// `nt._getfinalpathname(path)`: the final path name Windows gives an existing file or folder (`\\?\C:\...`), or the
/// Windows error number. Opened as CPython opens it (no access, no sharing, backup semantics). A path past 260
/// characters is opened through its `\\?\` form where long paths are on, as the long-path-aware python.exe opens it.
fn final_path(path: &str) -> Result<String, i32> {
    let long = !path.starts_with("\\\\") && path.encode_utf16().count() >= 260 && long_paths_enabled();
    let name = wide(&if long { format!("\\\\?\\{path}") } else { path.to_string() });
    // SAFETY: `name` outlives the call; the handle is closed below.
    let handle: HANDLE = unsafe {
        CreateFileW(
            PCWSTR(name.as_ptr()),
            0,
            FILE_SHARE_MODE(0),
            None,
            OPEN_EXISTING,
            FILE_FLAGS_AND_ATTRIBUTES(FILE_FLAG_BACKUP_SEMANTICS.0),
            None,
        )
    }
    .map_err(|error| error.code().0 & 0xFFFF)?;
    let mut buffer = vec![0u16; 1024];
    let result = loop {
        // SAFETY: the buffer is ours.
        let length =
            unsafe { GetFinalPathNameByHandleW(handle, &mut buffer, VOLUME_NAME_DOS) } as usize;
        if length == 0 {
            // SAFETY: no call between.
            break Err(unsafe { GetLastError() }.0 as i32);
        }
        if length > buffer.len() {
            buffer = vec![0u16; length + 1];
            continue;
        }
        break Ok(String::from_utf16_lossy(&buffer[..length]));
    };
    // SAFETY: opened above.
    unsafe {
        let _ = CloseHandle(handle);
    }
    result
}

/// `nt._findfirstfile(path)`: the name FindFirstFileW gives the last component (its real case, its long name), or
/// the Windows error number.
pub fn find_first_file(path: &str) -> Result<String, i32> {
    let name = wide(path);
    let mut data = WIN32_FIND_DATAW::default();
    // SAFETY: `name` is NUL-terminated; `data` is a writable WIN32_FIND_DATAW; the search handle is closed below.
    let search = unsafe { FindFirstFileW(PCWSTR(name.as_ptr()), &mut data) }
        .map_err(|error| error.code().0 & 0xFFFF)?;
    // SAFETY: FindFirstFileW gave `search`.
    unsafe {
        let _ = FindClose(search);
    }
    Ok(from_wide(&data.cFileName))
}

/// `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled` is 1: python.exe (whose manifest is long-path
/// aware) then opens a path past 260 characters without its prefix. Read once.
pub fn long_paths_enabled() -> bool {
    static ENABLED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ENABLED.get_or_init(|| {
        let mut value: u32 = 0;
        let mut size = std::mem::size_of::<u32>() as u32;
        // SAFETY: `value` and `size` are ours and sized for a DWORD; the names are NUL-terminated literals.
        let read = unsafe {
            RegGetValueW(
                HKEY_LOCAL_MACHINE,
                w!("SYSTEM\\CurrentControlSet\\Control\\FileSystem"),
                w!("LongPathsEnabled"),
                RRF_RT_REG_DWORD,
                None,
                Some((&mut value as *mut u32).cast()),
                Some(&mut size),
            )
        };
        read.is_ok() && value == 1
    })
}

/// What `os.path.realpath` asks of Windows, answered natively.
struct Native;

impl car_machine::winpath::NtOs for Native {
    fn final_path(&self, path: &str) -> Result<String, i32> {
        final_path(path)
    }
    fn is_symlink(&self, path: &str) -> bool {
        crate::links::is_symlink(Path::new(path))
    }
    fn find_first_file(&self, path: &str) -> Result<String, i32> {
        find_first_file(path)
    }
    fn long_paths(&self) -> bool {
        long_paths_enabled()
    }
}

/// `os.path.realpath` for a path (non-strict, the bundled 3.14.10's: car-machine's `winpath::realpath_os`, the one
/// implementation car-config resolves with too): what exists is spelled as Windows spells it (long names, the real
/// case, links followed, a link the OS cannot open followed by hand); what does not exist is kept as written after the
/// part that does. Where the reference would raise an OSError (an error the walk does not pass over), the path made
/// absolute is answered, as this crate always has.
pub fn realpath(text: &str) -> String {
    let normal = normpath(text);
    let cwd = std::env::current_dir()
        .map(|p| p.display().to_string())
        .unwrap_or_default();
    let absolute = if is_absolute(&normal) {
        normal.clone()
    } else {
        normpath(&format!("{cwd}\\{normal}"))
    };
    car_machine::winpath::realpath_os(&normal, &cwd, &Native).unwrap_or(absolute)
}

/// `Path.home()` as text, from the environment as Python reads it: USERPROFILE, else HOMEDRIVE and HOMEPATH.
pub fn home_text() -> Option<String> {
    if let Some(profile) = std::env::var_os("USERPROFILE") {
        return Some(pathlib_text(&profile.to_string_lossy()));
    }
    let path = std::env::var_os("HOMEPATH")?;
    let mut joined = std::env::var_os("HOMEDRIVE").unwrap_or_default();
    joined.push(&path);
    Some(pathlib_text(&joined.to_string_lossy()))
}

/// `Path.home()`.
pub fn home_dir() -> Option<PathBuf> {
    home_text().map(PathBuf::from)
}

/// `os.path.normcase(str(Path(path).resolve()))`: the one spelling every derived name is made from.
pub fn identity_text(path: &str) -> String {
    normcase(&realpath(&pathlib_text(path)))
}

/// `os.path.normcase(str(Path.home().resolve()))`; None where no home can be told.
pub fn home_identity() -> Option<String> {
    Some(normcase(&realpath(&home_text()?)))
}

/// A path's text for the places the product writes it (lossy where the path is not Unicode).
pub fn text_of(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

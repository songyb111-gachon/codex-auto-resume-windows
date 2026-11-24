//! How Python spells a path, and the hash the product names things by (`os.path.normcase`, `Path.resolve`,
//! `Path.home`, `hashlib.sha256`).
//!
//! Every named object, lock file and registration the product derives from a home or a user is named from
//! `normcase(str(Path.home().resolve()))` and a SHA-256 of it. Rust spells the same text here so a name made by
//! this crate and a name made by the Python reference are the same name - a watcher of either one must find the
//! other's mutex (PLAN 6.2). The reference is Python 3.13's `ntpath` (`normcase` is LCMapStringEx on the
//! invariant locale, `realpath` is the final path name of what exists and the rest of the path as written).

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};

use windows::Win32::Foundation::{CloseHandle, HANDLE, LPARAM};
use windows::Win32::Globalization::{LCMAP_LOWERCASE, LCMapStringEx};
use windows::Win32::Security::Cryptography::{BCRYPT_SHA256_ALG_HANDLE, BCryptHash};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE,
    GetFinalPathNameByHandleW, OPEN_EXISTING, VOLUME_NAME_DOS,
};
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

/// The final path name Windows gives an existing file or folder (`\\?\C:\...`), or None.
fn final_path(path: &str) -> Option<String> {
    let name = wide(path);
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
    .ok()?;
    let mut buffer = vec![0u16; 1024];
    let result = loop {
        // SAFETY: the buffer is ours.
        let length =
            unsafe { GetFinalPathNameByHandleW(handle, &mut buffer, VOLUME_NAME_DOS) } as usize;
        if length == 0 {
            break None;
        }
        if length > buffer.len() {
            buffer = vec![0u16; length + 1];
            continue;
        }
        break Some(String::from_utf16_lossy(&buffer[..length]));
    };
    // SAFETY: opened above.
    unsafe {
        let _ = CloseHandle(handle);
    }
    result
}

/// `os.path.realpath` for a path: what exists is spelled as Windows spells it (long names, the real case, links
/// followed); what does not exist is kept as written after the part that does.
pub fn realpath(text: &str) -> String {
    let normal = normpath(text);
    let absolute = if is_absolute(&normal) {
        normal
    } else {
        let cwd = std::env::current_dir()
            .map(|p| p.display().to_string())
            .unwrap_or_default();
        normpath(&format!("{cwd}\\{normal}"))
    };
    let had_prefix = absolute.starts_with("\\\\?\\");
    let mut head = absolute.clone();
    let mut tail: Vec<String> = Vec::new();
    let found = loop {
        if let Some(path) = final_path(&head) {
            break Some(path);
        }
        let (root, rest) = split_root(&head);
        if rest.is_empty() {
            break None;
        }
        let Some(cut) = head.rfind('\\') else {
            break None;
        };
        tail.push(head[cut + 1..].to_string());
        head = if cut < root.len() {
            root.clone()
        } else {
            head[..cut].to_string()
        };
    };
    let Some(mut resolved) = found else {
        return absolute;
    };
    if !had_prefix && resolved.starts_with("\\\\?\\") {
        if let Some(unc) = resolved.strip_prefix("\\\\?\\UNC\\") {
            resolved = format!("\\\\{unc}");
        } else {
            let short = resolved[4..].to_string();
            let drive = short.as_bytes().get(1) == Some(&b':');
            if drive && final_path(&short).as_deref() == Some(resolved.as_str()) {
                resolved = short;
            }
        }
    }
    for part in tail.iter().rev() {
        if !resolved.ends_with('\\') {
            resolved.push('\\');
        }
        resolved.push_str(part);
    }
    resolved
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

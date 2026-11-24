//! The few questions about paths the settings need answered by Windows, handed in (car-policy makes no Windows call;
//! D3 keeps every one in car-platform).
//!
//! The reference asks them of `ntpath` and `pathlib`: `os.path.islink` (a real symbolic link only - a junction is a
//! folder), `os.path.isjunction`, `os.path.normcase` (LCMapStringEx on the invariant locale), `os.path.abspath`
//! (GetFullPathNameW of the normalised path) and `Path.resolve()`. Texts travel as UTF-16, so a path holding half of
//! a surrogate pair - a hand-edited settings file can hold one - is asked about exactly as Python asks.
//! The entry points build one over car-platform (the harness's `policy` module is the model); car-store's and
//! car-config's `Links` are the same idea.

use std::path::{Path, PathBuf};

use car_machine::json::Str;

pub trait Os {
    /// `os.path.islink(path)`: a real symbolic link, never a junction; false where it cannot be told.
    fn is_symlink(&self, path: &Path) -> bool;
    /// `os.path.isjunction(path)`.
    fn is_junction(&self, path: &Path) -> bool;
    /// `os.path.normcase(text)`.
    fn normcase(&self, text: &[u16]) -> Vec<u16>;
    /// `os.path.abspath(text)` (which falls back to the normalised text where Windows refuses it).
    fn abspath(&self, text: &[u16]) -> Vec<u16>;
    /// `str(Path(text).resolve())`; the class of the exception it raises.
    fn resolve(&self, text: &[u16]) -> Result<Vec<u16>, &'static str>;
}

/// A Python `str` as the UTF-16 Windows takes: a lone surrogate as itself.
pub fn wide(text: &Str) -> Vec<u16> {
    let mut out = Vec::new();
    for point in text.code_points() {
        match char::from_u32(point) {
            Some(c) => {
                let mut buffer = [0u16; 2];
                out.extend_from_slice(c.encode_utf16(&mut buffer));
            }
            // A surrogate code point: one unit, as Python hands it to Windows.
            None => out.push(point as u16),
        }
    }
    out
}

/// UTF-16 back to a Python `str`: pairs joined, a lone half kept.
pub fn from_wide(units: &[u16]) -> Str {
    Str::from_wide(units)
}

/// A Python `str` as a path for the file system.
pub fn os_path(text: &Str) -> PathBuf {
    use std::os::windows::ffi::OsStringExt;
    PathBuf::from(std::ffi::OsString::from_wide(&wide(text)))
}

const BACKSLASH: u16 = b'\\' as u16;
const SLASH: u16 = b'/' as u16;
const COLON: u16 = b':' as u16;
const DOT: u16 = b'.' as u16;

/// `ntpath.splitroot(text)` with the slashes already backslashes: (drive, root, tail) lengths.
fn splitroot(p: &[u16]) -> (usize, usize) {
    let at = |index: usize| p.get(index).copied();
    if at(0) == Some(BACKSLASH) {
        if at(1) == Some(BACKSLASH) {
            // UNC and device drives: \\server\share, \\?\UNC\server\share, \\.\device, \\?\device
            let head: Vec<u16> = p.iter().take(8).map(|unit| upper(*unit)).collect();
            let unc: Vec<u16> = r"\\?\UNC\".encode_utf16().collect();
            let start = if head == unc { 8 } else { 2 };
            let find = |from: usize| {
                p.iter()
                    .skip(from)
                    .position(|unit| *unit == BACKSLASH)
                    .map(|index| index + from)
            };
            let Some(index) = find(start) else {
                return (p.len(), 0);
            };
            let Some(index2) = find(index + 1) else {
                return (p.len(), 0);
            };
            return (index2, 1);
        }
        return (0, 1);
    }
    if at(1) == Some(COLON) {
        return if at(2) == Some(BACKSLASH) {
            (2, 1)
        } else {
            (2, 0)
        };
    }
    (0, 0)
}

fn upper(unit: u16) -> u16 {
    if (u16::from(b'a')..=u16::from(b'z')).contains(&unit) {
        unit - 32
    } else {
        unit
    }
}

/// `ntpath.normpath(text)` over UTF-16 (Python 3.13's): separators made backslashes, `.` and empty parts dropped,
/// `..` taking the part before it (and dropped at the root).
pub fn normpath(text: &[u16]) -> Vec<u16> {
    let path: Vec<u16> = text
        .iter()
        .map(|unit| if *unit == SLASH { BACKSLASH } else { *unit })
        .collect();
    let (drive, root) = splitroot(&path);
    let prefix = &path[..drive + root];
    let rest = &path[drive + root..];
    let mut parts: Vec<&[u16]> = rest.split(|unit| *unit == BACKSLASH).collect();
    let mut i = 0;
    while i < parts.len() {
        if parts[i].is_empty() || parts[i] == [DOT] {
            parts.remove(i);
        } else if parts[i] == [DOT, DOT] {
            if i > 0 && parts[i - 1] != [DOT, DOT] {
                parts.drain(i - 1..=i);
                i -= 1;
            } else if i == 0 && root > 0 {
                parts.remove(i);
            } else {
                i += 1;
            }
        } else {
            i += 1;
        }
    }
    let mut out = prefix.to_vec();
    if prefix.is_empty() && parts.is_empty() {
        out.push(DOT);
        return out;
    }
    for (index, part) in parts.iter().enumerate() {
        if index > 0 {
            out.push(BACKSLASH);
        }
        out.extend_from_slice(part);
    }
    out
}

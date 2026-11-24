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
    /// `os.path.abspath(text)`; the class of the exception it raises.
    fn abspath(&self, text: &[u16]) -> Result<Vec<u16>, &'static str>;
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

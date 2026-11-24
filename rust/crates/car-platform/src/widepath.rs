//! `os.path.normcase` and `os.path.abspath`'s `GetFullPathNameW` over UTF-16 text (S2.2), for car-policy's `Os`.
//!
//! The settings hold paths a person or a hand-edited file wrote, which may hold half of a surrogate pair; Python hands
//! such a text to Windows unit for unit, and so do these. `paths::normcase` is the same question over UTF-8 text.

use windows::Win32::Foundation::LPARAM;
use windows::Win32::Globalization::{LCMAP_LOWERCASE, LCMapStringEx};
use windows::Win32::Storage::FileSystem::GetFullPathNameW;
use windows::core::{PCWSTR, w};

const BACKSLASH: u16 = b'\\' as u16;
const SLASH: u16 = b'/' as u16;

/// `ntpath.normcase(text)`: slashes made backslashes, then lower-cased by `LCMapStringEx` on the invariant locale.
pub fn normcase(text: &[u16]) -> Vec<u16> {
    let source: Vec<u16> = text
        .iter()
        .map(|unit| if *unit == SLASH { BACKSLASH } else { *unit })
        .collect();
    if source.is_empty() {
        return source;
    }
    let mut target = vec![0u16; source.len() * 2 + 8];
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
        return source;
    }
    target.truncate(written as usize);
    target
}

/// `nt._getfullpathname(text)`: `GetFullPathNameW`, or None where it fails (Python then falls back).
pub fn full_path(text: &[u16]) -> Option<Vec<u16>> {
    if text.contains(&0) {
        return None;
    }
    let mut name: Vec<u16> = text.to_vec();
    name.push(0);
    let mut buffer = vec![0u16; 1024];
    loop {
        // SAFETY: `name` is NUL-terminated and outlives the call; the buffer is ours and as long as we say.
        let needed =
            unsafe { GetFullPathNameW(PCWSTR(name.as_ptr()), Some(&mut buffer), None) } as usize;
        if needed == 0 {
            return None;
        }
        if needed < buffer.len() {
            buffer.truncate(needed);
            return Some(buffer);
        }
        buffer = vec![0u16; needed + 1];
    }
}

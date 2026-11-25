//! Windows' interface font, and whether a face can set a language whole (`win/typeface.py`).
//!
//! Windows' UI font - the message font the Dashboard is drawn in - is Segoe UI on an English Windows and on one set
//! to any language Segoe UI covers, and an East Asian face on an East Asian one. Those have every letter of English
//! and of the other languages the product speaks, but not of every language: Malgun Gothic has no `ế`, `ї`, `ą` or
//! `ş`, Microsoft JhengHei UI no Cyrillic at all. A language whose letters Windows' UI font does not all have, and
//! Segoe UI does, is set in Segoe UI (`face_for`); a language with a script face of its own - Korean, Japanese,
//! Chinese, Thai - is set in the face Windows itself sets it in on a Windows set to that language (`language_face`).
//!
//! GDI is asked which glyphs a face has (`GetGlyphIndicesW`) once per face and text, and the answer is remembered.
//! Read, never written; nothing here draws, and nothing here fails: what cannot be asked is taken as whole.

use std::collections::HashMap;
use std::sync::Mutex;
use std::sync::OnceLock;

use windows::Win32::Foundation::HWND;
use windows::Win32::Graphics::Gdi::{
    CLIP_DEFAULT_PRECIS, CreateCompatibleDC, CreateFontW, DEFAULT_CHARSET, DeleteDC, DeleteObject,
    FONT_QUALITY, FW_NORMAL, GGI_MARK_NONEXISTING_GLYPHS, GetGlyphIndicesW, GetTextFaceW, HDC,
    HGDIOBJ, OUT_DEFAULT_PRECIS, SelectObject,
};
use windows::Win32::UI::WindowsAndMessaging::{
    NONCLIENTMETRICSW, SPI_GETNONCLIENTMETRICS, SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS,
    SystemParametersInfoW,
};
use windows::core::PCWSTR;

use crate::paths::{from_wide, wide};

/// The face every Windows has, with every letter of every language not set in a script face of its own.
pub const SEGOE: &str = "Segoe UI";
/// The face Windows sets each language with a script face of its own in, on a Windows set to that language.
pub const SCRIPT_FACES: [(&str, &str); 5] = [
    ("ko", "Malgun Gothic"),
    ("ja", "Yu Gothic UI"),
    ("zh-CN", "Microsoft YaHei UI"),
    ("zh-TW", "Microsoft JhengHei UI"),
    ("th", "Leelawadee UI"),
];
const NO_GLYPH: u16 = 0xFFFF;
const NO_SUCH_FACE: &str = "CodexAutoResume No Such Face";

/// Unicode general category Cf (format characters) in the Basic Multilingual Plane, the only ones `letters` meets.
const FORMAT_CHARACTERS: [(u32, u32); 14] = [
    (0x00AD, 0x00AD),
    (0x0600, 0x0605),
    (0x061C, 0x061C),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x180E, 0x180E),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x206F),
    (0xFEFF, 0xFEFF),
    (0xFFF9, 0xFFFB),
];

fn is_format(character: char) -> bool {
    let code = character as u32;
    FORMAT_CHARACTERS
        .iter()
        .any(|&(low, high)| (low..=high).contains(&code))
}

/// Every character of `texts` that is drawn - less white space and the control and format characters, which draw
/// nothing - once each, in order. Pure.
pub fn letters<S: AsRef<str>>(texts: &[S]) -> String {
    let mut found: Vec<char> = texts
        .iter()
        .flat_map(|text| text.as_ref().chars())
        .filter(|c| {
            !c.is_whitespace() && (*c as u32) <= 0xFFFF && !c.is_control() && !is_format(*c)
        })
        .collect();
    found.sort_unstable();
    found.dedup();
    found.into_iter().collect()
}

/// The face `text` is set in when Windows' UI font is `face`: `face` when it has every character of `text`, or when
/// Segoe UI lacks one too (a script with a face of its own); Segoe UI otherwise. `lacks` answers which characters a
/// face has no glyph for. Pure, given `lacks`.
pub fn face_for(face: &str, text: &str, lacks: &dyn Fn(&str, &str) -> String) -> String {
    if car_machine::pytext::strip(face).is_empty()
        || car_machine::pytext::strip(face).to_lowercase() == SEGOE.to_lowercase()
        || text.is_empty()
    {
        return face.to_string();
    }
    if !lacks(face, text).is_empty() && lacks(SEGOE, text).is_empty() {
        SEGOE.to_string()
    } else {
        face.to_string()
    }
}

/// The face the words of `locale`, whose letters are `text`, are set in when Windows' UI font is `face`: the
/// language's own script face where `installed` says Windows has it, and otherwise what `face_for` chooses.
pub fn language_face(
    locale: Option<&str>,
    face: &str,
    text: &str,
    lacks: &dyn Fn(&str, &str) -> String,
    installed: &dyn Fn(&str) -> bool,
) -> String {
    let own = locale.and_then(|locale| {
        SCRIPT_FACES
            .iter()
            .find(|(code, _)| *code == locale)
            .map(|(_, face)| *face)
    });
    match own {
        Some(own) if installed(own) => own.to_string(),
        _ => face_for(face, text, lacks),
    }
}

fn create_font(face: &str) -> windows::Win32::Graphics::Gdi::HFONT {
    let name = wide(face);
    // SAFETY: `name` is NUL-terminated and outlives the call.
    unsafe {
        CreateFontW(
            -12,
            0,
            0,
            0,
            FW_NORMAL.0 as i32,
            0,
            0,
            0,
            DEFAULT_CHARSET,
            OUT_DEFAULT_PRECIS,
            CLIP_DEFAULT_PRECIS,
            FONT_QUALITY(5),
            0,
            PCWSTR(name.as_ptr()),
        )
    }
}

fn realized(dc: HDC, face: &str) -> String {
    let font = create_font(face);
    if font.is_invalid() {
        return String::new();
    }
    // SAFETY: a font and a device context of our own.
    let previous = unsafe { SelectObject(dc, HGDIOBJ(font.0)) };
    let mut buffer = vec![0u16; 64];
    // SAFETY: a buffer of our own.
    unsafe { GetTextFaceW(dc, Some(&mut buffer)) };
    // SAFETY: restores what was selected, then frees the font.
    unsafe {
        SelectObject(dc, previous);
        let _ = DeleteObject(HGDIOBJ(font.0));
    }
    from_wide(&buffer)
}

fn installed_cache() -> &'static Mutex<HashMap<String, bool>> {
    static CACHE: OnceLock<Mutex<HashMap<String, bool>>> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

fn lacking_cache() -> &'static Mutex<HashMap<(String, String), String>> {
    static CACHE: OnceLock<Mutex<HashMap<(String, String), String>>> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

/// Whether GDI has the face `face` itself rather than a stand-in for it: the face it realizes for the name is the
/// name, or - a face Windows reports by its localized name - anything but what a face that does not exist is
/// realized as. False when Windows cannot be asked. Asked once per face.
pub fn installed(face: &str) -> bool {
    if car_machine::pytext::strip(face).is_empty() {
        return false;
    }
    let mut cache = installed_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some(known) = cache.get(face) {
        return *known;
    }
    // SAFETY: a device context of our own, deleted below.
    let dc = unsafe { CreateCompatibleDC(None) };
    let mut found = false;
    if !dc.is_invalid() {
        let stand_in = realized(dc, NO_SUCH_FACE);
        let real = realized(dc, face);
        found =
            !real.is_empty() && (real.to_lowercase() == face.to_lowercase() || real != stand_in);
        // SAFETY: the context created above.
        unsafe {
            let _ = DeleteDC(dc);
        }
    }
    cache.insert(face.to_string(), found);
    found
}

/// The characters of `text` the face `face` has no glyph of its own for - not one it would borrow through a font
/// link. "" when Windows cannot be asked. Asked once per face and text.
pub fn lacks(face: &str, text: &str) -> String {
    if car_machine::pytext::strip(face).is_empty() || text.is_empty() {
        return String::new();
    }
    let key = (face.to_string(), text.to_string());
    let mut cache = lacking_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some(known) = cache.get(&key) {
        return known.clone();
    }
    let mut missing = String::new();
    // SAFETY: a device context of our own, deleted below.
    let dc = unsafe { CreateCompatibleDC(None) };
    if !dc.is_invalid() {
        let font = create_font(face);
        if !font.is_invalid() {
            // GetGlyphIndicesW counts UTF-16 units, as the reference's `len(text)` does for the BMP text it is given.
            let units: Vec<u16> = text.encode_utf16().collect();
            let count = text.chars().count().min(units.len());
            let mut glyphs = vec![0u16; count];
            // SAFETY: a font and a device context of our own.
            let previous = unsafe { SelectObject(dc, HGDIOBJ(font.0)) };
            // SAFETY: buffers of our own, as long as the count passed.
            let answer = unsafe {
                GetGlyphIndicesW(
                    dc,
                    PCWSTR(units.as_ptr()),
                    count as i32,
                    glyphs.as_mut_ptr(),
                    GGI_MARK_NONEXISTING_GLYPHS,
                )
            };
            if answer != 0xFFFF_FFFF {
                missing = text
                    .chars()
                    .zip(glyphs.iter())
                    .filter(|(_, glyph)| **glyph == NO_GLYPH)
                    .map(|(c, _)| c)
                    .collect();
            }
            // SAFETY: restores what was selected, then frees the font.
            unsafe {
                SelectObject(dc, previous);
                let _ = DeleteObject(HGDIOBJ(font.0));
            }
        }
        // SAFETY: the context created above.
        unsafe {
            let _ = DeleteDC(dc);
        }
    }
    cache.insert(key, missing.clone());
    missing
}

/// The face of Windows' message font, or None when Windows cannot be asked: Segoe UI on an English Windows, Malgun
/// Gothic - by its Korean name - on a Korean one. Asked each time; nothing is cached.
pub fn ui_face() -> Option<String> {
    let mut metrics = NONCLIENTMETRICSW {
        cbSize: std::mem::size_of::<NONCLIENTMETRICSW>() as u32,
        ..Default::default()
    };
    // SAFETY: a structure of our own with its size set.
    unsafe {
        SystemParametersInfoW(
            SPI_GETNONCLIENTMETRICS,
            metrics.cbSize,
            Some(&mut metrics as *mut _ as *mut _),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        )
    }
    .ok()?;
    let face = from_wide(&metrics.lfMessageFont.lfFaceName);
    (!car_machine::pytext::strip(&face).is_empty()).then_some(face)
}

#[allow(dead_code)]
fn _hwnd(_: HWND) {}

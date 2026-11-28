//! Asking the settings window that is already open to come forward on a page (`win/handover.py`, issue #55).
//!
//! The window has no single-instance rule of its own, so every open from the notification-area icon, its popup or a
//! notification's button used to start one more window beside the one already on screen. Before one is started, a
//! window of this same program - the process whose image is the very file the open would start, whatever the
//! spelling of its path - is asked with `WM_COPYDATA`, under a mark of ours, to come to the front on that page; one
//! that takes it answers TAKEN and nothing is started. A window that does not answer TAKEN leaves the open as it
//! always was: a new window.
//!
//! Only top-level, visible, unowned Windows Forms windows of that program are asked, so the mark reaches nothing
//! else on the desktop. Nothing here fails: a question Windows cannot answer is a window not found.

use std::collections::HashMap;

use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::System::DataExchange::COPYDATASTRUCT;
use windows::Win32::UI::WindowsAndMessaging::{
    AllowSetForegroundWindow, EnumWindows, GW_OWNER, GetClassNameW, GetWindow,
    GetWindowThreadProcessId, IsWindowVisible, SMTO_ABORTIFHUNG, SendMessageTimeoutW, WM_COPYDATA,
};
use windows::core::BOOL;

use crate::paths::{from_wide, normcase, realpath};

/// What marks the message as an open request (`COPYDATASTRUCT.dwData`): "CARP".
pub const OPEN_REQUEST_MARK: usize = 0x4341_5250;
/// What a window that took one answers: "OPEN".
pub const OPEN_REQUEST_TAKEN: usize = 0x4F50_454E;
/// The class every Windows Forms window registers under, the settings window's among them.
pub const FORMS_CLASS: &str = "WindowsForms10.";
/// How long a window may take to answer: it answers at once and comes forward afterwards.
pub const ANSWER_MILLISECONDS: u32 = 3000;

/// One spelling of a file's path, whatever it was written as: long names, the real folder, one case.
pub fn spelled(path: &str) -> String {
    normcase(&realpath(path))
}

/// What an open request carries: the page ("" where it is) - and, for the popup's row menu, a second line, the row
/// and its dialog.
pub fn request_text(page: Option<&str>, row: Option<&str>) -> String {
    match row {
        None => page.unwrap_or("").to_string(),
        Some(row) => format!("{}\n{row}", page.unwrap_or("")),
    }
}

struct Search {
    name: String,
    target: String,
    images: HashMap<u32, bool>,
    found: Vec<(isize, u32)>,
}

unsafe extern "system" fn each(window: HWND, lparam: LPARAM) -> BOOL {
    // A callback Windows makes: a panic must not unwind into it (D15); a window that cannot be judged is skipped.
    let _ = std::panic::catch_unwind(|| judge(window, lparam));
    BOOL(1)
}

fn judge(window: HWND, lparam: LPARAM) {
    // SAFETY: the `Search` `windows_of` passed, alive for the whole enumeration.
    let search = unsafe { &mut *(lparam.0 as *mut Search) };
    // SAFETY: plain window queries.
    unsafe {
        if !IsWindowVisible(window).as_bool()
            || GetWindow(window, GW_OWNER).is_ok_and(|owner| !owner.0.is_null())
        {
            return;
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(window, Some(&mut pid));
        if pid == 0 {
            return;
        }
        let mut class = vec![0u16; 256];
        let length = GetClassNameW(window, &mut class);
        if length == 0 || !from_wide(&class).starts_with(FORMS_CLASS) {
            return;
        }
        let known = search.images.get(&pid).copied();
        let matches = match known {
            Some(matches) => matches,
            None => {
                let matches = crate::kernel::process_image(pid).is_some_and(|image| {
                    normcase(&basename(&image)) == search.name && spelled(&image) == search.target
                });
                search.images.insert(pid, matches);
                matches
            }
        };
        if matches {
            search.found.push((window.0 as isize, pid));
        }
    }
}

/// `os.path.basename(text)`: what follows the last `\` or `/` after the drive (`ntpath.split`), as the reference takes
/// a program's name - a path written with forward slashes included.
fn basename(text: &str) -> String {
    car_machine::winpath::split(text).1
}

/// `[(window, pid)]` for the top-level, visible, unowned Windows Forms windows of processes running `exe`. Sends
/// nothing to any of them.
pub fn windows_of(exe: &str) -> Vec<(isize, u32)> {
    let target = spelled(exe);
    let name = normcase(&basename(&target));
    let mut search = Search {
        name,
        target,
        images: HashMap::new(),
        found: Vec::new(),
    };
    // SAFETY: the callback only reads `search`, which outlives the call.
    unsafe {
        let _ = EnumWindows(Some(each), LPARAM(&mut search as *mut Search as isize));
    }
    search.found
}

/// Ask one window to come forward on `page` (None: where it is). True when it answered TAKEN.
pub fn ask(window: isize, pid: u32, text: &str) -> bool {
    let data: Vec<u8> = text
        .encode_utf16()
        .flat_map(|unit| unit.to_le_bytes())
        .collect();
    let mut buffer = data.clone();
    buffer.push(0);
    let copy = COPYDATASTRUCT {
        dwData: OPEN_REQUEST_MARK,
        cbData: data.len() as u32,
        lpData: if data.is_empty() {
            std::ptr::null_mut()
        } else {
            buffer.as_mut_ptr() as *mut _
        },
    };
    // This process may bring a window forward - a person just chose the item - and lets the window do it itself.
    // SAFETY: a plain permission call.
    unsafe {
        let _ = AllowSetForegroundWindow(pid);
    }
    let mut answer = 0usize;
    // SAFETY: `copy` and its buffer outlive the call.
    let sent = unsafe {
        SendMessageTimeoutW(
            HWND(window as *mut _),
            WM_COPYDATA,
            WPARAM(0),
            LPARAM(&copy as *const COPYDATASTRUCT as isize),
            SMTO_ABORTIFHUNG,
            ANSWER_MILLISECONDS,
            Some(&mut answer),
        )
    };
    sent.0 != 0 && answer == OPEN_REQUEST_TAKEN
}

/// True when a window of `exe` that is already open took the request to come forward on `page` - with `row`, also to
/// open that row's dialog.
pub fn hand_over(exe: &str, page: Option<&str>, row: Option<&str>) -> bool {
    let text = request_text(page, row);
    windows_of(exe)
        .into_iter()
        .any(|(window, pid)| ask(window, pid, &text))
}

#[cfg(test)]
mod tests {
    #[test]
    fn a_name_is_what_follows_the_last_separator_of_either_kind_after_the_drive() {
        for (path, name) in [
            (
                r"C:\a\b\CodexAutoResumeSettings.exe",
                "CodexAutoResumeSettings.exe",
            ),
            (
                "C:/a/b/CodexAutoResumeSettings.exe",
                "CodexAutoResumeSettings.exe",
            ),
            (r"C:\a/b\x.exe", "x.exe"),
            ("C:x.exe", "x.exe"),
            (r"C:\a\", ""),
            ("x.exe", "x.exe"),
        ] {
            assert_eq!(super::basename(path), name, "{path}");
        }
    }
}

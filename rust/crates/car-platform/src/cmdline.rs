//! Command lines as Windows reads them, and as Python's `subprocess.list2cmdline` writes them.
//!
//! `list2cmdline` is the reference's own rule (CPython 3.13, `subprocess.py`), written out here rather than
//! left to `std::process::Command`, whose quoting differs (it quotes the program always, and handles backslashes
//! before a quote its own way). A value the product registers - the sign-in Run value, a protocol handler, a
//! shortcut's arguments, an uninstall string - is compared by its text, so it is made by these.

use windows::Win32::Foundation::{HLOCAL, LocalFree};
use windows::Win32::UI::Shell::CommandLineToArgvW;
use windows::core::PCWSTR;

use crate::paths::{from_wide, pathlib_text, realpath, wide};

/// `subprocess.list2cmdline`: an argument is quoted only when it has a space or a tab or is empty; a run of
/// backslashes is doubled only before a quote - and, as CPython writes it, at the end of a quoted argument twice
/// over (the reference does that, and the line must equal it).
pub fn list2cmdline<S: AsRef<str>>(arguments: &[S]) -> String {
    let mut result = String::new();
    for (index, argument) in arguments.iter().enumerate() {
        let argument = argument.as_ref();
        if index > 0 {
            result.push(' ');
        }
        let need_quote = argument.contains(' ') || argument.contains('\t') || argument.is_empty();
        if need_quote {
            result.push('"');
        }
        let mut backslashes = 0usize;
        for character in argument.chars() {
            if character == '\\' {
                backslashes += 1;
            } else if character == '"' {
                result.push_str(&"\\".repeat(backslashes * 2));
                backslashes = 0;
                result.push_str("\\\"");
            } else {
                result.push_str(&"\\".repeat(backslashes));
                backslashes = 0;
                result.push(character);
            }
        }
        // CPython writes the trailing run once as it flushes the buffer and again before the closing quote.
        result.push_str(&"\\".repeat(backslashes));
        if need_quote {
            result.push_str(&"\\".repeat(backslashes));
            result.push('"');
        }
    }
    result
}

/// `startup.quote_argument`: one argument quoted always, by the documented CommandLineToArgvW rule - a run of
/// backslashes matters only immediately before a quote, where it is doubled (and at the end, before the closing one).
pub fn quote_argument(value: &str) -> String {
    let mut quoted = String::from("\"");
    let mut slashes = 0usize;
    for character in value.chars() {
        if character == '\\' {
            slashes += 1;
            continue;
        }
        if character == '"' {
            quoted.push_str(&"\\".repeat(slashes * 2 + 1));
            quoted.push('"');
        } else {
            quoted.push_str(&"\\".repeat(slashes));
            quoted.push(character);
        }
        slashes = 0;
    }
    quoted.push_str(&"\\".repeat(slashes * 2));
    quoted.push('"');
    quoted
}

/// Every argument through `quote_argument`, joined by one space (how the Run value and the handler are written).
pub fn quote_all<S: AsRef<str>>(arguments: &[S]) -> String {
    arguments
        .iter()
        .map(|argument| quote_argument(argument.as_ref()))
        .collect::<Vec<_>>()
        .join(" ")
}

/// `str(Path(path).resolve())`.
pub fn resolved(path: &str) -> String {
    realpath(&pathlib_text(path))
}

/// `startup.parse_command`: a registered command split the way Windows itself would (CommandLineToArgvW).
pub fn parse_command(command: &str) -> Vec<String> {
    let text = wide(command);
    let mut count = 0i32;
    // SAFETY: `text` is NUL-terminated and outlives the call; the array is freed with LocalFree below.
    let pointer = unsafe { CommandLineToArgvW(PCWSTR(text.as_ptr()), &mut count) };
    if pointer.is_null() {
        return Vec::new();
    }
    let mut found = Vec::with_capacity(count.max(0) as usize);
    for index in 0..count.max(0) as usize {
        // SAFETY: the API returned `count` NUL-terminated strings.
        let item = unsafe { *pointer.add(index) };
        let length = (0..)
            .take_while(|&offset| unsafe { *item.0.add(offset) } != 0)
            .count();
        // SAFETY: `length` units were just read from the string.
        found.push(from_wide(unsafe {
            std::slice::from_raw_parts(item.0, length)
        }));
    }
    // SAFETY: the one block CommandLineToArgvW allocated.
    unsafe {
        let _ = LocalFree(Some(HLOCAL(pointer as *mut _)));
    }
    found
}

/// `startup.script_index`: where the script is in an interpreter's command line - after the program and its options,
/// `-X` and `-W` each with its value.
pub fn script_index(arguments: &[String]) -> usize {
    let mut index = 1;
    while index < arguments.len() && arguments[index].starts_with('-') && arguments[index] != "-" {
        index += if arguments[index] == "-X" || arguments[index] == "-W" {
            2
        } else {
            1
        };
    }
    index
}

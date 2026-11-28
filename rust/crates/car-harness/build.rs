//! S6.4e: the Dashboard opener's own Rust, compiled a second time into the harness over a scratch world.
//!
//! `car-watcher/src/dashboard.rs` (`open_dashboard`, `open_chat`, `row_argument`) and `car-platform/src/handover.rs`
//! (`hand_over`, `windows_of`, `ask`, `request_text`, `spelled`) call Windows and start a process directly: they have no
//! seam a test can stand in at, and this wave edits no product crate. So this script copies the two files into OUT_DIR
//! with only their Windows and process-start names re-pointed at `src/opener.rs`'s `world` - every other line is the
//! product's own, compiled as it is - and `opener.rs` includes them. Each re-pointing is counted: a product file whose
//! lines moved fails this build rather than compiling something that is not the product. The harness does not depend
//! on the `windows` crate, so a Windows call left in either copy cannot compile: nothing here reaches a real window or
//! starts a process.

use std::fs;
use std::path::{Path, PathBuf};

/// Every `use windows::...;` statement (one line or several) cut out; the count is checked by the caller.
fn cut_windows_uses(text: &str) -> (String, usize) {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    let mut count = 0;
    while let Some(at) = rest.find("use windows::") {
        let line_start = rest[..at].rfind('\n').map_or(0, |n| n + 1);
        if !rest[line_start..at].trim().is_empty() {
            out.push_str(&rest[..at + 1]);
            rest = &rest[at + 1..];
            continue;
        }
        let end = rest[at..]
            .find(';')
            .map(|n| at + n + 1)
            .expect("a use statement ends");
        out.push_str(&rest[..line_start]);
        rest = rest[end..].strip_prefix('\n').unwrap_or(&rest[end..]);
        count += 1;
    }
    out.push_str(rest);
    (out, count)
}

/// `from` replaced by `to`, exactly `times` times, or the build fails naming the file.
fn replaced(text: &str, from: &str, to: &str, times: usize, file: &str) -> String {
    let found = text.matches(from).count();
    assert_eq!(
        found, times,
        "{file}: `{from}` is there {found} times, the opener harness expects {times}"
    );
    text.replace(from, to)
}

fn without_inner_docs(text: &str) -> String {
    text.lines()
        .filter(|line| !line.trim_start().starts_with("//!"))
        .map(|line| format!("{line}\n"))
        .collect()
}

fn main() {
    let manifest =
        PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("cargo sets CARGO_MANIFEST_DIR"));
    let crates = manifest.parent().expect("the crates folder").to_path_buf();
    let out = PathBuf::from(std::env::var("OUT_DIR").expect("cargo sets OUT_DIR"));
    let handover = crates.join("car-platform").join("src").join("handover.rs");
    let dashboard = crates.join("car-watcher").join("src").join("dashboard.rs");
    for each in [&handover, &dashboard] {
        println!("cargo:rerun-if-changed={}", each.display());
    }
    println!("cargo:rerun-if-changed=build.rs");

    // handover.rs: its four `use windows::...` statements become the world's names, `crate::kernel::process_image` the
    // world's image of a pid, `crate::paths` car-platform's own (normcase, realpath and from_wide are pure or read only
    // the scratch paths a case names).
    let text = read(&handover);
    let (text, uses) = cut_windows_uses(&without_inner_docs(&text));
    assert_eq!(
        uses, 4,
        "handover.rs: {uses} `use windows::` statements, the opener harness expects 4"
    );
    let text = replaced(
        &text,
        "use crate::paths::",
        "use car_platform::paths::",
        1,
        "handover.rs",
    );
    let text = replaced(
        &text,
        "crate::kernel::process_image(",
        "super::world::process_image(",
        1,
        "handover.rs",
    );
    let text = format!("use super::world::win::*;\n{text}");
    refuse_left(
        &text,
        "handover.rs",
        &[
            "windows::",
            "crate::",
            "car_platform::handover",
            "Command::",
        ],
    );
    write(&out.join("handover.rs"), &text);

    // dashboard.rs: its process start is the world's recorder and its hand-over the world's (the product's hand-over
    // copy above, or the case's answer).
    let text = without_inner_docs(&read(&dashboard));
    let text = replaced(
        &text,
        "use car_platform::spawn::{Spawn, SpawnError, SystemStarter};",
        "use super::world::{Spawn, SpawnError, SystemStarter};",
        1,
        "dashboard.rs",
    );
    let text = replaced(
        &text,
        "car_platform::handover::hand_over(",
        "super::world::hand_over(",
        1,
        "dashboard.rs",
    );
    refuse_left(
        &text,
        "dashboard.rs",
        &["car_platform::", "windows::", "Command::"],
    );
    write(&out.join("dashboard.rs"), &text);
}

fn refuse_left(text: &str, file: &str, names: &[&str]) {
    for name in names {
        assert!(
            !text.contains(name),
            "{file}: `{name}` is still in the opener harness's copy"
        );
    }
}

fn read(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_else(|error| panic!("{}: {error}", path.display()))
}

fn write(path: &Path, text: &str) {
    fs::write(path, text).unwrap_or_else(|error| panic!("{}: {error}", path.display()));
}

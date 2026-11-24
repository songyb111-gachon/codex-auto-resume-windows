//! Every golden file under tests/golden, read with serde_json (D5) and written back with our
//! writer, is the same bytes (D12: no golden is regenerated for the port).
//!
//! The wire goldens (`bridge/`, `mcp/`) are `json.dumps(document, ensure_ascii=False, indent=2)`
//! and a line feed (tests/wiregolden.py `_render`); the file directly in tests/golden,
//! defaults-v0.6.10.json, adds `sort_keys=True` (tests/test_defaults_golden.py `text`). Git
//! stores them with line feeds and checks them out with CRLF (.gitattributes), so a CRLF
//! checkout is read as the line feeds it holds.

use std::path::{Path, PathBuf};

use car_machine::json::{Options, from_slice, to_string};

fn golden_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/golden")
}

fn files(folder: &Path, found: &mut Vec<PathBuf>) {
    for entry in std::fs::read_dir(folder).expect("tests/golden is readable") {
        let path = entry.unwrap().path();
        if path.is_dir() {
            files(&path, found);
        } else {
            found.push(path);
        }
    }
}

/// The bytes Git holds: a CRLF checkout's line ends read back as line feeds.
fn as_stored(bytes: Vec<u8>) -> Vec<u8> {
    if !bytes.contains(&b'\r') {
        return bytes;
    }
    let mut stored = Vec::with_capacity(bytes.len());
    let mut at = 0;
    while at < bytes.len() {
        if bytes[at] == b'\r' {
            assert_eq!(
                bytes.get(at + 1),
                Some(&b'\n'),
                "a carriage return not before a line feed"
            );
            at += 1;
            continue;
        }
        stored.push(bytes[at]);
        at += 1;
    }
    stored
}

#[test]
fn every_golden_is_written_back_byte_for_byte() {
    let root = golden_root();
    let mut found = Vec::new();
    files(&root, &mut found);
    found.sort();
    let (mut wire, mut other, mut differ) = (0, 0, Vec::new());
    for path in &found {
        let relative = path.strip_prefix(&root).unwrap();
        let top_level = relative.components().count() == 1;
        let options = if top_level {
            other += 1;
            Options::wire().indent(2).sort_keys(true)
        } else {
            wire += 1;
            Options::wire().indent(2)
        };
        let stored = as_stored(std::fs::read(path).unwrap());
        let value =
            from_slice(&stored).unwrap_or_else(|error| panic!("{}: {error}", relative.display()));
        let written = to_string(&value, &options).unwrap() + "\n";
        if written.as_bytes() != stored.as_slice() {
            differ.push(relative.display().to_string());
        }
    }
    eprintln!(
        "json goldens: {} files ({wire} wire, {other} other), {} differ",
        found.len(),
        differ.len()
    );
    assert!(
        wire >= 74 && other >= 1,
        "the goldens were not all found under {}",
        root.display()
    );
    assert!(differ.is_empty(), "written back differently: {differ:?}");
}

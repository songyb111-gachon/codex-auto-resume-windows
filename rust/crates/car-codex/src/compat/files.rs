//! `compat/files.py`: the registry's files - the bundled baseline, the product version, and atomic writes.

use std::io::Write;
use std::os::windows::fs::MetadataExt;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

use car_machine::compat::model::{Document, DocumentError, MAX_DOCUMENT_BYTES, parse_document};
use car_machine::json::{Options, Value, to_string};

use super::standing::document_standing;
use crate::system::System;

pub const REFRESH_TIMEOUT_SECONDS: f64 = 150.0;
/// What `bootstrap.ps1 -Compatibility` answers with, beside its one `compatibility:` line.
pub const REFRESH_EXIT: [(&str, i64); 3] = [("refreshed", 0), ("unavailable", 12), ("refused", 13)];
pub const REFRESH_ANSWERS: [&str; 5] = [
    "refreshed",
    "refused",
    "unavailable",
    "incomplete",
    "failed",
];

/// `_read_capped(path, limit)`: the file's bytes, refusing a link or anything over `limit` before reading it.
pub fn read_capped(path: &str, limit: usize) -> Result<Vec<u8>, DocumentError> {
    let unreadable = || DocumentError::new("unreadable");
    let target = Path::new(path);
    if car_platform::links::is_symlink(target) || !target.is_file() {
        return Err(unreadable());
    }
    let size = std::fs::metadata(target).map_err(|_| unreadable())?.len();
    if size > limit as u64 {
        return Err(DocumentError::new("too_large"));
    }
    let data = std::fs::read(target).map_err(|_| unreadable())?;
    if data.len() > limit {
        return Err(DocumentError::new("too_large"));
    }
    Ok(data)
}

/// `_stamp(path)`: (size, mtime_ns), or None where the file cannot be asked about.
pub fn stamp(path: &str) -> Option<(u64, u64)> {
    let found = std::fs::metadata(path).ok()?;
    Some((
        found.len(),
        crate::transport::mtime_ns(found.last_write_time()),
    ))
}

/// `_signature(path)`: the stamp as a list, or None.
pub fn signature(path: &str) -> Value {
    stamp(path).map_or(Value::Null, |(size, written)| {
        Value::Array(vec![Value::from(size as i64), Value::from(written as i64)])
    })
}

static TEMPORARY: AtomicU64 = AtomicU64::new(0);

/// `write_json_atomic(path, value, prefix)`: a temporary file beside it, flushed to disk, then replaced whole.
pub fn write_json_atomic(path: &str, value: &Value, prefix: &str) -> std::io::Result<()> {
    let target = Path::new(path);
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = to_string(value, &Options::wire().separators(",", ":").sort_keys(true))
        .map_err(|_| std::io::Error::other("the value cannot be written"))?;
    let parent = target.parent().unwrap_or(Path::new("."));
    let (mut file, temporary) = loop {
        let name = format!(
            "{prefix}{}{}.json.tmp",
            std::process::id(),
            TEMPORARY.fetch_add(1, Ordering::SeqCst)
        );
        let candidate = parent.join(name);
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => break (file, candidate),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error),
        }
    };
    let written = (|| {
        file.write_all(text.as_bytes())?;
        file.flush()?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&temporary, target)
    })();
    if written.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    written
}

/// `path_digest(path)`: SHA-256 of the resolved, case-folded path, or None where it cannot be resolved.
pub fn path_digest(system: &dyn System, path: &str) -> Option<String> {
    let resolved = system.resolve(&car_config::winpath::path_str(path))?;
    let folded = car_platform::paths::normcase(&resolved);
    Some(car_platform::paths::sha256_hex(folded.as_bytes()))
}

/// `product_version()` of a version text: MAJOR.MINOR.PATCH of this product's own version, or "unknown".
pub fn product_version(version: &str) -> String {
    let chars: Vec<char> = version.chars().collect();
    let mut at = 0;
    let number = |at: &mut usize| -> bool {
        let start = *at;
        while *at < chars.len() && *at - start < 6 && chars[*at].is_ascii_digit() {
            *at += 1;
        }
        *at > start && !(chars.get(*at).is_some_and(char::is_ascii_digit))
    };
    let release = (|| {
        for index in 0..3 {
            if index > 0 {
                if chars.get(at) != Some(&'.') {
                    return None;
                }
                at += 1;
            }
            if !number(&mut at) {
                return None;
            }
        }
        Some(at)
    })();
    let Some(end) = release else {
        return "unknown".into();
    };
    let rest: String = chars[end..].iter().collect();
    let suffix_fine = rest.is_empty()
        || ["-alpha", "-beta"].iter().any(|stage| {
            rest.strip_prefix(stage).is_some_and(|tail| {
                tail.is_empty()
                    || tail.strip_prefix('.').is_some_and(|number| {
                        let all = !number.is_empty() && number.chars().all(|c| c.is_ascii_digit());
                        all && match number.len() {
                            1 => ('2'..='9').contains(&number.chars().next().unwrap_or('0')),
                            2 | 3 => !number.starts_with('0'),
                            _ => false,
                        }
                    })
            })
        });
    if suffix_fine {
        chars[..end].iter().collect()
    } else {
        "unknown".into()
    }
}

/// `load_bundled(path, product=, now=)`: (the document or None, one of `BUNDLED_STATES`).
pub fn load_bundled(path: &str, product: &str) -> (Option<Document>, &'static str) {
    if !Path::new(path).is_file() {
        return (None, "missing");
    }
    let document = match read_capped(path, MAX_DOCUMENT_BYTES)
        .and_then(|raw| parse_document(&raw, MAX_DOCUMENT_BYTES))
    {
        Ok(document) => document,
        Err(_) => return (None, "rejected"),
    };
    if document_standing(&document, product, None, 0.0, true) == "ok" {
        (Some(document), "ok")
    } else {
        (None, "rejected")
    }
}

/// `bundled_verified_versions()`: the versions the bundled baseline verifies, where it is in force.
pub fn bundled_verified_versions(path: &str, product: &str) -> Vec<String> {
    match load_bundled(path, product) {
        (document, "ok") => super::standing::verified_versions(document.as_ref()),
        _ => Vec::new(),
    }
}

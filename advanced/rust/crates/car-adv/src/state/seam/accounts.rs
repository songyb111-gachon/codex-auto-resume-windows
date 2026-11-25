//! SEAM (seat S7.1a): what the saved accounts (`profiles.py`) read of `codex/authfile.py`, `codex/account.py` and
//! `codex/swap.py` (seat S7.2) and of Windows (DPAPI, the named mutex: car-platform's).
//!
//! The pure halves are written here as the tag has them - `authfile.check`, `authfile.confined`, the plain part of
//! `authfile.own_folder` and `authfile.write_atomic`, `account.mask` - so the profiles can be held to the reference
//! now; what needs another seat or Windows is the [`Host`] a caller hands in: the seal and its opening (DPAPI for the
//! current user), the saved accounts' lock, the folder's private access list, `authfile.sweep` and `swap.unwind`.

use std::path::{Path, PathBuf};

use car_machine::json::Value;

/// `authfile.LIMIT`.
pub const LIMIT: usize = 64 * 1024;
/// `account.HIDDEN`.
pub const HIDDEN: &str = "\u{2022}\u{2022}\u{2022}";

/// What a [`Host`] refuses or fails with, as the reference's exception class and sentence.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Failure(pub String);

/// What the saved accounts need of other seats and of Windows.
pub trait Host: Send + Sync {
    /// DPAPI `protect` for the current user.
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, Failure>;
    /// DPAPI `unprotect`.
    fn open(&self, blob: &[u8]) -> Result<Vec<u8>, Failure>;
    /// The named mutex `account-switch:<folder>` taken within `seconds`, or a failure.
    fn lock(&self, directory: &Path, seconds: f64) -> Result<Box<dyn std::any::Any>, Failure>;
    /// `authfile.private(directory)`: the folder's access list made the current user's alone.
    fn private(&self, directory: &Path);
    /// `authfile.sweep(directory, codex_home, stale=0)`.
    fn sweep(&self, directory: &Path, codex_home: Option<&Path>);
    /// `swap.unwind(store, codex_home)`: whether nothing a switch left waits on the saved accounts any more. Given
    /// the intent as the store read it.
    fn unwind(&self, intent: &Value, codex_home: Option<&Path>) -> bool;
    /// `secrets.token_hex(count)`.
    fn token(&self, count: usize) -> String;
}

/// `authfile.check(data)`: `data` if it is a sign-in file's shape - a JSON object, not empty, of 1 to LIMIT bytes.
pub fn check(data: &[u8]) -> Result<Vec<u8>, Failure> {
    if data.is_empty() || data.len() > LIMIT {
        return Err(Failure("not a sign-in file's size".into()));
    }
    let Ok(text) = std::str::from_utf8(data) else {
        return Err(Failure("not a sign-in file".into()));
    };
    match car_machine::json::from_str(text) {
        Ok(Value::Object(map)) if !map.is_empty() => Ok(data.to_vec()),
        _ => Err(Failure("not a sign-in file".into())),
    }
}

/// `authfile.confined(directory)`: no link or junction, and it resolves where it stands under its own parent.
pub fn confined(directory: &Path) -> bool {
    let text = directory.to_string_lossy();
    if car_config::paths::is_link(&text) {
        return false;
    }
    let absolute = |path: &Path| -> Option<PathBuf> { std::path::absolute(path).ok() };
    let resolved = match std::fs::canonicalize(directory) {
        Ok(found) => strip_verbatim(found),
        Err(_) => match absolute(directory) {
            Some(found) => found,
            None => return false,
        },
    };
    let parent = directory
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_default();
    let parent = match std::fs::canonicalize(&parent) {
        Ok(found) => strip_verbatim(found),
        Err(_) => absolute(&parent).unwrap_or(parent),
    };
    let same_parent = resolved.parent().is_some_and(|found| {
        found.to_string_lossy().to_lowercase() == parent.to_string_lossy().to_lowercase()
    });
    let name = |path: &Path| {
        path.file_name()
            .map(|name| name.to_string_lossy().to_lowercase())
    };
    same_parent && name(&resolved) == name(directory)
}

fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy().into_owned();
    match text.strip_prefix(r"\\?\") {
        Some(rest) if !rest.starts_with("UNC\\") => PathBuf::from(rest),
        Some(rest) => PathBuf::from(format!(r"\\{}", &rest[4..])),
        None => path,
    }
}

/// `authfile.own_folder(directory)`: made where it is not, refused where it is a link, the provenance marker
/// written once and the folder then made private.
pub fn own_folder(host: &dyn Host, directory: &Path) -> Result<(), Failure> {
    std::fs::create_dir_all(directory).map_err(|error| Failure(error.to_string()))?;
    if !confined(directory) {
        return Err(Failure("the saved accounts folder is a link".into()));
    }
    let marker = directory.join(car_config::paths::OWNER_MARKER);
    if !marker.exists() {
        let _ = std::fs::write(&marker, crate::state::session::owner_text().as_bytes());
        host.private(directory);
    }
    Ok(())
}

/// `authfile.write_atomic(path, data)`: written beside it, then moved over it.
pub fn write_atomic(host: &dyn Host, path: &Path, data: &[u8]) -> Result<(), Failure> {
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temporary = path.with_file_name(format!("{name}.car-{}", host.token(4)));
    let outcome = (|| -> std::io::Result<()> {
        use std::io::Write;
        let mut handle = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        handle.write_all(data)?;
        handle.flush()?;
        handle.sync_all()?;
        drop(handle);
        std::fs::rename(&temporary, path)
    })();
    let _ = std::fs::remove_file(&temporary);
    outcome.map_err(|error| Failure(error.to_string()))
}

/// `account.mask(email)`: the address as the card shows it, or None for anything that is not one.
pub fn mask(email: &Value) -> Option<String> {
    let text = match email {
        Value::Str(text) => text.as_str()?,
        _ => return None,
    };
    if text.matches('@').count() != 1 {
        return None;
    }
    let stripped = car_machine::pytext::strip(text);
    let (local, domain) = stripped.split_once('@')?;
    if local.is_empty() || domain.is_empty() || domain.starts_with('.') || domain.ends_with('.') {
        return None;
    }
    let labels: Vec<&str> = domain.split('.').collect();
    let first = |text: &str| text.chars().next().map(String::from).unwrap_or_default();
    let mut shown = format!("{}{HIDDEN}@{}{HIDDEN}", first(local), first(labels[0]));
    if labels.len() > 1 {
        shown.push('.');
        shown.push_str(labels[labels.len() - 1]);
    }
    Some(shown)
}

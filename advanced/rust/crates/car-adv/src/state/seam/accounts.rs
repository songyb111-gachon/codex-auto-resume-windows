//! What the saved accounts (`profiles.py`) read of `codex/authfile.py`, `codex/account.py` and `codex/swap.py` and of
//! Windows (S7.1a's seam, filled by seat S7.2b).
//!
//! The pure halves are written here as the tag has them - `authfile.check`, `authfile.confined`, the plain part of
//! `authfile.own_folder` and `authfile.write_atomic`, `account.mask` - and `codex::authfile` builds on them. What
//! needs Windows or the switch is the [`Host`] a caller hands in: the seal and its opening (DPAPI for the current
//! user), the saved accounts' lock, the folder's private access list, `authfile.sweep` and `swap.unwind`. [`Windows`]
//! is the product's own (S7.2b): `win::dpapi`, car-platform's named mutex `account-switch:<folder>`, the private
//! access list, `codex::authfile::sweep` and `codex::swap::unwind` over the live world; [`live_profiles`] the saved
//! accounts of one product home with it. The diffs hand a stand-in seal instead (S7.1a's, never a real blob).

use std::path::{Path, PathBuf};

use car_machine::json::{Str, Value};

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
    match car_machine::compat::loads(text) {
        Ok(Value::Object(map)) if !map.is_empty() => Ok(data.to_vec()),
        Err(car_machine::compat::LoadsError::Recursion) => Err(Failure(RECURSION.into())),
        _ => Err(Failure("not a sign-in file".into())),
    }
}

/// The sentence of a [`Failure`] that is Python's RecursionError (a document nested past the interpreter's limit),
/// which no `except` of the reference's catches.
pub const RECURSION: &str = "maximum recursion depth exceeded";

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
        // `open(temporary, "xb")`: shared as Python shares (car-machine's pyfile).
        let mut handle = car_machine::pyfile::options()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        handle.write_all(data)?;
        handle.flush()?;
        handle.sync_all()?;
        drop(handle);
        // `os.replace(temporary, path)`: MoveFileExW alone (car-platform), never std's POSIX retry.
        car_platform::files::replace(&temporary, path)
    })();
    let _ = std::fs::remove_file(&temporary);
    outcome.map_err(|error| Failure(error.to_string()))
}

/// `account.mask(email)`: the address as the card shows it, or None for anything that is not one - by code points,
/// so half a surrogate pair is kept as Python keeps it.
pub fn mask(email: &Value) -> Option<Str> {
    let Value::Str(text) = email else {
        return None;
    };
    let points: Vec<u32> = text.code_points().collect();
    let at = u32::from(b'@');
    if points.iter().filter(|point| **point == at).count() != 1 {
        return None;
    }
    let space = |point: &u32| char::from_u32(*point).is_some_and(car_machine::pytext::is_space);
    let start = points
        .iter()
        .position(|point| !space(point))
        .unwrap_or(points.len());
    let end = points
        .iter()
        .rposition(|point| !space(point))
        .map_or(start, |index| index + 1);
    let stripped = &points[start..end.max(start)];
    let split = stripped.iter().position(|point| *point == at)?;
    let (local, domain) = (&stripped[..split], &stripped[split + 1..]);
    let dot = u32::from(b'.');
    if local.is_empty() || domain.is_empty() || domain[0] == dot || domain[domain.len() - 1] == dot
    {
        return None;
    }
    let labels: Vec<&[u32]> = domain.split(|point| *point == dot).collect();
    let mut shown: Vec<u32> = vec![local[0]];
    shown.extend(HIDDEN.chars().map(u32::from));
    shown.push(at);
    shown.extend(labels[0].iter().take(1));
    shown.extend(HIDDEN.chars().map(u32::from));
    if labels.len() > 1 {
        shown.push(dot);
        shown.extend(labels[labels.len() - 1]);
    }
    Str::from_code_points(shown)
}

// ------------------------------------------------------------------------------------------------ the product's host
/// `os.path.normcase(str(Path(directory).absolute()))`: joined to the working folder where relative, pathlib's
/// separators, then lower case.
pub fn mutex_folder(directory: &Path) -> String {
    let joined = if directory.is_absolute() {
        directory.to_path_buf()
    } else {
        std::env::current_dir().unwrap_or_default().join(directory)
    };
    let text = joined.to_string_lossy().replace('/', "\\");
    let mut parts: Vec<&str> = Vec::new();
    for (index, part) in text.split('\\').enumerate() {
        if index > 0 && (part.is_empty() || part == ".") {
            continue;
        }
        parts.push(part);
    }
    let mut kept = parts.join("\\");
    if kept.ends_with(':') {
        kept.push('\\');
    }
    kept.to_lowercase()
}

/// The named mutex held for as long as this lives (`held.__exit__` on drop).
struct Held(car_platform::sync::Mutex);

impl Drop for Held {
    fn drop(&mut self) {
        self.0.exit();
    }
}

/// The product's saved accounts' host for the folder `directory`: DPAPI with the product's label, the named mutex,
/// the private access list, and the switch's own sweep and put-back.
#[derive(Clone)]
pub struct Windows {
    pub directory: PathBuf,
}

impl Host for Windows {
    fn seal(&self, data: &[u8]) -> Result<Vec<u8>, Failure> {
        crate::win::dpapi::protect(data).map_err(|error| Failure(format!("{error:?}")))
    }
    fn open(&self, blob: &[u8]) -> Result<Vec<u8>, Failure> {
        crate::win::dpapi::unprotect(blob).map_err(|error| Failure(format!("{error:?}")))
    }
    fn lock(&self, directory: &Path, seconds: f64) -> Result<Box<dyn std::any::Any>, Failure> {
        let name = format!("account-switch:{}", mutex_folder(directory));
        let mut mutex = car_platform::sync::Mutex::new(&name, seconds)
            .map_err(|error| Failure(error.0.to_owned()))?;
        mutex.enter().map_err(|error| Failure(error.0.to_owned()))?;
        Ok(Box::new(Held(mutex)))
    }
    fn private(&self, directory: &Path) {
        crate::codex::authfile::private_dacl(directory);
    }
    fn sweep(&self, directory: &Path, codex_home: Option<&Path>) {
        crate::codex::authfile::sweep(
            directory,
            codex_home,
            crate::state::session::wall_clock(),
            0.0,
        );
    }
    fn unwind(&self, _intent: &Value, codex_home: Option<&Path>) -> bool {
        let store = crate::profiles::Profiles {
            directory: self.directory.clone(),
            host: std::sync::Arc::new(self.clone()),
            clock: Box::new(crate::state::session::wall_clock),
        };
        let live = crate::codex::swap::Live::new();
        // A put-back that raised what the reference lets go on is a put-back that waits: nothing is deleted.
        crate::codex::swap::unwind(&live.world(), &store, codex_home).unwrap_or(false)
    }
    fn token(&self, count: usize) -> String {
        use super::Tokens;
        crate::credentials::SystemTokens.hex(count)
    }
}

/// `Profiles(home)`: the saved accounts of the product home `home`, with the product's own host and the wall clock.
pub fn live_profiles(home: &Path) -> crate::profiles::Profiles {
    let directory = home.join(crate::profiles::FOLDER);
    crate::profiles::Profiles {
        directory: directory.clone(),
        host: std::sync::Arc::new(Windows { directory }),
        clock: Box::new(crate::state::session::wall_clock),
    }
}

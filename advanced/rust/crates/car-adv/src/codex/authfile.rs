//! `codex/authfile.py` (seat S7.2b): Codex's sign-in file, for account_auto_switch alone.
//!
//! Every other part of the product never reads Codex's sign-in file, a token or a cookie (standard B11). This
//! capability departs from that, and only it may: it copies `auth.json` into a sealed profile (`profiles`) and puts
//! another profile's copy in its place. The bytes are never parsed for a token, logged, journalled or sent anywhere;
//! the one check made on them is that they are a JSON object of a bounded size, so a damaged copy is never written into
//! Codex's home.
//!
//! Codex keeps its sign-in in a file only where `cli_auth_credentials_store` (config.toml) is unset or "file"; anything
//! else, or no file there, fails closed ([`usable`] says why). The config is read as the reference reads it: UTF-8 in
//! text mode (universal newlines), then `tomllib` ([`toml`], every rule of Python 3.14's parser).
//!
//! What a test replaces in the reference is a seam here: the random names (`secrets.token_hex`, [`Tokens`]), the private
//! access list (`_PRIVATE`, a function handed in) and the pause before a second removal (a sleep handed in).

mod toml;

use std::path::{Path, PathBuf};

use crate::state::seam::Tokens;
pub use crate::state::seam::accounts::{LIMIT, RECURSION};

pub const NAME: &str = "auth.json";
pub const CONFIG: &str = "config.toml";
pub const KEY: &str = "cli_auth_credentials_store";
pub const USABLE: &str = "usable";
pub const NOT_FILE: &str = "not_file";
pub const NO_FILE: &str = "no_file";
pub const UNREADABLE: &str = "unreadable";
pub const MODES: [&str; 4] = ["file", "keyring", "auto", "ephemeral"];
pub const SCRATCH_STALE: f64 = 1200.0;
pub const TEMPORARY_STALE: f64 = 60.0;
/// The Python frames on the stack when `store_mode` enters `tomllib.loads` from a direct call (the diffs' script: the
/// module, the case's function and `store_mode` itself). The reference's recursion limit counts the caller's frames
/// too, so how deeply nested a config may be before it is a RecursionError depends on who asked (AUDIT-v0628).
pub const FRAMES: usize = 3;

/// What the reference raises, by its class (`AuthFileError` for a sign-in file that cannot be read, is not one Codex
/// writes, or could not be put in place; `OSError` for any other operating system error; `ValueError`,
/// `UnicodeDecodeError`, `RecursionError` and the rest for what goes on through every `except OSError`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Fault {
    pub class: String,
    pub message: String,
}

impl Fault {
    pub fn new(class: &str, message: &str) -> Fault {
        Fault {
            class: class.to_owned(),
            message: message.to_owned(),
        }
    }

    pub fn auth(message: &str) -> Fault {
        Fault::new("AuthFileError", message)
    }

    pub fn os(error: &std::io::Error) -> Fault {
        Fault::new("OSError", &error.to_string())
    }

    /// Whether `except OSError` catches it: OSError and its subclasses (AuthFileError, ProfileError, Locked,
    /// PutBackWaits, DpapiError and the operating system's own).
    pub fn is_os(&self) -> bool {
        matches!(
            self.class.as_str(),
            "OSError"
                | "AuthFileError"
                | "ProfileError"
                | "Locked"
                | "PutBackWaits"
                | "DpapiError"
                | "FileNotFoundError"
                | "FileExistsError"
                | "PermissionError"
                | "IsADirectoryError"
                | "NotADirectoryError"
        )
    }

    /// `except ProfileError`: ProfileError and its subclasses.
    pub fn is_profile(&self) -> bool {
        matches!(
            self.class.as_str(),
            "ProfileError" | "Locked" | "PutBackWaits"
        )
    }
}

impl From<crate::profiles::ProfileError> for Fault {
    fn from(error: crate::profiles::ProfileError) -> Fault {
        Fault::new(error.class, &error.message)
    }
}

impl std::fmt::Display for Fault {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.class, self.message)
    }
}

/// Whether the C runtime's `open` says ENOENT for this error (FileNotFoundError): what `_dosmaperr` maps to it.
fn not_found(error: &std::io::Error) -> bool {
    matches!(
        error.raw_os_error(),
        Some(2 | 3 | 15 | 18 | 53 | 67 | 161 | 206)
    )
}

/// `path.read_text(encoding="utf-8")`: the bytes decoded strictly, then the universal newlines of text mode.
fn read_text(path: &Path) -> Result<String, std::io::Error> {
    let bytes = std::fs::read(path)?;
    match String::from_utf8(bytes) {
        Ok(text) => Ok(text.replace("\r\n", "\n").replace('\r', "\n")),
        Err(_) => Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "UnicodeDecodeError",
        )),
    }
}

/// `store_mode(codex_home)`: the `cli_auth_credentials_store` Codex's config names - "file" where it names none - or
/// None where the config cannot be read or names a mode Codex does not have. A config that is not UTF-8 raises
/// UnicodeDecodeError and one nested past Python's recursion limit RecursionError, as the reference lets both go on.
pub fn store_mode(codex_home: &Path) -> Result<Option<&'static str>, Fault> {
    store_mode_at(codex_home, FRAMES + 1)
}

/// [`store_mode`] for a caller `frames` Python frames deep, `store_mode` itself counted.
pub fn store_mode_at(codex_home: &Path, frames: usize) -> Result<Option<&'static str>, Fault> {
    let text = match read_text(&codex_home.join(CONFIG)) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::InvalidData => {
            return Err(Fault::new(
                "UnicodeDecodeError",
                "'utf-8' codec can't decode the config",
            ));
        }
        Err(error) if not_found(&error) => return Ok(Some("file")),
        Err(_) => return Ok(None),
    };
    match toml::top_level(&text, KEY, frames) {
        Ok(None) => Ok(Some("file")),
        Ok(Some(toml::Found::Str(mode))) => Ok(MODES.into_iter().find(|each| *each == mode)),
        Ok(Some(toml::Found::Other)) => Ok(None),
        Err(toml::Error::Decode) => Ok(None),
        Err(toml::Error::Recursion) => Err(Fault::new(
            "RecursionError",
            "maximum recursion depth exceeded",
        )),
        Err(toml::Error::Index) => Err(Fault::new("IndexError", "list index out of range")),
    }
}

/// `usable(codex_home)`: USABLE where the sign-in at `codex_home` is a file this capability may copy and replace;
/// otherwise why not.
pub fn usable(codex_home: &Path) -> Result<&'static str, Fault> {
    Ok(match store_mode_at(codex_home, FRAMES + 2)? {
        None => UNREADABLE,
        Some("file") => {
            if codex_home.join(NAME).is_file() {
                USABLE
            } else {
                NO_FILE
            }
        }
        Some(_) => NOT_FILE,
    })
}

/// `check(data)`: `data` if it is a sign-in file's shape - a JSON object of at most LIMIT bytes - else AuthFileError
/// (and a document nested past Python's limit the RecursionError the reference does not catch).
pub fn check(data: &[u8]) -> Result<Vec<u8>, Fault> {
    crate::state::seam::accounts::check(data).map_err(|failure| {
        if failure.0 == RECURSION {
            Fault::new("RecursionError", RECURSION)
        } else {
            Fault::auth(&failure.0)
        }
    })
}

/// `read(codex_home)`: the sign-in file's bytes at `codex_home`, checked.
pub fn read(codex_home: &Path) -> Result<Vec<u8>, Fault> {
    match std::fs::read(codex_home.join(NAME)) {
        Ok(bytes) => check(&bytes),
        Err(_) => Err(Fault::auth("the sign-in file cannot be read")),
    }
}

/// `write_atomic(path, data)`: `data` at `path` whole or not at all - written beside it, flushed, then moved over it
/// (one rename on one volume) - and the temporary taken away whatever happened.
pub fn write_atomic(path: &Path, data: &[u8], tokens: &dyn Tokens) -> Result<(), Fault> {
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let temporary = path.with_file_name(format!("{name}.car-{}", tokens.hex(4)));
    let outcome = (|| -> std::io::Result<()> {
        use std::io::Write;
        let mut handle = car_machine::pyfile::options()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        handle.write_all(data)?;
        handle.flush()?;
        handle.sync_all()?;
        drop(handle);
        car_platform::files::replace(&temporary, path)
    })();
    let _ = std::fs::remove_file(&temporary);
    outcome.map_err(|error| Fault::os(&error))
}

/// `replace(codex_home, data)`: `data` (checked) put in place as the sign-in file at `codex_home`, atomically.
pub fn replace(codex_home: &Path, data: &[u8], tokens: &dyn Tokens) -> Result<(), Fault> {
    let checked = check(data)?;
    write_atomic(&codex_home.join(NAME), &checked, tokens).map_err(|fault| {
        if fault.is_os() {
            Fault::auth("the sign-in file could not be put in place")
        } else {
            fault
        }
    })
}

/// `confined(directory)`: no link or junction, and it resolves where it stands, under its own parent.
pub fn confined(directory: &Path) -> bool {
    crate::state::seam::accounts::confined(directory)
}

/// `own_folder(directory)`: made where it is not, refused where it is a link, the provenance marker written once and
/// the folder then made private (`private`, the reference's `private(directory)`).
pub fn own_folder(directory: &Path, private: &dyn Fn(&Path) -> bool) -> Result<(), Fault> {
    std::fs::create_dir_all(directory).map_err(|error| Fault::os(&error))?;
    if !confined(directory) {
        return Err(Fault::auth("the saved accounts folder is a link"));
    }
    let marker = directory.join(car_config::paths::OWNER_MARKER);
    if !marker.exists() {
        let _ = std::fs::write(&marker, crate::state::session::owner_text().as_bytes());
        private(directory);
    }
    Ok(())
}

/// `_private_dacl(directory)`: the folder's access list made the current Windows user's alone (car-platform), where
/// that user's SID reads as one; whether Windows took it. No test calls it on a folder that is not its own.
pub fn private_dacl(directory: &Path) -> bool {
    let Some(sid) = car_platform::kernel::user_sid() else {
        return false;
    };
    let shaped = sid
        .strip_prefix("S-1-")
        .is_some_and(|rest| rest.bytes().all(|b| b.is_ascii_digit() || b == b'-'))
        && sid.len() > 4;
    shaped && car_platform::restart::private_folder(directory, &sid)
}

fn is_link(path: &Path) -> bool {
    car_config::paths::is_link(&path.to_string_lossy())
}

fn remove(entry: &Path) -> std::io::Result<()> {
    if is_link(entry) {
        // A link is taken away as a link, never entered.
        if std::fs::remove_file(entry).is_err() {
            std::fs::remove_dir(entry)?;
        }
        return Ok(());
    }
    if entry.is_dir() {
        for child in std::fs::read_dir(entry)? {
            remove(&child?.path())?;
        }
        return std::fs::remove_dir(entry);
    }
    match std::fs::remove_file(entry) {
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
            let mut permissions = std::fs::symlink_metadata(entry)?.permissions();
            #[allow(clippy::permissions_set_readonly_false)]
            permissions.set_readonly(false);
            std::fs::set_permissions(entry, permissions)?;
            std::fs::remove_file(entry)
        }
        other => other,
    }
}

fn lexists(path: &Path) -> bool {
    std::fs::symlink_metadata(path).is_ok()
}

/// `remove_tree(path)`: a folder this capability made, and everything in it, removed - no link or junction in it
/// followed. Whether it is gone.
pub fn remove_tree(path: &Path) -> bool {
    let _ = remove(path);
    !lexists(path)
}

fn age(path: &Path, now: f64) -> f64 {
    match std::fs::symlink_metadata(path).and_then(|found| found.modified()) {
        Ok(modified) => {
            let seconds = match modified.duration_since(std::time::UNIX_EPOCH) {
                Ok(after) => after.as_secs_f64(),
                Err(before) => -before.duration().as_secs_f64(),
            };
            now - seconds
        }
        Err(_) => -1.0,
    }
}

fn hex_tail(text: &str, count: usize) -> bool {
    text.len() == count
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `_SCRATCH.match(name)`.
pub fn scratch_name(name: &str) -> bool {
    name.strip_prefix("scratch-")
        .is_some_and(|rest| hex_tail(rest, 12))
}

/// `_TEMPORARY.match(name)`: `^.+\.car-[0-9a-f]{8}$` (no line break in a file name).
pub fn temporary_name(name: &str) -> bool {
    name.len() > 13
        && name
            .rfind(".car-")
            .is_some_and(|at| at > 0 && hex_tail(&name[at + 5..], 8))
        && !name.contains('\n')
}

/// `_BESIDE.match(name)`.
pub fn beside_name(name: &str) -> bool {
    name.strip_prefix("auth.json.car-")
        .is_some_and(|rest| hex_tail(rest, 8))
}

/// `sweep(directory, codex_home, now=, stale=)`: what a kill or a held file left of this capability's plain sign-in
/// files, taken away - scratch homes in the saved accounts folder older than `stale` seconds, its temporaries, and the
/// temporary beside Codex's own sign-in file - only names this capability makes, only directly in those folders,
/// nothing that is a link (nor through one). (removed, failed).
pub fn sweep(directory: &Path, codex_home: Option<&Path>, now: f64, stale: f64) -> (i64, i64) {
    let (mut removed, mut failed) = (0, 0);
    let mut places = vec![(directory, true)];
    if let Some(home) = codex_home {
        places.push((home, false));
    }
    for (folder, accounts) in places {
        if is_link(folder) || !folder.is_dir() {
            continue;
        }
        let Ok(listed) = std::fs::read_dir(folder) else {
            continue;
        };
        let Ok(mut entries) = listed
            .map(|entry| entry.map(|entry| entry.path()))
            .collect::<std::io::Result<Vec<PathBuf>>>()
        else {
            continue;
        };
        entries.sort_by_key(|path| path.to_string_lossy().to_lowercase());
        for entry in entries {
            let name = entry
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_default();
            if is_link(&entry) {
                continue;
            }
            let gone = if accounts && scratch_name(&name) && entry.is_dir() {
                if age(&entry, now) < stale {
                    continue;
                }
                remove_tree(&entry)
            } else if (if accounts {
                temporary_name(&name)
            } else {
                beside_name(&name)
            }) && entry.is_file()
            {
                if age(&entry, now) < stale.min(TEMPORARY_STALE) {
                    continue;
                }
                let _ = std::fs::remove_file(&entry);
                !lexists(&entry)
            } else {
                continue;
            };
            if gone {
                removed += 1;
            } else {
                failed += 1;
            }
        }
    }
    (removed, failed)
}

/// `Scratch(root, data)`: a private Codex home made for one read on a saved account (or Codex's own sign-in for a new
/// one), under the product's own accounts folder, whose config keeps the sign-in in a file and which holds `data` as
/// its sign-in file where given. On leaving, the sign-in file there is kept in `after` and the folder removed whatever
/// happened; `removed` says whether it went.
#[derive(Debug, Default)]
pub struct Scratch {
    pub root: PathBuf,
    pub data: Option<Vec<u8>>,
    pub path: Option<PathBuf>,
    pub after: Option<Vec<u8>>,
    pub removed: Option<bool>,
}

impl Scratch {
    pub fn new(root: &Path, data: Option<Vec<u8>>) -> Scratch {
        Scratch {
            root: root.to_path_buf(),
            data,
            ..Scratch::default()
        }
    }

    /// `__enter__`: the home made; its path.
    pub fn enter(
        &mut self,
        tokens: &dyn Tokens,
        private: &dyn Fn(&Path) -> bool,
    ) -> Result<PathBuf, Fault> {
        own_folder(&self.root, private)?;
        let path = self.root.join(format!("scratch-{}", tokens.hex(6)));
        self.path = Some(path.clone());
        std::fs::create_dir(&path).map_err(|error| Fault::os(&error))?;
        if !confined(&path) {
            return Err(Fault::auth("a scratch home is a link"));
        }
        // write_text in text mode: the line break is Windows'.
        std::fs::write(path.join(CONFIG), format!("{KEY} = \"file\"\r\n"))
            .map_err(|error| Fault::os(&error))?;
        if let Some(data) = &self.data {
            write_atomic(&path.join(NAME), &check(data)?, tokens)?;
        }
        Ok(path)
    }

    /// `__exit__`: the sign-in file kept in `after`, the home removed (once more after `pause` where it stayed).
    pub fn exit(&mut self, pause: &dyn Fn(f64)) -> Result<(), Fault> {
        let path = self.path.clone().unwrap_or_default();
        self.after = match read(&path) {
            Ok(found) => Some(found),
            Err(fault) if fault.class == "AuthFileError" => None,
            Err(fault) => return Err(fault),
        };
        let mut removed = remove_tree(&path);
        if !removed {
            pause(0.2); // a child that has just ended may still hold a file
            removed = remove_tree(&path);
        }
        self.removed = Some(removed);
        Ok(())
    }

    /// `with Scratch(...) as home: body(home)`: what `body` answered, or what was raised - `__exit__`'s own raise first.
    pub fn with<T>(
        &mut self,
        tokens: &dyn Tokens,
        private: &dyn Fn(&Path) -> bool,
        pause: &dyn Fn(f64),
        body: impl FnOnce(&Path) -> Result<T, Fault>,
    ) -> Result<T, Fault> {
        let home = self.enter(tokens, private)?;
        let answer = body(&home);
        self.exit(pause)?;
        answer
    }
}

//! The names of the objects the product makes from a home or a user (`win/sync.py`, `win/homelock.py`).
//!
//! A name is a prefix and the SHA-256 of `normcase(str(Path.home().resolve()))`, a tag and the caller's own name
//! (the state folder), so two installs, two accounts or two sessions never share one, and a Rust watcher and a
//! Python watcher of the same home share exactly one. `tests/rustdiff/platform_diffs.py` holds every name here to
//! the reference's for fifty homes.

use std::path::PathBuf;

use crate::paths::{home_identity, identity_text, pathlib_text, sha256_hex};

/// The installer's mutex (`win/homelock.py` INSTALL_LOCK): held by an installation, repair or update while it runs.
pub const INSTALL_LOCK: &str = "Local\\CodexAutoResume.Install";

const MUTEX_PREFIX: &str = "Local\\codex-auto-resume-";
const STOP_PREFIX: &str = "Local\\codex-auto-resume-stop-";
const WAKE_PREFIX: &str = "Local\\codex-auto-resume-wake-";
const DEMO_PREFIX: &str = "Local\\codex-auto-resume-demo-";

/// The four named objects of one watcher: its mutex and the stop, wake and demo events.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WatcherNames {
    pub mutex: String,
    pub stop: String,
    pub wake: String,
    pub demo: String,
}

fn named(prefix: &str, home: &str, tag: &str, name: &str) -> String {
    format!(
        "{prefix}{}",
        sha256_hex(format!("{home}{tag}{name}").as_bytes())
    )
}

/// `Mutex(name).name` for a home already spelled (`paths::home_identity`).
pub fn mutex_name_for(home: &str, name: &str) -> String {
    named(MUTEX_PREFIX, home, "\0", name)
}

/// `StopEvent(name).name`.
pub fn stop_name_for(home: &str, name: &str) -> String {
    named(STOP_PREFIX, home, "::stop::", name)
}

/// `WakeEvent(name).name`.
pub fn wake_name_for(home: &str, name: &str) -> String {
    named(WAKE_PREFIX, home, "::wake::", name)
}

/// `DemoEvent(name).name`.
pub fn demo_name_for(home: &str, name: &str) -> String {
    named(DEMO_PREFIX, home, "::demo::", name)
}

/// All four, for the home the environment names (`Path.home()`); None where no home can be told.
pub fn watcher_names(name: &str) -> Option<WatcherNames> {
    let home = home_identity()?;
    Some(WatcherNames {
        mutex: mutex_name_for(&home, name),
        stop: stop_name_for(&home, name),
        wake: wake_name_for(&home, name),
        demo: demo_name_for(&home, name),
    })
}

/// The folder a home lock's files are in: `base`, else `%LOCALAPPDATA%` (or the home) `\codex-auto-resume\homes`.
pub fn lock_root(base: Option<&str>) -> Option<String> {
    if let Some(base) = base.filter(|b| !b.is_empty()) {
        return Some(pathlib_text(base));
    }
    let local = match std::env::var("LOCALAPPDATA") {
        Ok(value) if !value.is_empty() => pathlib_text(&value),
        _ => crate::paths::home_text()?,
    };
    Some(pathlib_text(&format!("{local}\\codex-auto-resume\\homes")))
}

/// The file `HomeLock(codex_home, base).path` names: the SHA-256 of the home's resolved path, `.lock`.
pub fn home_lock_path(codex_home: &str, base: Option<&str>) -> Option<PathBuf> {
    let root = lock_root(base)?;
    let resolved = identity_text(codex_home);
    Some(PathBuf::from(format!(
        "{root}\\{}.lock",
        sha256_hex(resolved.as_bytes())
    )))
}

/// The second lock file of a home, named by the folder's identity (`win/folderid.py`): `id-<identity>.lock`.
pub fn identity_lock_path(root: &str, identity: &str) -> PathBuf {
    PathBuf::from(format!("{root}\\id-{identity}.lock"))
}

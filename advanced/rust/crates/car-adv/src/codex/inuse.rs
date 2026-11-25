//! `codex/inuse.py` as the v0.6.26 final has it: the Codex an installation drives, for the capabilities' own sessions and
//! reads (seat S7.2c).
//!
//! The watcher tells its plug the Codex it found and checked ([`tell`], core's `Plug.codex`), and that is the one used
//! here; a process that holds no watcher (the Dashboard's bridge) finds Codex as the watcher does with no arguments
//! ([`backend`]). The final added what a capability's own pairing look saw the app main run instead of the told engine
//! ([`saw`]) - kept only where the look was made on the told codex.exe, forgotten whenever the watcher tells a Codex - and
//! core reads it back through the plug ([`elsewhere`], `AdvancedPlug.served_elsewhere`, S7.2a's) to decide alone whether
//! one is taken up.
//!
//! Module state is per process, as the reference's: `{an installation's home: (codex.exe, Codex home)}` and `{home: the
//! paths seen elsewhere}`, the home compared as pathlib compares a Windows path (lower-cased).

use std::collections::{BTreeSet, HashMap};
use std::path::Path;
use std::sync::{Arc, Mutex, PoisonError};

use car_codex::system::System;
use car_codex::transport::Backend;
use car_config::Os;
use car_machine::json::Value;
use car_machine::winpath::{Env, path_str};

/// What the watcher told and what was seen elsewhere, per installation.
#[derive(Default)]
struct Held {
    told: HashMap<String, (String, String)>,
    elsewhere: HashMap<String, BTreeSet<String>>,
}

static HELD: Mutex<Option<Held>> = Mutex::new(None);

fn with<T>(act: impl FnOnce(&mut Held) -> T) -> T {
    let mut held = HELD.lock().unwrap_or_else(PoisonError::into_inner);
    act(held.get_or_insert_with(Held::default))
}

/// `_key(paths)`: `Path(paths.home)`, as a dict compares it.
fn key(home: &str) -> String {
    path_str(home).to_lowercase()
}

/// `os.path.normcase(str(path))`.
fn normcase(path: &str) -> String {
    car_platform::paths::normcase(path)
}

/// `tell(paths, codex_exe, codex_home)`: what the watcher of the installation at `home` drives; what was seen elsewhere
/// is forgotten. `Err` where `Path.resolve()` raises (the Windows error number).
pub fn tell(home: &str, codex_exe: &str, codex_home: &str, os: &Os) -> Result<(), i32> {
    let exe = path_str(&os.resolve(codex_exe)?);
    let where_ = path_str(&os.resolve(codex_home)?);
    with(|held| {
        held.told.insert(key(home), (exe, where_));
        held.elsewhere.remove(&key(home));
    });
    Ok(())
}

/// `told(paths)`: (codex.exe, Codex home) as the watcher told them for `home`, or none.
pub fn told(home: Option<&str>) -> Option<(String, String)> {
    let home = home?;
    with(|held| held.told.get(&key(home)).cloned())
}

/// `forget(paths)`: what was told for `home` forgotten, and what was seen elsewhere.
pub fn forget(home: &str) {
    with(|held| {
        held.told.remove(&key(home));
        held.elsewhere.remove(&key(home));
    });
}

/// What `saw` reads of a backend a look was made through: its codex.exe and what its pairing look found the app main
/// running instead (`served_elsewhere`).
pub trait Looked {
    fn codex_exe(&self) -> Option<String>;
    fn served_elsewhere(&self) -> Vec<String>;
}

impl Looked for Backend {
    fn codex_exe(&self) -> Option<String> {
        Some(self.codex_exe.clone())
    }
    fn served_elsewhere(&self) -> Vec<String> {
        self.served_elsewhere.clone()
    }
}

/// `saw(paths, backend)`: the look's `served_elsewhere`, kept only where it was made on the told codex.exe (the paths
/// compared as `os.path.normcase` makes them), and nothing where that look found none.
pub fn saw(home: Option<&str>, backend: &dyn Looked) {
    let Some(found) = told(home) else {
        return;
    };
    let Some(exe) = backend.codex_exe() else {
        return;
    };
    if normcase(&exe) != normcase(&found.0) {
        return;
    }
    let seen: BTreeSet<String> = backend.served_elsewhere().into_iter().collect();
    if let Some(home) = home {
        with(|held| held.elsewhere.insert(key(home), seen));
    }
}

/// `elsewhere(paths)`: the paths `saw` last kept for `home`, or nothing.
pub fn elsewhere(home: Option<&str>) -> BTreeSet<String> {
    let Some(home) = home else {
        return BTreeSet::new();
    };
    with(|held| held.elsewhere.get(&key(home)).cloned().unwrap_or_default())
}

/// `home(paths)`: the Codex home - the watcher's, as told; else CODEX_HOME's, as the watcher finds it (`config.codex_home`,
/// whose exception's name is the `Err`).
pub fn home(installation: Option<&str>, env: Env, os: &Os) -> Result<String, &'static str> {
    match told(installation) {
        Some((_, found)) => Ok(found),
        None => car_config::codex::codex_home(env, os),
    }
}

/// `_pinned(paths)`: the codex.exe the `codex_exe` setting pins, or none.
pub fn pinned(settings_file: Option<&Path>) -> Option<String> {
    let file = settings_file?;
    let settings = car_policy::settings::load(&car_codex::system::PolicyOs, file).ok()?;
    match settings.get("codex_exe") {
        Some(Value::Str(text)) if !text.is_empty() => text.as_str().map(str::to_owned),
        _ => None,
    }
}

/// Why `backend` raised: discovery's refusal (core's ConfigError, its text) or the engine check's (an AdapterError code).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum BackendError {
    Config(String),
    Check(String),
    Adapter(String),
    Raised(&'static str),
}

/// What `backend` asks of the outside world.
pub struct Discovery<'a> {
    pub system: Arc<dyn System>,
    pub env: Env<'a>,
    pub os: &'a Os,
    /// `config.version()`.
    pub product_version: String,
}

fn adapter(error: car_codex::errors::Error) -> String {
    match error {
        car_codex::errors::Error::Adapter(code) => code.to_owned(),
        other => format!("{other:?}"),
    }
}

/// `backend(paths)`: core's Backend for the Codex the installation drives, checked: the one its watcher told, else the
/// one the watcher would find (the `codex_exe` setting or CODEX_AR_CODEX_EXE, discovery otherwise, the app's own engine
/// where several pass).
pub fn backend(
    installation: Option<&str>,
    settings_file: Option<&Path>,
    world: &Discovery,
) -> Result<Backend, BackendError> {
    let (exe, where_) = match told(installation) {
        Some(found) => found,
        None => {
            let where_ =
                car_config::codex::codex_home(world.env, world.os).map_err(BackendError::Raised)?;
            let pinned = installation.and(pinned(settings_file));
            let system = Arc::clone(&world.system);
            let compatible = |path: &str| -> Result<(), String> {
                let mut made = Backend::new(
                    Arc::clone(&system),
                    &where_,
                    path,
                    false,
                    &world.product_version,
                );
                made.compatible().map_err(adapter)
            };
            let running = || car_codex::pairing::app_engines(world.system.as_ref()).ok();
            let exe = car_config::codex::discover_codex_exe(
                pinned.as_deref(),
                &compatible,
                Some(&running),
                false,
                true,
                world.env,
                world.os,
            )
            .map_err(|error| match error {
                car_config::codex::DiscoverError::Config(error) => BackendError::Config(error.0),
                car_config::codex::DiscoverError::Check(why) => BackendError::Check(why),
            })?;
            (exe, where_)
        }
    };
    let mut made = Backend::new(
        Arc::clone(&world.system),
        &where_,
        &exe,
        false,
        &world.product_version,
    );
    made.compatible()
        .map_err(|error| BackendError::Adapter(adapter(error)))?;
    Ok(made)
}

/// Forget every installation: a new process, for tests and the harness.
pub fn reset() {
    *HELD.lock().unwrap_or_else(PoisonError::into_inner) = None;
}

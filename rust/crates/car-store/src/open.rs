//! Opening the state for one command: one set of steps, and the policy each caller chooses
//! (src/codex_auto_resume/openstate.py; tests/test_layers.py already plans it as `store/open.py`).
//!
//! Cut C3 (PLAN 1.3): the Python module calls `windows.install_in_progress()` and holds `windows.Mutex`;
//! here both come in as a [`Windows`] the caller passes, so car-store reaches no Windows API and the
//! policy -> codex edge is gone. car-platform (S3.1) gives the real one; a test gives a stand-in.

use std::any::Any;
use std::path::Path;
use std::sync::Arc;

use crate::errors::{Error, Kind, Result};
use crate::legacy::LegacyStore;
use crate::session::{Clock, Links, Options, Store, wall_clock};

/// `POLICIES`.
pub const POLICIES: &[&str] = &["never", "if_reducing", "always"];

/// `UPGRADE_PENDING`.
pub const UPGRADE_PENDING: &str = "Upgrade pending: an older watcher still owns the state. Use Stop watcher, then Start watcher, or sign out and back in.";

/// `windows.AdapterError`: the mutex is held by another process, or could not be made.
#[derive(Debug)]
pub struct AdapterError(pub String);

/// What `open_state` asks of Windows (cut C3).
pub trait Windows {
    /// `windows.install_in_progress()`: Some(true) while an installation holds its lock, Some(false) when
    /// none does, None when the lock cannot be looked at.
    fn install_in_progress(&self) -> Option<bool>;

    /// `windows.Mutex(state_dir, timeout=0.0)` entered: a guard holding the watcher's single-instance mutex
    /// until it is dropped, or the AdapterError of a mutex another process holds.
    fn watcher_mutex(&self, state_dir: &Path) -> std::result::Result<Box<dyn Any>, AdapterError>;

    /// `Path.is_symlink()` (car-platform's `links::is_symlink`): the store refuses a state folder that is one.
    fn links(&self) -> Arc<dyn Links>;
}

/// What `open_state` gives: the store, or under an older watcher the older watcher's own.
pub enum Opened {
    Store(Store),
    Legacy(LegacyStore),
}

/// `open_state`'s keywords.
pub struct OpenState<'a> {
    pub legacy: &'a str,
    pub reducing: bool,
    pub check: bool,
    /// `upgrade_failed`: the caller's own error for a failed upgrade.
    pub upgrade_failed: Option<&'a dyn Fn(Error) -> Error>,
    pub hold_while_installing: bool,
    /// `superseded`: whether another version was installed under this process since it started.
    pub superseded: Option<&'a dyn Fn() -> bool>,
    /// A fixed clock for the stores it opens, where Python's run at `time.time` (the differential harness pins
    /// the time a migration journals); None is the wall clock.
    pub clock: Option<f64>,
}

impl Default for OpenState<'_> {
    fn default() -> Self {
        OpenState {
            legacy: "never",
            reducing: false,
            check: false,
            upgrade_failed: None,
            hold_while_installing: false,
            superseded: None,
            clock: None,
        }
    }
}

/// `open_state(state_dir, ...)`: a Store, or - under an older watcher - what `legacy` allows.
pub fn open_state(
    state_dir: &Path,
    windows: &dyn Windows,
    options: &OpenState<'_>,
) -> Result<Opened> {
    if !POLICIES.contains(&options.legacy) {
        return Err(Error::Python(
            "ValueError",
            format!("legacy must be one of {}", POLICIES.join(", ")),
        ));
    }
    let clock = || -> Clock {
        match options.clock {
            Some(fixed) => Box::new(move || fixed),
            None => Box::new(wall_clock),
        }
    };
    match Store::open_with(
        state_dir,
        Options {
            migrate: false,
            check: options.check,
            clock: clock(),
            links: windows.links(),
        },
    ) {
        Ok(store) => return Ok(Opened::Store(store)),
        Err(error) if error.kind() == Some(Kind::UpgradePending) => {}
        Err(error) => return Err(error),
    }
    let held = (options.hold_while_installing && windows.install_in_progress() != Some(false))
        || options.superseded.is_some_and(|superseded| superseded());
    if !held {
        // An AdapterError: an older watcher holds the state.
        if let Ok(guard) = windows.watcher_mutex(state_dir) {
            let opened = Store::open_with(
                state_dir,
                Options {
                    migrate: true,
                    check: true,
                    clock: clock(),
                    links: windows.links(),
                },
            );
            drop(guard);
            match opened {
                Ok(store) => return Ok(Opened::Store(store)),
                Err(error) if error.is_store() => {
                    return Err(match options.upgrade_failed {
                        Some(upgrade_failed) => upgrade_failed(error),
                        None => error,
                    });
                }
                Err(error) => return Err(error),
            }
        }
    }
    if options.legacy == "always" {
        return LegacyStore::open(state_dir, &*windows.links()).map(Opened::Legacy);
    }
    if options.legacy == "if_reducing"
        && options.reducing
        && let Ok(legacy) = LegacyStore::open(state_dir, &*windows.links())
    {
        return Ok(Opened::Legacy(legacy));
    }
    Err(Error::Store(Kind::UpgradePending, UPGRADE_PENDING.into()))
}

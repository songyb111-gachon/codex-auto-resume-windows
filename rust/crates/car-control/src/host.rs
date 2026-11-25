//! What the control layer asks of the machine it runs on - the clock, Windows, the registry's policy keys, the
//! Codex home, the compatibility report - as one trait, so that the layer holds no Windows call of its own (D3)
//! and a test can stand in for any answer.
//!
//! [`SystemHost`] is the real one, over car-platform and car-config. The differential harness wraps it and
//! stands in for what the reference's golden installation stands in for (the watcher's mutex, the Run key, the
//! policy keys, the clock): see `car-harness/src/bridge.rs`.
//!
//! Every method says which Python call it answers.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_machine::json::{Map, Str, Value};
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;
use car_store::open::{AdapterError, Windows};

/// `ownprocess`'s reading of this sign-in and this start of Windows, for `how_it_ended`.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Boot {
    pub sign_in: Option<String>,
    pub booted_at: Option<f64>,
}

/// The outside world, as the control layer asks it.
pub trait Host: Windows + Send + Sync {
    /// `time.time()`.
    fn now(&self) -> f64;
    /// A clock the stores this layer opens run at, where a caller pins it (the differential harness); None is
    /// the wall clock, as `Store(...)` has it.
    fn store_clock(&self) -> Option<f64> {
        None
    }
    /// The settings' questions about paths (`os.path.*`, `Path.resolve()`), asked of Windows.
    fn os(&self) -> Arc<dyn Os + Send + Sync>;
    /// `config.version()`: the plugin manifest's version, as this process read it.
    fn version(&self) -> String;
    /// `config.codex_home()`.
    fn codex_home(&self) -> String;
    /// `control.policy.managed_policy()`: the administrator's policy keys in force (`managed.NONE` for a copy that
    /// is not installed).
    fn managed(&self) -> Managed;
    /// `os.environ.get(name)`.
    fn environ(&self, name: &str) -> Option<String>;
    /// `l10n._windows_preferred()`: the user's preferred UI languages, Windows' own.
    fn windows_languages(&self) -> Vec<String>;
    /// `Control.watcher_running()`: True, False, or None where the probe was unavailable.
    fn watcher_running(&self, state_dir: &Path) -> Option<bool>;
    /// `startup.current_value()`: the Run value; None for none, and for a registry that could not be read.
    fn startup_value(&self) -> Option<String>;
    /// `ownprocess.sign_in()` and `ownprocess.booted_at()`.
    fn boot(&self) -> Boot;
    /// `compatio.reader_view(paths, settings=...)`: the Compatibility card's view (S3.3's, behind this seam).
    fn compat_view(&self, state_dir: &Path, settings: &Map) -> Value;
    /// `acl.state_access(path)`: owner_only, shared or unknown.
    fn state_access(&self, path: &Path) -> String;
    /// `kernel.host_app(pid, started_by=...)`: `{"state", "family", "app"}`.
    fn host_app(&self, pid: Option<u32>, started_by: Option<f64>) -> Value;
    /// `edition.name().value` of the code this process runs.
    fn edition_name(&self) -> String;
    /// `control.state.superseded()`: the files this process was started from now say another version than it runs.
    fn superseded(&self) -> bool;
    /// `config.installed_home() is not None`: this copy runs from an installation, not a checkout.
    fn installed(&self) -> bool;
    /// `userenv.codex_home()`: the account's `CODEX_HOME` as Windows holds it for the programs it starts.
    fn account_codex_home(&self) -> Option<String>;
    /// `homefind.app_homes()`: where the Codex app says it has run.
    fn app_homes(&self) -> Vec<String>;
    /// `time.localtime` and `time.mktime`: the zone a reset time is written in.
    fn local_clock(&self) -> Box<dyn car_policy::classify::clock::LocalClock> {
        Box::new(crate::localclock::UtcClock)
    }
    /// `os.path.islink`, the way the store and the settings ask it.
    fn is_symlink(&self, path: &Path) -> bool;
    /// `win.sync.Mutex(name, timeout)` entered: a guard that holds it until dropped, or why it could not be had.
    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError>;
}

/// A held named mutex, released when dropped.
pub struct Held(car_platform::sync::Mutex);

impl Drop for Held {
    fn drop(&mut self) {
        self.0.exit();
    }
}

/// The real host: this machine.
pub struct SystemHost {
    pub project_root: String,
    pub links: Arc<dyn car_store::session::Links>,
    os: Arc<dyn Os + Send + Sync>,
}

/// `Os` over car-platform: the one link probe, LCMapStringEx, GetFullPathNameW and `realpath`.
pub struct PlatformOs;

impl Os for PlatformOs {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }

    fn is_junction(&self, path: &Path) -> bool {
        car_platform::links::reparse_tag(path) == Some(car_platform::links::MOUNT_POINT_TAG)
    }

    fn normcase(&self, text: &[u16]) -> Vec<u16> {
        car_platform::widepath::normcase(text)
    }

    fn abspath(&self, text: &[u16]) -> Vec<u16> {
        let normal = car_policy::settings::os::normpath(text);
        car_platform::widepath::full_path(&normal).unwrap_or(normal)
    }

    fn resolve(&self, text: &[u16]) -> Result<Vec<u16>, &'static str> {
        match String::from_utf16(text) {
            Ok(plain) => Ok(car_platform::paths::realpath(&plain)
                .encode_utf16()
                .collect()),
            Err(_) => Ok(text.to_vec()),
        }
    }
}

/// The link probe for the store.
#[derive(Debug)]
pub struct Probe;

impl car_store::session::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

impl SystemHost {
    pub fn new(project_root: &str) -> SystemHost {
        SystemHost {
            project_root: project_root.to_owned(),
            links: Arc::new(Probe),
            os: Arc::new(PlatformOs),
        }
    }
}

impl Windows for SystemHost {
    fn install_in_progress(&self) -> Option<bool> {
        Some(car_platform::homelock::install_in_progress())
    }

    fn watcher_mutex(
        &self,
        state_dir: &Path,
    ) -> std::result::Result<Box<dyn std::any::Any>, AdapterError> {
        let mut mutex = car_platform::sync::Mutex::new(&state_dir.to_string_lossy(), 0.0)
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        mutex
            .enter()
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        Ok(Box::new(Held(mutex)))
    }

    fn links(&self) -> Arc<dyn car_store::session::Links> {
        Arc::clone(&self.links)
    }
}

impl Host for SystemHost {
    fn now(&self) -> f64 {
        car_store::session::wall_clock()
    }

    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        Arc::clone(&self.os)
    }

    fn version(&self) -> String {
        car_config::codex::version(&self.project_root, &mut |_| {})
    }

    fn codex_home(&self) -> String {
        let env = |name: &str| std::env::var(name).ok();
        car_config::codex::codex_home(&env, &car_config::Os::here(false, Arc::new(Probe)))
            .unwrap_or_default()
    }

    fn managed(&self) -> Managed {
        // Only an installed copy asks Windows (`control/policy.managed_policy`); the registry reader that makes
        // the places is car-platform's, wired in by the entry point that knows it is installed.
        Managed::default()
    }

    fn environ(&self, name: &str) -> Option<String> {
        std::env::var(name).ok()
    }

    fn windows_languages(&self) -> Vec<String> {
        Vec::new()
    }

    fn watcher_running(&self, state_dir: &Path) -> Option<bool> {
        let mut mutex = car_platform::sync::Mutex::new(&state_dir.to_string_lossy(), 0.0).ok()?;
        match mutex.enter() {
            Ok(()) => {
                mutex.exit();
                Some(false)
            }
            Err(error) if error.0 == "mutex_busy" => Some(true),
            Err(_) => None,
        }
    }

    fn startup_value(&self) -> Option<String> {
        None
    }

    fn boot(&self) -> Boot {
        Boot {
            sign_in: car_platform::ownprocess::sign_in(),
            booted_at: car_platform::ownprocess::booted_at(),
        }
    }

    fn compat_view(&self, _state_dir: &Path, _settings: &Map) -> Value {
        Value::Null
    }

    fn state_access(&self, path: &Path) -> String {
        car_platform::acl::state_access(path).as_str().to_owned()
    }

    fn host_app(&self, pid: Option<u32>, started_by: Option<f64>) -> Value {
        let verdict = car_platform::kernel::host_app(pid, started_by);
        let mut map = Map::new();
        map.insert(Str::from("state"), Value::from(verdict.state));
        map.insert(Str::from("family"), Value::from(verdict.family));
        map.insert(Str::from("app"), Value::from(verdict.app));
        Value::Object(map)
    }

    fn edition_name(&self) -> String {
        "standard".to_owned()
    }

    fn superseded(&self) -> bool {
        false
    }

    fn installed(&self) -> bool {
        car_config::paths::installed_home(&self.project_root).is_some()
    }

    fn account_codex_home(&self) -> Option<String> {
        car_platform::registry_reads::codex_home(
            &car_platform::registry::WinRegistry::current_user(),
        )
    }

    fn app_homes(&self) -> Vec<String> {
        crate::homefind::app_homes(std::env::var("LOCALAPPDATA").ok().as_deref())
    }

    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }

    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError> {
        let mut mutex = car_platform::sync::Mutex::new(name, timeout)
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        mutex
            .enter()
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        Ok(Box::new(Held(mutex)))
    }
}

/// A path as the control layer holds it.
pub fn path_of(text: &str) -> PathBuf {
    PathBuf::from(text)
}

impl car_config::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

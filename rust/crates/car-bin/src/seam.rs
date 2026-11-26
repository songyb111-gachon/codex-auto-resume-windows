//! What the command line asks of the machine beyond car-control's Host, behind one trait, so that a test stands in
//! for every answer and nothing here writes the registry, a shortcut or the real installation (brief rule 3).
//!
//! Two kinds of method:
//!
//! * **the registrations** (`startup.register_aumid`, `install_protocol`, `shortcut.*`, `addremove.*`): car-platform's,
//!   which [`SystemOutside`] calls over `WinRegistry::current_user()` and PowerShell;
//! * **the engine and the watcher** (`App.backend()`, the app's pairing, `compatio.engine_word`, the Restart Manager,
//!   the history's readability, `App.run`, the notifier, opening the Dashboard): S3.3's (car-codex `codex/pairing`,
//!   `compat/*`), P6's (car-watcher `runtime/app.py`) and car-surface's, not ported yet. [`SystemOutside`] refuses each
//!   as the reference meets a failure of that call, and the integration hands the real ones in (GROUNDWORK, S5.2).
//!
//! Every method says which Python call it answers.

use std::path::Path;

use car_machine::json::Value;

/// What a call raised: the Python class and `str(exc)`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Raised {
    pub class: String,
    pub message: String,
}

impl Raised {
    pub fn new(class: &str, message: impl Into<String>) -> Raised {
        Raised {
            class: class.to_owned(),
            message: message.into(),
        }
    }
}

/// `shortcut`'s two failures.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ShortcutFailure {
    /// `DesktopTaken`: another shortcut has the name; `str(exc)`.
    Taken(String),
    /// `ShortcutError`: `str(exc)`.
    Failed(String),
}

/// What the Start-menu entry and a Desktop shortcut open (`_what_the_entry_opens`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Opens {
    pub target: String,
    pub arguments: Option<String>,
    pub icon: Option<String>,
    pub description: String,
}

/// `App.backend()`: the engine found and checked.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Backend {
    pub codex_exe: String,
    pub engine_version: String,
}

/// `backend.app_identity()` and the look it took (`app_look`: "closed", "unmatched", ...).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Paired {
    /// `(identity["pid"], identity["server"]["pid"])`.
    pub identity: Option<(i64, i64)>,
    /// The backend whose look that was (`_app_paired`'s second answer).
    pub looked: Backend,
    pub app_look: String,
}

/// `app.source().latest_failures(now - 60)`, as `doctor` reads it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum History {
    Readable,
    /// `HistoryNotYet`.
    NotYet,
    /// Any other exception: its class.
    Failed(String),
}

/// The outside world of the command line.
pub trait Outside: Send + Sync {
    // ------------------------------------------------------------------ registrations (car-platform)
    /// `startup.register_aumid(icon)`.
    fn register_aumid(&self, icon: Option<&str>) -> Result<bool, Raised>;
    /// `startup.unregister_aumid()`.
    fn unregister_aumid(&self) -> Result<bool, Raised>;
    /// `startup.install_protocol(command)`.
    fn install_protocol(&self, command: &str) -> Result<bool, Raised>;
    /// `startup.uninstall_protocol()`.
    fn uninstall_protocol(&self) -> Result<bool, Raised>;
    /// `shortcut.install(**opens)`.
    fn shortcut_install(&self, opens: &Opens) -> Result<bool, ShortcutFailure>;
    /// `shortcut.uninstall()`.
    fn shortcut_uninstall(&self) -> bool;
    /// `shortcut.shortcut_path().name`.
    fn shortcut_name(&self) -> String {
        car_platform::shortcut::SHORTCUT_NAME.to_owned()
    }
    /// `shortcut.install_desktop(home, **opens)`.
    fn desktop_install(&self, home: &str, opens: &Opens) -> Result<bool, ShortcutFailure>;
    /// `shortcut.uninstall_desktop(home)`.
    fn desktop_uninstall(&self, home: &str) -> Result<bool, ShortcutFailure>;
    /// `addremove.register(home, edition, version, name)`.
    fn addremove_register(
        &self,
        home: &str,
        edition: &str,
        version: &str,
        name: &str,
    ) -> Result<(), Raised>;
    /// `addremove.unregister(home)`: whether an entry was removed.
    fn addremove_unregister(&self, home: &str) -> Result<bool, Raised>;
    /// `addremove.remove_kept(home)`.
    fn addremove_remove_kept(&self, home: &str) -> bool;

    /// `app.mutex(timeout)` entered: a guard holding the watcher's mutex until dropped, or `str(AdapterError)`
    /// ("mutex_busy" when another holds it past the wait).
    fn watcher_mutex(
        &self,
        state_dir: &Path,
        timeout: f64,
    ) -> Result<Box<dyn std::any::Any>, Raised> {
        let mut mutex = car_platform::sync::Mutex::new(&state_dir.to_string_lossy(), timeout)
            .map_err(|error| Raised::new("AdapterError", error.0))?;
        mutex
            .enter()
            .map_err(|error| Raised::new("AdapterError", error.0))?;
        Ok(Box::new(Held(mutex)))
    }

    // ------------------------------------------------------------------ the engine and the watcher (S3.3, P6)
    /// `App.backend()`: the engine, or the ConfigError/AdapterError it raised (`str(exc)`).
    fn backend(&self, codex_exe: Option<&str>, codex_home: &str) -> Result<Backend, Raised> {
        let _ = (codex_exe, codex_home);
        Err(Raised::new("AdapterError", "engine_discovery_not_ported"))
    }
    /// `compatio.engine_word(paths, version)`.
    fn engine_word(&self, state_dir: &Path, version: &str) -> Option<String> {
        let _ = (state_dir, version);
        None
    }
    /// `_app_paired(app, backend)`.
    fn app_paired(&self, backend: &Backend) -> Paired {
        Paired {
            identity: None,
            looked: backend.clone(),
            app_look: "unmatched".to_owned(),
        }
    }
    /// `codex.pairing.app_running_now()`: True, False, or None where it cannot be told.
    fn app_running_now(&self) -> Option<bool> {
        None
    }
    /// `windows.resource_users(path)`: None when the Restart Manager answered, else `str(AdapterError)`.
    fn resource_users(&self, path: &Path) -> Option<String> {
        let _ = path;
        Some("restart_manager_not_ported".to_owned())
    }
    /// `app.source().latest_failures(now - 60)`.
    fn history(&self, codex_home: &str, since: f64) -> History {
        let _ = (codex_home, since);
        History::Failed("NotImplementedError".to_owned())
    }
    /// `App.run(once=..., poll=...)`: the watcher in the foreground (P6's host is the watcher).
    fn run_watcher(&self, home: &str, once: bool, poll: Option<i128>) -> i32 {
        let _ = (home, once, poll);
        1
    }
    /// `notifier.deliver(notifier.with_open_codex(notifier.build_cancelled(thread, stay), open_codex), ...)`.
    fn announce_cancelled(&self, thread_id: &str, open_codex: bool) {
        let _ = (thread_id, open_codex);
    }
    /// `tray.open_dashboard(home, page)` (cut C6) and `tray.open_chat(home, thread)`.
    fn open_dashboard(&self, home: &str, page: &str) -> bool {
        let _ = (home, page);
        false
    }
    fn open_chat(&self, home: &str, thread_id: &str) -> bool {
        let _ = (home, thread_id);
        false
    }
    /// `notifier.activate(uri, control=..., announce=..., log=..., stay=...)` for a power-stop URI: "stopped" or not.
    fn power_stop(&self, home: &str, uri: &str) -> String {
        let _ = (home, uri);
        "refused".to_owned()
    }
    /// `codex.pairing.official_engine(path)`: (official, reason), or None where it cannot be told (S3.3's).
    fn official_engine(&self, path: &Path) -> Option<(bool, String)> {
        let _ = path;
        None
    }
    /// `compatio.live_view(app.paths, app.codex_home, backend=backend, discovery={}, source=app.source())`.
    fn doctor_live_view(
        &self,
        state_dir: &Path,
        codex_home: &str,
        backend: &Backend,
    ) -> Result<Value, Raised> {
        let _ = (state_dir, codex_home, backend);
        Err(Raised::new(
            "NotImplementedError",
            "compat_live_view_not_ported",
        ))
    }
}

/// A held mutex, let go when dropped.
struct Held(car_platform::sync::Mutex);

impl Drop for Held {
    fn drop(&mut self) {
        self.0.exit();
    }
}

/// The real machine: car-platform's registrations over `HKCU`; the engine's calls refused until the integration.
pub struct SystemOutside;

fn startup_error(error: car_platform::startup::StartupError) -> Raised {
    Raised::new("StartupError", error.0)
}

fn shortcut_failure(error: car_platform::shortcut::ShortcutError) -> ShortcutFailure {
    match error {
        car_platform::shortcut::ShortcutError::DesktopTaken => {
            ShortcutFailure::Taken(error.to_string())
        }
        other => ShortcutFailure::Failed(other.to_string()),
    }
}

impl Outside for SystemOutside {
    fn register_aumid(&self, icon: Option<&str>) -> Result<bool, Raised> {
        car_platform::startup::register_aumid(
            &car_platform::registry::WinRegistry::current_user(),
            icon.map(Path::new),
        )
        .map_err(startup_error)
    }
    fn unregister_aumid(&self) -> Result<bool, Raised> {
        Ok(car_platform::startup::unregister_aumid(
            &car_platform::registry::WinRegistry::current_user(),
        ))
    }
    fn install_protocol(&self, command: &str) -> Result<bool, Raised> {
        car_platform::startup::install_protocol(
            &car_platform::registry::WinRegistry::current_user(),
            command,
        )
        .map_err(startup_error)
    }
    fn uninstall_protocol(&self) -> Result<bool, Raised> {
        Ok(car_platform::startup::uninstall_protocol(
            &car_platform::registry::WinRegistry::current_user(),
        ))
    }
    fn shortcut_install(&self, opens: &Opens) -> Result<bool, ShortcutFailure> {
        car_platform::shortcut::install(
            &car_platform::spawn::SystemStarter,
            Path::new(&opens.target),
            opens.arguments.as_deref().unwrap_or(""),
            opens.icon.as_deref().map(Path::new),
            Some(car_platform::startup::AUMID),
            &opens.description,
        )
        .map_err(shortcut_failure)
    }
    fn shortcut_uninstall(&self) -> bool {
        car_platform::shortcut::uninstall()
    }
    fn desktop_install(&self, home: &str, opens: &Opens) -> Result<bool, ShortcutFailure> {
        car_platform::shortcut::install_desktop(
            &car_platform::spawn::SystemStarter,
            Path::new(home),
            Path::new(&opens.target),
            opens.arguments.as_deref().unwrap_or(""),
            opens.icon.as_deref().map(Path::new),
            Some(car_platform::startup::AUMID),
            &opens.description,
        )
        .map_err(shortcut_failure)
    }
    fn desktop_uninstall(&self, home: &str) -> Result<bool, ShortcutFailure> {
        car_platform::shortcut::uninstall_desktop(
            &car_platform::spawn::SystemStarter,
            Path::new(home),
        )
        .map_err(shortcut_failure)
    }
    fn addremove_register(
        &self,
        home: &str,
        edition: &str,
        version: &str,
        name: &str,
    ) -> Result<(), Raised> {
        car_platform::addremove::register(
            &car_platform::registry::WinRegistry::current_user(),
            Path::new(home),
            edition,
            &["standard", "advanced"],
            version,
            Some(name),
        )
        .map(|_| ())
        .map_err(startup_error)
    }
    fn addremove_unregister(&self, home: &str) -> Result<bool, Raised> {
        car_platform::addremove::unregister(
            &car_platform::registry::WinRegistry::current_user(),
            Path::new(home),
            &["standard", "advanced"],
        )
        .map(|removed| !removed.is_empty())
        .map_err(startup_error)
    }
    fn addremove_remove_kept(&self, home: &str) -> bool {
        car_platform::addremove::remove_kept(Path::new(home))
    }
}

//! The seams: every call the surfaces' decisions make outside this crate, as a trait the caller hands in.
//!
//! Two kinds. What draws or raises something on the real desktop - the card's window and its text measure, the
//! wake of the icon's thread, the presence probes, PowerShell's toast, explorer.exe - is never done here: the C#
//! watcher host (D1) or car-platform implements it ([`CardHost`], [`Presence`], [`PowerShell`], [`Launch`]). And what
//! the reference's surfaces ask the control layer and the store - the card's buttons, the popup's reads and actions,
//! the icon's snapshot, the stored settings - is a trait car-control and car-watcher implement ([`CardControl`],
//! [`PopupControl`], [`TrayStore`], [`StoredSettings`], [`TraySurface`]). rust/GROUNDWORK.md (seat S6.0) names each
//! with the Python it stands for.

use std::path::Path;
use std::time::Duration;

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_platform::pwsh;
use car_platform::spawn::{Spawn, SpawnError, Starter, SystemStarter};

/// An exception a seam's call raised, as the reference reads one: its class's name and its `code` attribute (a
/// control layer's refusal carries one), `Value::Null` where it has none.
#[derive(Clone, Debug, PartialEq)]
pub struct Raised {
    pub class: String,
    pub code: Value,
}

impl Raised {
    pub fn new(class: &str) -> Raised {
        Raised {
            class: class.to_owned(),
            code: Value::Null,
        }
    }

    pub fn coded(class: &str, code: Value) -> Raised {
        Raised {
            class: class.to_owned(),
            code,
        }
    }
}

/// `try: body() except Exception` for a panic as well as an `Err` (D15, review8 S2): where the reference's surfaces
/// catch every exception a seam raised (`perform`, `activate`, `deliver`'s probe, `told`'s store), a panic is the
/// exception the port's seams cannot carry in a `Result`, so it answers as one. The class is the payload's where it
/// is a [`Raised`] or a text of the form `ClassName: ...` (a Python exception's name ending in `Error` or
/// `Exception`), else `Exception`. The integration seat shares one such helper across the crates (GROUNDWORK S6.0).
pub fn caught<T>(body: impl FnOnce() -> Result<T, Raised>) -> Result<T, Raised> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(body)).unwrap_or_else(|payload| {
        if let Some(raised) = payload.downcast_ref::<Raised>() {
            return Err(raised.clone());
        }
        let text = payload
            .downcast_ref::<&str>()
            .map(|text| (*text).to_owned())
            .or_else(|| payload.downcast_ref::<String>().cloned());
        let class = text
            .as_deref()
            .and_then(|text| text.split_once(':'))
            .map(|(name, _)| name)
            .filter(|name| {
                (name.ends_with("Error") || name.ends_with("Exception"))
                    && name.chars().all(|c| c.is_ascii_alphanumeric())
            })
            .unwrap_or("Exception");
        Err(Raised::new(class))
    })
}

// ------------------------------------------------------------------ the desktop: C# host and car-platform
/// The card's host on the icon's thread, which the C# watcher host is (D1; PLAN 1.5 "the surface port"): it draws the
/// card `notice_card::layout` lays out, measuring its text with its own renderer, and it is woken to take what the
/// inbox holds. `notice_window.py` and `ui/card/*` are its Python.
pub trait CardHost {
    /// `wake()`: post the one message that makes the host call `Inbox::take` on its own thread. False when it
    /// could not be posted.
    fn wake(&self) -> bool;
    /// The renderer's `measure(role, text, width, wrap)`: (width, height) in device pixels.
    fn measure(&self, role: &str, text: &str, width: i64, wrap: bool) -> (i64, i64);
}

/// What Windows says about showing a card now (`notice_presence`'s probes), which car-platform asks (D3): each answer
/// one of the closed values `notice_presence` lists, or `Value::Null` for "cannot tell".
pub trait Presence {
    /// `snapshot(aumid)`: the six answers `card_allowed` reads, keyed by its argument names.
    fn snapshot(&self, aumid: &str) -> Map;
    /// `battery_saver()`.
    fn battery_saver(&self) -> bool;
    /// `message_duration_ms()`.
    fn message_duration_ms(&self) -> Option<i64>;
}

/// PowerShell did not run the script to its end (the error `notify.show` catches, whichever it was).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NotRun;

/// The toast's PowerShell (`pwsh.executable` and `pwsh.run`).
pub trait PowerShell {
    /// `pwsh.executable() is not None`.
    fn available(&self) -> bool;
    /// `pwsh.run(script, values, timeout=...)`: the exit code, or Err for what `notify.show` catches (OSError,
    /// SubprocessError, PowerShellError).
    fn run(&self, script: &str, values: &[(&str, &str)], timeout: Duration) -> Result<i32, NotRun>;
}

/// car-platform's PowerShell through a `Starter`: the system's (`SystemStarter`), or a test's stand-in that records
/// what would have been started.
pub struct SystemPowerShell<'a> {
    pub starter: &'a dyn Starter,
}

impl SystemPowerShell<'_> {
    pub fn system() -> SystemPowerShell<'static> {
        SystemPowerShell {
            starter: &SystemStarter,
        }
    }
}

impl PowerShell for SystemPowerShell<'_> {
    fn available(&self) -> bool {
        pwsh::executable().is_some()
    }

    fn run(&self, script: &str, values: &[(&str, &str)], timeout: Duration) -> Result<i32, NotRun> {
        let values: Vec<(&str, Option<&str>)> = values
            .iter()
            .map(|(name, value)| (*name, Some(*value)))
            .collect();
        pwsh::run(self.starter, script, &values, timeout).map_err(|_| NotRun)
    }
}

/// Starting a program without waiting for it (explorer.exe, `open_in_codex`).
pub trait Launch {
    /// `os.path.isfile(path)` (`Path.is_file`).
    fn is_file(&self, path: &Path) -> bool;
    /// `subprocess.Popen(argv, close_fds=True, creationflags=CREATE_NO_WINDOW)`; the error is the class it raises.
    fn start(&self, spawn: &Spawn) -> Py<()>;
}

/// Windows itself.
pub struct SystemLaunch;

impl Launch for SystemLaunch {
    fn is_file(&self, path: &Path) -> bool {
        path.is_file()
    }

    fn start(&self, spawn: &Spawn) -> Py<()> {
        SystemStarter
            .start(spawn)
            .map(|_| ())
            .map_err(|error| launch_error(&error))
    }
}

/// The class of the exception `subprocess.Popen` raises for what car-platform's starter answered.
pub fn launch_error(error: &SpawnError) -> &'static str {
    match error {
        SpawnError::Os(_) => "OSError",
        SpawnError::Timeout => "TimeoutExpired",
    }
}

// ------------------------------------------------------------------ the control layer and the store
/// What a card's button asks the control layer (`notifier.activate`): car-control's `Control`.
pub trait CardControl {
    /// `control.cancel_interruption(interruption_id, actor="toast")`.
    fn cancel_interruption(&self, interruption_id: &str, actor: &str) -> Result<Value, Raised>;
    /// `control.stop_power_countdown(nonce, actor="toast")`.
    fn stop_power_countdown(&self, nonce: &str, actor: &str) -> Result<Value, Raised>;
}

/// The control calls the popup may make (`model.CONTROL_CALLS`): car-control's `Control`, in process.
pub trait PopupControl {
    fn list_pending(&self, source: Option<&Value>) -> Result<Value, Raised>;
    fn get_status(&self) -> Result<Value, Raised>;
    fn set_enabled(&self, enabled: bool) -> Result<Value, Raised>;
    fn set_interruption_recovery(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        enabled: bool,
    ) -> Result<Value, Raised>;
    fn postpone(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        preset: &Value,
    ) -> Result<Value, Raised>;
    fn unpostpone(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised>;
    fn release_hold(&self, interruption_id: &Value, thread_id: &Value) -> Result<Value, Raised>;
    fn set_thread_tier(
        &self,
        thread_id: &Value,
        tier: &Value,
        interruption_id: &Value,
    ) -> Result<Value, Raised>;
    fn set_project_rule(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        always: bool,
        source: Option<&Value>,
    ) -> Result<Value, Raised>;
    fn set_once_words(
        &self,
        interruption_id: &Value,
        thread_id: &Value,
        words: &Value,
    ) -> Result<Value, Raised>;
}

/// The store the icon's snapshot is read from (`tray.snapshot_from`): car-store's `Store`.
pub trait TrayStore {
    fn pending(&self) -> Py<Vec<Value>>;
    fn disabled_threads(&self) -> Py<Vec<Value>>;
    fn settings(&self) -> Py<Value>;
    fn failure_marks(&self) -> Py<Value>;
}

/// The stored settings the icon reads for itself (`StoredMixin`): the control layer's `get_settings` and
/// `settings_path`, either of which a control layer may lack, and the file's stamp.
pub trait StoredSettings {
    /// Whether the control layer has `get_settings` (`getattr(control, "get_settings", None) is not None`).
    fn has_get_settings(&self) -> bool;
    /// `control.get_settings()`, called only where it has one.
    fn get_settings(&self) -> Result<Value, Raised>;
    /// `control.settings_path()`, None where it has no such call.
    fn settings_path(&self) -> Option<Result<Value, Raised>>;
    /// `os.stat(path)`: (st_mtime_ns, st_size), or Err for an OSError.
    fn stat(&self, path: &Value) -> Result<(i128, u64), Raised>;
}

/// What the icon does with what it read (`StoredMixin`'s other half): the C# host's popup and menu take the words,
/// the theme and Reduce motion; the watcher's log takes the line.
pub trait TraySurface {
    /// `tray_popup.adopt_settings(values)`.
    fn adopt_settings(&self, values: &Map) -> Result<(), Raised>;
    /// `self.strings`.
    fn strings(&self) -> Map;
    /// `self.set_strings(strings)`.
    fn set_strings(&self, strings: Map);
    /// `tray_popup.set_reduce_motion(value)`.
    fn set_reduce_motion(&self, value: &Value);
    /// `self.log(line)`.
    fn log(&self, line: &str);
}

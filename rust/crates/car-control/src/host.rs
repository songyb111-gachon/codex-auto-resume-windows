//! What the control layer asks of the machine it runs on - the clock, Windows, the registry's policy keys, the
//! Codex home, the compatibility report - as one trait, so that the layer holds no Windows call of its own (D3)
//! and a test can stand in for any answer.
//!
//! [`SystemHost`] is the real one, over car-platform and car-config. The differential harness wraps it and
//! stands in for what the reference's golden installation stands in for (the watcher's mutex, the Run key, the
//! policy keys, the clock): see `car-harness/src/bridge.rs`.
//!
//! Every method says which Python call it answers.

use std::fs::{File, OpenOptions};
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

/// What a call of the outside world raised, as Python names it: the exception's class and `str(exc)`.
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

    /// What a host that cannot answer raises: the stand-in's refusal (`NotImplementedError`), which every caller
    /// meets as it meets any other exception of that call.
    pub fn refused(what: &str) -> Raised {
        Raised::new(
            "NotImplementedError",
            format!("{what} is not wired into this host"),
        )
    }
}

/// The three named events the control layer signals (`win/sync.py`): Retry now's look-now, Stop watcher's stop,
/// and the demo card of Show me what happens.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Event {
    Wake,
    Stop,
    Demo,
}

impl Event {
    pub fn word(self) -> &'static str {
        match self {
            Event::Wake => "wake",
            Event::Stop => "stop",
            Event::Demo => "demo",
        }
    }
}

/// A process the control layer started: what `subprocess.Popen` gives back and is asked of.
pub trait Launched {
    /// `Popen.pid`.
    fn pid(&self) -> u32;
    /// `Popen.poll()`: the exit code once it has ended, None while it runs.
    fn poll(&mut self) -> Option<i64>;
}

/// `rescan.judge_for(control)`'s `judge(row, kin)`: one waiting record judged by the watcher's own rules.
pub trait Judge {
    /// (outcome, reason), or what the judge raised.
    fn judge(&mut self, row: &Map, kin: &[Map]) -> Result<(Value, Value), Raised>;
}

/// Random bytes from std alone: SipHash under std's OS-seeded keys over a counter and the clock. car-platform has
/// no `BCryptGenRandom` yet (GROUNDWORK, S5.1b: the integration hands one in); the nonce and the bundle's alias key
/// need only be unguessable to another process.
pub fn std_random(count: usize) -> Vec<u8> {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let mut out = Vec::with_capacity(count + 8);
    while out.len() < count {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(COUNTER.fetch_add(1, Ordering::SeqCst));
        if let Ok(since) = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
            hasher.write_u128(since.as_nanos());
        }
        out.extend_from_slice(&hasher.finish().to_le_bytes());
    }
    out.truncate(count);
    out
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
    /// `os.stat(path).st_ino`: the file's identity, which a replaced file does not keep (`Control._seen_file`'s
    /// stamp). None where Windows will not say.
    fn file_id(&self, path: &Path) -> Option<u128>;
    /// `open(path, "rb").read()`: the whole file, opened as Python opens it (shared for reading and writing, never
    /// for delete: a file this holds cannot be deleted or renamed while it is read).
    fn read_file(&self, path: &Path) -> std::io::Result<Vec<u8>>;
    /// `open(path, "rb")`: a file to read in pieces, shared as `read_file` shares it.
    fn open_file(&self, path: &Path) -> std::io::Result<File>;
    /// `tempfile.mkstemp`'s open: a new file, made exclusively (FileExistsError for a name taken), shared as Python
    /// shares.
    fn create_file(&self, path: &Path) -> std::io::Result<File>;
    /// `os.replace(from, to)`: MoveFileExW with REPLACE_EXISTING alone - a target another handle holds open, or a
    /// folder or a junction, is refused (PermissionError, 5), whatever std's own rename would do.
    fn replace(&self, from: &Path, to: &Path) -> std::io::Result<()>;
    /// `os.rename(from, to)`: MoveFileExW with no flag - an existing name, a dangling link included, is refused
    /// (FileExistsError, 183).
    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()>;
    /// `win.sync.Mutex(name, timeout)` entered: a guard that holds it until dropped, or why it could not be had.
    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError>;

    // ------------------------------------------------------------------------- S5.1b: what acts, or asks more
    // Each has a default that refuses (`Raised::refused`) or answers nothing, so a host that answers only the quiet
    // commands still builds; `SystemHost` answers each for real where the crate graph allows it.

    /// `time.monotonic()`.
    fn monotonic(&self) -> f64 {
        0.0
    }
    /// `time.sleep(seconds)`.
    fn sleep(&self, seconds: f64) {
        let _ = seconds;
    }
    /// `WakeEvent(state_dir).signal()`, `StopEvent(...)`, `DemoEvent(...)`: whether a watcher holds the event.
    fn signal(&self, event: Event, state_dir: &Path) -> Result<bool, Raised> {
        let _ = (event, state_dir);
        Err(Raised::refused("signal"))
    }
    /// `startup.current_value()`: the Run value, None for none, or the `StartupError` it raised.
    fn startup_read(&self) -> Result<Option<String>, Raised> {
        Ok(self.startup_value())
    }
    /// `startup.install(command)`: whether the Run value was written.
    fn startup_install(&self, command: &str) -> Result<bool, Raised> {
        let _ = command;
        Err(Raised::refused("startup.install"))
    }
    /// `startup.uninstall()`: whether a Run value was removed.
    fn startup_uninstall(&self) -> Result<bool, Raised> {
        Err(Raised::refused("startup.uninstall"))
    }
    /// `startup.protocol_value()`: the toast button's URL protocol command, or None.
    fn protocol_value(&self) -> Result<Option<String>, Raised> {
        Err(Raised::refused("startup.protocol_value"))
    }
    /// `startup.notification_identity_owner(home)`: True ours, False another's, None none registered.
    fn notification_identity_owner(&self, home: &str) -> Result<Option<bool>, Raised> {
        let _ = home;
        Err(Raised::refused("startup.notification_identity_owner"))
    }
    /// `startup.python_launcher()`: the windowless interpreter beside the one running, or the `StartupError`.
    fn python_launcher(&self) -> Result<PathBuf, Raised> {
        Err(Raised::refused("startup.python_launcher"))
    }
    /// `subprocess.Popen(argv, cwd=cwd, creationflags=flags, close_fds=True, every stream DEVNULL)`.
    fn launch(&self, argv: &[String], cwd: &Path, flags: u32) -> Result<Box<dyn Launched>, Raised> {
        let _ = (argv, cwd, flags);
        Err(Raised::new("OSError", "no process is started by this host"))
    }
    /// `win/powerdown.available(action)`: whether Windows lets this account do it here, and why not.
    fn power_available(&self, action: &str) -> Result<(bool, Option<String>), Raised> {
        let _ = action;
        Err(Raised::refused("powerdown.available"))
    }
    /// `win/network.internet()`: True, False, or None where Windows would not say.
    fn internet(&self) -> Result<Option<bool>, Raised> {
        Err(Raised::refused("network.internet"))
    }
    /// `secrets.token_hex(count)`: `2 * count` lowercase hex digits.
    fn token_hex(&self, count: usize) -> String {
        car_machine::hash::hex(&std_random(count))
    }
    /// `secrets.token_bytes(count)`.
    fn token_bytes(&self, count: usize) -> Vec<u8> {
        std_random(count)
    }
    /// `windows.process_context()`: what Windows wrapped this process in, as the dict it is.
    fn process_context(&self) -> Result<Value, Raised> {
        Err(Raised::refused("windows.process_context"))
    }
    /// `os.getpid()`.
    fn pid(&self) -> u32 {
        std::process::id()
    }
    /// `windows.process_identity(pid)` answered (codexstart's `_process_there`): whether `pid` still runs.
    fn process_there(&self, pid: u32) -> bool {
        let _ = pid;
        false
    }
    /// `ownreport.document.windows_version()`: `10.0.<build>` as Windows reports it to this process, or None.
    fn windows_version(&self) -> Option<String> {
        None
    }
    /// `diagnostics._system()`: `{"windows", "python", "machine"}`.
    fn system(&self) -> Value {
        Value::Null
    }
    /// `compatio.live_view(paths, codex_home, explicit=...)`: a fresh compatibility check (S3.3's).
    fn compat_live_view(
        &self,
        state_dir: &Path,
        codex_home: &str,
        explicit: &Value,
    ) -> Result<Value, Raised> {
        let _ = (state_dir, codex_home, explicit);
        Err(Raised::refused("compatio.live_view"))
    }
    /// `compatio.import_document(paths, target, origin=...)` (S3.3's): the import's codes.
    fn compat_import(
        &self,
        state_dir: &Path,
        target: &Str,
        origin: &Value,
    ) -> Result<Value, Raised> {
        let _ = (state_dir, target, origin);
        Err(Raised::refused("compatio.import_document"))
    }
    /// `compatio.run_refresh(home)` (S3.3's): the bootstrap's refresh.
    fn compat_refresh(&self, home: &Path) -> Result<Value, Raised> {
        let _ = home;
        Err(Raised::refused("compatio.run_refresh"))
    }
    /// `checkup.run(control)`: Diagnostics' check, in the Interface language (car-watcher's).
    fn checkup(&self, home: &Path) -> Result<Value, Raised> {
        let _ = home;
        Err(Raised::refused("checkup.run"))
    }
    /// `checkup.for_bundle(control)(redact)`: the check as the diagnostics bundle runs it, under the bundle's alias
    /// key (car-watcher's).
    fn checkup_for_bundle(&self, home: &Path, key: &[u8]) -> Result<Value, Raised> {
        let _ = (home, key);
        Err(Raised::refused("checkup.for_bundle"))
    }
    /// `rescan.judge_for(control)`: the watcher's own rules for Rescan (car-watcher's).
    fn rescan_judge(&self, home: &Path) -> Result<Box<dyn Judge>, Raised> {
        let _ = home;
        Err(Raised::refused("rescan.judge_for"))
    }
    /// `codexstart._note_turn(stream)`: this writer's turn at codex-start.log - one byte locked past any end the
    /// file can have, within two seconds. A byte-range lock is a Windows call car-platform does not have yet, so the
    /// default (and `SystemHost`) answers no turn: the line is appended and the file is not cut.
    fn note_turn(&self, file: &File) -> bool {
        let _ = file;
        false
    }
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
        self.startup_read().ok().flatten()
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
        crate::homefind::app_homes(self, std::env::var("LOCALAPPDATA").ok().as_deref())
    }

    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }

    fn file_id(&self, path: &Path) -> Option<u128> {
        // std's stable surface has no file index (`windows_by_handle` is unstable) and D3 keeps the Windows call in
        // car-platform: the creation time stands in until the integration hands car-platform's file index in
        // (GROUNDWORK, Integration 6). It is a new file's own, but a rename onto a name just deleted may carry the
        // old file's (NTFS tunnelling), where st_ino would not.
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            std::fs::metadata(path)
                .ok()
                .map(|info| u128::from(info.creation_time()))
        }
        #[cfg(not(windows))]
        {
            let _ = path;
            None
        }
    }

    fn read_file(&self, path: &Path) -> std::io::Result<Vec<u8>> {
        use std::io::Read;
        let mut bytes = Vec::new();
        self.open_file(path)?.read_to_end(&mut bytes)?;
        Ok(bytes)
    }

    fn open_file(&self, path: &Path) -> std::io::Result<File> {
        python_options().read(true).open(path)
    }

    fn create_file(&self, path: &Path) -> std::io::Result<File> {
        python_options()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)
    }

    fn replace(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        if held_or_folder(to) {
            return Err(std::io::Error::from_raw_os_error(5));
        }
        std::fs::rename(from, to)
    }

    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        if std::fs::symlink_metadata(to).is_ok() {
            return Err(std::io::Error::from_raw_os_error(183));
        }
        std::fs::rename(from, to)
    }

    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError> {
        let mut mutex = car_platform::sync::Mutex::new(name, timeout)
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        mutex
            .enter()
            .map_err(|error| AdapterError(error.0.to_owned()))?;
        Ok(Box::new(Held(mutex)))
    }

    fn monotonic(&self) -> f64 {
        static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
        START
            .get_or_init(std::time::Instant::now)
            .elapsed()
            .as_secs_f64()
    }

    fn sleep(&self, seconds: f64) {
        if seconds.is_finite() && seconds > 0.0 {
            std::thread::sleep(std::time::Duration::from_secs_f64(seconds));
        }
    }

    fn signal(&self, event: Event, state_dir: &Path) -> Result<bool, Raised> {
        let name = state_dir.to_string_lossy();
        let failed =
            |error: car_machine::domain::errors::AdapterError| Raised::new("AdapterError", error.0);
        match event {
            Event::Wake => car_platform::sync::WakeEvent::new(&name)
                .map(|found| found.signal())
                .map_err(failed),
            Event::Stop => car_platform::sync::StopEvent::new(&name)
                .map(|found| found.signal())
                .map_err(failed),
            Event::Demo => car_platform::sync::DemoEvent::new(&name)
                .map(|found| found.signal())
                .map_err(failed),
        }
    }

    fn startup_read(&self) -> Result<Option<String>, Raised> {
        car_platform::startup::current_value(&car_platform::registry::WinRegistry::current_user())
            .map_err(startup_error)
    }

    fn startup_install(&self, command: &str) -> Result<bool, Raised> {
        car_platform::startup::install(
            &car_platform::registry::WinRegistry::current_user(),
            command,
        )
        .map_err(startup_error)
    }

    fn startup_uninstall(&self) -> Result<bool, Raised> {
        car_platform::startup::uninstall(&car_platform::registry::WinRegistry::current_user())
            .map_err(startup_error)
    }

    fn protocol_value(&self) -> Result<Option<String>, Raised> {
        car_platform::startup::protocol_value(&car_platform::registry::WinRegistry::current_user())
            .map_err(startup_error)
    }

    fn notification_identity_owner(&self, home: &str) -> Result<Option<bool>, Raised> {
        car_platform::startup::notification_identity_owner(
            &car_platform::registry::WinRegistry::current_user(),
            home,
        )
        .map_err(startup_error)
    }

    fn python_launcher(&self) -> Result<PathBuf, Raised> {
        // `Path(sys.executable).resolve().with_name("pythonw.exe")`: the program running this code is the
        // interpreter here. The Rust core runs under no interpreter, so the sentence is the one a person reads
        // where none is beside it.
        let executable = std::env::current_exe()
            .map(|path| PathBuf::from(car_platform::paths::realpath(&path.to_string_lossy())))
            .unwrap_or_default();
        let windowless = executable.with_file_name("pythonw.exe");
        if windowless.is_file() {
            return Ok(windowless);
        }
        let name = executable
            .file_name()
            .map(|each| each.to_string_lossy().into_owned())
            .unwrap_or_default();
        Err(Raised::new(
            "StartupError",
            format!(
                "no pythonw.exe beside {name}: nothing is registered or started with a console interpreter, \
                 which would open a window"
            ),
        ))
    }

    fn launch(&self, argv: &[String], cwd: &Path, flags: u32) -> Result<Box<dyn Launched>, Raised> {
        use car_platform::spawn::{Spawn, Stream, SystemStarter};
        let request = Spawn::new(argv.iter().cloned())
            .with_flags(flags)
            .with_streams(Stream::Null, Stream::Null, Stream::Null)
            .with_cwd(cwd);
        match SystemStarter.start(&request) {
            Ok(child) => Ok(Box::new(Started(child))),
            Err(car_platform::spawn::SpawnError::Os(error)) => {
                Err(Raised::new("OSError", os_error_text(&error)))
            }
            Err(other) => Err(Raised::new("OSError", other.to_string())),
        }
    }

    fn power_available(&self, action: &str) -> Result<(bool, Option<String>), Raised> {
        let (available, reason) = car_platform::powerdown::available(action);
        Ok((available, reason.map(str::to_owned)))
    }

    fn internet(&self) -> Result<Option<bool>, Raised> {
        Ok(car_platform::network::internet())
    }

    fn process_context(&self) -> Result<Value, Raised> {
        let facts = car_platform::kernel::process_context();
        let mut map = Map::new();
        let tri = |value: Option<bool>| value.map_or(Value::Null, Value::Bool);
        map.insert(Str::from("in_job"), tri(facts.in_job));
        map.insert(Str::from("kill_on_close"), tri(facts.kill_on_close));
        map.insert(Str::from("breakaway_ok"), tri(facts.breakaway_ok));
        map.insert(
            Str::from("silent_breakaway_ok"),
            tri(facts.silent_breakaway_ok),
        );
        map.insert(Str::from("packaged"), tri(facts.packaged));
        Ok(Value::Object(map))
    }

    fn process_there(&self, pid: u32) -> bool {
        car_platform::kernel::process_identity(pid).is_ok()
    }

    fn system(&self) -> Value {
        // `sys.getwindowsversion()` has no reader in car-platform yet, and the Rust core runs under no Python:
        // both are None until the integration hands a version reader in (GROUNDWORK, S5.1b).
        let machine = std::env::var("PROCESSOR_ARCHITEW6432")
            .ok()
            .filter(|each| !each.is_empty())
            .or_else(|| {
                std::env::var("PROCESSOR_ARCHITECTURE")
                    .ok()
                    .filter(|each| !each.is_empty())
            });
        let mut map = Map::new();
        map.insert(
            Str::from("windows"),
            self.windows_version().map_or(Value::Null, Value::from),
        );
        map.insert(Str::from("python"), Value::Null);
        map.insert(
            Str::from("machine"),
            machine.map_or(Value::Null, Value::from),
        );
        Value::Object(map)
    }
}

/// A process `SystemHost::launch` started.
struct Started(std::process::Child);

impl Launched for Started {
    fn pid(&self) -> u32 {
        self.0.id()
    }

    fn poll(&mut self) -> Option<i64> {
        match self.0.try_wait() {
            Ok(Some(status)) => Some(i64::from(status.code().unwrap_or(-1))),
            _ => None,
        }
    }
}

/// `StartupError(sentence)` as Python raises it.
fn startup_error(error: car_platform::startup::StartupError) -> Raised {
    Raised::new("StartupError", error.0)
}

/// `str(OSError)` as Python writes a Windows error: `[WinError 2] The system cannot find the file specified`, the
/// message's trailing full stop and line break taken away.
pub fn os_error_text(error: &std::io::Error) -> String {
    match error.raw_os_error() {
        Some(code) => {
            let text = error.to_string();
            let message = text
                .rsplit_once(" (os error ")
                .map_or(text.as_str(), |(head, _)| head);
            format!(
                "[WinError {code}] {}",
                message.trim_end_matches(['.', '\r', '\n', ' '])
            )
        }
        None => error.to_string(),
    }
}

/// `FILE_SHARE_READ | FILE_SHARE_WRITE`: the C runtime's `_SH_DENYNO`, which every Python open uses. std's own opens
/// share delete too, so a file the reference holds cannot be deleted or renamed and one std holds can.
#[cfg(windows)]
const PYTHON_SHARE: u32 = 0x1 | 0x2;

/// `OpenOptions::new()` with Python's share mode.
fn python_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.share_mode(PYTHON_SHARE);
    }
    options
}

/// Whether `os.replace` onto `path` would be refused (error 5) where std's rename would go through: a folder or a
/// junction (std's POSIX-semantics retry replaces a junction), or a file another handle holds open (std's retry
/// replaces it when that handle shares delete). An open asking DELETE access and sharing nothing fails with a
/// sharing violation (32) while any other handle with any access is open, whatever that handle shares. The product
/// hands car-platform's `files::replace` in instead (integration 6); this is the std-only rule it answers by.
fn held_or_folder(path: &Path) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::{MetadataExt, OpenOptionsExt};
        const DELETE: u32 = 0x0001_0000;
        const FILE_ATTRIBUTE_DIRECTORY: u32 = 0x10;
        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        if let Ok(info) = std::fs::symlink_metadata(path)
            && info.file_attributes() & FILE_ATTRIBUTE_DIRECTORY != 0
        {
            return true;
        }
        let probe = OpenOptions::new()
            .access_mode(DELETE)
            .share_mode(0)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(path);
        matches!(probe, Err(error) if error.raw_os_error() == Some(32))
    }
    #[cfg(not(windows))]
    {
        let _ = path;
        false
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

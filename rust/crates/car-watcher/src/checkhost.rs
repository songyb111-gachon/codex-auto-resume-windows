//! The host the bridge runs on in the product (S6.2b4): car-control's [`Host`] as another host answers it, with the
//! three calls the control layer leaves to the watcher answered by the watcher's own rules -
//!
//! * `checkup(home)` - `checkup.run(control)`, Diagnostics' check, in the Interface language;
//! * `checkup_for_bundle(home, key)` - `checkup.for_bundle(control)(redact)`, in English under the bundle's key;
//! * `rescan_judge(home)` - `rescan.judge_for(control)`, each record judged by an engine of its own Codex home.
//!
//! Every other call is the wrapped host's, so a stand-in host (the differential harness's world) keeps every answer
//! it pins and the check runs over them as the reference's runs over the same patched modules.

use std::any::Any;
use std::fs::File;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_config::Paths;
use car_control::Control;
use car_control::host::{Boot, Event, Host, Judge, Launched, Raised};
use car_machine::json::{Map, Str, Value};
use car_policy::plug::Guarded;
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;
use car_store::open::{AdapterError, Windows};

/// How a notice reaches the person now (`checkup._presence`), asked each time the check runs.
pub type Presence = Arc<dyn Fn() -> Result<Value, Raised> + Send + Sync>;
/// The control layer's paths for a home, made as the bridge made its own.
pub type PathsFor = Arc<dyn Fn(&Path) -> Result<Paths, &'static str> + Send + Sync>;

/// [`Host`] with the watcher's check and Rescan judge.
pub struct WatcherHost {
    inner: Arc<dyn Host>,
    plug: Arc<Guarded>,
    paths: PathsFor,
    presence: Presence,
    key: Option<Vec<u8>>,
}

impl WatcherHost {
    pub fn new(
        inner: Arc<dyn Host>,
        plug: Arc<Guarded>,
        paths: PathsFor,
        presence: Presence,
    ) -> WatcherHost {
        WatcherHost {
            inner,
            plug,
            paths,
            presence,
            key: None,
        }
    }

    /// The same host, its check's aliases under `key` rather than a fresh one (`checkup.Redactor` pinned, as the wire
    /// goldens pin it); the product never pins one.
    pub fn with_key(mut self, key: &[u8]) -> WatcherHost {
        self.key = Some(key.to_vec());
        self
    }

    /// The product's: this PC's presence probes, the home's paths as the watcher makes them (`app::paths`).
    pub fn system(inner: Arc<dyn Host>, plug: Arc<Guarded>, project_root: &str) -> WatcherHost {
        let root = project_root.to_owned();
        WatcherHost::new(
            inner,
            plug,
            Arc::new(move |home: &Path| crate::app::paths(Some(&home.to_string_lossy()), &root)),
            Arc::new(crate::checkup::system_presence),
        )
    }

    /// The bridge's control layer for `home`, over the wrapped host (whose calls the check makes).
    fn control(&self, home: &Path) -> Result<Control, Raised> {
        let paths = (self.paths)(home).map_err(|class| Raised::new(class, ""))?;
        Ok(Control::new(
            paths,
            Arc::clone(&self.inner),
            Arc::clone(&self.plug),
        ))
    }
}

impl Windows for WatcherHost {
    fn install_in_progress(&self) -> Option<bool> {
        self.inner.install_in_progress()
    }
    fn watcher_mutex(&self, state_dir: &Path) -> Result<Box<dyn Any>, AdapterError> {
        self.inner.watcher_mutex(state_dir)
    }
    fn links(&self) -> Arc<dyn car_store::session::Links> {
        self.inner.links()
    }
}

impl Host for WatcherHost {
    fn checkup(&self, home: &Path) -> Result<Value, Raised> {
        let control = self.control(home)?;
        let presence = Arc::clone(&self.presence);
        let asked = crate::checkup::Asked {
            now: self.inner.now(),
            key: self.key.as_deref(),
            locale: None,
            presence: &*presence,
        };
        crate::fail::guarded(|| crate::checkup::run(&control, &asked).map_err(failed))
            .map_err(|failed| Raised::new(&failed.class, failed.message))
    }
    fn checkup_for_bundle(&self, home: &Path, key: &[u8]) -> Result<Value, Raised> {
        let control = self.control(home)?;
        let presence = Arc::clone(&self.presence);
        let now = self.inner.now();
        crate::fail::guarded(|| {
            crate::checkup::for_bundle(&control, key, now, &*presence).map_err(failed)
        })
        .map_err(|failed| Raised::new(&failed.class, failed.message))
    }
    fn rescan_judge(&self, home: &Path) -> Result<Box<dyn Judge>, Raised> {
        let control = self.control(home)?;
        let judged = crate::rescan::judge_for(&control, self.inner.now(), crate::rescan::SECONDS)?;
        Ok(Box::new(judged))
    }

    fn now(&self) -> f64 {
        self.inner.now()
    }
    fn store_clock(&self) -> Option<f64> {
        self.inner.store_clock()
    }
    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        self.inner.os()
    }
    fn version(&self) -> String {
        self.inner.version()
    }
    fn codex_home(&self) -> String {
        self.inner.codex_home()
    }
    fn managed(&self) -> Managed {
        self.inner.managed()
    }
    fn environ(&self, name: &str) -> Option<String> {
        self.inner.environ(name)
    }
    fn windows_languages(&self) -> Vec<String> {
        self.inner.windows_languages()
    }
    fn watcher_running(&self, state_dir: &Path) -> Option<bool> {
        self.inner.watcher_running(state_dir)
    }
    fn startup_value(&self) -> Option<String> {
        self.inner.startup_value()
    }
    fn boot(&self) -> Boot {
        self.inner.boot()
    }
    fn compat_view(&self, state_dir: &Path, settings: &Map) -> Value {
        self.inner.compat_view(state_dir, settings)
    }
    fn state_access(&self, path: &Path) -> String {
        self.inner.state_access(path)
    }
    fn host_app(&self, pid: Option<u32>, started_by: Option<f64>) -> Value {
        self.inner.host_app(pid, started_by)
    }
    fn edition_name(&self) -> String {
        self.inner.edition_name()
    }
    fn superseded(&self) -> bool {
        self.inner.superseded()
    }
    fn installed(&self) -> bool {
        self.inner.installed()
    }
    fn account_codex_home(&self) -> Option<String> {
        self.inner.account_codex_home()
    }
    fn app_homes(&self) -> Vec<String> {
        self.inner.app_homes()
    }
    fn local_clock(&self) -> Box<dyn car_policy::classify::clock::LocalClock> {
        self.inner.local_clock()
    }
    fn is_symlink(&self, path: &Path) -> bool {
        self.inner.is_symlink(path)
    }
    fn file_id(&self, path: &Path) -> Option<u128> {
        self.inner.file_id(path)
    }
    fn read_file(&self, path: &Path) -> std::io::Result<Vec<u8>> {
        self.inner.read_file(path)
    }
    fn open_file(&self, path: &Path) -> std::io::Result<File> {
        self.inner.open_file(path)
    }
    fn create_file(&self, path: &Path) -> std::io::Result<File> {
        self.inner.create_file(path)
    }
    fn replace(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.replace(from, to)
    }
    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.rename(from, to)
    }
    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn Any>, AdapterError> {
        self.inner.lock(name, timeout)
    }
    fn monotonic(&self) -> f64 {
        self.inner.monotonic()
    }
    fn sleep(&self, seconds: f64) {
        self.inner.sleep(seconds)
    }
    fn signal(&self, event: Event, state_dir: &Path) -> Result<bool, Raised> {
        self.inner.signal(event, state_dir)
    }
    fn startup_read(&self) -> Result<Option<String>, Raised> {
        self.inner.startup_read()
    }
    fn startup_install(&self, command: &str) -> Result<bool, Raised> {
        self.inner.startup_install(command)
    }
    fn startup_uninstall(&self) -> Result<bool, Raised> {
        self.inner.startup_uninstall()
    }
    fn protocol_value(&self) -> Result<Option<String>, Raised> {
        self.inner.protocol_value()
    }
    fn notification_identity_owner(&self, home: &str) -> Result<Option<bool>, Raised> {
        self.inner.notification_identity_owner(home)
    }
    fn python_launcher(&self) -> Result<PathBuf, Raised> {
        self.inner.python_launcher()
    }
    fn launch(&self, argv: &[String], cwd: &Path, flags: u32) -> Result<Box<dyn Launched>, Raised> {
        self.inner.launch(argv, cwd, flags)
    }
    fn power_available(&self, action: &str) -> Result<(bool, Option<String>), Raised> {
        self.inner.power_available(action)
    }
    fn internet(&self) -> Result<Option<bool>, Raised> {
        self.inner.internet()
    }
    fn token_hex(&self, count: usize) -> String {
        self.inner.token_hex(count)
    }
    fn token_bytes(&self, count: usize) -> Vec<u8> {
        self.inner.token_bytes(count)
    }
    fn process_context(&self) -> Result<Value, Raised> {
        self.inner.process_context()
    }
    fn pid(&self) -> u32 {
        self.inner.pid()
    }
    fn process_there(&self, pid: u32) -> bool {
        self.inner.process_there(pid)
    }
    fn windows_version(&self) -> Option<String> {
        self.inner.windows_version()
    }
    fn system(&self) -> Value {
        self.inner.system()
    }
    fn compat_live_view(
        &self,
        state_dir: &Path,
        codex_home: &str,
        explicit: &Value,
    ) -> Result<Value, Raised> {
        self.inner.compat_live_view(state_dir, codex_home, explicit)
    }
    fn compat_import(
        &self,
        state_dir: &Path,
        target: &Str,
        origin: &Value,
    ) -> Result<Value, Raised> {
        self.inner.compat_import(state_dir, target, origin)
    }
    fn compat_refresh(&self, home: &Path) -> Result<Value, Raised> {
        self.inner.compat_refresh(home)
    }
    fn note_turn(&self, file: &File) -> bool {
        self.inner.note_turn(file)
    }
    fn text_size(&self) -> Value {
        self.inner.text_size()
    }
    fn ui_face(&self) -> Option<String> {
        self.inner.ui_face()
    }
    fn face_lacks(&self, face: &str, text: &str) -> String {
        self.inner.face_lacks(face, text)
    }
}

fn failed(raised: Raised) -> crate::fail::Failed {
    crate::fail::Failed::new(&raised.class, raised.message)
}

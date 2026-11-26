//! Review of the quiet bridge commands (seat review6b, outputs/plans/v0627-rust/REVIEW-bridge.md): what the
//! differential harness cannot reach, held to the reference's rule as its source states it. Both tests FAIL today.
//!
//! * R-B1 (D15): `controlcli.serve` answers any exception of a command with the generic refusal and reads the next
//!   line (controlcli.py:607-611, and `dispatch`'s own `except Exception`, :550-553). car-control's `serve` has no
//!   unwind boundary, so a panic anywhere under a command - a Windows call, a dependency's `expect` - ends the
//!   long-lived bridge and the window is left with a dead pipe.
//! * R-N (seen cache): `_seen_file` re-reads the failure-seen file whenever its (st_ino, st_mtime_ns, st_size)
//!   changes (control/seen.py:90); car-control's stamp leaves the file's identity out (seen.rs:178), so a file
//!   replaced by another of the same size and modification time is not read again by a long-lived bridge.

use std::io::Cursor;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use car_control::Control;
use car_control::host::{Boot, Host, Probe, SystemHost};
use car_machine::json::{Map, Value};
use car_policy::plug::Guarded;
use car_policy::settings::managed::Managed;
use car_policy::settings::os::Os;
use car_store::open::{AdapterError, Windows};

/// A host over a scratch folder: nothing of this machine's installation, Codex home or registry is asked; the
/// policy keys' read panics the first time when `panic_once` is set.
struct Scratch {
    inner: SystemHost,
    codex: String,
    panic_once: AtomicBool,
}

impl Windows for Scratch {
    fn install_in_progress(&self) -> Option<bool> {
        Some(false)
    }

    fn watcher_mutex(&self, state_dir: &Path) -> Result<Box<dyn std::any::Any>, AdapterError> {
        self.inner.watcher_mutex(state_dir)
    }

    fn links(&self) -> Arc<dyn car_store::session::Links> {
        self.inner.links()
    }
}

impl Host for Scratch {
    fn now(&self) -> f64 {
        1_790_000_000.0
    }
    fn os(&self) -> Arc<dyn Os + Send + Sync> {
        self.inner.os()
    }
    fn version(&self) -> String {
        "0.6.26".into()
    }
    fn codex_home(&self) -> String {
        self.codex.clone()
    }
    fn local_clock(&self) -> Box<dyn car_policy::classify::clock::LocalClock> {
        Box::new(car_control::localclock::UtcClock)
    }
    fn managed(&self) -> Managed {
        if self.panic_once.swap(false, Ordering::SeqCst) {
            panic!("a Windows call failed in a way nobody wrote down");
        }
        Managed::default()
    }
    fn environ(&self, _name: &str) -> Option<String> {
        None
    }
    fn windows_languages(&self) -> Vec<String> {
        Vec::new()
    }
    fn watcher_running(&self, _state_dir: &Path) -> Option<bool> {
        Some(false)
    }
    fn startup_value(&self) -> Option<String> {
        None
    }
    fn boot(&self) -> Boot {
        Boot::default()
    }
    fn compat_view(&self, _state_dir: &Path, _settings: &Map) -> Value {
        Value::Null
    }
    fn state_access(&self, _path: &Path) -> String {
        "owner_only".into()
    }
    fn host_app(&self, _pid: Option<u32>, _started_by: Option<f64>) -> Value {
        Value::Null
    }
    fn edition_name(&self) -> String {
        "standard".into()
    }
    fn superseded(&self) -> bool {
        false
    }
    fn installed(&self) -> bool {
        false
    }
    fn account_codex_home(&self) -> Option<String> {
        None
    }
    fn app_homes(&self) -> Vec<String> {
        Vec::new()
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
    fn open_file(&self, path: &Path) -> std::io::Result<std::fs::File> {
        self.inner.open_file(path)
    }
    fn create_file(&self, path: &Path) -> std::io::Result<std::fs::File> {
        self.inner.create_file(path)
    }
    fn replace(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.replace(from, to)
    }
    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.rename(from, to)
    }
    fn lock(&self, name: &str, timeout: f64) -> Result<Box<dyn std::any::Any>, AdapterError> {
        self.inner.lock(name, timeout)
    }
}

fn scratch(name: &str) -> PathBuf {
    let folder =
        std::env::temp_dir().join(format!("car-v0627-review6b-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    std::fs::create_dir_all(folder.join("home").join("config")).unwrap();
    std::fs::create_dir_all(folder.join("codex")).unwrap();
    folder
}

fn control(folder: &Path, panic_once: bool) -> Control {
    let home = folder.join("home").to_string_lossy().into_owned();
    let no_env = |_: &str| None;
    let os = car_config::Os::here(false, Arc::new(Probe));
    let paths = car_config::Paths::new(Some(&home), &home, &no_env, os).expect("scratch paths");
    let host = Scratch {
        inner: SystemHost::new(&home),
        codex: folder.join("codex").to_string_lossy().into_owned(),
        panic_once: AtomicBool::new(panic_once),
    };
    Control::new(paths, Arc::new(host), Arc::new(Guarded::null()))
}

#[test]
fn a_panic_under_one_command_is_answered_and_the_next_line_is_read() {
    let folder = scratch("panic");
    let control = control(&folder, true);
    let mut input = Cursor::new(
        b"{\"id\": 1, \"command\": \"settings\"}\n{\"id\": 2, \"command\": \"settings\"}\n"
            .to_vec(),
    );
    let mut output: Vec<u8> = Vec::new();
    let served = catch_unwind(AssertUnwindSafe(|| {
        car_control::bridge::serve(&control, &mut input, &mut output)
    }));
    let _ = std::fs::remove_dir_all(&folder);
    let code =
        served.expect("serve let a command's panic out: the long-lived bridge would end here");
    let text = String::from_utf8(output).unwrap();
    let mut replies = text.lines();
    assert_eq!(
        replies.next(),
        Some(
            "{\"id\": 1, \"reply\": {\"ok\": false, \"error\": \"the request could not be completed\", \
             \"error_code\": \"request_failed\"}}"
        )
    );
    assert!(
        replies.next().is_some_and(
            |line| line.starts_with("{\"id\": 2, \"reply\": {\"ok\": true, \"settings\": {")
        ),
        "the second request is answered as the reference answers it"
    );
    assert_eq!(code, 0);
}

#[test]
fn a_failure_seen_file_replaced_by_another_of_the_same_size_and_time_is_read_again() {
    let folder = scratch("seen");
    let control = control(&folder, false);
    let path = folder.join("home").join("config").join("failure-seen.json");
    std::fs::write(&path, b"{\"seen_at\": 1000.0}").unwrap();
    let first = control.failure_seen_at().unwrap();
    let modified = std::fs::metadata(&path).unwrap().modified().unwrap();
    // Another writer's whole replace (a new file, so a new file id), the same size, the same modification time.
    let other = folder.join("home").join("config").join("failure-seen.new");
    std::fs::write(&other, b"{\"seen_at\": 2000.0}").unwrap();
    std::fs::File::options()
        .write(true)
        .open(&other)
        .unwrap()
        .set_modified(modified)
        .unwrap();
    std::fs::remove_file(&path).unwrap();
    std::fs::rename(&other, &path).unwrap();
    let second = control.failure_seen_at().unwrap();
    let _ = std::fs::remove_dir_all(&folder);
    assert_eq!(first, Some(1000.0));
    assert_eq!(
        second,
        Some(2000.0),
        "the reference's stamp holds st_ino, so a new file is a new read"
    );
}

#[test]
fn a_panic_under_the_one_shot_form_is_the_generic_refusal_and_exit_one() {
    let folder = scratch("panic-one-shot");
    let control = control(&folder, true);
    let mut input = Cursor::new(Vec::new());
    let mut output: Vec<u8> = Vec::new();
    let argv = vec!["settings".to_owned()];
    let code = catch_unwind(AssertUnwindSafe(|| {
        car_control::bridge::one_shot(&control, &argv, &mut input, &mut output)
    }))
    .expect(
        "one_shot let a command's panic out: the process would exit 101 with nothing on stdout",
    );
    let _ = std::fs::remove_dir_all(&folder);
    assert_eq!(
        String::from_utf8(output).unwrap(),
        "{\"ok\": false, \"error\": \"the request could not be completed\", \"error_code\": \"request_failed\"}\n"
    );
    assert_eq!(code, 1);
}

fn text_of(points: &[u32]) -> car_machine::json::Str {
    car_machine::json::Str::from_code_points(points.iter().copied()).unwrap()
}

fn points(value: Option<&Value>) -> Vec<u32> {
    match value {
        Some(Value::Str(text)) => text.code_points().collect(),
        other => panic!("not a text: {other:?}"),
    }
}

/// The text of `{"<key>": "<value>"}` with the given code points, as the request's argument.
fn argument_of(key: &[u32], value: &[u32]) -> Value {
    let mut all: Vec<u32> = "{\"".chars().map(u32::from).collect();
    all.extend_from_slice(key);
    all.extend("\": \"".chars().map(u32::from));
    all.extend_from_slice(value);
    all.extend("\"}".chars().map(u32::from));
    Value::Str(text_of(&all))
}

#[test]
fn an_argument_text_with_a_lone_surrogate_in_a_string_is_parsed_as_the_text_it_is() {
    let argument = argument_of(&[0x78, 0xD800], &[0xDC00, 0x79]);
    let body = car_control::bridge::payload(&argument).expect("json.loads reads it");
    let (key, value) = body.iter().next().unwrap();
    assert_eq!(key.code_points().collect::<Vec<_>>(), vec![0x78, 0xD800]);
    assert_eq!(points(Some(value)), vec![0xDC00, 0x79]);
}

#[test]
fn a_raw_high_half_beside_a_raw_low_half_stays_two_characters() {
    let argument = argument_of(&[0x6B], &[0xD83D, 0xDE00]);
    let body = car_control::bridge::payload(&argument).unwrap();
    assert_eq!(points(body.get("k")), vec![0xD83D, 0xDE00]);
}

#[test]
fn a_stand_in_never_meets_a_character_the_text_holds_or_an_escape_makes() {
    // U+F0000 raw, and U+F0001 by an escape pair, beside a lone surrogate: each is read as itself.
    let mut value = vec![0xD800, 0xF0000];
    value.extend("\\udb80\\udc01".chars().map(u32::from));
    let body = car_control::bridge::payload(&argument_of(&[0x6B], &value)).unwrap();
    assert_eq!(points(body.get("k")), vec![0xD800, 0xF0000, 0xF0001]);
}

#[test]
fn a_lone_surrogate_outside_a_string_is_not_json() {
    let mut all: Vec<u32> = "{\"k\": ".chars().map(u32::from).collect();
    all.push(0xD800);
    all.push(u32::from('}'));
    let error = car_control::bridge::payload(&Value::Str(text_of(&all))).unwrap_err();
    assert_eq!(error.message.as_str(), Some("argument must be JSON"));
}

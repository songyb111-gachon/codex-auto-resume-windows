//! What the host tests share: a scratch home every home variable points at (so the watcher's mutex, stop and wake
//! events are named from the test's own state folder and its Codex home lock is the test's own; nothing of the real
//! installation, CODEX_HOME or registry is touched), and the six exports called as the C# host calls them.
#![allow(dead_code)]

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use car_machine::json::{self, Map, Value};

pub struct Scratch {
    pub base: PathBuf,
    pub home: PathBuf,
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.base);
    }
}

/// A scratch installation: `<home>\app\bin\CodexAutoResume.exe` (empty), `runtime.json`, a Codex home of its own, and
/// the profile, local and roaming folders all inside it. `settings` is written as the home's settings file when given.
pub fn scratch(name: &str, settings: Option<&str>) -> Scratch {
    let base = std::env::temp_dir().join(format!("car-host-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    let home = base.join("home");
    let codex = base.join("codex");
    std::fs::create_dir_all(home.join("app").join("bin")).expect("home");
    std::fs::create_dir_all(&codex).expect("codex home");
    std::fs::write(
        home.join("app").join("bin").join("CodexAutoResume.exe"),
        b"",
    )
    .expect("host");
    let quoted = json::to_string(
        &Value::from(home.to_string_lossy().as_ref()),
        &json::Options::new(),
    )
    .expect("text");
    std::fs::write(home.join("runtime.json"), format!("{{\"home\": {quoted}}}")).expect("runtime");
    if let Some(settings) = settings {
        std::fs::create_dir_all(home.join("config")).expect("config");
        std::fs::write(home.join("config").join("settings.json"), settings).expect("settings");
    }
    // SAFETY: each test binary runs one test; nothing else reads the environment while it is set.
    unsafe {
        for name in ["USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA"] {
            std::env::set_var(name, &base);
        }
        std::env::set_var("CODEX_HOME", &codex);
        // The engine join discovers codex.exe at the first tick: a named engine that is not there ends discovery
        // before any candidate is asked (no codex.exe of this PC, nor the ChatGPT app's, is ever started by a test).
        std::env::set_var(
            "CODEX_AUTO_RESUME_CODEX_EXE",
            base.join("no-codex").join("codex.exe"),
        );
        std::env::set_var("LANG", "en_US.UTF-8");
        // The real-engine guard (car-platform `realengine`): no engine or app of this PC is found, listed or started.
        std::env::set_var("CAR_NO_REAL_ENGINE", "1");
        for name in [
            "CODEX_AUTO_RESUME_HOME",
            "CODEX_AUTO_RESUME_RELAUNCHED",
            "CODEX_AUTO_RESUME_AFTER_STOP",
            "LC_ALL",
            "LC_MESSAGES",
            "LANGUAGE",
        ] {
            std::env::remove_var(name);
        }
    }
    Scratch { base, home }
}

/// The `car_start` request the host makes: `--home <home> run`, its own image.
pub fn start_request(home: &Path) -> String {
    let mut request = Map::new();
    request.insert(
        "argv".into(),
        Value::Array(vec![
            Value::from("--home"),
            Value::from(home.to_string_lossy().as_ref()),
            Value::from("run"),
        ]),
    );
    let image = home.join("app").join("bin").join("CodexAutoResume.exe");
    request.insert(
        "image".into(),
        Value::from(image.to_string_lossy().as_ref()),
    );
    json::to_string(&Value::Object(request), &json::Options::wire()).expect("request")
}

/// One reply as text, freed once (`HostCore.Take`); None for NULL.
fn take(reply: *mut u8, length: usize) -> Option<String> {
    if reply.is_null() {
        return None;
    }
    // SAFETY: `length` bytes the core handed out.
    let text = String::from_utf8(unsafe { std::slice::from_raw_parts(reply, length) }.to_vec())
        .expect("utf-8");
    // SAFETY: handed back once with its own length.
    unsafe { car_core::car_free(reply, length) };
    Some(text)
}

pub fn start(request: &str) -> String {
    let mut length = 0usize;
    // SAFETY: `request` lives for the call.
    let reply = unsafe { car_core::car_start(request.as_ptr(), request.len(), &mut length) };
    take(reply, length).expect("a reply")
}

pub fn bridge(line: &str) -> String {
    let mut length = 0usize;
    // SAFETY: as above.
    let reply = unsafe { car_core::car_bridge(line.as_ptr(), line.len(), &mut length) };
    take(reply, length).expect("a reply")
}

pub fn post(action: &str) -> Value {
    let mut length = 0usize;
    // SAFETY: as above.
    let reply = unsafe { car_core::car_post_action(action.as_ptr(), action.len(), &mut length) };
    json::from_str(&take(reply, length).expect("a reply")).expect("json")
}

pub fn next_event(timeout_ms: u32) -> Option<Value> {
    let mut length = 0usize;
    // SAFETY: `length` is the test's.
    let reply = unsafe { car_core::car_next_event(timeout_ms, &mut length) };
    take(reply, length).map(|text| json::from_str(&text).expect("json"))
}

pub fn kind(event: &Value) -> String {
    text(event, "kind")
}

pub fn text(value: &Value, key: &str) -> String {
    match value {
        Value::Object(map) => match map.get(key) {
            Some(Value::Str(found)) => found.as_str().unwrap_or_default().to_owned(),
            _ => String::new(),
        },
        _ => String::new(),
    }
}

pub fn keys(value: &Value) -> Vec<String> {
    match value {
        Value::Object(map) => map
            .keys()
            .filter_map(|key| key.as_str().map(str::to_owned))
            .collect(),
        _ => Vec::new(),
    }
}

pub fn get<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

pub fn log(home: &Path) -> String {
    std::fs::read_to_string(home.join("logs").join("auto-resume.log")).unwrap_or_default()
}

/// Pulls events as the pump does, answering the two waits as the surfaces would, until `done` says so or a minute
/// passed; every event pulled, in order.
pub fn pump(mut done: impl FnMut(&[Value]) -> bool, seconds: u64) -> Vec<Value> {
    let mut seen = Vec::new();
    let until = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < until && !done(&seen) {
        let Some(event) = next_event(250) else {
            continue;
        };
        match kind(&event).as_str() {
            "surfaces" => {
                post(r#"{"action": "tray_started"}"#);
            }
            "close" => {
                post(r#"{"action": "closed"}"#);
            }
            _ => {}
        }
        seen.push(event);
    }
    seen
}

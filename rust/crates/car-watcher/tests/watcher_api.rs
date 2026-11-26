//! The `Watcher` API end to end on a scratch home: every home variable pointed at the scratch folder first, so the
//! watcher's mutex, stop and wake events are named from the test's own state folder and its Codex home lock is the
//! test's own; nothing of the real installation, CODEX_HOME or registry is touched. No timer is armed (keep-awake and
//! the wake listener are off at the defaults), no window is made: the icon's two waits are answered here, as the host
//! answers them.

use std::path::PathBuf;
use std::time::{Duration, Instant};

use car_machine::json::{Map, Value};
use car_watcher::api::Watcher;

fn scratch() -> PathBuf {
    let base = std::env::temp_dir().join(format!("car-watcher-api-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    std::fs::create_dir_all(&base).expect("scratch");
    base
}

fn kind(event: &Value) -> String {
    match event {
        Value::Object(map) => match map.get("kind") {
            Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
            _ => String::new(),
        },
        _ => String::new(),
    }
}

#[test]
fn a_watcher_starts_is_stopped_and_says_ended_last() {
    let base = scratch();
    let home = base.join("home");
    let codex = base.join("codex");
    std::fs::create_dir_all(home.join("app").join("bin")).expect("home");
    std::fs::create_dir_all(&codex).expect("codex home");
    std::fs::write(home.join("app").join("bin").join("CodexAutoResume.exe"), b"").expect("host");
    std::fs::write(
        home.join("runtime.json"),
        format!(
            "{{\"home\": {}}}",
            car_machine::json::to_string(
                &Value::from(home.to_string_lossy().as_ref()),
                &car_machine::json::Options::new()
            )
            .expect("text")
        ),
    )
    .expect("runtime.json");
    // SAFETY: this test binary's one test; nothing else reads the environment while it is set.
    unsafe {
        for name in ["USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA"] {
            std::env::set_var(name, &base);
        }
        std::env::set_var("CODEX_HOME", &codex);
        std::env::remove_var("CODEX_AUTO_RESUME_HOME");
        std::env::remove_var("CODEX_AUTO_RESUME_RELAUNCHED");
        std::env::remove_var("CODEX_AUTO_RESUME_AFTER_STOP");
    }
    let mut request = Map::new();
    request.insert(
        "argv".into(),
        Value::Array(vec![
            Value::from("--home"),
            Value::from(home.to_string_lossy().as_ref()),
            Value::from("run"),
        ]),
    );
    request.insert(
        "image".into(),
        Value::from(home.join("app").join("bin").join("CodexAutoResume.exe").to_string_lossy().as_ref()),
    );
    let watcher = Watcher::start(
        &Value::Object(request),
        car_policy::plug::Guarded::null,
        &home.join("app").to_string_lossy(),
    )
    .expect("started");
    let mut seen = Vec::new();
    let until = Instant::now() + Duration::from_secs(60);
    let mut stopped = false;
    while Instant::now() < until {
        let Some(event) = watcher.next_event(Duration::from_millis(250)) else {
            if !stopped && home.join("logs").join("auto-resume.log").is_file() {
                let log = std::fs::read_to_string(home.join("logs").join("auto-resume.log")).unwrap_or_default();
                if log.contains("initialising Codex adapter failed (EngineNotJoined)") {
                    assert_eq!(watcher.stop(), 1, "the stop event is held by the watcher");
                    stopped = true;
                }
            }
            continue;
        };
        let name = kind(&event);
        match name.as_str() {
            "surfaces" => {
                watcher.post_action("tray_started", &Map::new());
            }
            "close" => {
                watcher.post_action("closed", &Map::new());
            }
            _ => {}
        }
        seen.push(name.clone());
        if name == "ended" {
            assert_eq!(
                event,
                {
                    let mut map = Map::new();
                    map.insert("kind".into(), Value::from("ended"));
                    map.insert("exit_code".into(), Value::from(0));
                    Value::Object(map)
                },
                "{seen:?}"
            );
            break;
        }
    }
    watcher.join();
    assert_eq!(seen.first().map(String::as_str), Some("surfaces"), "{seen:?}");
    assert_eq!(seen.last().map(String::as_str), Some("ended"), "{seen:?}");
    assert!(seen.contains(&"snapshot".to_owned()), "{seen:?}");
    assert!(seen.contains(&"close".to_owned()), "{seen:?}");
    let log = std::fs::read_to_string(home.join("logs").join("auto-resume.log")).expect("log");
    assert!(log.contains("watcher started (pid"), "{log}");
    assert!(log.contains("stop requested; watcher exiting"), "{log}");
    assert!(log.contains("watcher stopped"), "{log}");
    let launched = std::fs::read_to_string(home.join("logs").join("launcher.log")).expect("launcher.log");
    assert!(launched.contains("launcher started (pid"), "{launched}");
    // After `ended` nothing more comes.
    assert!(watcher.next_event(Duration::from_millis(50)).is_none());
    let _ = std::fs::remove_dir_all(&base);
}

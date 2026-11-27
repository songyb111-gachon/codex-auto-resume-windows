//! The real-engine guard (car-platform `realengine`): with `CAR_NO_REAL_ENGINE` set, discovery pointed at this PC's
//! own `LocalAppData` finds no build there, the app is not asked for one, the process list shows none of the Codex app's
//! processes, and a start of a build in the real folder is refused before any process is made.
//!
//! The test itself starts nothing: the checks it passes to discovery only record the paths they are asked about, and
//! the one start it tries names a file that is not there.

use std::sync::{Arc, Mutex};

use car_codex::system::{Platform, System};
use car_platform::realengine;

fn local_app_data() -> String {
    // The first root is the known LocalAppData's `OpenAI` (folded); its parent is the account's real LocalAppData.
    let root = &realengine::real_roots()[0];
    root.strip_suffix("\\openai")
        .expect("the OpenAI root")
        .to_owned()
}

/// A row's text field, or "" where it is not text.
fn field(row: &car_machine::json::Value, name: &str) -> String {
    match row {
        car_machine::json::Value::Object(map) => match map.get(name) {
            Some(car_machine::json::Value::Str(text)) => text.as_str().unwrap_or("").to_owned(),
            _ => String::new(),
        },
        _ => String::new(),
    }
}

#[test]
fn discovery_never_reaches_this_pcs_codex_while_the_switch_is_set() {
    // SAFETY: this test binary's one test sets it before anything reads the environment.
    unsafe { std::env::set_var(realengine::SWITCH, "1") };
    let local = local_app_data();
    let platform = Platform::new();

    // Discovery over the real LocalAppData: no candidate of this PC is checked, the app's engines are not offered.
    let asked: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let record = Arc::clone(&asked);
    let compatible = move |path: &str| -> Result<(), String> {
        record.lock().unwrap().push(path.to_owned());
        Err("recorded_only".to_owned())
    };
    let running = || car_codex::pairing::app_engines(&platform).ok();
    let real_local = local.clone();
    let env = move |name: &str| match name {
        "LOCALAPPDATA" => Some(real_local.clone()),
        _ => std::env::var(name).ok(),
    };
    let chosen = car_config::codex::discover_codex_exe(
        None,
        &compatible,
        Some(&running),
        true,
        true,
        &env,
        &platform.config,
    );
    let asked = asked.lock().unwrap().clone();
    assert!(
        asked.iter().all(|path| !realengine::is_real_engine(path)),
        "discovery checked this PC's own Codex: {asked:?}"
    );
    assert!(
        chosen
            .as_ref()
            .map_or(true, |path| !realengine::is_real_engine(path)),
        "discovery chose this PC's own Codex: {chosen:?}"
    );

    // A build named by path in the real folder is as if it were not there.
    let named = format!("{local}\\OpenAI\\Codex\\bin\\0\\codex.exe");
    let explicit = car_config::codex::discover_codex_exe(
        Some(&named),
        &|_: &str| Ok(()),
        None,
        false,
        false,
        &env,
        &platform.config,
    );
    assert!(explicit.is_err(), "{explicit:?}");

    // The process list leaves the Codex app and its engines out.
    let families = car_codex::pairing::inventory_families();
    let families: Vec<&str> = families.iter().map(String::as_str).collect();
    if let Ok(rows) = platform.processes_named(&["codex.exe", "chatgpt.exe", "codex"], &families) {
        for row in &rows {
            let text = car_machine::json::to_string(row, &car_machine::json::Options::new())
                .unwrap_or_default();
            let path = field(row, "path");
            let family = field(row, "family");
            assert!(
                !realengine::is_real_engine(&path) && !realengine::is_real_family(&family),
                "this PC's Codex is listed: {text}"
            );
        }
    }

    // A start of a build in the real folder is refused before any process is made (`last_started_flags` would hold
    // this start's flags had `Command::new` been reached).
    let before = car_platform::spawn::last_started_flags();
    let flags =
        car_platform::spawn::CREATE_NEW_PROCESS_GROUP | car_platform::spawn::DETACHED_PROCESS;
    let spawn = car_platform::spawn::Spawn::new([format!(
        "{local}\\OpenAI\\Codex\\bin\\car-guard-none\\codex.exe"
    )])
    .with_flags(flags);
    let started = car_platform::spawn::SystemStarter.start(&spawn);
    assert!(started.is_err());
    let after = car_platform::spawn::last_started_flags();
    assert_eq!(after, before, "the start reached Command::new");
}

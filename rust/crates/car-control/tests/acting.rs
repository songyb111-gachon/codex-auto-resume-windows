//! S5.1b's own checks beside the diffs: nothing in this crate can act on the power, the stand-ins that refuse do
//! refuse, and the own report's hand-written matchers read as Python's `re` reads.

use std::path::Path;

use car_control::host::{Host, SystemHost, std_random};
use car_control::ownreport::evidence;
use car_machine::json::{Map, Str, Value};

/// No source of car-control names a call that sleeps, hibernates or shuts down this PC: the power commands only
/// arm, turn off and read a file, and ask Windows whether an action is available.
#[test]
fn no_source_here_can_act_on_the_power() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
    let mut stack = vec![root];
    let forbidden = [
        "powerdown::act",
        "SetSuspendState",
        "ExitWindowsEx",
        "InitiateSystemShutdown",
        "InitiateShutdown",
    ];
    let mut read = 0;
    while let Some(folder) = stack.pop() {
        for entry in std::fs::read_dir(&folder).expect("the crate's sources") {
            let path = entry.expect("an entry").path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            let text = std::fs::read_to_string(&path).expect("a source file");
            read += 1;
            for name in forbidden {
                assert!(!text.contains(name), "{} names {name}", path.display());
            }
        }
    }
    assert!(read > 20, "the sources were read");
}

/// What the integration must still hand in refuses, as the reference's caller meets an exception - and touches
/// nothing on the way.
#[test]
fn the_stand_ins_refuse() {
    let host = SystemHost::new(".");
    let nowhere = Path::new("Z:\\car-v0627-bridge6-never");
    assert!(host.compat_refresh(nowhere).is_err());
    assert!(
        host.compat_import(nowhere, &Str::from("x.json"), &Value::from("file"))
            .is_err()
    );
    assert!(
        host.compat_live_view(nowhere, "Z:\\codex", &Value::Null)
            .is_err()
    );
    assert!(host.checkup(nowhere).is_err());
    assert!(host.checkup_for_bundle(nowhere, &[0; 16]).is_err());
    assert!(host.rescan_judge(nowhere).is_err());
    assert_eq!(host.windows_version(), None);
    let file = tempfile_like();
    assert!(!host.note_turn(&file.0), "no byte-range lock: no turn");
    assert_eq!(std_random(16).len(), 16);
    assert_eq!(host.token_hex(8).len(), 16);
    assert_ne!(host.token_hex(8), host.token_hex(8));
}

/// The watcher's mutex is named from the state folder it guards: a scratch home's is a name of its own, which no
/// real watcher holds, so Start and Stop watcher asked over a scratch home never meet the running watcher.
#[test]
fn a_scratch_home_asks_a_watcher_mutex_of_its_own() {
    let scratch = std::env::temp_dir().join(format!(
        "car-v0627-bridge6-home-{}\\config",
        std::process::id()
    ));
    let host = SystemHost::new(".");
    assert_eq!(host.watcher_running(&scratch), Some(false));
    // Held on a thread of its own: a named mutex is recursive for the thread that owns it.
    let (took, taken) = std::sync::mpsc::channel();
    let (leave, left) = std::sync::mpsc::channel::<()>();
    let folder = scratch.clone();
    let holder = std::thread::spawn(move || {
        let host = SystemHost::new(".");
        let guard = car_store::open::Windows::watcher_mutex(&host, &folder);
        took.send(guard.is_ok()).expect("the test waits");
        let _ = left.recv();
        drop(guard);
    });
    assert!(
        taken.recv().expect("the holder answers"),
        "the scratch mutex is had"
    );
    assert_eq!(
        host.watcher_running(&scratch),
        Some(true),
        "held by this test's thread"
    );
    leave.send(()).expect("the holder waits");
    holder.join().expect("the holder ends");
    assert_eq!(host.watcher_running(&scratch), Some(false));
}

/// A scratch file of this test's own, removed when dropped.
struct Scratch(std::fs::File, std::path::PathBuf);

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.1);
    }
}

fn tempfile_like() -> Scratch {
    let path =
        std::env::temp_dir().join(format!("car-v0627-bridge6-turn-{}.log", std::process::id()));
    let file = std::fs::File::create(&path).expect("a scratch file");
    Scratch(file, path)
}

#[test]
fn iso_is_utc_seconds_rounded_as_python_rounds_them() {
    assert_eq!(evidence::iso(0.5).unwrap(), "1970-01-01T00:00:00Z");
    assert_eq!(evidence::iso(1.9999995).unwrap(), "1970-01-01T00:00:01Z");
    assert_eq!(evidence::iso(1.9999996).unwrap(), "1970-01-01T00:00:02Z");
    assert_eq!(
        evidence::iso(1_790_000_000.0).unwrap(),
        "2026-09-21T14:13:20Z"
    );
    assert_eq!(
        evidence::iso(951_782_400.0).unwrap(),
        "2000-02-29T00:00:00Z"
    );
    assert_eq!(
        evidence::iso(32_535_215_999.0).unwrap(),
        "3000-12-31T23:59:59Z"
    );
    assert_eq!(
        evidence::iso(32_536_850_399.0).unwrap(),
        "3001-01-19T21:59:59Z"
    );
    assert_eq!(evidence::iso(32_536_850_399.9999996), Err("OSError"));
    assert_eq!(evidence::iso(1e15), Err("OSError"));
    assert_eq!(evidence::iso(9.3e18), Err("OverflowError"));
}

#[test]
fn versions_are_read_as_the_reporter_reads_them() {
    let canonical = |text: &str| evidence::canonical_version(&Value::from(text));
    assert_eq!(canonical("0.130.0").as_deref(), Some("codex-cli 0.130.0"));
    assert_eq!(
        canonical(" codex-cli 0.130.0 ").as_deref(),
        Some("codex-cli 0.130.0")
    );
    assert_eq!(canonical("00.130.0"), None);
    assert_eq!(
        canonical("0.130.0-alpha.2").as_deref(),
        Some("codex-cli 0.130.0-alpha.2")
    );
    assert_eq!(canonical("0.130.0-alpha.2.0"), None);
    assert_eq!(
        canonical("0.130.0-alpha.2.1").as_deref(),
        Some("codex-cli 0.130.0-alpha.2.1")
    );
    assert_eq!(canonical("1234567.0.0"), None);
    assert_eq!(canonical("\u{0660}.1.0"), None);
    assert!(evidence::version_matches("codex-cli \u{0660}.1.0"));
    assert!(!evidence::version_matches("codex-cli 0.1.\u{0660}"));
    let version = |text: &str| evidence::engine_version_of(text);
    assert_eq!(
        version("engine codex-cli 0.130.0 passes").as_deref(),
        Some("codex-cli 0.130.0")
    );
    assert_eq!(
        version("xengine codex-cli 0.1.0)").as_deref(),
        Some("codex-cli 0.1.0")
    );
    assert_eq!(
        version("engine codex-cli 0.9.0x passes").as_deref(),
        Some("codex-cli 0.9.0x")
    );
    assert_eq!(version("engine codex-cli 0.9.0_ passes"), None);
    assert_eq!(
        version("engine codex-cli 0.9.0_ engine codex-cli 1.0.0;").as_deref(),
        Some("codex-cli 1.0.0")
    );
    assert_eq!(
        version("engine codex-cli 0.9.0").as_deref(),
        Some("codex-cli 0.9.0")
    );
}

#[test]
fn graded_counts_delivered_records_only() {
    let record = |delivered: bool, state: &str| {
        let mut map = Map::new();
        map.insert(
            Str::from("delivered_at"),
            if delivered {
                Value::from("2026-01-01T00:00:00Z")
            } else {
                Value::Null
            },
        );
        map.insert(Str::from("state"), Value::from(state));
        Value::Object(map)
    };
    let graded = evidence::graded(&[record(true, "recovered"), record(false, "failed")]);
    let Value::Object(graded) = graded else {
        panic!("an object")
    };
    assert_eq!(graded.get("worked"), Some(&Value::Bool(true)));
    assert_eq!(graded.get("failed"), Some(&Value::Bool(false)));
    assert_eq!(graded.get("both"), Some(&Value::Bool(false)));
}

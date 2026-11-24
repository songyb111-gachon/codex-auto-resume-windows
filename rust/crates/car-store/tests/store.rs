//! car-store on its own, in scratch folders: the cases the differential harness (tests/rustdiff/diffs_store.py)
//! runs against the reference, kept here as table tests so `cargo test` holds them without a Python.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};

use car_machine::json::{Map, Str, Value};
use car_store::claims::Claim;
use car_store::records::Register;
use car_store::schema::{MARK_VALUE, SCHEMA_VERSION};
use car_store::{Kind, Options, Store};

const THREAD: &str = "0a1b2c3d-0001-7000-8000-000000000001";
const NOW: f64 = 1_700_000_100.0;

fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let folder = std::env::temp_dir().join(format!(
        "car-store-test-{}-{}-{name}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    let _ = std::fs::remove_dir_all(&folder);
    folder
}

fn key(index: u8) -> String {
    format!("{:02x}", index + 1).repeat(32)
}

fn record(index: u8, category: &str) -> Map {
    let mut map = Map::new();
    let mut put = |name: &str, value: Value| {
        map.insert(Str::new(name), value);
    };
    put("thread_id", Value::from(THREAD));
    put(
        "turn_id",
        Value::from(format!("0a1b2c3d-0002-7000-8000-{:012}", index)),
    );
    put("completed_at", Value::Float(110.0));
    put("started_at", Value::Float(105.0));
    put("ordinal", Value::from(i64::from(index)));
    put("interruption_id", Value::from(key(index)));
    put("reset_at", Value::Null);
    put("limit_type", Value::from("x"));
    put("uncertain", Value::Bool(false));
    put("category", Value::from(category));
    map
}

fn pinned(migrate: bool) -> Options {
    Options {
        migrate,
        check: true,
        clock: Box::new(|| NOW),
    }
}

#[test]
fn a_fresh_state_is_schema_5_and_marked_by_the_watcher() {
    let home = scratch("fresh");
    let store = Store::open_with(&home, pinned(false)).expect("opens");
    assert_eq!(store.schema_version().unwrap(), SCHEMA_VERSION);
    assert_eq!(
        store.pragma("application_id").unwrap(),
        Value::from(MARK_VALUE)
    );
    assert_eq!(
        store.pragma("busy_timeout").unwrap(),
        Value::from(10_000i64)
    );
    assert_eq!(store.pragma("foreign_keys").unwrap(), Value::from(1i64));
    assert_eq!(store.pragma("synchronous").unwrap(), Value::from(2i64));
    assert_eq!(store.pragma("journal_mode").unwrap(), Value::from("delete"));
    drop(store);
    std::fs::remove_dir_all(home).unwrap();
}

#[test]
fn one_claim_then_possibly_sent() {
    let home = scratch("claim");
    let store = Store::open_with(&home, pinned(false)).unwrap();
    store.set_enabled(true, NOW).unwrap();
    assert!(
        store
            .register(&record(0, "server_5xx"), NOW, &Register::default())
            .unwrap()
    );
    assert!(
        !store
            .register(&record(0, "server_5xx"), NOW, &Register::default())
            .unwrap()
    );
    let claim = Claim::default();
    assert_eq!(
        store.reserve_detailed(&key(0), NOW + 10.0, &claim).unwrap(),
        (true, None, None)
    );
    assert_eq!(
        store.reserve_detailed(&key(0), NOW + 11.0, &claim).unwrap(),
        (
            false,
            Some("submission_safe".into()),
            Some("possibly_sent".into())
        )
    );
    // A kind core never recovers alone is refused by the NULL plug's claim.
    assert!(
        store
            .register(&record(1, "unknown"), NOW, &Register::default())
            .unwrap()
    );
    let (granted, gate, _) = store.reserve_detailed(&key(1), NOW + 12.0, &claim).unwrap();
    assert!(!granted);
    assert_eq!(gate.as_deref(), Some("submission_safe"));
    drop(store);
    std::fs::remove_dir_all(home).unwrap();
}

#[test]
fn an_older_schema_waits_for_the_watcher_and_a_newer_one_is_refused() {
    let home = scratch("versions");
    drop(Store::open_with(&home, pinned(false)).unwrap());
    let path = home.join("state.sqlite");
    let set = |sql: &str| {
        let connection = rusqlite::Connection::open(&path).unwrap();
        connection.execute_batch(sql).unwrap();
    };
    set("PRAGMA user_version=6; PRAGMA application_id=0;");
    let refused = Store::open_with(&home, pinned(false))
        .err()
        .expect("refused");
    assert_eq!(refused.kind(), Some(Kind::StateFromNewerVersion));
    set("PRAGMA user_version=5;");
    assert!(
        Store::open_with(&home, pinned(true)).is_ok(),
        "a current state opens and is marked again"
    );
    std::fs::remove_dir_all(home).unwrap();
}

#[test]
fn an_empty_existing_file_is_never_reset() {
    let home = scratch("empty");
    std::fs::create_dir_all(&home).unwrap();
    std::fs::write(home.join("state.sqlite"), b"").unwrap();
    let refused = Store::open_with(&home, pinned(false))
        .err()
        .expect("refused");
    assert_eq!(
        refused.message(),
        "Existing state is empty or uninitialized; refusing to reset"
    );
    std::fs::remove_dir_all(home).unwrap();
}

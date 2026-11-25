//! Review 5: what the heartbeat keeps and `watcher_status` reads, on values no diff feeds (REVIEW-int5.md).
//!
//! store/watcher.py checks the sign-in with `re.compile(r"^[0-9a-f]{16}$").match`, and `$` also matches before a
//! trailing newline: v0.6.26-beta.2's store writes `"0123456789abcdef\n"` and reads it back as it is. car-store's
//! `sign_in` asks for exactly 16 characters, so it writes NULL and reads None. And `"last_tick_ok": bool(row[...])`
//! of a BLOB is `bool(bytes)`, True for `x'01'`; car-store reads a BLOB as an empty list (value.rs `from_sql`), whose
//! truth is False. Both answers below are the tag's own store on a scratch state (Python 3.13.15).

use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_machine::json::Value;
use car_store::session::Links;
use car_store::watcher::Beat;
use car_store::{Options, Store};

struct NoLinks;

impl Links for NoLinks {
    fn is_symlink(&self, _path: &Path) -> bool {
        false
    }
}

fn scratch(name: &str) -> PathBuf {
    let folder =
        std::env::temp_dir().join(format!("car-v0627-review5-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    folder
}

fn store(folder: &Path) -> Store {
    Store::open_with(
        folder,
        Options {
            migrate: true,
            check: true,
            clock: Box::new(|| 1_764_000_000.0),
            links: Arc::new(NoLinks),
        },
    )
    .unwrap()
}

fn beat(sign_in: &str) -> Beat {
    Beat {
        pid: 5,
        session_id: "x".into(),
        started_at: Value::Float(1_764_000_000.0),
        ok: true,
        engine_state: "running".into(),
        code_version: "0.6.26".into(),
        usage: None,
        awake_since: Value::Null,
        memory_peak: Value::Null,
        sign_in: Value::from(sign_in),
        booted_at: Value::Null,
        homes: Value::Null,
    }
}

fn field(store: &Store, name: &str) -> Value {
    store
        .watcher_status()
        .unwrap()
        .unwrap()
        .get(name)
        .cloned()
        .unwrap()
}

#[test]
fn a_sign_in_with_a_trailing_newline_is_kept_as_the_reference_keeps_it() {
    let folder = scratch("sign-in");
    let opened = store(&folder);
    opened
        .heartbeat(1_764_000_000.0, &beat("0123456789abcdef\n"))
        .unwrap();
    let read = field(&opened, "sign_in");
    drop(opened);
    let _ = std::fs::remove_dir_all(&folder);
    assert_eq!(read, Value::from("0123456789abcdef\n"));
}

#[test]
fn a_blob_last_tick_ok_reads_true_as_bool_of_bytes() {
    let folder = scratch("blob");
    let opened = store(&folder);
    opened
        .heartbeat(1_764_000_000.0, &beat("0123456789abcdef"))
        .unwrap();
    let other = rusqlite::Connection::open(folder.join("state.sqlite")).unwrap();
    other
        .execute("UPDATE watcher_status SET last_tick_ok=x'01'", [])
        .unwrap();
    drop(other);
    let read = field(&opened, "last_tick_ok");
    drop(opened);
    let _ = std::fs::remove_dir_all(&folder);
    assert_eq!(read, Value::Bool(true));
}

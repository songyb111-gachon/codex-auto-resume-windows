//! Review 7 (REVIEW-int5b.md, finding S3): the compatibility report's atomic write replaces a file another handle
//! holds open with share-delete; the reference's `os.replace` refuses (REVIEW-int5 S2's rule, in S3.3's writers).
//!
//! `compat/files.py` `write_json_atomic` ends in `os.replace` (MoveFileExW alone): with the report open by a handle
//! that shares delete - any Rust reader, since std opens every file so - it raises PermissionError (winerror 5), the
//! temporary is removed, and the watcher logs that the report could not be written. car-codex's `write_json_atomic`
//! ends in `std::fs::rename`, which retries with POSIX semantics and replaces the file under the open handle.
//! Measured on the reference (2026-11-26, the same steps): `PermissionError 5`, the old text kept.
//! The layout watch's `_write` (`layout.rs:327`) and the advanced edition's `images.rs:256` and `state/seam/accounts.rs:133` take the
//! same `std::fs::rename`. Fails today. Run: `cargo test --locked -p car-codex --test review7_replace` (in rust/).

use car_machine::json::Value;

#[test]
fn a_report_held_open_with_share_delete_is_not_replaced() {
    let folder =
        std::env::temp_dir().join(format!("car-v0627-review7-replace-{}", std::process::id()));
    std::fs::create_dir_all(&folder).expect("a scratch folder");
    let target = folder.join("compatibility.json");
    std::fs::write(&target, b"{\"old\":true}").expect("the old report");
    // std opens with FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE.
    let reader = std::fs::File::open(&target).expect("a reader's handle");
    let written = car_codex::compat::files::write_json_atomic(
        &target.to_string_lossy(),
        &Value::from("new"),
        "compatibility.",
    );
    drop(reader);
    let left = std::fs::read_to_string(&target).unwrap_or_default();
    let _ = std::fs::remove_dir_all(&folder);
    assert!(
        matches!(&written, Err(error) if error.raw_os_error() == Some(5)),
        "the reference raises PermissionError 5; car-codex answered {written:?}"
    );
    assert_eq!(left, "{\"old\":true}", "the reference keeps the old report");
}

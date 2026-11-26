//! Table tests of car-codex's readers: small cases that need no reference interpreter, each a rule the differential
//! diffs (`tests/rustdiff/diffs_codex_*.py`) hold to the reference tag over thousands of inputs. A home is a scratch
//! folder of this process's own, made with SQLite's own bundled build and removed at the end; nothing else of the
//! machine is read.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_codex::chains::ChainMemory;
use car_codex::errors::Error;
use car_codex::source::{LocalSource, Why};
use car_codex::{eligibility, labels, payload, rollout, sql, usage, values, workspace};
use car_machine::json::{Value, from_str};
use car_policy::settings::os::Os;

const A: &str = "0a1b2c3d-0001-7000-8000-00000000000a";
const B: &str = "0a1b2c3d-0001-7000-8000-00000000000b";
const T: &str = "0a1b2c3d-0001-7000-8000-0000000000c1";

/// The questions about a path the reader asks of Windows, answered by the standard library (the harness answers them
/// with car-platform's).
struct StdOs;

impl Os for StdOs {
    fn is_symlink(&self, path: &Path) -> bool {
        std::fs::symlink_metadata(path).is_ok_and(|found| found.file_type().is_symlink())
    }
    fn is_junction(&self, _path: &Path) -> bool {
        false
    }
    fn normcase(&self, text: &[u16]) -> Vec<u16> {
        String::from_utf16_lossy(text)
            .to_lowercase()
            .encode_utf16()
            .collect()
    }
    fn abspath(&self, text: &[u16]) -> Vec<u16> {
        text.to_vec()
    }
    fn resolve(&self, text: &[u16]) -> Result<Vec<u16>, &'static str> {
        let plain = String::from_utf16_lossy(text);
        let found = std::fs::canonicalize(&plain).map_or(plain, |each| {
            let shown = each.to_string_lossy().into_owned();
            shown
                .strip_prefix("\\\\?\\")
                .map_or(shown.clone(), str::to_owned)
        });
        Ok(found.encode_utf16().collect())
    }
}

fn scratch(name: &str) -> PathBuf {
    let folder = std::env::temp_dir().join(format!("car-codex-test-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    std::fs::create_dir_all(folder.join("sessions")).expect("a scratch folder");
    folder
}

fn json(text: &str) -> Value {
    from_str(text).expect("JSON")
}

fn set(words: &[&str]) -> BTreeSet<String> {
    words.iter().map(|each| (*each).to_owned()).collect()
}

#[test]
fn a_label_is_one_printable_line_cut_at_72() {
    assert_eq!(
        labels::label(&json("\"Plan the trip\"")).as_deref(),
        Some("Plan the trip")
    );
    assert_eq!(labels::label(&json("\"two\\nlines\"")), None);
    assert_eq!(labels::label(&json("\"tab\\there\"")), None);
    assert_eq!(labels::label(&json("\"   \"")), None);
    assert_eq!(labels::label(&json("5")), None);
    assert_eq!(labels::label(&json("\"a\\u0007b\"")).as_deref(), Some("ab"));
    let long = format!("\"{}\"", "x".repeat(80));
    let cut = labels::label(&json(&long)).expect("a label");
    assert_eq!(cut.chars().count(), 72);
    assert!(cut.ends_with('\u{2026}'));
    let spaced = format!("\"{} {}\"", "y".repeat(70), "z".repeat(10));
    assert_eq!(
        labels::label(&json(&spaced))
            .expect("a label")
            .chars()
            .count(),
        71
    );
}

#[test]
fn printable_is_pythons_answer_at_its_edges() {
    for (point, printable) in [
        (0x20, true),
        (0x7E, true),
        (0x7F, false),
        (0xA0, false),
        (0xAD, false),
        (0xE9, true),
        (0x2028, false),
        (0x3000, false),
        (0xD800, false),
        (0xE000, false),
        (0x1F600, true),
        (0x10FFFF, false),
    ] {
        assert_eq!(labels::is_printable(point), printable, "{point:#x}");
    }
}

#[test]
fn a_split_name_is_read_whole_or_not_at_all() {
    let name = format!("rollout-2026-10-14T12-00-00-{A}_{B}.jsonl");
    assert_eq!(rollout::continued_id(A, &name).as_deref(), Some(B));
    assert_eq!(
        rollout::continued_id(A, &format!("{A}_{B}.jsonl")).as_deref(),
        Some(B)
    );
    assert_eq!(rollout::continued_id(A, &format!("x{A}_{B}.jsonl")), None);
    assert_eq!(rollout::continued_id(A, &format!("{A}_{A}.jsonl")), None);
    assert_eq!(
        rollout::continued_id(A, &format!("{A}_{}.jsonl", B.to_uppercase())),
        None
    );
    assert_eq!(rollout::continued_id(A, &format!("{A}_{B}.JSONL")), None);
    assert_eq!(rollout::continued_id(&A.to_uppercase(), &name), None);
    assert_eq!(rollout::continued_id(A, "short"), None);
}

#[test]
fn a_turn_after_a_split_comes_after_every_turn_before_it() {
    let row = json("{\"thread_id\": \"x\", \"rollout_ordinal\": 5, \"status\": \"failed\"}");
    let Value::Object(row) = row else {
        panic!("an object")
    };
    let moved = rollout::placed(&row, &Value::from(A), 2);
    assert_eq!(
        moved.get("rollout_ordinal"),
        Some(&Value::from(2 * (1_i64 << 40) + 5))
    );
    assert_eq!(moved.get("thread_id"), Some(&Value::from(A)));
    let same = rollout::placed(&row, &Value::from(A), 0);
    assert_eq!(same.get("rollout_ordinal"), Some(&Value::from(5)));
}

#[test]
fn quoting_a_path_into_the_uri_sqlite_opens() {
    assert_eq!(
        sql::as_uri("C:\\a b\\c.sqlite").as_deref(),
        Some("file:///C:/a%20b/c.sqlite")
    );
    assert_eq!(
        sql::as_uri("C:\\caf\u{e9}\\x").as_deref(),
        Some("file:///C:/caf%C3%A9/x")
    );
    assert_eq!(
        sql::as_uri("\\\\server\\share\\x").as_deref(),
        Some("file://server/share/x")
    );
    assert_eq!(sql::as_uri("relative\\x"), None);
}

#[test]
fn a_normalized_turn_keeps_the_fields_it_needs_and_nothing_of_the_error() {
    let row = json(&format!(
        "{{\"thread_id\": \"{A}\", \"turn_id\": \"{B}\", \"status\": \"failed\", \"started_at\": 1788627900, \"completed_at\": 1788628000, \
         \"rollout_ordinal\": 5, \"error_json\": \"{{\\\"codexErrorInfo\\\":\\\"usageLimitExceeded\\\",\\\"message\\\":\\\"secret words\\\"}}\"}}"
    ));
    let found = values::normalize(&row)
        .expect("no exception")
        .expect("a turn");
    assert_eq!(found.get("category"), Some(&Value::from("usage_limit")));
    assert!(found.get("error_json").is_none());
    assert!(!format!("{found:?}").contains("secret"));
    // read again, it is the same decision
    let again = values::normalize(&Value::Object(found.clone()))
        .expect("no exception")
        .expect("a turn");
    assert_eq!(again, found);
    let detected = payload::detect(&row)
        .expect("no exception")
        .expect("recoverable");
    assert_eq!(
        detected
            .get("interruption_id")
            .map(|id| matches!(id, Value::Str(each) if each.len() == 64)),
        Some(true)
    );
    // a turn that is not failed, or whose id is not a UUID, is none
    assert_eq!(
        values::normalize(&json("{\"thread_id\": \"x\"}")).expect("no exception"),
        None
    );
}

#[test]
fn the_apps_conversations_are_taken_up_and_others_by_name_only() {
    let own = set(&[]);
    let first = json("{\"originator\": \"Codex Desktop\", \"source\": \"vscode\"}");
    assert_eq!(
        eligibility::kind_of(&Value::from("vscode"), &first, &own, &own),
        Ok(Some("desktop"))
    );
    let tui = json("{\"originator\": \"codex-tui\", \"source\": \"cli\"}");
    assert_eq!(
        eligibility::kind_of(&Value::from("cli"), &tui, &own, &own),
        Ok(None)
    );
    assert_eq!(
        eligibility::kind_of(&Value::from("cli"), &tui, &set(&["cli"]), &own),
        Ok(Some("cli"))
    );
    assert_eq!(
        eligibility::kind_of(&Value::from("vscode"), &tui, &own, &own),
        Ok(Some("desktop"))
    );
    // an originator that cannot be hashed is the reference's TypeError, not a refusal
    let list = json("{\"originator\": [1], \"source\": \"vscode\"}");
    assert_eq!(
        eligibility::kind_of(&Value::from("vscode"), &list, &own, &own),
        Err("TypeError")
    );
    let widened = set(&["every_desktop"]);
    let other = json("{\"originator\": \"Something\", \"source\": \"vscode\"}");
    assert_eq!(
        eligibility::kind_of(&Value::from("vscode"), &other, &own, &own),
        Ok(None)
    );
    assert_eq!(
        eligibility::kind_of(&Value::from("vscode"), &other, &own, &widened),
        Ok(Some("desktop"))
    );
}

#[test]
fn a_usage_reply_is_read_to_numbers_only() {
    let reply = json(
        "{\"rateLimitsByLimitId\": {\"codex\": {\"primary\": {\"usedPercent\": 100, \"windowDurationMins\": 300, \"resetsAt\": 1788631600}, \
         \"secondary\": null}}, \"account\": \"someone\"}",
    );
    let found = usage::parse_usage(&reply).expect("no exception");
    assert_eq!(found.get("available"), Some(&Value::Bool(false)));
    assert_eq!(found.get("limit_type"), Some(&Value::from("300m")));
    assert!(!format!("{found:?}").contains("someone"));
    let nothing = usage::parse_usage(&json("{}")).expect("no exception");
    assert_eq!(
        nothing.get("reason"),
        Some(&Value::from("usage_snapshot_unknown"))
    );
}

#[test]
fn a_head_that_is_not_there_is_a_word_not_an_error() {
    let folder = scratch("workspace");
    let text = folder.to_string_lossy().into_owned();
    assert_eq!(workspace::head_digest(&text), workspace::NONE);
    std::fs::create_dir_all(folder.join(".git")).expect("a folder");
    std::fs::write(folder.join(".git").join("HEAD"), b"ref: refs/heads/main\n").expect("a file");
    assert_eq!(workspace::head_digest(&text).len(), 64);
    assert_eq!(
        workspace::head_digest("relative\\folder"),
        workspace::UNREADABLE
    );
    assert_eq!(
        workspace::head_digest("\\\\server\\share\\x"),
        workspace::UNREADABLE
    );
    let _ = std::fs::remove_dir_all(&folder);
}

fn put(folder: &Path, name: &str, statements: &[&str]) {
    let connection = rusqlite::Connection::open(folder.join(name)).expect("a database");
    for statement in statements {
        connection.execute_batch(statement).expect("a statement");
    }
}

fn home(name: &str) -> (PathBuf, LocalSource) {
    let folder = scratch(name);
    put(
        &folder,
        "state_5.sqlite",
        &[
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, source TEXT, thread_source TEXT, archived INTEGER, history_mode TEXT)",
        ],
    );
    put(
        &folder,
        "thread_history_1.sqlite",
        &[
            "CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT, error_json TEXT, started_at INTEGER, completed_at INTEGER, \
         rollout_ordinal INTEGER, rollout_end_byte_offset INTEGER, first_user_item_id TEXT)",
            "CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, item_type TEXT, item_json TEXT)",
        ],
    );
    put(
        &folder,
        "queue_1.sqlite",
        &["CREATE TABLE queued_items (id TEXT, thread_id TEXT, payload_json TEXT)"],
    );
    let source = LocalSource::new(
        Arc::new(StdOs),
        &folder.to_string_lossy(),
        Some(Arc::new(Mutex::new(ChainMemory::new(None, true)))),
    )
    .expect("a reader");
    (folder, source)
}

#[test]
fn a_failed_turn_of_a_desktop_conversation_is_found_and_a_schema_that_moved_is_refused() {
    let (folder, source) = home("failure");
    let rollout_path = folder.join("sessions").join(format!("rollout-{A}.jsonl"));
    std::fs::write(
        &rollout_path,
        format!("{{\"type\":\"session_meta\",\"payload\":{{\"id\":\"{A}\",\"originator\":\"Codex Desktop\",\"source\":\"vscode\",\"thread_source\":\"user\"}}}}\n"),
    )
    .expect("a rollout");
    put(
        &folder,
        "state_5.sqlite",
        &[&format!(
            "INSERT INTO threads VALUES ('{A}', '{}', 'vscode', 'user', 0, 'paginated')",
            rollout_path.to_string_lossy().replace('\'', "''")
        )],
    );
    put(
        &folder,
        "thread_history_1.sqlite",
        &[&format!(
            "INSERT INTO thread_turns VALUES ('{A}', '{T}', 'failed', '{{\"codexErrorInfo\":\"serverOverloaded\"}}', 1788627900, 1788628000, 5, 0, NULL)"
        )],
    );
    let found = source
        .latest_failures(&Value::from(1_788_624_400), &BTreeSet::new(), false, false)
        .expect("a read");
    assert_eq!(found.len(), 1);
    assert_eq!(found[0].get("category"), Some(&Value::from("server_5xx")));
    assert_eq!(found[0].get("thread_id"), Some(&Value::from(A)));
    // an unreadable start is the reference's refusal, not a list
    assert!(matches!(
        source.latest_failures(&Value::from("x"), &BTreeSet::new(), false, false),
        Err(Error::Source(_))
    ));
    // not taken up where the row says archived
    put(
        &folder,
        "state_5.sqlite",
        &[&format!("UPDATE threads SET archived = 1 WHERE id = '{A}'")],
    );
    let (path, why) = source
        .eligibility(A, false, None, None, None)
        .expect("a verdict");
    assert_eq!(path, None);
    assert_eq!(
        why,
        Some(Why {
            reason: "other_kind",
            kind: Some("archived".to_owned())
        })
    );
    // a missing column means the schema moved: refuse, never guess
    put(
        &folder,
        "state_6.sqlite",
        &["CREATE TABLE threads (id TEXT)"],
    );
    assert!(matches!(source.resolve("state"), Err(Error::Source(_))));
    let _ = std::fs::remove_dir_all(&folder);
}

#[test]
fn a_fresh_home_has_no_history_yet_and_every_other_home_refuses_as_it_did() {
    // test_history_not_yet ReaderTests (v0.6.26 final): no history database and a state with no conversation is
    // HistoryNotYet, still a SourceError; with a conversation, or with no state either, the plain refusal.
    let nothing = BTreeSet::<String>::new;
    let (folder, source) = home("not-yet");
    // a history that is there is read as it was
    assert!(
        source
            .latest_failures(&Value::from(1_788_624_400), &nothing(), false, false)
            .expect("a read")
            .is_empty()
    );
    std::fs::remove_file(folder.join("thread_history_1.sqlite")).expect("no history");
    let fresh = source.latest_failures(&Value::from(1_788_624_400), &nothing(), false, false);
    let Err(refused) = fresh else {
        panic!("a fresh home refuses")
    };
    assert!(refused.is_history_not_yet());
    assert!(matches!(refused, Error::Source(_)));
    assert_eq!(refused.class(), "HistoryNotYet");
    assert_eq!(refused.message(), "No Codex history database yet");
    // only the history is "not yet": the state still resolves
    assert!(source.resolve("state").is_ok());
    // a conversation in the state: the refusal it was
    put(
        &folder,
        "state_5.sqlite",
        &[&format!(
            "INSERT INTO threads VALUES ('{A}', '', 'vscode', 'user', 0, 'paginated')"
        )],
    );
    let lost = source
        .latest_failures(&Value::from(1_788_624_400), &nothing(), false, false)
        .expect_err("a refusal");
    assert!(!lost.is_history_not_yet());
    assert_eq!(lost.class(), "SourceError");
    assert_eq!(
        lost.message(),
        "No Codex history database with the required schema"
    );
    // no state either: the refusal it was
    std::fs::remove_file(folder.join("state_5.sqlite")).expect("no state");
    let gone = source.resolve("history").expect_err("a refusal");
    assert_eq!(gone.class(), "SourceError");
    let _ = std::fs::remove_dir_all(&folder);
}

#[test]
fn what_a_rollout_says_after_a_failed_turn_is_one_of_six_words() {
    let folder = scratch("superseded");
    let file = folder.join("sessions").join("one.jsonl");
    let done = format!(
        "{{\"type\":\"event_msg\",\"payload\":{{\"type\":\"task_complete\",\"turn_id\":\"{T}\"}}}}\n"
    );
    let person =
        "{\"type\":\"event_msg\",\"payload\":{\"type\":\"user_message\",\"message\":\"hi\"}}\n";
    let text = file.to_string_lossy().into_owned();
    std::fs::write(&file, format!("{done}{person}")).expect("a file");
    assert_eq!(
        rollout::superseded_in(&text, T, None),
        rollout::LATER_MESSAGE
    );
    std::fs::write(&file, &done).expect("a file");
    assert_eq!(
        rollout::superseded_in(&text, T, None),
        rollout::NOTHING_LATER
    );
    std::fs::write(&file, format!("{person}{done}")).expect("a file");
    assert_eq!(
        rollout::superseded_in(&text, T, None),
        rollout::NOTHING_LATER
    );
    std::fs::write(&file, format!("{done}{person}{{\"type\":\"event_msg\",\"payload\":{{\"type\":\"thread_rolled_back\"}}}}\n")).expect("a file");
    assert_eq!(rollout::superseded_in(&text, T, None), rollout::ROLLED_BACK);
    std::fs::write(&file, person).expect("a file");
    assert_eq!(rollout::superseded_in(&text, T, None), rollout::NO_ANCHOR);
    assert_eq!(
        rollout::superseded_in(&text, T, Some(3)),
        rollout::TOO_LARGE
    );
    assert_eq!(
        rollout::superseded_in(&folder.join("missing").to_string_lossy(), T, None),
        rollout::UNREADABLE
    );
    let _ = std::fs::remove_dir_all(&folder);
}

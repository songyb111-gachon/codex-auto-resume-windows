//! The power action after tasks a person picked (`power_after_tasks`, v0.6.20, Discussion #57): its list, and its
//! answer at P21 (seat S7.2e2, `engine/powertasks.py`).
//!
//! A person picks conversations whose turn runs now and arms core's own power action for them, once
//! (control/powertasks.py). Core keeps the arming, the countdown and every condition but one: whether those tasks have
//! ended as the person chose to count them - one PowerTasks word. The list is `config/advanced/power-tasks.json`: the
//! core arming's nonce, whether a failed and an interrupted ending count beside a completed one, and each task as its
//! conversation and the turn that ran when it was armed - ids and booleans (D2). Written whole under its own named
//! lock; a list for another nonce answers nothing core may act on. A task's end is followed as follow.py follows a
//! delivered message, ids and statuses only; anything that cannot be read is UNKNOWN, on which core waits.

use std::cmp::Ordering;
use std::io::Write;
use std::path::{Path, PathBuf};

use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::{Map, Options, Value};
use car_machine::vocab_gen::domain_power_vocabulary::PowerTasks;
use car_machine::vocab_gen::domain_states::{TERMINAL, WAITING};

use super::supervise::{field, word};
use crate::capabilities::{Code, Raised, Said, Spoke};
use crate::state::sql;

pub const CAPABILITY: &str = "power_after_tasks";
pub const FILE_NAME: &str = "power-tasks.json";
pub const FORMAT: &str = "codex-auto-resume/power-tasks/1";
pub const FILE_LIMIT: u64 = 16 * 1024;
/// How many tasks one arming waits for at most, and how many cut-offs one task is followed through.
pub const MOST: usize = 16;
pub const STEPS: usize = 12;
pub const LOCK_SECONDS: f64 = 5.0;
pub const RUNNING: &str = "running";
pub const COMPLETED: &str = "completed";
pub const FAILED: &str = "failed";
pub const INTERRUPTED: &str = "interrupted";
pub const UNKNOWN: &str = "unknown";
pub const ENDS: [&str; 5] = [RUNNING, COMPLETED, FAILED, INTERRUPTED, UNKNOWN];
const KEYS: [&str; 6] = ["format", "nonce", "armed_at", "failed", "interrupted", "tasks"];
/// A cut-off core gave up because the person (or a newer cut-off) continued the conversation.
pub const CONTINUED: [&str; 2] = ["superseded_by_user", "superseded"];

pub fn path_of(paths: &Paths) -> PathBuf {
    Path::new(&paths.advanced_dir).join(FILE_NAME)
}

// ---------------------------------------------------------------------------------------------- the list
fn exactly(map: &Map, keys: &[&str]) -> bool {
    map.len() == keys.len()
        && keys
            .iter()
            .all(|key| map.contains_key(&car_machine::json::Str::new(key)))
}

/// `valid(document)`: exactly its keys, a power nonce, a number, two booleans, 1 to MOST tasks each exactly a
/// conversation id and a turn id, no conversation twice.
pub fn valid(document: &Value) -> bool {
    let Value::Object(map) = document else {
        return false;
    };
    if !exactly(map, &KEYS) || *field(document, "format") != word(FORMAT) {
        return false;
    }
    if !ids::is_power_nonce(field(document, "nonce"))
        || !matches!(field(document, "armed_at"), Value::Int(_) | Value::Float(_))
    {
        return false;
    }
    if !matches!(field(document, "failed"), Value::Bool(_))
        || !matches!(field(document, "interrupted"), Value::Bool(_))
    {
        return false;
    }
    let Value::Array(tasks) = field(document, "tasks") else {
        return false;
    };
    if !(1..=MOST).contains(&tasks.len()) {
        return false;
    }
    let mut threads: Vec<&Value> = Vec::new();
    for task in tasks {
        let Value::Object(each) = task else {
            return false;
        };
        if !exactly(each, &["thread_id", "turn_id"])
            || !ids::is_uuid(field(task, "thread_id"))
            || !ids::is_uuid(field(task, "turn_id"))
        {
            return false;
        }
        let thread = field(task, "thread_id");
        if threads.iter().any(|seen| **seen == *thread) {
            return false;
        }
        threads.push(thread);
    }
    true
}

/// `read(paths)`: the list as it may be believed, or None: missing, a link, too large, unreadable or not valid.
pub fn read(paths: &Paths) -> Option<Value> {
    let path = path_of(paths);
    let parent = path.parent().map(Path::to_path_buf).unwrap_or_default();
    if car_config::paths::is_link(&path.to_string_lossy())
        || car_config::paths::is_link(&parent.to_string_lossy())
    {
        return None;
    }
    if std::fs::metadata(&path).ok()?.len() > FILE_LIMIT {
        return None;
    }
    let bytes = std::fs::read(&path).ok()?;
    let text = String::from_utf8(bytes).ok()?;
    let document = car_machine::compat::loads(&text).ok()?;
    valid(&document).then_some(document)
}

/// The list's bytes as `json.dump(document, handle, sort_keys=True)` writes them.
pub fn text_of(document: &Value) -> Option<String> {
    car_machine::json::to_string(document, &Options::new().sort_keys(true)).ok()
}

/// `write(paths, document)`: written whole under the list's named lock (a temporary file flushed, then moved over
/// it); false where it is not valid, the lock was not had, or Windows refused - with nothing left behind.
pub fn write(paths: &Paths, document: &Value) -> bool {
    if !valid(document) {
        return false;
    }
    let path = path_of(paths);
    let Some(parent) = path.parent().map(Path::to_path_buf) else {
        return false;
    };
    if std::fs::create_dir_all(&parent).is_err() || car_config::paths::is_link(&parent.to_string_lossy())
    {
        return false;
    }
    let Ok(mut lock) = car_platform::sync::Mutex::new(&path.to_string_lossy(), LOCK_SECONDS) else {
        return false;
    };
    if lock.enter().is_err() {
        return false;
    }
    let Some(text) = text_of(document) else {
        return false;
    };
    let Some((temporary, mut handle)) = temporary_in(&parent, "power-tasks.", ".tmp") else {
        return false;
    };
    let written = handle
        .write_all(text.as_bytes())
        .and_then(|()| handle.flush())
        .and_then(|()| handle.sync_all());
    drop(handle);
    if written.is_ok() && car_platform::files::replace(&temporary, &path).is_ok() {
        return true;
    }
    let _ = std::fs::remove_file(&temporary);
    false
}

/// `tempfile.mkstemp(dir=folder, prefix=..., suffix=...)`: a new file of its own name, opened for writing.
pub(crate) fn temporary_in(
    folder: &Path,
    prefix: &str,
    suffix: &str,
) -> Option<(PathBuf, std::fs::File)> {
    for _ in 0..100 {
        let mut bytes = [0u8; 6];
        car_platform::random::fill(&mut bytes).ok()?;
        let name: String = bytes
            .iter()
            .map(|byte| char::from(b"abcdefghijklmnopqrstuvwxyz0123456789_"[*byte as usize % 37]))
            .collect();
        let candidate = folder.join(format!("{prefix}{name}{suffix}"));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(file) => return Some((candidate, file)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(_) => return None,
        }
    }
    None
}

/// `remove(paths)`: the list gone, where it is. Never raises.
pub fn remove(paths: &Paths) {
    let path = path_of(paths);
    if !car_config::paths::is_link(&path.to_string_lossy()) {
        let _ = std::fs::remove_file(&path);
    }
}

// ---------------------------------------------------------------------------------------------- one task's end
/// What follows a record's end can raise in the reference (an unhashable state or key, keys that cannot be ordered):
/// the task is then UNKNOWN.
struct Unreadable;

fn hashable(value: &Value) -> Result<(), Unreadable> {
    if matches!(value, Value::Array(_) | Value::Object(_)) {
        Err(Unreadable)
    } else {
        Ok(())
    }
}

/// Python's `x < y` between two sort-key parts: numbers with numbers, texts with texts, lists element by element;
/// anything else a TypeError.
fn less(first: &Value, second: &Value) -> Result<bool, Unreadable> {
    let numeric = |value: &Value| match value {
        Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
        Value::Int(number) => number.as_i64().map(|n| n as f64),
        Value::Float(number) => Some(*number),
        _ => None,
    };
    match (first, second) {
        (Value::Str(a), Value::Str(b)) => Ok(a < b),
        (Value::Array(a), Value::Array(b)) => {
            for (x, y) in a.iter().zip(b) {
                if !sql::py_eq(x, y) {
                    return less(x, y);
                }
            }
            Ok(a.len() < b.len())
        }
        _ => match (numeric(first), numeric(second)) {
            (Some(a), Some(b)) => Ok(a < b),
            _ => Err(Unreadable),
        },
    }
}

/// `(a1, b1) < (a2, b2)` as CPython's tuple compare does it: the first unequal place decides.
fn key_less(first: &(Value, Value), second: &(Value, Value)) -> Result<bool, Unreadable> {
    if !sql::py_eq(&first.0, &second.0) {
        return less(&first.0, &second.0);
    }
    if !sql::py_eq(&first.1, &second.1) {
        return less(&first.1, &second.1);
    }
    Ok(false)
}

/// `list.sort()` of a short list as CPython 3.13+ does it (`count_run`, then `binarysort` from where the run ends):
/// the same comparisons in the same order, so a pair that cannot be ordered raises exactly where the reference's
/// does. Lists of 64 and more (no turn has that many interruptions) are sorted with every adjacent pair compared.
fn sort_keyed<T: Clone>(items: &mut Vec<(T, (Value, Value))>) -> Result<(), Unreadable> {
    let n = items.len();
    if n < 2 {
        return Ok(());
    }
    if n >= 64 {
        let mut failed = false;
        items.sort_by(|a, b| match key_less(&a.1, &b.1) {
            Ok(true) => Ordering::Less,
            Ok(false) => match key_less(&b.1, &a.1) {
                Ok(true) => Ordering::Greater,
                Ok(false) => Ordering::Equal,
                Err(_) => {
                    failed = true;
                    Ordering::Equal
                }
            },
            Err(_) => {
                failed = true;
                Ordering::Equal
            }
        });
        return if failed { Err(Unreadable) } else { Ok(()) };
    }
    let lt = |items: &Vec<(T, (Value, Value))>, i: usize, j: usize| key_less(&items[i].1, &items[j].1);
    // count_run
    let mut run = 1;
    while run < n {
        if lt(items, run, run - 1)? {
            break;
        }
        run += 1;
    }
    if run < n {
        let mut descending = true;
        if run > 1 {
            if lt(items, 0, run - 1)? {
                descending = false;
            } else {
                items[..run].reverse();
            }
        }
        if descending {
            run += 1;
            let mut neq = 0usize;
            let reverse_last = |items: &mut Vec<(T, (Value, Value))>, run: usize, neq: &mut usize| {
                if *neq > 0 {
                    let count = *neq + 1;
                    items[run - count..run].reverse();
                    *neq = 0;
                }
            };
            while run < n {
                if lt(items, run, run - 1)? {
                    reverse_last(items, run, &mut neq);
                } else if lt(items, run - 1, run)? {
                    break;
                } else {
                    neq += 1;
                }
                run += 1;
            }
            reverse_last(items, run, &mut neq);
            items[..run].reverse();
            while run < n {
                if lt(items, run, run - 1)? {
                    break;
                }
                run += 1;
            }
        }
    }
    // binarysort(lo, n, run)
    let mut ok = run.max(1);
    while ok < n {
        let (mut low, mut high) = (0usize, ok);
        let pivot = items[ok].clone();
        while low < high {
            let middle = (low + high) >> 1;
            if key_less(&pivot.1, &items[middle].1)? {
                high = middle;
            } else {
                low = middle + 1;
            }
        }
        items.remove(ok);
        items.insert(low, pivot);
        ok += 1;
    }
    Ok(())
}

fn or_default(value: &Value, default: Value) -> Value {
    if sql::truthy(value) {
        value.clone()
    } else {
        default
    }
}

/// `_cut_off(records, turn_id, parent)`: core's interruption of `turn_id` - or, failing that, the one whose parent is
/// `parent` - the earliest detected.
fn cut_off<'a>(
    records: &'a [Value],
    turn: &Value,
    parent: &Value,
) -> Result<Option<&'a Value>, Unreadable> {
    let mut found: Vec<&Value> = records
        .iter()
        .filter(|record| sql::py_eq(field(record, "turn_id"), turn))
        .collect();
    if found.is_empty() && !matches!(parent, Value::Null) {
        found = records
            .iter()
            .filter(|record| sql::py_eq(field(record, "parent_interruption_id"), parent))
            .collect();
    }
    let mut keyed: Vec<(&Value, (Value, Value))> = found
        .into_iter()
        .map(|record| {
            let key = (
                or_default(field(record, "detected_at"), Value::Int(0.into())),
                or_default(field(record, "interruption_id"), word("")),
            );
            (record, key)
        })
        .collect();
    sort_keyed(&mut keyed)?;
    Ok(keyed.first().map(|(record, _)| *record))
}

fn status_end(status: &Value) -> Result<&'static str, Unreadable> {
    hashable(status)?;
    Ok(match status {
        Value::Str(text) => match text.as_str() {
            Some("inProgress") => RUNNING,
            Some("completed") => COMPLETED,
            Some("failed") => FAILED,
            Some("interrupted") => INTERRUPTED,
            _ => UNKNOWN,
        },
        _ => UNKNOWN,
    })
}

/// A turn's status (None for no such turn); an `Err` is one that cannot be read.
pub type StatusOf<'a> = &'a mut dyn FnMut(&Value, &Value) -> Result<Value, Raised>;
/// The conversation's newest turn's id (None for none); an `Err` is one that cannot be read.
pub type LatestOf<'a> = &'a mut dyn FnMut(&Value) -> Result<Value, Raised>;

/// `end_of(task, records, status_of, latest_of=None)`: how the task stands (ENDS).
pub fn end_of(
    task: &Value,
    records: &[Value],
    status_of: StatusOf<'_>,
    latest_of: Option<LatestOf<'_>>,
) -> &'static str {
    let mut latest_of = latest_of;
    end_walk(task, records, status_of, &mut latest_of).unwrap_or(UNKNOWN)
}

fn end_walk(
    task: &Value,
    records: &[Value],
    status_of: StatusOf<'_>,
    latest_of: &mut Option<LatestOf<'_>>,
) -> Result<&'static str, Unreadable> {
    let thread = field(task, "thread_id").clone();
    let mut turn = field(task, "turn_id").clone();
    let mut parent = Value::Null;
    let mut seen: Vec<Value> = Vec::new();
    for _ in 0..STEPS {
        let Some(record) = cut_off(records, &turn, &parent)? else {
            let status = status_of(&thread, &turn).map_err(|_| Unreadable)?;
            return status_end(&status);
        };
        let key = field(record, "interruption_id").clone();
        hashable(&key)?;
        if seen.iter().any(|known| sql::py_eq(known, &key)) {
            return Ok(UNKNOWN);
        }
        seen.push(key.clone());
        let state = field(record, "state");
        hashable(state)?;
        let named = |words: &[&str]| car_store::value::is_in(state, words);
        if named(WAITING) || !named(TERMINAL) {
            return Ok(RUNNING);
        }
        if named(&["recovered", "resumed"]) {
            let following = field(record, "recovery_turn_id");
            if !ids::is_uuid(following) {
                return Ok(RUNNING);
            }
            turn = following.clone();
            parent = key;
            continue;
        }
        if named(&CONTINUED)
            && let Some(latest) = latest_of.as_mut()
        {
            let following = latest(&thread).map_err(|_| Unreadable)?;
            if ids::is_uuid(&following) && following != turn {
                turn = following;
                parent = key;
                continue;
            }
        }
        let status = status_of(&thread, &turn).map_err(|_| Unreadable)?;
        return Ok(if status == word("interrupted") {
            INTERRUPTED
        } else {
            FAILED
        });
    }
    Ok(UNKNOWN)
}

/// `judge(ends, failed, interrupted)`: UNKNOWN if any cannot be read, RUNNING while any runs, MET when each ended in an
/// ending counted, else NOT_MET.
pub fn judge(ends: &[Value], failed: bool, interrupted: bool) -> &'static str {
    let is = |end: &Value, name: &str| *end == word(name);
    if ends.is_empty()
        || ends
            .iter()
            .any(|end| !ENDS.iter().any(|name| is(end, name)) || is(end, UNKNOWN))
    {
        return PowerTasks::Unknown.as_str();
    }
    if ends.iter().any(|end| is(end, RUNNING)) {
        return PowerTasks::Running.as_str();
    }
    let counted = |end: &Value| {
        is(end, COMPLETED) || (failed && is(end, FAILED)) || (interrupted && is(end, INTERRUPTED))
    };
    if ends.iter().all(counted) {
        PowerTasks::Met.as_str()
    } else {
        PowerTasks::NotMet.as_str()
    }
}

// ---------------------------------------------------------------------------------------------- the code
/// Codex's turn history as the capability reads it (`codex/turns.Turns`' shape): `status` always, `latest` where the
/// object has one (`getattr(turns, "latest", None)`).
pub trait TurnHistory {
    fn status(&mut self, thread: &Value, turn: &Value) -> Result<Value, Raised>;
    /// Whether the history has a `latest` at all.
    fn has_latest(&self) -> bool {
        true
    }
    /// The newest turn's id (None for none).
    fn latest(&mut self, thread: &Value) -> Result<Value, Raised>;
}

impl TurnHistory for crate::codex::turns::Turns {
    fn status(&mut self, thread: &Value, turn: &Value) -> Result<Value, Raised> {
        match crate::codex::turns::Turns::status(self, thread, turn) {
            Ok(found) => Ok(found.map(|text| word(&text)).unwrap_or(Value::Null)),
            Err(_) => Err(Raised::new("TurnsUnavailable")),
        }
    }
    fn latest(&mut self, thread: &Value) -> Result<Value, Raised> {
        match crate::codex::turns::Turns::latest(self, thread) {
            Ok(found) => Ok(found.map(|turn| word(&turn.turn_id)).unwrap_or(Value::Null)),
            Err(_) => Err(Raised::new("TurnsUnavailable")),
        }
    }
}

/// `records()`: core's interruptions, every one; an `Err` where they cannot be read.
pub type Records = Box<dyn FnMut() -> Result<Vec<Value>, Raised> + Send>;
/// `turns()`: the turn history of the home the watcher drives; an `Err` is the reference's raise there.
pub type MakeTurns = Box<dyn FnMut() -> Result<Box<dyn TurnHistory>, Raised> + Send>;

/// `core_records(paths)`: core's interruptions, every one; [] where core's state is not there yet.
pub fn core_records(paths: &Paths) -> Result<Vec<Value>, Raised> {
    let state = Path::new(&paths.state_dir);
    if !state.join("state.sqlite").is_file() {
        return Ok(Vec::new());
    }
    let store = car_store::session::Store::open(state, std::sync::Arc::new(car_control::host::Probe))
        .map_err(|_| Raised::new("StoreError"))?;
    let rows = store.all_records().map_err(|_| Raised::new("StoreError"))?;
    Ok(rows.into_iter().map(Value::Object).collect())
}

/// `PowerAfterTasks(paths, records=..., turns=...)`: its answer at P21.
pub struct PowerAfterTasks {
    paths: Paths,
    records: Records,
    turns: MakeTurns,
}

impl PowerAfterTasks {
    pub fn new(paths: Paths, records: Records, turns: MakeTurns) -> PowerAfterTasks {
        PowerAfterTasks {
            paths,
            records,
            turns,
        }
    }

    /// `stand(document)`: each task's end, every task UNKNOWN where core's records cannot be read.
    pub fn stand(&mut self, document: &Value) -> Result<Vec<&'static str>, Raised> {
        let Value::Array(tasks) = field(document, "tasks") else {
            return Ok(Vec::new());
        };
        let Ok(records) = (self.records)() else {
            return Ok(tasks.iter().map(|_| UNKNOWN).collect());
        };
        let mut turns = (self.turns)()?;
        let mut found = Vec::new();
        for task in tasks {
            let own: Vec<Value> = records
                .iter()
                .filter(|record| sql::py_eq(field(record, "thread_id"), field(task, "thread_id")))
                .cloned()
                .collect();
            let has_latest = turns.has_latest();
            let history = std::cell::RefCell::new(&mut turns);
            let mut status_of =
                |thread: &Value, turn: &Value| history.borrow_mut().status(thread, turn);
            let mut latest_of = |thread: &Value| history.borrow_mut().latest(thread);
            let end = if has_latest {
                end_of(task, &own, &mut status_of, Some(&mut latest_of))
            } else {
                end_of(task, &own, &mut status_of, None)
            };
            found.push(end);
        }
        Ok(found)
    }

    /// P21: `{"tasks": PowerTasks word, "threads": the list's conversations}`.
    pub fn answer(&mut self, facts: &Value) -> Spoke {
        let nonce = field(facts, "nonce");
        let unknown = || {
            let mut said = Map::new();
            said.insert("tasks".into(), word(PowerTasks::Unknown.as_str()));
            said.insert("threads".into(), Value::Array(Vec::new()));
            Ok(Said::Value(Value::Object(said)))
        };
        let Some(document) = read(&self.paths) else {
            return unknown();
        };
        if !ids::is_power_nonce(nonce) || *field(&document, "nonce") != *nonce {
            return unknown();
        }
        let ends: Vec<Value> = self.stand(&document)?.into_iter().map(word).collect();
        let flag = |name: &str| matches!(field(&document, name), Value::Bool(true));
        let mut said = Map::new();
        said.insert(
            "tasks".into(),
            word(judge(&ends, flag("failed"), flag("interrupted"))),
        );
        let threads = match field(&document, "tasks") {
            Value::Array(tasks) => tasks
                .iter()
                .map(|task| field(task, "thread_id").clone())
                .collect(),
            _ => Vec::new(),
        };
        said.insert("threads".into(), Value::Array(threads));
        Ok(Said::Value(Value::Object(said)))
    }
}

impl Code for PowerAfterTasks {
    fn power(&mut self, facts: &Value) -> Spoke {
        self.answer(facts)
    }
}

/// `make(paths)`: core's interruptions from its store, and the turn history of the home `inuse.home` names.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    let reading = paths.clone();
    let homes = paths.clone();
    Some(Box::new(PowerAfterTasks::new(
        paths.clone(),
        Box::new(move || core_records(&reading)),
        Box::new(move || {
            let home = super::supervise::codex_home(&homes)?;
            Ok(Box::new(crate::codex::turns::Turns::new(
                &home,
                std::sync::Arc::new(car_codex::system::PolicyOs),
            )) as Box<dyn TurnHistory>)
        }),
    )))
}

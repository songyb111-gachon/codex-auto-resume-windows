//! `codex/rollout.py`: a conversation's rollout file, read no further than this product needs (v0.6.16-beta.3).
//!
//! None of these readings is a statement to a database - `history.rs` keeps every one:
//!
//! * `confined`       which file a `threads` row's path names, if it is that conversation's in the sessions folder
//! * `session_meta`   the file's first line: who the conversation says it is
//! * `continued_id`   the id Codex records the conversation's turns under, where it split them
//! * `earlier`        the ids it recorded them under before, by the names of its earlier files
//! * `named_after`    the conversations whose file names an id as theirs, by name
//! * `reset_scan`     the rate-limit snapshots just before a usage-limit failure, for the reset hint
//! * `superseded_in`  whether a person's message came after a failed turn's end, for Rescan and reconcile (issue #39)
//! * `turn_trigger`   how Codex says a turn was started - "composer" is the person's input box (issue #54)
//!
//! The split is Codex's (openai/codex#43422, this project's issue #30): the `threads` row keeps the conversation's id
//! A, but its current file is named `..._A_B.jsonl` and its turns are projected under B, which has no row of its own -
//! and a later split names `..._A_C.jsonl` while B's turns stay under B. Its turns are every id's, in that order
//! (`SPAN`); whether an id is taken is `history.rs`'s (`chain`), with every guard. Only file names are looked at
//! here, never a file's contents.

use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::{LazyLock, Mutex, MutexGuard};
use std::time::Instant;

use car_config::winpath;
use car_machine::domain::ids;
use car_machine::json::{Int, Map, Str, Value};
use car_machine::pyval;
use car_policy::settings::os::Os;
use indexmap::IndexMap;

use crate::errors::Result;
use crate::paths::{child, name_of, safe_path};
use crate::payload::{choose_reset, unknown_reset};
use crate::values::{MAX_ITEM_BYTES, MAX_META_BYTES, MAX_SCAN_BYTES, json_text};

/// What `superseded_in` finds (v0.6.16, issue #39): a person's message after the failed turn's own end; that end and
/// nothing of a person's after it; not that end at all; a file over RESCAN_BYTES; a file that cannot be read; and a
/// rollback - or a line that cannot be read - after that end, past which nothing in the file is proof of anything.
pub const LATER_MESSAGE: &str = "later_message";
pub const NOTHING_LATER: &str = "nothing_later";
pub const NO_ANCHOR: &str = "no_anchor";
pub const TOO_LARGE: &str = "too_large";
pub const UNREADABLE: &str = "unreadable";
pub const ROLLED_BACK: &str = "rolled_back";

/// What a rollback is written with (Codex's thread_rolled_back event): any line after the anchor that holds it.
const ROLLBACK: &[u8] = b"rolled_back";
/// The largest file it reads, start to end, only when a person asks for it.
pub const RESCAN_BYTES: u64 = 32 * 1024 * 1024;
const OURS: &[u8] = b"[codex-auto-resume:";
/// A turn's ordinal across a split conversation: the index of the id it is recorded under (A's own 0, then each split
/// id in order) times SPAN, plus its own rollout ordinal - so a turn of a later id always comes after every turn of an
/// earlier one, whatever Codex numbered it, and a conversation never split reads its ordinals as they are.
pub const SPAN: i128 = 1 << 40;
/// The split files of each Codex home by name, looked at again at most every LIST_SECONDS: one listing for every
/// conversation, names only.
pub const LIST_SECONDS: f64 = 60.0;
pub const AGAIN: usize = 5;

/// `time.monotonic()`: seconds from an origin of this process's own, for the caches below and for a caller's
/// deadline (`passed_over`).
pub fn monotonic() -> f64 {
    static START: LazyLock<Instant> = LazyLock::new(Instant::now);
    START.elapsed().as_secs_f64() + 1000.0
}

type Pairs = Vec<(String, String)>;
type Listing = IndexMap<String, Pairs>;

#[derive(Default)]
struct Caches {
    /// `_SPLITS`: home -> (when listed, {conversation id: ((split id, file), ...)}).
    splits: HashMap<String, (f64, std::sync::Arc<Listing>)>,
    /// `_ASKED`: what was asked of a fresh listing once already.
    asked: HashSet<Vec<String>>,
    /// `_RELISTED`: when each home was listed again for `named_after`.
    relisted: HashMap<String, Vec<f64>>,
    /// `_META`: the id an earlier file's first line says it is.
    meta: IndexMap<String, Option<String>>,
    /// `_TRIGGERS`: (file, turn id, size, mtime) -> the trigger found.
    triggers: IndexMap<TriggerKey, Option<String>>,
}

type TriggerKey = (String, Option<String>, Option<(u64, i128)>);

static CACHES: LazyLock<Mutex<Caches>> = LazyLock::new(|| Mutex::new(Caches::default()));

fn caches() -> MutexGuard<'static, Caches> {
    CACHES
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Forget everything remembered (for a test of the reader, which is one process with many homes; the reference's
/// caches are module state, so a fresh process of either starts empty).
pub fn forget() {
    *caches() = Caches::default();
}

fn is_uuid(text: &str) -> bool {
    ids::is_uuid(&Value::from(text))
}

/// A UUID's text in either case: 8-4-4-4-12 hex digits.
fn uuid_any_case(text: &[char]) -> bool {
    if text.len() != 36 {
        return false;
    }
    text.iter().enumerate().all(|(at, each)| {
        if matches!(at, 8 | 13 | 18 | 23) {
            *each == '-'
        } else {
            each.is_ascii_hexdigit()
        }
    })
}

/// `(%s)_(%s)\.jsonl\Z` searched in a file name: (the first id, the second), both read in either case.
fn pair_of(name: &str) -> Option<(String, String)> {
    let chars: Vec<char> = name.chars().collect();
    if chars.len() < 79 {
        return None;
    }
    let tail = &chars[chars.len() - 79..];
    let (first, rest) = tail.split_at(36);
    let (separator, rest) = rest.split_at(1);
    let (second, suffix) = rest.split_at(36);
    (uuid_any_case(first)
        && separator[0] == '_'
        && uuid_any_case(second)
        && suffix.iter().collect::<String>() == ".jsonl")
        .then(|| (first.iter().collect(), second.iter().collect()))
}

/// `continued_id(thread_id, name)`: B, where the file name `name` ends exactly in `<thread_id>_<B>.jsonl` and B is
/// another id; else None.
pub fn continued_id(thread_id: &str, name: &str) -> Option<String> {
    if !is_uuid(thread_id) {
        return None;
    }
    let chars: Vec<char> = name.chars().collect();
    if chars.len() < 79 {
        return None;
    }
    let start = chars.len() - 79;
    // `(?:^|[-_])`: the match begins at the start of the name, or after one `-` or `_`.
    if start != 0 && !matches!(chars[start - 1], '-' | '_') {
        return None;
    }
    let wanted: Vec<char> = thread_id.chars().collect();
    if chars[start..start + 36] != wanted[..] || chars[start + 36] != '_' {
        return None;
    }
    let other = &chars[start + 37..start + 73];
    if !uuid_any_case(other) || chars[start + 73..].iter().collect::<String>() != ".jsonl" {
        return None;
    }
    let other: String = other.iter().collect();
    (is_uuid(&other) && other != thread_id).then_some(other)
}

/// The entries of a directory in the order Windows lists them, with whether each is a folder that is no symbolic link
/// (`DirEntry.is_dir(follow_symlinks=False)`: a junction is a folder).
fn scandir(os: &dyn Os, directory: &str) -> Option<Vec<(String, bool)>> {
    use std::os::windows::fs::MetadataExt;
    let mut found = Vec::new();
    for entry in std::fs::read_dir(directory).ok()? {
        let Ok(entry) = entry else {
            return None;
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        let folder = entry.metadata().is_ok_and(|facts| {
            facts.file_attributes() & 0x10 != 0 && !os.is_symlink(&entry.path())
        });
        found.push((name, folder));
    }
    Some(found)
}

fn named_like(name: &str) -> bool {
    name.contains('_') && name.ends_with(".jsonl")
}

/// `Path(directory).rglob("*_*.jsonl")`, in the order Python 3.13 yields it: the folder's own matches, then those of
/// each folder under it as the walk meets it - a stack, so the last folder of a listing is walked first.
fn rglob(os: &dyn Os, root: &str) -> Vec<String> {
    let mut found = Vec::new();
    let matches_in = |directory: &str, found: &mut Vec<String>| {
        if let Some(entries) = scandir(os, directory) {
            for (name, _) in entries {
                if named_like(&name) {
                    found.push(child(directory, &name));
                }
            }
        }
    };
    matches_in(root, &mut found);
    let mut stack = vec![root.to_owned()];
    while let Some(directory) = stack.pop() {
        let Some(entries) = scandir(os, &directory) else {
            continue;
        };
        for (name, folder) in entries {
            if folder {
                let path = child(&directory, &name);
                matches_in(&path, &mut found);
                stack.push(path);
            }
        }
    }
    found
}

/// `_splits(home, fresh)`: {conversation id: ((split id, file), ...) oldest first} for every file under the home's
/// sessions folder named `<id>_<id>.jsonl` - by name only, nothing opened, no link followed; none where it cannot be
/// listed.
fn splits(os: &dyn Os, home: &str, fresh: bool) -> std::sync::Arc<Listing> {
    let now = monotonic();
    if !fresh
        && let Some((at, held)) = caches().splits.get(home)
        && now - at <= LIST_SECONDS
    {
        return std::sync::Arc::clone(held);
    }
    let mut found: Listing = IndexMap::new();
    let mut names: Vec<(String, String)> = rglob(os, &child(home, "sessions"))
        .into_iter()
        .filter(|path| Path::new(path).is_file())
        .map(|path| (name_of(&path), path))
        .collect();
    names.sort_by(|a, b| a.0.cmp(&b.0));
    for (name, path) in names {
        if let Some((owner, other)) = pair_of(&name)
            && continued_id(&owner, &name).as_deref() == Some(other.as_str())
        {
            found.entry(owner).or_default().push((other, path));
        }
    }
    let held = std::sync::Arc::new(found);
    caches()
        .splits
        .insert(home.to_owned(), (now, std::sync::Arc::clone(&held)));
    held
}

/// `earlier(home, thread_id, current)`: ((id, file), ...): the ids before `current` that `thread_id`'s earlier files
/// name as `<thread_id>_<id>`, oldest first by file name (Codex starts each name with its time).
pub fn earlier(os: &dyn Os, home: &str, thread_id: &str, current: &str) -> Pairs {
    let mut pairs = splits(os, home, false)
        .get(thread_id)
        .cloned()
        .unwrap_or_default();
    let key = vec![home.to_owned(), thread_id.to_owned(), current.to_owned()];
    let asked = caches().asked.contains(&key);
    if !asked && pairs.iter().all(|pair| pair.0 != current) {
        let mut held = caches();
        if held.asked.len() > 4096 {
            held.asked.clear();
        }
        held.asked.insert(key);
        drop(held);
        // A split newer than the listing: list again, once.
        pairs = splits(os, home, true)
            .get(thread_id)
            .cloned()
            .unwrap_or_default();
    }
    pairs.into_iter().filter(|pair| pair.0 != current).collect()
}

/// `taken(chain, rows)`: the ids of `chain` that are no split id of the conversation's: one with a `threads` row of
/// its own, or one another conversation's file names (`rows`: (id, rollout_path) of those rows).
pub fn taken(chain: &[String], rows: &[(Option<String>, Option<String>)]) -> HashSet<String> {
    chain
        .iter()
        .filter(|other| {
            rows.iter().any(|(row_id, path)| {
                row_id.as_deref() == Some(other.as_str())
                    || path
                        .as_deref()
                        .is_some_and(|text| text.contains(other.as_str()))
            })
        })
        .cloned()
        .collect()
}

/// `meta_id(path)`: the id an earlier file's first line says it is (`session_meta`), read once and remembered - None
/// for none.
pub fn meta_id(path: &str) -> Option<String> {
    if let Some(held) = caches().meta.get(path) {
        return held.clone();
    }
    let Ok(payload) = session_meta(path) else {
        return None;
    };
    let id = match payload {
        Some(map) if !map.is_empty() => match map.get("id") {
            Some(Value::Str(text)) => text.as_str().map(str::to_owned),
            _ => None,
        },
        _ => None,
    };
    let mut held = caches();
    if held.meta.len() >= 4096 {
        held.meta.shift_remove_index(0);
    }
    held.meta.insert(path.to_owned(), id.clone());
    id
}

/// `named_after(home, turns_id)`: the conversation ids whose files, by name and first line, hold `turns_id`'s turns
/// (`<id>_<turns_id>.jsonl`) - listed again, once for each id and at most AGAIN times a minute, where the listing
/// names none: a split newer than the listing is found at once, and many ids no file names cost a few listings.
pub fn named_after(os: &dyn Os, home: &str, turns_id: &str) -> Vec<String> {
    // A file whose first line is another conversation's names no one.
    let named = |listing: &Listing| -> Vec<String> {
        listing
            .iter()
            .filter(|(owner, pairs)| {
                pairs.iter().any(|(other, file)| {
                    other == turns_id && meta_id(file).as_deref() == Some(owner.as_str())
                })
            })
            .map(|(owner, _)| owner.clone())
            .collect()
    };
    let mut found = named(&splits(os, home, false));
    let now = monotonic();
    let key = vec![home.to_owned(), turns_id.to_owned()];
    let again = {
        let mut held = caches();
        let recent = held.relisted.entry(home.to_owned()).or_default();
        recent.retain(|at| now - *at < LIST_SECONDS);
        let count = recent.len();
        let asked = held.asked.contains(&key);
        if found.is_empty() && !asked && count < AGAIN {
            if held.asked.len() > 4096 {
                held.asked.clear();
            }
            held.asked.insert(key);
            if let Some(recent) = held.relisted.get_mut(home) {
                recent.push(now);
            }
            true
        } else {
            false
        }
    };
    if again {
        found = named(&splits(os, home, true));
    }
    found
}

/// `placed(row, owner, index)`: a turn's row as its conversation's: `owner`'s id, and its ordinal across the split
/// (SPAN) - itself for a conversation never split, where `index` is 0.
pub fn placed(row: &Map, owner: &Value, index: usize) -> Map {
    let mut found = row.clone();
    let ordinal = row.get("rollout_ordinal").cloned().unwrap_or(Value::Null);
    found.insert(Str::from("thread_id"), owner.clone());
    let moved = match &ordinal {
        Value::Int(number) => {
            let base: i128 = number.to_string().parse().unwrap_or(0);
            Value::Int(
                Int::parse(&(index as i128 * SPAN + base).to_string())
                    .unwrap_or_else(|| Int::from(0)),
            )
        }
        other => other.clone(),
    };
    found.insert(Str::from("rollout_ordinal"), moved);
    found
}

/// `confined(home, thread_id, raw)`: `raw`, the rollout path Codex's `threads` row names, as a path if it is this
/// conversation's file in the Codex home `home`'s sessions folder: a .jsonl file whose name holds the id. None for
/// anything else, which is then neither opened nor asked about.
pub fn confined(os: &dyn Os, home: &str, thread_id: &str, raw: &Value) -> Result<Option<String>> {
    let Value::Str(raw) = raw else {
        return Ok(None);
    };
    if !is_uuid(thread_id) {
        return Ok(None);
    }
    let Some(raw) = raw.as_str() else {
        return Ok(None);
    };
    let path = safe_path(os, raw)?;
    let sessions = safe_path(os, &child(home, "sessions"))?;
    let name = name_of(&path);
    // `Path.suffix`: from the last dot, unless it is the first or the last character of the name.
    let suffix = match name.rfind('.') {
        Some(at) if at > 0 && at < name.len() - 1 => &name[at..],
        _ => "",
    };
    if !winpath::is_relative_to(&path, &sessions) || suffix != ".jsonl" || !name.contains(thread_id)
    {
        return Ok(None);
    }
    Ok(Some(path))
}

/// `Path.open("rb").readline(limit)`: up to `limit` bytes, through the first newline.
fn readline<R: BufRead>(stream: &mut R, limit: usize) -> std::io::Result<Vec<u8>> {
    let mut line = Vec::new();
    while line.len() < limit {
        let buffer = stream.fill_buf()?;
        if buffer.is_empty() {
            break;
        }
        let room = limit - line.len();
        let window = &buffer[..buffer.len().min(room)];
        match window.iter().position(|byte| *byte == b'\n') {
            Some(at) => {
                line.extend_from_slice(&window[..=at]);
                stream.consume(at + 1);
                break;
            }
            None => {
                line.extend_from_slice(window);
                let used = window.len();
                stream.consume(used);
            }
        }
    }
    Ok(line)
}

/// `session_meta(path)`: the payload of the file's first line where it is a session_meta event, or None. An OSError is
/// the caller's: a file that cannot be opened now is not a file that says nothing.
pub fn session_meta(path: &str) -> Result<Option<Map>> {
    let mut stream = BufReader::new(std::fs::File::open(path)?);
    let first = readline(&mut stream, MAX_META_BYTES + 1)?;
    if first.len() > MAX_META_BYTES || !first.ends_with(b"\n") {
        return Ok(None);
    }
    let Ok(text) = String::from_utf8(first) else {
        return Ok(None);
    };
    let Some(Value::Object(event)) = json_text(&text) else {
        return Ok(None);
    };
    if !event
        .get("type")
        .is_some_and(|word| pyval::is(word, "session_meta"))
    {
        return Ok(None);
    }
    Ok(match event.get("payload") {
        Some(Value::Object(payload)) => Some(payload.clone()),
        _ => None,
    })
}

fn bucket_name(text: &Str) -> bool {
    let Some(word) = text.as_str() else {
        return false;
    };
    (1..=64).contains(&word.chars().count())
        && word
            .chars()
            .all(|each| each.is_ascii_alphanumeric() || matches!(each, '_' | '-'))
}

/// `bytes.splitlines()`: the lines of a byte string, broken at `\n`, `\r` and `\r\n`.
fn split_lines(data: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut at = 0;
    while at < data.len() {
        match data[at] {
            b'\n' => {
                lines.push(&data[start..at]);
                at += 1;
                start = at;
            }
            b'\r' => {
                lines.push(&data[start..at]);
                at += if data.get(at + 1) == Some(&b'\n') {
                    2
                } else {
                    1
                };
                start = at;
            }
            _ => at += 1,
        }
    }
    if start < data.len() {
        lines.push(&data[start..]);
    }
    lines
}

/// `reset_scan(path, end, turn_id, completed_at)`: the reset hint of the usage-limit failure of `turn_id`, whose
/// event ends at byte `end` of `path`: the rate-limit snapshots before it, chosen as `choose_reset` chooses - or
/// UNKNOWN_RESET.
pub fn reset_scan(path: &str, end: &Value, turn_id: &str, completed_at: &Value) -> pyval::Py<Map> {
    let Value::Int(end) = end else {
        return Ok(unknown_reset());
    };
    let Some(end) = end.as_i64().filter(|each| *each > 0) else {
        // An int past i64 is a positive end no file reaches: the whole of the last MAX_SCAN_BYTES, as Python reads it.
        return if end.to_string().starts_with('-')
            || end.as_u64().is_none() && end.to_string() == "0"
        {
            Ok(unknown_reset())
        } else {
            read_scan(path, u64::MAX, turn_id, completed_at)
        };
    };
    read_scan(path, end as u64, turn_id, completed_at)
}

fn read_scan(path: &str, end: u64, turn_id: &str, completed_at: &Value) -> pyval::Py<Map> {
    let data = (|| -> std::io::Result<Option<Vec<u8>>> {
        // The verified end offset is immediately after the failure event. Never include a subsequent turn's
        // unrelated rate-limit snapshot.
        let mut stream = BufReader::new(std::fs::File::open(path)?);
        let start = end.saturating_sub(MAX_SCAN_BYTES as u64);
        stream.seek(SeekFrom::Start(start))?;
        if start != 0 {
            readline(&mut stream, MAX_ITEM_BYTES + 1)?;
        }
        let position = stream.stream_position()?;
        if end <= position {
            return Ok(None);
        }
        let remaining = end - position;
        let mut data = Vec::new();
        stream
            .take(remaining.min(MAX_SCAN_BYTES as u64))
            .read_to_end(&mut data)?;
        Ok(Some(data))
    })();
    let Ok(Some(data)) = data else {
        return Ok(unknown_reset());
    };
    let mut buckets = Map::new();
    let mut found = false;
    for line in split_lines(&data) {
        if line.len() > MAX_ITEM_BYTES {
            continue;
        }
        let Ok(text) = std::str::from_utf8(line) else {
            continue;
        };
        let Some(Value::Object(event)) = json_text(text) else {
            continue;
        };
        if !event
            .get("type")
            .is_some_and(|word| pyval::is(word, "event_msg"))
        {
            continue;
        }
        let Some(Value::Object(payload)) = event.get("payload") else {
            continue;
        };
        let kind = payload.get("type");
        if kind.is_some_and(|word| pyval::is(word, "task_complete"))
            && payload
                .get("turn_id")
                .is_some_and(|held| pyval::is(held, turn_id))
        {
            found = matches!(payload.get("error"), Some(Value::Object(error))
                if error.get("codex_error_info").is_some_and(|held| pyval::is(held, "usage_limit_exceeded")));
            break;
        }
        if kind.is_some_and(|word| pyval::is(word, "token_count"))
            && let Some(Value::Object(limits)) = payload.get("rate_limits")
            && let Some(Value::Str(bucket)) = limits.get("limit_id")
            && bucket_name(bucket)
        {
            buckets.insert(bucket.clone(), Value::Object(limits.clone()));
        }
    }
    if found {
        choose_reset(&Value::Object(buckets), completed_at)
    } else {
        Ok(unknown_reset())
    }
}

/// `superseded_in(path, turn_id, limit)`: whether the file holds the exact end of the failed turn `turn_id` - its own
/// task_complete event - and, after it, a person's message: a user_message event that carries no marker of this
/// product's. Read only on a person's Rescan and reconcile, and only while Codex's history has not caught up with the
/// file: the file whole, up to `limit` bytes, one line at a time, each line parsed and dropped. Nothing of what a line
/// says is kept; the answer is one of six words.
///
/// A line over MAX_ITEM_BYTES, a line that is not JSON and any event but those two are passed over, which can only
/// lose an answer, never make one: no anchor, nothing later. Where a person's message comes before that end, it is not
/// after it, so a conversation's earlier work - or a file that replays it (a split's, issue #30) - proves nothing.
///
/// A rollback undoes turns, and only Codex's history - which the engine reads, and which a rollback rewrites - says
/// which. So the whole file is read, and a rollback anywhere after the anchor (`ROLLBACK`, whatever its event), or a
/// line after it that cannot be read and so could be one, means nothing after the anchor proves anything:
/// ROLLED_BACK, never LATER_MESSAGE, though a person's message came before it.
pub fn superseded_in(path: &str, turn_id: &str, limit: Option<u64>) -> &'static str {
    let read = || -> std::io::Result<(bool, bool, bool, bool)> {
        let size = std::fs::metadata(path)?.len();
        if size > limit.unwrap_or(RESCAN_BYTES) {
            return Ok((true, false, false, false));
        }
        let (mut anchored, mut later, mut doubt, mut read) = (false, false, false, 0u64);
        let mut stream = BufReader::new(std::fs::File::open(path)?);
        while read < size {
            let mut line = readline(&mut stream, MAX_ITEM_BYTES + 1)?;
            if line.is_empty() {
                break;
            }
            read += line.len() as u64;
            if line.len() > MAX_ITEM_BYTES {
                // The rest of a line too long to read.
                while !line.is_empty() && !line.ends_with(b"\n") {
                    line = readline(&mut stream, MAX_ITEM_BYTES + 1)?;
                    read += line.len() as u64;
                }
                doubt = doubt || anchored;
                continue;
            }
            if anchored && contains(&line, ROLLBACK) {
                doubt = true;
                continue;
            }
            if !contains(&line, b"\"event_msg\"") {
                continue;
            }
            let event = std::str::from_utf8(&line).ok().and_then(json_text);
            let Some(Value::Object(event)) = event else {
                doubt = doubt || anchored;
                continue;
            };
            let payload = if event
                .get("type")
                .is_some_and(|word| pyval::is(word, "event_msg"))
            {
                event.get("payload")
            } else {
                None
            };
            let Some(Value::Object(payload)) = payload else {
                continue;
            };
            if !anchored {
                anchored = payload
                    .get("type")
                    .is_some_and(|word| pyval::is(word, "task_complete"))
                    && payload
                        .get("turn_id")
                        .is_some_and(|held| pyval::is(held, turn_id));
            } else if payload
                .get("type")
                .is_some_and(|word| pyval::is(word, "user_message"))
                && !contains(&line, OURS)
            {
                later = true;
            }
        }
        Ok((false, anchored, later, doubt))
    };
    match read() {
        Err(_) => UNREADABLE,
        Ok((true, ..)) => TOO_LARGE,
        Ok((false, false, ..)) => NO_ANCHOR,
        Ok((false, true, later, doubt)) => {
            if doubt {
                ROLLED_BACK
            } else if later {
                LATER_MESSAGE
            } else {
                NOTHING_LATER
            }
        }
    }
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window == needle)
}

/// `turn_trigger(path, turn_id)`: the turn_attribution.turn_trigger Codex wrote for the turn `turn_id` in its
/// task_started event (issue #54, measured on codex-cli 0.164) - else for the last turn the file starts: the file read
/// once, a line at a time, each dropped after it is looked at - from its last RESCAN_BYTES on (v0.6.23, audit C4),
/// where the latest turns are. None is unknown - an older Codex wrote no attribution, the turn is not in what was
/// read, the file cannot be read - and is never a value; an OSError is the caller's, as session_meta's is.
pub fn turn_trigger(path: &str, turn_id: Option<&str>) -> Result<Option<String>> {
    if let Some(turn) = turn_id
        && !is_uuid(turn)
    {
        return Ok(None);
    }
    let facts = std::fs::metadata(path)?;
    let size = facts.len();
    // The last turn's answer is the file's as it stands (size and time), nothing found included; a turn's is its own
    // for good.
    let stamp = crate::chains::mtime_ns(Path::new(path));
    let key: TriggerKey = match turn_id {
        Some(turn) => (path.to_owned(), Some(turn.to_owned()), None),
        None => (path.to_owned(), None, Some((size, stamp.unwrap_or(0)))),
    };
    if let Some(held) = caches().triggers.get(&key) {
        return Ok(held.clone());
    }
    let wanted = turn_id.map(str::as_bytes);
    let mut found: Option<String> = None;
    let mut stream = BufReader::new(std::fs::File::open(path)?);
    if size > RESCAN_BYTES {
        // From RESCAN_BYTES before the end, the line cut there dropped unless the cut falls on a line's start.
        stream.seek(SeekFrom::Start(size - RESCAN_BYTES - 1))?;
        let mut line = vec![0u8; 0];
        let mut one = [0u8; 1];
        let read = stream.read(&mut one)?;
        line.extend_from_slice(&one[..read]);
        while !line.is_empty() && !line.ends_with(b"\n") {
            line = readline(&mut stream, MAX_ITEM_BYTES + 1)?;
        }
    }
    loop {
        let mut line = readline(&mut stream, MAX_ITEM_BYTES + 1)?;
        if line.is_empty() {
            break;
        }
        if line.len() > MAX_ITEM_BYTES {
            while !line.is_empty() && !line.ends_with(b"\n") {
                line = readline(&mut stream, MAX_ITEM_BYTES + 1)?;
            }
            continue;
        }
        if !contains(&line, b"\"task_started\"")
            || wanted.is_some_and(|turn| !contains(&line, turn))
        {
            continue;
        }
        let Some(text) = std::str::from_utf8(&line).ok() else {
            continue;
        };
        let event = json_text(text);
        let payload = match &event {
            Some(Value::Object(map))
                if map
                    .get("type")
                    .is_some_and(|word| pyval::is(word, "event_msg")) =>
            {
                map.get("payload")
            }
            _ => None,
        };
        let Some(Value::Object(payload)) = payload else {
            continue;
        };
        if !payload
            .get("type")
            .is_some_and(|word| pyval::is(word, "task_started"))
        {
            continue;
        }
        if let Some(turn) = turn_id
            && !payload
                .get("turn_id")
                .is_some_and(|held| pyval::is(held, turn))
        {
            continue;
        }
        let value = match payload.get("turn_attribution") {
            Some(Value::Object(attribution)) => attribution.get("turn_trigger"),
            _ => None,
        };
        found = match value {
            Some(Value::Str(text)) => text.as_str().map(str::to_owned),
            _ => None,
        };
        if turn_id.is_some() {
            break;
        }
    }
    if found.is_some() || turn_id.is_none() {
        let mut held = caches();
        if held.triggers.len() >= 4096 {
            held.triggers.shift_remove_index(0);
        }
        held.triggers.insert(key, found.clone());
    }
    Ok(found)
}

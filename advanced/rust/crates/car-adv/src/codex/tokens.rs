//! `codex/tokens.py`: the tokens a conversation used, read from its rollout - four numbers and a count, never a word
//! (v0.6.20, usage_analytics; seat adv72d).
//!
//! Only `token_count` and `task_started` events are parsed, and only a line at most [`LINE_BYTES`] that holds the bytes
//! `"token_count"` or `"task_started"`; of them only the four counts and the local day the event fell on are kept. Each
//! file is read `rb` from where the last pass stopped, at most [`FILE_BYTES`] of it (and the caller's budget). The
//! conversation is the one the file's first line names (car-codex's `session_meta`), its project the 16-hex digest of
//! the folder that line names (car-policy's `projects::key_for`). Files: `.jsonl` under each watched home's
//! `sessions`, changed in the last [`KEEP_DAYS`], never a link, never one resolving outside that folder.
//!
//! The local day is `time.strftime("%Y-%m-%d", local(at))` with `local` the caller's [`LocalClock`] (the product's is
//! car-platform's `Crt`, the C runtime's `localtime` as CPython calls it, TZ and all); its refusal (a time before 1970
//! on Windows) is the reference's uncaught OSError, here `Err("OSError")`.

use std::io::{Read as _, Seek, SeekFrom};
use std::os::windows::fs::MetadataExt;
use std::path::Path;

use car_codex::paths::safe_path;
use car_codex::rollout::session_meta;
use car_machine::domain::ids;
use car_machine::hash;
use car_machine::json::{Map, Value};
use car_machine::localclock::LocalClock;
use car_machine::pyval;
use car_machine::winpath::{self, Env};
use car_platform::links::{MOUNT_POINT_TAG, SYMLINK_TAG, reparse_tag};
use car_platform::paths::{normcase, pathlib_text};
use car_policy::settings::os::Os;

/// Read of one file in one pass, at most.
pub const FILE_BYTES: i64 = 2 * 1024 * 1024;
/// Read of every file together in one pass, at most.
pub const PASS_BYTES: i64 = 8 * 1024 * 1024;
/// A longer line is passed over unparsed.
pub const LINE_BYTES: usize = 64 * 1024;
/// How far before where a pass begins it looks for the totals seen last.
pub const LOOK_BACK: i64 = 256 * 1024;
/// A file not changed in this long is not read.
pub const KEEP_DAYS: i64 = 90;
pub const TOKEN_BYTES: &[u8] = b"\"token_count\"";
pub const TURN_BYTES: &[u8] = b"\"task_started\"";
/// The four kinds kept, in the order a day holds them.
pub const KINDS: [&str; 4] = [
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
];
/// A count larger than this is no count Codex wrote.
pub const MOST: i64 = 10_000_000_000_000;
pub const READ: &str = "read";
pub const CAPPED: &str = "capped";
pub const UNREADABLE: &str = "unreadable";
pub const UNCHANGED: &str = "unchanged";
/// How many files under one home's sessions folder are looked at, at most.
pub const FILES_LIMIT: usize = 20000;

/// A rollout to read: its home, its path, its key and what its stat said.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rollout {
    pub home: String,
    pub path: String,
    pub key: String,
    pub size: i64,
    pub changed_ns: i128,
}

/// What one pass read of one file: the numbers by local day - `(day, [input, cached, output, reasoning, turns])` in
/// the order the days were first met - and where the next pass begins.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Read {
    pub key: String,
    pub thread_id: Option<String>,
    pub size: i64,
    pub offset: i64,
    pub changed_ns: i128,
    pub days: Vec<(String, [i64; 5])>,
    pub project_key: Option<String>,
    pub outcome: &'static str,
    pub consumed: i64,
}

/// `file_key(path)`: the first 16 hex digits of the SHA-256 of its resolved, case-folded path.
pub fn file_key(os: &dyn Os, path: &str) -> Result<String, car_codex::errors::Error> {
    let resolved = normcase(&safe_path(os, path)?);
    Ok(hash::hex(&hash::sha256(resolved.as_bytes()))[..16].to_owned())
}

/// `watched_homes(paths)`: the default home (the watcher's, as told - `inuse::home`), then those Settings add, each
/// once (by the case-folded resolved path); a home that cannot be named is left out. The homes as pathlib writes them.
pub fn watched_homes(
    installation: Option<&str>,
    settings_file: Option<&Path>,
    env: Env,
    config_os: &car_config::Os,
    os: &dyn Os,
) -> Vec<String> {
    let mut found = Vec::new();
    if let Ok(home) = super::inuse::home(installation, env, config_os) {
        found.push(pathlib_text(&home));
    }
    let extra = settings_file
        .and_then(|file| car_policy::settings::load(os, file).ok())
        .map(|settings| {
            let field = match settings.get(car_policy::settings::homes::FIELD) {
                Some(value) if pyval::truthy(value) => value.clone(),
                _ => Value::Array(Vec::new()),
            };
            car_policy::settings::homes::coerce(os, &field, &Value::Array(Vec::new()))
        })
        .unwrap_or(Value::Array(Vec::new()));
    if let Value::Array(entries) = extra {
        for entry in entries {
            if let Value::Object(entry) = entry
                && let Some(Value::Str(path)) = entry.get("path")
            {
                found.push(pathlib_text(&String::from_utf8_lossy(path.as_bytes())));
            }
        }
    }
    let mut unique: Vec<String> = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for home in found {
        let Ok(resolved) = safe_path(os, &home) else {
            continue;
        };
        let marker = normcase(&resolved);
        if !seen.contains(&marker) {
            seen.push(marker);
            unique.push(home);
        }
    }
    unique
}

/// `_is_link(entry)`: a symbolic link, or a junction; one that cannot be looked at counts as a link.
fn is_link(path: &Path) -> bool {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return true;
    };
    if metadata.file_attributes() & 0x400 == 0 {
        return false;
    }
    match reparse_tag(path) {
        Some(tag) => tag == SYMLINK_TAG || tag == MOUNT_POINT_TAG,
        None => true,
    }
}

/// os.stat's `st_mtime_ns` of a FILETIME.
fn mtime_ns(metadata: &std::fs::Metadata) -> i128 {
    (i128::from(metadata.last_write_time()) - 116_444_736_000_000_000) * 100
}

/// `rollouts(homes, now, keep_days)`: the rollouts to read, newest first. `Err` where a found file's key cannot be
/// made (the reference calls `file_key` outside its `try`).
pub fn rollouts(
    os: &dyn Os,
    homes: &[String],
    now: f64,
    keep_days: i64,
) -> Result<Vec<Rollout>, &'static str> {
    let mut found = Vec::new();
    let since_ns = ((now - (keep_days * 86400) as f64) * 1e9) as i128;
    for home in homes {
        let Ok(root) = safe_path(os, &winpath::join(home, "sessions")) else {
            continue;
        };
        if !Path::new(&root).is_dir() {
            continue;
        }
        let mut stack = vec![root.clone()];
        let mut seen = 0usize;
        while seen < FILES_LIMIT {
            let Some(folder) = stack.pop() else {
                break;
            };
            let Ok(listing) = std::fs::read_dir(&folder) else {
                continue;
            };
            let entries: Vec<String> = listing
                .filter_map(Result::ok)
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .collect();
            for name in entries {
                let entry_path = winpath::join(&folder, &name);
                if is_link(Path::new(&entry_path)) {
                    continue;
                }
                let Ok(metadata) = std::fs::symlink_metadata(&entry_path) else {
                    continue;
                };
                if metadata.file_attributes() & 0x10 != 0 {
                    stack.push(entry_path);
                    continue;
                }
                if !name.ends_with(".jsonl") {
                    continue;
                }
                seen += 1;
                let Ok(path) = safe_path(os, &entry_path) else {
                    continue;
                };
                if !winpath::is_relative_to(&path, &root) || mtime_ns(&metadata) < since_ns {
                    continue;
                }
                let key = file_key(os, &path).map_err(|_| "OSError")?;
                found.push(Rollout {
                    home: pathlib_text(home),
                    path,
                    key,
                    size: metadata.file_size() as i64,
                    changed_ns: mtime_ns(&metadata),
                });
            }
        }
    }
    found.sort_by(|a, b| b.changed_ns.cmp(&a.changed_ns));
    Ok(found)
}

fn known_get<'a>(known: Option<&'a Map>, key: &str) -> Option<&'a Value> {
    known.and_then(|map| map.get(key))
}

/// `unchanged(rollout, known)`: the same size and time as its token_files row, read to its end.
pub fn unchanged(rollout: &Rollout, known: Option<&Map>) -> Result<bool, &'static str> {
    let Some(map) = known else {
        return Ok(false);
    };
    let changed = Value::from(rollout.changed_ns as i64);
    let size = Value::from(rollout.size);
    if !pyval::eq(map.get("mtime_ns").unwrap_or(&Value::Null), &changed)
        || !pyval::eq(map.get("size").unwrap_or(&Value::Null), &size)
    {
        return Ok(false);
    }
    let offset = map.get("offset").cloned().unwrap_or(Value::from(0));
    Ok(!pyval::less(&offset, &size)?)
}

/// `_first(path)`: (the conversation id, the 16-hex digest of the folder) its first line names.
fn first(path: &str) -> Result<(Option<String>, Option<String>), ()> {
    let payload = session_meta(path).map_err(|_| ())?;
    let Some(payload) = payload else {
        return Ok((None, None));
    };
    let thread = match payload.get("id") {
        Some(Value::Str(text)) => Some(String::from_utf8_lossy(text.as_bytes()).to_lowercase()),
        _ => None,
    };
    let cwd = payload.get("cwd").cloned().unwrap_or(Value::Null);
    let digest = car_policy::classify::projects::key_for(&Value::Null, &cwd);
    let thread = thread.filter(|id| ids::is_uuid(&Value::from(id.as_str())));
    Ok((
        thread,
        digest.map(|digest| digest.chars().take(16).collect()),
    ))
}

/// `_epoch(stamp)`: an event's UTC `timestamp` in seconds, or None.
fn epoch(stamp: Option<&Value>) -> Option<i64> {
    let Some(Value::Str(stamp)) = stamp else {
        return None;
    };
    let text = stamp.as_str()?;
    if text.chars().count() < 19 {
        return None;
    }
    let head: String = text.chars().take(19).collect();
    crate::pytime::timegm(&head, "%Y-%m-%dT%H:%M:%S")
}

/// `_counts(value)`: the four kinds as whole numbers, or None where any is missing or not one.
fn counts(value: Option<&Value>) -> Option<[i64; 4]> {
    let Some(Value::Object(map)) = value else {
        return None;
    };
    let mut out = [0i64; 4];
    for (index, kind) in KINDS.iter().enumerate() {
        let Some(Value::Int(number)) = map.get(*kind) else {
            return None;
        };
        let number = number.as_i64()?;
        if !(0..=MOST).contains(&number) {
            return None;
        }
        out[index] = number;
    }
    Some(out)
}

/// `_event(line)`: a line's (kind, payload, seconds), parsed - None for one that is not an event of the two kinds.
fn event(line: &[u8]) -> Option<(&'static str, Map, i64)> {
    let text = std::str::from_utf8(line).ok()?;
    let Ok(Value::Object(event)) = car_machine::compat::loads(text) else {
        return None;
    };
    if !event
        .get("type")
        .is_some_and(|kind| pyval::is(kind, "event_msg"))
    {
        return None;
    }
    let Some(Value::Object(payload)) = event.get("payload") else {
        return None;
    };
    let kind = match payload.get("type") {
        Some(kind) if pyval::is(kind, "token_count") => "token_count",
        Some(kind) if pyval::is(kind, "task_started") => "task_started",
        _ => return None,
    };
    let at = epoch(event.get("timestamp"))?;
    Some((kind, payload.clone(), at))
}

fn contains(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window == needle)
}

fn info_of(payload: &Map) -> Option<&Map> {
    match payload.get("info") {
        Some(Value::Object(info)) => Some(info),
        _ => None,
    }
}

/// `_totals_before(stream, offset)`: the running totals of the last token_count event before `offset`.
fn totals_before(stream: &mut std::fs::File, offset: i64) -> std::io::Result<Option<[i64; 4]>> {
    let back = offset.min(LOOK_BACK);
    if back <= 0 {
        return Ok(None);
    }
    stream.seek(SeekFrom::Start((offset - back) as u64))?;
    let mut data = Vec::new();
    stream.by_ref().take(back as u64).read_to_end(&mut data)?;
    if offset - back > 0 {
        data = match data.iter().position(|byte| *byte == b'\n') {
            Some(at) => data[at + 1..].to_vec(),
            None => Vec::new(),
        };
    }
    for line in data.split(|byte| *byte == b'\n').rev() {
        if line.len() > LINE_BYTES || !contains(line, TOKEN_BYTES) {
            continue;
        }
        if let Some(("token_count", payload, _)) = event(line)
            && let Some(info) = info_of(&payload)
            && let Some(totals) = counts(info.get("total_token_usage"))
        {
            return Ok(Some(totals));
        }
    }
    Ok(None)
}

/// `time.strftime("%Y-%m-%d", local(at))`.
fn local_day(local: &dyn LocalClock, at: i64) -> Result<String, &'static str> {
    let tm = local.localtime(at as f64)?;
    Ok(format!("{:04}-{:02}-{:02}", tm.year, tm.mon, tm.mday))
}

fn day_entry<'a>(days: &'a mut Vec<(String, [i64; 5])>, day: &str) -> &'a mut [i64; 5] {
    let at = match days.iter().position(|(each, _)| each == day) {
        Some(at) => at,
        None => {
            days.push((day.to_owned(), [0; 5]));
            days.len() - 1
        }
    };
    &mut days[at].1
}

/// `read(rollout, known, budget, local=...)`: one pass over `rollout` from where `known` (its token_files row) says
/// it stopped, reading at most min(FILE_BYTES, budget) bytes. `Err` is the class of what the reference lets out (the
/// local clock's refusal; a `known` offset of no number's type).
pub fn read(
    rollout: &Rollout,
    known: Option<&Map>,
    budget: i64,
    local: &dyn LocalClock,
) -> Result<Read, &'static str> {
    let nothing = |outcome: &'static str,
                   thread: Option<String>,
                   offset: i64,
                   project: Option<String>,
                   consumed: i64| Read {
        key: rollout.key.clone(),
        thread_id: thread,
        size: rollout.size,
        offset,
        changed_ns: rollout.changed_ns,
        days: Vec::new(),
        project_key: project,
        outcome,
        consumed,
    };
    let known_offset = || -> Result<i64, &'static str> {
        match known_get(known, "offset") {
            None => Ok(0),
            Some(Value::Int(number)) => number.as_i64().ok_or("OverflowError"),
            Some(Value::Bool(flag)) => Ok(i64::from(*flag)),
            Some(_) => Err("TypeError"),
        }
    };
    let Ok((thread, project)) = first(&rollout.path) else {
        return Ok(nothing(UNREADABLE, None, known_offset()?, None, 0));
    };
    let Some(thread) = thread else {
        return Ok(nothing(UNREADABLE, None, rollout.size, None, 0));
    };
    let mut offset = known_offset()?;
    let same_thread = known_get(known, "thread_id")
        .is_some_and(|said| pyval::eq(said, &Value::from(thread.as_str())));
    if known.is_none() || !same_thread || rollout.size < offset {
        offset = 0;
    }
    let allowed = FILE_BYTES.min(budget).max(0);
    if allowed == 0 || offset >= rollout.size {
        let outcome = if offset >= rollout.size {
            UNCHANGED
        } else {
            CAPPED
        };
        return Ok(nothing(outcome, Some(thread), offset, project, 0));
    }
    let opened = (|| -> std::io::Result<(Option<[i64; 4]>, Vec<u8>)> {
        let mut stream = std::fs::File::open(&rollout.path)?;
        let previous = totals_before(&mut stream, offset)?;
        stream.seek(SeekFrom::Start(offset as u64))?;
        let mut chunk = Vec::new();
        stream.take(allowed as u64).read_to_end(&mut chunk)?;
        Ok((previous, chunk))
    })();
    let Ok((mut previous, chunk)) = opened else {
        return Ok(nothing(UNREADABLE, Some(thread), offset, project, 0));
    };
    let Some(end) = chunk.iter().rposition(|byte| *byte == b'\n') else {
        let length = chunk.len() as i64;
        let moved = if length >= allowed { length } else { 0 };
        let outcome = if moved != 0 { CAPPED } else { UNCHANGED };
        return Ok(nothing(
            outcome,
            Some(thread),
            offset + moved,
            project,
            length,
        ));
    };
    let started_at_zero = offset == 0;
    let mut days: Vec<(String, [i64; 5])> = Vec::new();
    for line in chunk[..end].split(|byte| *byte == b'\n') {
        if line.len() > LINE_BYTES || (!contains(line, TOKEN_BYTES) && !contains(line, TURN_BYTES))
        {
            continue;
        }
        let Some((kind, payload, at)) = event(line) else {
            continue;
        };
        let day = local_day(local, at)?;
        if kind == "task_started" {
            day_entry(&mut days, &day)[4] += 1;
            continue;
        }
        let Some(info) = info_of(&payload) else {
            continue;
        };
        let total = counts(info.get("total_token_usage"));
        let last = counts(info.get("last_token_usage"));
        if total.is_some() && total == previous {
            continue;
        }
        let numbers = match (last, total, previous) {
            (Some(last), _, _) => Some(last),
            (None, Some(total), Some(before)) => {
                let mut out = [0i64; 4];
                for index in 0..4 {
                    out[index] = (total[index] - before[index]).max(0);
                }
                Some(out)
            }
            (None, Some(total), None) if started_at_zero => Some(total),
            _ => None,
        };
        if total.is_some() {
            previous = total;
        }
        let Some(numbers) = numbers else {
            continue;
        };
        let kept = day_entry(&mut days, &day);
        for index in 0..4 {
            kept[index] += numbers[index];
        }
    }
    let consumed = end as i64 + 1;
    let outcome = if offset + consumed < rollout.size && chunk.len() as i64 >= allowed {
        CAPPED
    } else {
        READ
    };
    Ok(Read {
        key: rollout.key.clone(),
        thread_id: Some(thread),
        size: rollout.size,
        offset: offset + consumed,
        changed_ns: rollout.changed_ns,
        days,
        project_key: project,
        outcome,
        consumed,
    })
}

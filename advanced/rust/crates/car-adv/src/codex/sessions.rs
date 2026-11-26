//! `codex/sessions.py`: where a conversation came from, the kinds of its rollout's newest events, and where its rollout
//! is - for the measurements MO, MC2, MTOK and MGAVE alone, never what any of it says (seat S7.2c). Paths are used,
//! never returned to a caller that keeps them.
//!
//! `names()` walks the sessions folders as `Path.rglob` does on the reference's 3.13: a symbolic link is never followed;
//! a junction is (`AUDIT-v0628.md` has the line - std's `FileType` calls a junction a link, so the walk asks
//! car-platform's reparse tag).

use std::io::{Read as _, Seek, SeekFrom};
use std::path::Path;

use car_codex::paths::safe_path;
use car_codex::sql::{self, Param};
use car_config::winpath;
use car_machine::compat::{LoadsError, loads};
use car_machine::domain::ids;
use car_machine::json::{Map, Value};

use super::turns::{Failure, Read, SharedOs, connect, is_alpha, thread_id_text, unavailable};

pub const THREAD_COLUMNS: &[&str] = &[
    "id",
    "rollout_path",
    "source",
    "thread_source",
    "history_mode",
];
pub const ORIGIN: &str =
    "SELECT rollout_path, source, thread_source, history_mode FROM threads WHERE id=?";
pub const STATEMENTS: [&str; 1] = [ORIGIN];
pub const FIRST_LINE_BYTES: usize = 64 * 1024;
pub const TAIL_BYTES: u64 = 64 * 1024;
pub const WORD_MAX: usize = 64;

/// `_word(value)`: a word of letters and underscores, or "other".
pub fn word(value: Option<&Value>) -> String {
    if let Some(Value::Str(text)) = value
        && let Some(text) = text.as_str()
        && (1..=WORD_MAX).contains(&text.chars().count())
        && is_alpha(&text.replace('_', ""))
    {
        return text.to_owned();
    }
    "other".to_owned()
}

/// `_regular(path)`: a regular file, never a link to one.
fn regular(path: &str) -> bool {
    let target = Path::new(path);
    !car_platform::links::is_symlink(target) && target.is_file()
}

/// `bytes.strip()` is empty.
fn blank(line: &[u8]) -> bool {
    line.iter()
        .all(|b| matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c))
}

/// `json.loads(line.decode("utf-8"))`: the event, none for a line that is no JSON or no UTF-8, or the RecursionError.
fn event(line: &[u8]) -> Result<Option<Value>, Failure> {
    let Ok(text) = std::str::from_utf8(line) else {
        return Ok(None);
    };
    match loads(text) {
        Ok(found) => Ok(Some(found)),
        Err(LoadsError::Recursion) => Err(Failure::Raised("RecursionError")),
        Err(_) => Ok(None),
    }
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

/// The conversations of the Codex home `home`, as MO, MC2, MTOK and MGAVE read them.
pub struct Origins {
    pub home: String,
    pub os: SharedOs,
}

/// `Path(text).suffix`.
fn suffix(path: &str) -> String {
    let name = winpath::parse(path).2.last().cloned().unwrap_or_default();
    match name.rfind('.') {
        Some(0) | None => String::new(),
        Some(at) if at + 1 == name.len() => String::new(),
        Some(at) => name[at..].to_owned(),
    }
}

fn name_of(path: &str) -> String {
    winpath::parse(path).2.last().cloned().unwrap_or_default()
}

impl Origins {
    fn row(&self, thread_id: &Value) -> Read<Option<Map>> {
        if !ids::is_uuid(thread_id) {
            return Err(unavailable("not a conversation"));
        }
        let thread = thread_id_text(thread_id);
        let connection = connect(
            self.os.as_ref(),
            &self.home,
            "state",
            &[("threads", THREAD_COLUMNS)],
        )?;
        let found = sql::first(&connection, ORIGIN, &[Param::Text(&thread)])
            .map_err(|_| unavailable("the conversation cannot be read"))?;
        Ok(found.map(|row| {
            ["rollout_path", "source", "thread_source", "history_mode"]
                .iter()
                .enumerate()
                .map(|(index, name)| ((*name).into(), row.at(index).value()))
                .collect()
        }))
    }

    fn safe(&self, path: &str) -> Read<String> {
        safe_path(self.os.as_ref(), path).map_err(super::turns::raised)
    }

    /// `_rollout(thread_id, raw)`: the rollout where it is the conversation's own .jsonl file inside the sessions folder.
    fn rollout_of(&self, thread_id: &str, raw: Option<&Value>) -> Read<Option<String>> {
        let Some(Value::Str(raw)) = raw else {
            return Ok(None);
        };
        let path = self.safe(&String::from_utf8_lossy(raw.as_bytes()))?;
        let sessions = self.safe(&winpath::join(&self.home, "sessions"))?;
        if !winpath::is_relative_to(&path, &sessions)
            || suffix(&path) != ".jsonl"
            || !name_of(&path).contains(thread_id)
        {
            return Ok(None);
        }
        Ok(Some(path))
    }

    /// `rollout(thread_id)`: the conversation's rollout, where it is its own .jsonl file inside the sessions folder.
    pub fn rollout(&self, thread_id: &Value) -> Read<Option<String>> {
        let Some(row) = self.row(thread_id)? else {
            return Ok(None);
        };
        self.rollout_of(&thread_id_text(thread_id), row.get("rollout_path"))
    }

    /// `find(thread_id, names)`: (the rollout, how it was found) - "row", "archived", "name" - or (none, "missing").
    pub fn find(
        &self,
        thread_id: &Value,
        names: Option<&[(String, String)]>,
    ) -> Read<(Option<String>, &'static str)> {
        if !ids::is_uuid(thread_id) {
            return Ok((None, "missing"));
        }
        let thread = thread_id_text(thread_id);
        let row = self.row(thread_id)?;
        if let Some(Value::Str(raw)) = row.as_ref().and_then(|row| row.get("rollout_path")) {
            let path = self.safe(&String::from_utf8_lossy(raw.as_bytes()))?;
            for (folder, how) in [("sessions", "row"), ("archived_sessions", "archived")] {
                let root = self.safe(&winpath::join(&self.home, folder))?;
                if winpath::is_relative_to(&path, &root)
                    && suffix(&path) == ".jsonl"
                    && name_of(&path).contains(&thread)
                    && regular(&path)
                {
                    return Ok((Some(path), how));
                }
            }
        }
        let listed;
        let names = match names {
            Some(names) => names,
            None => {
                listed = self.names()?;
                &listed
            }
        };
        Ok(match names.iter().find(|(id, _)| *id == thread) {
            Some((_, path)) => (Some(path.clone()), "name"),
            None => (None, "missing"),
        })
    }

    /// `names()`: `{the id a file's name ends in: the file}` for every regular .jsonl file under archived_sessions and then
    /// sessions, in that order (a later one of the same id wins), each folder's files sorted as pathlib sorts them.
    pub fn names(&self) -> Read<Vec<(String, String)>> {
        let mut found: Vec<(String, String)> = Vec::new();
        for folder in ["archived_sessions", "sessions"] {
            let root = winpath::join(&self.home, folder);
            let Some(mut paths) = walk(&root) else {
                continue;
            };
            paths.retain(|path| regular(path));
            paths.sort_by_key(|path| {
                winpath::path_str(path)
                    .to_lowercase()
                    .split('\\')
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
            });
            for path in paths {
                let name = name_of(&path);
                let stem = match name.rfind('.') {
                    Some(at) if at > 0 => &name[..at],
                    _ => name.as_str(),
                };
                let chars: Vec<char> = stem.chars().collect();
                let tail: String = chars[chars.len().saturating_sub(36)..]
                    .iter()
                    .collect::<String>()
                    .to_lowercase();
                let separated = chars.len() == 36
                    || (chars.len() > 36 && matches!(chars[chars.len() - 37], '-' | '_'));
                if ids::is_uuid(&Value::from(tail.as_str())) && separated {
                    let safe = self.safe(&path)?;
                    match found.iter_mut().find(|(id, _)| *id == tail) {
                        Some(slot) => slot.1 = safe,
                        None => found.push((tail, safe)),
                    }
                }
            }
        }
        Ok(found)
    }

    /// `origin(thread_id)`: (the row's source, thread source and history mode; the first line's originator, source and
    /// CLI version) - each none where it is not there.
    pub fn origin(&self, thread_id: &Value) -> Read<(Option<Map>, Option<Map>)> {
        let Some(mut row) = self.row(thread_id)? else {
            return Ok((None, None));
        };
        let raw = row.shift_remove("rollout_path");
        let thread = thread_id_text(thread_id);
        let path = self.rollout_of(&thread, raw.as_ref())?;
        let mut first = None;
        if let Some(path) = path {
            let line = (|| -> std::io::Result<Vec<u8>> {
                let mut stream = car_machine::pyfile::open(&path)?;
                let mut line = Vec::new();
                let mut byte = [0u8; 1];
                while line.len() < FIRST_LINE_BYTES + 1 {
                    if stream.read(&mut byte)? == 0 {
                        break;
                    }
                    line.push(byte[0]);
                    if byte[0] == b'\n' {
                        break;
                    }
                }
                Ok(line)
            })();
            let found = match line {
                Ok(line) if line.ends_with(b"\n") => event(&line)?,
                _ => None,
            };
            let payload = found
                .as_ref()
                .filter(|event| matches!(get(event, "type"), Some(Value::Str(word)) if word.as_bytes() == b"session_meta"))
                .and_then(|event| get(event, "payload"));
            if let Some(payload @ Value::Object(_)) = payload
                && matches!(get(payload, "id"), Some(Value::Str(id)) if id.as_bytes() == thread.as_bytes())
            {
                let mut said = Map::new();
                for key in ["originator", "source", "cli_version"] {
                    said.insert(
                        key.into(),
                        get(payload, key).cloned().unwrap_or(Value::Null),
                    );
                }
                first = Some(said);
            }
        }
        Ok((Some(row), first))
    }

    /// `events_since(thread_id, offset)`: the payload type of each complete line the rollout gained after `offset`, and
    /// the offset to look from next.
    pub fn events_since(
        &self,
        thread_id: &Value,
        offset: Option<i64>,
    ) -> Read<(Vec<String>, Option<i64>)> {
        let path = match self.row(thread_id)? {
            Some(row) => self.rollout_of(&thread_id_text(thread_id), row.get("rollout_path"))?,
            None => None,
        };
        let Some(path) = path else {
            return Ok((Vec::new(), offset));
        };
        let cannot = || unavailable("the rollout cannot be read");
        let mut stream = car_machine::pyfile::open(&path).map_err(|_| cannot())?;
        let size = stream.seek(SeekFrom::End(0)).map_err(|_| cannot())? as i64;
        let offset = match offset {
            Some(offset) if offset <= size => offset,
            _ => return Ok((Vec::new(), Some(size))),
        };
        let start = offset.max(size - TAIL_BYTES as i64);
        if start < 0 {
            return Err(cannot());
        }
        stream
            .seek(SeekFrom::Start(start as u64))
            .map_err(|_| cannot())?;
        let mut data = Vec::new();
        stream
            .take((size - start) as u64)
            .read_to_end(&mut data)
            .map_err(|_| cannot())?;
        let complete = match data.iter().rposition(|b| *b == b'\n') {
            Some(at) => &data[..=at],
            None => &data[..0],
        };
        let mut kinds = Vec::new();
        for line in complete.split(|b| *b == b'\n') {
            if blank(line) {
                continue;
            }
            match event(line)? {
                None => kinds.push("other".to_owned()),
                Some(found) => kinds.push(word(
                    get(&found, "payload").and_then(|payload| get(payload, "type")),
                )),
            }
        }
        Ok((kinds, Some(start + complete.len() as i64)))
    }

    /// `newest_event(thread_id)`: (the newest complete line's type, its payload's type), or none.
    pub fn newest_event(&self, thread_id: &Value) -> Read<Option<(String, String)>> {
        let path = match self.row(thread_id)? {
            Some(row) => self.rollout_of(&thread_id_text(thread_id), row.get("rollout_path"))?,
            None => None,
        };
        let Some(path) = path else {
            return Ok(None);
        };
        let cannot = || unavailable("the rollout cannot be read");
        let mut stream = car_machine::pyfile::open(&path).map_err(|_| cannot())?;
        let size = stream.seek(SeekFrom::End(0)).map_err(|_| cannot())?;
        stream
            .seek(SeekFrom::Start(size.saturating_sub(TAIL_BYTES)))
            .map_err(|_| cannot())?;
        let mut tail = Vec::new();
        stream.read_to_end(&mut tail).map_err(|_| cannot())?;
        let parts: Vec<&[u8]> = tail.split(|b| *b == b'\n').collect();
        let skip = usize::from(size > TAIL_BYTES);
        let end = parts.len().saturating_sub(1);
        let lines: Vec<&[u8]> = if skip < end {
            parts[skip..end].to_vec()
        } else {
            Vec::new()
        }
        .into_iter()
        .filter(|line| !blank(line))
        .collect();
        let Some(last) = lines.last() else {
            return Ok(None);
        };
        Ok(Some(match event(last)? {
            None => ("other".to_owned(), "other".to_owned()),
            Some(found) => (
                word(get(&found, "type")),
                word(get(&found, "payload").and_then(|payload| get(payload, "type"))),
            ),
        }))
    }
}

/// Every `.jsonl` file under `root`, as `Path.rglob("*.jsonl")` finds them (a symbolic link never followed), or none where
/// the folder cannot be listed.
fn walk(root: &str) -> Option<Vec<String>> {
    let top = std::fs::read_dir(root).ok()?;
    let mut found = Vec::new();
    let mut stack = vec![top];
    while let Some(entries) = stack.pop() {
        for entry in entries.flatten() {
            let path = entry.path();
            let text = path.to_string_lossy().into_owned();
            let link = car_platform::links::is_symlink(&path);
            if path.is_dir() {
                if !link && let Ok(inner) = std::fs::read_dir(&path) {
                    stack.push(inner);
                }
                continue;
            }
            if text.ends_with(".jsonl") {
                found.push(text);
            }
        }
    }
    Some(found)
}

//! `control/tools.py`: Diagnostics' own tools (v0.6.11) - the logs searched, who may open the state folder, and where
//! the watcher and this bridge run. Each only reads, and each is asked only when a person asks for it.
//! (`show_demo` signals the icon's event: it is not read-only, and is S5.1b's.)

use std::path::PathBuf;

use car_config::logbook::BACKUP_COUNT;
use car_machine::json::{Map, Str, Value};
use car_machine::{pytext, pyval};
use car_policy::settings::homes::casefold;

use crate::error::{Res, refuse};
use crate::layer::Control;

/// The most lines one answer carries, the longest search, and the most of each file read.
pub const LOG_LIMIT: i64 = 500;
pub const MAX_QUERY: usize = 100;
pub const MAX_LOG_BYTES: u64 = 2 * 1024 * 1024;
/// The pictures' pin for `host_app`: set to "outside" only by the screenshots' capture.
pub const STILL_HOST: &str = "CODEX_AR_STILL_HOST";

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

/// `str.splitlines()`: the text cut at every line boundary Python knows.
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let bytes = text.as_bytes();
    let mut start = 0;
    let mut iter = text.char_indices().peekable();
    while let Some((at, each)) = iter.next() {
        let boundary = matches!(
            each,
            '\n' | '\r'
                | '\u{0b}'
                | '\u{0c}'
                | '\u{1c}'
                | '\u{1d}'
                | '\u{1e}'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if !boundary {
            continue;
        }
        lines.push(&text[start..at]);
        let mut next = at + each.len_utf8();
        if each == '\r' && bytes.get(next) == Some(&b'\n') {
            iter.next();
            next += 1;
        }
        start = next;
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}

/// `LOG_LINE.match(line)`: `[YYYY-MM-DD HH:MM:SS] text` with a text of 1 to 2000 characters holding no line break;
/// `\d` is a decimal digit of any script. The time and the text.
fn log_line(line: &str) -> Option<(&str, &str)> {
    let chars: Vec<(usize, char)> = line.char_indices().collect();
    let shape = "[dddd-dd-dd dd:dd:dd] ";
    if chars.len() < shape.chars().count() + 1 {
        return None;
    }
    for ((_, found), expected) in chars.iter().zip(shape.chars()) {
        let fits = match expected {
            'd' => pytext::is_digit(*found),
            other => *found == other,
        };
        if !fits {
            return None;
        }
    }
    let taken = shape.chars().count();
    let at = chars[1].0;
    let end_time = chars[20].0;
    let rest = chars[taken].0;
    let text = &line[rest..];
    let length = text.chars().count();
    if !(1..=2000).contains(&length) || text.contains(['\r', '\n']) {
        return None;
    }
    Some((&line[at..end_time], text))
}

impl Control {
    /// `_log_files()`: the log and its rotated copies, oldest first.
    fn log_files(&self) -> Vec<PathBuf> {
        let main = PathBuf::from(&self.paths.log_file);
        let name = main
            .file_name()
            .map(|each| each.to_string_lossy().into_owned())
            .unwrap_or_default();
        let mut found: Vec<PathBuf> = (1..=BACKUP_COUNT)
            .rev()
            .map(|number| main.with_file_name(format!("{name}.{number}")))
            .collect();
        found.push(main);
        found
            .into_iter()
            .filter(|path| path.is_file() && !self.host.is_symlink(path))
            .collect()
    }

    /// `search_logs(query=None, limit=LOG_LIMIT)`: the log's lines that hold `query` - every line for none - newest
    /// last, at most `limit`.
    pub fn search_logs(&self, query: &Value, limit: &Value) -> Res<Value> {
        let text_query = match query {
            Value::Null => None,
            Value::Str(text) => {
                if text.code_points().count() > MAX_QUERY
                    || text.code_points().any(|point| point < 32)
                {
                    return refuse("the request could not be completed", "request_failed");
                }
                Some(text.clone())
            }
            _ => return refuse("the request could not be completed", "request_failed"),
        };
        let limit = match limit {
            Value::Int(int) => match int.as_i64() {
                Some(each) if (1..=LOG_LIMIT).contains(&each) => each as usize,
                _ => LOG_LIMIT as usize,
            },
            _ => LOG_LIMIT as usize,
        };
        let wanted: Option<Str> = text_query.as_ref().map(|text| {
            let stripped = match text.as_str() {
                Some(plain) => Str::from(pytext::strip(plain)),
                None => text.clone(),
            };
            casefold(&stripped)
        });
        let wanted = wanted.filter(|text| !text.is_empty());
        let mut found: Vec<(String, String)> = Vec::new();
        let mut total: i64 = 0;
        for path in self.log_files() {
            let Ok(mut stream) = self.host.open_file(&path) else {
                continue;
            };
            use std::io::{Read, Seek, SeekFrom};
            let Ok(size) = stream.seek(SeekFrom::End(0)) else {
                continue;
            };
            if stream
                .seek(SeekFrom::Start(size.saturating_sub(MAX_LOG_BYTES)))
                .is_err()
            {
                continue;
            }
            let mut bytes = Vec::new();
            if stream.read_to_end(&mut bytes).is_err() {
                continue;
            }
            let text = String::from_utf8_lossy(&bytes).into_owned();
            for line in splitlines(&text) {
                let Some((at, rest)) = log_line(line) else {
                    continue;
                };
                total += 1;
                let hit = match &wanted {
                    None => true,
                    Some(needle) => {
                        let folded = casefold(&Str::from(line));
                        let needle = needle.as_bytes();
                        folded
                            .as_bytes()
                            .windows(needle.len().max(1))
                            .any(|window| window == needle)
                    }
                };
                if hit {
                    found.push((at.to_owned(), rest.to_owned()));
                }
            }
        }
        let matched = found.len() as i64;
        let skip = found.len().saturating_sub(limit);
        let lines: Vec<Value> = found
            .into_iter()
            .skip(skip)
            .map(|(at, text)| object(vec![("at", Value::from(at)), ("text", Value::from(text))]))
            .collect();
        Ok(object(vec![
            ("lines", Value::Array(lines)),
            ("matched", Value::from(matched)),
            ("total", Value::from(total)),
            (
                "query",
                match query {
                    Value::Str(text) => Value::Str(text.clone()),
                    _ => Value::from(""),
                },
            ),
        ]))
    }

    /// `state_access()`: who Windows lets open the state folder.
    pub fn state_access(&self) -> Value {
        object(vec![(
            "access",
            Value::from(self.host.state_access(&self.state_dir())),
        )])
    }

    /// `host_app()`: whether the watcher and this bridge run inside another app, and which.
    pub fn host_app(&self) -> Res<Value> {
        let outside = || {
            object(vec![
                ("state", Value::from("outside")),
                ("family", Value::Null),
                ("app", Value::Null),
            ])
        };
        let pinned = self.host.environ(STILL_HOST).as_deref() == Some("outside");
        let walk = |pid: Option<u32>, started: Option<f64>| -> Value {
            if pinned {
                outside()
            } else {
                self.host.host_app(pid, started)
            }
        };
        let unknown = || {
            object(vec![
                ("state", Value::from("unknown")),
                ("family", Value::Null),
                ("app", Value::Null),
            ])
        };
        let seen = match self.open(true) {
            Ok(state) => self
                .watcher(&state)
                .unwrap_or_else(|_| object(vec![("running", Value::Null)])),
            Err(_) => object(vec![("running", Value::Null)]),
        };
        let held = |name: &str| -> Value {
            match &seen {
                Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            }
        };
        let running = held("running");
        let watcher = if matches!(running, Value::Null) {
            unknown()
        } else if pyval::truthy(&running) {
            let (pid, started) = (held("pid"), held("started_at"));
            let pid = match &pid {
                Value::Int(int) => int
                    .as_i64()
                    .filter(|each| *each > 0 && *each <= i64::from(u32::MAX)),
                _ => None,
            };
            let started = match &started {
                Value::Float(x) => Some(*x),
                Value::Int(int) => int.as_i64().map(|each| each as f64),
                _ => None,
            };
            match (pid, started) {
                (Some(pid), Some(started)) => walk(Some(pid as u32), Some(started)),
                _ => unknown(),
            }
        } else {
            object(vec![
                ("state", Value::from("not_running")),
                ("family", Value::Null),
                ("app", Value::Null),
            ])
        };
        Ok(object(vec![
            ("watcher", watcher),
            ("bridge", walk(None, None)),
        ]))
    }
}

impl Control {
    /// `show_demo()`: the made-up rows the Dashboard plays, and whether the watcher's icon was asked to draw the
    /// made-up card (False when no watcher holds the event). Nothing is read from the state or written to it.
    pub fn show_demo(&self) -> Res<Value> {
        let asked = self
            .host
            .signal(crate::host::Event::Demo, &self.state_dir())
            .unwrap_or(false);
        let rows = car_policy::settings::demo::rows(&Value::Float(self.host.now()))
            .map_err(|class| crate::error::Failure::Other(class.to_owned()))?;
        let mut map = match rows {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        map.insert(Str::from("asked"), Value::Bool(asked));
        Ok(Value::Object(map))
    }
}

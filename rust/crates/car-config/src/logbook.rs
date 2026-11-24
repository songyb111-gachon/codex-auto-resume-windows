//! `logbook.py`: the rotating local log. Only static reason codes, UUIDs and timestamps are written.
//!
//! Prompt text, Codex error text, usage-account fields and secrets never reach this module: the engine passes
//! `(thread_id, code, detail)` where detail is an interruption hash or an integer timestamp string. The lines are
//! pinned (Diagnostics and `ownreport` read them back), so the sentences are the tag's (`logbook_gen.rs`), the
//! file's format is `[%Y-%m-%d %H:%M:%S] <mark><message>` and its rotation is `RotatingFileHandler`'s.
//!
//! The local time zone is the platform's (car-platform), so every call that needs one takes a [`Clock`].

use std::fs::{self, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

use car_machine::domain::ids;
use car_machine::json::Value;
use car_machine::pytext::{is_space, py_str};
use car_machine::pyval::{Py, hashable, text};

use crate::logbook_gen::{MESSAGES, SKIP_WORDS};

pub use crate::vocab_gen::logbook::{LOGGER_NAME, SKIPPED};
pub const MAX_BYTES: u64 = 1_000_000;
pub const BACKUP_COUNT: u32 = 5;
/// How much of the log is read back, once, for the skip lines a watcher before this one wrote.
pub const SAID_BYTES: u64 = 2 * 1024 * 1024;
/// The largest second `time.localtime` takes on Windows.
const LOCALTIME_MAX: i64 = 32_536_799_999;

/// The platform's clock: the time now, and the offset of the local zone from UTC at a moment (`None` where the
/// system cannot say, as `time.localtime` raises OSError).
pub trait Clock {
    fn now(&self) -> f64;
    fn utc_offset(&self, seconds: i64) -> Option<i32>;
}

fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// The seconds `datetime.fromtimestamp(x, utc)` keeps of a float: truncated, the microseconds rounded half to even.
fn whole_seconds(x: f64) -> Option<i64> {
    if !x.is_finite() || x.abs() > 1e18 {
        return None;
    }
    let mut whole = x.trunc();
    let mut micro = ((x - whole) * 1e6).round_ties_even();
    if micro >= 1e6 {
        whole += 1.0;
        micro -= 1e6;
    } else if micro < 0.0 {
        whole -= 1.0;
        micro += 1e6;
    }
    let _ = micro;
    Some(whole as i64)
}

/// `broken_down(seconds, offset)`: the local year, month, day, hour, minute, second.
fn broken_down(seconds: i64, offset: i32) -> (i64, i64, i64, i64, i64, i64) {
    let local = seconds + i64::from(offset);
    let (days, rest) = (local.div_euclid(86_400), local.rem_euclid(86_400));
    let (year, month, day) = civil_from_days(days);
    (year, month, day, rest / 3600, rest % 3600 / 60, rest % 60)
}

/// `format_local(timestamp)`: unix seconds as Windows local time with an explicit UTC offset, `unknown-time` for
/// anything the system cannot say.
pub fn format_local(timestamp: &Value, clock: &dyn Clock) -> String {
    let unknown = || "unknown-time".to_owned();
    let Ok(x) = car_machine::pytext::to_float(timestamp) else {
        return unknown();
    };
    let Some(seconds) = whole_seconds(x) else {
        return unknown();
    };
    if !(0..=LOCALTIME_MAX).contains(&seconds) {
        return unknown();
    }
    let Some(offset) = clock.utc_offset(seconds) else {
        return unknown();
    };
    let (year, month, day, hour, minute, second) = broken_down(seconds, offset);
    let sign = if offset < 0 { '-' } else { '+' };
    let total = offset.abs();
    format!(
        "{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02} {sign}{:02}:{:02}",
        total / 3600,
        total % 3600 / 60
    )
}

/// `[0-9a-f]{1,64}\Z`
fn hex_detail(word: &str) -> bool {
    (1..=ids::INTERRUPTION_ID_LENGTH).contains(&word.len())
        && word
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// `[0-9]{1,12}\Z`
fn digit_detail(word: &str) -> bool {
    (1..=12).contains(&word.len()) && word.bytes().all(|b| b.is_ascii_digit())
}

fn safe_detail(detail: &Value) -> String {
    if matches!(detail, Value::Null) {
        return String::new();
    }
    let shown = match detail {
        Value::Array(_) | Value::Object(_) => return "?".to_owned(),
        other => py_str(other),
    };
    if hex_detail(&shown) || digit_detail(&shown) {
        shown
    } else {
        "?".to_owned()
    }
}

fn template(code: &str, reason: Option<&str>) -> Option<&'static str> {
    MESSAGES
        .iter()
        .find(|(each, why, _)| *each == code && *why == reason)
        .map(|(_, _, sentence)| *sentence)
}

/// `[A-Za-z0-9_]{1,80}\Z`
fn reason_word(word: &str) -> bool {
    (1..=80).contains(&word.chars().count())
        && word.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// `render(thread_id, code, reason, detail)`: one line for one transition or event, with the reason for it whenever
/// there is one. A (state, reason) pair that has been given words keeps them; anything else gets the reason added.
pub fn render(
    thread_id: &Value,
    code: &Value,
    reason: &Value,
    detail: &Value,
    clock: &dyn Clock,
) -> Py<String> {
    hashable(code)?;
    hashable(reason)?;
    let code_text = py_str(code);
    let reason_text = text(reason);
    let wanted = if matches!(reason, Value::Null) {
        None
    } else {
        reason_text
    };
    let mut sentence = match template(&code_text, wanted) {
        Some(found) if wanted.is_some() || matches!(reason, Value::Null) => found.to_owned(),
        _ => {
            let general =
                template(&code_text, None).map_or_else(|| code_text.clone(), str::to_owned);
            if car_machine::pyval::truthy(reason) && !general.contains("{reason}") {
                format!("{general} ({{reason}})")
            } else {
                general
            }
        }
    };
    let safe = safe_detail(detail);
    let detail_time = if digit_detail(&safe) {
        let seconds: i64 = safe.parse().unwrap_or(0);
        format_local(&Value::from(seconds), clock)
    } else {
        "unknown-time".to_owned()
    };
    let named = match reason_text {
        Some(each) if reason_word(each) => each.to_owned(),
        _ => "unspecified".to_owned(),
    };
    let short: String = safe.chars().take(12).collect();
    for (name, value) in [
        ("{detail12}", short.as_str()),
        ("{detail_time}", detail_time.as_str()),
        ("{detail}", safe.as_str()),
        ("{reason}", named.as_str()),
    ] {
        sentence = sentence.replace(name, value);
    }
    let prefix = if ids::is_uuid(thread_id) {
        format!("thread {}: ", py_str(thread_id))
    } else {
        String::new()
    };
    Ok(sentence
        .split('\n')
        .map(|line| format!("{prefix}{line}"))
        .collect::<Vec<_>>()
        .join("\n"))
}

fn kind_word(word: &str) -> bool {
    (1..=48).contains(&word.chars().count())
        && word
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | ' ' | '-'))
}

/// `skipped(thread_id, turn_id, reason, kind)`: the one line for a failed turn not taken up.
pub fn skipped(thread_id: &Value, turn_id: &Value, reason: &Value, kind: &Value) -> Py<String> {
    hashable(reason)?;
    let known = |word: &str| SKIP_WORDS.iter().any(|(code, _)| *code == word);
    let reason = match text(reason) {
        Some(word) if known(word) => word.to_owned(),
        _ if matches!(reason, Value::Null) => "unknown_conversation".to_owned(),
        _ => "other".to_owned(),
    };
    let turn = if ids::is_uuid(turn_id) {
        py_str(turn_id)
    } else {
        "?".to_owned()
    };
    let said = match text(kind) {
        Some(found) if kind_word(found) => format!("{reason}: {found}"),
        _ => reason.clone(),
    };
    let prefix = if ids::is_uuid(thread_id) {
        format!("thread {}: ", py_str(thread_id))
    } else {
        String::new()
    };
    let words = SKIP_WORDS
        .iter()
        .find(|(code, _)| *code == reason)
        .map_or("unspecified", |(_, sentence)| sentence);
    Ok(format!(
        "{prefix}failed turn {turn} not taken up ({said}): {words}"
    ))
}

/// `tail(path, count)`: the last `count` lines of a file, line ends dropped; none where it cannot be read.
pub fn tail(path: &Path, count: i64) -> Vec<String> {
    let Ok(raw) = fs::read(path) else {
        return Vec::new();
    };
    let decoded = String::from_utf8_lossy(&raw).replace("\r\n", "\n");
    let lines: Vec<&str> = decoded.split_inclusive('\n').collect();
    let count = count.max(0) as usize;
    if count == 0 {
        return Vec::new();
    }
    lines[lines.len().saturating_sub(count)..]
        .iter()
        .map(|line| line.trim_end_matches(['\r', '\n']).to_owned())
        .collect()
}

/// One skip line `SKIP_LINE` finds: the turn and the reason it names.
fn skip_lines(text: &str) -> Vec<(String, String)> {
    const MARK: &str = "failed turn ";
    let mut found = Vec::new();
    let mut from = 0;
    while let Some(at) = text[from..].find(MARK) {
        let start = from + at + MARK.len();
        let rest = &text[start..];
        let turn: String = rest.chars().take_while(|c| !is_space(*c)).collect();
        let mut tail = &rest[turn.len()..];
        from = start;
        if turn.is_empty() || !tail.starts_with(" not taken up (") {
            continue;
        }
        tail = &tail[" not taken up (".len()..];
        let reason: String = tail
            .chars()
            .take_while(|c| c.is_ascii_lowercase() || *c == '_')
            .collect();
        if reason.is_empty() {
            continue;
        }
        tail = &tail[reason.len()..];
        let closed = if tail.starts_with(')') {
            true
        } else if let Some(after) = tail.strip_prefix(": ") {
            let run: String = after
                .chars()
                .take_while(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | ' ' | '-'))
                .collect();
            (1..=48).contains(&run.chars().count()) && after[run.len()..].starts_with(')')
        } else {
            false
        };
        if closed {
            found.push((turn, reason));
            from = start + rest.len() - tail.len();
        }
    }
    found
}

/// The rotating log: `logging.RotatingFileHandler` with `maxBytes=1_000_000`, `backupCount=5`, UTF-8, on Windows
/// (a line ends `\r\n` on disk, and the size rule counts a line as the text and one character).
pub struct Logbook {
    file: String,
    mark: String,
    said: Option<Vec<(String, String)>>,
    state_codes: Vec<String>,
}

impl Logbook {
    /// `setup_logging(log_file, mark=...)`: the folder made, the file opened for appending when the first line is written.
    pub fn open(log_file: &str, mark: &str, state_codes: &[&str]) -> Logbook {
        if let Some(parent) = Path::new(log_file).parent() {
            let _ = fs::create_dir_all(parent);
        }
        // The handler opens the file as it is made, so a log with no line yet exists.
        let _ = OpenOptions::new().create(true).append(true).open(log_file);
        Logbook {
            file: log_file.to_owned(),
            mark: mark.to_owned(),
            said: None,
            state_codes: state_codes.iter().map(|each| (*each).to_owned()).collect(),
        }
    }

    fn rollover(&self) {
        for i in (1..BACKUP_COUNT).rev() {
            let (from, to) = (
                format!("{}.{i}", self.file),
                format!("{}.{}", self.file, i + 1),
            );
            if Path::new(&from).exists() {
                let _ = fs::remove_file(&to);
                let _ = fs::rename(&from, &to);
            }
        }
        let first = format!("{}.1", self.file);
        let _ = fs::remove_file(&first);
        let _ = fs::rename(&self.file, &first);
    }

    /// `logger.info(line)`: one formatted line, rolled over first where it would reach the cap.
    pub fn info(&self, line: &str, clock: &dyn Clock) {
        let now = clock.now();
        let stamp = whole_seconds(now)
            .and_then(|seconds| clock.utc_offset(seconds).map(|offset| (seconds, offset)))
            .map(|(seconds, offset)| {
                let (year, month, day, hour, minute, second) = broken_down(seconds, offset);
                format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}")
            })
            .unwrap_or_else(|| "0000-00-00 00:00:00".to_owned());
        let message = format!("[{stamp}] {}{line}", self.mark);
        let size = fs::metadata(&self.file).map_or(0, |found| found.len());
        if Path::new(&self.file).is_file() && size + message.chars().count() as u64 + 1 >= MAX_BYTES
        {
            self.rollover();
        }
        if let Ok(mut stream) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.file)
        {
            let _ = stream.write_all(format!("{message}\r\n").as_bytes());
        }
    }

    fn already_said(&mut self) -> &mut Vec<(String, String)> {
        if self.said.is_none() {
            let mut said = Vec::new();
            for path in [format!("{}.1", self.file), self.file.clone()] {
                let Ok(mut stream) = fs::File::open(&path) else {
                    continue;
                };
                let end = stream.seek(SeekFrom::End(0)).unwrap_or(0);
                let _ = stream.seek(SeekFrom::Start(end.saturating_sub(SAID_BYTES)));
                let mut raw = Vec::new();
                let _ = stream.read_to_end(&mut raw);
                said.extend(skip_lines(&String::from_utf8_lossy(&raw)));
            }
            self.said = Some(said);
        }
        self.said.as_mut().expect("read just above")
    }

    /// `EngineLog.__call__(thread_id, code, detail)`: the engine's `(thread_id, code, detail)` as lines of the log.
    /// A skip is said once per (turn, reason), including by a watcher before this one.
    pub fn log(
        &mut self,
        thread_id: &Value,
        code: &Value,
        detail: &Value,
        clock: &dyn Clock,
    ) -> Py<()> {
        if text(code) == Some(SKIPPED)
            && let Value::Array(parts) = detail
            && parts.len() == 3
        {
            let key = (py_str(&parts[0]), py_str(&parts[1]));
            if !self.already_said().contains(&key) {
                self.already_said().push(key);
                let line = skipped(thread_id, &parts[0], &parts[1], &parts[2])?;
                self.info(&line, clock);
            }
            return Ok(());
        }
        let is_state =
            text(code).is_some_and(|word| self.state_codes.iter().any(|each| each == word));
        let (reason, detail) = if is_state {
            (
                if text(detail).is_some() {
                    detail.clone()
                } else {
                    Value::Null
                },
                Value::Null,
            )
        } else {
            (Value::Null, detail.clone())
        };
        for line in render(thread_id, code, &reason, &detail, clock)?.split('\n') {
            self.info(line, clock);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::json::from_str;

    struct Tokyo;
    impl Clock for Tokyo {
        fn now(&self) -> f64 {
            1_700_000_000.5
        }
        fn utc_offset(&self, _: i64) -> Option<i32> {
            Some(9 * 3600)
        }
    }

    #[test]
    fn local_time() {
        assert_eq!(
            format_local(&Value::from(0), &Tokyo),
            "1970-01-01 09:00:00 +09:00"
        );
        assert_eq!(format_local(&Value::from(-1), &Tokyo), "unknown-time");
        assert_eq!(format_local(&Value::from("x"), &Tokyo), "unknown-time");
        assert_eq!(
            format_local(&Value::from(32_536_800_000_i64), &Tokyo),
            "unknown-time"
        );
    }

    #[test]
    fn lines() {
        let thread = Value::from("0a1b2c3d-0001-7000-8000-000000000001");
        let line = render(
            &thread,
            &Value::from("queued"),
            &Value::Null,
            &Value::Null,
            &Tokyo,
        )
        .unwrap();
        assert_eq!(
            line,
            "thread 0a1b2c3d-0001-7000-8000-000000000001: queued; awaiting delivery receipt"
        );
        let said = skipped(
            &thread,
            &Value::from("x"),
            &Value::from("newer_turn"),
            &Value::Null,
        )
        .unwrap();
        assert!(said.contains("failed turn ? not taken up (newer_turn): a newer turn"));
        assert_eq!(
            skip_lines(&said),
            vec![("?".to_owned(), "newer_turn".to_owned())]
        );
        let none = from_str("null").unwrap();
        assert_eq!(safe_detail(&none), "");
    }
}

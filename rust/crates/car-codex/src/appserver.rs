//! `codex/appserver.py`: the App Server, spoken to for exactly three things and closed again.
//!
//! A finite separate stdio server, opened for one call and shut: it reads the usage or deletes one queued message
//! this product itself queued. `PROTOCOL_METHODS` is the whole of what it may be asked. The lines it writes are the
//! reference's bytes (`json.dumps(payload, ensure_ascii=False, allow_nan=False)` and the `\r\n` a text-mode pipe
//! writes on Windows); the lines it reads are decoded as a text-mode pipe decodes them (UTF-8 with replacement,
//! universal newlines) and counted in characters, as `readline(LINE_LIMIT + 1)` counts them.

use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, SyncSender, TrySendError, sync_channel};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use car_machine::compat::{LoadsError, loads, raw_decode};
use car_machine::json::{Int, Map, Options, Str, Value, to_string};
use car_machine::pytext::{decimal_value, is_space};
use car_machine::pyval;

use crate::errors::{Error, Result};
use crate::system::object;
use crate::transport::Backend;
use crate::usage::parse_usage;

/// The only App Server methods the finite helper may call.
pub const PROTOCOL_METHODS: [&str; 3] = [
    "initialize",
    "account/rateLimits/read",
    "thread/queue/delete",
];
pub const METHOD_UNKNOWN: &str = "protocol_method_unknown";
pub const REFUSED: &str = "protocol_request_refused";
/// The codes that mean Codex answered, and not in a way this version knows.
pub const BROKEN: [&str; 4] = [
    "protocol_home_mismatch",
    "protocol_platform_mismatch",
    METHOD_UNKNOWN,
    "protocol_reply_unknown",
];
const METHOD_NOT_FOUND: i64 = -32601;
const INVALID_REQUEST: i64 = -32600;
/// A line up to LINE_LIMIT characters is parsed whole; a longer one is read to its newline keeping its ends.
pub const LINE_LIMIT: usize = 1024 * 1024;
pub const KEPT: usize = 64 * 1024;
/// The one word an answer too large to keep carries.
pub const OVERSIZE: &str = "_oversize";
/// How long one call waits for its answer, in seconds.
pub const CALL_SECONDS: f64 = 25.0;
/// How long the helper is given to end once its input is closed, and again once it is ended.
pub const EXIT_SECONDS: f64 = 4.0;
/// How long the reader is waited for at the end.
pub const JOIN_SECONDS: f64 = 1.0;
/// How many answers wait for their caller before the reader stops.
pub const RESPONSES: usize = 64;

/// What the helper last met, by method: (code, the count that orders them).
pub type Results = Vec<(String, (String, u64))>;

struct Noted {
    results: Results,
    sequence: u64,
}

static RESULTS: Mutex<Noted> = Mutex::new(Noted {
    results: Vec::new(),
    sequence: 0,
});

fn noted() -> std::sync::MutexGuard<'static, Noted> {
    RESULTS
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// A fresh process's `RESULTS` (for the harness and tests).
pub fn reset() {
    let mut held = noted();
    held.results.clear();
    held.sequence = 0;
}

/// This process's `RESULTS`, as they are now.
pub fn results() -> Results {
    noted().results.clone()
}

/// Replace this process's `RESULTS` (for the harness and tests, as a test assigns the reference's dict).
pub fn set_results(results: Results) {
    let mut held = noted();
    held.sequence = results.iter().map(|(_, (_, at))| *at).max().unwrap_or(0);
    held.results = results;
}

fn put(results: &mut Results, method: &str, entry: (String, u64)) {
    match results.iter_mut().find(|(each, _)| each == method) {
        Some(slot) => slot.1 = entry,
        None => results.push((method.to_owned(), entry)),
    }
}

/// `_unknown(error, method)`: whether Codex's error answer says it does not know the method.
pub fn unknown(error: &Value, method: &str) -> bool {
    let Value::Object(error) = error else {
        return false;
    };
    let (code, message) = (
        error.get("code").unwrap_or(&Value::Null),
        error.get("message").unwrap_or(&Value::Null),
    );
    let Value::Int(code) = code else {
        return false;
    };
    if code.as_i64() == Some(METHOD_NOT_FOUND) {
        return true;
    }
    let named = format!("`{method}`");
    code.as_i64() == Some(INVALID_REQUEST)
        && matches!(message, Value::Str(text)
            if contains(text, "unknown variant") && contains(text, &named))
}

fn contains(text: &Str, needle: &str) -> bool {
    let hay: Vec<u32> = text.code_points().collect();
    let needle: Vec<u32> = needle.chars().map(|c| c as u32).collect();
    hay.windows(needle.len().max(1))
        .any(|window| window == needle.as_slice())
        || needle.is_empty()
}

/// `_note(backend, method, code)`: keep what the helper met for `method`.
pub fn note(backend: &mut Backend, method: &str, code: &str) {
    let entry = {
        let mut held = noted();
        held.sequence += 1;
        let entry = (code.to_owned(), held.sequence);
        put(&mut held.results, method, entry.clone());
        entry
    };
    put(&mut backend.protocol_results, method, entry);
}

/// `last_result(method, results)`: what the helper last met for `method` - its own call's code, or the start's where
/// that came after it - or None where it has not been asked here.
pub fn last_result(method: &str, results: Option<&Results>) -> Option<String> {
    let global;
    let results = match results {
        Some(results) => results,
        None => {
            global = noted().results.clone();
            &global
        }
    };
    let find = |name: &str| {
        results
            .iter()
            .find(|(each, _)| each == name)
            .map(|(_, entry)| entry.clone())
    };
    let (own, start) = (find(method), find("initialize"));
    if let Some(start) = &start
        && start.0 != "ok"
        && own.as_ref().is_none_or(|own| start.1 > own.1)
    {
        return Some(start.0.clone());
    }
    own.map(|own| own.0)
}

// ------------------------------------------------------------------------------------------------ reading lines
/// A text-mode pipe as Python reads one: UTF-8 with replacement, `\r\n` and `\r` read as `\n`.
pub struct TextReader<R: Read> {
    inner: BufReader<R>,
    pending: Option<char>,
}

impl<R: Read> TextReader<R> {
    pub fn new(inner: R) -> TextReader<R> {
        TextReader {
            inner: BufReader::new(inner),
            pending: None,
        }
    }

    fn peek_byte(&mut self) -> std::io::Result<Option<u8>> {
        Ok(self.inner.fill_buf()?.first().copied())
    }

    /// One character, decoded with replacement (a maximal invalid subpart is one U+FFFD).
    fn decoded(&mut self) -> std::io::Result<Option<char>> {
        let Some(lead) = self.peek_byte()? else {
            return Ok(None);
        };
        self.inner.consume(1);
        let (need, low, high): (usize, u8, u8) = match lead {
            0x00..=0x7F => return Ok(Some(char::from(lead))),
            0xC2..=0xDF => (1, 0x80, 0xBF),
            0xE0 => (2, 0xA0, 0xBF),
            0xE1..=0xEC | 0xEE..=0xEF => (2, 0x80, 0xBF),
            0xED => (2, 0x80, 0x9F),
            0xF0 => (3, 0x90, 0xBF),
            0xF1..=0xF3 => (3, 0x80, 0xBF),
            0xF4 => (3, 0x80, 0x8F),
            _ => return Ok(Some('\u{FFFD}')),
        };
        let mut value = u32::from(lead) & (0x7F >> (need + 1));
        for index in 0..need {
            let (lo, hi) = if index == 0 {
                (low, high)
            } else {
                (0x80, 0xBF)
            };
            match self.peek_byte()? {
                Some(byte) if (lo..=hi).contains(&byte) => {
                    self.inner.consume(1);
                    value = (value << 6) | (u32::from(byte) & 0x3F);
                }
                _ => return Ok(Some('\u{FFFD}')),
            }
        }
        Ok(Some(char::from_u32(value).unwrap_or('\u{FFFD}')))
    }

    /// One character with universal newlines.
    fn next_char(&mut self) -> std::io::Result<Option<char>> {
        let found = match self.pending.take() {
            Some(c) => Some(c),
            None => self.decoded()?,
        };
        if found == Some('\r') {
            match self.decoded()? {
                Some('\n') | None => {}
                Some(other) => self.pending = Some(other),
            }
            return Ok(Some('\n'));
        }
        Ok(found)
    }

    /// `readline(limit)`: up to `limit` characters, ending at a newline it keeps.
    pub fn readline(&mut self, limit: usize) -> std::io::Result<Vec<char>> {
        let mut line = Vec::new();
        while line.len() < limit {
            match self.next_char()? {
                Some(c) => {
                    line.push(c);
                    if c == '\n' {
                        break;
                    }
                }
                None => break,
            }
        }
        Ok(line)
    }
}

/// What `next_message` reads.
#[derive(Clone, Debug, PartialEq)]
pub enum Message {
    /// The stream ended.
    End,
    /// A line that is no message this client reads.
    Skipped,
    /// A message: a JSON object.
    Value(Map),
    /// A line nested past what the reader takes: the reference's RecursionError, which ends its reader thread.
    TooDeep,
}

fn text_of(chars: &[char]) -> String {
    chars.iter().collect()
}

/// `next_message(stream)`: the next message on a Codex server's stdout. `log` hears the line the reference's logger
/// is told for a line it drops.
pub fn next_message<R: Read>(
    stream: &mut TextReader<R>,
    log: &mut dyn FnMut(&str),
) -> std::io::Result<Message> {
    let line = stream.readline(LINE_LIMIT + 1)?;
    if line.is_empty() {
        return Ok(Message::End);
    }
    if line.last() == Some(&'\n') || line.len() <= LINE_LIMIT {
        return Ok(match loads(&text_of(&line)) {
            Ok(Value::Object(map)) => Message::Value(map),
            Ok(_) | Err(LoadsError::Value | LoadsError::IntTooLong) => Message::Skipped,
            Err(LoadsError::Recursion) => Message::TooDeep,
        });
    }
    let head: Vec<char> = line[..KEPT].to_vec();
    let mut tail: Vec<char> = line[line.len() - KEPT..].to_vec();
    let mut size = line.len();
    loop {
        let piece = stream.readline(LINE_LIMIT)?;
        if piece.is_empty() {
            break;
        }
        size += piece.len();
        if piece.len() >= KEPT {
            tail = piece[piece.len() - KEPT..].to_vec();
        } else {
            tail.extend_from_slice(&piece);
            let extra = tail.len().saturating_sub(KEPT);
            tail.drain(..extra);
        }
        if piece.last() == Some(&'\n') {
            break;
        }
    }
    Ok(oversize(&head, &tail, size, log))
}

fn skip_space(text: &[char], mut at: usize) -> usize {
    while text.get(at).is_some_and(|c| is_space(*c)) {
        at += 1;
    }
    at
}

/// `_members(head)`: the top-level members of the JSON object `head` begins, and the key whose value runs past it.
pub fn members(head: &[char]) -> (Map, Option<Str>) {
    let mut seen = Map::new();
    let mut position = skip_space(head, 0);
    if head.get(position) != Some(&'{') {
        return (seen, None);
    }
    position = skip_space(head, position + 1);
    while position < head.len() {
        let Ok((key, after)) = raw_decode(head, position) else {
            return (seen, None);
        };
        position = skip_space(head, after);
        let Value::Str(key) = key else {
            return (seen, None);
        };
        if head.get(position) != Some(&':') {
            return (seen, None);
        }
        position = skip_space(head, position + 1);
        let Ok((value, after)) = raw_decode(head, position) else {
            return (seen, Some(key));
        };
        position = skip_space(head, after);
        if position >= head.len() {
            return (seen, Some(key));
        }
        seen.insert(key, value);
        if head.get(position) != Some(&',') {
            return (seen, None);
        }
        position = skip_space(head, position + 1);
    }
    (seen, None)
}

fn is_digit(c: char) -> bool {
    decimal_value(c).is_some()
}

/// `_LAST_ID.search(tail)`: `"id"\s*:\s*(-?\d+|"(?:[^"\\]|\\.)*")\s*\}\s*$`, the id's text.
fn last_id(tail: &[char]) -> Option<String> {
    let word: Vec<char> = "\"id\"".chars().collect();
    for start in 0..tail.len() {
        if !tail[start..].starts_with(&word) {
            continue;
        }
        let mut at = skip_space(tail, start + word.len());
        if tail.get(at) != Some(&':') {
            continue;
        }
        at = skip_space(tail, at + 1);
        let begin = at;
        if tail.get(at) == Some(&'"') {
            at += 1;
            let mut closed = false;
            while let Some(c) = tail.get(at) {
                match c {
                    '"' => {
                        at += 1;
                        closed = true;
                        break;
                    }
                    '\\' => {
                        if tail.get(at + 1).is_none_or(|next| *next == '\n') {
                            break;
                        }
                        at += 2;
                    }
                    _ => at += 1,
                }
            }
            if !closed {
                continue;
            }
        } else {
            if tail.get(at) == Some(&'-') {
                at += 1;
            }
            let digits = at;
            while tail.get(at).is_some_and(|c| is_digit(*c)) {
                at += 1;
            }
            if at == digits {
                continue;
            }
        }
        let group = text_of(&tail[begin..at]);
        let after = skip_space(tail, at);
        if tail.get(after) != Some(&'}') {
            continue;
        }
        if skip_space(tail, after + 1) == tail.len() {
            return Some(group);
        }
    }
    None
}

/// `_ERROR_CODE.match(head)`: `\{\s*"error"\s*:\s*\{\s*"code"\s*:\s*(-?\d+)\s*[,}]`, the code as `int()` reads it.
fn error_code(head: &[char]) -> Option<Value> {
    let expect = |at: usize, word: &str| -> Option<usize> {
        let chars: Vec<char> = word.chars().collect();
        head[at.min(head.len())..]
            .starts_with(&chars)
            .then_some(at + chars.len())
    };
    let mut at = expect(0, "{")?;
    at = expect(skip_space(head, at), "\"error\"")?;
    at = expect(skip_space(head, at), ":")?;
    at = expect(skip_space(head, at), "{")?;
    at = expect(skip_space(head, at), "\"code\"")?;
    at = expect(skip_space(head, at), ":")?;
    at = skip_space(head, at);
    let mut digits = String::new();
    if head.get(at) == Some(&'-') {
        digits.push('-');
        at += 1;
    }
    let start = at;
    while let Some(value) = head.get(at).and_then(|c| decimal_value(*c)) {
        digits.push(char::from_digit(value, 10)?);
        at += 1;
    }
    if at == start {
        return None;
    }
    at = skip_space(head, at);
    matches!(head.get(at), Some(',' | '}'))
        .then(|| Int::parse(&digits).map(Value::Int).unwrap_or(Value::Null))
}

fn megabytes(size: usize) -> usize {
    size.div_ceil(LINE_LIMIT)
}

/// `_oversize(head, tail, size)`: what an oversize line is, from its head and its tail alone.
pub fn oversize(head: &[char], tail: &[char], size: usize, log: &mut dyn FnMut(&str)) -> Message {
    let (seen, cut) = members(head);
    let method = seen.get("method");
    let mut ident = seen.get("id").cloned().unwrap_or(Value::Null);
    if let Some(Value::Str(method)) = method {
        if seen.contains_key("id") && matches!(ident, Value::Int(_) | Value::Str(_)) {
            let mut out = Map::new();
            out.insert(Str::from("id"), ident);
            out.insert(Str::from("method"), Value::Str(method.clone()));
            return Message::Value(out);
        }
        let shown: Vec<u32> = method.code_points().take(80).collect();
        let shown = Str::from_code_points(shown).unwrap_or_default();
        log(&format!(
            "a notification of {} MB was not read: {}",
            megabytes(size),
            car_machine::pytext::py_str(&Value::Str(shown))
        ));
        return Message::Skipped;
    }
    let mut kind = cut
        .as_ref()
        .and_then(Str::as_str)
        .filter(|word| ["result", "error"].contains(word))
        .map(str::to_owned);
    if kind.is_none() {
        kind = ["result", "error"]
            .iter()
            .find(|key| seen.contains_key(**key))
            .map(|key| (*key).to_owned());
    }
    if kind.is_some()
        && !seen.contains_key("id")
        && let Some(found) = last_id(tail)
    {
        ident = loads(&found).unwrap_or(Value::Null);
    }
    if let Some(kind) = kind
        && matches!(ident, Value::Int(_) | Value::Str(_))
    {
        let mut payload = Map::new();
        payload.insert(Str::from(OVERSIZE), Value::Bool(true));
        if kind == "error"
            && let Some(code) = error_code(head)
        {
            payload.insert(Str::from("code"), code);
        }
        let mut out = Map::new();
        out.insert(Str::from("id"), ident);
        out.insert(Str::from(kind.as_str()), Value::Object(payload));
        return Message::Value(out);
    }
    log(&format!(
        "a line of {} MB was not read: unknown",
        megabytes(size)
    ));
    Message::Skipped
}

// ------------------------------------------------------------------------------------------------ the helper
/// What a protocol session writes to: the helper's input, shared by the caller and the reader.
type Input = Arc<Mutex<Option<ChildStdin>>>;

/// What a text-mode pipe opened with `errors="replace"` writes of a value's texts: each lone surrogate as `?`.
fn replaced(value: &Value) -> Value {
    let text = |text: &Str| {
        if text.has_surrogate() {
            let kept: String = text
                .code_points()
                .map(|point| char::from_u32(point).unwrap_or('?'))
                .collect();
            Str::new(&kept)
        } else {
            text.clone()
        }
    };
    match value {
        Value::Str(each) => Value::Str(text(each)),
        Value::Array(items) => Value::Array(items.iter().map(replaced).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, each)| (text(key), replaced(each)))
                .collect(),
        ),
        other => other.clone(),
    }
}

/// `_write(payload)`: `json.dumps(payload, ensure_ascii=False, allow_nan=False)` and a new line, through the
/// helper's text-mode input (UTF-8, `errors="replace"`): a lone surrogate - an echoed request id can hold one - is
/// written as `?`, never refused.
fn write_line(input: &Input, payload: &Value) -> Result<()> {
    let text = match to_string(payload, &Options::wire()) {
        Ok(text) => text,
        Err(car_machine::json::Error::Surrogate) => to_string(&replaced(payload), &Options::wire())
            .map_err(|_| Error::Python("ValueError"))?,
        Err(_) => return Err(Error::Python("ValueError")),
    };
    let mut held = input
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let stream = held.as_mut().ok_or(Error::Os)?;
    // A text-mode pipe on Windows writes "\n" as "\r\n".
    let bytes = text.replace('\n', "\r\n").into_bytes();
    stream.write_all(&bytes)?;
    stream.write_all(b"\r\n")?;
    stream.flush()?;
    Ok(())
}

/// Lines the reader's logger was told, for whoever asks (the reference logs them at INFO).
pub static SAID: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// The helper's stdout as the reader thread reads it, with the reference's `process.stdout.close()`: once `closed`
/// is set, the read in progress ends as it would and the next one fails (`ValueError: I/O operation on closed
/// file`), so the reader returns, as Python's buffered reader lets a close in only between two reads.
struct Closable {
    inner: std::process::ChildStdout,
    closed: Arc<AtomicBool>,
}

impl Read for Closable {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        if self.closed.load(Ordering::SeqCst) {
            return Err(std::io::Error::other("I/O operation on closed file"));
        }
        self.inner.read(buffer)
    }
}

fn reader(stdout: Closable, input: Input, answers: SyncSender<Map>) {
    let mut stream = TextReader::new(stdout);
    let mut log = |line: &str| {
        SAID.lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .push(line.to_owned());
    };
    loop {
        let message = match next_message(&mut stream, &mut log) {
            Ok(message) => message,
            Err(_) => return,
        };
        let value = match message {
            Message::End | Message::TooDeep => return,
            Message::Skipped => continue,
            Message::Value(value) => value,
        };
        if value.contains_key("id") && value.contains_key("method") {
            let refusal = object(vec![
                ("id", value["id"].clone()),
                (
                    "error",
                    object(vec![
                        ("code", Value::from(-32601)),
                        ("message", Value::from("Client requests unsupported")),
                    ]),
                ),
            ]);
            if write_line(&input, &refusal).is_err() {
                return;
            }
        } else if value.contains_key("id")
            && (value.contains_key("result") || value.contains_key("error"))
        {
            match answers.try_send(value) {
                Ok(()) => {}
                Err(TrySendError::Full(_) | TrySendError::Disconnected(_)) => return,
            }
        }
    }
}

/// `Protocol`: a finite separate stdio server that reads the usage or deletes one owned queue item.
pub struct Protocol<'a> {
    pub backend: &'a mut Backend,
    process: Option<Child>,
    input: Input,
    answers: Option<Receiver<Map>>,
    reader: Option<std::thread::JoinHandle<()>>,
    /// `process.stdout.close()`, as the reader sees it.
    closed: Arc<AtomicBool>,
    sequence: i64,
    /// What the last error answer was: METHOD_UNKNOWN or REFUSED.
    pub refusal: Option<&'static str>,
}

impl<'a> Protocol<'a> {
    /// `__enter__`: start the helper, say who we are, and check that it serves this home on Windows.
    pub fn open(backend: &'a mut Backend) -> Result<Protocol<'a>> {
        backend.compatible()?;
        let mut session = Protocol {
            backend,
            process: None,
            input: Arc::new(Mutex::new(None)),
            answers: None,
            reader: None,
            closed: Arc::new(AtomicBool::new(false)),
            sequence: 0,
            refusal: None,
        };
        match session.start() {
            Ok(()) => Ok(session),
            Err(error) => {
                if let Error::Adapter(code) = &error
                    && code.starts_with("protocol_")
                {
                    let met = session.noted(code);
                    note(session.backend, "initialize", met);
                }
                session.close();
                Err(error)
            }
        }
    }

    fn start(&mut self) -> Result<()> {
        let mut argv = self.backend.argv();
        argv.extend(["app-server".to_owned(), "--stdio".to_owned()]);
        let spawn = car_platform::spawn::Spawn::new(argv)
            .with_env(self.backend.environment())
            .with_cwd(&self.backend.codex_home)
            .with_streams(
                car_platform::spawn::Stream::Piped,
                car_platform::spawn::Stream::Piped,
                car_platform::spawn::Stream::Null,
            );
        let mut child = car_platform::spawn::SystemStarter
            .start_guarded(&spawn, cfg!(test))
            .map_err(|_| Error::Os)?;
        let stdout = child.stdout.take();
        *self.input.lock().unwrap_or_else(|p| p.into_inner()) = child.stdin.take();
        self.process = Some(child);
        let (send, receive) = sync_channel(RESPONSES);
        self.answers = Some(receive);
        if let Some(stdout) = stdout {
            let input = Arc::clone(&self.input);
            let stdout = Closable {
                inner: stdout,
                closed: Arc::clone(&self.closed),
            };
            self.reader = Some(car_machine::stack::spawn_deep(move || {
                reader(stdout, input, send)
            }));
        }
        let version = self.backend.product_version.clone();
        let params = object(vec![
            (
                "clientInfo",
                object(vec![
                    ("name", Value::from("codex_auto_resume")),
                    ("version", Value::from(version.as_str())),
                ]),
            ),
            (
                "capabilities",
                object(vec![("experimentalApi", Value::Bool(true))]),
            ),
        ]);
        let response = self.call("initialize", Some(params))?;
        let Value::Object(reply) = &response else {
            return Err(Error::Adapter("protocol_home_mismatch"));
        };
        let home = match reply.get("codexHome") {
            None => String::new(),
            Some(Value::Str(text)) => text
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| String::from_utf8_lossy(text.as_bytes()).into_owned()),
            Some(_) => return Err(Error::Python("TypeError")),
        };
        let resolved = self
            .backend
            .system
            .resolve(&car_config::winpath::path_str(&home))
            .ok_or(Error::Os)?;
        if crate::refold::lower_points(&crate::refold::points(&resolved))
            != crate::refold::lower_points(&crate::refold::points(&self.backend.codex_home))
        {
            return Err(Error::Adapter("protocol_home_mismatch"));
        }
        if !pyval::is(reply.get("platformOs").unwrap_or(&Value::Null), "windows") {
            return Err(Error::Adapter("protocol_platform_mismatch"));
        }
        write_line(
            &self.input,
            &object(vec![("method", Value::from("initialized"))]),
        )?;
        note(self.backend, "initialize", "ok");
        Ok(())
    }

    /// `_noted(error)`: what the helper met, as RESULTS keeps it.
    fn noted(&self, code: &'static str) -> &'static str {
        if code == "protocol_request_failed" {
            self.refusal.unwrap_or(REFUSED)
        } else {
            code
        }
    }

    /// `call(method, params)`.
    pub fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value> {
        if !PROTOCOL_METHODS.contains(&method) {
            return Err(Error::Adapter("protocol_method_not_allowed"));
        }
        if method == "initialize" {
            return self.exchange(method, params);
        }
        let result = match self.exchange(method, params) {
            Ok(result) => result,
            Err(Error::Adapter(code)) => {
                let met = self.noted(code);
                note(self.backend, method, met);
                return Err(Error::Adapter(code));
            }
            Err(other) => return Err(other),
        };
        let unread = method == "account/rateLimits/read"
            && pyval::is(
                parse_usage(&result)
                    .map_err(Error::Python)?
                    .get("reason")
                    .unwrap_or(&Value::Null),
                "usage_snapshot_unknown",
            );
        note(
            self.backend,
            method,
            if unread {
                "protocol_reply_unknown"
            } else {
                "ok"
            },
        );
        Ok(result)
    }

    /// `_call(method, params)`: one request, and its answer within CALL_SECONDS.
    fn exchange(&mut self, method: &str, params: Option<Value>) -> Result<Value> {
        self.refusal = None;
        self.sequence += 1;
        let sequence = Value::from(self.sequence);
        let mut request = Map::new();
        request.insert(Str::from("id"), sequence.clone());
        request.insert(Str::from("method"), Value::from(method));
        if let Some(params) = params {
            request.insert(Str::from("params"), params);
        }
        let unavailable = Error::Adapter("protocol_unavailable");
        if write_line(&self.input, &Value::Object(request)).is_err() {
            return Err(unavailable);
        }
        let deadline = Instant::now() + Duration::from_secs_f64(CALL_SECONDS);
        let Some(answers) = &self.answers else {
            return Err(unavailable);
        };
        while Instant::now() < deadline {
            let left = deadline
                .saturating_duration_since(Instant::now())
                .max(Duration::from_millis(10));
            let response = match answers.recv_timeout(left) {
                Ok(response) => response,
                Err(RecvTimeoutError::Timeout | RecvTimeoutError::Disconnected) => {
                    // queue.get(timeout=...) waits its whole time whether or not the reader still runs.
                    if let Some(rest) = deadline.checked_duration_since(Instant::now()) {
                        std::thread::sleep(rest);
                    }
                    return Err(unavailable);
                }
            };
            if !pyval::eq(response.get("id").unwrap_or(&Value::Null), &sequence) {
                // Another call's answer: dropped, as the reference's queue drops it.
                continue;
            }
            if response.contains_key("error") {
                self.refusal = Some(
                    if unknown(response.get("error").unwrap_or(&Value::Null), method) {
                        METHOD_UNKNOWN
                    } else {
                        REFUSED
                    },
                );
                return Err(Error::Adapter("protocol_request_failed"));
            }
            return Ok(response.get("result").cloned().unwrap_or(Value::Null));
        }
        Err(Error::Adapter("protocol_timeout"))
    }

    /// `__exit__`: close the helper's input, give it EXIT_SECONDS to end, end it, give the reader JOIN_SECONDS, then
    /// close its stdout: the close waits for the read in progress (a process the helper started can hold the pipe
    /// open after the helper ended), the next read fails, and the reader thread is joined - none is left running.
    pub fn close(&mut self) {
        let Some(mut process) = self.process.take() else {
            return;
        };
        drop(
            self.input
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .take(),
        );
        if !wait(&mut process, EXIT_SECONDS) {
            let _ = process.kill(); // only our own finite helper
            wait(&mut process, EXIT_SECONDS);
        }
        if let Some(reader) = self.reader.take() {
            let until = Instant::now() + Duration::from_secs_f64(JOIN_SECONDS);
            while !reader.is_finished() && Instant::now() < until {
                std::thread::sleep(Duration::from_millis(5));
            }
            self.closed.store(true, Ordering::SeqCst);
            let _ = reader.join();
        }
        self.answers = None;
    }
}

impl Drop for Protocol<'_> {
    fn drop(&mut self) {
        self.close();
    }
}

/// Wait up to `seconds` for the process to end: whether it did.
fn wait(process: &mut Child, seconds: f64) -> bool {
    let until = Instant::now() + Duration::from_secs_f64(seconds);
    loop {
        match process.try_wait() {
            Ok(Some(_)) => return true,
            Ok(None) => {}
            Err(_) => return false,
        }
        if Instant::now() >= until {
            return false;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// `errors="replace"` on the helper's input: a lone surrogate of an echoed id is `?`, the rest as it is.
    #[test]
    fn a_lone_surrogate_is_written_as_a_question_mark() {
        let lone = Str::from_code_points([0x61, 0xD800, 0x62, 0xDC00, 0x1F600]).unwrap();
        let mut payload = Map::new();
        payload.insert(Str::from("id"), Value::Str(lone));
        payload.insert(Str::from("n"), Value::from(1));
        let payload = Value::Object(payload);
        assert!(matches!(
            to_string(&payload, &Options::wire()),
            Err(car_machine::json::Error::Surrogate)
        ));
        assert_eq!(
            to_string(&replaced(&payload), &Options::wire()).unwrap(),
            "{\"id\": \"a?b?\u{1F600}\", \"n\": 1}"
        );
    }
}

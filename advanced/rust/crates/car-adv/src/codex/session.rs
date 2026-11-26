//! `codex/protocol.py`'s `Session` and `submitted` (seat adv72d): the one-turn App Server helper over
//! `codex app-server --stdio`, opened for one measurement or one capability, the methods it may call fixed by
//! [`protocol::methods_for`] / [`protocol::methods_for_capability`].
//!
//! It initialises and checks the home as the reference does (not the platform: that is core's helper's), answers every
//! request Codex makes with that request's own refusal ([`protocol::reply_to`]) and counts it by method, queues the
//! answers (128, the reader ends when full) and the notifications (1,024, dropped when full), and on exit unsubscribes
//! from every thread it resumed, closes its input, waits four seconds, ends only its own process, and lets the reader
//! go. The process is started through car-platform's one starter (`CREATE_NO_WINDOW`), counted as our own app server
//! by car-codex's `pairing::own_server` for its life. The line reading is car-codex's (`TextReader`, `next_message`:
//! the text-mode pipe's decoding and the bounded read); a request is written as a text-mode pipe writes it (`\r\n`).
//!
//! [`Channel`] is what [`submitted`] and car-adv's `headless` need of a session; a test's stand-in implements it.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::io::Write;
use std::process::{Child, ChildStdin};
use std::sync::mpsc::{Receiver, RecvTimeoutError, TrySendError, sync_channel};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::{Duration, Instant};

use car_codex::appserver::{Message, TextReader, next_message};
use car_codex::errors::Error;
use car_codex::transport::Backend;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;

use super::protocol;
use crate::vocabulary::Measurement;

/// How long `receive` waits by default, and how long the exit waits for the process.
pub const RECEIVE_SECONDS: f64 = 25.0;
pub const EXIT_SECONDS: f64 = 4.0;
pub const JOIN_SECONDS: f64 = 1.0;
pub const RESPONSES: usize = 128;
pub const EVENTS: usize = 1024;
/// `str(SessionRefused(...))`.
pub const NOT_PERMITTED: &str = "method not permitted for this session";

/// What a session raised, by the reference's class.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionError {
    /// `SessionRefused`: a method this session may not call.
    Refused,
    /// `AdapterError(code)`.
    Adapter(&'static str),
    /// `RefusedByCodex` (an AdapterError "protocol_request_failed"): Codex answered no, with its numeric code.
    ByCodex { method: String, code: Option<i64> },
    /// Any other exception, by class (`ValueError`, `TypeError`, `OSError`, ...).
    Raised(&'static str),
}

impl SessionError {
    /// `str(exc)` where the reference reads it (`protocol_timeout`), or the class's words.
    pub fn text(&self) -> &str {
        match self {
            SessionError::Refused => NOT_PERMITTED,
            SessionError::Adapter(code) => code,
            SessionError::ByCodex { .. } => "protocol_request_failed",
            SessionError::Raised(class) => class,
        }
    }

    /// The `method` a RefusedByCodex carries (`getattr(exc, "method", None)`).
    pub fn method(&self) -> Option<&str> {
        match self {
            SessionError::ByCodex { method, .. } => Some(method),
            _ => None,
        }
    }

    pub fn class(&self) -> &'static str {
        match self {
            SessionError::Refused => "SessionRefused",
            SessionError::Adapter(_) => "AdapterError",
            SessionError::ByCodex { .. } => "RefusedByCodex",
            SessionError::Raised(class) => class,
        }
    }
}

fn from_core(error: Error) -> SessionError {
    match error {
        Error::Adapter(code) => SessionError::Adapter(code),
        Error::Os => SessionError::Raised("OSError"),
        Error::Python(class) => SessionError::Raised(class),
        Error::Sqlite => SessionError::Raised("Error"),
        Error::Source(refused) => SessionError::Raised(refused.class()),
    }
}

type Input = Arc<Mutex<Option<ChildStdin>>>;

/// `_write(payload)`: one line as a text-mode pipe writes it (`\n` as `\r\n`, what UTF-8 cannot carry replaced).
fn write_line(input: &Input, payload: &Value) -> Result<(), SessionError> {
    let text =
        to_string(payload, &Options::wire()).map_err(|_| SessionError::Raised("ValueError"))?;
    let mut held = input.lock().unwrap_or_else(PoisonError::into_inner);
    let stream = held.as_mut().ok_or(SessionError::Raised("ValueError"))?;
    let bytes = String::from_utf8_lossy(text.as_bytes())
        .replace('\n', "\r\n")
        .into_bytes();
    stream
        .write_all(&bytes)
        .and_then(|()| stream.write_all(b"\r\n"))
        .and_then(|()| stream.flush())
        .map_err(|_| SessionError::Raised("OSError"))
}

/// What the reader counts: what was declined with a refusal and what was refused with an error, by method.
#[derive(Debug, Default)]
struct Counts {
    declined: BTreeMap<String, i64>,
    refused: BTreeMap<String, i64>,
}

/// What a session's notifications are kept in.
type Events = Arc<Mutex<VecDeque<Map>>>;

fn read(
    stdout: std::process::ChildStdout,
    input: Input,
    answers: std::sync::mpsc::SyncSender<Map>,
    events: Events,
    counts: Arc<Mutex<Counts>>,
) {
    let mut stream = TextReader::new(stdout);
    let mut log = |_: &str| {};
    loop {
        let value = match next_message(&mut stream, &mut log) {
            Ok(Message::Value(value)) => value,
            Ok(Message::Skipped) => continue,
            Ok(Message::End | Message::TooDeep) | Err(_) => return,
        };
        if value.contains_key("id") && value.contains_key("method") {
            let reply = protocol::reply_to(&Value::Object(value.clone()));
            if write_line(&input, &reply).is_err() {
                return;
            }
            let method = match value.get("method") {
                Some(Value::Str(text)) => String::from_utf8_lossy(text.as_bytes()).into_owned(),
                _ => "?".to_owned(),
            };
            let declined = matches!(&reply, Value::Object(map) if map.contains_key("result"));
            let mut held = counts.lock().unwrap_or_else(PoisonError::into_inner);
            let table = if declined {
                &mut held.declined
            } else {
                &mut held.refused
            };
            *table.entry(method).or_insert(0) += 1;
        } else if value.contains_key("id")
            && (value.contains_key("result") || value.contains_key("error"))
        {
            match answers.try_send(value) {
                Ok(()) => {}
                Err(TrySendError::Full(_) | TrySendError::Disconnected(_)) => return,
            }
        } else if value.contains_key("method") {
            let mut held = events.lock().unwrap_or_else(PoisonError::into_inner);
            if held.len() < EVENTS {
                held.push_back(value);
            }
        }
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

/// What a session is to `submitted` and to a headless run: a request written now and its answer awaited later, one
/// call whole, the notifications so far, and the way in and out.
pub trait Channel: Send {
    fn enter(&mut self) -> Result<(), SessionError>;
    fn submit(&mut self, method: &str, params: Option<Value>) -> Result<i64, SessionError>;
    fn receive(
        &mut self,
        method: &str,
        sequence: i64,
        params: Option<&Value>,
    ) -> Result<Value, SessionError>;
    fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value, SessionError> {
        let sequence = self.submit(method, params.clone())?;
        self.receive(method, sequence, params.as_ref())
    }
    fn drain_events(&mut self) -> Vec<Value>;
    /// `__exit__`: never raises.
    fn exit(&mut self);
}

/// A one-turn App Server helper for one measurement or one capability.
pub struct Session {
    pub backend: Backend,
    /// Codex's own `-c key=value` settings the server starts with.
    pub config: Vec<(String, String)>,
    pub measurement: Option<Measurement>,
    pub allowed: BTreeSet<&'static str>,
    process: Option<Child>,
    input: Input,
    sequence: i64,
    responses: Option<Receiver<Map>>,
    events: Events,
    counts: Arc<Mutex<Counts>>,
    subscribed: Vec<Value>,
    reader: Option<std::thread::JoinHandle<()>>,
    own: Option<(Value, Value)>,
}

impl Session {
    /// `Session(backend, measurement, capability=..., config=...)`: one of the two, never both or neither (ValueError).
    pub fn new(
        backend: Backend,
        measurement: Option<Measurement>,
        capability: Option<&str>,
        config: Vec<(String, String)>,
    ) -> Result<Session, SessionError> {
        let allowed = match (measurement, capability) {
            (Some(measurement), None) => protocol::methods_for(measurement),
            (None, Some(capability)) => protocol::methods_for_capability(capability),
            _ => return Err(SessionError::Raised("ValueError")),
        };
        Ok(Session {
            backend,
            config,
            measurement,
            allowed,
            process: None,
            input: Arc::new(Mutex::new(None)),
            sequence: 0,
            responses: None,
            events: Arc::default(),
            counts: Arc::default(),
            subscribed: Vec::new(),
            reader: None,
            own: None,
        })
    }

    fn start(&mut self) -> Result<(), SessionError> {
        let mut argv = self.backend.argv();
        for (key, value) in &self.config {
            argv.push("-c".to_owned());
            argv.push(format!("{key}={value}"));
        }
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
            .start(&spawn)
            .map_err(|_| SessionError::Raised("OSError"))?;
        let stdout = child.stdout.take();
        *self.input.lock().unwrap_or_else(PoisonError::into_inner) = child.stdin.take();
        let pid = Value::from(i64::from(child.id()));
        self.process = Some(child);
        self.own = car_codex::pairing::own_server(self.backend.system.as_ref(), &pid)
            .map_err(from_core)?;
        let (send, receive) = sync_channel(RESPONSES);
        self.responses = Some(receive);
        if let Some(stdout) = stdout {
            let (input, events, counts) = (
                Arc::clone(&self.input),
                Arc::clone(&self.events),
                Arc::clone(&self.counts),
            );
            self.reader = Some(car_machine::stack::spawn_deep(move || {
                read(stdout, input, send, events, counts)
            }));
        }
        Ok(())
    }

    fn hello(&mut self) -> Result<(), SessionError> {
        let mut info = Map::new();
        info.insert("name".into(), "codex_auto_resume".into());
        info.insert(
            "version".into(),
            self.backend.product_version.as_str().into(),
        );
        let mut capabilities = Map::new();
        capabilities.insert("experimentalApi".into(), Value::Bool(true));
        let mut params = Map::new();
        params.insert("clientInfo".into(), Value::Object(info));
        params.insert("capabilities".into(), Value::Object(capabilities));
        let response = self.call("initialize", Some(Value::Object(params)))?;
        let Value::Object(reply) = &response else {
            return Err(SessionError::Adapter("protocol_home_mismatch"));
        };
        let home = match reply.get("codexHome") {
            None => String::new(),
            Some(Value::Str(text)) => String::from_utf8_lossy(text.as_bytes()).into_owned(),
            Some(_) => return Err(SessionError::Raised("TypeError")),
        };
        let resolved = self
            .backend
            .system
            .resolve(&car_config::winpath::path_str(&home))
            .ok_or(SessionError::Raised("OSError"))?;
        let fold = |text: &str| car_codex::refold::lower_points(&car_codex::refold::points(text));
        if fold(&resolved) != fold(&self.backend.codex_home) {
            return Err(SessionError::Adapter("protocol_home_mismatch"));
        }
        let mut initialized = Map::new();
        initialized.insert("method".into(), "initialized".into());
        write_line(&self.input, &Value::Object(initialized))
    }

    /// `declined_count()`: how many requests were answered with their refusal so far.
    pub fn declined_count(&self) -> i64 {
        self.counts
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .declined
            .values()
            .sum()
    }

    /// The two counters by method: (declined, refused).
    pub fn counted(&self) -> (BTreeMap<String, i64>, BTreeMap<String, i64>) {
        let held = self.counts.lock().unwrap_or_else(PoisonError::into_inner);
        (held.declined.clone(), held.refused.clone())
    }

    /// `receive(method, sequence, params, seconds)`.
    pub fn receive_within(
        &mut self,
        method: &str,
        sequence: i64,
        params: Option<&Value>,
        seconds: f64,
    ) -> Result<Value, SessionError> {
        let unavailable = SessionError::Adapter("protocol_unavailable");
        let deadline = Instant::now() + Duration::from_secs_f64(seconds.max(0.0));
        let Some(answers) = &self.responses else {
            return Err(unavailable);
        };
        let wanted = Value::from(sequence);
        while Instant::now() < deadline {
            let left = deadline
                .saturating_duration_since(Instant::now())
                .max(Duration::from_millis(10));
            let response = match answers.recv_timeout(left) {
                Ok(response) => response,
                Err(RecvTimeoutError::Timeout) => return Err(unavailable),
                Err(RecvTimeoutError::Disconnected) => {
                    // queue.get(timeout=...) waits its whole time whether or not the reader still runs.
                    std::thread::sleep(left);
                    return Err(unavailable);
                }
            };
            if !pyval::eq(response.get("id").unwrap_or(&Value::Null), &wanted) {
                continue;
            }
            if response.contains_key("error") {
                let code = match response.get("error") {
                    Some(Value::Object(error)) => match error.get("code") {
                        Some(Value::Int(code)) => code.as_i64(),
                        _ => None,
                    },
                    _ => None,
                };
                return Err(SessionError::ByCodex {
                    method: method.to_owned(),
                    code,
                });
            }
            if method == "thread/unsubscribe"
                && let Some(Value::Object(params)) = params
            {
                let gone = params.get("threadId").cloned().unwrap_or(Value::Null);
                self.subscribed.retain(|thread| !pyval::eq(thread, &gone));
            }
            return Ok(response.get("result").cloned().unwrap_or(Value::Null));
        }
        Err(SessionError::Adapter("protocol_timeout"))
    }

    fn close(&mut self) {
        let Some(mut process) = self.process.take() else {
            return;
        };
        let subscribed = self.subscribed.clone();
        if self.allowed.contains("thread/unsubscribe") {
            for thread in subscribed {
                let mut params = Map::new();
                params.insert(Str::from("threadId"), thread);
                let _ = self.call("thread/unsubscribe", Some(Value::Object(params)));
            }
        }
        drop(
            self.input
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .take(),
        );
        if !wait(&mut process, EXIT_SECONDS) {
            let _ = process.kill(); // only our own one-turn helper
            wait(&mut process, EXIT_SECONDS);
        }
        if let Some(mark) = self.own.take() {
            car_codex::pairing::own_server_gone(&mark);
        }
        if let Some(reader) = self.reader.take() {
            let until = Instant::now() + Duration::from_secs_f64(JOIN_SECONDS);
            while !reader.is_finished() && Instant::now() < until {
                std::thread::sleep(Duration::from_millis(5));
            }
            if reader.is_finished() {
                let _ = reader.join();
            }
        }
    }
}

impl Channel for Session {
    /// `__enter__`: the engine checked, the server started, `initialize` answered for this home, `initialized` said.
    fn enter(&mut self) -> Result<(), SessionError> {
        self.backend.compatible().map_err(from_core)?;
        self.start()?;
        match self.hello() {
            Ok(()) => Ok(()),
            Err(error) => {
                self.close();
                Err(error)
            }
        }
    }

    /// `submit(method, params)`: one request written, its sequence number.
    fn submit(&mut self, method: &str, params: Option<Value>) -> Result<i64, SessionError> {
        if !self.allowed.contains(method) {
            return Err(SessionError::Refused);
        }
        self.sequence += 1;
        let sequence = self.sequence;
        let params = params.unwrap_or_else(|| Value::Object(Map::new()));
        if method == "thread/resume"
            && let Value::Object(map) = &params
            && let Some(thread) = map.get("threadId")
            && pyval::truthy(thread)
        {
            self.subscribed.push(thread.clone());
        }
        let mut request = Map::new();
        request.insert(Str::from("id"), Value::from(sequence));
        request.insert(Str::from("method"), Value::from(method));
        request.insert(Str::from("params"), params);
        write_line(&self.input, &Value::Object(request))
            .map_err(|_| SessionError::Adapter("protocol_unavailable"))?;
        Ok(sequence)
    }

    fn receive(
        &mut self,
        method: &str,
        sequence: i64,
        params: Option<&Value>,
    ) -> Result<Value, SessionError> {
        self.receive_within(method, sequence, params, RECEIVE_SECONDS)
    }

    /// `drain_events()`: every notification seen so far, taken.
    fn drain_events(&mut self) -> Vec<Value> {
        self.events
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .drain(..)
            .map(Value::Object)
            .collect()
    }

    fn exit(&mut self) {
        self.close();
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        self.close();
    }
}

/// `submitted(session, method, params)`: one request written now, its answer awaited later.
pub enum Submitted {
    Written {
        method: String,
        sequence: i64,
        params: Option<Value>,
    },
    Failed(SessionError),
}

impl Submitted {
    /// The answer, or what the request raised.
    pub fn answer(self, session: &mut dyn Channel) -> Result<Value, SessionError> {
        match self {
            Submitted::Written {
                method,
                sequence,
                params,
            } => session.receive(&method, sequence, params.as_ref()),
            Submitted::Failed(error) => Err(error),
        }
    }
}

/// `submitted(session, method, params)`: never raises itself.
pub fn submitted(session: &mut dyn Channel, method: &str, params: Option<Value>) -> Submitted {
    match session.submit(method, params.clone()) {
        Ok(sequence) => Submitted::Written {
            method: method.to_owned(),
            sequence,
            params,
        },
        Err(error) => Submitted::Failed(error),
    }
}

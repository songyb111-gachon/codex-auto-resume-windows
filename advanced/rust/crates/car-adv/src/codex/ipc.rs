//! `codex/ipc.py`: the Codex Desktop app's own IPC pipe, `\\.\pipe\codex-ipc` - the forced stop near a usage limit
//! ([`stop_turn`]), the turn started after the reset ([`start_turn`]) and MSTEER2's line added to a running turn
//! ([`steer_turn`]) (seat adv72d).
//!
//! Every frame is 4 bytes of little-endian length and UTF-8 JSON; each request has one deadline for its whole answer,
//! however many broadcasts come first; the versions the app checks exactly are pinned ([`request_shape`]). Every
//! outcome is one closed word. The pipe's Windows calls are car-platform's `ipc_pipe` (D3): a connection refused
//! where its server is not this account's own, overlapped I/O cancelled and waited out at its deadline. The pipe's
//! name is a parameter: None is the Desktop's own, which a test never names (car-platform refuses it under test and
//! where `CAR_NO_REAL_IPC` is set).

use std::time::{Duration, Instant};

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pyval;
use car_platform::ipc_pipe::{self, Pipe, PipeError, Way};

pub const PIPE: &str = ipc_pipe::DESKTOP_PIPE;
pub const READ_SECONDS: f64 = 5.0;
pub const INTERRUPT_SECONDS: f64 = 30.0;
pub const FRAMES_LIMIT: usize = 200;
pub const FRAME_LIMIT: usize = 8 * 1024 * 1024;
pub const CLIENT_TYPE: &str = "codex-auto-resume";

/// What came of one request: the closed words the journal keeps.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stop {
    Stopped,
    NotStopped,
    NoClient,
    VersionMismatch,
    NoPipe,
    NoAnswer,
    Unconfirmed,
    Refused,
    Broken,
    Held,
}

impl Stop {
    pub const fn as_str(self) -> &'static str {
        match self {
            Stop::Stopped => "stopped",
            Stop::NotStopped => "not_stopped",
            Stop::NoClient => "no_client",
            Stop::VersionMismatch => "version_mismatch",
            Stop::NoPipe => "no_pipe",
            Stop::NoAnswer => "no_answer",
            Stop::Unconfirmed => "unconfirmed",
            Stop::Refused => "refused",
            Stop::Broken => "broken",
            Stop::Held => "held",
        }
    }
}

/// `Start.STARTED`, `Steer.STEERED`.
pub const STARTED: &str = "started";
pub const STEERED: &str = "steered";

/// What a step raised: `_Failed(word)`, or another exception.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fail {
    Word(Stop),
    Raised,
}

impl From<PipeError> for Fail {
    fn from(error: PipeError) -> Fail {
        Fail::Word(match error {
            PipeError::NoPipe => Stop::NoPipe,
            PipeError::Broken => Stop::Broken,
            PipeError::NoAnswer => Stop::NoAnswer,
        })
    }
}

fn parsed(text: &str) -> Value {
    car_machine::compat::loads(text).unwrap_or(Value::Null)
}

/// `REQUESTS[method]` (and `INTERRUPT_EXPECTING` for the v4 stop): (version, the params' shape).
pub fn request_shape(method: &str, expecting: bool) -> Option<(i64, Value)> {
    let found = match (method, expecting) {
        ("initialize", _) => (0, r#"{"clientType": "codex-auto-resume"}"#),
        ("thread-owner-discovery", _) => {
            (1, r#"{"hostId": "local", "conversationId": "{thread}"}"#)
        }
        ("thread-follower-interrupt-turn", false) => {
            (3, r#"{"conversationId": "{thread}", "mode": "system"}"#)
        }
        ("thread-follower-interrupt-turn", true) => (
            4,
            r#"{"conversationId": "{thread}", "mode": "system", "expectedTurnId": "{turn}"}"#,
        ),
        ("thread-follower-start-turn", _) => (
            2,
            r#"{"conversationId": "{thread}", "turnStart": {"request": {"threadId": "{thread}", "clientUserMessageId": "{message}", "input": [{"type": "text", "text": "{text}", "text_elements": []}]}, "context": {"inheritThreadSettings": true}}}"#,
        ),
        ("thread-follower-steer-turn", _) => (
            1,
            r#"{"conversationId": "{thread}", "clientUserMessageId": "{message}", "input": [{"type": "text", "text": "{text}", "text_elements": []}], "restoreMessage": {"id": "{message}", "text": "{text}", "cwd": null, "context": {"workspaceRoots": [], "collaborationMode": null, "commentAttachments": []}}, "serviceTier": null, "attachments": [], "additionalContext": null, "toolOutput": null}"#,
        ),
        _ => return None,
    };
    Some((found.0, parsed(found.1)))
}

/// `_filled(shape, fields)`: every string `"{name}"` whose name is a field, replaced by that field.
pub fn filled(shape: &Value, fields: &[(&str, Value)]) -> Value {
    match shape {
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, value)| (key.clone(), filled(value, fields)))
                .collect(),
        ),
        Value::Array(items) => {
            Value::Array(items.iter().map(|item| filled(item, fields)).collect())
        }
        Value::Str(text) => {
            if let Some(inner) = text
                .as_str()
                .and_then(|text| text.strip_prefix('{'))
                .and_then(|text| text.strip_suffix('}'))
                && let Some((_, value)) = fields.iter().find(|(name, _)| *name == inner)
            {
                return value.clone();
            }
            shape.clone()
        }
        other => other.clone(),
    }
}

/// Core's errand guard around the one writing that cannot be taken back: `__enter__`'s `permitted` and `__exit__`.
pub trait Gate {
    fn enter(&mut self) -> Result<Value, ()>;
    fn exit(&mut self) -> Result<(), ()>;
}

/// One connection to the pipe.
pub struct Channel {
    pipe: Pipe,
}

impl Channel {
    /// `Channel(name)`: None is the Desktop's own pipe.
    pub fn open(name: Option<&str>) -> Result<Channel, Fail> {
        Ok(Channel {
            pipe: ipc_pipe::open(name.unwrap_or(PIPE))?,
        })
    }

    fn exactly(&mut self, size: usize, seconds: f64) -> Result<Vec<u8>, Fail> {
        let mut found = Vec::with_capacity(size);
        while found.len() < size {
            let mut buffer = vec![0u8; size - found.len()];
            let got = self.pipe.io(Way::Read, &mut buffer, seconds)?;
            if got == 0 {
                return Err(Fail::Word(Stop::Broken));
            }
            found.extend_from_slice(&buffer[..got.min(buffer.len())]);
        }
        Ok(found)
    }

    /// `write(message)`: one frame.
    pub fn write(&mut self, message: &Value) -> Result<(), Fail> {
        let data = to_string(message, &Options::new()).map_err(|_| Fail::Raised)?;
        let mut frame = (data.len() as u32).to_le_bytes().to_vec();
        frame.extend_from_slice(data.as_bytes());
        let length = frame.len();
        if self.pipe.io(Way::Write, &mut frame, READ_SECONDS)? != length {
            return Err(Fail::Word(Stop::Broken));
        }
        Ok(())
    }

    /// `read(seconds)`: one frame, a JSON object.
    pub fn read(&mut self, seconds: f64) -> Result<Map, Fail> {
        let head = self.exactly(4, seconds)?;
        let size = u32::from_le_bytes([head[0], head[1], head[2], head[3]]) as usize;
        if !(0 < size && size <= FRAME_LIMIT) {
            return Err(Fail::Word(Stop::Broken));
        }
        let body = self.exactly(size, seconds)?;
        let text = std::str::from_utf8(&body).map_err(|_| Fail::Word(Stop::Broken))?;
        match car_machine::compat::loads(text) {
            Ok(Value::Object(found)) => Ok(found),
            Ok(_) => Err(Fail::Word(Stop::Broken)),
            Err(car_machine::compat::LoadsError::Recursion) => Err(Fail::Raised),
            Err(_) => Err(Fail::Word(Stop::Broken)),
        }
    }

    pub fn close(&mut self) {
        self.pipe.close();
    }
}

fn get<'a>(map: &'a Map, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    map.get(key).unwrap_or(&NULL)
}

/// `_request(channel, client, method, shape, fields, target, seconds, gate)`: one request and its answer within one
/// deadline from its writing.
#[allow(clippy::too_many_arguments)]
fn request(
    channel: &mut Channel,
    client: &Value,
    method: &str,
    shape: (i64, Value),
    fields: &[(&str, Value)],
    target: Option<&Value>,
    seconds: Option<f64>,
    gate: Option<&mut dyn Gate>,
    ids: &mut dyn FnMut() -> String,
) -> Result<Map, Fail> {
    let (version, params) = shape;
    let key = ids();
    let mut message = Map::new();
    message.insert(Str::from("type"), "request".into());
    message.insert(Str::from("requestId"), key.as_str().into());
    message.insert(Str::from("sourceClientId"), client.clone());
    message.insert(Str::from("version"), version.into());
    message.insert(Str::from("method"), method.into());
    message.insert(Str::from("params"), filled(&params, fields));
    if let Some(target) = target {
        message.insert(Str::from("targetClientId"), target.clone());
    }
    let message = Value::Object(message);
    match gate {
        None => channel.write(&message)?,
        Some(gate) => {
            let permitted = gate.enter().map_err(|()| Fail::Raised)?;
            let inner = if matches!(permitted, Value::Bool(true)) {
                channel.write(&message)
            } else {
                Err(Fail::Word(Stop::Held))
            };
            gate.exit().map_err(|()| Fail::Raised)?;
            inner?;
        }
    }
    let deadline = Instant::now() + Duration::from_secs_f64(seconds.unwrap_or(READ_SECONDS));
    let key = Value::from(key.as_str());
    for _ in 0..=FRAMES_LIMIT {
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            break;
        }
        let found = channel.read(left.as_secs_f64())?;
        if pyval::is(get(&found, "type"), "client-discovery-request") {
            let mut response = Map::new();
            response.insert(Str::from("canHandle"), Value::Bool(false));
            let mut reply = Map::new();
            reply.insert(Str::from("type"), "client-discovery-response".into());
            reply.insert(Str::from("requestId"), get(&found, "requestId").clone());
            reply.insert(Str::from("response"), Value::Object(response));
            channel.write(&Value::Object(reply))?;
            continue;
        }
        if !pyval::is(get(&found, "type"), "response") || !pyval::eq(get(&found, "requestId"), &key)
        {
            continue;
        }
        if pyval::is(get(&found, "resultType"), "success") {
            return Ok(found);
        }
        let error = get(&found, "error");
        if pyval::is(error, "no-client-found") {
            return Err(Fail::Word(Stop::NoClient));
        }
        if pyval::is(error, "request-version-mismatch") {
            return Err(Fail::Word(Stop::VersionMismatch));
        }
        return Err(Fail::Word(Stop::Refused));
    }
    Err(Fail::Word(Stop::NoAnswer))
}

/// `_stopped(answer, turn_id)`.
pub fn stopped(answer: &Map, turn_id: &Value) -> Stop {
    let named = match get(answer, "result") {
        Value::Object(result) => get(result, "interruptedTurnId").clone(),
        _ => Value::Null,
    };
    let Value::Str(named_text) = &named else {
        return Stop::NotStopped;
    };
    if named_text.is_empty() {
        return Stop::NotStopped;
    }
    if !pyval::truthy(turn_id) || pyval::eq(&named, turn_id) {
        Stop::Stopped
    } else {
        Stop::NotStopped
    }
}

/// `(hello.get("result") or {}).get("clientId")` and the owner after it: the client and the owner, or the word.
fn hello_and_owner(
    channel: &mut Channel,
    thread_id: &Value,
    ids: &mut dyn FnMut() -> String,
) -> Result<Result<(Value, Value), Stop>, Fail> {
    let shape = request_shape("initialize", false).ok_or(Fail::Raised)?;
    let hello = request(
        channel,
        &"initializing-client".into(),
        "initialize",
        shape,
        &[],
        None,
        None,
        None,
        ids,
    )?;
    let result = get(&hello, "result");
    let client = if pyval::truthy(result) {
        match result {
            Value::Object(result) => get(result, "clientId").clone(),
            _ => return Err(Fail::Raised),
        }
    } else {
        Value::Null
    };
    if !matches!(&client, Value::Str(text) if !text.is_empty()) {
        return Ok(Err(Stop::Refused));
    }
    let shape = request_shape("thread-owner-discovery", false).ok_or(Fail::Raised)?;
    let owner = request(
        channel,
        &client,
        "thread-owner-discovery",
        shape,
        &[("thread", thread_id.clone())],
        None,
        None,
        None,
        ids,
    )?;
    let owner = get(&owner, "handledByClientId").clone();
    if !matches!(&owner, Value::Str(text) if !text.is_empty()) {
        return Ok(Err(Stop::NoClient));
    }
    Ok(Ok((client, owner)))
}

fn opened(name: Option<&str>) -> Result<Channel, &'static str> {
    Channel::open(name).map_err(|fail| match fail {
        Fail::Word(word) => word.as_str(),
        Fail::Raised => Stop::Broken.as_str(),
    })
}

fn word_of(done: Result<&'static str, Fail>) -> &'static str {
    match done {
        Ok(word) => word,
        Err(Fail::Word(word)) => word.as_str(),
        Err(Fail::Raised) => Stop::Broken.as_str(),
    }
}

/// `stop_turn(thread_id, turn_id, channel, gate)`: the Stop word of what came of it.
pub fn stop_turn(
    thread_id: &Value,
    turn_id: &Value,
    pipe: Option<&str>,
    gate: Option<&mut dyn Gate>,
    ids: &mut dyn FnMut() -> String,
) -> &'static str {
    let mut channel = match opened(pipe) {
        Ok(channel) => channel,
        Err(word) => return word,
    };
    let done = (|| -> Result<&'static str, Fail> {
        let (client, owner) = match hello_and_owner(&mut channel, thread_id, ids)? {
            Ok(found) => found,
            Err(word) => return Ok(word.as_str()),
        };
        let expecting = pyval::truthy(turn_id);
        let shape =
            request_shape("thread-follower-interrupt-turn", expecting).ok_or(Fail::Raised)?;
        match request(
            &mut channel,
            &client,
            "thread-follower-interrupt-turn",
            shape,
            &[("thread", thread_id.clone()), ("turn", turn_id.clone())],
            Some(&owner),
            Some(INTERRUPT_SECONDS),
            gate,
            ids,
        ) {
            Ok(answer) => Ok(stopped(&answer, turn_id).as_str()),
            Err(Fail::Word(Stop::NoAnswer)) => Ok(Stop::Unconfirmed.as_str()),
            Err(other) => Err(other),
        }
    })();
    channel.close();
    word_of(done)
}

/// `start_turn(thread_id, text, channel, gate)`: STARTED, or the Stop word of what failed.
pub fn start_turn(
    thread_id: &Value,
    text: &Value,
    pipe: Option<&str>,
    gate: Option<&mut dyn Gate>,
    ids: &mut dyn FnMut() -> String,
) -> &'static str {
    let mut channel = match opened(pipe) {
        Ok(channel) => channel,
        Err(word) => return word,
    };
    let done = (|| -> Result<&'static str, Fail> {
        let (client, owner) = match hello_and_owner(&mut channel, thread_id, ids)? {
            Ok(found) => found,
            Err(word) => return Ok(word.as_str()),
        };
        let shape = request_shape("thread-follower-start-turn", false).ok_or(Fail::Raised)?;
        let message = Value::from(ids());
        match request(
            &mut channel,
            &client,
            "thread-follower-start-turn",
            shape,
            &[
                ("thread", thread_id.clone()),
                ("message", message),
                ("text", text.clone()),
            ],
            Some(&owner),
            None,
            gate,
            ids,
        ) {
            Ok(_) => Ok(STARTED),
            Err(Fail::Word(Stop::NoAnswer)) => Ok(Stop::Unconfirmed.as_str()),
            Err(other) => Err(other),
        }
    })();
    channel.close();
    word_of(done)
}

/// `steer_turn(thread_id, text, message, channel, gate)`: STEERED, or the Stop word of what failed; one request
/// written once, UNCONFIRMED where it may have been.
pub fn steer_turn(
    thread_id: &Value,
    text: &Value,
    message: &Value,
    pipe: Option<&str>,
    gate: Option<&mut dyn Gate>,
    ids: &mut dyn FnMut() -> String,
) -> &'static str {
    let mut channel = match opened(pipe) {
        Ok(channel) => channel,
        Err(word) => return word,
    };
    let done = (|| -> Result<&'static str, Fail> {
        let (client, owner) = match hello_and_owner(&mut channel, thread_id, ids)? {
            Ok(found) => found,
            Err(word) => return Ok(word.as_str()),
        };
        let shape = request_shape("thread-follower-steer-turn", false).ok_or(Fail::Raised)?;
        let message = if pyval::truthy(message) {
            message.clone()
        } else {
            Value::from(ids())
        };
        match request(
            &mut channel,
            &client,
            "thread-follower-steer-turn",
            shape,
            &[
                ("thread", thread_id.clone()),
                ("message", message),
                ("text", text.clone()),
            ],
            Some(&owner),
            None,
            gate,
            ids,
        ) {
            Ok(_) => Ok(STEERED),
            Err(Fail::Word(Stop::NoAnswer | Stop::Broken) | Fail::Raised) => {
                Ok(Stop::Unconfirmed.as_str())
            }
            Err(other) => Err(other),
        }
    })();
    channel.close();
    word_of(done)
}

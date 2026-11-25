//! `controlcli.py`: the JSON bridge over the shared control layer - its commands, its framing and its refusals.
//!
//! The standalone window drives the product through this, so it re-implements no validation, defaults or
//! persistence. Two ways to call it, one set of commands:
//!
//! * one command per process: `<command> [json]` writes exactly one JSON object on stdout ([`emit`], with the
//!   argument read by [`argument`] and [`payload`]);
//! * `serve`: one line per request, `{"id": n, "command": "...", "argument": {...}}`, one line per reply,
//!   `{"id": n, "reply": {...}}`, where `reply` is exactly what the one-shot form would have printed ([`serve`]).
//!
//! A rejected request always answers `{"ok": false, "error": "...", "error_code": "..."}`: the English sentence and
//! the stable code, and nothing else - no traceback, no path, no identifier.
//!
//! The wire is UTF-8 and one line per message, written by car-machine's writer exactly as
//! `json.dumps(..., ensure_ascii=False, allow_nan=False)` writes it (D5, D12).

use std::io::{Read, Write};

use car_machine::compat::loads;
use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pytext;

use crate::error::{ControlError, FALLBACK_CODE, Failure, Res, refuse};
use crate::layer::Control;

/// Commands with no argument (`PLAIN`).
pub const PLAIN: &[&str] = &[
    "status",
    "settings",
    "describe",
    "defaults",
    "pending",
    "pending-all",
    "start-watcher",
    "stop-watcher",
    "strings",
    "history",
    "clear-history",
    "dashboard",
    "cancel-all",
    "failure-seen",
    "plugin-copy",
    "state-access",
    "demo",
    "power-action",
    "detection-check",
    "rescan",
    "host-app",
    "home-suggestion",
    "own-report",
];

/// Commands that take one JSON object (`WITH_ARGUMENT`).
pub const WITH_ARGUMENT: &[&str] = &[
    "update",
    "enabled",
    "startup",
    "cancel",
    "reset-budget",
    "retry-now",
    "timeline",
    "statistics",
    "thread-enabled",
    "cancel-thread",
    "diagnostics",
    "preview-continuation",
    "interruption-recovery",
    "compatibility",
    "compat-import",
    "compat-refresh",
    "postpone",
    "release-hold",
    "thread-tier",
    "project-rule",
    "unpostpone",
    "conversation-message",
    "logs",
    "check-setting",
    "power-arm",
    "power-disarm",
    "once-words",
    "home-dismiss",
];

/// Big enough for the largest Save the settings layer accepts (`MAX_LINE`), counted in characters.
pub const MAX_LINE: usize = 1024 * 1024;
/// The one-shot form's argument that means "the JSON argument is on stdin".
pub const STDIN_ARGUMENT: &str = "-";
/// What a rejection says when nothing more precise is known.
pub const GENERIC_ERROR: &str = "the request could not be completed";
/// How many days a statistics request may cover.
pub const DAYS: (i64, i64) = (1, 3650);

/// `_rejected(message, code)`: the only shape a refusal leaves here in.
pub fn rejected(message: impl Into<Str>, code: &str) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("ok"), Value::Bool(false));
    map.insert(Str::from("error"), Value::Str(message.into()));
    map.insert(Str::from("error_code"), Value::from(code));
    Value::Object(map)
}

/// The generic refusal.
pub fn generic() -> Value {
    rejected(GENERIC_ERROR, FALLBACK_CODE)
}

/// `{"ok": true, name: value}`.
pub fn ok_with(name: &str, value: Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("ok"), Value::Bool(true));
    map.insert(Str::from(name), value);
    Value::Object(map)
}

/// Why a line could not be written at all: Python's own exception ended the loop (or the call).
#[derive(Debug, PartialEq, Eq)]
pub enum Fatal {
    /// `json.dumps` succeeded and the stream's strict UTF-8 refused the text (a lone surrogate), or the last
    /// candidate - the caller's plain refusal - could not be written either.
    Unwritable,
}

/// `encode(*candidates)`: the first of `candidates` that can be written as strict JSON, as one line; the last is
/// written unguarded.
pub fn encode(candidates: &[Value]) -> Result<String, Fatal> {
    let options = Options::wire();
    for candidate in &candidates[..candidates.len() - 1] {
        match to_string(candidate, &options) {
            Ok(line) => return Ok(line),
            Err(error) if error.is_unwritable() => continue,
            Err(_) => return Err(Fatal::Unwritable),
        }
    }
    to_string(candidates.last().expect("a last candidate"), &options).map_err(|_| Fatal::Unwritable)
}

/// `_payload(raw)`: only a missing argument means "no argument"; a text is JSON that must be an object.
pub fn payload(raw: &Value) -> Result<Map, ControlError> {
    match raw {
        Value::Null => return Ok(Map::new()),
        Value::Str(text) if text.is_empty() => return Ok(Map::new()),
        Value::Object(map) => return Ok(map.clone()),
        Value::Str(_) => {}
        _ => return Err(ControlError::plain("argument must be a JSON object")),
    }
    let Value::Str(text) = raw else {
        unreachable!()
    };
    let Some(text) = text.as_str() else {
        // A text holding half of a pair is not UTF-8: `json.loads` reads it as the text it is, and it is not JSON.
        return Err(ControlError::plain("argument must be JSON"));
    };
    match loads(text) {
        Ok(Value::Object(map)) => Ok(map),
        Ok(_) => Err(ControlError::plain("argument must be a JSON object")),
        Err(_) => Err(ControlError::plain("argument must be JSON")),
    }
}

/// `_argument(raw, stream)`: the one-shot form's JSON argument, as given or read from `stdin` for `-`.
pub fn argument(raw: &str, stdin: Option<&mut dyn Read>) -> Result<Value, ControlError> {
    if raw != STDIN_ARGUMENT {
        return Ok(Value::from(raw));
    }
    let Some(stream) = stdin else {
        return Ok(Value::from(""));
    };
    let mut bytes = Vec::new();
    if stream.read_to_end(&mut bytes).is_err() {
        return Err(ControlError::plain("argument must be JSON"));
    }
    match String::from_utf8(bytes) {
        // `reconfigure(newline="\n")`: no translation; a leading BOM is a character like another.
        Ok(text) => Ok(Value::from(text)),
        Err(_) => Err(ControlError::plain("argument must be JSON")),
    }
}

/// `statistics_days(payload)`: absent, or a number from 1 to 3650.
pub fn statistics_days(payload: &Map) -> Res<Option<Value>> {
    let days = payload.get("days").unwrap_or(&Value::Null);
    let valid = match days {
        Value::Null => true,
        Value::Int(_) | Value::Float(_) => {
            let number = match days {
                Value::Float(x) => *x,
                Value::Int(int) => int
                    .as_i64()
                    .map(|each| each as f64)
                    .unwrap_or_else(|| int.to_string().parse().unwrap_or(f64::INFINITY)),
                _ => f64::NAN,
            };
            (DAYS.0 as f64) <= number && number <= (DAYS.1 as f64)
        }
        _ => false,
    };
    if !valid {
        return refuse(
            format!("days must be a number from {} to {}", DAYS.0, DAYS.1),
            FALLBACK_CODE,
        );
    }
    Ok(match days {
        Value::Null => None,
        other => Some(other.clone()),
    })
}

/// `_flag(payload)`: the `enabled` field of a switch request - a real boolean, or a refusal.
pub fn flag(payload: &Map) -> Res<bool> {
    match payload.get("enabled") {
        Some(Value::Bool(on)) => Ok(*on),
        _ => refuse("enabled must be true or false", "invalid_enabled"),
    }
}

/// `_boolean(payload, name)`: an optional flag - absent is False, a real boolean is itself, anything else refused.
pub fn boolean(payload: &Map, name: &str) -> Res<bool> {
    match payload.get(name) {
        None => Ok(false),
        Some(Value::Bool(on)) => Ok(*on),
        Some(_) => refuse(format!("{name} must be true or false"), FALLBACK_CODE),
    }
}

/// `dispatch(control, command, payload)`: one command, one reply. The whole typed surface of the bridge.
pub fn dispatch(control: &Control, command: &str, payload: &Map) -> Value {
    match crate::commands::run(control, command, payload) {
        Ok(Some(reply)) => reply,
        Ok(None) => rejected("unknown command", FALLBACK_CODE),
        Err(Failure::Control(error)) => rejected(error.message, &error.code),
        Err(Failure::Other(_)) => generic(),
    }
}

/// `_plugged(control, command, argument)`: a command the bridge has none of its own for, put to the edition's
/// plug (P10). Refused, as every unknown command always was, unless the plug answers it with a JSON object.
fn plugged(control: &Control, command: &Value, argument: &Value) -> Result<Value, ControlError> {
    if !control.plug().is_null()
        && let Value::Str(name) = command
    {
        let facts = payload(argument).ok().map(|body| {
            let mut asked = Map::new();
            asked.insert(Str::from("command"), Value::Str(name.clone()));
            asked.insert(Str::from("argument"), Value::Object(body));
            Value::Object(asked)
        });
        if let Some(facts) = facts
            && let car_policy::plug::Answer::Is(added) = control
                .plug()
                .surface(car_policy::plug::Surface::Bridge, &facts)
        {
            return Ok(ok_with("result", added));
        }
    }
    Err(ControlError::plain("unknown command"))
}

/// One request line, answered: the id to echo and the reply.
fn answer(control: &Control, line: &str) -> (Value, Value) {
    if line.chars().count() > MAX_LINE {
        return (
            Value::Null,
            refused(&ControlError::plain("request too large")),
        );
    }
    let request = match loads(line) {
        Ok(request) => request,
        Err(_) => return (Value::Null, rejected("request must be JSON", FALLBACK_CODE)),
    };
    let Value::Object(request) = request else {
        return (
            Value::Null,
            refused(&ControlError::plain("request must be a JSON object")),
        );
    };
    let id = request.get("id").cloned().unwrap_or(Value::Null);
    let whole = matches!(&id, Value::Null) || matches!(&id, Value::Int(_));
    if !whole {
        return (id, refused(&ControlError::plain("id must be an integer")));
    }
    let command = request.get("command").cloned().unwrap_or(Value::Null);
    let argument = request.get("argument").cloned().unwrap_or(Value::Null);
    let known = match &command {
        Value::Str(name) => name
            .as_str()
            .filter(|each| PLAIN.contains(each) || WITH_ARGUMENT.contains(each)),
        _ => None,
    };
    // `serve`'s `except Exception`: whatever a command raises is the generic refusal, the id still echoed.
    let reply = unwound(|| match known {
        Some(name) => match payload(&argument) {
            Ok(body) => dispatch(control, name, &body),
            Err(error) => refused(&error),
        },
        None => match plugged(control, &command, &argument) {
            Ok(reply) => reply,
            Err(error) => refused(&error),
        },
    });
    (id, reply)
}

/// D15's boundary for the bridge: Python's `except Exception` around a command (`dispatch`, :550-553, and `serve`,
/// :607-611) is, for a panic, an unwind caught here. A panic is the generic refusal, as any exception the reference
/// does not name is, and the caller goes on to read the next line (or to exit as the refusal does).
fn unwound(work: impl FnOnce() -> Value) -> Value {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(work)) {
        Ok(reply) => reply,
        Err(_) => generic(),
    }
}

fn refused(error: &ControlError) -> Value {
    rejected(error.message.clone(), &error.code)
}

fn envelope(id: &Value, reply: &Value) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("id"), id.clone());
    map.insert(Str::from("reply"), reply.clone());
    Value::Object(map)
}

/// What `serve` ended with: the code the process exits with.
pub const SERVED: i32 = 0;
/// A stream that could not be decoded or a line that could not be written ends Python's loop with a traceback.
pub const CRASHED: i32 = 1;

/// `serve(control, stream_in, stream_out)`: answer requests, one line each, until the input closes. A request that
/// cannot be parsed still gets exactly one reply line.
///
/// The input is read as Python's text stream reads it: UTF-8, strict, in chunks of 8192 bytes, lines ending at
/// `\n` only. Bytes that are not UTF-8 raise inside the `for` loop, outside its `try`: the lines before the chunk
/// that held them are answered, and the loop ends.
pub fn serve(control: &Control, input: &mut dyn Read, output: &mut dyn Write) -> i32 {
    const CHUNK: usize = 8192;
    let mut pending: Vec<u8> = Vec::new();
    let mut buffer = vec![0u8; CHUNK];
    let mut text = String::new();
    loop {
        let read = match input.read(&mut buffer) {
            Ok(read) => read,
            Err(_) => return CRASHED,
        };
        let end = read == 0;
        pending.extend_from_slice(&buffer[..read]);
        // The incremental decoder: a sequence cut by the chunk waits for the next one.
        let (valid, rest) = match std::str::from_utf8(&pending) {
            Ok(all) => (all.len(), 0),
            Err(error) => {
                if error.error_len().is_some() || end {
                    return CRASHED;
                }
                (error.valid_up_to(), pending.len() - error.valid_up_to())
            }
        };
        text.push_str(std::str::from_utf8(&pending[..valid]).unwrap_or_default());
        pending.drain(..valid);
        debug_assert_eq!(pending.len(), rest);
        while let Some(at) = text.find('\n') {
            let line: String = text.drain(..=at).collect();
            if !line_done(control, &line, output) {
                return CRASHED;
            }
        }
        if end {
            if !text.is_empty() {
                let line = std::mem::take(&mut text);
                if !line_done(control, &line, output) {
                    return CRASHED;
                }
            }
            return SERVED;
        }
    }
}

/// One line of the stream, answered and written. False where Python's loop would have died.
fn line_done(control: &Control, raw: &str, output: &mut dyn Write) -> bool {
    let line = pytext::strip(raw.trim_start_matches('\u{feff}'));
    if line.is_empty() {
        return true;
    }
    // Before the id is known (the reading of the line itself) a panic is the generic refusal with a null id.
    let (id, reply) =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| answer(control, line)))
            .unwrap_or_else(|_| (Value::Null, generic()));
    let line = match encode(&[
        envelope(&id, &reply),
        envelope(&id, &generic()),
        envelope(&Value::Null, &reply),
        envelope(&Value::Null, &generic()),
    ]) {
        Ok(line) => line,
        Err(_) => return false,
    };
    output
        .write_all(line.as_bytes())
        .and_then(|_| output.write_all(b"\n"))
        .and_then(|_| output.flush())
        .is_ok()
}

/// `_emit(payload)`: the one-shot form's only way out - one reply object as one line, and the exit code.
pub fn emit(reply: Value, output: &mut dyn Write) -> i32 {
    let options = Options::wire();
    let (line, reply) = match to_string(&reply, &options) {
        Ok(line) => (line, reply),
        Err(error) if error.is_unwritable() => {
            let refusal = generic();
            match to_string(&refusal, &options) {
                Ok(line) => (line, refusal),
                Err(_) => return CRASHED,
            }
        }
        Err(_) => return CRASHED,
    };
    if output
        .write_all(line.as_bytes())
        .and_then(|_| output.write_all(b"\n"))
        .is_err()
    {
        return CRASHED;
    }
    match &reply {
        Value::Object(map) => match map.get("ok") {
            None => 0,
            Some(other) => i32::from(!car_machine::pyval::truthy(other)),
        },
        _ => 0,
    }
}

/// `main(argv)` without argparse: the one-shot form over the arguments after `--home`. `argv` is the command, then
/// its JSON argument (or `-`) if it takes one, and for `compat-import` the bootstrap's `--file` and `--origin`.
/// Choosing a command and refusing a malformed command line is the entry point's (car-bin).
pub fn one_shot(
    control: &Control,
    argv: &[String],
    stdin: &mut dyn Read,
    output: &mut dyn Write,
) -> i32 {
    let Some(command) = argv.first() else {
        return 2;
    };
    let mut json = String::new();
    let (mut file, mut origin) = (None, None);
    let mut rest = argv[1..].iter();
    while let Some(word) = rest.next() {
        match word.as_str() {
            "--file" => file = rest.next().cloned(),
            "--origin" => origin = rest.next().cloned(),
            _ => json = word.clone(),
        }
    }
    // `dispatch`'s `except Exception` answers a panic with the generic refusal, and `_emit` gives it exit 1.
    let reply = unwound(
        || match argument(&json, Some(stdin)).and_then(|raw| payload(&raw)) {
            Ok(mut body) => {
                if command == "compat-import"
                    && let Some(path) = file.filter(|each| !each.is_empty())
                {
                    body.insert(Str::from("path"), Value::from(path));
                    if let Some(origin) = origin.filter(|each| !each.is_empty()) {
                        body.insert(Str::from("origin"), Value::from(origin));
                    }
                }
                dispatch(control, command, &body)
            }
            Err(error) => refused(&error),
        },
    );
    emit(reply, output)
}

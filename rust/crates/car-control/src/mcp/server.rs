//! `mcp/server.py`: an MCP server so the product can be managed from inside Codex - the JSON-RPC loop and every
//! tool's body.
//!
//! A typed front end: every tool calls the same validated control layer the command line, the skill and the
//! settings window call. Not a second recovery engine, scheduler or database: no tool detects, schedules, reserves
//! or sends, and nothing here writes SQL. It starts nothing but what `start_watcher` asks for (the control layer's
//! own start), and the start with Codex is the entry point's (car-bin), beside the handshake.
//!
//! Transport is newline-delimited JSON-RPC on stdin/stdout, read as the reference reads its stdin on Windows:
//! UTF-8, strict, in chunks of 8192 bytes, universal newlines (`\r\n` and a lone `\r` end a line as `\n` does).
//! Nothing but protocol messages reaches the output.

use std::io::{Read, Write};

use car_machine::compat::{LoadsError, loads};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext;
use car_policy::classify::reasons::RECOVERABLE;
use car_policy::plug::{Answer, Surface};
use car_policy::settings::DASHBOARD_ONLY;

use crate::bridge::{GENERIC_ERROR, encode, statistics_days};
use crate::error::{ControlError, FALLBACK_CODE, Failure};
use crate::layer::Control;

use super::tools::{
    PANEL_DISPLAY_MODES, PANEL_PREFERRED_MODE, SETTINGS_UI, object, plugged_tools, resources,
    settings_schema, tools,
};

/// `PROTOCOL_VERSION`.
pub const PROTOCOL_VERSION: &str = "2025-06-18";
/// `SUPPORTED_PROTOCOLS`.
pub const SUPPORTED_PROTOCOLS: &[&str] = &[PROTOCOL_VERSION, "2025-03-26", "2024-11-05"];
/// `SERVER_NAME`.
pub const SERVER_NAME: &str = "codex-auto-resume";
/// `STARTER_GRACE_SECONDS`: how long a finished server waits for its start-with-Codex launch, and never more.
pub const STARTER_GRACE_SECONDS: f64 = 3.0;

pub const PARSE_ERROR: i64 = -32700;
pub const INVALID_REQUEST: i64 = -32600;
pub const METHOD_NOT_FOUND: i64 = -32601;
pub const INVALID_PARAMS: i64 = -32602;
pub const INTERNAL_ERROR: i64 = -32603;

/// `PATH_SETTINGS`: settings that hold a path a person chose, said only as whether one is set.
pub const PATH_SETTINGS: &[&str] = &["codex_exe"];

/// The deepest batch the reference's `_dispatch` takes before Python's RecursionError ends the loop (measured on the
/// v0.6.26 final's Python as `codex-auto-resume.exe mcp` runs it: `tests/rustdiff/diffs_mcp.py` `EdgesDiff`).
pub const BATCH_DEPTH_LIMIT: usize = 995;

/// What `serve` ended with: 0 when the input closed; 1 where the reference's loop dies with a traceback.
pub const SERVED: i32 = 0;
pub const CRASHED: i32 = 1;

const INSTRUCTIONS: &str = "Manage Codex Auto Resume, which recovers the exact Codex task an interruption stopped. Use open_settings when the user wants to see or change how it behaves. Identify a pending recovery only by the exact interruption id from list_pending; never by title, project or recency. There is no way to retry an unclassified failure or to force a send, and asking for one is not an oversight to work around.";

/// `START_WORDING`.
fn start_wording(state: Option<&str>) -> &'static str {
    match state {
        Some("running") => "The watcher is running.",
        Some("already-running") => "It was already running; nothing to do.",
        Some("exited") => {
            "The watcher was started but stopped again straight away. The logs directory in the installation says why; nothing is watching right now."
        }
        _ => {
            "Watcher launch requested, but its running state could not be confirmed. Ask for the status again in a moment."
        }
    }
}

/// `ENDS_WITH_CODEX[ends]`, for True and None.
fn ends_with_codex(ends: Option<bool>) -> &'static str {
    if ends == Some(true) {
        "It was started from inside Codex, which ends what its plugins start, so it stops when Codex closes, if not sooner. Once Codex has closed, open Codex Auto Resume from the Start menu and start it there, or turn on Run at Windows sign-in in the Dashboard so it starts with Windows."
    } else {
        "It was started from inside Codex, and Windows would not say whether Codex ends what its plugins start, so it may stop when Codex closes. If it does, open Codex Auto Resume from the Start menu and start it there, or turn on Run at Windows sign-in in the Dashboard so it starts with Windows."
    }
}

/// Why a request was not answered with a result: the reference's three ways out of `handle`'s `try`.
enum Raised {
    /// `ControlError`: a refused call, a tool-level failure.
    Control(ControlError),
    /// `UnknownName`: a tool or resource this server does not have.
    UnknownName(&'static str),
    /// Any other exception: an internal error whose text never goes out.
    Other,
}

impl From<Failure> for Raised {
    fn from(failure: Failure) -> Raised {
        match failure {
            Failure::Control(error) => Raised::Control(error),
            Failure::Other(_) => Raised::Other,
        }
    }
}

impl From<ControlError> for Raised {
    fn from(error: ControlError) -> Raised {
        Raised::Control(error)
    }
}

type Out<T> = Result<T, Raised>;

fn refuse<T>(message: impl Into<Str>) -> Out<T> {
    Err(Raised::Control(ControlError::new(message, FALLBACK_CODE)))
}

fn error(id: &Value, code: i64, message: impl Into<Str>) -> Value {
    object([
        ("jsonrpc", Value::from("2.0")),
        ("id", id.clone()),
        (
            "error",
            object([
                ("code", Value::from(code)),
                ("message", Value::Str(message.into())),
            ]),
        ),
    ])
}

fn result(id: &Value, result: Value) -> Value {
    object([
        ("jsonrpc", Value::from("2.0")),
        ("id", id.clone()),
        ("result", result),
    ])
}

/// `_failure(message, code)`: a refused call - the sentence a reader gets, and the same refusal as a value.
fn failure(message: Str, code: &str) -> Value {
    object([
        ("isError", Value::Bool(true)),
        (
            "content",
            Value::Array(vec![object([
                ("type", Value::from("text")),
                ("text", Value::Str(message)),
            ])]),
        ),
        (
            "structuredContent",
            object([("error_code", Value::from(code))]),
        ),
    ])
}

/// `_no_homes(value)`: the Codex homes taken out of every settings mapping in it, and a path setting said as `<set>`.
pub fn no_homes(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = Map::new();
            for (key, item) in map {
                let name = key.as_str();
                if name.is_some_and(|each| DASHBOARD_ONLY.contains(&each)) {
                    continue;
                }
                let kept = if name.is_some_and(|each| PATH_SETTINGS.contains(&each)) {
                    if car_machine::pyval::truthy(item) {
                        Value::from("<set>")
                    } else {
                        Value::Null
                    }
                } else {
                    no_homes(item)
                };
                out.insert(key.clone(), kept);
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(items.iter().map(no_homes).collect()),
        other => other.clone(),
    }
}

/// `_reply(summary, data, meta=None)`.
fn reply(summary: impl Into<Str>, data: &Value, meta: Option<Value>) -> Value {
    let mut map = Map::new();
    map.insert(
        Str::from("content"),
        Value::Array(vec![object([
            ("type", Value::from("text")),
            ("text", Value::Str(summary.into())),
        ])]),
    );
    map.insert(Str::from("structuredContent"), no_homes(data));
    if let Some(meta) = meta {
        map.insert(Str::from("_meta"), meta);
    }
    Value::Object(map)
}

fn field<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(name),
        _ => None,
    }
}

fn arg(arguments: &Map, name: &str) -> Value {
    arguments.get(name).cloned().unwrap_or(Value::Null)
}

/// `"%d" % value`, as a reply's count says it.
fn count(value: Option<&Value>) -> Out<String> {
    match value {
        Some(Value::Int(int)) => Ok(int.to_string()),
        Some(Value::Bool(on)) => Ok(i64::from(*on).to_string()),
        Some(Value::Float(x)) if x.is_finite() => Ok(format!("{}", x.trunc() as i128)),
        _ => Err(Raised::Other),
    }
}

/// `str(value)` of a reply's text field.
fn text(value: Option<&Value>) -> Out<String> {
    match value {
        Some(Value::Str(text)) => Ok(text
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| String::from_utf8_lossy(text.as_bytes()).into_owned())),
        Some(_) | None => Err(Raised::Other),
    }
}

/// `s[:1].upper() + s[1:]`.
fn capitalised(sentence: &str) -> String {
    let mut characters = sentence.chars();
    match characters.next() {
        Some(first) => first.to_uppercase().chain(characters).collect(),
        None => String::new(),
    }
}

/// `{True: a, False: b}.get(value, c)`: a bool, or 1 and 0 as Python's hashing makes them the same keys.
fn running_word(
    value: Option<&Value>,
    yes: &'static str,
    no: &'static str,
    neither: &'static str,
) -> &'static str {
    match value {
        Some(Value::Bool(true)) => yes,
        Some(Value::Bool(false)) => no,
        Some(Value::Int(int)) if int.as_i64() == Some(1) => yes,
        Some(Value::Int(int)) if int.as_i64() == Some(0) => no,
        Some(Value::Float(x)) if *x == 1.0 => yes,
        Some(Value::Float(x)) if *x == 0.0 => no,
        _ => neither,
    }
}

/// One connection. Synchronous by design: the control layer is not concurrent.
pub struct Server<'a> {
    control: &'a Control,
    pub initialized: bool,
}

impl<'a> Server<'a> {
    pub fn new(control: &'a Control) -> Server<'a> {
        Server {
            control,
            initialized: false,
        }
    }

    // ------------------------------------------------------------------ transport
    /// `serve()`: answer requests until the input closes. 0, or [`CRASHED`] where the reference's loop dies.
    pub fn serve(&mut self, input: &mut dyn Read, output: &mut dyn Write) -> i32 {
        const CHUNK: usize = 8192;
        let mut pending: Vec<u8> = Vec::new();
        let mut buffer = vec![0u8; CHUNK];
        let mut text = String::new();
        // The newline decoder's `pendingcr`: a `\r` at the end of what was decoded waits for the next character.
        let mut carriage = false;
        loop {
            let read = match input.read(&mut buffer) {
                Ok(read) => read,
                Err(_) => return CRASHED,
            };
            let end = read == 0;
            pending.extend_from_slice(&buffer[..read]);
            let valid = match std::str::from_utf8(&pending) {
                Ok(all) => all.len(),
                Err(error) => {
                    if error.error_len().is_some() || end {
                        return CRASHED;
                    }
                    error.valid_up_to()
                }
            };
            let decoded = std::str::from_utf8(&pending[..valid])
                .unwrap_or_default()
                .to_owned();
            pending.drain(..valid);
            let mut piece = String::with_capacity(decoded.len() + 1);
            if carriage {
                piece.push('\r');
                carriage = false;
            }
            piece.push_str(&decoded);
            if !end && piece.ends_with('\r') {
                piece.pop();
                carriage = true;
            }
            text.push_str(&piece.replace("\r\n", "\n").replace('\r', "\n"));
            while let Some(at) = text.find('\n') {
                let line: String = text.drain(..=at).collect();
                if !self.line_done(&line, output) {
                    return CRASHED;
                }
            }
            if end {
                if !text.is_empty() {
                    let line = std::mem::take(&mut text);
                    if !self.line_done(&line, output) {
                        return CRASHED;
                    }
                }
                return SERVED;
            }
        }
    }

    /// One line: parsed, dispatched, every response written. False where the reference's loop dies.
    fn line_done(&mut self, raw: &str, output: &mut dyn Write) -> bool {
        let line = pytext::strip(raw.trim_start_matches('\u{feff}'));
        if line.is_empty() {
            return true;
        }
        let message = match loads(line) {
            Ok(message) => message,
            Err(LoadsError::Recursion) => return false,
            Err(_) => return write(&error(&Value::Null, PARSE_ERROR, "invalid JSON"), output),
        };
        self.dispatch(&message, 0, output)
    }

    /// `_dispatch(message)`: a batch is a list, a message an object; a notification gets nothing. Each response is
    /// written as it is made, as the reference's generator hands them out.
    fn dispatch(&mut self, message: &Value, depth: usize, output: &mut dyn Write) -> bool {
        if depth >= BATCH_DEPTH_LIMIT {
            return false;
        }
        match message {
            Value::Array(items) => {
                for item in items {
                    if !self.dispatch(item, depth + 1, output) {
                        return false;
                    }
                }
                true
            }
            Value::Object(map) => {
                let response =
                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.handle(map)))
                        .unwrap_or_else(|_| {
                            let id = map.get("id").cloned().unwrap_or(Value::Null);
                            Some(error(&id, INTERNAL_ERROR, GENERIC_ERROR))
                        });
                match response {
                    Some(response) => write(&response, output),
                    None => true,
                }
            }
            _ => write(
                &error(&Value::Null, INVALID_REQUEST, "message must be an object"),
                output,
            ),
        }
    }

    // ------------------------------------------------------------------- protocol
    /// `handle(message)`: one request's response, or None for a notification.
    pub fn handle(&mut self, message: &Map) -> Option<Value> {
        let method = message.get("method");
        let request_id = message.get("id").cloned().unwrap_or(Value::Null);
        let valid_id = match &request_id {
            Value::Null | Value::Str(_) | Value::Int(_) => true,
            Value::Float(x) => x.is_finite(),
            _ => false,
        };
        let is_text = matches!(method, Some(Value::Str(_)));
        if message.get("jsonrpc") != Some(&Value::from("2.0")) || !is_text || !valid_id {
            let id = if valid_id {
                request_id.clone()
            } else {
                Value::Null
            };
            return Some(error(&id, INVALID_REQUEST, "invalid JSON-RPC request"));
        }
        if !message.contains_key("id") {
            return None;
        }
        let Some(Value::Str(method)) = method else {
            return None;
        };
        let empty = Value::Object(Map::new());
        let params = message.get("params").unwrap_or(&empty);
        let Value::Object(params) = params else {
            return Some(error(
                &request_id,
                INVALID_PARAMS,
                "params must be an object",
            ));
        };
        let answered: Out<Option<Value>> = match method.as_str() {
            Some("initialize") => Ok(Some(self.initialize(params))),
            Some("ping") => Ok(Some(Value::Object(Map::new()))),
            Some("tools/list") => self.plugged().map(|plugged| {
                let mut listed = tools();
                listed.extend(plugged);
                Some(object([("tools", Value::Array(listed))]))
            }),
            Some("resources/list") => Ok(Some(object([("resources", Value::Array(resources()))]))),
            Some("resources/templates/list") => Ok(Some(object([(
                "resourceTemplates",
                Value::Array(Vec::new()),
            )]))),
            Some("prompts/list") => Ok(Some(object([("prompts", Value::Array(Vec::new()))]))),
            Some("resources/read") => self.read_resource(params).map(Some),
            Some("tools/call") => self.call_tool(params).map(Some),
            _ => Ok(None),
        };
        Some(match answered {
            Ok(Some(value)) => result(&request_id, value),
            Ok(None) => {
                let mut message = b"unknown method: ".to_vec();
                message.extend_from_slice(method.as_bytes());
                let said = Str::from_surrogatepass(message)
                    .unwrap_or_else(|| Str::from("unknown method: "));
                error(&request_id, METHOD_NOT_FOUND, said)
            }
            Err(Raised::Control(refused)) => {
                result(&request_id, failure(refused.message, &refused.code))
            }
            Err(Raised::UnknownName(what)) => error(&request_id, INVALID_PARAMS, what),
            Err(Raised::Other) => error(&request_id, INTERNAL_ERROR, GENERIC_ERROR),
        })
    }

    fn initialize(&mut self, params: &Map) -> Value {
        self.initialized = true;
        let version = match params.get("protocolVersion") {
            Some(Value::Str(asked))
                if asked
                    .as_str()
                    .is_some_and(|each| SUPPORTED_PROTOCOLS.contains(&each)) =>
            {
                Value::Str(asked.clone())
            }
            _ => Value::from(PROTOCOL_VERSION),
        };
        object([
            ("protocolVersion", version),
            (
                "capabilities",
                object([
                    ("tools", object([("listChanged", Value::Bool(false))])),
                    (
                        "resources",
                        object([
                            ("subscribe", Value::Bool(false)),
                            ("listChanged", Value::Bool(false)),
                        ]),
                    ),
                ]),
            ),
            (
                "serverInfo",
                object([
                    ("name", Value::from(SERVER_NAME)),
                    ("version", Value::from(self.version())),
                ]),
            ),
            ("instructions", Value::from(INSTRUCTIONS)),
        ])
    }

    /// `_version()`: `str(get_status().get("version") or "unknown")`, "unknown" for anything raised.
    fn version(&self) -> String {
        match self.control.get_status() {
            Ok(status) => match field(&status, "version") {
                Some(value) if car_machine::pyval::truthy(value) => pytext::py_str(value),
                _ => "unknown".to_owned(),
            },
            Err(_) => "unknown".to_owned(),
        }
    }

    fn set_language(&self, settings: &Map) {
        let host = std::sync::Arc::clone(&self.control.host);
        let environ = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        let chosen = match settings.get("interface_language") {
            Some(Value::Str(text)) => text.as_str().map(str::to_owned),
            _ => None,
        };
        car_words::l10n::set_preference(chosen.as_deref(), &environ, &windows);
    }

    fn read_resource(&self, params: &Map) -> Out<Value> {
        if params.get("uri") != Some(&Value::from(SETTINGS_UI)) {
            return Err(Raised::UnknownName("unknown resource"));
        }
        let settings = self.control.get_settings()?;
        self.set_language(&settings);
        let host = std::sync::Arc::clone(&self.control.host);
        let day = super::panel::day_look_at(&*host, host.now());
        let page = super::panel::settings_page(
            &*host,
            &super::panel::Page {
                day,
                ..Default::default()
            },
        )
        .map_err(|_| Raised::Other)?;
        Ok(object([(
            "contents",
            Value::Array(vec![object([
                ("uri", Value::from(SETTINGS_UI)),
                ("mimeType", Value::from("text/html+skybridge")),
                ("text", Value::from(page)),
                (
                    "_meta",
                    object([(
                        "openai/ui",
                        object([
                            (
                                "availableDisplayModes",
                                Value::Array(
                                    PANEL_DISPLAY_MODES
                                        .iter()
                                        .map(|m| Value::from(*m))
                                        .collect(),
                                ),
                            ),
                            ("preferredDisplayMode", Value::from(PANEL_PREFERRED_MODE)),
                        ]),
                    )]),
                ),
            ])]),
        )]))
    }

    // ---------------------------------------------------------------------- tools
    fn call_tool(&self, params: &Map) -> Out<Value> {
        let name = params.get("name");
        let empty = Value::Object(Map::new());
        let arguments = params.get("arguments").unwrap_or(&empty);
        let Value::Object(arguments) = arguments else {
            return refuse("arguments must be an object");
        };
        let core = tools();
        let wanted = |tool: &&Value| match (field(tool, "name"), name) {
            (Some(a), Some(b)) => a == b,
            _ => false,
        };
        let mut plugged = false;
        let tool = match core.iter().find(wanted) {
            Some(tool) => tool.clone(),
            None => {
                let offered = self.plugged()?;
                match offered.iter().find(wanted) {
                    Some(tool) => {
                        plugged = true;
                        tool.clone()
                    }
                    None => return Err(Raised::UnknownName("unknown tool")),
                }
            }
        };
        let schema = field(&tool, "inputSchema");
        let Some(Value::Object(offered)) = schema.and_then(|schema| field(schema, "properties"))
        else {
            return Err(Raised::Other);
        };
        if arguments.keys().any(|key| !offered.contains_key(key)) {
            return refuse("unrecognized tool arguments");
        }
        if let Some(required) = schema.and_then(|schema| field(schema, "required")) {
            let Value::Array(required) = required else {
                return Err(Raised::Other);
            };
            for key in required {
                let Value::Str(key) = key else {
                    return Err(Raised::Other);
                };
                if !arguments.contains_key(key) {
                    return refuse("missing required tool arguments");
                }
            }
        }
        if let Some(flag) = arguments.get("include_finished")
            && !matches!(flag, Value::Bool(_))
        {
            return refuse("include_finished must be true or false");
        }
        let name = match name {
            Some(Value::Str(name)) => name.as_str().unwrap_or_default().to_owned(),
            _ => return Err(Raised::Other),
        };
        if plugged {
            return self.plugged_call(&name, arguments);
        }
        self.tool(&name, arguments)
    }

    /// `_plugged_tools()`: the edition's plug's tools after core's; none in the standard edition.
    fn plugged(&self) -> Out<Vec<Value>> {
        let plug = self.control.plug();
        if plug.is_null() {
            return Ok(Vec::new());
        }
        let facts = object([("request", Value::from("tools"))]);
        Ok(match plug.surface(Surface::Mcp, &facts) {
            Answer::Is(added) => plugged_tools(field(&added, "tools")),
            _ => plugged_tools(None),
        })
    }

    /// `_plugged_call(name, arguments)`: a call to one of the plug's own tools, answered by the plug alone.
    fn plugged_call(&self, name: &str, arguments: &Map) -> Out<Value> {
        let facts = object([
            ("request", Value::from("call")),
            ("tool", Value::from(name)),
            ("arguments", Value::Object(arguments.clone())),
        ]);
        if let Answer::Is(answer) = self.control.plug().surface(Surface::Mcp, &facts) {
            let refused = field(&answer, "refused");
            if let Some(Value::Str(refused)) = refused
                && !pytext::strip(&String::from_utf8_lossy(refused.as_bytes())).is_empty()
            {
                let points: Vec<u32> = refused.code_points().take(300).collect();
                return refuse(Str::from_code_points(points).unwrap_or_default());
            }
            if let (Some(Value::Str(summary)), Some(data @ Value::Object(_))) =
                (field(&answer, "summary"), field(&answer, "data"))
            {
                let points: Vec<u32> = summary.code_points().take(500).collect();
                return Ok(reply(
                    Str::from_code_points(points).unwrap_or_default(),
                    data,
                    None,
                ));
            }
        }
        refuse(GENERIC_ERROR)
    }

    /// `_status()`: the shared status, with the Compatibility Registry's summary under `watcher`.
    fn status(&self) -> Out<Value> {
        let status = self.control.get_status()?;
        let empty = Map::new();
        let settings = match field(&status, "settings") {
            Some(Value::Object(map)) => map,
            _ => &empty,
        };
        let host = std::sync::Arc::clone(&self.control.host);
        let view = host.compat_view(&self.control.state_dir(), settings);
        let summary = super::seam::mcp_view(&view).ok();
        let Value::Object(mut status) = status else {
            return Ok(status);
        };
        if let (Some(Value::Object(watcher)), Some(summary)) = (status.get("watcher"), summary) {
            let mut watcher = watcher.clone();
            watcher.insert(Str::from("compatibility"), summary);
            status.insert(Str::from("watcher"), Value::Object(watcher));
        }
        Ok(Value::Object(status))
    }

    /// `_snapshot()`: everything the settings panel needs, in one read.
    fn snapshot(&self) -> Out<Value> {
        let settings = self.control.get_settings()?;
        self.set_language(&settings);
        let status = self.status()?;
        let schema = Value::Array(self.control.describe_settings());
        let pending = Value::Array(self.control.list_pending(false, None)?);
        let host = std::sync::Arc::clone(&self.control.host);
        let environ = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        let mut endonyms = Map::new();
        for (locale, name) in car_words::l10n::offered_endonyms() {
            endonyms.insert(Str::from(locale), Value::from(name));
        }
        Ok(object([
            ("status", status),
            ("schema", schema),
            ("settings", Value::Object(settings)),
            ("pending", pending),
            (
                "reasons",
                Value::Array(RECOVERABLE.iter().map(|each| Value::from(*each)).collect()),
            ),
            ("endonyms", Value::Object(endonyms)),
            (
                "system_language",
                Value::from(car_words::l10n::from_system(&environ, &windows)),
            ),
        ]))
    }

    fn tool(&self, name: &str, arguments: &Map) -> Out<Value> {
        let control = self.control;
        let id = || arg(arguments, "interruption_id");
        let thread = || arg(arguments, "thread_id");
        match name {
            "open_settings" => {
                let data = self.snapshot()?;
                let status = field(&data, "status").cloned().unwrap_or(Value::Null);
                let summary = format!(
                    "Auto recovery is {}; the watcher is {}; {} pending.",
                    if field(&status, "enabled").is_some_and(car_machine::pyval::truthy) {
                        "on"
                    } else {
                        "paused"
                    },
                    running_word(
                        field(&status, "watcher_running"),
                        "running",
                        "not running",
                        "in an unknown state"
                    ),
                    count(field(&status, "pending"))?
                );
                Ok(reply(
                    summary,
                    &data,
                    Some(object([(
                        "openai/outputTemplate",
                        Value::from(SETTINGS_UI),
                    )])),
                ))
            }
            "get_status" => {
                let status = self.status()?;
                let summary = format!(
                    "Auto recovery {}, watcher {}, {} pending, version {}.",
                    if field(&status, "enabled").is_some_and(car_machine::pyval::truthy) {
                        "enabled"
                    } else {
                        "paused"
                    },
                    running_word(
                        field(&status, "watcher_running"),
                        "running",
                        "not running",
                        "unknown"
                    ),
                    count(field(&status, "pending"))?,
                    match field(&status, "version") {
                        Some(value) => pytext::py_str(value),
                        None => return Err(Raised::Other),
                    }
                );
                Ok(reply(summary, &status, None))
            }
            "list_pending" => {
                let include = arguments
                    .get("include_finished")
                    .is_some_and(car_machine::pyval::truthy);
                let rows = control.list_pending(include, None)?;
                let summary = format!(
                    "{} recover{} listed.",
                    rows.len(),
                    if rows.len() == 1 { "y" } else { "ies" }
                );
                Ok(reply(
                    summary,
                    &object([("pending", Value::Array(rows))]),
                    None,
                ))
            }
            "update_settings" => {
                if arguments.is_empty() {
                    return refuse("name at least one setting to change");
                }
                let mut named: Vec<&Str> = arguments.keys().collect();
                named.sort_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
                let dashboard: Vec<String> = named
                    .iter()
                    .filter(|key| {
                        key.as_str()
                            .is_some_and(|each| DASHBOARD_ONLY.contains(&each))
                    })
                    .map(|key| key.as_str().unwrap_or_default().to_owned())
                    .collect();
                if !dashboard.is_empty() {
                    return refuse(format!(
                        "not changeable from Codex: {}",
                        dashboard.join(", ")
                    ));
                }
                let schema = settings_schema();
                let Some(Value::Object(offered)) = field(&schema, "properties") else {
                    return Err(Raised::Other);
                };
                let refused: Vec<Str> = named
                    .iter()
                    .filter(|key| !offered.contains_key(**key))
                    .map(|key| (*key).clone())
                    .collect();
                if !refused.is_empty() {
                    let mut said = b"not changeable from Codex: ".to_vec();
                    for (index, key) in refused.iter().enumerate() {
                        if index > 0 {
                            said.extend_from_slice(b", ");
                        }
                        said.extend_from_slice(key.as_bytes());
                    }
                    return refuse(Str::from_surrogatepass(said).unwrap_or_default());
                }
                let values = control.update_settings(&Value::Object(arguments.clone()))?;
                let mut said = b"Updated ".to_vec();
                for (index, key) in named.iter().enumerate() {
                    if index > 0 {
                        said.extend_from_slice(b", ");
                    }
                    said.extend_from_slice(key.as_bytes());
                }
                said.push(b'.');
                Ok(reply(
                    Str::from_surrogatepass(said).unwrap_or_default(),
                    &object([("settings", Value::Object(values))]),
                    None,
                ))
            }
            "preview_recovery_message" => {
                let changes = arg(arguments, "changes");
                if !matches!(changes, Value::Null) {
                    let Value::Object(changes) = &changes else {
                        return refuse("changes must be an object");
                    };
                    let allowed = [
                        "interface_language",
                        "continuation_language",
                        "continuation_style",
                        "custom_message_mode",
                    ];
                    if changes
                        .keys()
                        .any(|key| !key.as_str().is_some_and(|each| allowed.contains(&each)))
                    {
                        return refuse("only language and style can be previewed from Codex");
                    }
                }
                let preview = control.preview_continuation(
                    &arg(arguments, "category"),
                    &changes,
                    &Value::Null,
                    &Value::Null,
                )?;
                let said = match field(&preview, "text") {
                    Some(Value::Str(text)) => text.clone(),
                    _ => return Err(Raised::Other),
                };
                Ok(reply(said, &object([("preview", preview)]), None))
            }
            "restore_default_settings" => Ok(reply(
                "Settings restored to their defaults.",
                &object([("settings", Value::Object(control.restore_defaults()?))]),
                None,
            )),
            "pause_auto_recovery" => {
                let done = control.set_enabled(false)?;
                Ok(reply(
                    "Automatic recovery is paused. Nothing will be sent until it is resumed.",
                    &done,
                    None,
                ))
            }
            "turn_off_power_action" => {
                let done = control.disarm_power_action("mcp")?;
                let changed = field(&done, "changed").is_some_and(car_machine::pyval::truthy);
                Ok(reply(
                    if changed {
                        "The power action is off: this PC stays on when the recoveries finish."
                    } else {
                        "The power action was already off."
                    },
                    &done,
                    None,
                ))
            }
            "resume_auto_recovery" => {
                let done = control.set_enabled(true)?;
                Ok(reply(
                    "Automatic recovery is on again. Every check still applies.",
                    &done,
                    None,
                ))
            }
            "cancel_recovery" => {
                let done = control.cancel_interruption(&id(), "mcp")?;
                let said = format!("{}.", capitalised(&text(field(&done, "message"))?));
                Ok(reply(said, &done, None))
            }
            "reset_recovery_budget" => {
                let done = control.reset_recovery_budget(&id(), "mcp")?;
                let mut said =
                    "Attempts restored; it is waiting again. Nothing was sent.".to_owned();
                if let Some(note) = field(&done, "note")
                    && car_machine::pyval::truthy(note)
                {
                    said.push_str(" Note: ");
                    said.push_str(&text(Some(note))?);
                    said.push('.');
                }
                Ok(reply(said, &done, None))
            }
            "postpone_recovery" => {
                let done = control.postpone(
                    &id(),
                    &thread(),
                    &Value::Null,
                    &arg(arguments, "preset"),
                    &arg(arguments, "minutes"),
                    "mcp",
                )?;
                Ok(reply(
                    "Postponed: nothing is sent for it before not_before. Nothing was sent; every check still applies.",
                    &done,
                    None,
                ))
            }
            "release_hold" => {
                let done = control.release_hold(&id(), &thread(), "mcp")?;
                Ok(reply(
                    "It may continue now. Nothing was sent; the watcher still runs every check.",
                    &done,
                    None,
                ))
            }
            "disable_conversation_recovery" => {
                let done = control.cancel_thread(&thread(), "mcp")?;
                Ok(reply(
                    "Automatic recovery is off for that conversation.",
                    &done,
                    None,
                ))
            }
            "enable_conversation_recovery" => {
                let done = control.set_thread_enabled(&thread(), true, "mcp")?;
                Ok(reply(
                    "Automatic recovery is on again for that conversation. Nothing was sent; every check still applies.",
                    &done,
                    None,
                ))
            }
            "get_recovery_statistics" => {
                let days = statistics_days(arguments)?;
                let done = control.statistics(days.as_ref())?;
                let rate = field(&done, "success_rate");
                let rate = match rate {
                    None | Some(Value::Null) => "not enough data yet".to_owned(),
                    Some(Value::Float(x)) => {
                        let rounded = (x * 100.0).round_ties_even();
                        if !rounded.is_finite() {
                            return Err(Raised::Other);
                        }
                        format!("{}%", rounded as i128)
                    }
                    Some(Value::Int(int)) => match int.as_i64() {
                        Some(each) => format!("{}%", i128::from(each) * 100),
                        None => return Err(Raised::Other),
                    },
                    Some(_) => return Err(Raised::Other),
                };
                let said = format!(
                    "{} interruptions, {} continuations sent, {} recovered; success rate {}.",
                    count(field(&done, "interruptions_detected"))?,
                    count(field(&done, "continuations_submitted"))?,
                    count(field(&done, "outcomes").and_then(|each| field(each, "recovered")))?,
                    rate
                );
                Ok(reply(said, &done, None))
            }
            "get_recovery_timeline" => {
                let done = control.timeline(&id())?;
                let events = match field(&done, "events") {
                    Some(Value::Array(events)) => events.len(),
                    _ => return Err(Raised::Other),
                };
                Ok(reply(format!("{events} events."), &done, None))
            }
            "clear_recovery_history" => {
                let done = control.clear_history("mcp")?;
                let said = format!(
                    "{} finished recoveries hidden; {} kept visible because they may still change. Nothing was deleted.",
                    count(field(&done, "hidden"))?,
                    count(field(&done, "kept"))?
                );
                Ok(reply(said, &done, None))
            }
            "start_watcher" => {
                let done = control.start_watcher()?;
                let state = match field(&done, "state") {
                    Some(Value::Str(state)) => state.as_str().map(str::to_owned),
                    _ => None,
                };
                let mut said = start_wording(state.as_deref()).to_owned();
                let mut done = done;
                if field(&done, "started").is_some_and(car_machine::pyval::truthy) {
                    let ends = control.launch_ends_with_job();
                    if let Value::Object(map) = &mut done {
                        map.insert(
                            Str::from("ends_with_codex"),
                            ends.map_or(Value::Null, Value::Bool),
                        );
                    }
                    if ends != Some(false) && state.as_deref() != Some("exited") {
                        said.push(' ');
                        said.push_str(ends_with_codex(ends));
                    }
                }
                Ok(reply(said, &done, None))
            }
            "retry_now" => {
                let done = control.request_retry_now(&id(), "mcp")?;
                let said = format!(
                    "{}. The watcher still revalidates it, still needs the conversation open, and still refuses anything uncertain.",
                    capitalised(&text(field(&done, "note"))?)
                );
                Ok(reply(said, &done, None))
            }
            _ => Err(Raised::Other),
        }
    }
}

/// `_write(payload)`: one response as one line - the response, else the internal error for its id, else that error
/// with a null id. False where nothing could be written (the reference's loop dies).
fn write(payload: &Value, output: &mut dyn Write) -> bool {
    let id = field(payload, "id").cloned().unwrap_or(Value::Null);
    let failed = error(&id, INTERNAL_ERROR, GENERIC_ERROR);
    let line = match encode(&[
        payload.clone(),
        failed,
        error(&Value::Null, INTERNAL_ERROR, GENERIC_ERROR),
    ]) {
        Ok(line) => line,
        Err(_) => return false,
    };
    output
        .write_all(format!("{line}\n").as_bytes())
        .and_then(|_| output.flush())
        .is_ok()
}

//! `marker_free_continuation`'s code (seat S7.2e1b; `engine/markerfree.py`): the advanced edition's answer at P5 and
//! P15 - every continuation sent with no marker, under the client id core derives, as one `thread/queue/add` through
//! Codex's own app server (M7).
//!
//! P15 answers CLIENT_ID; P5 names [`MarkerFreeChannel`], whose one send adds the words to the conversation's queue and
//! says what came of it as core's backend does: accepted (with the queued item's id), unknown, or not started. It
//! carries a QUEUE_FOR_OPEN answer where MQO passed (`carries`) and pools where MQP passed. Core holds the launch guard
//! around the whole send here (car-policy's `Channel::send` takes none), so the reference's "consent refused" answer,
//! which only a guard handed in can give, never arises (AUDIT-v0628.md).
//!
//! The pieces the prompt queue's and the chat's channels reuse (their Python classes subclass this one): [`send`],
//! [`queue_id`], [`MAX_PROMPT`], [`Open`].

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_policy::plug::{Alternative, Channel, HookFailed};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::headless::Opener;
use crate::codex::session::{self, SessionError};
use crate::state::scoped::Scoped;
use crate::vocabulary::{ArmingWarning, Measurement};

pub const CAPABILITY: &str = "marker_free_continuation";
pub const METHOD: &str = "thread/queue/add";
/// What core's own send takes as one message (codex/transport.py), and so all this one takes.
pub const MAX_PROMPT: usize = car_policy::classify::continuation::PROMPT_SEND_LIMIT;

/// The factory of the app-server session the one call is made in (`session=`), shared by the code and its channels.
pub type Open = Arc<Mutex<Opener>>;

/// What a code made from `paths` alone opens: nothing (the live session over `inuse.backend` is the entry points'
/// to hand in, S7.3d) - every send is then "not started", as one with no app server is.
pub fn no_session() -> Open {
    Arc::new(Mutex::new(Box::new(|_: &str| Err(()))))
}

fn word(text: &str) -> Value {
    Value::Str(text.into())
}

fn answer(pairs: &[(&str, Value)]) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert((*name).into(), value.clone());
    }
    Value::Object(map)
}

/// `{"outcome": "not_started", "error_code": code}`.
pub fn not_started(code: &str) -> Value {
    answer(&[("outcome", word("not_started")), ("error_code", word(code))])
}

/// `_queue_id(result)`: the queued item's id in what thread/queue/add answered, where it says one in a shape this knows.
pub fn queue_id(result: &Value) -> Value {
    let Value::Object(map) = result else {
        return Value::Null;
    };
    let mut found: Vec<Value> = vec![
        map.get("queuedSubmissionId")
            .cloned()
            .unwrap_or(Value::Null),
        map.get("id").cloned().unwrap_or(Value::Null),
    ];
    for name in ["queuedSubmission", "item"] {
        if let Some(Value::Object(nested)) = map.get(name) {
            found.push(nested.get("id").cloned().unwrap_or(Value::Null));
        }
    }
    found.into_iter().find(ids::is_uuid).unwrap_or(Value::Null)
}

/// The add's `input`: the words alone.
pub fn text_input(prompt: &Str) -> Value {
    Value::Array(vec![answer(&[
        ("type", word("text")),
        ("text", Value::Str(prompt.clone())),
    ])])
}

/// Whether the words are ones this channel sends: some, at most MAX_PROMPT code points, no NUL.
pub fn prompt_passes(prompt: &Str) -> bool {
    !prompt.is_empty()
        && prompt.len() <= MAX_PROMPT
        && !prompt.code_points().any(|point| point == 0)
}

/// `MarkerFreeContinuation.send`'s body: `params` added under `capability`'s session; never raises.
pub fn send_params(open: &Open, capability: &str, params: Value) -> Value {
    let opened = {
        let mut open = open.lock().unwrap_or_else(PoisonError::into_inner);
        (open)(capability)
    };
    let Ok(mut channel) = opened else {
        return not_started("queue_spawn_failed");
    };
    if channel.enter().is_err() {
        return not_started("queue_spawn_failed");
    }
    let pending = session::submitted(channel.as_mut(), METHOD, Some(params));
    let result = pending.answer(channel.as_mut());
    channel.exit();
    match result {
        Ok(result) => answer(&[
            ("outcome", word("accepted")),
            ("queue_id", queue_id(&result)),
        ]),
        Err(SessionError::Refused) => not_started("queue_preflight_failed"),
        Err(error) => answer(&[
            ("outcome", word("unknown")),
            (
                "error_code",
                word(if error.text() == "protocol_timeout" {
                    "queue_timeout"
                } else {
                    "queue_result_unknown"
                }),
            ),
        ]),
    }
}

/// `send(thread_id, prompt, client_id=None)` with the add's `input` a channel builds: the preflight, then the one add.
pub fn send(
    open: &Open,
    capability: &str,
    thread_id: &str,
    prompt: &Str,
    client_id: Option<&str>,
    input: impl FnOnce(&Str) -> Value,
) -> Value {
    let thread = word(thread_id);
    if !ids::is_uuid(&thread)
        || !prompt_passes(prompt)
        || !client_id.is_none_or(|client| ids::is_uuid(&word(client)))
    {
        return not_started("queue_preflight_failed");
    }
    let client = client_id.map_or_else(car_platform::ipc_pipe::uuid4, str::to_owned);
    let params = answer(&[
        ("threadId", thread),
        ("input", input(prompt)),
        ("clientUserMessageId", word(&client)),
    ]);
    send_params(open, capability, params)
}

/// True where `measurement` passed on the Codex in force, else why not as the statement's warning words say it.
pub fn measured_or_why(scoped: Option<&Scoped<'_>>, measurement: Measurement) -> Value {
    if let Some(scoped) = scoped {
        let name = word(measurement.as_str());
        if scoped.passed(&name) {
            return Value::Bool(true);
        }
        if scoped.failed(&name) {
            return word(ArmingWarning::MeasurementFailed.as_str());
        }
    }
    word(ArmingWarning::Unmeasured.as_str())
}

/// `pools()` of a channel bound to `binding`: True where MQP passed, else the warning word.
pub fn pools_of(binding: Option<&Binding>) -> Value {
    binding
        .and_then(|binding| binding.with(|scoped| measured_or_why(Some(scoped), Measurement::Mqp)))
        .unwrap_or_else(|| word(ArmingWarning::Unmeasured.as_str()))
}

/// A second hold of the same binding (for a channel, which outlives the hook).
pub fn rebound(binding: Option<&Binding>) -> Option<Binding> {
    binding.map(super::emptyreply::rebind)
}

/// The channel core sends through (the reference's code object itself, handed back at P5).
pub struct MarkerFreeChannel {
    binding: Option<Binding>,
    open: Open,
}

impl Channel for MarkerFreeChannel {
    fn send(&self, thread_id: &str, prompt: &Str, client_id: Option<&str>) -> Value {
        send(
            &self.open, CAPABILITY, thread_id, prompt, client_id, text_input,
        )
    }
    fn pools(&self) -> Result<bool, HookFailed> {
        Ok(matches!(pools_of(self.binding.as_ref()), Value::Bool(true)))
    }
    fn pools_said(&self) -> Option<Result<Value, HookFailed>> {
        Some(Ok(pools_of(self.binding.as_ref())))
    }
}

/// `MarkerFreeContinuation(paths, session=None)`.
pub struct MarkerFreeContinuation {
    pub paths: Paths,
    binding: Option<Binding>,
    open: Open,
}

impl MarkerFreeContinuation {
    pub fn new(paths: Paths, open: Open) -> MarkerFreeContinuation {
        MarkerFreeContinuation {
            paths,
            binding: None,
            open,
        }
    }
}

/// `carries(word)`: True for QUEUE_FOR_OPEN where MQO passed on the Codex in force; otherwise why not.
pub fn carries_of(binding: Option<&Binding>, said: &Value) -> Value {
    let queued = matches!(said, Value::Str(text) if text.as_str() == Some(Alternative::QueueForOpen.as_str()));
    if queued && let Some(binding) = binding {
        return binding
            .with(|scoped| measured_or_why(Some(scoped), Measurement::Mqo))
            .unwrap_or_else(|| word(ArmingWarning::Unmeasured.as_str()));
    }
    word(ArmingWarning::Unmeasured.as_str())
}

impl Code for MarkerFreeContinuation {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    fn carries(&mut self, said: &Value) -> Option<Result<Value, Raised>> {
        Some(Ok(carries_of(self.binding.as_ref(), said)))
    }

    /// P5: this object is the channel.
    fn sender(&mut self, _record: &Value) -> Spoke {
        Ok(Said::Channel(Box::new(MarkerFreeChannel {
            binding: rebound(self.binding.as_ref()),
            open: self.open.clone(),
        })))
    }

    /// P15: no marker; core derives the client id and proves delivery by it.
    fn delivery(&mut self, _record: &Value) -> Spoke {
        Ok(Said::Word(Alternative::ClientId))
    }
}

/// `make(paths)`: the capability's code with the session a code made from `paths` alone has.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(paths, no_session())
}

/// `MarkerFreeContinuation(paths, session=...)` with an entry point's or a test's own session.
pub fn make_with(paths: &Paths, open: Open) -> Option<Box<dyn Code>> {
    Some(Box::new(MarkerFreeContinuation::new(paths.clone(), open)))
}

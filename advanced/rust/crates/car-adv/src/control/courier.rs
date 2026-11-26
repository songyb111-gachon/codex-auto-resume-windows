//! `control/courier.py` (seat S7.3b): the courier's card on the Advanced features page - its bridge commands, the
//! Dashboard's alone.
//!
//! * advanced-courier - the card read: each channel's switch, whether its address and secret are saved (never what
//!   they are), its refusals today and whether they turned it off, the events picked, Telegram's pairing, the feed;
//! * advanced-courier-save - one channel's address and secret checked and kept - or, for Telegram with `pair`, a
//!   pairing begun (a one-time code answered for the card, only its digest kept);
//! * advanced-courier-forget - one channel's address and secret taken out of Credential Manager;
//! * advanced-courier-test - the fixed test notice sent now by a courier run, its outcome one word;
//! * advanced-feed-refresh - a courier run with `--feed` started, and the last reading answered.
//!
//! No answer ever carries an address, a token, a password or the chat kept. Nothing here sends: the courier does, in
//! its own process (`courier::launch`).

use car_machine::json::{Map, Str, Value};

use crate::courier::address::{self, Shape};
use crate::courier::main::Runtime;
use crate::courier::{feed, keep, outbox};
use crate::credentials::Secrets;
use crate::engine::push;
use crate::jsonx::object;
use crate::state::sql::{self, string};
use crate::vocabulary::{ArmingState, CourierChannel, Refusal};

pub const PUSH: &str = "push_notices";
pub const FEED: &str = "status_feed";
pub const TEST_SECONDS: i64 = 30;

/// `TEST_WORDS[code]`: a test notice's exit code as the card's word.
pub fn test_word(code: Option<i32>) -> &'static str {
    match code {
        Some(0) => "sent",
        Some(5) => "refused",
        Some(6) => "server_error",
        Some(7) => "timed_out",
        Some(8) => "tls",
        Some(3) => "busy",
        Some(4) => "not_saved",
        _ => "no_answer",
    }
}

fn refused(word: Refusal) -> Value {
    object([
        ("done", Value::Bool(false)),
        ("refusal", Value::from(word.as_str())),
    ])
}

fn refused_why(word: Refusal, why: &str) -> Value {
    object([
        ("done", Value::Bool(false)),
        ("refusal", Value::from(word.as_str())),
        ("why", Value::from(why)),
    ])
}

/// `_standing(runtime, capability, watched=)`.
fn standing(runtime: &dyn Runtime, capability: &str, watched: bool) -> Option<Refusal> {
    if runtime.registry().get(capability).is_none() {
        return Some(Refusal::UnknownCapability);
    }
    let Ok(states) = runtime.states() else {
        return Some(Refusal::StateUnavailable);
    };
    match states.state_of(capability) {
        ArmingState::Armed => None,
        ArmingState::Shadow if watched => None,
        _ => Some(Refusal::NotOn),
    }
}

fn channel_of(value: &Value) -> Option<&'static str> {
    crate::state::py::text(value)
        .and_then(CourierChannel::parse)
        .map(CourierChannel::as_str)
}

fn has(secrets: &Secrets<'_>, name: &str) -> bool {
    matches!(keep::read(secrets, name), Ok(Some(_)))
}

/// `view(runtime, secrets=)`: what the card shows - never a secret.
pub fn view(runtime: &dyn Runtime, secrets: &Secrets<'_>) -> Value {
    if runtime.registry().get(PUSH).is_none() {
        return refused(Refusal::UnknownCapability);
    }
    let now = runtime.clock();
    let state = runtime.state();
    let read = (|| -> Result<(Map, Vec<Value>, bool, bool, Value), crate::state::Error> {
        let options = state.options(&string(PUSH))?;
        let mut rows = Vec::new();
        for channel in CourierChannel::ALL {
            let word = channel.as_str();
            let refused_today = outbox::refusals_today(state, &Value::from(word), now)?;
            let on = sql::py_eq(options.get(word).unwrap_or(&Value::Null), &Value::from(1));
            rows.push(object([
                ("channel", Value::from(word)),
                ("on", Value::Bool(on)),
                ("saved", Value::Bool(keep::saved(secrets, word))),
                ("refused_today", Value::from(refused_today)),
                (
                    "tripped",
                    Value::Bool(!on && refused_today >= outbox::TRIPWIRE),
                ),
            ]));
        }
        let token = keep::saved(secrets, "telegram") || has(secrets, "telegram_token");
        let row = keep::pairing(state)?;
        let pairing = row.as_ref().is_some_and(|row| {
            car_machine::pyval::truthy(sql::get(row, "code_digest"))
                && crate::state::py::as_f64(sql::get(row, "code_expires_at")).unwrap_or(0.0) > now
        });
        let reading = if runtime.registry().get(FEED).is_some() {
            feed::read(state)?.map_or(Value::Null, Value::Object)
        } else {
            Value::Null
        };
        Ok((options, rows, token, pairing, reading))
    })();
    let Ok((options, rows, token, pairing, reading)) = read else {
        return refused(Refusal::StateUnavailable);
    };
    object([
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("channels", Value::Array(rows)),
        (
            "events",
            options.get("push_events").cloned().unwrap_or(Value::Null),
        ),
        (
            "event_order",
            Value::Array(
                push::events()
                    .iter()
                    .map(|event| Value::from(event.as_str()))
                    .collect(),
            ),
        ),
        (
            "telegram",
            object([
                ("token_saved", Value::Bool(token)),
                ("paired", Value::Bool(keep::saved(secrets, "telegram"))),
                ("pairing", Value::Bool(pairing)),
            ]),
        ),
        ("feed", reading),
    ])
}

/// How a pairing's code is drawn (`"%06d" % secrets.randbelow(10 ** 6)`) and a courier started (`launch.start`).
pub struct Seams<'a> {
    pub code: &'a dyn Fn() -> String,
    pub start: &'a dyn Fn(&[&str]) -> bool,
    pub run: &'a dyn Fn(&[&str], i64) -> Option<i32>,
}

/// `save(runtime, argument, secrets=, start=)`: one channel's address and secret checked and kept, or Telegram's
/// pairing begun.
pub fn save(
    runtime: &dyn Runtime,
    argument: &Value,
    secrets: &Secrets<'_>,
    seams: &Seams<'_>,
) -> Value {
    if let Some(refusal) = standing(runtime, PUSH, true) {
        return refused(refusal);
    }
    let get = |key: &str| match argument {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    let Some(channel) = channel_of(&get("channel")) else {
        return refused(Refusal::InvalidRequest);
    };
    let name = |text: &str| string(text);
    let kept = (|| -> Result<Option<Value>, Kept> {
        match channel {
            "ntfy" => {
                let url = address::checked_url(&get("url"))?;
                secrets.write(PUSH, &name("ntfy_url"), &Value::from(url))?;
            }
            "webhook" => {
                let token = get("token");
                let url = address::checked_url(&get("url"))?;
                let token = match &token {
                    Value::Null => None,
                    Value::Str(text) if text.is_empty() => None,
                    other => Some(address::checked_token(other, Shape::Printable)?),
                };
                secrets.write(PUSH, &name("webhook_url"), &Value::from(url))?;
                match token {
                    None => {
                        secrets.delete(PUSH, &name("webhook_token"))?;
                    }
                    Some(token) => {
                        secrets.write(PUSH, &name("webhook_token"), &Value::from(token))?
                    }
                }
            }
            "telegram" if matches!(get("pair"), Value::Bool(true)) => {
                return Ok(Some(begin_pair(runtime, secrets, seams.code, seams.start)));
            }
            "telegram" => {
                let token = address::checked_token(&get("token"), Shape::TelegramToken)?;
                secrets.write(PUSH, &name("telegram_token"), &Value::from(token))?;
                secrets.delete(PUSH, &name("telegram_chat"))?;
                secrets.delete(PUSH, &name("telegram_chat_name"))?;
            }
            _ => {
                let mut blob = Map::new();
                for key in ["host", "port", "user", "password", "from", "to"] {
                    blob.insert(Str::from(key), get(key));
                }
                let checked = address::checked_smtp(&Value::Object(blob))?;
                let text = car_machine::json::to_string(
                    &checked,
                    &car_machine::json::Options::new().separators(",", ":"),
                )
                .map_err(|_| Kept::Secret)?;
                secrets.write(PUSH, &name("smtp"), &Value::from(text))?;
            }
        }
        Ok(None)
    })();
    match kept {
        Ok(Some(paired)) => paired,
        Ok(None) => object([
            ("done", Value::Bool(true)),
            ("refusal", Value::Null),
            ("saved", Value::Bool(keep::saved(secrets, channel))),
        ]),
        Err(Kept::Address(word)) => refused_why(Refusal::AddressRefused, word),
        Err(Kept::Secret) => refused(Refusal::SecretUnavailable),
    }
}

enum Kept {
    Address(&'static str),
    Secret,
}

impl From<address::AddressRefused> for Kept {
    fn from(refused: address::AddressRefused) -> Kept {
        Kept::Address(refused.word)
    }
}

impl From<crate::credentials::SecretError> for Kept {
    fn from(_: crate::credentials::SecretError) -> Kept {
        Kept::Secret
    }
}

/// `_pair(runtime, secrets, start)`: Telegram's pairing begun - the code answered for the card, its digest kept.
pub fn begin_pair(
    runtime: &dyn Runtime,
    secrets: &Secrets<'_>,
    code: &dyn Fn() -> String,
    start: &dyn Fn(&[&str]) -> bool,
) -> Value {
    if !has(secrets, "telegram_token") {
        return refused(Refusal::NotSaved);
    }
    let code = code();
    let now = runtime.clock();
    if keep::begin_pairing(runtime.state(), &Value::from(code.as_str()), now).is_err() {
        return refused(Refusal::StateUnavailable);
    }
    if !start(&["--pair"]) {
        return refused(Refusal::CourierUnavailable);
    }
    object([
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("code", Value::from(code)),
        ("expires_at", Value::Float(now + keep::PAIR_SECONDS)),
    ])
}

/// `forget(runtime, channel, secrets=)`: one channel's address and secret taken out of Credential Manager.
pub fn forget(runtime: &dyn Runtime, channel: &Value, secrets: &Secrets<'_>) -> Value {
    let channel = channel_of(channel);
    let Some(channel) = channel.filter(|_| runtime.registry().get(PUSH).is_some()) else {
        return refused(Refusal::InvalidRequest);
    };
    for name in keep::channel_secrets(channel) {
        if secrets.delete(PUSH, &string(name)).is_err() {
            return refused(Refusal::SecretUnavailable);
        }
    }
    object([("done", Value::Bool(true)), ("refusal", Value::Null)])
}

/// `test(runtime, channel, secrets=, run=)`: the test notice sent now by a courier run, waited for at most
/// TEST_SECONDS.
pub fn test(
    runtime: &dyn Runtime,
    channel: &Value,
    secrets: &Secrets<'_>,
    seams: &Seams<'_>,
) -> Value {
    if let Some(refusal) = standing(runtime, PUSH, true) {
        return refused(refusal);
    }
    let Some(channel) = channel_of(channel) else {
        return refused(Refusal::InvalidRequest);
    };
    if !keep::saved(secrets, channel) {
        return object([
            ("done", Value::Bool(true)),
            ("refusal", Value::Null),
            ("outcome", Value::from("not_saved")),
        ]);
    }
    let code = (seams.run)(&["--test", channel], TEST_SECONDS);
    object([
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("outcome", Value::from(test_word(code))),
    ])
}

/// `feed_refresh(runtime, start=)`: one reading started now, and the last one answered.
pub fn feed_refresh(runtime: &dyn Runtime, seams: &Seams<'_>) -> Value {
    if let Some(refusal) = standing(runtime, FEED, false) {
        return refused(refusal);
    }
    let started = (seams.start)(&["--feed"]);
    let reading = feed::read(runtime.state())
        .ok()
        .flatten()
        .map_or(Value::Null, Value::Object);
    object([
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("started", Value::Bool(started)),
        ("feed", reading),
    ])
}

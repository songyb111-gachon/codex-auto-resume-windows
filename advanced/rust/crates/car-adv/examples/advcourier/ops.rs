//! The ops of advcourier, one family each: address, keep, feed, mime, telegram, remote, api, push, outbox, channels.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use car_adv::arming::States;
use car_adv::control::remote::{self as remote, Failed, Layer};
use car_adv::courier::address::{self, Shape};
use car_adv::courier::channels::{self, mime};
use car_adv::courier::http::{Answer, Fault, Opener, Request};
use car_adv::courier::main::Runtime;
use car_adv::courier::{api, feed, keep, outbox, telegram};
use car_adv::credentials::Secrets;
use car_adv::engine::push;
use car_adv::jsonx::object;
use car_adv::registry::{self, Registry};
use car_adv::state::AdvancedState;
use car_adv::state::seam::Tokens;
use car_adv::vocabulary::{ArmingState, OffReason};
use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_platform::credman::{Backend, Memory};

use crate::util::{Failure, Out, arg, bad, float, list, map, maybe_text, number, text, untag};

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "address.url" => Ok(refusal_or(
            address::checked_url(arg(args, 0)?).map(Value::from),
        )),
        "address.token" => {
            let shape = match maybe_text(arg(args, 1)?)? {
                Some("telegram_token") => Shape::TelegramToken,
                Some("telegram_chat") => Shape::TelegramChat,
                _ => Shape::Printable,
            };
            Ok(refusal_or(
                address::checked_token(arg(args, 0)?, shape).map(Value::from),
            ))
        }
        "address.mailbox" => Ok(refusal_or(
            address::checked_mailbox(arg(args, 0)?).map(Value::from),
        )),
        "address.smtp" => Ok(refusal_or(address::checked_smtp(arg(args, 0)?))),
        "address.host" => {
            Ok(address::host_problem_value(arg(args, 0)?).map_or(Value::Null, Value::from))
        }
        "address.web_view" => Ok(Value::from(address::web_view(
            number(arg(args, 0)?)?,
            maybe_text(arg(args, 1)?)?,
            maybe_text(arg(args, 2)?)?,
        ))),
        "keep.label" => Ok(keep::chat_label(arg(args, 0)?).map_or(Value::Null, Value::from)),
        "keep.digest" => Ok(Value::from(keep::digest(text(arg(args, 0)?)?))),
        "feed.parse" => match feed::parse(&bytes(arg(args, 0)?)?) {
            Ok((word, codex, count)) => Ok(Value::Array(vec![
                Value::from(word.as_str()),
                Value::from(codex.as_str()),
                Value::from(count),
            ])),
            Err(()) => Err(Failure::new("RecursionError")),
        },
        "mime.flatten" => Ok(byte_list(&mime::flatten(
            text(arg(args, 0)?)?,
            text(arg(args, 1)?)?,
            text(arg(args, 2)?)?,
            text(arg(args, 3)?)?,
        ))),
        "telegram.parse" => {
            let (command, alias) = telegram::parse(arg(args, 0)?);
            Ok(Value::Array(vec![
                command.map_or(Value::Null, Value::from),
                alias.map_or(Value::Null, Value::from),
            ]))
        }
        "telegram.first_id" => {
            Ok(telegram::first_update_id(&bytes(arg(args, 0)?)?).map_or(Value::Null, Value::from))
        }
        "telegram.readable" => match telegram::readable(&bytes(arg(args, 0)?)?) {
            Ok(Some(found)) => Ok(Value::Array(found.into_iter().map(Value::Object).collect())),
            Ok(None) => Ok(Value::Null),
            Err(()) => Err(Failure::new("RecursionError")),
        },
        "remote.pending" => {
            let layer = FakeLayer::new(list(arg(args, 0)?)?.clone());
            failed(remote::pending(&layer))
        }
        "remote.metrics" => failed(remote::metrics(arg(args, 0)?).map(Value::from)),
        "remote.resolve" => {
            let layer = FakeLayer::new(list(arg(args, 0)?)?.clone());
            failed(remote::resolve(&layer, arg(args, 1)?, arg(args, 2)?))
        }
        "remote.acts" => remote_acts(args),
        "api.route" => Ok(api::route_of(text(arg(args, 0)?)?).map_or(Value::Null, Value::from)),
        "api.host" => Ok(Value::Bool(api::host_allowed(
            text(arg(args, 0)?)?,
            number(arg(args, 1)?)?,
            matches!(arg(args, 2)?, Value::Bool(true)),
        ))),
        "api.client" => Ok(Value::from(api::client_of(text(arg(args, 0)?)?))),
        "api.headers" => Ok(Value::Array(
            api::parse_header_block(text(arg(args, 0)?)?)
                .into_iter()
                .map(|(name, value)| Value::Array(vec![Value::from(name), Value::from(value)]))
                .collect(),
        )),
        "api.gate" => api_gate(args),
        "api.date" => Ok(Value::from(api::http_date(float(arg(args, 0)?)?))),
        "push.event" => {
            Ok(push::event_of(arg(args, 0)?)
                .map_or(Value::Null, |event| Value::from(event.as_str())))
        }
        "push.picked" => {
            let event = push::events()
                .into_iter()
                .find(|each| Some(each.as_str()) == arg(args, 1).ok().and_then(|v| text(v).ok()))
                .ok_or_else(bad)?;
            Ok(Value::Bool(push::picked(arg(args, 0)?, event)))
        }
        "push.constants" => Ok(object([
            (
                "events",
                Value::Array(
                    push::events()
                        .iter()
                        .map(|e| Value::from(e.as_str()))
                        .collect(),
                ),
            ),
            ("default", Value::from(push::default_events())),
            (
                "codes",
                Value::Array(outbox::codes().into_iter().map(Value::from).collect()),
            ),
        ])),
        "outbox.scenario" => outbox_scenario(args),
        "channels.lines" => channels_lines(args),
        "channels.send" => channels_send(args),
        "channels.drain" => channels_drain(args),
        "channels.pair" => channels_pair(args),
        "api.serve" => api_serve(args),
        _ => Err(Failure::new("UnknownOp")),
    }
}

fn refusal_or(found: Result<Value, address::AddressRefused>) -> Value {
    match found {
        Ok(value) => object([("ok", value)]),
        Err(refused) => object([("refused", Value::from(refused.word))]),
    }
}

fn failed(found: Result<Value, Failed>) -> Out {
    match found {
        Ok(value) => Ok(value),
        Err(Failed::Stale) => Err(Failure::new("Stale")),
        Err(Failed::Raised(class)) => Err(Failure::new(&class)),
    }
}

fn bytes(value: &Value) -> Result<Vec<u8>, Failure> {
    list(value)?
        .iter()
        .map(|each| number(each).and_then(|n| u8::try_from(n).map_err(|_| bad())))
        .collect()
}

/// A value with every {"$float": ...} tag turned back into its float.
fn untagged(value: &Value) -> Value {
    match value {
        Value::Object(found) if found.len() == 1 && found.get("$float").is_some() => {
            crate::util::tagged_float(value).map_or(value.clone(), Value::Float)
        }
        Value::Object(found) => {
            let mut made = Map::new();
            for (key, each) in found.iter() {
                made.insert(key.clone(), untagged(each));
            }
            Value::Object(made)
        }
        Value::Array(items) => Value::Array(items.iter().map(untagged).collect()),
        other => other.clone(),
    }
}

fn byte_list(data: &[u8]) -> Value {
    Value::Array(data.iter().map(|b| Value::from(i64::from(*b))).collect())
}

fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    match value {
        Value::Object(found) => found.get(key).unwrap_or(&Value::Null),
        _ => &Value::Null,
    }
}

// ------------------------------------------------------------------------------------------ the fakes
/// The tests' control layer: its pending rows, and every act asked of it.
struct FakeLayer {
    rows: Vec<Value>,
    asked: Mutex<Vec<Value>>,
}

impl FakeLayer {
    fn new(rows: Vec<Value>) -> FakeLayer {
        FakeLayer {
            rows,
            asked: Mutex::new(Vec::new()),
        }
    }

    fn note(&self, value: Value) {
        self.asked
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(value);
    }
}

impl Layer for FakeLayer {
    fn pending_rows(&self) -> Result<Vec<Value>, Failed> {
        Ok(self.rows.clone())
    }
    fn status_document(&self, now: f64) -> Result<Value, Failed> {
        Ok(object([
            ("watcher", Value::from("running")),
            ("recovery", Value::from("on")),
            ("pending", Value::from(self.rows.len() as i64)),
            ("states", object([])),
            ("next_check_at", Value::Null),
            ("written_at", Value::Float(now)),
        ]))
    }
    fn set_enabled(&self, enabled: bool) -> Result<Value, Failed> {
        self.note(Value::Array(vec![
            Value::from("set_enabled"),
            Value::Bool(enabled),
        ]));
        Ok(object([("enabled", Value::Bool(enabled))]))
    }
    fn cancel_interruption(&self, id: &Value, actor: &str) -> Result<Value, Failed> {
        self.note(Value::Array(vec![
            Value::from("cancel"),
            id.clone(),
            Value::from(actor),
        ]));
        Ok(object([("changed", Value::Bool(true))]))
    }
    fn release_hold(&self, id: &Value, thread: &Value, actor: &str) -> Result<Value, Failed> {
        self.note(Value::Array(vec![
            Value::from("release"),
            id.clone(),
            thread.clone(),
            Value::from(actor),
        ]));
        Ok(Value::Null)
    }
    fn watcher_running(&self) -> Option<bool> {
        Some(true)
    }
}

fn remote_acts(args: &[Value]) -> Out {
    let layer = FakeLayer::new(list(arg(args, 0)?)?.clone());
    let mut answers = Vec::new();
    for step in list(arg(args, 1)?)? {
        let step = list(step)?;
        let found = match text(arg(step, 0)?)? {
            "pause" => remote::pause(&layer),
            "lift" => remote::lift_pause(&layer),
            "cancel" => remote::cancel(&layer, arg(step, 1)?, arg(step, 2)?),
            _ => remote::release(&layer, arg(step, 1)?, arg(step, 2)?),
        };
        answers.push(match found {
            Ok(value) => object([("ok", value)]),
            Err(Failed::Stale) => object([("error", Value::from("Stale"))]),
            Err(Failed::Raised(class)) => object([("error", Value::from(class))]),
        });
    }
    let asked = layer
        .asked
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone();
    Ok(object([
        ("answers", Value::Array(answers)),
        ("asked", Value::Array(asked)),
    ]))
}

fn api_gate(args: &[Value]) -> Out {
    let clock = Arc::new(Mutex::new(0.0f64));
    let reading = clock.clone();
    let gate = api::Gate::new(Arc::new(move || {
        *reading
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }));
    let mut answers = Vec::new();
    for step in list(arg(args, 0)?)? {
        let step = list(step)?;
        *clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = float(arg(step, 1)?)?;
        let client = text(arg(step, 2)?)?;
        answers.push(Value::Bool(match text(arg(step, 0)?)? {
            "wrong" => gate.wrong(client),
            _ => gate.closed(client),
        }));
    }
    let kept: Vec<Value> = gate
        .kept()
        .into_iter()
        .map(|(client, times, until)| {
            Value::Array(vec![
                Value::from(client),
                Value::Array(times.into_iter().map(Value::Float).collect()),
                Value::Float(until),
            ])
        })
        .collect();
    Ok(object([
        ("answers", Value::Array(answers)),
        ("kept", Value::Array(kept)),
    ]))
}

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

struct Counter(Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = self
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held += 1;
        format!("{:0width$x}", *held, width = 2 * count)
    }
}

/// The courier's runtime over a real advanced state in a scratch home: the clock pinned, the states scripted.
struct Probe {
    state: AdvancedState,
    registry: Arc<Registry>,
    paths: Paths,
    clock: Arc<Mutex<f64>>,
    states: Vec<(String, ArmingState)>,
    trips: Mutex<Vec<Value>>,
}

impl Runtime for Probe {
    fn state(&self) -> &AdvancedState {
        &self.state
    }
    fn registry(&self) -> &Registry {
        &self.registry
    }
    fn paths(&self) -> &Paths {
        &self.paths
    }
    fn clock(&self) -> f64 {
        *self
            .clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
    fn states(&self) -> Result<States, ()> {
        Ok(States(self.states.clone()))
    }
    fn unreadable(&self) -> bool {
        false
    }
    fn trip(&self, capability: &str, reason: OffReason) -> Result<bool, ()> {
        self.trips
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(Value::Array(vec![
                Value::from(capability),
                Value::from(reason.as_str()),
            ]));
        Ok(true)
    }
}

fn probe(home: &Value, clock: f64, states: &Value) -> Result<Probe, Failure> {
    let home = PathBuf::from(format!("{}-rust", text(home)?));
    std::fs::create_dir_all(&home).map_err(|_| Failure::new("OSError"))?;
    let home_text = home.to_string_lossy().into_owned();
    let no_env = |_: &str| None;
    let paths = Paths::new(
        Some(&home_text),
        &home_text,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .map_err(|_| Failure::new("PathsError"))?;
    let registry = Arc::new(registry::shipped(false).map_err(|_| Failure::new("RegistryError"))?);
    let clock = Arc::new(Mutex::new(clock));
    let reading = clock.clone();
    let state = AdvancedState::new(
        paths.clone(),
        registry.clone(),
        Box::new(move || {
            *reading
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }),
        Arc::new(Counter(Mutex::new(0))),
    );
    let mut scripted = Vec::new();
    if let Value::Object(found) = states {
        for (id, word) in found.iter() {
            let word = match text(word)? {
                "armed" => ArmingState::Armed,
                "shadow" => ArmingState::Shadow,
                _ => ArmingState::Off,
            };
            scripted.push((car_machine::pytext::py_str(&Value::Str(id.clone())), word));
        }
    }
    Ok(Probe {
        state,
        registry,
        paths,
        clock,
        states: scripted,
        trips: Mutex::new(Vec::new()),
    })
}

/// The tests' opener: scripted replies, every request kept as urllib's `Request` held it.
struct FakeOpener {
    replies: Mutex<Vec<Value>>,
    seen: Mutex<Vec<Value>>,
}

impl FakeOpener {
    fn new(replies: &Value) -> Result<FakeOpener, Failure> {
        Ok(FakeOpener {
            replies: Mutex::new(list(replies)?.clone()),
            seen: Mutex::new(Vec::new()),
        })
    }

    fn seen(&self) -> Value {
        Value::Array(
            self.seen
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone(),
        )
    }
}

impl Opener for FakeOpener {
    fn open(&self, request: &Request, most: usize) -> Result<Answer, Fault> {
        self.seen
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(object([
                ("url", Value::from(request.url.as_str())),
                ("method", Value::from(request.method.as_str())),
                (
                    "headers",
                    Value::Array(
                        request
                            .headers
                            .iter()
                            .map(|(n, v)| {
                                Value::Array(vec![Value::from(n.as_str()), Value::from(v.as_str())])
                            })
                            .collect(),
                    ),
                ),
                (
                    "body",
                    request.body.as_deref().map_or(Value::Null, byte_list),
                ),
                ("timeout", Value::from(request.timeout)),
            ]));
        let mut replies = self
            .replies
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if replies.is_empty() {
            return Err(Fault::Timeout);
        }
        let reply = replies.remove(0);
        let word = |key: &str| field(&reply, key).clone();
        match text(&word("raise")).ok() {
            Some("HTTPError") => return Err(Fault::Status(number(&word("code")).ok())),
            Some("URLError_ssl") => return Err(Fault::Tls),
            Some("URLError") | Some("timeout") | Some("OSError") => return Err(Fault::Timeout),
            Some(other) => return Err(Fault::Raised(other.to_owned())),
            None => {}
        }
        let body = bytes(&word("body")).unwrap_or_default();
        let read = match text(&word("read_raise")).ok() {
            Some("timeout") => Err(Fault::Timeout),
            Some(other) => Err(Fault::Raised(other.to_owned())),
            None => Ok(body[..body.len().min(most)].to_vec()),
        };
        Ok(Answer {
            status: number(&word("status")).ok(),
            body: read,
            expired: matches!(word("expired"), Value::Bool(true)),
        })
    }
}

fn secrets_backend(kept: &Value) -> Result<Arc<Memory>, Failure> {
    let backend = Arc::new(Memory::default());
    for (name, value) in map(kept)?.iter() {
        let name = car_machine::pytext::py_str(&Value::Str(name.clone()));
        backend
            .write(
                &format!("CodexAutoResume/advanced/push_notices/{name}"),
                text(value)?,
            )
            .map_err(|_| Failure::new("SecretError"))?;
    }
    Ok(backend)
}

fn secrets_dump(backend: &Memory) -> Value {
    let held = backend
        .secrets
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut found = Map::new();
    for (target, value) in held.iter() {
        let name = target.rsplit('/').next().unwrap_or("");
        found.insert(Str::from(name), Value::from(value.as_str()));
    }
    Value::Object(found)
}

struct NoWire;

impl channels::smtp::Wire for NoWire {
    fn connect(&self, _: &str, _: u16, _: i64) -> std::io::Result<Box<dyn channels::smtp::Stream>> {
        Err(std::io::Error::other("no SMTP in this op"))
    }
    fn secure(
        &self,
        stream: Box<dyn channels::smtp::Stream>,
        _: &str,
    ) -> Result<Box<dyn channels::smtp::Stream>, channels::smtp::Handshake> {
        Ok(stream)
    }
    fn local_hostname(&self) -> String {
        "pc.example.test".into()
    }
}

fn catalogs(dir: &Value) -> Result<car_adv::statement::Catalogs, Failure> {
    Ok(car_adv::statement::Catalogs::new(
        PathBuf::from(text(dir)?),
        Box::new(|| "en".to_owned()),
    ))
}

fn failure_value(failure: &car_adv::courier::http::Failure) -> Value {
    object([
        ("error", Value::from(failure.class())),
        ("word", failure.word().map_or(Value::Null, Value::from)),
    ])
}

// ------------------------------------------------------------------------------------------ outbox
fn outbox_scenario(args: &[Value]) -> Out {
    let probe = probe(arg(args, 0)?, 0.0, &Value::Null)?;
    let state = &probe.state;
    let mut answers = Vec::new();
    for step in list(arg(args, 1)?)? {
        let step = list(step)?;
        let at =
            |index: usize| -> Result<f64, Failure> { crate::util::tagged_float(arg(step, index)?) };
        let found = match text(arg(step, 0)?)? {
            "enqueue" => outbox::enqueue(
                state,
                list(arg(step, 1)?)?,
                arg(step, 2)?,
                arg(step, 3)?,
                arg(step, 4)?,
                at(5)?,
            )
            .map(Value::from),
            "due" => outbox::due(state, at(1)?)
                .map(|rows| Value::Array(rows.into_iter().map(Value::Object).collect())),
            "waiting" => outbox::waiting(state, at(1)?).map(Value::Bool),
            "settle" => outbox::settle(
                state,
                arg(step, 1)?,
                matches!(arg(step, 2)?, Value::Bool(true)),
                at(3)?,
            )
            .map(Value::from),
            "expire" => outbox::expire(state, at(1)?).map(Value::Array),
            "stale" => outbox::stale(state, arg(step, 1)?, at(2)?).map(Value::Array),
            "refusals" => outbox::refusals_today(state, arg(step, 1)?, at(2)?).map(Value::from),
            "alias" => Ok(outbox::alias(arg(step, 1)?)),
            _ => return Err(bad()),
        };
        answers.push(match found {
            Ok(value) => object([("ok", value)]),
            Err(error) => object([("error", Value::from(error.class()))]),
        });
    }
    state.close();
    Ok(Value::Array(answers))
}

// ------------------------------------------------------------------------------------------ channels
fn channels_lines(args: &[Value]) -> Out {
    let catalogs = catalogs(arg(args, 0)?)?;
    let locale = maybe_text(arg(args, 1)?)?;
    let local = car_platform::localclock::Crt;
    let words = channels::Words {
        catalogs: &catalogs,
        locale,
        local: &local,
    };
    match channels::lines(
        text(arg(args, 2)?)?,
        arg(args, 3)?,
        arg(args, 4)?,
        arg(args, 5)?,
        &words,
    ) {
        Ok(lines) => Ok(Value::Array(lines.into_iter().map(Value::from).collect())),
        Err(failure) => Err(Failure::new(&failure.class())),
    }
}

/// [catalogs, locale, channel, row, secrets, replies] -> {"answer", "requests"}.
fn channels_send(args: &[Value]) -> Out {
    let catalogs = catalogs(arg(args, 0)?)?;
    let locale = maybe_text(arg(args, 1)?)?;
    let local = car_platform::localclock::Crt;
    let registry = registry::shipped(false).map_err(|_| Failure::new("RegistryError"))?;
    let backend = secrets_backend(arg(args, 4)?)?;
    let secrets = Secrets::new(&registry, backend.clone() as Arc<dyn Backend>);
    let opener = FakeOpener::new(arg(args, 5)?)?;
    let wire = || -> Box<dyn channels::smtp::Wire> { Box::new(NoWire) };
    let seams = channels::Seams {
        opener: &opener,
        smtp: &wire,
        words: channels::Words {
            catalogs: &catalogs,
            locale,
            local: &local,
        },
    };
    let Value::Object(row) = untagged(arg(args, 3)?) else {
        return Err(bad());
    };
    let answer = match channels::send(text(arg(args, 2)?)?, &row, &secrets, &seams) {
        Ok(word) => object([("ok", Value::from(word))]),
        Err(failure) => failure_value(&failure),
    };
    Ok(object([("answer", answer), ("requests", opener.seen())]))
}

/// [home, catalogs, now, states, options {channel: 1|2}, secrets, rows to enqueue, replies, pre_refusals]
fn channels_drain(args: &[Value]) -> Out {
    let probe = probe(arg(args, 0)?, float(arg(args, 2)?)?, arg(args, 3)?)?;
    let catalogs = catalogs(arg(args, 1)?)?;
    let local = car_platform::localclock::Crt;
    let state = &probe.state;
    let generation = |state: &AdvancedState| -> Result<Value, Failure> {
        Ok(car_adv::state::sql::get(
            &state.meta().map_err(|e| Failure::new(e.class()))?,
            "generation",
        )
        .clone())
    };
    for (channel, value) in map(arg(args, 4)?)?.iter() {
        let generation = generation(state)?;
        state
            .set_option(
                &Value::from("push_notices"),
                &Value::Str(channel.clone()),
                value,
                &generation,
                &Value::from("dashboard"),
                &Value::Null,
            )
            .map_err(|e| Failure::new(e.class()))?;
    }
    for code in list(arg(args, 8)?)? {
        state
            .counted(&Value::from("push_notices"), code, &Value::Null)
            .map_err(|e| Failure::new(e.class()))?;
    }
    for row in list(arg(args, 6)?)? {
        let row = list(row)?;
        outbox::enqueue(
            state,
            list(arg(row, 0)?)?,
            arg(row, 1)?,
            arg(row, 2)?,
            arg(row, 3)?,
            float(arg(row, 4)?)?,
        )
        .map_err(|e| Failure::new(e.class()))?;
    }
    let registry = registry::shipped(false).map_err(|_| Failure::new("RegistryError"))?;
    let backend = secrets_backend(arg(args, 5)?)?;
    let secrets = Secrets::new(&registry, backend.clone() as Arc<dyn Backend>);
    let opener = FakeOpener::new(arg(args, 7)?)?;
    let wire = || -> Box<dyn channels::smtp::Wire> { Box::new(NoWire) };
    let seams = channels::Seams {
        opener: &opener,
        smtp: &wire,
        words: channels::Words {
            catalogs: &catalogs,
            locale: Some("en"),
            local: &local,
        },
    };
    let answer = match channels::drain(&probe, &secrets, &seams, None) {
        Ok(sent) => object([("ok", Value::from(sent))]),
        Err(channels::Raised::State(error)) => object([("error", Value::from(error.class()))]),
        Err(channels::Raised::Send(failure)) => failure_value(&failure),
    };
    state.close();
    Ok(object([("answer", answer), ("requests", opener.seen())]))
}

/// [home, now, states, secrets, code or null, replies, clock steps] -> {"answer", "requests", "secrets", "trips"}.
fn channels_pair(args: &[Value]) -> Out {
    let probe = probe(arg(args, 0)?, float(arg(args, 1)?)?, arg(args, 2)?)?;
    if let Value::Str(code) = arg(args, 4)? {
        keep::begin_pairing(
            &probe.state,
            &Value::Str(code.clone()),
            float(arg(args, 1)?)?,
        )
        .map_err(|e| Failure::new(e.class()))?;
    }
    let registry = registry::shipped(false).map_err(|_| Failure::new("RegistryError"))?;
    let backend = secrets_backend(arg(args, 3)?)?;
    let secrets = Secrets::new(&registry, backend.clone() as Arc<dyn Backend>);
    let opener = FakeOpener::new(arg(args, 5)?)?;
    let steps: Vec<f64> = list(arg(args, 6)?)?
        .iter()
        .map(float)
        .collect::<Result<_, _>>()?;
    let at = Mutex::new(0usize);
    let clock = || {
        let mut held = at.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let value = steps.get(*held).copied().unwrap_or(f64::INFINITY);
        *held += 1;
        value
    };
    let sleep = |_: f64| {};
    let answer = match channels::pair(&probe, &secrets, &opener, &clock, &sleep) {
        Ok(code) => object([("ok", Value::from(i64::from(code)))]),
        Err(channels::Raised::State(error)) => object([("error", Value::from(error.class()))]),
        Err(channels::Raised::Send(failure)) => failure_value(&failure),
    };
    let trips = Value::Array(
        probe
            .trips
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone(),
    );
    probe.state.close();
    let _ = untag;
    Ok(object([
        ("answer", answer),
        ("requests", opener.seen()),
        ("secrets", secrets_dump(&backend)),
        ("trips", trips),
    ]))
}

// ------------------------------------------------------------------------------------------ the loopback server
/// [home, now, states, token or null, rows, lan, raw requests (byte lists), page bytes] -> each answer's bytes, the
/// Date header's value replaced by "DATE", and the acts the layer was asked.
pub fn api_serve(args: &[Value]) -> Out {
    use std::io::{Read as _, Write as _};
    let probe = Arc::new(probe(arg(args, 0)?, float(arg(args, 1)?)?, arg(args, 2)?)?);
    let backend: Arc<Memory> = Arc::new(Memory::default());
    if let Value::Str(token) = arg(args, 3)? {
        backend
            .write(
                "CodexAutoResume/advanced/local_api/token",
                token.as_str().unwrap_or(""),
            )
            .map_err(|_| Failure::new("SecretError"))?;
    }
    let layer = Arc::new(FakeLayer::new(list(arg(args, 4)?)?.clone()));
    let page = bytes(arg(args, 7)?)?;
    let clock = probe.clock.clone();
    let service = api::Service {
        runtime: probe.clone() as car_adv::courier::main::SharedRuntime,
        port: 0,
        lan: matches!(arg(args, 5)?, Value::Bool(true)),
        layer: layer.clone(),
        backend: backend.clone() as Arc<dyn Backend>,
        clock: Arc::new(move || {
            *clock
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }),
        page: Arc::new(move || Ok(page.clone())),
    };
    let mut running =
        api::start_on(service, api::LOOPBACK, 0).map_err(|_| Failure::new("OSError"))?;
    let port = running.port;
    let mut answers = Vec::new();
    for raw in list(arg(args, 6)?)? {
        let raw = bytes(raw)?;
        let raw = String::from_utf8_lossy(&raw)
            .replace("{port}", &port.to_string())
            .into_bytes();
        let mut stream = std::net::TcpStream::connect(("127.0.0.1", port as u16))
            .map_err(|_| Failure::new("OSError"))?;
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(15)))
            .map_err(|_| Failure::new("OSError"))?;
        let _ = stream.write_all(&raw);
        let _ = stream.shutdown(std::net::Shutdown::Write);
        let mut got = Vec::new();
        let _ = stream.read_to_end(&mut got);
        answers.push(Value::from(masked(&got, port)));
    }
    use car_adv::courier::resident::Served as _;
    running.close();
    let asked = layer
        .asked
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone();
    probe.state.close();
    Ok(object([
        ("answers", Value::Array(answers)),
        ("asked", Value::Array(asked)),
    ]))
}

/// The answer as text (latin-1), its Date header's value replaced and the port written as `{port}`.
fn masked(raw: &[u8], port: i64) -> String {
    let text: String = raw.iter().map(|b| *b as char).collect();
    let mut out = Vec::new();
    for line in text.split("\r\n") {
        if line.starts_with("Date: ") {
            out.push("Date: DATE".to_owned());
        } else {
            out.push(line.replace(&format!(":{port}"), ":{port}"));
        }
    }
    out.join("\r\n")
}

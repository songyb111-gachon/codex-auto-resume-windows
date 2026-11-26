//! `codex/headless`'s ops (seat adv72d): `hl.case` (a `HeadlessRun` over a scripted session stand-in, its own
//! `Follower` on a counting clock, each resume followed to its end; every call, look and clock reading logged in the
//! reference fake's words) and `hl.pure` (the allow-list and the readers of Codex's answers).

use std::sync::{Arc, Mutex, PoisonError};

use car_adv::codex::headless::{self, AppLook, Follower, HeadlessRun};
use car_adv::codex::session::{Channel, SessionError};
use car_adv::jsonx::object;
use car_machine::json::{Map, Value};

use crate::{Context, Failure, Out, arg, bad, text};

type Log = Arc<Mutex<Vec<Value>>>;

fn push(log: &Log, entry: Vec<Value>) {
    log.lock()
        .unwrap_or_else(PoisonError::into_inner)
        .push(Value::Array(entry));
}

/// Per kind, answers taken in order (the last repeated).
#[derive(Clone, Default)]
struct Answers(Arc<Mutex<std::collections::BTreeMap<String, Vec<Value>>>>);

impl Answers {
    fn new(spec: &Value) -> Answers {
        let mut found = std::collections::BTreeMap::new();
        if let Value::Object(map) = spec {
            for (key, value) in map.iter() {
                if let Value::Array(list) = value {
                    found.insert(key.as_str().unwrap_or("").to_owned(), list.clone());
                }
            }
        }
        Answers(Arc::new(Mutex::new(found)))
    }

    fn take(&self, kind: &str, default: Value) -> Value {
        let mut held = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        match held.get_mut(kind) {
            None => default,
            Some(list) if list.is_empty() => default,
            Some(list) if list.len() > 1 => list.remove(0),
            Some(list) => list[0].clone(),
        }
    }
}

fn field<'a>(spec: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match spec {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn is_raise(value: &Value) -> bool {
    matches!(value, Value::Str(word) if word.as_str() == Some("raise"))
}

fn raised(marker: &Map, method: &str) -> SessionError {
    let kind = marker.get("raise").and_then(|kind| match kind {
        Value::Str(word) => word.as_str(),
        _ => None,
    });
    match kind {
        Some("SessionRefused") => SessionError::Refused,
        Some("RefusedByCodex") => SessionError::ByCodex {
            method: match marker.get("method") {
                Some(Value::Str(word)) => word.as_str().unwrap_or("").to_owned(),
                _ => method.to_owned(),
            },
            code: match marker.get("code") {
                Some(Value::Int(code)) => code.as_i64(),
                _ => None,
            },
        },
        Some("protocol_timeout") => SessionError::Adapter("protocol_timeout"),
        _ => SessionError::Raised("RuntimeError"),
    }
}

struct Fake {
    log: Log,
    answers: Answers,
    events: Arc<Mutex<Vec<Value>>>,
    follower: Arc<Follower>,
    enter_raises: bool,
}

impl Channel for Fake {
    fn enter(&mut self) -> Result<(), SessionError> {
        push(&self.log, vec!["enter".into()]);
        if self.enter_raises {
            return Err(SessionError::Raised("RuntimeError"));
        }
        Ok(())
    }
    fn submit(&mut self, _: &str, _: Option<Value>) -> Result<i64, SessionError> {
        Err(SessionError::Raised("AttributeError"))
    }
    fn receive(&mut self, _: &str, _: i64, _: Option<&Value>) -> Result<Value, SessionError> {
        Err(SessionError::Raised("AttributeError"))
    }
    fn call(&mut self, method: &str, params: Option<Value>) -> Result<Value, SessionError> {
        push(
            &self.log,
            vec!["call".into(), method.into(), params.unwrap_or(Value::Null)],
        );
        let found = self.answers.take(method, Value::Object(Map::new()));
        if let Value::Object(marker) = &found
            && marker.contains_key("raise")
        {
            return Err(raised(marker, method));
        }
        Ok(found)
    }
    fn drain_events(&mut self) -> Vec<Value> {
        push(&self.log, vec!["drain".into()]);
        let entry = {
            let mut events = self.events.lock().unwrap_or_else(PoisonError::into_inner);
            if events.is_empty() {
                Value::Array(Vec::new())
            } else {
                events.remove(0)
            }
        };
        if let Value::Object(map) = &entry
            && let Some(Value::Array(stop)) = map.get("stop")
        {
            let key = stop.first().cloned().unwrap_or(Value::Null);
            let reason = match stop.get(1) {
                Some(Value::Str(word)) => {
                    car_adv::vocabulary::RunEnd::parse(word.as_str().unwrap_or(""))
                        .unwrap_or(car_adv::vocabulary::RunEnd::Interrupted)
                }
                _ => car_adv::vocabulary::RunEnd::Interrupted,
            };
            let key = (!matches!(key, Value::Null)).then_some(key);
            let stopped = self.follower.stop(key.as_ref(), reason);
            push(&self.log, vec!["stopped".into(), Value::Bool(stopped)]);
            return Vec::new();
        }
        match entry {
            Value::Array(list) => list,
            _ => Vec::new(),
        }
    }
    fn exit(&mut self) {
        push(&self.log, vec!["exit".into()]);
    }
}

/// A logged look: Ok(the answer) or Err where the script says "raise".
fn look(log: &Log, looks: &Answers, kind: &str, arguments: Vec<Value>) -> Result<Value, ()> {
    let mut entry = vec![Value::from(kind)];
    entry.extend(arguments);
    push(log, entry);
    let found = looks.take(kind, Value::Bool(true));
    if is_raise(&found) { Err(()) } else { Ok(found) }
}

fn list_or(spec: &Value, key: &str, default: Value) -> Value {
    match field(spec, key) {
        Value::Array(list) if !list.is_empty() => Value::Array(list.clone()),
        _ => Value::Array(vec![default]),
    }
}

fn ends(found: Vec<headless::Ended>) -> Value {
    Value::Array(
        found
            .into_iter()
            .map(|end| {
                object([
                    ("key", end.key),
                    ("capability", end.capability.as_str().into()),
                    ("end", end.end.as_str().into()),
                    (
                        "model_restored",
                        end.model_restored.map_or(Value::Null, Value::Bool),
                    ),
                ])
            })
            .collect(),
    )
}

fn case(spec: &Value) -> Out {
    let log: Log = Arc::default();
    let start = match field(spec, "clock0") {
        Value::Null => 100.0,
        other => crate::float(other)?,
    };
    let step = match field(spec, "tick") {
        Value::Null => 1.0,
        other => crate::float(other)?,
    };
    let tick = Arc::new(Mutex::new(start));
    let clock_log = Arc::clone(&log);
    let follower = Follower::new(
        Arc::new(move || {
            let mut held = tick.lock().unwrap_or_else(PoisonError::into_inner);
            *held += step;
            push(&clock_log, vec!["clock".into()]);
            *held
        }),
        0.0,
    );
    let answers = Answers::new(field(spec, "session"));
    let events = Arc::new(Mutex::new(match field(spec, "events") {
        Value::Array(list) => list.clone(),
        _ => Vec::new(),
    }));
    let mut looks_spec = Map::new();
    looks_spec.insert("app".into(), list_or(spec, "app", Value::Bool(false)));
    looks_spec.insert("owe".into(), list_or(spec, "owe", Value::Bool(true)));
    looks_spec.insert("still".into(), list_or(spec, "still", Value::Bool(true)));
    looks_spec.insert("guard".into(), list_or(spec, "guard", Value::Bool(true)));
    looks_spec.insert(
        "guard_exit".into(),
        list_or(spec, "guard_exit", "ok".into()),
    );
    let looks = Answers::new(&Value::Object(looks_spec));

    let (open_log, open_answers, open_events, open_follower) = (
        Arc::clone(&log),
        answers.clone(),
        Arc::clone(&events),
        Arc::clone(&follower),
    );
    let open_raises = is_raise(field(spec, "open"));
    let enter_raises = is_raise(field(spec, "enter"));
    let opener: headless::Opener = Box::new(move |capability: &str| {
        push(&open_log, vec!["open".into(), capability.into()]);
        if open_raises {
            return Err(());
        }
        Ok(Box::new(Fake {
            log: Arc::clone(&open_log),
            answers: open_answers.clone(),
            events: Arc::clone(&open_events),
            follower: Arc::clone(&open_follower),
            enter_raises,
        }) as Box<dyn Channel>)
    });
    let capability = match field(spec, "capability") {
        Value::Null => "headless_run".to_owned(),
        other => text(other)?,
    };
    let key = match field(spec, "key") {
        Value::Null => Value::from("k1"),
        other => other.clone(),
    };
    let mut run = HeadlessRun::new(&capability, key, opener, Arc::clone(&follower));
    run.seconds = match field(spec, "seconds") {
        Value::Null => 8.0,
        other => crate::float(other)?,
    };
    run.mode = match field(spec, "mode") {
        Value::Str(word) if word.as_str() == Some("compact") => headless::COMPACT,
        Value::Str(word) if word.as_str() == Some("fallback") => headless::FALLBACK,
        _ => headless::TURN,
    };
    if pyval_truthy(field(spec, "app")) {
        let (app_log, app_looks) = (Arc::clone(&log), looks.clone());
        run.app_running = Some(Box::new(move || {
            let (inner_log, inner_looks) = (Arc::clone(&app_log), app_looks.clone());
            Box::new(move || look(&inner_log, &inner_looks, "app", Vec::new())) as AppLook
        }));
    }
    if pyval_truthy(field(spec, "owe")) {
        let (owe_log, owe_looks) = (Arc::clone(&log), looks.clone());
        run.owe = Some(Box::new(
            move |thread: &Value, model: &str, seconds: f64| {
                look(
                    &owe_log,
                    &owe_looks,
                    "owe",
                    vec![thread.clone(), model.into(), seconds.into()],
                )
            },
        ));
    }
    let Value::Array(resumes) = field(spec, "resumes") else {
        return Err(bad());
    };
    let mut out = Vec::new();
    for step in resumes {
        let mut guard = {
            let (guard_log, guard_looks) = (Arc::clone(&log), looks.clone());
            move || -> Result<Value, ()> {
                let entered = look(&guard_log, &guard_looks, "guard", Vec::new())?;
                let left = look(&guard_log, &guard_looks, "guard_exit", Vec::new())?;
                if is_raise(&left) {
                    return Err(());
                }
                Ok(entered)
            }
        };
        let mut still = {
            let (still_log, still_looks) = (Arc::clone(&log), looks.clone());
            move || look(&still_log, &still_looks, "still", Vec::new())
        };
        let answer = run.resume(
            field(step, "thread"),
            pyval_truthy(field(step, "guard"))
                .then_some(&mut guard as &mut dyn FnMut() -> Result<Value, ()>),
            pyval_truthy(field(step, "still"))
                .then_some(&mut still as &mut dyn FnMut() -> Result<Value, ()>),
            field(step, "words"),
            field(step, "client_id"),
        );
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        while follower.live().is_some() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
        out.push(object([
            ("answer", Value::Object(answer)),
            (
                "refused",
                run.refused.map_or(Value::Null, |end| end.as_str().into()),
            ),
            ("on_default", run.on_default.clone().unwrap_or(Value::Null)),
            (
                "model",
                run.model.as_deref().map_or(Value::Null, Value::from),
            ),
            ("live", Value::Bool(follower.live().is_some())),
            ("ends", ends(follower.drain(&run.capability))),
            ("others", ends(follower.drain("other"))),
            (
                "empty_refused",
                Value::Bool(headless::EMPTY_REFUSED.load(std::sync::atomic::Ordering::SeqCst)),
            ),
        ]));
    }
    let log = log.lock().unwrap_or_else(PoisonError::into_inner).clone();
    Ok(object([
        ("steps", Value::Array(out)),
        ("log", Value::Array(log)),
    ]))
}

fn pyval_truthy(value: &Value) -> bool {
    car_machine::pyval::truthy(value)
}

fn opt(value: Option<String>) -> Value {
    value.map_or(Value::Null, Value::from)
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "hl.case" => case(arg(args, 0)),
        "hl.pure" => {
            let value = arg(args, 1);
            match text(arg(args, 0))?.as_str() {
                "settings_allowed" => headless::settings_allowed(value)
                    .map(Value::Bool)
                    .map_err(Failure::new),
                "model" => Ok(opt(headless::model_of(value))),
                "default_model" => Ok(opt(headless::default_model(value))),
                "turn_id" => Ok(opt(headless::turn_id_of(value))),
                "completed" => {
                    let Value::Array(parts) = value else {
                        return Err(bad());
                    };
                    let events = match arg(parts, 0) {
                        Value::Array(list) => list.clone(),
                        _ => return Err(Failure::new("TypeError")),
                    };
                    let turn = match arg(parts, 2) {
                        Value::Null => None,
                        other => Some(other),
                    };
                    Ok(headless::completed(&events, arg(parts, 1), turn)
                        .map_or(Value::Null, Value::from))
                }
                _ => Err(bad()),
            }
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}

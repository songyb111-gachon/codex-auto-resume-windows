//! gh's ops (`github.*`): the pure functions, `find_gh`, and `github.run` - a program of `inspect` and `publish` steps
//! run over a runner that answers a recorded script and writes down every call it is made.
//!
//! The runner never starts a process: the reference recorded what the tag's `FakeGh` (advanced/tests/ghfake.py) answered
//! to each call, in order, and this answers them in the same order. Every call this side makes is kept in the answer, so
//! a call that differs - an argument, the environment, the standard input, the timeout, the flags - is the first
//! difference the diff names.

use std::sync::{Arc, Condvar, Mutex};

use car_adv::jsonx::object;
use car_adv::report::github::{
    self, Answer, Call, GhError, Inspected, Ready, RunError, Runner, blob_sha,
};
use car_codex::system::PolicyOs;
use car_machine::json::{Map, Options, Str, Value, to_string};

use crate::util::{Failure, Out, arg, list, map, maybe_text, number, text};

/// A recorded step: the call the reference made and what it was answered.
struct Step {
    answer: Result<Answer, RunError>,
}

/// A gate the first call waits at until the program releases it (the tests' way of holding a job in the middle of its
/// work: one check or send at a time).
pub type Gate = Arc<(Mutex<bool>, Condvar)>;

pub struct Scripted {
    steps: Vec<Step>,
    next: Mutex<usize>,
    pub calls: Mutex<Vec<Value>>,
    gate: Option<Gate>,
}

impl Scripted {
    pub fn new(script: &Value, gate: Option<Gate>) -> Result<Scripted, Failure> {
        Ok(Scripted {
            steps: script_of(script)?,
            next: Mutex::new(0),
            calls: Mutex::new(Vec::new()),
            gate,
        })
    }
}

/// `gate.set()`.
pub fn release(gate: &Gate) {
    *gate
        .0
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = true;
    gate.1.notify_all();
}

fn digest(env: &[(String, String)]) -> String {
    let mut sorted: Vec<&(String, String)> = env.iter().collect();
    sorted.sort();
    let pairs = Value::Array(
        sorted
            .into_iter()
            .map(|(name, value)| {
                Value::Array(vec![
                    Value::from(name.as_str()),
                    Value::from(value.as_str()),
                ])
            })
            .collect(),
    );
    let text = to_string(&pairs, &Options::new()).unwrap_or_default();
    car_machine::hash::hex(&car_machine::hash::sha256(text.as_bytes()))
}

pub fn call_value(call: &Call) -> Value {
    object([
        (
            "argv",
            Value::Array(
                call.argv
                    .iter()
                    .map(|each| Value::from(each.as_str()))
                    .collect(),
            ),
        ),
        ("env", Value::from(digest(&call.env))),
        ("cwd", Value::from(call.cwd.as_str())),
        (
            "stdin",
            call.stdin.as_ref().map_or(Value::Null, |bytes| {
                Value::from(String::from_utf8_lossy(bytes).into_owned())
            }),
        ),
        ("timeout", Value::from(call.timeout as i64)),
        ("flags", Value::from(i64::from(call.flags))),
    ])
}

impl Runner for Scripted {
    fn run(&self, call: &Call) -> Result<Answer, RunError> {
        self.calls
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(call_value(call));
        if let Some(gate) = &self.gate {
            let held = gate
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let _ = gate
                .1
                .wait_timeout_while(held, std::time::Duration::from_secs(60), |open| !*open);
        }
        let mut next = self
            .next
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let at = *next;
        *next += 1;
        match self.steps.get(at) {
            Some(step) => step.answer.clone(),
            None => Err(RunError::Raised("ScriptExhausted".to_owned())),
        }
    }
}

fn script_of(value: &Value) -> Result<Vec<Step>, Failure> {
    let mut steps = Vec::new();
    for entry in list(value)? {
        let entry = map(entry)?;
        let answer = match entry.get("answer") {
            Some(Value::Array(parts)) => {
                let code = number(arg(parts, 0)?)?;
                Ok((
                    code,
                    text(arg(parts, 1)?)?.to_owned(),
                    text(arg(parts, 2)?)?.to_owned(),
                ))
            }
            Some(Value::Object(raise)) => Err(match raise.get("raise") {
                Some(Value::Str(class)) => match class.as_str() {
                    Some("GhTimeout") => RunError::Timeout,
                    Some("OSError") => RunError::Failed("OSError"),
                    Some("ValueError") => RunError::Failed("ValueError"),
                    Some("SubprocessError") => RunError::Failed("SubprocessError"),
                    Some(other) => RunError::Raised(other.to_owned()),
                    None => RunError::Raised("Exception".to_owned()),
                },
                _ => RunError::Raised("Exception".to_owned()),
            }),
            _ => return Err(Failure::new("BadArgument")),
        };
        steps.push(Step { answer });
    }
    Ok(steps)
}

fn failure_value(error: &GhError) -> Map {
    let mut found = Map::new();
    match error {
        GhError::Refused(code) => {
            found.insert(Str::from("error"), Value::from("ReportRefused"));
            found.insert(Str::from("code"), Value::from(code.as_str()));
        }
        GhError::Stopped(code) => {
            found.insert(Str::from("error"), Value::from("Stopped"));
            found.insert(Str::from("code"), Value::from(code.as_str()));
        }
        GhError::Raised(class) => {
            found.insert(Str::from("error"), Value::from(class.as_str()));
        }
    }
    found
}

fn ready_value(ready: &Ready) -> Value {
    object([
        ("exe", Value::from(ready.exe.as_str())),
        ("who", Value::from(ready.who.as_str())),
        ("login", Value::from(ready.login.as_str())),
        ("fork", Value::from(ready.fork.as_str())),
        ("branch", Value::from(ready.branch.as_str())),
        ("target", Value::from(ready.target.as_str())),
        ("base", Value::from(ready.base.as_str())),
        ("has_fork", Value::Bool(ready.has_fork)),
        ("has_branch", Value::Bool(ready.has_branch)),
        ("cwd", Value::from(ready.cwd.as_str())),
        ("written", Value::Array(ready.written.clone())),
        ("writes", Value::Array(ready.writes())),
    ])
}

/// `["inspect", raw, report, login, exe, cwd]` and `["publish", {"stop": {"after": n, "with": word} | null}]`.
fn program(
    steps: &[Value],
    runner: &Scripted,
    sleeps: &Mutex<Vec<f64>>,
) -> Result<Vec<Value>, Failure> {
    let mut out = Vec::new();
    let mut found: Option<Ready> = None;
    let mut inspected: Option<(String, Value, String)> = None;
    for step in steps {
        let parts = list(step)?;
        match text(arg(parts, 0)?)? {
            "inspect" => {
                let raw = text(arg(parts, 1)?)?.to_owned();
                let report = arg(parts, 2)?.clone();
                let login = text(arg(parts, 3)?)?.to_owned();
                let exe = maybe_text(arg(parts, 4)?)?;
                let cwd = text(arg(parts, 5)?)?;
                found = None;
                out.push(
                    match github::inspect(raw.as_bytes(), &report, &login, exe, cwd, runner) {
                        Ok(Inspected::Ready(ready)) => {
                            let shown = object([("ready", ready_value(&ready))]);
                            found = Some(ready);
                            inspected = Some((raw, report, login));
                            shown
                        }
                        Ok(Inspected::Web(web)) => object([(
                            "web",
                            object([
                                ("why", Value::from(web.why.as_str())),
                                ("who", web.who.as_deref().map_or(Value::Null, Value::from)),
                            ]),
                        )]),
                        Ok(Inspected::Sent(sent)) => object([("sent", Value::from(sent.url))]),
                        Err(error) => Value::Object(failure_value(&error)),
                    },
                );
            }
            "publish" => {
                let options = match parts.get(1) {
                    Some(Value::Object(options)) => options.clone(),
                    _ => Map::new(),
                };
                let (Some(ready), Some((raw, report, _))) = (found.as_mut(), inspected.as_ref())
                else {
                    out.push(object([(
                        "skipped",
                        Value::from("inspect found nothing to publish"),
                    )]));
                    continue;
                };
                let stop = match options.get("stop") {
                    Some(Value::Object(stop)) => Some(stop.clone()),
                    _ => None,
                };
                let mut asked = 0usize;
                let mut before = || -> Result<(), GhError> {
                    asked += 1;
                    if let Some(stop) = &stop {
                        let after = stop
                            .get("after")
                            .map_or(0, |each| number(each).unwrap_or(0));
                        // The tag's tests raise once `found.written` holds `after` writes; `written` is not visible
                        // from here, so the case counts the asks: the n-th ask follows n-1 writes.
                        if asked as i64 > after {
                            return Err(match stop.get("with") {
                                Some(Value::Str(word)) if word.as_str() == Some("stopped") => {
                                    GhError::Stopped("paused".to_owned())
                                }
                                Some(Value::Str(word)) if word.as_str() == Some("error") => {
                                    GhError::Raised("RuntimeError".to_owned())
                                }
                                _ => GhError::Refused(car_adv::vocabulary::ReportRefusal::NotOn),
                            });
                        }
                    }
                    Ok(())
                };
                let pause = |seconds: f64| {
                    sleeps
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner)
                        .push(seconds);
                };
                let done =
                    github::publish(ready, raw.as_bytes(), report, &mut before, runner, &pause);
                let written = Value::Array(ready.written.clone());
                out.push(match done {
                    Ok(url) => object([("url", Value::from(url)), ("written", written)]),
                    Err(error) => {
                        let mut shown = failure_value(&error);
                        shown.insert(Str::from("written"), written);
                        Value::Object(shown)
                    }
                });
            }
            "fake" => {}
            _ => return Err(Failure::new("BadArgument")),
        }
    }
    Ok(out)
}

pub fn run(op: &str, args: &[Value]) -> Out {
    match op {
        "github.run" => {
            let steps = list(arg(args, 0)?)?;
            let runner = Scripted::new(arg(args, 1)?, None)?;
            let sleeps = Mutex::new(Vec::new());
            let results = program(steps, &runner, &sleeps)?;
            let calls = runner
                .calls
                .into_inner()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let slept = sleeps
                .into_inner()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            Ok(object([
                ("steps", Value::Array(results)),
                ("calls", Value::Array(calls)),
                (
                    "sleeps",
                    Value::Array(slept.into_iter().map(Value::Float).collect()),
                ),
            ]))
        }
        "github.blob_sha" => Ok(Value::from(blob_sha(text(arg(args, 0)?)?.as_bytes()))),
        "github.destination" => match github::destination(arg(args, 0)?, arg(args, 1)?) {
            Ok((path, branch)) => Ok(Value::Array(vec![Value::from(path), Value::from(branch)])),
            Err(GhError::Raised(class)) => Err(Failure::new(&class)),
            Err(other) => Err(Failure::new(&format!("{other:?}"))),
        },
        "github.spelling" => Ok(github::spelling(text(arg(args, 0)?)?, text(arg(args, 1)?)?)
            .map_or(Value::Null, Value::from)),
        "github.title" => Ok(Value::from(github::title(
            arg(args, 0)?,
            text(arg(args, 1)?)?,
        ))),
        "github.body" => Ok(Value::from(github::body(text(arg(args, 0)?)?))),
        "github.base64" => Ok(Value::from(github::base64(text(arg(args, 0)?)?.as_bytes()))),
        "github.environment" => Ok(Value::Object({
            let mut found = Map::new();
            for (name, value) in github::environment() {
                found.insert(Str::from(name.as_str()), Value::from(value));
            }
            found
        })),
        "github.find_gh" => {
            let path = maybe_text(arg(args, 0)?)?;
            let places: Vec<String> = list(arg(args, 1)?)?
                .iter()
                .map(|each| text(each).map(str::to_owned))
                .collect::<Result<_, _>>()?;
            let cwd = text(arg(args, 2)?)?;
            Ok(github::find_gh(&PolicyOs, path, &places, cwd).map_or(Value::Null, Value::from))
        }
        "github.pull" => {
            let whole = matches!(arg(args, 1)?, Value::Bool(true));
            Ok(github::pull_in(text(arg(args, 0)?)?, whole).map_or(Value::Null, Value::from))
        }
        _ => Err(Failure::new("UnknownOp")),
    }
}

//! `an.pure`: window_anchor's pure functions (the local clock the C runtime's, as the reference's `time.localtime`);
//! `an`: its capability over scripted sessions, request processes, a told pair and the watcher's log.

use car_adv::engine::anchor;
use car_machine::json::{Map, Value};
use car_platform::localclock::Crt;

use std::sync::{Arc, Mutex};

use car_adv::capabilities::Raised;
use car_adv::engine::anchor::{RequestBackend, UsageSession, WindowAnchor};
use car_policy::plug::Errand;

use crate::common::{Case, Script, error, f64_of, get, list, lock, object, text};
use crate::wake_ops::{StandView, shown_tick};

fn int_or_null(found: Option<i64>) -> Value {
    found.map_or(Value::Null, |n| Value::Int(n.into()))
}

/// What `printed` was handed as: a text, or `{"hex": bytes}` decoded as the reference decodes bytes ("replace").
fn printed(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let hex = text(get(map, "hex"));
            let bytes: Vec<u8> = (0..hex.len() / 2)
                .filter_map(|i| u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).ok())
                .collect();
            String::from_utf8_lossy(&bytes).into_owned()
        }
        other => text(other),
    }
}

fn pure(name: &str, arguments: &[Value]) -> Result<Value, String> {
    let at = |index: usize| arguments.get(index).cloned().unwrap_or(Value::Null);
    let now = |index: usize| f64_of(&at(index)).ok_or_else(|| "TypeError".to_owned());
    let fail = |class: &str| class.to_owned();
    Ok(match name {
        "encode_time" => int_or_null(anchor::encode_time(&at(0), &at(1))),
        "decode_time" => int_or_null(anchor::decode_time(&at(0))),
        "clock_text" => Value::Str(anchor::clock_text(&at(0)).as_str().into()),
        "picked" => Value::Array(
            anchor::picked(&at(0))
                .into_iter()
                .map(|n| Value::Int(n.into()))
                .collect(),
        ),
        "after_reset_on" => Value::Bool(anchor::after_reset_on(&at(0))),
        "midnight" => Value::Int(anchor::midnight(now(0)?, &Crt).map_err(fail)?.into()),
        "occurrence" => {
            let days = car_adv::state::py::small(&at(1)).unwrap_or(0);
            let minute = car_adv::state::py::small(&at(2)).unwrap_or(0);
            Value::Int(
                anchor::occurrence(now(0)?, days, minute, &Crt)
                    .map_err(fail)?
                    .into(),
            )
        }
        "slot_due" => int_or_null(anchor::slot_due(&at(0), now(1)?, &at(2), &Crt).map_err(fail)?),
        "reset_due" => {
            int_or_null(anchor::reset_due(&at(0), now(1)?, &at(2), &at(3)).map_err(fail)?)
        }
        "next_due" => int_or_null(
            anchor::next_due(&at(0), now(1)?, &at(2), &at(3), &at(4), &Crt).map_err(fail)?,
        ),
        "windows_of" => {
            let (five, weekly) = anchor::windows_of(&at(0)).map_err(fail)?;
            Value::Array(vec![
                five.unwrap_or(Value::Null),
                weekly.unwrap_or(Value::Null),
            ])
        }
        "running_reset" => int_or_null(anchor::running_reset(&at(0), now(1)?).map_err(fail)?),
        "judge" => Value::Str(anchor::judge(&at(0), &at(1)).map_err(fail)?.into()),
        "signed_in" => anchor::signed_in(&at(0)).map_or(Value::Null, Value::Bool),
        "tokens_of" => {
            let [input, cached, output] = anchor::tokens_of(&printed(&at(0)));
            object(vec![
                ("input", int_or_null(input)),
                ("cached", int_or_null(cached)),
                ("output", int_or_null(output)),
            ])
        }
        "thread_started" => Value::Bool(anchor::thread_started(&printed(&at(0)))),
        "refused" => Value::Bool(anchor::refused(&printed(&at(0)))),
        "toml_key" => Value::Str(anchor::toml_key(&at(0)).as_str().into()),
        "servers_off" => anchor::servers_off(&list(&at(0)))
            .map_or(Value::Null, |text| Value::Str(text.as_str().into())),
        "tokens_said" => Value::Str(anchor::tokens_said(&at(0)).as_str().into()),
        "hhmm" => Value::Str(anchor::hhmm(now(0)?, &Crt).map_err(fail)?.as_str().into()),
        other => return Err(format!("unknown function {other}")),
    })
}

pub fn answer(op: &str, case: &Map) -> Option<Result<Value, String>> {
    match op {
        "an.pure" => Some(pure(
            &text(get(case, "name")),
            &list(get(case, "arguments")),
        )),
        "an.toml" => {
            let home = std::path::Path::new(&text(get(case, "home"))).join("codex");
            let home = home.to_string_lossy().into_owned();
            Some(Ok(object(vec![
                (
                    "servers",
                    Value::Array(
                        anchor::declared_servers(&home)
                            .iter()
                            .map(|name| Value::Str(name.as_str().into()))
                            .collect(),
                    ),
                ),
                ("unreadable", Value::Bool(anchor::config_unreadable(&home))),
            ])))
        }
        "an" => Some(Ok(capability(case))),
        "an.view" => Some(Ok(view(case))),
        _ => None,
    }
}

struct StandSession(Arc<Script>);

impl UsageSession for StandSession {
    fn call(&mut self, method: &str, _params: &Value) -> Result<Value, Raised> {
        self.0
            .answer(&format!("call:{method}"), Value::Null, vec![])
    }
}

struct StandBackend {
    python: String,
    child: String,
    home: std::path::PathBuf,
    code: String,
}

impl RequestBackend for StandBackend {
    fn argv(&self) -> Vec<String> {
        vec![self.python.clone(), "-c".into(), self.child.clone()]
    }
    fn environment(&self) -> Vec<(std::ffi::OsString, std::ffi::OsString)> {
        let mut found: Vec<(std::ffi::OsString, std::ffi::OsString)> = std::env::vars_os()
            .filter(|(name, _)| {
                let name = name.to_string_lossy().to_uppercase();
                ![
                    "CODEX_HOME",
                    "ADVTIME_ARGV",
                    "ADVTIME_OUT",
                    "ADVTIME_ERR",
                    "ADVTIME_CODE",
                ]
                .contains(&name.as_str())
            })
            .collect();
        let path = |name: &str| self.home.join(name).into_os_string();
        found.push(("CODEX_HOME".into(), path("codex")));
        found.push(("ADVTIME_ARGV".into(), path("argv.txt")));
        found.push(("ADVTIME_OUT".into(), path("out.txt")));
        found.push(("ADVTIME_ERR".into(), path("err.txt")));
        found.push(("ADVTIME_CODE".into(), self.code.clone().into()));
        found
    }
}

fn capability(case: &Map) -> Value {
    let made = Case::new(case);
    let home = std::path::PathBuf::from(text(get(case, "home")));
    let script = Arc::new(Script::new(get(case, "script"), made.log.clone()));
    let permits = Mutex::new(match get(case, "permitted") {
        Value::Array(items) if !items.is_empty() => items.clone(),
        _ => vec![Value::Bool(true)],
    });
    let session_log = made.log.clone();
    let session_raise = matches!(get(case, "session_raise"), Value::Bool(true));
    let sessions = script.clone();
    let backend_log = made.log.clone();
    let backend_raise = matches!(get(case, "backend_raise"), Value::Bool(true));
    let python = text(get(case, "python"));
    let child = text(get(case, "child"));
    let code = match get(case, "code") {
        Value::Int(number) => number.to_string(),
        _ => "0".to_owned(),
    };
    let backend_home = home.clone();
    let begin_log = made.log.clone();
    let begin_runs = !matches!(get(case, "begin_runs"), Value::Bool(false));
    let told_home = home.join("codex").to_string_lossy().into_owned();
    let told = !matches!(get(case, "told"), Value::Bool(false));
    let line_log = made.log.clone();
    let anchor_code = WindowAnchor::new(
        made.paths.clone(),
        Some(Box::new(move || {
            lock(&session_log).push(Value::Array(vec![Value::Str("session".into())]));
            if session_raise {
                return Err(Raised::new("RuntimeError"));
            }
            Ok(Box::new(StandSession(sessions.clone())) as Box<dyn UsageSession>)
        })),
        Box::new(move || told.then(|| ("codex.exe".to_owned(), told_home.clone()))),
        Box::new(move || {
            lock(&backend_log).push(Value::Array(vec![Value::Str("backend".into())]));
            if backend_raise {
                return Err(Raised::new("RuntimeError"));
            }
            Ok(Box::new(StandBackend {
                python: python.clone(),
                child: child.clone(),
                home: backend_home.clone(),
                code: code.clone(),
            }) as Box<dyn RequestBackend>)
        }),
        Box::new(move |target| {
            lock(&begin_log).push(Value::Array(vec![Value::Str("begin".into())]));
            if begin_runs {
                target();
            }
            Ok(())
        }),
        Box::new(move |line: &str| {
            lock(&line_log).push(Value::Array(vec![
                Value::Str("log".into()),
                Value::Str(line.into()),
            ]));
            Ok(())
        }),
        Box::new(Crt),
    );
    if !matches!(get(case, "bind"), Value::Bool(false)) {
        anchor_code.bind_to(made.bound());
    }
    let view = StandView::new(get(case, "view"), made.log.clone());
    let mut answers = Vec::new();
    let mut errand: Option<Box<dyn Errand>> = None;
    for step in list(get(case, "steps")) {
        let step = list(&step);
        if made.common(&step) {
            answers.push(Value::Null);
            continue;
        }
        let answer = match text(step.first().unwrap_or(&Value::Null)).as_str() {
            "tick" => shown_tick(anchor_code.ticked(), &mut errand),
            "run" => match &errand {
                None => Value::Str("none".into()),
                Some(errand) => {
                    let log = made.log.clone();
                    let mut guards = |body: &mut dyn FnMut(bool) -> Value| {
                        let permitted = {
                            let mut held = lock(&permits);
                            if held.len() > 1 {
                                held.remove(0)
                            } else {
                                held[0].clone()
                            }
                        };
                        lock(&log).push(Value::Array(vec![
                            Value::Str("guard".into()),
                            permitted.clone(),
                        ]));
                        Ok(body(matches!(permitted, Value::Bool(true))))
                    };
                    match errand.run(&view, &mut guards) {
                        Ok(value) => value,
                        Err(_) => error(&Raised::new("raised")),
                    }
                }
            },
            other => object(vec![("unknown", Value::Str(other.into()))]),
        };
        answers.push(answer);
    }
    made.close();
    object(vec![
        ("answers", Value::Array(answers)),
        ("log", made.log()),
    ])
}

fn view(case: &Map) -> Value {
    let made = Case::new(case);
    let armed = text(get(case, "state")) == "armed";
    let now = *lock(&made.clock);
    let state = &made.held.state;
    let stamped = |option: car_adv::vocabulary::OptionKey| {
        state
            .stamped(
                &Value::Str(anchor::CAPABILITY.into()),
                &Value::Str(option.as_str().into()),
            )
            .ok()
    };
    let found = anchor::view(armed, &stamped, now);
    made.close();
    found
}

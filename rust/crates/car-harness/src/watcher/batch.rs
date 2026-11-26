//! `watcher.batch`: the watcher's smaller pieces, case by case, over stand-ins the case names (S6.1).
//!
//! * `["sweep", home, installing, running]`: setaside's sweep of a fixture home, the installer's lock and the
//!   running images the case's; (swept, left, the log lines).
//! * `["plug_notices", steps]`: an edition plug's surface answers in turn (`{"$defer": true}` for DEFER); per step
//!   (open_codex, chat, the notices raised).
//! * `["afterwork", state_dir, steps]`: the power action's looks over a store of its own, each step's control,
//!   powerdown and engine answers the step's; per step what was asked, logged and raised, and whether a countdown runs.

use std::cell::RefCell;
use std::path::Path;
use std::rc::Rc;

use car_machine::json::{Map, Value};
use car_policy::settings::managed::Managed;
use car_store::Store;
use car_watcher::afterwork::{Activity, AfterWork, Look, PowerControl, Powerdown};
use car_watcher::fail::Res;

use super::{AsStr, Calls, call, field, number};
use crate::object;

fn ok(value: Value) -> Value {
    object([("ok", value)])
}

fn error(class: &str) -> Value {
    object([("error", Value::from(class))])
}

fn paths_of(home: &str) -> Result<car_config::Paths, &'static str> {
    let no_env = |_: &str| None;
    car_config::Paths::new(
        Some(home),
        home,
        &no_env,
        car_config::Os::here(false, crate::links::for_config()),
    )
}

struct SweepMachine {
    installing: Option<bool>,
    running: Option<Vec<String>>,
}

impl car_watcher::setaside::Machine for SweepMachine {
    fn installing(&self) -> Option<bool> {
        self.installing
    }
    fn running(&self) -> Option<Vec<String>> {
        self.running.clone()
    }
}

fn sweep(args: &[Value]) -> Result<Value, String> {
    let home = args.first().and_then(AsStr::as_str_value).unwrap_or_default();
    let installing = match args.get(1) {
        Some(Value::Bool(flag)) => Some(*flag),
        _ => None,
    };
    let running = match args.get(2) {
        Some(Value::Array(items)) => Some(items.iter().map(car_machine::pytext::py_str).collect()),
        _ => None,
    };
    let paths = paths_of(home).map_err(str::to_owned)?;
    let lines = RefCell::new(Vec::new());
    let log = |line: &str| lines.borrow_mut().push(Value::from(line));
    let (swept, left) =
        car_watcher::setaside::sweep(&paths, Some(&log), &SweepMachine { installing, running });
    Ok(Value::Array(vec![
        Value::from(swept),
        Value::from(left),
        Value::Array(lines.into_inner()),
    ]))
}

fn plug_notices(args: &[Value]) -> Result<Value, String> {
    let mut notices = car_watcher::plugnotices::PlugNotices::new();
    let mut answers = Vec::new();
    let steps = match args.first() {
        Some(Value::Array(steps)) => steps.clone(),
        _ => Vec::new(),
    };
    for step in steps {
        let added = match &step {
            Value::Object(map) if map.get("$defer").is_some() => car_policy::plug::Answer::Defer,
            other => car_policy::plug::Answer::Is(other.clone()),
        };
        let raised = RefCell::new(Vec::new());
        let mut notice = |event: &str, detail: Map| -> Res<()> {
            raised
                .borrow_mut()
                .push(Value::Array(vec![Value::from(event), Value::Object(detail)]));
            Ok(())
        };
        notices
            .edition_notices(&added, &mut notice)
            .map_err(|failed| failed.class)?;
        answers.push(Value::Array(vec![
            Value::Bool(notices.open_codex),
            Value::Bool(notices.chat),
            Value::Array(raised.into_inner()),
        ]));
    }
    Ok(Value::Array(answers))
}

/// One afterwork step, shared by the control, the port and the engine stand-ins.
type Step = Rc<RefCell<Map>>;

fn has(step: &Step, key: &str) -> bool {
    step.borrow().contains_key(key)
}

fn get(step: &Step, key: &str) -> Value {
    step.borrow().get(key).cloned().unwrap_or(Value::Null)
}

struct StepControl(Step, Calls);

impl PowerControl for StepControl {
    fn read_power_action(&self, now: f64) -> Res<(String, Value)> {
        call(&self.1, vec!["read".into(), Value::Float(now)]);
        match get(&self.0, "read") {
            Value::Array(pair) if pair.len() == 2 => Ok((
                pair[0].as_str_value().unwrap_or("missing").to_owned(),
                pair[1].clone(),
            )),
            _ => Ok(("missing".into(), Value::Null)),
        }
    }
    fn power_batch_end(&self, nonce: &Value, result: &str, now: f64) -> Res<bool> {
        call(
            &self.1,
            vec!["batch_end".into(), nonce.clone(), result.into(), Value::Float(now)],
        );
        Ok(!matches!(get(&self.0, "batch_end"), Value::Bool(false)))
    }
    fn power_batch_finish(&self, nonce: &Value, now: f64) -> Res<Option<String>> {
        call(&self.1, vec!["batch_finish".into(), nonce.clone(), Value::Float(now)]);
        if !has(&self.0, "finish") {
            return Ok(Some("done".into()));
        }
        Ok(get(&self.0, "finish").as_str_value().map(str::to_owned))
    }
    fn power_refused(&self, now: f64) -> Res<bool> {
        call(&self.1, vec!["refused".into(), Value::Float(now)]);
        Ok(true)
    }
    fn power_show(&self, nonce: &Value, shown: &Value) -> Res<bool> {
        call(&self.1, vec!["show".into(), nonce.clone(), shown.clone()]);
        Ok(true)
    }
    fn plug_power(&self, facts: &Value) -> Res<Option<Value>> {
        call(&self.1, vec!["plug_power".into(), facts.clone()]);
        Ok(match get(&self.0, "power") {
            Value::Null => None,
            found => Some(found),
        })
    }
}

struct StepPort(Step, Calls);

impl Powerdown for StepPort {
    fn available(&self, action: &Value) -> Res<(bool, Option<String>)> {
        call(&self.1, vec!["available".into(), action.clone()]);
        Ok(match get(&self.0, "available") {
            Value::Bool(false) => (false, Some("no_privilege".into())),
            _ => (true, None),
        })
    }
    fn other_sessions(&self) -> Res<Value> {
        call(&self.1, vec!["others".into()]);
        Ok(if has(&self.0, "others") {
            get(&self.0, "others")
        } else {
            Value::from(0)
        })
    }
    fn idle_seconds(&self) -> Res<Value> {
        call(&self.1, vec!["idle".into()]);
        Ok(if has(&self.0, "idle") {
            get(&self.0, "idle")
        } else {
            Value::Float(600.0)
        })
    }
    fn act(&self, action: &Value) -> Res<Value> {
        call(&self.1, vec!["act".into(), action.clone()]);
        Ok(if has(&self.0, "act") {
            get(&self.0, "act")
        } else {
            Value::Bool(true)
        })
    }
    fn last_error(&self) -> Res<Value> {
        call(&self.1, vec!["last_error".into()]);
        Ok(get(&self.0, "last_error"))
    }
}

struct StepEngine(Step, Calls);

impl Activity for StepEngine {
    fn activity(&mut self, threads: &[String]) -> Res<Value> {
        call(
            &self.1,
            vec![
                "activity".into(),
                Value::Array(threads.iter().map(|t| Value::from(t.as_str())).collect()),
            ],
        );
        if has(&self.0, "activity") {
            return Ok(get(&self.0, "activity"));
        }
        let mut quiet = Map::new();
        quiet.insert("history".into(), Value::Bool(true));
        quiet.insert("running".into(), Value::from(0));
        quiet.insert("queued".into(), Value::from(0));
        Ok(Value::Object(quiet))
    }
    fn follow_option(&self) -> Option<Value> {
        None
    }
}

fn afterwork(args: &[Value]) -> Result<Value, String> {
    let state_dir = args.first().and_then(AsStr::as_str_value).unwrap_or_default();
    let steps = match args.get(1) {
        Some(Value::Array(steps)) => steps.clone(),
        _ => Vec::new(),
    };
    let _ = std::fs::create_dir_all(state_dir);
    let store = Store::open(Path::new(state_dir), crate::links::for_store())
        .map_err(|failed| failed.class().to_owned())?;
    // Recovery on, as a person's state has it: a fresh state is paused, and the power action waits on a pause.
    store
        .set_enabled(true, 1.0)
        .map_err(|failed| failed.class().to_owned())?;
    let current: Step = Rc::default();
    let calls: Calls = Rc::default();
    let now = Rc::new(RefCell::new(0.0_f64));
    let at = Rc::clone(&now);
    let mut work = AfterWork::new(
        Box::new(StepControl(Rc::clone(&current), Rc::clone(&calls))),
        Box::new(StepPort(Rc::clone(&current), Rc::clone(&calls))),
        Box::new(move || *at.borrow()),
    );
    let clock = car_watcher::clock::LogClock::here();
    let mut answers = Vec::new();
    for each in steps {
        let Value::Object(map) = each else {
            continue;
        };
        *now.borrow_mut() = number(field(&map, "now"));
        *current.borrow_mut() = map.clone();
        calls.borrow_mut().clear();
        let lines = RefCell::new(Vec::new());
        let notices = RefCell::new(Vec::new());
        let log = |line: &str| lines.borrow_mut().push(Value::from(line));
        let notice = |event: &str, detail: Map, last: bool| -> Res<()> {
            notices.borrow_mut().push(Value::Array(vec![
                Value::from(event),
                Value::Object(detail),
                Value::Bool(last),
            ]));
            Ok(())
        };
        let op = field(&map, "op").as_str_value().unwrap_or("look").to_owned();
        let managed = Managed {
            disable_power_action: matches!(field(&map, "held"), Value::Bool(true)),
            disable_auto_resume: matches!(field(&map, "paused_by_policy"), Value::Bool(true)),
            ..Managed::default()
        };
        let settings = field(&map, "settings").clone();
        let mut engine = StepEngine(Rc::clone(&current), Rc::clone(&calls));
        let result = match op.as_str() {
            "stop" => {
                work.stop(&log, &clock);
                Ok(())
            }
            "halt" => {
                work.halt(&log, &clock);
                Ok(())
            }
            _ => work.look(Look {
                store: &store,
                engine: if matches!(field(&map, "no_engine"), Value::Bool(true)) {
                    None
                } else {
                    Some(&mut engine)
                },
                ok: !matches!(field(&map, "ok"), Value::Bool(false)),
                waking: None,
                settings: &settings,
                managed: &managed,
                log: &log,
                notice: &notice,
                clock: &clock,
            }),
        };
        answers.push(object([
            (
                "raised",
                result
                    .err()
                    .map_or(Value::Null, |failed| Value::from(failed.class)),
            ),
            ("calls", Value::Array(calls.borrow().clone())),
            ("lines", Value::Array(lines.into_inner())),
            ("notices", Value::Array(notices.into_inner())),
            ("counting", Value::Bool(work.counting())),
            ("cap", Value::Float(work.cap(30.0))),
        ]));
    }
    Ok(Value::Array(answers))
}

/// Each case `[name, args...]`, answered `{"ok": value}` or `{"error": class}`.
pub fn batch(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let mut answers = Vec::with_capacity(cases.len());
    for each in cases {
        let Value::Array(parts) = each else {
            answers.push(error("TypeError"));
            continue;
        };
        let name = parts
            .first()
            .and_then(AsStr::as_str_value)
            .unwrap_or_default()
            .to_owned();
        let args = &parts[1..];
        let found = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| match name.as_str() {
            "sweep" => Some(sweep(args)),
            "plug_notices" => Some(plug_notices(args)),
            "afterwork" => Some(afterwork(args)),
            other => super::check::case(other, args),
        }));
        answers.push(match found {
            Ok(Some(Ok(value))) => ok(value),
            Ok(Some(Err(class))) => error(&class),
            Ok(None) => error(&format!("NotPorted:{name}")),
            Err(_) => error("RustPanic"),
        });
    }
    Value::Array(answers)
}

//! `watcher.launcher` {here, argv, env, script}: car-watcher's launcher logic over a scripted world
//! (`tests/rustdiff/diffs_watcher_launcher.py`): the plug's answers to P13 (through car-policy's own `Guarded`, so
//! an answer is checked as the product checks it), the supervised children's exit codes, the watcher's own code, the
//! stop probe of AFTER_STOP, and a clock of the script's own. `launcher.log`, `errors.log` and `unsupervised.txt` are
//! the real writers' files in the case's folders. Nothing is started.

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::{Arc, Mutex};

use car_machine::json::{Map, Value};
use car_policy::plug::{Alternative, Answer, Guarded, Hook, HookFailed, Plug};
use car_watcher::launcher::{Child, LauncherWorld};

use super::{AsStr, Calls, call, field, list};
use crate::object;

/// A plug answering P13 from the script: `supervise` in turn (a word, "defer", or "raise"), `supervise_held` once.
struct ScriptPlug {
    answers: Mutex<Vec<Value>>,
    held: Value,
    asked: Arc<Mutex<Vec<Value>>>,
}

impl Plug for ScriptPlug {
    fn supervise(&self, facts: &Value) -> Hook<Alternative> {
        self.asked
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(facts.clone());
        let mut answers = self
            .answers
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let word = if answers.is_empty() {
            "defer".to_owned()
        } else {
            answers
                .remove(0)
                .as_str_value()
                .unwrap_or("defer")
                .to_owned()
        };
        match word.as_str() {
            "raise" => Err(HookFailed),
            "defer" => Ok(Answer::Defer),
            other => match Alternative::ALL.iter().find(|each| each.as_str() == other) {
                Some(found) => Ok(Answer::Is(*found)),
                None => Ok(Answer::Defer),
            },
        }
    }
    fn supervise_held(&self) -> Result<Value, HookFailed> {
        Ok(self.held.clone())
    }
}

struct ScriptChild {
    pid: u32,
    code: i32,
}

impl Child for ScriptChild {
    fn pid(&self) -> u32 {
        self.pid
    }
    fn wait(&mut self) -> i32 {
        self.code
    }
}

struct LaunchWorld {
    here: PathBuf,
    env: Vec<(String, String)>,
    script: Map,
    clock: Rc<RefCell<f64>>,
    calls: Calls,
    plug: Option<Guarded>,
    asked: Arc<Mutex<Vec<Value>>>,
    children: Vec<Value>,
    started: u32,
    codes: Vec<Value>,
    probes: Vec<Value>,
}

impl LaunchWorld {
    fn next(list: &mut Vec<Value>, otherwise: Value) -> Value {
        if list.is_empty() {
            otherwise
        } else {
            list.remove(0)
        }
    }
}

impl LauncherWorld for LaunchWorld {
    fn here(&self) -> PathBuf {
        self.here.clone()
    }
    fn pid(&self) -> u32 {
        4242
    }
    fn env(&self, name: &str) -> Option<String> {
        self.env
            .iter()
            .find(|(each, _)| each == name)
            .map(|(_, value)| value.clone())
    }
    fn take_env(&mut self, name: &str) -> Option<String> {
        let at = self.env.iter().position(|(each, _)| each == name)?;
        Some(self.env.remove(at).1)
    }
    fn sleep(&mut self, seconds: f64) {
        call(&self.calls, vec!["sleep".into(), Value::Float(seconds)]);
        *self.clock.borrow_mut() += seconds;
    }
    fn monotonic(&mut self) -> f64 {
        *self.clock.borrow()
    }
    fn stamp(&self) -> String {
        "[0000-00-00 00:00:00] ".into()
    }
    fn usable(&self, root: &Path) -> bool {
        root.join("src").join("auto_resume.py").is_file()
            && root
                .join("src")
                .join("codex_auto_resume")
                .join("cli.py")
                .is_file()
    }
    fn codex_home(&self) -> PathBuf {
        PathBuf::from(
            field(&self.script, "codex_home")
                .as_str_value()
                .unwrap_or_default(),
        )
    }
    fn supervise(&mut self, _home: &Path, facts: &Value) -> Option<String> {
        let plug = self.plug.as_ref()?;
        match plug.supervise(facts) {
            Answer::Is(word) => Some(word.as_str().to_owned()),
            Answer::Defer => None,
        }
    }
    fn plug_is_null(&mut self, _home: &Path) -> bool {
        self.plug.as_ref().is_none_or(Guarded::is_null)
    }
    fn supervise_held(&mut self, _home: &Path) -> Value {
        self.plug
            .as_ref()
            .map_or(Value::Null, Guarded::supervise_held)
    }
    fn ended_cleanly(&mut self, _home: &Path) -> Option<bool> {
        None
    }
    fn probe_available(&mut self, _home: &Path) -> bool {
        !matches!(field(&self.script, "probe"), Value::Str(word) if word.as_str() == Some("unavailable"))
    }
    fn watcher_running(&mut self, _home: &Path) -> Option<bool> {
        call(&self.calls, vec!["probe".into()]);
        match LaunchWorld::next(&mut self.probes, Value::Bool(false)) {
            Value::Bool(flag) => Some(flag),
            _ => None,
        }
    }
    fn run_watcher(&mut self, _home: &Path, command: &[String]) -> i32 {
        call(
            &self.calls,
            vec![
                "watcher".into(),
                Value::Array(
                    command
                        .iter()
                        .map(|each| Value::from(each.as_str()))
                        .collect(),
                ),
            ],
        );
        match LaunchWorld::next(&mut self.codes, Value::from(0)) {
            Value::Int(code) => code.as_i64().unwrap_or(0) as i32,
            _ => 0,
        }
    }
    fn child_program(&self) -> Option<PathBuf> {
        if matches!(field(&self.script, "no_program"), Value::Bool(true)) {
            None
        } else {
            Some(PathBuf::from("CodexAutoResume.exe"))
        }
    }
    fn start_child(&mut self, arguments: &[String]) -> Result<Box<dyn Child>, String> {
        let tail: Vec<Value> = arguments[1..]
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect();
        call(&self.calls, vec!["child".into(), Value::Array(tail)]);
        let answer = LaunchWorld::next(&mut self.children, Value::from(0));
        if matches!(&answer, Value::Str(word) if word.as_str() == Some("oserror")) {
            return Err("cannot start".into());
        }
        let pid = 4242 + self.started;
        self.started += 1;
        let code = match answer {
            Value::Int(code) => code.as_i64().unwrap_or(0) as i32,
            _ => 0,
        };
        Ok(Box::new(ScriptChild { pid, code }))
    }
    fn relaunch(&mut self, arguments: &[String]) -> Result<(), String> {
        let tail: Vec<Value> = arguments[1..]
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect();
        call(&self.calls, vec!["relaunch".into(), Value::Array(tail)]);
        if matches!(field(&self.script, "relaunch_fails"), Value::Bool(true)) {
            return Err("cannot start".into());
        }
        Ok(())
    }
}

/// `watcher.launcher` {here, argv, env, script}.
pub fn run(request: &Map) -> Value {
    let here = PathBuf::from(field(request, "here").as_str_value().unwrap_or_default());
    let script = match field(request, "script") {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    let argv: Vec<String> = list(request, "argv")
        .iter()
        .map(car_machine::pytext::py_str)
        .collect();
    let env: Vec<(String, String)> = match field(request, "env") {
        Value::Object(map) => map
            .iter()
            .map(|(k, v)| (car_watcher::fail::lossy(k), car_machine::pytext::py_str(v)))
            .collect(),
        _ => Vec::new(),
    };
    let asked: Arc<Mutex<Vec<Value>>> = Arc::default();
    let plug = match field(&script, "plug").as_str_value() {
        Some("null") => Some(Guarded::null()),
        Some("none") => None,
        _ => Some(Guarded::new(Box::new(ScriptPlug {
            answers: Mutex::new(list(&script, "answers")),
            held: field(&script, "held").clone(),
            asked: Arc::clone(&asked),
        }))),
    };
    let calls: Calls = Rc::default();
    let mut world = LaunchWorld {
        here,
        env,
        children: list(&script, "children"),
        codes: list(&script, "codes"),
        probes: list(&script, "probes"),
        script,
        clock: Rc::new(RefCell::new(1000.0)),
        calls: Rc::clone(&calls),
        plug,
        asked: Arc::clone(&asked),
        started: 0,
    };
    let code = car_watcher::launcher::guarded(&mut world, &argv);
    let asked = asked
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .clone();
    let _ = &world.asked;
    object([
        ("code", Value::from(i64::from(code))),
        ("calls", Value::Array(calls.borrow().clone())),
        ("asked", Value::Array(asked)),
    ])
}

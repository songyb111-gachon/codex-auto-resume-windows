//! advaccount: the Rust side of S7.2b's differential tests (`tests/rustdiff/diffs_advaccount_*.py`). Dev only, never
//! shipped.
//!
//! One request on stdin: `{"world": {...}, "cases": [[op, arg, ...], ...]}`; one answer on stdout: `{"results": [{"ok":
//! v, "log": [...]} | {"error": "Class", "log": [...]}]}`. Every folder a case names is a scratch folder under the
//! working folder the diff made. Nothing real is asked: the seal is S7.1a's stand-in, the lock, Credential Manager, the
//! private access list, the process list, the Restart Manager, kernel32, Codex's sessions, the runner and the clocks are
//! scripted stand-ins that log every call, as the reference's script does (`tests/rustdiff/advaccount.py`). No process
//! is started, ended or asked.

mod engines;
mod script;
mod store;

use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use car_adv::codex::account;
use car_adv::codex::authfile::{self, Fault};
use car_adv::codex::restart;
use car_adv::codex::swap;
use car_adv::jsonx::object;
use car_adv::win::appclose;
use car_machine::json::{Options, Value, to_string};

use script::{Script, bytes, hex, log, rel, take_log, text};

pub type Out = Result<Value, Fault>;

pub fn arg(args: &[Value], at: usize) -> &Value {
    static NULL: Value = Value::Null;
    args.get(at).unwrap_or(&NULL)
}

pub fn root() -> PathBuf {
    std::env::current_dir().expect("the working folder")
}

pub fn folder(value: &Value) -> PathBuf {
    root().join(car_machine::pytext::py_str(value))
}

fn number(value: &Value) -> f64 {
    car_machine::pytext::to_float(value).unwrap_or(0.0)
}

// ------------------------------------------------------------------------------------------------ account
struct Session<'a> {
    script: &'a std::cell::RefCell<Script>,
    home: Option<PathBuf>,
}

impl account::Session for Session<'_> {
    fn call(&mut self, method: &str, params: Value) -> Result<Value, Fault> {
        log(vec![text("call"), text(method), params]);
        let fresh = self
            .script
            .borrow_mut()
            .take(&format!("refresh:{method}"), Value::Null)?;
        if let (Some(fresh), Some(home)) = (bytes(&fresh), &self.home) {
            std::fs::write(home.join("auth.json"), fresh).map_err(|error| Fault::os(&error))?;
        }
        self.script.borrow_mut().take(method, Value::Null)
    }
}

impl Drop for Session<'_> {
    fn drop(&mut self) {
        log(vec![text("exit")]);
    }
}

pub struct Sessions(pub std::cell::RefCell<Script>);

impl account::Opener for Sessions {
    fn open(&self, home: Option<&Path>) -> Result<Box<dyn account::Session + '_>, Fault> {
        log(vec![
            text("enter"),
            home.map_or(Value::Null, |home| text(&rel(home))),
        ]);
        self.0.borrow_mut().take("open", Value::Null)?;
        Ok(Box::new(Session {
            script: &self.0,
            home: home.map(Path::to_path_buf),
        }))
    }
}

pub struct Backend {
    pub script: std::rc::Rc<std::cell::RefCell<Script>>,
    pub home: Option<PathBuf>,
}

impl account::Backend for Backend {
    fn argv(&self) -> Result<Vec<String>, Fault> {
        let found = self
            .script
            .borrow_mut()
            .take("argv", Value::Array(vec![text("codex.exe")]))?;
        match found {
            Value::Array(items) => Ok(items.iter().map(car_machine::pytext::py_str).collect()),
            _ => Err(Fault::new("TypeError", "argv")),
        }
    }
    fn environment(&self) -> Result<Vec<(String, String)>, Fault> {
        let found = self.script.borrow_mut().take(
            "env",
            Value::Array(vec![Value::Array(vec![text("CODEX_HOME"), text("h")])]),
        )?;
        let Value::Array(pairs) = found else {
            return Err(Fault::new("TypeError", "env"));
        };
        let mut env: Vec<(String, String)> = Vec::new();
        for pair in pairs {
            if let Value::Array(both) = pair
                && both.len() == 2
            {
                let key = car_machine::pytext::py_str(&both[0]);
                let value = car_machine::pytext::py_str(&both[1]);
                match env.iter_mut().find(|(each, _)| *each == key) {
                    Some(slot) => slot.1 = value,
                    None => env.push((key, value)),
                }
            }
        }
        Ok(env)
    }
    fn codex_home(&self) -> String {
        match &self.home {
            Some(home) => home.to_string_lossy().into_owned(),
            None => car_machine::pytext::py_str(
                &self
                    .script
                    .borrow_mut()
                    .take("home", text("h"))
                    .unwrap_or(text("h")),
            ),
        }
    }
}

pub struct Runner(pub std::cell::RefCell<Script>);

impl account::Runner for Runner {
    fn run(
        &self,
        argv: &[String],
        env: &[(String, String)],
        cwd: &str,
        timeout: f64,
    ) -> Result<Value, account::Ran> {
        let mut pairs: Vec<Value> = env
            .iter()
            .map(|(key, value)| Value::Array(vec![text(key), text(value)]))
            .collect();
        pairs.sort_by_key(car_machine::pytext::py_str);
        let place = if Path::new(cwd).is_absolute() {
            text(&rel(Path::new(cwd)))
        } else {
            text(cwd)
        };
        log(vec![
            text("run"),
            Value::Array(argv.iter().map(|each| text(each)).collect()),
            Value::Array(pairs),
            place,
            Value::Null,
            Value::Float(timeout),
        ]);
        let found = self
            .0
            .borrow_mut()
            .take(
                "run",
                Value::Array(vec![Value::from(0), text(""), text("")]),
            )
            .map_err(account::Ran::Raised)?;
        if car_machine::pyval::is(&found, "timeout") {
            return Err(account::Ran::Timeout);
        }
        Ok(found)
    }
}

pub fn reader(script: std::rc::Rc<std::cell::RefCell<Script>>) -> impl Fn() -> Value {
    move || {
        log(vec![text("read")]);
        script
            .borrow_mut()
            .take("read", account_unknown())
            .unwrap_or(Value::Null)
    }
}

fn account_unknown() -> Value {
    object([
        ("present", Value::Null),
        ("plan_word", Value::Null),
        ("email", Value::Null),
        ("kind", Value::Null),
    ])
}

fn shared(value: &Value) -> std::rc::Rc<std::cell::RefCell<Script>> {
    std::rc::Rc::new(std::cell::RefCell::new(Script::new(value)))
}

fn run_account(op: &str, args: &[Value]) -> Out {
    match op {
        "ac.plan_word" => Ok(account::plan_word(arg(args, 0))),
        "ac.parse" => Ok(account::parse(arg(args, 0))),
        "ac.identity" => Ok(account::identity(arg(args, 0))?.unwrap_or(Value::Null)),
        "ac.digest" => Ok(text(&account::digest(arg(args, 0), arg(args, 1))?)),
        "ac.mask" => Ok(account::mask(arg(args, 0))),
        "ac.read" => Ok(account::read(&Sessions(std::cell::RefCell::new(
            Script::new(arg(args, 0)),
        )))),
        "ac.switch" => {
            let backend = if car_machine::pyval::is(arg(args, 0), "raise") {
                None
            } else {
                Some(Backend {
                    script: shared(arg(args, 0)),
                    home: None,
                })
            };
            let runner = Runner(std::cell::RefCell::new(Script::new(arg(args, 1))));
            let read = reader(shared(arg(args, 2)));
            let made: Result<&dyn account::Backend, Fault> = match &backend {
                Some(backend) => Ok(backend),
                None => Err(Fault::new("AttributeError", "no backend")),
            };
            let outcome = account::switch(made, &runner, &read, number(arg(args, 3)))?;
            Ok(text(outcome))
        }
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

// ------------------------------------------------------------------------------------------------ authfile
fn private(directory: &Path) -> bool {
    log(vec![text("private"), text(&rel(directory))]);
    true
}

fn pause(seconds: f64) {
    log(vec![text("pause"), Value::Float(seconds)]);
}

fn run_authfile(op: &str, args: &[Value]) -> Out {
    let tokens = script::Counter;
    match op {
        "af.check" => Ok(hex(&authfile::check(
            &bytes(arg(args, 0)).unwrap_or_default(),
        )
        .or_else(|fault| check_value(arg(args, 0), fault))?)),
        "af.names" => {
            let name = car_machine::pytext::py_str(arg(args, 0));
            Ok(Value::Array(vec![
                Value::Bool(authfile::scratch_name(&name)),
                Value::Bool(authfile::temporary_name(&name)),
                Value::Bool(authfile::beside_name(&name)),
            ]))
        }
        "af.store_mode" => Ok(authfile::store_mode_at(
            &folder(arg(args, 0)),
            authfile::FRAMES + 1,
        )?
        .map_or(Value::Null, text)),
        "af.usable" => Ok(text(authfile::usable(&folder(arg(args, 0)))?)),
        "af.read" => Ok(hex(&authfile::read(&folder(arg(args, 0)))?)),
        "af.replace" => {
            authfile::replace(
                &folder(arg(args, 0)),
                &bytes(arg(args, 1)).unwrap_or_default(),
                &tokens,
            )?;
            Ok(Value::Null)
        }
        "af.own_folder" => {
            authfile::own_folder(&folder(arg(args, 0)), &private)?;
            Ok(Value::Null)
        }
        "af.confined" => Ok(Value::Bool(authfile::confined(&folder(arg(args, 0))))),
        "af.remove_tree" => Ok(Value::Bool(authfile::remove_tree(&folder(arg(args, 0))))),
        "af.sweep" => {
            let home = match arg(args, 1) {
                Value::Null => None,
                other => Some(folder(other)),
            };
            let (removed, failed) = authfile::sweep(
                &folder(arg(args, 0)),
                home.as_deref(),
                number(arg(args, 2)),
                number(arg(args, 3)),
            );
            Ok(Value::Array(vec![
                Value::from(removed),
                Value::from(failed),
            ]))
        }
        "af.scratch" => {
            let mut scratch = authfile::Scratch::new(&folder(arg(args, 0)), bytes(arg(args, 1)));
            let action = arg(args, 2).clone();
            let done = scratch.with(&tokens, &private, &pause, |home| {
                log(vec![text("inside"), text(&rel(home))]);
                if car_machine::pyval::is(&action, "raise") {
                    return Err(Fault::new("RuntimeError", "stand-in"));
                }
                if let Value::Object(map) = &action
                    && let Some(data) = map.get("write").and_then(bytes)
                {
                    std::fs::write(home.join("auth.json"), data)
                        .map_err(|error| Fault::os(&error))?;
                }
                if car_machine::pyval::is(&action, "unlink") {
                    std::fs::remove_file(home.join("auth.json"))
                        .map_err(|error| Fault::os(&error))?;
                }
                Ok(())
            });
            match done {
                Err(fault) if fault.class == "RuntimeError" => log(vec![text("raised")]),
                Err(fault) => return Err(fault),
                Ok(()) => {}
            }
            Ok(Value::Array(vec![
                scratch
                    .path
                    .as_deref()
                    .map_or(Value::Null, |path| text(&rel(path))),
                scratch.after.as_deref().map_or(Value::Null, hex),
                scratch.removed.map_or(Value::Null, Value::Bool),
            ]))
        }
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

/// `authfile.check(value)` of something that is not bytes: the reference's refusal of its size.
fn check_value(value: &Value, fault: Fault) -> Result<Vec<u8>, Fault> {
    if bytes(value).is_some() {
        return Err(fault);
    }
    Err(Fault::auth("not a sign-in file's size"))
}

// ------------------------------------------------------------------------------------------------ appclose
struct Rm(std::cell::RefCell<Script>);

fn code(value: &Value) -> u32 {
    car_adv::state::py::small(value).unwrap_or(0) as u32
}

impl appclose::Manager for Rm {
    fn start_session(&self) -> Result<u32, u32> {
        log(vec![text("RmStartSession"), Value::from(0)]);
        let found = self
            .0
            .borrow_mut()
            .take("RmStartSession", Value::from(0))
            .unwrap_or(Value::from(0));
        let (answer, handle) = match &found {
            Value::Array(both) if both.len() == 2 => (code(&both[0]), code(&both[1])),
            other => (code(other), 1),
        };
        if answer == 0 { Ok(handle) } else { Err(answer) }
    }
    fn register(&self, session: u32, pid: u32, created: u64) -> u32 {
        log(vec![
            text("RmRegisterResources"),
            Value::from(i64::from(session)),
            Value::from(1),
            Value::from(i64::from(pid)),
            car_machine::json::Int::parse(&created.to_string()).map_or(Value::Null, Value::Int),
        ]);
        code(
            &self
                .0
                .borrow_mut()
                .take("RmRegisterResources", Value::from(0))
                .unwrap_or(Value::from(0)),
        )
    }
    fn shutdown(&self, session: u32, flags: u32) -> u32 {
        log(vec![
            text("RmShutdown"),
            Value::from(i64::from(session)),
            Value::from(i64::from(flags)),
        ]);
        code(
            &self
                .0
                .borrow_mut()
                .take("RmShutdown", Value::from(0))
                .unwrap_or(Value::from(0)),
        )
    }
    fn end_session(&self, session: u32) -> u32 {
        log(vec![text("RmEndSession"), Value::from(i64::from(session))]);
        code(
            &self
                .0
                .borrow_mut()
                .take("RmEndSession", Value::from(0))
                .unwrap_or(Value::from(0)),
        )
    }
}

struct Kernel(std::cell::RefCell<Script>);

impl Kernel {
    fn take(&self, kind: &str) -> Value {
        self.0
            .borrow_mut()
            .take(kind, Value::from(0))
            .unwrap_or(Value::from(0))
    }
}

impl appclose::Kernel for Kernel {
    fn open(&self, access: u32, pid: u32) -> isize {
        log(vec![
            text("OpenProcess"),
            Value::from(i64::from(access)),
            Value::from(i64::from(pid)),
        ]);
        car_adv::state::py::small(&self.take("OpenProcess")).unwrap_or(0) as isize
    }
    fn wait(&self, handle: isize, millis: u32) -> u32 {
        log(vec![
            text("WaitForSingleObject"),
            Value::from(handle as i64),
            Value::from(i64::from(millis)),
        ]);
        code(&self.take("WaitForSingleObject"))
    }
    fn created(&self, handle: isize) -> Option<u64> {
        log(vec![text("GetProcessTimes"), Value::from(handle as i64)]);
        let (low, _) = appclose::low_bits(&self.take("GetProcessTimes"));
        (low != 0).then_some(low)
    }
    fn terminate(&self, handle: isize, code: u32) -> bool {
        log(vec![
            text("TerminateProcess"),
            Value::from(handle as i64),
            Value::from(i64::from(code)),
        ]);
        car_machine::pyval::truthy(&self.take("TerminateProcess"))
    }
    fn close(&self, handle: isize) -> bool {
        log(vec![text("CloseHandle"), Value::from(handle as i64)]);
        car_machine::pyval::truthy(&self.take("CloseHandle"))
    }
}

fn run_appclose(op: &str, args: &[Value]) -> Out {
    let script = std::cell::RefCell::new(Script::new(arg(args, 2)));
    match op {
        "ap.ask_close" => Ok(Value::Bool(appclose::ask_close(
            &Rm(script),
            arg(args, 0),
            arg(args, 1),
        ))),
        "ap.end_process" => Ok(Value::Bool(appclose::end_process(
            &Kernel(script),
            arg(args, 0),
            arg(args, 1),
        ))),
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

// ------------------------------------------------------------------------------------------------ restart
struct Hands {
    script: std::cell::RefCell<Script>,
    clock: std::cell::Cell<f64>,
    system: car_codex::system::Platform,
}

impl Hands {
    fn new(script: &Value) -> Hands {
        Hands {
            script: std::cell::RefCell::new(Script::new(script)),
            clock: std::cell::Cell::new(0.0),
            system: car_codex::system::Platform::new(),
        }
    }
    fn take(&self, kind: &str, default: Value) -> Result<Value, Fault> {
        self.script.borrow_mut().take(kind, default)
    }
}

impl restart::Hands for Hands {
    fn system(&self) -> &dyn car_codex::system::System {
        &self.system
    }
    fn inventory(&self) -> Result<Vec<Value>, Fault> {
        log(vec![text("inventory")]);
        match self.take("inventory", Value::Array(Vec::new()))? {
            Value::Array(rows) => Ok(rows),
            _ => Err(Fault::new("TypeError", "not a list")),
        }
    }
    fn created(&self, pid: &Value) -> Result<Value, Fault> {
        log(vec![text("created"), pid.clone()]);
        self.take("created", Value::Null)
    }
    fn ask_close(&self, pid: &Value, created: &Value) -> Result<Value, Fault> {
        log(vec![text("ask_close"), pid.clone(), created.clone()]);
        self.take("ask_close", Value::Bool(false))
    }
    fn end_process(&self, pid: &Value, created: &Value) -> Result<Value, Fault> {
        log(vec![text("end_process"), pid.clone(), created.clone()]);
        self.take("end_process", Value::Bool(false))
    }
    fn newest_conversation(&self) -> Result<Value, Fault> {
        log(vec![text("newest")]);
        self.take("newest", Value::Null)
    }
    fn open(&self, link: &str) -> Result<Value, Fault> {
        log(vec![text("open"), text(link)]);
        self.take("open", Value::Bool(true))
    }
    fn read(&self) -> Result<Value, Fault> {
        log(vec![text("read")]);
        self.take("read", object([("present", Value::Bool(true))]))
    }
    fn now(&self) -> f64 {
        self.clock.get()
    }
    fn sleep(&self, seconds: f64) {
        log(vec![text("sleep"), Value::Float(seconds)]);
        self.clock.set(self.clock.get() + seconds);
    }
}

struct BusyStore(std::cell::RefCell<Script>);

impl restart::BusyStore for BusyStore {
    fn pending(&self) -> Result<Vec<Value>, Fault> {
        log(vec![text("pending")]);
        match self
            .0
            .borrow_mut()
            .take("pending", Value::Array(Vec::new()))?
        {
            Value::Array(rows) => Ok(rows),
            _ => Err(Fault::new("TypeError", "not a list")),
        }
    }
    fn watcher_status(&self) -> Result<Value, Fault> {
        log(vec![text("status")]);
        self.0.borrow_mut().take("status", Value::Null)
    }
}

struct Source(std::cell::RefCell<Script>);

impl restart::Activity for Source {
    fn activity(&self, now: &Value, booted: &Value) -> Result<Value, Fault> {
        log(vec![
            text("activity"),
            Value::Array(Vec::new()),
            now.clone(),
            booted.clone(),
        ]);
        self.0.borrow_mut().take("activity", Value::Null)
    }
}

fn run_restart(op: &str, args: &[Value]) -> Out {
    match op {
        "rs.restart" => {
            let hands = Hands::new(arg(args, 0));
            let between = match arg(args, 1) {
                Value::Null => None,
                other => Some(std::cell::RefCell::new(Script::new(other))),
            };
            let mut call = || {
                log(vec![text("between")]);
                if let Some(script) = &between {
                    let _ = script.borrow_mut().take("between", Value::Null);
                }
            };
            let (outcome, how) = restart::restart(
                &hands,
                if between.is_some() {
                    Some(&mut call)
                } else {
                    None
                },
            )?;
            Ok(Value::Array(vec![
                text(outcome),
                how.map_or(Value::Null, text),
            ]))
        }
        "rs.busy" => {
            let store = BusyStore(std::cell::RefCell::new(Script::new(arg(args, 0))));
            let source = Source(std::cell::RefCell::new(Script::new(arg(args, 1))));
            let found = restart::busy(
                Ok(&store),
                Ok(&source),
                arg(args, 2),
                car_machine::pyval::truthy(arg(args, 3)),
            )?;
            Ok(Value::Array(found.into_iter().map(text).collect()))
        }
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

// ------------------------------------------------------------------------------------------------ swap (pure)
fn run_swap_pure(op: &str, args: &[Value]) -> Out {
    match op {
        "sw.meters" => {
            let windows = match arg(args, 0) {
                Value::Array(items) => items.clone(),
                Value::Null => Vec::new(),
                _ => return Err(Fault::new("TypeError", "not iterable")),
            };
            Ok(Value::Object(swap::meters(&windows)?))
        }
        "sw.usage_of" => Ok(Value::Object(swap::usage_of(arg(args, 0))?)),
        "sw.has_room" => Ok(Value::Bool(swap::has_room(arg(args, 0)))),
        "sw.known" => Ok(Value::Bool(swap::known(arg(args, 0))?)),
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

fn dispatch(op: &str, args: &[Value]) -> Out {
    match op.split('.').next().unwrap_or("") {
        "ac" => run_account(op, args),
        "af" => run_authfile(op, args),
        "ap" => run_appclose(op, args),
        "rs" => run_restart(op, args),
        "sw" if ["sw.meters", "sw.usage_of", "sw.has_room", "sw.known"].contains(&op) => {
            run_swap_pure(op, args)
        }
        "sw" => store::run(op, args),
        "ea" | "ec" => engines::run(op, args),
        _ => Err(Fault::new("UnknownOp", op)),
    }
}

/// `name_of(error)`: the advanced edition's own classes by name, every other OSError as OSError.
fn name_of(fault: &Fault) -> Value {
    if ["AuthFileError", "ProfileError", "Locked", "PutBackWaits"].contains(&fault.class.as_str()) {
        return text(&fault.class);
    }
    if fault.is_os() {
        return text("OSError");
    }
    text(&fault.class)
}

pub fn class_of(fault: &Fault) -> Value {
    name_of(fault)
}

fn main() {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw).expect("stdin");
    let Ok(Value::Object(request)) = car_machine::compat::loads(&raw) else {
        eprintln!("the request is not a JSON object");
        std::process::exit(2);
    };
    let world = request.get("world").cloned().unwrap_or(Value::Null);
    script::set_world(&world);
    let Some(Value::Array(cases)) = request.get("cases") else {
        eprintln!("no cases");
        std::process::exit(2);
    };
    let mut results = Vec::with_capacity(cases.len());
    for case in cases {
        take_log();
        script::reset_counter();
        let Value::Array(parts) = case else {
            results.push(object([("error", text("BadCase"))]));
            continue;
        };
        let op = parts
            .first()
            .map(car_machine::pytext::py_str)
            .unwrap_or_default();
        let answer = dispatch(&op, &parts[parts.len().min(1)..]);
        let logged = Value::Array(take_log());
        results.push(match answer {
            Ok(value) => object([("ok", value), ("log", logged)]),
            Err(fault) => object([("error", name_of(&fault)), ("log", logged)]),
        });
    }
    let body = object([("results", Value::Array(results))]);
    let text = to_string(&body, &Options::new()).expect("the answer is JSON");
    std::io::stdout()
        .write_all(text.as_bytes())
        .expect("stdout");
}

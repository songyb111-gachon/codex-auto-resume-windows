//! `codex/wmi_escape`'s ops (seat adv72d): `wm.probe` (the chain over a scripted stand-in that logs every effect in the
//! reference fake's words: nothing is started, opened or written), `wm.helper` (what the helper would hand `pwsh.run`),
//! `wm.env` (the argument variables `pwsh` would set), `wm.record` (the heartbeat's record) and `wm.constants`.

use car_adv::codex::wmi_escape::{self, Chain, Facts, Handle, Raised};
use car_adv::jsonx::object;
use car_machine::json::{Map, Value};

use crate::ops_win::{Script, int_of};
use crate::{Context, Failure, Out, arg, text};

struct Fake {
    script: Script,
    calls: Vec<Value>,
}

impl Fake {
    fn log(&mut self, entry: Vec<Value>) {
        self.calls.push(Value::Array(entry));
    }
    fn answer(&self, kind: &str, default: Value) -> Result<Value, Raised> {
        self.script
            .answer(kind, default)
            .map_err(|_| Raised("RuntimeError"))
    }
    fn number(&self, kind: &str, default: i64) -> i64 {
        self.answer(kind, default.into()).map_or(0, |v| int_of(&v))
    }
}

fn text_of(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

impl Chain for Fake {
    fn windows(&self) -> bool {
        true
    }
    fn launcher(&mut self) -> Option<String> {
        self.log(vec!["launcher".into()]);
        self.answer("launcher", "C:/Python/pythonw.exe".into())
            .ok()
            .and_then(|v| text_of(&v))
    }
    fn make_workdir(&mut self, prefix: &str) -> Result<String, Raised> {
        self.log(vec!["mkdtemp".into(), prefix.into()]);
        let found = self.answer("workdir", "C:/Temp/car-mw-abc".into())?;
        text_of(&found).ok_or(Raised("TypeError"))
    }
    fn write_text(&mut self, path: &str, text: &str) -> Result<(), Raised> {
        self.log(vec!["write".into(), path.into(), text.into()]);
        self.answer("write", Value::Null).map(|_| ())
    }
    fn create_job_object(&mut self) -> Handle {
        self.log(vec!["job".into()]);
        self.number("job", 300) as Handle
    }
    fn set_information_job_object(&mut self, job: Handle, class: i32, limit_flags: u32) -> bool {
        self.log(vec![
            "setinfo".into(),
            (job as i64).into(),
            class.into(),
            limit_flags.into(),
        ]);
        self.number("setinfo", 1) != 0
    }
    fn assign_process_to_job_object(&mut self, job: Handle, process: Handle) -> bool {
        self.log(vec![
            "assign".into(),
            (job as i64).into(),
            (process as i64).into(),
        ]);
        self.number("assign", 1) != 0
    }
    fn open_process(&mut self, access: u32, inherit: bool, pid: i64) -> Handle {
        self.log(vec![
            "open".into(),
            access.into(),
            inherit.into(),
            pid.into(),
        ]);
        self.number("open", 77) as Handle
    }
    fn terminate_process(&mut self, process: Handle, code: u32) -> bool {
        self.log(vec![
            "terminate".into(),
            (process as i64).into(),
            code.into(),
        ]);
        self.number("terminate", 1) != 0
    }
    fn wait_for_single_object(&mut self, handle: Handle, millis: u32) -> u32 {
        self.log(vec!["wait".into(), (handle as i64).into(), millis.into()]);
        self.number("wait", 0x102) as u32
    }
    fn close_handle(&mut self, handle: Handle) -> bool {
        self.log(vec!["close".into(), (handle as i64).into()]);
        self.number("close", 1) != 0
    }
    fn spawn(&mut self, argv: &[String], flags: u32) -> Result<i64, Raised> {
        self.log(vec![
            "spawn".into(),
            Value::Array(argv.iter().map(|each| each.as_str().into()).collect()),
            flags.into(),
        ]);
        Ok(int_of(&self.answer("spawn", 4100.into())?))
    }
    fn wait_child(&mut self, pid: i64, timeout: f64) -> Result<(), Raised> {
        self.log(vec!["wait_child".into(), pid.into(), timeout.into()]);
        self.answer("wait_child", Value::Null).map(|_| ())
    }
    fn resume_process(&mut self, process: Handle) {
        self.log(vec!["resume".into(), (process as i64).into()]);
    }
    fn await_json(&mut self, path: &str, timeout: f64) -> Option<Value> {
        self.log(vec!["await".into(), path.into(), timeout.into()]);
        self.answer("heartbeat", Value::Null).ok()
    }
    fn sleep(&mut self, seconds: f64) {
        self.log(vec!["sleep".into(), seconds.into()]);
    }
    fn remove(&mut self, directory: &str) {
        self.log(vec!["remove".into(), directory.into()]);
    }
}

fn facts_value(facts: &Facts) -> Value {
    let maybe = |value: Option<bool>| value.map_or(Value::Null, Value::Bool);
    object([
        ("started", Value::Bool(facts.started)),
        ("in_job", maybe(facts.in_job)),
        ("job_kills_on_close", maybe(facts.job_kills_on_close)),
        ("kill_on_close", Value::Bool(facts.kill_on_close)),
        ("survived", Value::Bool(facts.survived)),
    ])
}

fn env_of(values: &Value) -> Out {
    let Value::Object(map) = values else {
        return Err(crate::bad());
    };
    let pairs: Vec<(String, Option<String>)> = map
        .iter()
        .map(|(key, value)| (key.as_str().unwrap_or("").to_owned(), text_of(value)))
        .collect();
    let borrowed: Vec<(&str, Option<&str>)> = pairs
        .iter()
        .map(|(key, value)| (key.as_str(), value.as_deref()))
        .collect();
    let found =
        car_platform::pwsh::environment(&borrowed).map_err(|_| Failure::new("PowerShellError"))?;
    let mut out: Vec<(String, String)> = found
        .into_iter()
        .map(|(key, value)| {
            (
                key.to_string_lossy().into_owned(),
                value.to_string_lossy().into_owned(),
            )
        })
        .filter(|(key, _)| key.to_uppercase().starts_with(car_platform::pwsh::PREFIX))
        .collect();
    out.sort();
    Ok(Value::Array(
        out.into_iter()
            .map(|(key, value)| Value::Array(vec![key.into(), value.into()]))
            .collect(),
    ))
}

pub fn run(_context: &Context, op: &str, args: &[Value]) -> Out {
    match op {
        "wm.probe" => {
            let mut fake = Fake {
                script: Script::new(arg(args, 0)),
                calls: Vec::new(),
            };
            let done = wmi_escape::probe(&mut fake, &text(arg(args, 1))?);
            let calls = Value::Array(std::mem::take(&mut fake.calls));
            Ok(match done {
                Ok(facts) => object([("facts", facts_value(&facts)), ("calls", calls)]),
                Err(Raised(class)) => object([("raised", class.into()), ("calls", calls)]),
            })
        }
        "wm.helper" => {
            let plan = wmi_escape::helper_plan(
                &text(arg(args, 0))?,
                &text(arg(args, 1))?,
                &text(arg(args, 2))?,
                &text(arg(args, 3))?,
            );
            let mut values = Map::new();
            for (name, value) in &plan.values {
                values.insert(name.as_str().into(), value.as_str().into());
            }
            let mut log = vec![Value::Array(vec![
                "pwsh".into(),
                plan.script.into(),
                Value::Object(values),
                plan.timeout.into(),
            ])];
            if !matches!(arg(args, 4), Value::Bool(true)) {
                log.push(Value::Array(vec!["sleep".into(), plan.then_sleep.into()]));
            }
            Ok(Value::Array(log))
        }
        "wm.env" => env_of(arg(args, 0)),
        "wm.record" => Ok(Value::from(wmi_escape::heartbeat_record(
            int_of(arg(args, 0)),
            arg(args, 1),
            arg(args, 2),
        ))),
        "wm.constants" => Ok(Value::Array(vec![
            wmi_escape::WMI_SCRIPT.into(),
            wmi_escape::BOOTSTRAP.into(),
            wmi_escape::CREATE_SUSPENDED.into(),
            wmi_escape::NO_WINDOW.into(),
            wmi_escape::JOB_KILL_ON_CLOSE.into(),
            wmi_escape::JOB_EXTENDED_LIMIT_INFORMATION.into(),
            wmi_escape::HEARTBEAT_SECONDS.into(),
            wmi_escape::HELPER_SECONDS.into(),
            wmi_escape::WMI_TIMEOUT.into(),
            wmi_escape::SETTLE_SECONDS.into(),
            Value::Array(
                car_platform::startup::NO_REMOTE_DEBUG
                    .iter()
                    .map(|each| (*each).into())
                    .collect(),
            ),
        ])),
        _ => Err(Failure::new("UnknownOp")),
    }
}

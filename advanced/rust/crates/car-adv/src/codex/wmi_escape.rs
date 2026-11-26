//! `codex/wmi_escape.py`: measurement MW's launcher - re-prove that a process can leave Codex's kind of job through WMI
//! (seat adv72d). **Never run by a seat or a test** (P7-DESIGN section 4): the diff compares what it would start and
//! ask, through a stand-in [`Chain`], and starts nothing.
//!
//! The chain, as the reference runs it: a job object with KILL_ON_JOB_CLOSE and no breakaway; a helper started
//! suspended (`CREATE_NO_WINDOW | CREATE_SUSPENDED`), assigned to the job and resumed; the helper asks WMI
//! `Win32_Process.Create` (through `pwsh.run`, [`WMI_SCRIPT`], ShowWindow = 0, never CreateFlags) to start the heartbeat,
//! which lands outside the job and writes its job words; the job is closed; the heartbeat must still be alive. Only
//! booleans are kept ([`Facts`]).
//!
//! What is the reference's own interpreter - `startup.python_launcher()`, the bootstrap file, the import roots - is a
//! parameter here ([`Launch`]): the reference's route names pythonw and its two-line bootstrap ([`BOOTSTRAP`]); the
//! Rust edition's roles are S7.3d's (`car-adv-bin`), which fills [`Chain`] with car-platform's job and process calls.
//! Until then nothing implements it but the diff's stand-in.

use car_machine::json::{Map, Value};
use car_platform::cmdline::quote_argument;
use car_platform::paths::pathlib_text;
use car_platform::startup::NO_REMOTE_DEBUG;

/// Started suspended so the helper is in the job before it fires WMI; it does not void CREATE_NO_WINDOW.
pub const CREATE_SUSPENDED: u32 = 0x0000_0004;
/// `subprocess.CREATE_NO_WINDOW` (core's `win/kernel.NO_WINDOW`).
pub const NO_WINDOW: u32 = 0x0800_0000;
/// `win/kernel.JOB_KILL_ON_CLOSE`.
pub const JOB_KILL_ON_CLOSE: u32 = 0x2000;
pub const JOB_EXTENDED_LIMIT_INFORMATION: i32 = 9;
pub const HEARTBEAT_SECONDS: f64 = 30.0;
pub const HELPER_SECONDS: f64 = 12.0;
pub const WMI_TIMEOUT: f64 = 30.0;
pub const SETTLE_SECONDS: f64 = 3.0;
/// SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, `_alive`'s access.
pub const ALIVE_ACCESS: u32 = 0x0010_0000 | 0x1000;
pub const PROCESS_TERMINATE: u32 = 0x0001;
pub const PROCESS_ALL_ACCESS: u32 = 0x1F_0FFF;
pub const WAIT_TIMEOUT: u32 = 0x0000_0102;
/// The temporary folder's prefix (`tempfile.mkdtemp(prefix=...)`).
pub const WORKDIR_PREFIX: &str = "car-mw-";

/// The WMI create, a constant `pwsh.run` script; the command line arrives as an environment variable.
pub const WMI_SCRIPT: &str = "\n$cmd = $env:CODEX_AUTO_RESUME_ARG_HEARTBEAT_CMD\n$startup = New-CimInstance -Namespace root/cimv2 -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }\n$r = Invoke-CimMethod -Namespace root/cimv2 -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd; ProcessStartupInformation = $startup }\nif ($null -eq $r -or $r.ReturnValue -ne 0) { exit 3 }\nexit 0\n";

/// The reference route's bootstrap file: the import roots on the path, then the module's own role.
pub const BOOTSTRAP: &str = "import os, sys\nsys.path[:0] = sys.argv[2].split(os.pathsep)\nfrom codex_auto_resume_advanced.codex import wmi_escape\nwmi_escape._role(sys.argv[1], sys.argv[2], sys.argv[3:])\n";

/// The value `pwsh.run` is handed the command line under.
pub const HEARTBEAT_VALUE: &str = "HEARTBEAT_CMD";

/// What starts the helper and the heartbeat: the launcher, the options after it, and the import roots handed on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Launch {
    pub launcher: String,
    pub options: Vec<String>,
    pub src_paths: String,
}

impl Launch {
    /// The reference's route: pythonw with `NO_REMOTE_DEBUG`.
    pub fn python(launcher: &str, src_paths: &str) -> Launch {
        Launch {
            launcher: launcher.to_owned(),
            options: NO_REMOTE_DEBUG
                .iter()
                .map(|each| (*each).to_owned())
                .collect(),
            src_paths: src_paths.to_owned(),
        }
    }
}

/// The helper's argv: `[launcher, *options, bootstrap, "helper", src_paths, workdir, launcher, bootstrap]`.
pub fn helper_argv(launch: &Launch, bootstrap: &str, workdir: &str) -> Vec<String> {
    let mut argv = vec![launch.launcher.clone()];
    argv.extend(launch.options.iter().cloned());
    argv.extend([
        bootstrap.to_owned(),
        "helper".to_owned(),
        launch.src_paths.clone(),
        workdir.to_owned(),
        launch.launcher.clone(),
        bootstrap.to_owned(),
    ]);
    argv
}

/// `os.path.join(workdir, "heartbeat.json")`, as the helper names the heartbeat's record.
fn os_path_join(folder: &str, name: &str) -> String {
    if folder.is_empty() {
        return name.to_owned();
    }
    if folder.ends_with(['\\', '/']) || (folder.len() == 2 && folder.ends_with(':')) {
        return format!("{folder}{name}");
    }
    format!("{folder}\\{name}")
}

/// What the helper hands `pwsh.run`: the heartbeat's command line (`HEARTBEAT_CMD`), every token quoted always.
pub fn heartbeat_command_line(
    launcher: &str,
    options: &[String],
    bootstrap: &str,
    src_paths: &str,
    workdir: &str,
) -> String {
    let out = os_path_join(workdir, "heartbeat.json");
    let mut tokens: Vec<String> = vec![launcher.to_owned()];
    tokens.extend(options.iter().cloned());
    tokens.extend([
        bootstrap.to_owned(),
        "heartbeat".to_owned(),
        src_paths.to_owned(),
        out,
    ]);
    tokens
        .iter()
        .map(|token| quote_argument(token))
        .collect::<Vec<_>>()
        .join(" ")
}

/// `_heartbeat_main`'s record, as `json.dump` writes it: `{"pid": ..., "in_job": ..., "kill_on_close": ...}`.
pub fn heartbeat_record(pid: i64, in_job: &Value, kill_on_close: &Value) -> String {
    let mut map = Map::new();
    map.insert("pid".into(), Value::from(pid));
    map.insert("in_job".into(), in_job.clone());
    map.insert("kill_on_close".into(), kill_on_close.clone());
    car_machine::json::to_string(&Value::Object(map), &car_machine::json::Options::new())
        .unwrap_or_default()
}

/// What the probe reports: content-free booleans.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Facts {
    pub started: bool,
    pub in_job: Option<bool>,
    pub job_kills_on_close: Option<bool>,
    pub kill_on_close: bool,
    pub survived: bool,
}

/// What a step of the chain raised: the probe lets it out, after its cleanup, as the reference does.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Raised(pub &'static str);

/// A handle, 0 for none.
pub type Handle = isize;

/// Everything the chain asks of Windows and of the process: the kernel calls `_kernel()` makes, starting the helper,
/// resuming it, the heartbeat's record, the clock, and the scratch folder. The diff's stand-in records each call.
pub trait Chain {
    /// `os.name == "nt"`.
    fn windows(&self) -> bool;
    /// `startup.python_launcher()`, or None where it raises.
    fn launcher(&mut self) -> Option<String>;
    /// `tempfile.mkdtemp(prefix="car-mw-")`.
    fn make_workdir(&mut self, prefix: &str) -> Result<String, Raised>;
    /// `Path(...).write_text(text, encoding="utf-8")`.
    fn write_text(&mut self, path: &str, text: &str) -> Result<(), Raised>;
    fn create_job_object(&mut self) -> Handle;
    fn set_information_job_object(&mut self, job: Handle, class: i32, limit_flags: u32) -> bool;
    fn assign_process_to_job_object(&mut self, job: Handle, process: Handle) -> bool;
    fn open_process(&mut self, access: u32, inherit: bool, pid: i64) -> Handle;
    fn terminate_process(&mut self, process: Handle, code: u32) -> bool;
    fn wait_for_single_object(&mut self, handle: Handle, millis: u32) -> u32;
    fn close_handle(&mut self, handle: Handle) -> bool;
    /// `subprocess.Popen(argv, creationflags=flags, ...)`: the child's pid.
    fn spawn(&mut self, argv: &[String], flags: u32) -> Result<i64, Raised>;
    /// `helper.wait(timeout=...)`: Err where it did not end in time.
    fn wait_child(&mut self, pid: i64, timeout: f64) -> Result<(), Raised>;
    /// `NtResumeProcess(handle)`.
    fn resume_process(&mut self, process: Handle);
    /// `_await_json(path, timeout)`: the heartbeat's record once whole, or None.
    fn await_json(&mut self, path: &str, timeout: f64) -> Option<Value>;
    fn sleep(&mut self, seconds: f64);
    /// `shutil.rmtree(directory, ignore_errors=True)`.
    fn remove(&mut self, directory: &str);
}

/// `_alive(k, pid)`.
pub fn alive(chain: &mut dyn Chain, pid: i64) -> bool {
    let handle = chain.open_process(ALIVE_ACCESS, false, pid);
    if handle == 0 {
        return false;
    }
    let running = chain.wait_for_single_object(handle, 0) == WAIT_TIMEOUT;
    chain.close_handle(handle);
    running
}

/// `_terminate(k, pid)`.
pub fn terminate(chain: &mut dyn Chain, pid: i64) {
    let handle = chain.open_process(PROCESS_TERMINATE, false, pid);
    if handle != 0 {
        chain.terminate_process(handle, 1);
        chain.close_handle(handle);
    }
}

/// Python's `bool(value)` of a JSON value.
fn truthy(value: Option<&Value>) -> bool {
    value.is_some_and(car_machine::pyval::truthy)
}

/// `isinstance(value, int)` (a bool is one): the pid it names.
fn int_pid(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Int(n) => n.as_i64(),
        Value::Bool(flag) => Some(i64::from(*flag)),
        _ => None,
    }
}

/// `probe(paths)`: run the whole chain once and report the heartbeat's job words. `src_paths` is what the reference's
/// `_src_paths()` answers (its own import roots).
pub fn probe(chain: &mut dyn Chain, src_paths: &str) -> Result<Facts, Raised> {
    let mut facts = Facts::default();
    if !chain.windows() {
        return Ok(facts);
    }
    let Some(launcher) = chain.launcher() else {
        return Ok(facts);
    };
    let launch = Launch::python(&launcher, src_paths);
    let workdir = pathlib_text(&chain.make_workdir(WORKDIR_PREFIX)?);
    let bootstrap = car_machine::winpath::join(&workdir, "bootstrap.py");
    chain.write_text(&bootstrap, BOOTSTRAP)?;
    let heartbeat_out = car_machine::winpath::join(&workdir, "heartbeat.json");

    let mut job = chain.create_job_object();
    let mut helper: Option<i64> = None;
    let mut helper_handle: Handle = 0;
    let mut heartbeat_pid: Option<i64> = None;
    let outcome = (|| -> Result<Facts, Raised> {
        if job == 0
            || !chain.set_information_job_object(
                job,
                JOB_EXTENDED_LIMIT_INFORMATION,
                JOB_KILL_ON_CLOSE,
            )
        {
            return Ok(facts.clone());
        }
        let argv = helper_argv(&launch, &bootstrap, &workdir);
        let pid = chain.spawn(&argv, NO_WINDOW | CREATE_SUSPENDED)?;
        helper = Some(pid);
        helper_handle = chain.open_process(PROCESS_ALL_ACCESS, false, pid);
        if helper_handle == 0 || !chain.assign_process_to_job_object(job, helper_handle) {
            return Ok(facts.clone());
        }
        chain.resume_process(helper_handle);
        let Some(heartbeat) = chain
            .await_json(&heartbeat_out, WMI_TIMEOUT)
            .filter(|found| !matches!(found, Value::Null))
        else {
            return Ok(facts.clone());
        };
        facts.started = true;
        let Value::Object(heartbeat) = heartbeat else {
            return Err(Raised("AttributeError"));
        };
        heartbeat_pid = int_pid(heartbeat.get("pid"));
        facts.in_job = Some(truthy(heartbeat.get("in_job")));
        facts.job_kills_on_close = Some(truthy(heartbeat.get("kill_on_close")));
        let helper_alive_before = alive(chain, pid);
        chain.close_handle(job);
        job = 0;
        chain.sleep(SETTLE_SECONDS);
        facts.kill_on_close = helper_alive_before && !alive(chain, pid);
        facts.survived = match heartbeat_pid {
            Some(pid) => alive(chain, pid),
            None => false,
        };
        Ok(facts.clone())
    })();
    if let Some(pid) = heartbeat_pid {
        terminate(chain, pid);
    }
    if let Some(pid) = helper
        && chain.wait_child(pid, 1.0).is_err()
    {
        terminate(chain, pid);
    }
    if helper_handle != 0 {
        chain.close_handle(helper_handle);
    }
    if job != 0 {
        chain.close_handle(job);
    }
    chain.remove(&workdir);
    outcome
}

/// What `_helper_main` hands `pwsh.run`, then sleeps: the script, the values and the timeout.
pub struct HelperPlan {
    pub script: &'static str,
    pub values: Vec<(String, String)>,
    pub timeout: f64,
    pub then_sleep: f64,
}

/// `_helper_main(src_paths, workdir, pythonw, bootstrap)`, as a plan: nothing is run.
pub fn helper_plan(src_paths: &str, workdir: &str, launcher: &str, bootstrap: &str) -> HelperPlan {
    let options: Vec<String> = NO_REMOTE_DEBUG
        .iter()
        .map(|each| (*each).to_owned())
        .collect();
    HelperPlan {
        script: WMI_SCRIPT,
        values: vec![(
            HEARTBEAT_VALUE.to_owned(),
            heartbeat_command_line(launcher, &options, bootstrap, src_paths, workdir),
        )],
        timeout: WMI_TIMEOUT,
        then_sleep: HELPER_SECONDS,
    }
}

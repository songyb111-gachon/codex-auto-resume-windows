//! The compatibility report as the Dashboard drives it: write, save, check, send - each the person's (`report/flow.py`).
//!
//! The capability's code (an action: core never asks it anything). The bridge's report commands (`surfaces.py`, S7.3a's)
//! are its only way in, and only the Dashboard's long-lived bridge reaches them. Writing, checking and sending are jobs -
//! each on a thread of this process, its status read with `advanced-report-job` - because the Dashboard ends a call after
//! thirty seconds and asks the one-shot bridge instead, which never reaches the plug; saving is a call of its own.
//!
//! Every command is answered in one order (design C.5): a job's status first, whatever stands - it reads no file, asks
//! nothing and starts nothing, so a send stopped by a turn-off, a policy or a pause still shows what it wrote; then an
//! administrator's policy; then where the capability stands - off refuses everything, watched allows writing and saving
//! and refuses checking and sending; then, for checking and sending, the pause (K5); then the arguments; then one job at
//! a time; then, for sending, the typed word and the writes the person read.
//!
//! One check or send runs at a time for each home, across every Dashboard window and process: its thread holds the home's
//! report mutex ([`HomeMutex`]) from its first question to GitHub to its last write. A send that ended part way is told by
//! the next check (`interrupted`), from what is on GitHub and from the mutex, abandoned.
//!
//! A send asks GitHub again first and writes nothing unless what sending would write is still exactly what the person
//! read; before every write it reads again where the capability stands, the policy and the pause, and stops with what it
//! had written. Only the word `send`, exactly, sends.
//!
//! What a report holds, its bytes and every status are kept in this process's memory and nowhere else; the journal gets
//! one closed code a step (`rpt.<code>`) and is never read to decide anything. A fault of this code - anything but a
//! refusal - turns the capability off (hook_exception); a panic is one (D15).
//!
//! SEAT S7.3c. The runtime, the home's mutex, the Codex home and the watcher's report are the seams of `seam.rs`; the
//! diffs hand them data (`tests/rustdiff/diffs_advreport_flow.py`).

use std::panic::AssertUnwindSafe;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use car_config::{Paths, winpath};
use car_machine::json::{Map, Str, Value};
use car_machine::localclock::LocalClock;
use car_machine::pyval;
use car_policy::settings::os::Os;

use super::document::{self, Facts, Fault};
use super::github::{self, GhError, Inspected, Ready, Runner};
use super::reading::{self, WatcherView};
use super::records::{self, World};
use super::seam::{CodexHome, HomeMutex, MakeMutex, Runtime};
use crate::registry::CapabilityDef;
use crate::state::seam::Tokens;
use crate::vocabulary::{
    ArmingState, BridgeCommand, OffReason, Refusal, ReportRefusal, ReportStatus,
};

/// What the person types to send, exactly: no trim, no case fold.
pub const WORD: &str = "send";
/// Reports kept to be saved, checked or sent.
pub const MAX_BUILDS: usize = 4;
/// Statuses kept to be read.
pub const MAX_JOBS: usize = 16;
/// How long a command waits for its job to take the mutex.
pub const START_SECONDS: f64 = 10.0;
pub const MUTEX_NAME: &str = "compat-report";

/// `{"done": False, "refusal": code}`.
pub fn refused(code: &str) -> Value {
    let mut map = Map::new();
    map.insert(Str::from("done"), Value::Bool(false));
    map.insert(Str::from("refusal"), Value::from(code));
    Value::Object(map)
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(Str::from(name), value);
    }
    Value::Object(map)
}

/// A report written and kept to be saved, checked or sent.
#[derive(Clone)]
pub struct Build {
    pub raw: String,
    pub document: Value,
    pub login: String,
    pub sha256: String,
}

/// What a job is told and tells (`context`).
#[derive(Default)]
pub struct Context {
    pub abandoned: bool,
    pub busy: bool,
    /// `context["written"]`: the writes a send had made when it ended by a fault; `None` before it began.
    pub written: Option<Vec<Value>>,
}

/// What a job's work answers: its status, or the class of the exception it raised.
type Done = Result<Value, String>;
type Work = Box<dyn FnOnce(&Arc<Mutex<Context>>) -> Done + Send>;

/// Everything a flow is made of and may be handed (the tag's keyword arguments, and the seams).
pub struct Config {
    pub runner: Arc<dyn Runner>,
    /// `find_gh=`: where gh is; `None` finds it as the reporter does.
    pub find: Option<Arc<dyn Fn() -> Option<String> + Send + Sync>>,
    pub make_mutex: MakeMutex,
    pub sleep: Arc<dyn Fn(f64) + Send + Sync>,
    pub clock: Arc<dyn Fn() -> f64 + Send + Sync>,
    pub product_version: Option<String>,
    pub windows: Option<String>,
    pub codex_home: Option<PathBuf>,
    /// `view=`: the watcher's report as a reader takes it; `None` asks `watcher`.
    pub view: Option<Arc<dyn WatcherView + Send + Sync>>,
    pub watcher: Arc<dyn WatcherView + Send + Sync>,
    pub facts: Arc<dyn Facts + Send + Sync>,
    pub homes: Arc<dyn CodexHome>,
    pub os: Arc<dyn Os + Send + Sync>,
    pub local_clock: Arc<dyn LocalClock + Send + Sync>,
    pub tokens: Arc<dyn Tokens>,
    /// The folders gh is never taken from besides the installation's home (`Path(codex_auto_resume.__file__)`'s root).
    pub unsafe_extra: Vec<String>,
}

#[derive(Default)]
struct Inner {
    /// `_builds`: sha256 -> Build, oldest first.
    builds: Vec<Build>,
    /// `_checked`: sha256 -> the writes the last check of it named.
    checked: Vec<(String, Vec<Value>)>,
    /// `_jobs`: job id -> status, oldest first.
    jobs: Vec<(String, Value)>,
    /// `_running`: the job id under way.
    running: Option<String>,
    mutex: Option<Arc<dyn HomeMutex>>,
}

/// One installation's report jobs, for the life of this process.
pub struct Flow {
    paths: Paths,
    config: Config,
    inner: Mutex<Inner>,
}

fn locked<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

fn gh_class(error: GhError) -> String {
    match error {
        GhError::Raised(class) => class,
        GhError::Refused(_) => "ReportRefused".to_owned(),
        GhError::Stopped(_) => "Stopped".to_owned(),
    }
}

impl Flow {
    pub fn new(paths: Paths, config: Config) -> Arc<Flow> {
        Arc::new(Flow {
            paths,
            config,
            inner: Mutex::new(Inner::default()),
        })
    }

    // ------------------------------------------------------------------ the commands
    /// One report command (`surfaces.REPORT_COMMANDS`) for the Dashboard, in the order above. `Err` is the class of an
    /// exception the reference lets through (the caller turns it into its own fault).
    pub fn answer(
        self: &Arc<Self>,
        runtime: &Arc<dyn Runtime>,
        definition: &Arc<CapabilityDef>,
        command: &str,
        argument: &Value,
    ) -> Result<Value, String> {
        // `argument.get(name)`: an AttributeError where the argument is not a dict, raised where it is first asked.
        let get = |name: &str| -> Result<Value, String> {
            match argument {
                Value::Object(map) => Ok(map.get(name).cloned().unwrap_or(Value::Null)),
                _ => Err("AttributeError".to_owned()),
            }
        };
        if command == BridgeCommand::AdvancedReportJob.as_str() {
            return Ok(self.job(&get("job")?));
        }
        let check = command == BridgeCommand::AdvancedReportCheck.as_str();
        let sending = check || command == BridgeCommand::AdvancedReportSend.as_str();
        let mut why = self.standing(runtime, definition, sending)?;
        if why.is_none() && sending {
            why = self.pause();
        }
        if let Some(why) = why {
            return Ok(refused(&why));
        }
        if command == BridgeCommand::AdvancedReportBuild.as_str() {
            return Ok(self.build(runtime, definition, &get("login")?));
        }
        if command == BridgeCommand::AdvancedReportSave.as_str() {
            let (sha, path) = (get("sha256")?, get("path")?);
            return self.save(runtime, definition, &sha, &path);
        }
        let Some(build) = self.build_of(&get("sha256")?) else {
            return Ok(refused(ReportRefusal::UnknownBuild.as_str()));
        };
        if check {
            let (flow, runtime2, definition2) = (
                Arc::clone(self),
                Arc::clone(runtime),
                Arc::clone(definition),
            );
            return Ok(self.start(
                runtime,
                definition,
                Box::new(move |context| flow.check(&runtime2, &definition2, &build, context)),
                true,
            ));
        }
        if locked(&self.inner).running.is_some() {
            return Ok(refused(ReportRefusal::Busy.as_str()));
        }
        if !pyval::is(&get("word")?, WORD) {
            return Ok(refused(ReportRefusal::Word.as_str()));
        }
        let writes = get("writes")?;
        let shown = locked(&self.inner)
            .checked
            .iter()
            .find(|(sha, _)| *sha == build.sha256)
            .map(|(_, writes)| writes.clone());
        let Some(shown) = shown else {
            return Ok(refused(ReportRefusal::Changed.as_str()));
        };
        if !matches!(writes, Value::Array(_)) || !pyval::eq(&writes, &Value::Array(shown.clone())) {
            return Ok(refused(ReportRefusal::Changed.as_str()));
        }
        let (flow, runtime2, definition2) = (
            Arc::clone(self),
            Arc::clone(runtime),
            Arc::clone(definition),
        );
        Ok(self.start(
            runtime,
            definition,
            Box::new(move |context| flow.send(&runtime2, &definition2, &build, &shown, context)),
            true,
        ))
    }

    /// `job(job)`: how the job `job` is getting on: memory alone, whatever stands now. `lost` for one this process does
    /// not hold - it ended with another process, or was never started.
    pub fn job(&self, job: &Value) -> Value {
        let inner = locked(&self.inner);
        let status = match job {
            Value::Str(id) => id.as_str().and_then(|id| {
                inner
                    .jobs
                    .iter()
                    .find(|(each, _)| each == id)
                    .map(|(_, status)| status.clone())
            }),
            _ => None,
        };
        match status {
            Some(Value::Object(mut status)) => {
                // `dict(status, done=True, job=job)`.
                status.insert(Str::from("done"), Value::Bool(true));
                status.insert(Str::from("job"), job.clone());
                Value::Object(status)
            }
            _ => object(vec![
                ("done", Value::Bool(true)),
                ("status", Value::from(ReportStatus::Lost.as_str())),
            ]),
        }
    }

    // ------------------------------------------------------------------ standing
    /// `standing(runtime, definition, sending=)`: why nothing of the kind may be done now, or None: a policy, off, or - to
    /// check or send - watched. A policy is looked at first, since under one a capability reads as off.
    pub fn standing(
        &self,
        runtime: &Arc<dyn Runtime>,
        definition: &CapabilityDef,
        sending: bool,
    ) -> Result<Option<String>, String> {
        let policy = runtime.policy()?;
        if policy.forbid {
            return Ok(Some(Refusal::ForbiddenByPolicy.as_str().to_owned()));
        }
        if !policy.admits(&definition.id) {
            return Ok(Some(Refusal::NotAllowedByPolicy.as_str().to_owned()));
        }
        let state = runtime
            .state_of(&definition.id)?
            .unwrap_or(ArmingState::Off);
        if state == ArmingState::Off {
            return Ok(Some(ReportRefusal::NotOn.as_str().to_owned()));
        }
        if sending && state != ArmingState::Armed {
            let stored = runtime.stored_state(&definition.id).unwrap_or(None);
            return Ok(Some(
                if policy.force_shadow && stored == Some(ArmingState::Armed) {
                    Refusal::ShadowForcedByPolicy.as_str()
                } else {
                    ReportRefusal::Watched.as_str()
                }
                .to_owned(),
            ));
        }
        Ok(None)
    }

    /// `pause()`: why nothing may be checked or sent, or None: recovery paused, or a switch that cannot be read - a pull
    /// request cannot be taken back, so not knowing is no.
    pub fn pause(&self) -> Option<String> {
        match reading::paused(&self.paths) {
            None => Some(ReportRefusal::StateUnreadable.as_str().to_owned()),
            Some(true) => Some(ReportRefusal::Paused.as_str().to_owned()),
            Some(false) => None,
        }
    }

    // ------------------------------------------------------------------ writing and saving
    fn build(
        self: &Arc<Self>,
        runtime: &Arc<dyn Runtime>,
        definition: &Arc<CapabilityDef>,
        login: &Value,
    ) -> Value {
        let login = match document::check_login(login) {
            Ok(login) => login,
            Err(Fault::Refused(code)) => return refused(code),
            Err(Fault::Error(_)) => return refused(ReportRefusal::LoginInvalid.as_str()),
        };
        let (flow, runtime2, definition2) = (
            Arc::clone(self),
            Arc::clone(runtime),
            Arc::clone(definition),
        );
        self.start(
            runtime,
            definition,
            Box::new(move |_| flow.write(&runtime2, &definition2, &login)),
            false,
        )
    }

    fn write(&self, runtime: &Arc<dyn Runtime>, definition: &CapabilityDef, login: &str) -> Done {
        let home = match &self.config.codex_home {
            Some(home) => home.clone(),
            None => self.config.homes.home(&self.paths),
        };
        let world = World {
            os: Arc::clone(&self.config.os),
            clock: &*self.config.local_clock,
            watcher: &*self.config.watcher,
        };
        let seen = self
            .config
            .view
            .as_deref()
            .map(|view| view as &dyn WatcherView);
        let found = match records::read(
            &self.paths,
            &world,
            &home,
            None,
            (self.config.clock)(),
            seen,
        ) {
            Ok(found) => found,
            Err(reading::Refused::Code(code)) => return Ok(self.refused(runtime, definition, code)),
            Err(reading::Refused::Raised(class)) => return Err(class.to_owned()),
        };
        let login_value = Value::from(login);
        let made = document::assemble(
            &found.body,
            &login_value,
            self.config.product_version.as_deref(),
            self.config.windows.as_deref(),
            (self.config.clock)(),
            &*self.config.facts,
        );
        let made = match made {
            Ok(made) => made,
            Err(Fault::Refused(code)) => return Ok(self.refused(runtime, definition, code)),
            Err(Fault::Error(class)) => return Err(class.to_owned()),
        };
        let raw = match document::check(&made) {
            Ok(raw) => raw,
            Err(Fault::Refused(code)) => return Ok(self.refused(runtime, definition, code)),
            Err(Fault::Error(class)) => return Err(class.to_owned()),
        };
        let sha = car_machine::hash::hex(&car_machine::hash::sha256(raw.as_bytes()));
        {
            let mut inner = locked(&self.inner);
            inner.builds.retain(|build| build.sha256 != sha);
            inner.builds.push(Build {
                raw: raw.clone(),
                document: made.clone(),
                login: login.to_owned(),
                sha256: sha.clone(),
            });
            while inner.builds.len() > MAX_BUILDS {
                inner.builds.remove(0);
            }
        }
        let version = match &made {
            Value::Object(map) => map.get("codex_version").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let (target, branch) = github::destination(&version, &login_value).map_err(gh_class)?;
        self.note(runtime, definition, "built");
        let part = |name: &str| match &made {
            Value::Object(map) => map.get(name).cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let left_out = match found.value() {
            Value::Object(map) => map.get("left_out").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let count = match part("records") {
            Value::Array(records) => records.len() as i64,
            _ => 0,
        };
        Ok(object(vec![
            ("status", Value::from(ReportStatus::Built.as_str())),
            ("sha256", Value::from(sha)),
            ("bytes", Value::from(raw.len() as i64)),
            ("text", Value::from(raw)),
            ("codex_version", version),
            ("records", Value::from(count)),
            ("verdict", part("verdict")),
            ("left_out", left_out),
            ("login", Value::from(login)),
            (
                "file_name",
                Value::from(target.rsplit('/').next().unwrap_or_default()),
            ),
            ("branch", Value::from(branch)),
        ]))
    }

    /// `save(runtime, definition, sha, path)`: the report `sha` written to `path`, which the person chose, and never over a
    /// file.
    fn save(
        &self,
        runtime: &Arc<dyn Runtime>,
        definition: &CapabilityDef,
        sha: &Value,
        path: &Value,
    ) -> Result<Value, String> {
        let Some(build) = self.build_of(sha) else {
            return Ok(refused(ReportRefusal::UnknownBuild.as_str()));
        };
        let Value::Str(text) = path else {
            return Ok(refused(ReportRefusal::SaveFailed.as_str()));
        };
        let Some(text) = text.as_str() else {
            return Err("UnicodeEncodeError".to_owned());
        };
        let (drive, root, _) = winpath::parse(text);
        if text.is_empty() || drive.is_empty() || root.is_empty() {
            return Ok(refused(ReportRefusal::SaveFailed.as_str()));
        }
        if text.contains('\0') {
            return Err("ValueError".to_owned());
        }
        use std::io::Write;
        let written = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(Path::new(text))
            .and_then(|mut handle| handle.write_all(build.raw.as_bytes()));
        match written {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                return Ok(refused(ReportRefusal::FileExists.as_str()));
            }
            Err(_) => return Ok(refused(ReportRefusal::SaveFailed.as_str())),
        }
        self.note(runtime, definition, "saved");
        Ok(object(vec![
            ("done", Value::Bool(true)),
            ("status", Value::from(ReportStatus::Saved.as_str())),
        ]))
    }

    fn build_of(&self, sha: &Value) -> Option<Build> {
        let Value::Str(sha) = sha else {
            return None;
        };
        let sha = sha.as_str()?;
        locked(&self.inner)
            .builds
            .iter()
            .find(|build| build.sha256 == sha)
            .cloned()
    }

    // ------------------------------------------------------------------ checking and sending
    fn gh(&self) -> Option<String> {
        if let Some(find) = &self.config.find {
            return find();
        }
        let mut places = vec![self.paths.home.clone()];
        places.extend(self.config.unsafe_extra.iter().cloned());
        let cwd = std::env::current_dir()
            .map(|found| found.to_string_lossy().into_owned())
            .unwrap_or_default();
        github::find_gh(&*self.config.os, None, &places, &cwd)
    }

    fn inspect(&self, build: &Build) -> Result<Inspected, GhError> {
        github::inspect(
            build.raw.as_bytes(),
            &build.document,
            &build.login,
            self.gh().as_deref(),
            &self.paths.advanced_dir,
            &*self.config.runner,
        )
    }

    fn check(
        &self,
        runtime: &Arc<dyn Runtime>,
        definition: &CapabilityDef,
        build: &Build,
        context: &Arc<Mutex<Context>>,
    ) -> Done {
        let abandoned = locked(context).abandoned;
        if abandoned {
            self.note(runtime, definition, "lost");
        }
        let found = match self.inspect(build) {
            Ok(found) => found,
            Err(GhError::Refused(code)) => {
                return Ok(self.refused(runtime, definition, code.as_str()));
            }
            Err(other) => return Err(gh_class(other)),
        };
        let ready = match found {
            Inspected::Web(web) => return self.web(build, &web),
            Inspected::Sent(sent) => {
                self.note(runtime, definition, "sent");
                return Ok(object(vec![
                    ("status", Value::from(ReportStatus::Sent.as_str())),
                    ("url", Value::from(sent.url)),
                    ("already", Value::Bool(true)),
                ]));
            }
            Inspected::Ready(ready) => ready,
        };
        let writes = ready.writes();
        {
            let mut inner = locked(&self.inner);
            inner.checked.retain(|(sha, _)| *sha != build.sha256);
            inner.checked.push((build.sha256.clone(), writes.clone()));
        }
        self.note(runtime, definition, "checked");
        // The report's branch on the fork, with no pull request of it open (inspect read both), is the trace of a send
        // that ended part way; a fork alone is not - the person may have had it anyway.
        Ok(object(vec![
            ("status", Value::from(ReportStatus::Checked.as_str())),
            ("gh", Value::from(ready.exe.as_str())),
            ("who", Value::from(ready.who.as_str())),
            ("writes", Value::Array(writes)),
            ("interrupted", Value::Bool(abandoned || ready.has_branch)),
        ]))
    }

    fn web(&self, build: &Build, found: &github::Web) -> Done {
        let version = match &build.document {
            Value::Object(map) => map.get("codex_version").cloned().unwrap_or(Value::Null),
            _ => Value::Null,
        };
        let (target, branch) =
            github::destination(&version, &Value::from(build.login.as_str())).map_err(gh_class)?;
        Ok(object(vec![
            ("status", Value::from(ReportStatus::Web.as_str())),
            ("why", Value::from(found.why.as_str())),
            ("login", Value::from(build.login.as_str())),
            ("who", found.who.as_deref().map_or(Value::Null, Value::from)),
            ("branch", Value::from(branch)),
            (
                "file_name",
                Value::from(target.rsplit('/').next().unwrap_or_default()),
            ),
            ("target", Value::from(target)),
            ("project_page", Value::from(github::PROJECT_PAGE)),
        ]))
    }

    fn send(
        &self,
        runtime: &Arc<dyn Runtime>,
        definition: &CapabilityDef,
        build: &Build,
        shown: &[Value],
        context: &Arc<Mutex<Context>>,
    ) -> Done {
        let found = match self.inspect(build) {
            Ok(found) => found,
            Err(GhError::Refused(code)) => {
                return Ok(self.refused(runtime, definition, code.as_str()));
            }
            Err(other) => return Err(gh_class(other)),
        };
        let mut ready: Ready = match found {
            Inspected::Sent(sent) => {
                self.note(runtime, definition, "sent");
                return Ok(object(vec![
                    ("status", Value::from(ReportStatus::Sent.as_str())),
                    ("url", Value::from(sent.url)),
                    ("already", Value::Bool(true)),
                ]));
            }
            Inspected::Ready(ready)
                if pyval::eq(&Value::Array(ready.writes()), &Value::Array(shown.to_vec())) =>
            {
                ready
            }
            _ => return Ok(self.refused(runtime, definition, ReportRefusal::Changed.as_str())),
        };
        locked(context).written = Some(Vec::new());
        let mut before = || -> Result<(), GhError> {
            let why = match self.standing(runtime, definition, true) {
                Ok(Some(why)) => Some(why),
                Ok(None) => self.pause(),
                Err(class) => return Err(GhError::Raised(class)),
            };
            match why {
                Some(why) => Err(GhError::Stopped(why)),
                None => Ok(()),
            }
        };
        let sleep = |seconds: f64| (self.config.sleep)(seconds);
        let done = std::panic::catch_unwind(AssertUnwindSafe(|| {
            github::publish(
                &mut ready,
                build.raw.as_bytes(),
                &build.document,
                &mut before,
                &*self.config.runner,
                &sleep,
            )
        }));
        let url = match done {
            Ok(Ok(url)) => url,
            Ok(Err(GhError::Raised(class))) => {
                locked(context).written = Some(ready.written.clone());
                return Err(class);
            }
            Ok(Err(stop)) => {
                let code = stop.code().unwrap_or_default();
                if ready.written.is_empty() {
                    return Ok(self.refused(runtime, definition, &code));
                }
                self.note(runtime, definition, "partial");
                return Ok(object(vec![
                    ("status", Value::from(ReportStatus::Partial.as_str())),
                    ("written", Value::Array(ready.written.clone())),
                    ("refusal", Value::from(code)),
                ]));
            }
            Err(_panic) => {
                locked(context).written = Some(ready.written.clone());
                return Err("Panic".to_owned());
            }
        };
        self.note(runtime, definition, "sent");
        Ok(object(vec![
            ("status", Value::from(ReportStatus::Sent.as_str())),
            ("url", Value::from(url)),
            ("already", Value::Bool(false)),
        ]))
    }

    // ------------------------------------------------------------------ jobs
    /// `_start(runtime, definition, work, mutex=)`: `work` on a thread of its own, as this process's one job; with `mutex`,
    /// holding the home's report mutex throughout, or `busy` - without starting anything - where another holds it.
    fn start(
        self: &Arc<Self>,
        runtime: &Arc<dyn Runtime>,
        definition: &Arc<CapabilityDef>,
        work: Work,
        mutex: bool,
    ) -> Value {
        let job = {
            let mut inner = locked(&self.inner);
            if inner.running.is_some() {
                return refused(ReportRefusal::Busy.as_str());
            }
            let job = self.config.tokens.hex(8);
            inner.running = Some(job.clone());
            inner.jobs.retain(|(each, _)| *each != job);
            inner.jobs.push((
                job.clone(),
                object(vec![(
                    "status",
                    Value::from(ReportStatus::Running.as_str()),
                )]),
            ));
            while inner.jobs.len() > MAX_JOBS {
                inner.jobs.remove(0);
            }
            job
        };
        let taken = Arc::new((Mutex::new(false), Condvar::new()));
        let context = Arc::new(Mutex::new(Context::default()));
        let (flow, runtime2, definition2) = (
            Arc::clone(self),
            Arc::clone(runtime),
            Arc::clone(definition),
        );
        let (taken2, context2, job2) = (Arc::clone(&taken), Arc::clone(&context), job.clone());
        let run = move || {
            let mut lock: Option<Arc<dyn HomeMutex>> = None;
            let body = std::panic::catch_unwind(AssertUnwindSafe(|| -> bool {
                if mutex {
                    // Any exception making or taking the mutex is `busy`: nothing started, nothing held.
                    let taken_lock = std::panic::catch_unwind(AssertUnwindSafe(|| {
                        let made = {
                            let mut inner = locked(&flow.inner);
                            if inner.mutex.is_none() {
                                inner.mutex =
                                    Some(Arc::from((flow.config.make_mutex)(&flow.paths)));
                            }
                            inner.mutex.clone()
                        };
                        made.and_then(|made| made.take().ok().map(|abandoned| (made, abandoned)))
                    }));
                    match taken_lock {
                        Ok(Some((made, abandoned))) => {
                            lock = Some(made);
                            locked(&context2).abandoned = abandoned;
                        }
                        _ => {
                            locked(&context2).busy = true;
                            return false;
                        }
                    }
                }
                {
                    *locked(&taken2.0) = true;
                    taken2.1.notify_all();
                }
                let done = std::panic::catch_unwind(AssertUnwindSafe(|| work(&context2)))
                    .unwrap_or_else(|_| Err("Panic".to_owned()));
                let status = match done {
                    Ok(status) => status,
                    Err(_class) => {
                        // A fault of this code, never a refusal: the capability turns itself off.
                        runtime2.trip(&definition2.id, OffReason::HookException);
                        let written = locked(&context2).written.clone().unwrap_or_default();
                        if written.is_empty() {
                            object(vec![
                                ("status", Value::from(ReportStatus::Refused.as_str())),
                                ("refusal", Value::from(ReportRefusal::NotOn.as_str())),
                            ])
                        } else {
                            object(vec![
                                ("status", Value::from(ReportStatus::Partial.as_str())),
                                ("written", Value::Array(written)),
                                ("refusal", Value::from(ReportRefusal::NotOn.as_str())),
                            ])
                        }
                    }
                };
                let mut inner = locked(&flow.inner);
                if let Some(entry) = inner.jobs.iter_mut().find(|(each, _)| *each == job2) {
                    entry.1 = status;
                }
                true
            }));
            let _ = body;
            if let Some(lock) = lock {
                lock.give();
            }
            {
                let mut inner = locked(&flow.inner);
                if locked(&context2).busy {
                    inner.jobs.retain(|(each, _)| *each != job2);
                }
                if inner.running.as_deref() == Some(job2.as_str()) {
                    inner.running = None;
                }
            }
            *locked(&taken2.0) = true;
            taken2.1.notify_all();
        };
        let started = std::thread::Builder::new()
            .name("compat-report".to_owned())
            .spawn(run);
        if started.is_err() {
            let mut inner = locked(&self.inner);
            inner.jobs.retain(|(each, _)| *each != job);
            inner.running = None;
            return refused(ReportRefusal::Busy.as_str());
        }
        {
            let guard = locked(&taken.0);
            let _ =
                taken
                    .1
                    .wait_timeout_while(guard, Duration::from_secs_f64(START_SECONDS), |done| {
                        !*done
                    });
        }
        if locked(&context).busy {
            return refused(ReportRefusal::Busy.as_str());
        }
        object(vec![("done", Value::Bool(true)), ("job", Value::from(job))])
    }

    /// `wait(job, seconds=30.0)`: the job's status once it is no longer running, or as it stands after `seconds`: for
    /// tests.
    pub fn wait(&self, job: &str, seconds: f64) -> Value {
        let deadline = Instant::now() + Duration::from_secs_f64(seconds);
        let running = Value::from(ReportStatus::Running.as_str());
        while Instant::now() < deadline {
            let found = self.job(&Value::from(job));
            let status = match &found {
                Value::Object(map) => map.get("status").cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            };
            if !pyval::eq(&status, &running) {
                return found;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        self.job(&Value::from(job))
    }

    // ------------------------------------------------------------------ the journal
    fn refused(&self, runtime: &Arc<dyn Runtime>, definition: &CapabilityDef, code: &str) -> Value {
        self.note(runtime, definition, "refused");
        object(vec![
            ("status", Value::from(ReportStatus::Refused.as_str())),
            ("refusal", Value::from(code)),
        ])
    }

    fn note(&self, runtime: &Arc<dyn Runtime>, definition: &CapabilityDef, code: &str) {
        let _ = runtime.note(definition, code, (self.config.clock)());
    }
}

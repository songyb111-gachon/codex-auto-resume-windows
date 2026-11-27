//! `control/codexstart.py`: starting with Codex, and the one line it writes about what happened.
//!
//! v0.6.9 measured it: Codex runs each MCP server in a job object with KILL_ON_JOB_CLOSE and no breakaway, so a
//! watcher started there dies with the server. The refusal and the note are what is left, and they say which of
//! those two things happened. The edition's plug may name a route of its own (P9); the standard edition has none.
//!
//! The note's writers take turns on one byte locked past any end the file can have (`_note_turn`). That lock is a
//! Windows call car-platform does not have yet: [`Host::note_turn`](crate::host::Host) answers "no turn", so a line
//! is still appended and the file is cut only by a writer that has the turn (GROUNDWORK, S5.1b).

use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use car_machine::json::{Map, Value};
use car_machine::pytext::py_str;
use car_machine::pyval;
use car_policy::plug::{Answer, StartRoute};

use crate::error::Failure;
use crate::layer::{Control, State};
use crate::lifecycle::{LAUNCHER, OS_ERRORS};

/// `CODEX_START_LOG_LINES`.
pub const CODEX_START_LOG_LINES: usize = 50;
/// `CONFIRM_SECONDS`, `CONFIRM_POLL_SECONDS`, `HANDOVER_LOOKS`.
pub const CONFIRM_SECONDS: f64 = 8.0;
pub const CONFIRM_POLL_SECONDS: f64 = 0.5;
pub const HANDOVER_LOOKS: [f64; 2] = [4.0, 4.0];
/// `OUTCOMES`: what a start for Codex came to, in the words a plug's route is told, by the decision's opening words.
pub const OUTCOMES: &[(&str, &str)] = &[
    ("already running", "running"),
    ("started through WMI pid", "started"),
    ("started pid", "started"),
    ("start uncertain", "uncertain"),
    ("not started: recovery is paused", "paused"),
    ("not started: the watcher could not be asked", "unasked"),
    ("not started: an installation is in progress", "installing"),
    ("not started: not installed", "not_installed"),
    ("not started: WMI refused", "refused"),
    ("failed:", "failed"),
];

fn flag(context: &Value, name: &str) -> Value {
    pyval::get(context, name).cloned().unwrap_or(Value::Null)
}

/// `_context_words(context)`: windows.process_context as a few fixed words.
pub fn context_words(context: &Value) -> String {
    let empty = !pyval::truthy(context);
    let mut words = if empty || matches!(flag(context, "in_job"), Value::Null) {
        "job unknown".to_owned()
    } else if !pyval::truthy(&flag(context, "in_job")) {
        "not in a job".to_owned()
    } else {
        let flags: Vec<&str> = [
            ("kill_on_close", "kill on close"),
            ("breakaway_ok", "may leave"),
            ("silent_breakaway_ok", "children leave"),
        ]
        .iter()
        .filter(|(key, _)| pyval::truthy(&flag(context, key)))
        .map(|(_, name)| *name)
        .collect();
        let unknown = matches!(flag(context, "kill_on_close"), Value::Null);
        let inner = if unknown {
            "limits unknown".to_owned()
        } else if flags.is_empty() {
            "no limits read".to_owned()
        } else {
            flags.join(", ")
        };
        format!("in a job ({inner})")
    };
    if !empty && pyval::truthy(&flag(context, "packaged")) {
        words.push_str(", packaged");
    }
    words
}

/// `ends_with_job(context, leaving=False)`: whether a process this one starts is ended when the job closes.
pub fn ends_with_job(context: &Value, leaving: bool) -> Option<bool> {
    if !pyval::truthy(context) || matches!(flag(context, "in_job"), Value::Null) {
        return None;
    }
    if !pyval::truthy(&flag(context, "in_job"))
        || leaving
        || pyval::truthy(&flag(context, "silent_breakaway_ok"))
    {
        return Some(false);
    }
    match flag(context, "kill_on_close") {
        Value::Null => None,
        kill => Some(pyval::truthy(&kill)),
    }
}

/// `outcome_word(decision)`.
pub fn outcome_word(decision: &str) -> &'static str {
    OUTCOMES
        .iter()
        .find(|(opening, _)| decision.starts_with(opening))
        .map_or("other", |(_, word)| word)
}

/// `_tell(route, word)`: a plug's start route told what core made of it. Never raises: the route is the plug's code, and
/// what it does with the word changes nothing of core's (a panic in it is caught here, D15).
fn tell(route: &dyn StartRoute, word: &str) {
    let _ = car_machine::caught::catch(|| route.told(word));
}

/// `_word(held)`: a plug's reason as core writes one, `[a-z_]` 1 to 32 letters, or None.
pub fn held_word(held: &Value) -> Option<String> {
    let text = pyval::text(held)?;
    let count = text.chars().count();
    ((1..=32).contains(&count) && text.chars().all(|c| c == '_' || c.is_ascii_lowercase()))
        .then(|| text.to_owned())
}

/// `_started_pid(decision)`: the pid a "started" decision names, or None.
pub fn started_pid(decision: &str) -> Option<u32> {
    for opening in ["started through WMI pid ", "started pid "] {
        if let Some(rest) = decision.strip_prefix(opening) {
            let digits = car_machine::pytext::strip(rest.split(',').next().unwrap_or_default());
            return (!digits.is_empty() && digits.chars().all(|c| c.is_ascii_digit()))
                .then(|| digits.parse().ok())
                .flatten();
        }
    }
    None
}

/// `str.splitlines(keepends=True)` of bytes: `\n`, `\r\n` and `\r`.
fn byte_lines(data: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut at = 0;
    while at < data.len() {
        match data[at] {
            b'\n' => {
                lines.push(&data[start..=at]);
                start = at + 1;
            }
            b'\r' => {
                let end = if data.get(at + 1) == Some(&b'\n') {
                    at + 1
                } else {
                    at
                };
                lines.push(&data[start..=end]);
                at = end;
                start = end + 1;
            }
            _ => {}
        }
        at += 1;
    }
    if start < data.len() {
        lines.push(&data[start..]);
    }
    lines
}

impl Control {
    /// `_note_line(path, text)`: one timestamped line appended to a trimmed log. Best effort.
    pub fn note_line(&self, path: &Path, text: &str) {
        let parent = path.parent().unwrap_or(Path::new(""));
        if self.host.is_symlink(parent) || !parent.is_dir() || self.host.is_symlink(path) {
            return;
        }
        let stamp = match self.host.local_clock().localtime(self.host.now()) {
            Ok(tm) => format!(
                "[{:04}-{:02}-{:02} {:02}:{:02}:{:02}] ",
                tm.year, tm.mon, tm.mday, tm.hour, tm.min, tm.sec
            ),
            Err(_) => return,
        };
        // `open(path, "a+b")`: read and write, each write at the end (the C runtime seeks there first). Not std's
        // append mode, which opens without FILE_WRITE_DATA and so could never cut the file.
        let Ok(mut stream) = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
        else {
            return;
        };
        let turn = self.host.note_turn(&stream);
        let line = format!("{stamp}{text}\n");
        if stream.seek(SeekFrom::End(0)).is_err() || stream.write_all(line.as_bytes()).is_err() {
            return;
        }
        if turn {
            let mut data = Vec::new();
            if stream.seek(SeekFrom::Start(0)).is_err() || stream.read_to_end(&mut data).is_err() {
                return;
            }
            let lines = byte_lines(&data);
            if lines.len() > CODEX_START_LOG_LINES {
                let kept: Vec<u8> = lines[lines.len() - CODEX_START_LOG_LINES..].concat();
                if stream.set_len(0).is_ok() && stream.seek(SeekFrom::Start(0)).is_ok() {
                    let _ = stream.write_all(&kept);
                }
            }
        }
    }

    /// `launch_ends_with_job()`: whether a watcher Start watcher launches from this process ends when this
    /// process's job closes. Never raises.
    pub fn launch_ends_with_job(&self) -> Option<bool> {
        self.host
            .process_context()
            .ok()
            .and_then(|context| ends_with_job(&context, false))
    }

    /// `start_for_codex(confirm_seconds=0)`: the watcher started because Codex started this plugin's MCP server - if
    /// asked to. Never raises; returns the one line it records in logs/codex-start.log.
    pub fn start_for_codex(&self, confirm_seconds: f64) -> String {
        let mut context = Value::Object(Map::new());
        let mut named: Vec<Box<dyn StartRoute>> = Vec::new();
        let decision = match self.host.process_context() {
            Ok(found) => {
                context = found;
                match self.decide_for_codex(&context, &mut named) {
                    Ok(decision) => decision,
                    Err(class) => format!("failed: {class}"),
                }
            }
            Err(raised) => format!("failed: {}", raised.class),
        };
        let line = format!(
            "pid {}; {}; {}",
            self.host.pid(),
            context_words(&context),
            decision
        );
        self.note_line(&PathBuf::from(&self.paths.codex_start_log), &line);
        // v0.6.16-beta.3 (issue #31): a route the plug named is told what core made of it.
        let route = named.first().map(|route| &**route);
        if let Some(route) = route {
            tell(route, outcome_word(&decision));
        }
        if confirm_seconds > 0.0 {
            self.confirm_codex_start(&decision, route, confirm_seconds);
        }
        line
    }

    /// `_confirm_codex_start(decision, route, seconds)`: whether the watcher a start for Codex just made is still
    /// there `seconds` later, said in a second line only where it is not. Never raises.
    fn confirm_codex_start(&self, decision: &str, route: Option<&dyn StartRoute>, seconds: f64) {
        let Some(pid) = started_pid(decision) else {
            return;
        };
        let deadline = self.host.monotonic() + seconds;
        let mut gone = false;
        while self.host.monotonic() < deadline {
            if !self.host.process_there(pid) {
                gone = true;
                break;
            }
            self.host.sleep(CONFIRM_POLL_SECONDS);
        }
        if !gone {
            return;
        }
        for wait in HANDOVER_LOOKS {
            self.host.sleep(wait);
            if self.watcher_running() == Some(true) {
                return;
            }
        }
        self.note_line(
            &PathBuf::from(&self.paths.codex_start_log),
            &format!(
                "pid {}; the watcher started as pid {pid} ended within {} s (see logs/errors.log)",
                self.host.pid(),
                seconds.trunc() as i64
            ),
        );
        if let Some(route) = route {
            tell(route, "ended");
        }
    }

    /// `_start_for_codex(context, named)`: the decision itself. The error is the class of what was raised.
    fn decide_for_codex(
        &self,
        context: &Value,
        named: &mut Vec<Box<dyn StartRoute>>,
    ) -> Result<String, String> {
        let class = |failure: Failure| match failure {
            Failure::Control(_) => "ControlError".to_owned(),
            Failure::Other(class) => class,
        };
        let settings = self.get_settings().map_err(class)?;
        let setting_on = settings.get("start_with_codex").is_some_and(pyval::truthy);
        let in_job = pyval::truthy(&flag(context, "in_job"));
        let breakaway = in_job
            && pyval::truthy(&flag(context, "breakaway_ok"))
            && !pyval::truthy(&flag(context, "silent_breakaway_ok"));
        let job_ends = ends_with_job(context, breakaway) == Some(true);
        // A route the plug names goes into `named` at once, as the reference appends it: a refusal after it was named
        // is told to it too.
        if !setting_on {
            match self.plug().start_route(context) {
                Answer::Is(found) => named.push(found),
                Answer::Defer => {
                    return Ok(match held_word(&self.plug().start_held()) {
                        Some(held) => format!("off (held: {held})"),
                        None => "off".to_owned(),
                    });
                }
            }
        }
        if self.paused_for_codex().map_err(class)? {
            return Ok("not started: recovery is paused".to_owned());
        }
        match self.watcher_running() {
            Some(true) => return Ok("already running".to_owned()),
            None => return Ok("not started: the watcher could not be asked".to_owned()),
            Some(false) => {}
        }
        if self.host.install_in_progress() != Some(false) {
            return Ok("not started: an installation is in progress".to_owned());
        }
        if !self.home_dir().join(LAUNCHER).is_file() {
            return Ok("not started: not installed".to_owned());
        }
        if job_ends {
            if named.is_empty()
                && let Answer::Is(found) = self.plug().start_route(context)
            {
                named.push(found);
            }
            let Some(route) = named.first() else {
                return Ok("not started: this Codex ends what its plugins start".to_owned());
            };
            return self.start_through_route(&**route);
        }
        if self.host.install_in_progress() != Some(false) {
            return Ok("not started: an installation is in progress".to_owned());
        }
        let extra = if breakaway {
            car_platform::spawn::CREATE_BREAKAWAY_FROM_JOB
        } else {
            0
        };
        let (process, left) = match self.launch_watcher(extra, true).map_err(class)? {
            Ok(process) => (process, breakaway),
            Err(raised) if !breakaway => return Err(raised.class),
            Err(_) => match self.launch_watcher(0, true).map_err(class)? {
                Ok(process) => (process, false),
                Err(raised) => return Err(raised.class),
            },
        };
        let tail = if left {
            ", out of the job"
        } else if in_job {
            ", inside the job"
        } else {
            ""
        };
        Ok(format!("started pid {}{tail}", process.pid()))
    }

    /// `_paused()`: the global switch turned off in a state that already exists. Never raises a refusal.
    fn paused_for_codex(&self) -> Result<bool, Failure> {
        if !PathBuf::from(&self.paths.state_dir)
            .join("state.sqlite")
            .is_file()
        {
            return Ok(false);
        }
        let enabled = match self.open(true) {
            Ok(State::Current(store)) => store.settings().map(|row| row.get("enabled").cloned()),
            Ok(State::Legacy(store)) => store.settings().map(|row| row.get("enabled").cloned()),
            Err(Failure::Control(_)) => return Ok(false),
            Err(other) => return Err(other),
        };
        match enabled {
            Ok(value) => Ok(!value.as_ref().is_some_and(pyval::truthy)),
            Err(error) => Err(crate::layer::from_store(error)),
        }
    }

    /// `_start_through_route(route)`: a plug's start route carried out, and what happened said.
    fn start_through_route(&self, route: &dyn StartRoute) -> Result<String, String> {
        if self.host.install_in_progress() != Some(false) {
            return Ok("not started: an installation is in progress".to_owned());
        }
        let python = self.host.python_launcher().map_err(|raised| raised.class)?;
        let command = car_platform::startup::command_line(
            &self.home_dir().join(LAUNCHER),
            None,
            &python.to_string_lossy(),
            &car_platform::startup::NO_REMOTE_DEBUG,
        );
        let outcome = route.start(&[command]);
        let outcome = match outcome {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        if let Some(pid) = outcome.get("pid") {
            let positive = match pid {
                Value::Bool(true) => Some(1),
                Value::Int(int) => int.as_i64().filter(|n| *n > 0),
                _ => None,
            };
            if let Some(pid) = positive {
                return Ok(format!("started through WMI pid {pid}"));
            }
        }
        if let Some(uncertain) = outcome.get("uncertain") {
            return Ok(format!(
                "start uncertain: WMI did not answer ({})",
                py_str(uncertain)
            ));
        }
        let code = match outcome.get("code") {
            None | Some(Value::Null) => "no pid".to_owned(),
            Some(code) => py_str(code),
        };
        let _ = OS_ERRORS;
        Ok(format!("not started: WMI refused ({code})"))
    }
}

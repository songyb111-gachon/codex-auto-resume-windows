//! A weekly update check while idle (`idle_update_check`, v0.6.18): the Dashboard's Check for updates, run by the
//! watcher once a week (seat S7.2e2, `engine/updatecheck.py`).
//!
//! At most once in WEEK, only while no recovery is waiting, being sent or being watched, at P8 as an errand that starts
//! the check on a thread of its own: this installation's `scripts\bootstrap.ps1 -CheckOnly`, run by Windows PowerShell
//! from System32 by full path with no console, waited for at most CHECK_SECONDS and never killed. Its answer is read as
//! the window reads it (`offer`). An administrator's DisableUpdateCheck means no check. What it offers is kept as
//! stamps (`encode`) so a watcher that starts again shows it once in its life, until it is installed or put away. Each
//! check that ends says what it did in the watcher's log in one English line (`said`). It never downloads or installs
//! anything. It talks to GitHub through the script: a seat never runs it (P7-DESIGN 4); every diff hands `run`.

use std::ffi::OsString;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use car_config::Paths;
use car_machine::json::Value;
use car_machine::vocab_gen::domain_states::{CLAIMED, IN_FLIGHT, OBSERVING, WAITING};
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::supervise::{Bound, lock, word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "idle_update_check";
pub const WEEK: i64 = 7 * 86400;
pub const CHECK_SECONDS: f64 = 120.0;
pub const LOOK_EVERY: f64 = 60.0;
/// The answers of `-CheckOnly`: the `update:` line's first word, with the exit code it comes with.
pub const ANSWERS: [(&str, i64); 4] = [("current", 0), ("available", 10), ("newer-local", 11), ("unavailable", 12)];
pub const HOME_VARIABLE: &str = "CODEX_AUTO_RESUME_PLUGIN_HOME";
pub const INSTALL_VARIABLES: [&str; 2] = ["CODEX_AUTO_RESUME_UPDATING_DASHBOARD", "CODEX_AUTO_RESUME_PROGRESS_LINES"];
pub const MISSING: &str = "missing";
pub const NOT_STARTED: &str = "not_started";
pub const RUNNING: &str = "running";
/// The Dashboard's words for a check that did not answer: their key in the English catalog and the English beside it.
pub const COULD_NOT: [(&str, &str, &str); 4] = [
    (
        "unavailable",
        "diag.update_could_not_ask",
        "GitHub could not be asked just now. This says nothing about whether an update exists.",
    ),
    (
        MISSING,
        "diag.update_incomplete",
        "Files this installation is made of are missing, so it could not be checked. Install it again from the release archive.",
    ),
    (
        RUNNING,
        "diag.update_running",
        "It is taking longer than usual and is still working. It carries on in the background; look at this page again in a few minutes.",
    ),
    ("failed", "diag.update_failed", "The update check did not finish."),
];
pub const LOG_PREFIX: &str = "weekly update check: ";

// ---------------------------------------------------------------------------------------------- versions
/// `(0|[1-9][0-9]{0,5})` at the start of `text`: the number and the rest.
fn number_part(text: &str) -> Option<(i64, &str)> {
    let bytes = text.as_bytes();
    if bytes.first() == Some(&b'0') {
        return Some((0, &text[1..]));
    }
    let digits = bytes.iter().take_while(|byte| byte.is_ascii_digit()).count();
    if digits == 0 || bytes[0] == b'0' {
        return None;
    }
    // `[1-9][0-9]{0,5}` takes at most six digits; a seventh is left for what follows (and fails it).
    let taken = digits.min(6);
    Some((text[..taken].parse().ok()?, &text[taken..]))
}

/// PRODUCT_RELEASE at the start of `text`: the three numbers and the rest.
fn release_prefix(text: &str) -> Option<([i64; 3], &str)> {
    let (major, rest) = number_part(text)?;
    let rest = rest.strip_prefix('.')?;
    let (minor, rest) = number_part(rest)?;
    let rest = rest.strip_prefix('.')?;
    let (patch, rest) = number_part(rest)?;
    Some(([major, minor, patch], rest))
}

/// `RELEASE.match(text)`: `PRODUCT_RELEASE\Z`.
pub fn release(text: &str) -> Option<[i64; 3]> {
    match release_prefix(text)? {
        (numbers, "") => Some(numbers),
        _ => None,
    }
}

/// `PRERELEASE.match(text)`: the numbers, the stage, and the stage's number (None for none).
pub fn prerelease(text: &str) -> Option<([i64; 3], &'static str, Option<i64>)> {
    let (numbers, rest) = release_prefix(text)?;
    let rest = rest.strip_prefix('-')?;
    let (stage, rest) = if let Some(rest) = rest.strip_prefix("alpha") {
        ("alpha", rest)
    } else {
        ("beta", rest.strip_prefix("beta")?)
    };
    if rest.is_empty() {
        return Some((numbers, stage, None));
    }
    let digits = rest.strip_prefix('.')?;
    // `([2-9]|[1-9][0-9]{1,2})\Z`
    let bytes = digits.as_bytes();
    let fits = match bytes.len() {
        1 => (b'2'..=b'9').contains(&bytes[0]),
        2 | 3 => (b'1'..=b'9').contains(&bytes[0]) && bytes[1..].iter().all(u8::is_ascii_digit),
        _ => false,
    };
    fits.then(|| (numbers, stage, digits.parse().ok()))
}

/// `_last(printed, name)`: the rest of the last line of `printed` that starts with `name`, or None.
pub fn last(printed: &str, name: &str) -> Option<String> {
    let mut found = None;
    for line in printed.replace('\r', "").split('\n') {
        let line = car_machine::pytext::strip(line);
        if let Some(rest) = line.strip_prefix(name) {
            found = Some(rest.to_owned());
        }
    }
    found
}

fn answer_code(said: &str) -> Option<i64> {
    ANSWERS.iter().find(|(word, _)| *word == said).map(|(_, code)| *code)
}

/// `str.split(" ")` of the `update:` line, or nothing where there is none.
fn words_of(printed: &str) -> Vec<String> {
    last(printed, "update: ").map_or_else(Vec::new, |line| line.split(' ').map(str::to_owned).collect())
}

/// `offer(code, printed)`: (version, False) for a newer release, (version, True) for a newer pre-release, or None.
pub fn offer(code: &Value, printed: &str) -> Option<(String, bool)> {
    let words = words_of(printed);
    let said = words.first().map_or("", String::as_str);
    let expected = answer_code(said)?;
    if !car_store::value::py_eq(&Value::Int(expected.into()), code) {
        return None;
    }
    if said == "available" {
        let latest = words.get(2).map_or("", String::as_str);
        return release(latest).map(|_| (latest.to_owned(), false));
    }
    if said == "current" || said == "newer-local" {
        let pre = last(printed, "prerelease: ")?;
        let tail = pre.strip_prefix('v')?;
        if prerelease(tail).is_some() {
            return Some((tail.to_owned(), true));
        }
    }
    None
}

/// `english(why)`: the Dashboard's English words for a check that did not answer.
pub fn english(why: &str) -> String {
    let (_, key, fallback) = COULD_NOT
        .iter()
        .find(|(name, _, _)| *name == why)
        .unwrap_or(&COULD_NOT[3]);
    let mut text = car_words::l10n::text(key, "en", &[]).unwrap_or_else(|| (*fallback).to_owned());
    if why == RUNNING {
        let head = text.split(';').next().unwrap_or("").trim_end_matches('.').to_owned();
        text = head + ".";
    }
    text
}

/// What a check that ended answered: (exit code, what it printed), or None.
pub type Answered = Option<(Value, String)>;

/// `said(answered, why)`: the watcher's log line for a check that ended - versions only.
pub fn said(answered: &Answered, why: Option<&str>) -> String {
    let Some((code, printed)) = answered else {
        let why = why.filter(|why| *why == MISSING || *why == RUNNING).unwrap_or("failed");
        return format!("{LOG_PREFIX}could not check: {}", english(why));
    };
    if let Some((version, prerelease)) = offer(code, printed) {
        return if prerelease {
            format!("{LOG_PREFIX}pre-release v{version} offered")
        } else {
            format!("{LOG_PREFIX}v{version} offered")
        };
    }
    let words = words_of(printed);
    let answer = words.first().and_then(|first| {
        answer_code(first)
            .filter(|expected| car_store::value::py_eq(&Value::Int((*expected).into()), code))
            .map(|_| first.as_str())
    });
    let mut shown: Vec<&str> = words
        .iter()
        .skip(1)
        .take(2)
        .map(|word| if release(word).is_some() { word.as_str() } else { "?" })
        .collect();
    shown.extend(["?", "?"]);
    match answer {
        Some("current") => format!(
            "{LOG_PREFIX}checked, nothing newer: v{} is the newest published release",
            shown[0]
        ),
        Some("newer-local") => format!(
            "{LOG_PREFIX}checked, nothing newer: this build is ahead of the newest published release, v{}",
            shown[1]
        ),
        Some("unavailable") => format!("{LOG_PREFIX}could not check: {}", english("unavailable")),
        _ => format!("{LOG_PREFIX}could not check: {}", english("failed")),
    }
}

/// `_parts(version)`: (major, minor, patch, stage) - 9999 for a release, 1000/2000 and the stage's number otherwise.
fn parts(version: &str) -> Option<[i64; 4]> {
    let (numbers, stage) = match release(version) {
        Some(numbers) => (numbers, 9999),
        None => {
            let (numbers, stage, number) = prerelease(version)?;
            (numbers, if stage == "alpha" { 1000 } else { 2000 } + number.unwrap_or(1))
        }
    };
    numbers
        .iter()
        .all(|number| *number < 1000)
        .then_some([numbers[0], numbers[1], numbers[2], stage])
}

/// `encode(version)`: one whole number from 1 that keeps the versions' order, or None.
pub fn encode(version: &Value) -> Option<i64> {
    let Value::Str(text) = version else {
        return None;
    };
    let [major, minor, patch, stage] = parts(text.as_str()?)?;
    Some(((major * 1000 + minor) * 1000 + patch) * 10000 + stage)
}

/// `decode(value)`: (version, prerelease) of a number `encode` made, or None.
pub fn decode(value: &Value) -> Option<(String, bool)> {
    let Value::Int(number) = value else {
        return None;
    };
    let value = number.as_i64()?;
    if value < 1 {
        return None;
    }
    let (stage, rest) = (value % 10000, value / 10000);
    let (patch, rest) = (rest % 1000, rest / 1000);
    let (minor, major) = (rest % 1000, rest / 1000);
    if major >= 1000 {
        return None;
    }
    let base = format!("{major}.{minor}.{patch}");
    let (version, prerelease) = if stage == 9999 {
        (base, false)
    } else if (1001..=1999).contains(&stage) || (2001..=2999).contains(&stage) {
        let number = stage % 1000;
        let name = if stage < 2000 { "-alpha" } else { "-beta" };
        let tail = if number == 1 { String::new() } else { format!(".{number}") };
        (format!("{base}{name}{tail}"), true)
    } else {
        return None;
    };
    (encode(&word(&version)) == Some(value)).then_some((version, prerelease))
}

/// `script_of(paths)`: `<home>\app\scripts\bootstrap.ps1`.
pub fn script_of(paths: &Paths) -> PathBuf {
    Path::new(&paths.home).join("app").join("scripts").join("bootstrap.ps1")
}

// ---------------------------------------------------------------------------------------------- the check
/// A child's exit code as Python's `returncode` (Windows' unsigned exit code).
fn returncode(status: std::process::ExitStatus) -> i64 {
    status.code().map_or(-1, |code| i64::from(code as u32))
}

/// `process.communicate(timeout=seconds)`: (exit code, stdout, stderr), or the child back where it has not ended
/// in time (its pipes still drained by threads of their own, as `communicate` after a TimeoutExpired would).
pub(crate) fn communicate(
    mut child: Child,
    seconds: f64,
) -> Result<(i64, Vec<u8>, Vec<u8>), (Child, ReadBack)> {
    let reader = |stream: Option<Box<dyn Read + Send>>| {
        let kept = Arc::new(Mutex::new(Vec::new()));
        let writing = kept.clone();
        let handle = stream.map(|mut stream| {
            std::thread::spawn(move || {
                let mut buffer = [0u8; 8192];
                while let Ok(count) = stream.read(&mut buffer) {
                    if count == 0 {
                        break;
                    }
                    lock(&writing).extend_from_slice(&buffer[..count]);
                }
            })
        });
        (kept, handle)
    };
    let out = reader(child.stdout.take().map(|s| Box::new(s) as Box<dyn Read + Send>));
    let err = reader(child.stderr.take().map(|s| Box::new(s) as Box<dyn Read + Send>));
    let started = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                let code = returncode(status);
                for handle in [out.1, err.1].into_iter().flatten() {
                    let _ = handle.join();
                }
                let stdout = lock(&out.0).clone();
                let stderr = lock(&err.0).clone();
                return Ok((code, stdout, stderr));
            }
            Ok(None) if started.elapsed().as_secs_f64() < seconds => {
                std::thread::sleep(Duration::from_millis(20));
            }
            _ => return Err((child, ReadBack { out, err })),
        }
    }
}

type Drain = (Arc<Mutex<Vec<u8>>>, Option<std::thread::JoinHandle<()>>);

/// The pipes of a child that has not ended in time, still drained.
pub(crate) struct ReadBack {
    out: Drain,
    err: Drain,
}

impl ReadBack {
    /// What the child printed once it ended (the readers joined).
    pub(crate) fn finish(self) -> (Vec<u8>, Vec<u8>) {
        for handle in [self.out.1, self.err.1].into_iter().flatten() {
            let _ = handle.join();
        }
        let stdout = lock(&self.out.0).clone();
        let stderr = lock(&self.err.0).clone();
        (stdout, stderr)
    }
}

/// `run_check(script, home, seconds, said)`: the check run as the Dashboard runs it; None, with why on `said`, where
/// Windows PowerShell or the script is not there, it could not be started, or it has not finished - then it is left to
/// finish on its own, never killed.
pub fn run_check(script: &Path, home: &str, seconds: f64, said: &mut Vec<&'static str>) -> Answered {
    let powershell = car_platform::pwsh::executable();
    if !script.is_file() {
        said.push(MISSING);
        return None;
    }
    let Some(powershell) = powershell else {
        said.push(NOT_STARTED);
        return None;
    };
    let mut environment: Vec<(OsString, OsString)> = std::env::vars_os()
        .filter(|(name, _)| {
            let name = name.to_string_lossy().to_uppercase();
            name != HOME_VARIABLE && !INSTALL_VARIABLES.contains(&name.as_str())
        })
        .collect();
    environment.push((HOME_VARIABLE.into(), home.into()));
    let spawn = car_platform::spawn::Spawn::new([
        powershell.to_string_lossy().into_owned(),
        "-NoProfile".into(),
        "-NonInteractive".into(),
        "-ExecutionPolicy".into(),
        "Bypass".into(),
        "-File".into(),
        script.to_string_lossy().into_owned(),
        "-CheckOnly".into(),
    ])
    .with_env(environment)
    .with_streams(
        car_platform::spawn::Stream::Null,
        car_platform::spawn::Stream::Piped,
        car_platform::spawn::Stream::Piped,
    );
    let Ok(child) = car_platform::spawn::SystemStarter.start(&spawn) else {
        said.push(NOT_STARTED);
        return None;
    };
    match communicate(child, seconds) {
        Ok((code, printed, _errors)) => {
            Some((Value::Int(code.into()), String::from_utf8_lossy(&printed).into_owned()))
        }
        Err((child, back)) => {
            // Left to finish, as the window leaves a check it calls "running": what it prints is read and dropped.
            std::thread::spawn(move || {
                let mut child = child;
                let _ = child.wait();
                let _ = back.finish();
            });
            said.push(RUNNING);
            None
        }
    }
}

// ---------------------------------------------------------------------------------------------- the seams
/// `run(script, home)`: a check, as `run_check` answers; the stand-in a test hands. `None` uses `run_check` itself.
pub type Run = Box<dyn Fn(&Path, &str) -> Result<Answered, Raised> + Send + Sync>;
/// `managed()`: whether an administrator's DisableUpdateCheck is set (`False` lets a check start).
pub type Managed = Box<dyn Fn() -> Result<Value, Raised> + Send + Sync>;
/// How the check's thread is started.
pub type Start = Box<dyn Fn(Box<dyn FnOnce() + Send>) -> Result<(), Raised> + Send + Sync>;
/// The version installed here (`config.version`), or None.
pub type Installed = Box<dyn Fn() -> Result<Value, Raised> + Send + Sync>;
/// One line in the watcher's log.
pub type Log = Box<dyn Fn(&str) -> Result<(), Raised> + Send + Sync>;

/// The product's administrator switch: core's managed policy, as an installed copy reads it.
pub fn managed_policy() -> Result<Value, Raised> {
    let registry = car_platform::registry::WinRegistry::current_user();
    let managed = car_policy::settings::managed::parse(&Value::Array(
        car_platform::registry_reads::policy_places(&registry),
    ));
    Ok(Value::Bool(managed.disable_update_check))
}

/// The product's start: a daemon thread.
pub fn thread_start(target: Box<dyn FnOnce() + Send>) -> Result<(), Raised> {
    std::thread::Builder::new()
        .spawn(target)
        .map(|_| ())
        .map_err(|_| Raised::new("RuntimeError"))
}

// ---------------------------------------------------------------------------------------------- the code
#[derive(Default)]
struct Held {
    offered: Option<(String, bool)>,
    offered_at: Option<i64>,
    found: Option<(String, bool)>,
    said: Option<&'static str>,
    line: Option<String>,
    running: bool,
}

struct Inner {
    paths: Paths,
    bound: Mutex<Option<Bound>>,
    run: Option<Run>,
    managed: Managed,
    start: Start,
    installed: Installed,
    log: Log,
    held: Mutex<Held>,
    looked: Mutex<Option<f64>>,
    loaded: Mutex<bool>,
}

/// `IdleUpdateCheck(paths, run=..., managed=..., start=..., installed=..., log=...)`.
#[derive(Clone)]
pub struct IdleUpdateCheck {
    inner: Arc<Inner>,
}

type Answer<T> = Result<T, Raised>;

impl IdleUpdateCheck {
    pub fn new(
        paths: Paths,
        run: Option<Run>,
        managed: Managed,
        start: Start,
        installed: Installed,
        log: Log,
    ) -> IdleUpdateCheck {
        IdleUpdateCheck {
            inner: Arc::new(Inner {
                paths,
                bound: Mutex::new(None),
                run,
                managed,
                start,
                installed,
                log,
                held: Mutex::new(Held::default()),
                looked: Mutex::new(None),
                loaded: Mutex::new(false),
            }),
        }
    }

    /// `bind(scoped)` with a harness's own state.
    pub fn bind_to(&self, bound: Bound) {
        *lock(&self.inner.bound) = Some(bound);
    }

    fn bound(&self) -> Answer<Bound> {
        lock(&self.inner.bound)
            .clone()
            .ok_or_else(|| Raised::new("AttributeError"))
    }

    /// P8: settle what a check came to, then - looked at every LOOK_EVERY - an errand where a check is due.
    pub fn ticked(&self, view: &dyn View) -> Spoke {
        let Ok(bound) = self.bound() else {
            return Ok(Said::Defer);
        };
        let _ = self.settle(&bound);
        let Ok(now) = bound.now() else {
            return Ok(Said::Defer);
        };
        let looked = *lock(&self.inner.looked);
        if let Some(looked) = looked
            && 0.0 <= now - looked
            && now - looked < LOOK_EVERY
        {
            return Ok(Said::Defer);
        }
        *lock(&self.inner.looked) = Some(now);
        match self.due(&bound, view, now) {
            Ok(true) => Ok(Said::Errand(Box::new(CheckErrand(self.clone(), now)))),
            _ => Ok(Said::Defer),
        }
    }

    /// `_due(view, now)`.
    fn due(&self, bound: &Bound, view: &dyn View, now: f64) -> Answer<bool> {
        if lock(&self.inner.held).running {
            return Ok(false);
        }
        let last = bound.read(|scoped| scoped.stamped(&word(OptionKey::LastCheck.as_str())))?;
        if let Value::Int(last) = last
            && let Some(last) = last.as_i64()
            && 0.0 <= now - last as f64
            && now - (last as f64) < WEEK as f64
        {
            return Ok(false);
        }
        if busy(view) {
            return Ok(false);
        }
        if (self.inner.managed)()? != Value::Bool(false) {
            return Ok(false);
        }
        Ok(script_of(&self.inner.paths).is_file())
    }

    /// The errand: the time of this check kept first, then the check started on a thread of its own.
    pub fn start(&self, now: f64) -> Answer<()> {
        let bound = self.bound()?;
        let whole = super::anchor::whole(now).map_err(Raised::new)?;
        let kept = bound.read(|scoped| {
            scoped.stamp(&word(OptionKey::LastCheck.as_str()), &Value::Int(whole.into()))
        })?;
        if !kept {
            return Ok(());
        }
        {
            let mut held = lock(&self.inner.held);
            if held.running {
                return Ok(());
            }
            held.running = true;
        }
        let checking = self.clone();
        if (self.inner.start)(Box::new(move || checking.check())).is_err() {
            lock(&self.inner.held).running = false;
        }
        Ok(())
    }

    /// `_check()`: the check, on its own thread - what it offers, kept at once, and its word for the next tick.
    pub fn check(&self) {
        let paths = &self.inner.paths;
        let mut why: Vec<&'static str> = Vec::new();
        let answered = match &self.inner.run {
            None => Ok(run_check(&script_of(paths), &paths.home, CHECK_SECONDS, &mut why)),
            Some(run) => run(&script_of(paths), &paths.home),
        };
        let (found, word_said, line) = match answered {
            Ok(answered) => {
                let found = answered
                    .as_ref()
                    .and_then(|(code, printed)| offer(code, printed));
                let word_said = if answered.is_none() {
                    "unanswered"
                } else if found.is_some() {
                    "offered"
                } else {
                    "checked"
                };
                let line = said(&answered, why.first().copied());
                (found, word_said, line)
            }
            Err(_) => (
                None,
                "unanswered",
                format!("{LOG_PREFIX}could not check: {}", english("failed")),
            ),
        };
        let mut held = lock(&self.inner.held);
        if found.is_some() {
            held.offered = found.clone();
        }
        held.found = found;
        held.said = Some(word_said);
        held.line = Some(line);
        held.running = false;
    }

    /// `_settle()`: a check that ended counted and what it found kept; the kept offer read once; dropped where the
    /// version installed reached it or it was found before the capability last stood on.
    fn settle(&self, bound: &Bound) -> Answer<()> {
        let (said_word, found, line) = {
            let mut held = lock(&self.inner.held);
            (held.said.take(), held.found.take(), held.line.take())
        };
        if let Some(line) = line {
            let _ = (self.inner.log)(&line);
        }
        if let Some(said_word) = said_word {
            let _ = bound.with(|scoped| scoped.count(&word(said_word)));
        }
        if said_word == Some("offered") {
            if let Some(found) = found {
                let now = bound.now()?;
                self.keep(bound, found, super::anchor::whole(now).map_err(Raised::new)?)?;
            }
        } else if said_word == Some("checked") {
            self.drop_offer(bound)?;
        }
        let first = {
            let mut loaded = lock(&self.inner.loaded);
            let first = !*loaded;
            *loaded = true;
            first
        };
        if first {
            let kept = decode(&bound.read(|scoped| scoped.stamped(&word(OptionKey::OfferedVersion.as_str())))?);
            let at = bound.read(|scoped| scoped.stamped(&word(OptionKey::OfferedAt.as_str())))?;
            if let (Some(kept), Value::Int(at)) = (kept, at)
                && let Some(at) = at.as_i64()
            {
                let mut held = lock(&self.inner.held);
                held.offered = Some(kept);
                held.offered_at = Some(at);
            }
        }
        let (offered, at) = {
            let held = lock(&self.inner.held);
            (held.offered.clone(), held.offered_at)
        };
        let Some(offered) = offered else {
            return Ok(());
        };
        let installed = encode(&(self.inner.installed)()?);
        let reached = installed.is_some_and(|installed| installed >= encode(&word(&offered.0)).unwrap_or(0));
        let since = bound.read(|scoped| scoped.since())?;
        let put_away = match (super::supervise::number(&since), at) {
            (Some(since), Some(at)) => (at as f64) < since,
            _ => false,
        };
        if reached || put_away {
            self.drop_offer(bound)?;
        }
        Ok(())
    }

    fn keep(&self, bound: &Bound, found: (String, bool), now: i64) -> Answer<()> {
        let code = encode(&word(&found.0));
        {
            let mut held = lock(&self.inner.held);
            held.offered = Some(found);
            held.offered_at = Some(now);
        }
        if let Some(code) = code {
            bound.read(|scoped| scoped.stamp(&word(OptionKey::OfferedVersion.as_str()), &Value::Int(code.into())))?;
            bound.read(|scoped| scoped.stamp(&word(OptionKey::OfferedAt.as_str()), &Value::Int(now.into())))?;
        }
        Ok(())
    }

    fn drop_offer(&self, bound: &Bound) -> Answer<()> {
        {
            let mut held = lock(&self.inner.held);
            held.offered = None;
            held.offered_at = None;
        }
        for key in [OptionKey::OfferedVersion, OptionKey::OfferedAt] {
            bound.read(|scoped| scoped.unstamp(&word(key.as_str())))?;
        }
        Ok(())
    }

    /// `offered()`: (version, prerelease) offered and not put away, or None.
    pub fn offered(&self) -> Option<(String, bool)> {
        lock(&self.inner.held).offered.clone()
    }
}

/// `_busy(view)`: whether core holds a recovery that is waiting, being sent or watched - or its records cannot be read.
fn busy(view: &dyn View) -> bool {
    let wanted: Vec<&str> = WAITING
        .iter()
        .chain(CLAIMED)
        .chain(IN_FLIGHT)
        .chain(OBSERVING)
        .copied()
        .collect();
    match view.records_in(&wanted) {
        Ok(rows) => !rows.is_empty(),
        Err(_) => true,
    }
}

struct CheckErrand(IdleUpdateCheck, f64);

impl Errand for CheckErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        self.0.start(self.1).map(|()| Value::Null).map_err(|_| HookFailed)
    }
}

impl Code for IdleUpdateCheck {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.bind_to(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, view: &dyn View) -> Spoke {
        self.ticked(view)
    }
}

/// `make(paths)`: the real check, core's policy, a daemon thread, the version and the log the entry points hand
/// (S6.1/S7.3d: `config.version()` and core's logbook; until then none and nothing written).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(IdleUpdateCheck::new(
        paths.clone(),
        None,
        Box::new(managed_policy),
        Box::new(thread_start),
        Box::new(|| Ok(Value::Null)),
        Box::new(|_line: &str| Ok(())),
    )))
}

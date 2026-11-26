//! gh, the GitHub CLI the person installed, asked for a report as codex-compat-reporter asks it (`report/github.py`).
//!
//! The one module of this edition that names gh or starts it. Everything else of the report reaches GitHub through here,
//! and here reaches it through gh alone: no networking module is imported, no address is called, and gh does every
//! request with the person's own sign-in, which this code never sees (B11, C1 by delegation).
//!
//! gh is found as the reporter finds it ([`find_gh`]): `gh.exe` in an absolute folder on PATH, never the current folder,
//! never the installation's home or anything in it. It is started by that full path with an argument list, no shell,
//! and an environment that is the process's own less GH_HOST and GH_REPO, with prompts and the update notifier off and
//! the current folder out of the executable search; every `api` call names `--hostname github.com` and every `pr` call
//! `--repo github.com/<the project>`, so nothing a local configuration says can send a request elsewhere.
//!
//! The file goes to GitHub on gh's standard input (`--input -`), never through a temporary file.
//!
//! `inspect` is everything before the first write, and only reads; `publish` makes the writes, asking `before` before
//! each one whether it may still go on. A refusal is one closed word ([`GhError::Refused`]).
//!
//! SEAT S7.3c. Starting gh is the seam [`Runner`]: the tag's `runner=` parameter. [`ProcessRunner`] is the production
//! one - gh started windowless and suspended, put in this process's one job object with KILL_ON_JOB_CLOSE, resumed, and
//! ended alone when it has not answered in `TIMEOUT` seconds - over [`Jobs`], the job object itself, which is S7.3b's
//! car-platform `job.rs` and is not here. The diffs never start anything: they hand [`inspect`] and [`publish`] a runner
//! that answers a recorded script (`tests/rustdiff/diffs_advreport_github.py`), as the tag's tests hand them ghfake.

use std::path::Path;
use std::sync::Arc;

use car_config::winpath;
use car_machine::compat::{LoadsError, loads, raw_decode};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::{decimal_value, is_space, py_str, strip};
use car_policy::settings::os::Os;

use super::document;
use crate::vocabulary::{ReportRefusal, ReportWrite, WebReason};

pub const HOST: &str = "github.com";
pub const REPOSITORY: &str = document::REPOSITORY;
pub const COMMUNITY: &str = "docs/evidence/community";
pub const PROJECT_PAGE: &str = "https://github.com/songyb111-gachon/codex-auto-resume-windows";
pub const BRANCH_PREFIX: &str = "compat-report/";
/// Seconds one gh may take before it alone is ended.
pub const TIMEOUT: u64 = 120;
/// How long a new fork is given to be copied (the reporter's).
pub const FORK_WAITS: usize = 20;
pub const FORK_WAIT_SECONDS: f64 = 3.0;
/// `win/kernel.NO_WINDOW`, and `CREATE_SUSPENDED`: started suspended, so it is in the job before it runs an instruction.
pub const NO_WINDOW: u32 = 0x0800_0000;
pub const CREATE_SUSPENDED: u32 = 0x0000_0004;
pub const FLAGS: u32 = NO_WINDOW | CREATE_SUSPENDED;

/// `OWNER, NAME = REPOSITORY.split("/")`.
pub fn name() -> &'static str {
    REPOSITORY.split('/').nth(1).unwrap_or_default()
}

/// What stops a call of this module: a closed refusal (`ReportRefused`), a stop the flow asked for between two writes
/// (`flow.Stopped`, which `publish`'s `before` raises) or any other exception, by class.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GhError {
    Refused(ReportRefusal),
    Stopped(String),
    Raised(String),
}

impl GhError {
    fn refused(code: ReportRefusal) -> GhError {
        GhError::Refused(code)
    }

    /// The word a flow reports: the refusal's code, or the stop's.
    pub fn code(&self) -> Option<String> {
        match self {
            GhError::Refused(code) => Some(code.as_str().to_owned()),
            GhError::Stopped(code) => Some(code.clone()),
            GhError::Raised(_) => None,
        }
    }
}

type Gh<T> = Result<T, GhError>;

// ------------------------------------------------------------------------------ finding gh
fn is_absolute(text: &str) -> bool {
    // `Path(entry).is_absolute()`: a drive and a root.
    let (drive, root, _) = winpath::parse(text);
    !drive.is_empty() && !root.is_empty()
}

fn resolved(os: &dyn Os, text: &str) -> Option<String> {
    let units: Vec<u16> = text.encode_utf16().collect();
    let found = os.resolve(&units).ok()?;
    Some(winpath::path_str(&String::from_utf16_lossy(&found)))
}

/// `_inside(folder, place)`: `place` is `folder` or one of its parents.
fn inside(os: &dyn Os, folder: &str, place: &str) -> bool {
    match (resolved(os, folder), resolved(os, place)) {
        (Some(folder), Some(place)) => winpath::is_relative_to(&folder, &place),
        _ => false,
    }
}

/// `_same(folder, place)`.
fn same(os: &dyn Os, folder: &str, place: &str) -> bool {
    match (resolved(os, folder), resolved(os, place)) {
        (Some(folder), Some(place)) => winpath::same_path(&folder, &place),
        _ => false,
    }
}

/// `find_gh(path=None, unsafe=())`: `gh.exe` from an absolute PATH entry, or None. Never `.`, a relative entry, the
/// current folder itself - as the reporter's find_gh, a folder under it is any other folder - or one of `unsafe`, the
/// installation's home and everything in it, however PATH spells them. `cwd` is `Path.cwd()`.
pub fn find_gh(
    os: &dyn Os,
    path: Option<&str>,
    unsafe_places: &[String],
    cwd: &str,
) -> Option<String> {
    let environment = std::env::var("PATH").unwrap_or_default();
    let path = path.unwrap_or(&environment);
    for entry in path.split(';') {
        let entry = strip(entry).trim_matches('"');
        if entry.is_empty() || entry == "." || !is_absolute(entry) {
            continue;
        }
        let folder = winpath::path_str(entry);
        if same(os, &folder, cwd) || unsafe_places.iter().any(|place| inside(os, &folder, place)) {
            continue;
        }
        let candidate = winpath::path_str(&winpath::join(&folder, "gh.exe"));
        if Path::new(&candidate).is_file()
            && !unsafe_places
                .iter()
                .any(|place| inside(os, &winpath::path_str(&winpath::split(&candidate).0), place))
        {
            return Some(candidate);
        }
    }
    None
}

/// `environment()`: this process's, less what would point gh elsewhere (`os.environ`'s names are upper case on Windows).
pub fn environment() -> Vec<(String, String)> {
    let mut found: Vec<(String, String)> = Vec::new();
    for (name, value) in std::env::vars() {
        if name.starts_with('=') {
            continue;
        }
        let name = name.to_uppercase();
        match found.iter_mut().find(|(each, _)| *each == name) {
            Some(entry) => entry.1 = value,
            None => found.push((name, value)),
        }
    }
    for (name, value) in [
        ("GH_PROMPT_DISABLED", "1"),
        ("GH_NO_UPDATE_NOTIFIER", "1"),
        ("NoDefaultCurrentDirectoryInExePath", "1"),
    ] {
        match found.iter_mut().find(|(each, _)| each == name) {
            Some(entry) => entry.1 = value.to_owned(),
            None => found.push((name.to_owned(), value.to_owned())),
        }
    }
    found.retain(|(name, _)| name != "GH_HOST" && name != "GH_REPO");
    found
}

// ------------------------------------------------------------------------------ the process
/// One gh to run: what the tag's runner is called with.
#[derive(Clone, Debug, PartialEq)]
pub struct Call {
    pub argv: Vec<String>,
    pub env: Vec<(String, String)>,
    pub cwd: String,
    pub stdin: Option<Vec<u8>>,
    pub timeout: u64,
    pub flags: u32,
}

/// Why a runner did not answer: gh did not answer in time and was ended (`GhTimeout`), an `OSError`, `ValueError` or
/// `subprocess.SubprocessError` (all of which are `gh_failed`), or any other exception, which goes on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RunError {
    Timeout,
    Failed(&'static str),
    Raised(String),
}

/// (exit code, standard output, standard error) of one gh, the output decoded as UTF-8 with replacement and stripped.
pub type Answer = (i64, String, String);

/// The seam: how a gh is started and answered (`runner=` of `GhSession`).
pub trait Runner: Send + Sync {
    fn run(&self, call: &Call) -> Result<Answer, RunError>;
}

/// The job object gh runs in (`_job`, `_adopt`): S7.3b's car-platform `job.rs`. `adopt` puts a process, started
/// suspended, in this process's one job (KILL_ON_JOB_CLOSE, its handle never closed here) and resumes it.
pub trait Jobs: Send + Sync {
    fn adopt(&self, child: &std::process::Child) -> std::io::Result<()>;
}

/// `run_process`: gh as the tag starts it, over [`Jobs`].
pub struct ProcessRunner {
    pub jobs: Arc<dyn Jobs>,
}

impl Runner for ProcessRunner {
    fn run(&self, call: &Call) -> Result<Answer, RunError> {
        use car_platform::spawn::{Spawn, Stream, SystemStarter};
        use std::io::{Read, Write};
        use std::time::{Duration, Instant};
        let spawn = Spawn::new(call.argv.clone())
            .with_env(
                call.env
                    .iter()
                    .map(|(name, value)| (name.into(), value.into()))
                    .collect(),
            )
            .with_cwd(&call.cwd)
            .with_flags(CREATE_SUSPENDED)
            .with_streams(
                if call.stdin.is_some() {
                    Stream::Piped
                } else {
                    Stream::Null
                },
                Stream::Piped,
                Stream::Piped,
            );
        let mut child = SystemStarter
            .start(&spawn)
            .map_err(|_| RunError::Failed("OSError"))?;
        if self.jobs.adopt(&child).is_err() {
            // A suspended gh that nobody ends would be waited for for ever: ended before the error goes on.
            let _ = child.kill();
            let _ = child.wait();
            return Err(RunError::Failed("OSError"));
        }
        let mut readers = Vec::new();
        if let Some(mut out) = child.stdout.take() {
            readers.push(std::thread::spawn(move || {
                let mut bytes = Vec::new();
                let _ = out.read_to_end(&mut bytes);
                bytes
            }));
        }
        if let Some(mut err) = child.stderr.take() {
            readers.push(std::thread::spawn(move || {
                let mut bytes = Vec::new();
                let _ = err.read_to_end(&mut bytes);
                bytes
            }));
        }
        let writer = match (child.stdin.take(), call.stdin.clone()) {
            (Some(mut pipe), Some(bytes)) => Some(std::thread::spawn(move || {
                let _ = pipe.write_all(&bytes);
            })),
            _ => None,
        };
        let started = Instant::now();
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) => {}
                Err(_) => return Err(RunError::Failed("OSError")),
            }
            if started.elapsed() >= Duration::from_secs(call.timeout) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(RunError::Timeout);
            }
            std::thread::sleep(Duration::from_millis(10));
        };
        if let Some(writer) = writer {
            let _ = writer.join();
        }
        let mut outputs = readers
            .into_iter()
            .map(|reader| reader.join().unwrap_or_default());
        let decode = |bytes: Vec<u8>| strip(&String::from_utf8_lossy(&bytes)).to_owned();
        let out = decode(outputs.next().unwrap_or_default());
        let err = decode(outputs.next().unwrap_or_default());
        Ok((i64::from(status.code().unwrap_or(-1)), out, err))
    }
}

// ------------------------------------------------------------------------------ asking
fn not_found(result: &Answer) -> bool {
    let (code, out, err) = result;
    let squeezed: String = out.chars().filter(|each| !is_space(*each)).collect();
    *code != 0 && (err.contains("(HTTP 404)") || squeezed.contains("\"status\":\"404\""))
}

/// `_json(text)`: the JSON, or None where it is none; a RecursionError goes on.
fn json(text: &str) -> Gh<Option<Value>> {
    match loads(text) {
        Ok(value) => Ok(Some(value)),
        Err(LoadsError::Recursion) => Err(GhError::Raised("RecursionError".to_owned())),
        Err(_) => Ok(None),
    }
}

/// `_pages(text)`: every entry of `gh api --paginate`'s answer: one JSON array a page, written one after another.
fn pages(text: &str) -> Gh<Vec<Value>> {
    let chars: Vec<char> = text.chars().collect();
    let mut found = Vec::new();
    let mut at = 0;
    while at < chars.len() {
        while at < chars.len() && is_space(chars[at]) {
            at += 1;
        }
        if at >= chars.len() {
            break;
        }
        let (value, end) = match raw_decode(&chars, at) {
            Ok(done) => done,
            Err(LoadsError::Recursion) => return Err(GhError::Raised("RecursionError".to_owned())),
            Err(_) => return Err(GhError::refused(ReportRefusal::GhFailed)),
        };
        at = end;
        let Value::Array(items) = value else {
            return Err(GhError::refused(ReportRefusal::GhFailed));
        };
        found.extend(items);
    }
    Ok(found)
}

fn dict(value: Option<&Value>) -> Map {
    match value {
        Some(Value::Object(map)) => map.clone(),
        _ => Map::new(),
    }
}

/// `blob_sha(raw)`: the git blob SHA-1 of `raw`: what GitHub calls the file's `sha`.
pub fn blob_sha(raw: &[u8]) -> String {
    let mut blob = format!("blob {}\0", raw.len()).into_bytes();
    blob.extend_from_slice(raw);
    car_machine::hash::hex(&car_machine::hash::sha1(&blob))
}

/// `destination(codex_version, login)`: (path, branch): the one place a report of `codex_version` filed under `login`
/// can have.
pub fn destination(codex_version: &Value, login: &Value) -> Gh<(String, String)> {
    let Value::Str(version) = codex_version else {
        return Err(GhError::Raised("TypeError".to_owned()));
    };
    let version: String = version
        .as_str()
        .map(|text| text.chars().skip("codex-cli ".len()).collect())
        .ok_or_else(|| GhError::Raised("UnicodeEncodeError".to_owned()))?;
    let file = format!("codex-cli-{version}.json");
    let branch = format!(
        "{BRANCH_PREFIX}{}",
        file.strip_suffix(".json").unwrap_or(&file)
    );
    Ok((format!("{COMMUNITY}/{}/{file}", py_str(login)), branch))
}

/// `GhSession`: gh, by its full path, pinned to github.com, never prompting, each call in the job.
pub struct GhSession<'a> {
    pub exe: String,
    pub cwd: String,
    pub runner: &'a dyn Runner,
}

impl GhSession<'_> {
    pub fn run(&self, arguments: &[&str], stdin: Option<&[u8]>) -> Gh<Answer> {
        let mut argv = vec![self.exe.clone()];
        argv.extend(arguments.iter().map(|each| (*each).to_owned()));
        let call = Call {
            argv,
            env: environment(),
            cwd: self.cwd.clone(),
            stdin: stdin.map(<[u8]>::to_vec),
            timeout: TIMEOUT,
            flags: FLAGS,
        };
        match self.runner.run(&call) {
            Ok(answer) => Ok(answer),
            Err(RunError::Timeout) => Err(GhError::refused(ReportRefusal::GhTimeout)),
            Err(RunError::Failed(_)) => Err(GhError::refused(ReportRefusal::GhFailed)),
            Err(RunError::Raised(class)) => Err(GhError::Raised(class)),
        }
    }

    pub fn api(
        &self,
        method: &str,
        endpoint: &str,
        more: &[&str],
        stdin: Option<&[u8]>,
    ) -> Gh<Answer> {
        let mut arguments = vec!["api", "--hostname", HOST, "-X", method, endpoint];
        arguments.extend_from_slice(more);
        self.run(&arguments, stdin)
    }

    /// `must(result)`: the output, or `gh_failed` for a non-zero exit.
    pub fn must(result: &Answer) -> Gh<&str> {
        if result.0 != 0 {
            return Err(GhError::refused(ReportRefusal::GhFailed));
        }
        Ok(&result.1)
    }
}

// ------------------------------------------------------------------------------ what a check finds
/// gh cannot send it from here: the person sends it on the web, as `why` says.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Web {
    pub why: WebReason,
    pub who: Option<String>,
}

/// A pull request of this very file is open already: nothing is to be written.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Sent {
    pub url: String,
}

/// Everything before the first write: where it goes and every write sending would make.
#[derive(Clone, Debug, PartialEq)]
pub struct Ready {
    pub exe: String,
    pub who: String,
    pub login: String,
    pub fork: String,
    pub branch: String,
    pub target: String,
    pub base: String,
    pub has_fork: bool,
    pub has_branch: bool,
    pub cwd: String,
    pub written: Vec<Value>,
}

impl Ready {
    /// The writes, in order, as the person is shown them: `[{"kind", "name"}]`.
    pub fn writes(&self) -> Vec<Value> {
        fn write(kind: ReportWrite, name: &str) -> Value {
            let mut map = Map::new();
            map.insert(Str::from("kind"), Value::from(kind.as_str()));
            map.insert(Str::from("name"), Value::from(name));
            Value::Object(map)
        }
        vec![
            write(
                if self.has_fork {
                    ReportWrite::ForkKept
                } else {
                    ReportWrite::ForkNew
                },
                &self.fork,
            ),
            write(
                if self.has_branch {
                    ReportWrite::BranchReset
                } else {
                    ReportWrite::BranchNew
                },
                &self.branch,
            ),
            write(ReportWrite::File, &self.target),
            write(ReportWrite::Pr, REPOSITORY),
        ]
    }
}

/// What `inspect` found.
#[derive(Clone, Debug, PartialEq)]
pub enum Inspected {
    Web(Web),
    Sent(Sent),
    Ready(Ready),
}

/// `U+017F` and the other characters whose full case folding is ASCII, by their folding: the only non-ASCII characters
/// `str.casefold()` can turn into a part of a GitHub login.
const FOLDS: &[(char, &str)] = &[
    ('\u{17F}', "s"),
    ('\u{212A}', "k"),
    ('\u{DF}', "ss"),
    ('\u{1E9E}', "ss"),
    ('\u{FB00}', "ff"),
    ('\u{FB01}', "fi"),
    ('\u{FB02}', "fl"),
    ('\u{FB03}', "ffi"),
    ('\u{FB04}', "ffl"),
    ('\u{FB05}', "st"),
    ('\u{FB06}', "st"),
];

/// `who.casefold()` where that can be ASCII, else None: a text with any other non-ASCII character folds to something
/// that is not a login.
fn ascii_fold(text: &str) -> Option<String> {
    let mut folded = String::new();
    for each in text.chars() {
        if each.is_ascii() {
            folded.push(each.to_ascii_lowercase());
        } else {
            folded.push_str(FOLDS.iter().find(|(from, _)| *from == each)?.1);
        }
    }
    Some(folded)
}

/// `spelling(login, who)`: gh's spelling of `login`, where `who` is that account typed in other letters, else None.
pub fn spelling(login: &str, who: &str) -> Option<String> {
    if who.is_empty() || who == login {
        return None;
    }
    (ascii_fold(who)? == login.to_ascii_lowercase()).then(|| who.to_owned())
}

/// `_open_reports(github, login)`: (url, branch) of every open report pull request of `login`, from the project's own list
/// of open pull requests, page by page - never `pr list --author`, which GitHub answers through its search.
fn open_reports(github: &GhSession<'_>, login: &str) -> Gh<Vec<(String, String)>> {
    let listing = github.api(
        "GET",
        &format!("repos/{REPOSITORY}/pulls?state=open&per_page=100"),
        &["--paginate"],
        None,
    )?;
    let listed = pages(GhSession::must(&listing)?)?;
    let mut found = Vec::new();
    for entry in listed {
        let entry = dict(Some(&entry));
        let head = dict(entry.get("head"));
        let is_login = |value: Option<&Value>| matches!(value, Some(Value::Str(text)) if text.as_str() == Some(login));
        let Some(Value::Str(reference)) = head.get("ref") else {
            continue;
        };
        let Some(reference) = reference.as_str() else {
            continue;
        };
        if is_login(dict(entry.get("user")).get("login"))
            && reference.starts_with(BRANCH_PREFIX)
            && is_login(dict(dict(head.get("repo")).get("owner")).get("login"))
        {
            let url = match entry.get("html_url") {
                Some(Value::Str(url)) => url.as_str().unwrap_or_default().to_owned(),
                _ => String::new(),
            };
            found.push((url, reference.to_owned()));
        }
    }
    Ok(found)
}

/// `PULL.search(text)` or `PULL.fullmatch(text)`: `PROJECT_PAGE/pull/` and one to nine digits (any script's).
pub fn pull_in(text: &str, whole: bool) -> Option<String> {
    let prefix = format!("{PROJECT_PAGE}/pull/");
    let starts: Vec<usize> = text.match_indices(&prefix).map(|(at, _)| at).collect();
    for start in starts {
        if whole && start != 0 {
            continue;
        }
        let digits: Vec<char> = text[start + prefix.len()..]
            .chars()
            .take_while(|each| decimal_value(*each).is_some())
            .collect();
        let taken = digits.len().min(9);
        if taken == 0 {
            continue;
        }
        let end = start
            + prefix.len()
            + digits[..taken]
                .iter()
                .map(|each| each.len_utf8())
                .sum::<usize>();
        if whole && end != text.len() {
            continue;
        }
        return Some(text[start..end].to_owned());
    }
    None
}

/// `_sent_already(github, login, branch, target, raw, open_ones)`: the pull request of exactly `raw` from
/// `login:branch` that is open, or None.
fn sent_already(
    github: &GhSession<'_>,
    login: &str,
    branch: &str,
    target: &str,
    raw: &[u8],
    open_ones: &[(String, String)],
) -> Gh<Option<String>> {
    for (url, reference) in open_ones {
        if reference != branch || pull_in(url, true).is_none() {
            continue;
        }
        let fork = format!("{login}/{}", name());
        let sha = github.api(
            "GET",
            &format!("repos/{fork}/contents/{target}?ref={branch}"),
            &["--jq", ".sha"],
            None,
        )?;
        if sha.0 == 0 && sha.1 == blob_sha(raw) {
            return Ok(Some(url.clone()));
        }
    }
    Ok(None)
}

/// `inspect(raw, report, login, exe=, cwd=, runner=, sleep=)`: what sending `raw` - the report `report`, filed under
/// `login` - would do, asking GitHub only questions: Web, Sent or Ready; a refusal where it may not be sent at all.
pub fn inspect(
    raw: &[u8],
    report: &Value,
    login: &str,
    exe: Option<&str>,
    cwd: &str,
    runner: &dyn Runner,
) -> Gh<Inspected> {
    let version = match report {
        Value::Object(map) => map.get("codex_version").cloned(),
        _ => None,
    };
    let (target, branch) = destination(
        &version.ok_or_else(|| GhError::Raised("KeyError".to_owned()))?,
        &Value::from(login),
    )?;
    let Some(exe) = exe else {
        return Ok(Inspected::Web(Web {
            why: WebReason::NoGh,
            who: None,
        }));
    };
    let github = GhSession {
        exe: exe.to_owned(),
        cwd: cwd.to_owned(),
        runner,
    };
    if github.run(&["auth", "status", "--hostname", HOST], None)?.0 != 0 {
        return Ok(Inspected::Web(Web {
            why: WebReason::GhSignedOut,
            who: None,
        }));
    }
    let user = github.api("GET", "user", &["--jq", ".login"], None)?;
    let who = GhSession::must(&user)?.to_owned();
    if spelling(login, &who).is_some() {
        return Err(GhError::refused(ReportRefusal::GhSpelling));
    }
    if who != login {
        let shown = document::login_shape(&who).then(|| who.clone());
        return Ok(Inspected::Web(Web {
            why: WebReason::GhOtherLogin,
            who: shown,
        }));
    }
    let door = github.api(
        "GET",
        &format!("repos/{REPOSITORY}/contents/{COMMUNITY}"),
        &[],
        None,
    )?;
    if not_found(&door) {
        return Err(GhError::refused(ReportRefusal::NotOpen));
    }
    GhSession::must(&door)?;
    let open_ones = open_reports(&github, login)?;
    if let Some(url) = sent_already(&github, login, &branch, &target, raw, &open_ones)? {
        return Ok(Inspected::Sent(Sent { url }));
    }
    let filed = github.api(
        "GET",
        &format!("repos/{REPOSITORY}/contents/{target}"),
        &[],
        None,
    )?;
    if filed.0 == 0 {
        return Err(GhError::refused(ReportRefusal::AlreadyFiled));
    }
    if !not_found(&filed) {
        GhSession::must(&filed)?;
    }
    if !open_ones.is_empty() {
        return Err(GhError::refused(ReportRefusal::PrOpen));
    }
    let fork = format!("{login}/{}", name());
    let looked = github.api("GET", &format!("repos/{fork}"), &[], None)?;
    let has_fork = !not_found(&looked);
    if has_fork {
        let text = GhSession::must(&looked)?;
        let text = if text.is_empty() { "{}" } else { text };
        let info = dict(json(text)?.as_ref());
        let fork_flag = info.get("fork").is_some_and(car_machine::pyval::truthy);
        let parent = dict(info.get("parent"));
        let named = matches!(parent.get("full_name"), Some(Value::Str(full)) if full.as_str() == Some(REPOSITORY));
        if !fork_flag || !named {
            return Err(GhError::refused(ReportRefusal::ForkNamedOtherwise));
        }
    }
    let mut has_branch = false;
    if has_fork {
        let found = github.api(
            "GET",
            &format!("repos/{fork}/git/ref/heads/{branch}"),
            &[],
            None,
        )?;
        has_branch = found.0 == 0;
        if !has_branch && !not_found(&found) {
            GhSession::must(&found)?;
        }
    }
    let based = github.api(
        "GET",
        &format!("repos/{REPOSITORY}/git/ref/heads/main"),
        &["--jq", ".object.sha"],
        None,
    )?;
    let base = GhSession::must(&based)?.to_owned();
    if !(base.len() == 40
        && base
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f')))
    {
        return Err(GhError::refused(ReportRefusal::BaseInvalid));
    }
    Ok(Inspected::Ready(Ready {
        exe: exe.to_owned(),
        who,
        login: login.to_owned(),
        fork,
        branch,
        target,
        base,
        has_fork,
        has_branch,
        cwd: cwd.to_owned(),
        written: Vec::new(),
    }))
}

// ------------------------------------------------------------------------------ the writes
/// `title(report, login)`.
pub fn title(report: &Value, login: &str) -> String {
    let version = match report {
        Value::Object(map) => map.get("codex_version").map(py_str).unwrap_or_default(),
        _ => String::new(),
    };
    format!("Compatibility report: {version} ({login})")
}

/// `body(product_version)`.
pub fn body(product_version: &str) -> String {
    format!(
        "Written by Codex Auto Resume {product_version} (advanced edition) from my own machine's records. Counts, states and times only. It counts towards the Reported grade beside the version and nothing else."
    )
}

/// `base64.b64encode(raw).decode("ascii")`.
pub fn base64(raw: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(raw.len().div_ceil(3) * 4);
    for chunk in raw.chunks(3) {
        let block = (u32::from(chunk[0]) << 16)
            | (u32::from(*chunk.get(1).unwrap_or(&0)) << 8)
            | u32::from(*chunk.get(2).unwrap_or(&0));
        out.push(TABLE[(block >> 18) as usize & 63] as char);
        out.push(TABLE[(block >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            TABLE[(block >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            TABLE[block as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

/// `publish(ready, raw, report, before=, runner=, sleep=)`: the writes `ready.writes()` names, in order - each one done
/// added to `ready.written` - and the pull request's address. `before()` is asked before every write and returns the
/// stop to end it; a refusal after a write leaves what was written in `ready.written`.
pub fn publish(
    ready: &mut Ready,
    raw: &[u8],
    report: &Value,
    before: &mut dyn FnMut() -> Result<(), GhError>,
    runner: &dyn Runner,
    sleep: &dyn Fn(f64),
) -> Gh<String> {
    let github = GhSession {
        exe: ready.exe.clone(),
        cwd: ready.cwd.clone(),
        runner,
    };
    let writes = ready.writes();
    let (login, fork, branch, target) = (
        ready.login.clone(),
        ready.fork.clone(),
        ready.branch.clone(),
        ready.target.clone(),
    );
    if !ready.has_fork {
        before()?;
        let forked = github.api(
            "POST",
            &format!("repos/{REPOSITORY}/forks"),
            &["--jq", ".full_name"],
            None,
        )?;
        let made = GhSession::must(&forked)?;
        if made != fork {
            return Err(GhError::refused(ReportRefusal::ForkNamedOtherwise));
        }
        ready.written.push(writes[0].clone());
        // A new fork answers as a repository before GitHub has copied its git data into it, and a branch cannot be
        // made until it has: wait for its main, not for its name.
        let mut ready_at = false;
        for _attempt in 0..FORK_WAITS {
            let looked = github.api(
                "GET",
                &format!("repos/{fork}/git/ref/heads/main"),
                &["--jq", ".object.sha"],
                None,
            )?;
            if looked.0 == 0 {
                ready_at = true;
                break;
            }
            sleep(FORK_WAIT_SECONDS);
        }
        if !ready_at {
            return Err(GhError::refused(ReportRefusal::ForkNotReady));
        }
    }
    before()?;
    if ready.has_branch {
        let moved = github.api(
            "PATCH",
            &format!("repos/{fork}/git/refs/heads/{branch}"),
            &["-f", &format!("sha={}", ready.base), "-F", "force=true"],
            None,
        )?;
        GhSession::must(&moved)?;
    } else {
        let made = github.api(
            "POST",
            &format!("repos/{fork}/git/refs"),
            &[
                "-f",
                &format!("ref=refs/heads/{branch}"),
                "-f",
                &format!("sha={}", ready.base),
            ],
            None,
        )?;
        GhSession::must(&made)?;
    }
    ready.written.push(writes[1].clone());
    before()?;
    let version = match report {
        Value::Object(map) => map.get("codex_version").map(py_str).unwrap_or_default(),
        _ => String::new(),
    };
    let mut upload = Map::new();
    upload.insert(
        Str::from("message"),
        Value::from(format!("Compatibility report for {version} from {login}")),
    );
    upload.insert(Str::from("branch"), Value::from(branch.as_str()));
    upload.insert(Str::from("content"), Value::from(base64(raw)));
    let upload =
        car_machine::json::to_string(&Value::Object(upload), &car_machine::json::Options::new())
            .map_err(|_| GhError::Raised("ValueError".to_owned()))?;
    let put = github.api(
        "PUT",
        &format!("repos/{fork}/contents/{target}"),
        &["--input", "-"],
        Some(upload.as_bytes()),
    )?;
    GhSession::must(&put)?;
    ready.written.push(writes[2].clone());
    before()?;
    let tool_version = match report {
        Value::Object(map) => match map.get("reporter") {
            Some(Value::Object(reporter)) => {
                reporter.get("tool_version").map(py_str).unwrap_or_default()
            }
            _ => String::new(),
        },
        _ => String::new(),
    };
    let made = github.run(
        &[
            "pr",
            "create",
            "--repo",
            &format!("{HOST}/{REPOSITORY}"),
            "--base",
            "main",
            "--head",
            &format!("{login}:{branch}"),
            "--title",
            &title(report, &login),
            "--body",
            &body(&tool_version),
        ],
        None,
    )?;
    let found = if made.0 == 0 {
        pull_in(&made.1, false)
    } else {
        None
    };
    let Some(found) = found else {
        // gh refused it because one is open already, or answered without its address: what is open from this branch with
        // exactly this file is the pull request.
        let open_ones = open_reports(&github, &login)?;
        let Some(url) = sent_already(&github, &login, &branch, &target, raw, &open_ones)? else {
            return Err(GhError::refused(ReportRefusal::GhFailed));
        };
        ready.written.push(writes[3].clone());
        return Ok(url);
    };
    ready.written.push(writes[3].clone());
    Ok(found)
}

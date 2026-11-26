//! `codex/account.py` (seat S7.2b): which Codex account is signed in, and Codex's own sign-out and sign-in
//! (account_switch).
//!
//! [`read`] asks the app server `account/read` through a finite session of this capability's own and answers
//! {present, plan_word, email, kind}: whether an account is signed in - None where the answer was not one Codex gives -
//! its plan as a closed word, its address and its kind. The address goes to the caller in this process only: the card
//! shows [`mask`] of it and the watcher keeps [`digest`] of it, keyed by this installation's own salt.
//!
//! [`switch`] is the one way this product signs anyone out or in: Codex's own `codex logout`, then `codex login`, each
//! an argument list with no shell and no console, started in the Dashboard's job (report/github's runner), and what it
//! came to read back with `account/read`.
//!
//! The seams are the reference's: the session ([`Opener`]: `Session(inuse.backend(paths), capability=...)`, or a
//! test's), the backend ([`Backend`]: core's argv, environment and Codex home) and the runner ([`Runner`]).

use std::path::Path;

use car_machine::json::{Map, Str, Value};

use super::authfile::Fault;
use crate::state::seam::Tokens;
use crate::vocabulary::PlanWord;

pub const CAPABILITY: &str = "account_switch";
pub const READ: &str = "account/read";
pub const LOGOUT_SECONDS: f64 = 60.0;
pub const LOGIN_SECONDS: f64 = 600.0;
pub const SIGNED_IN: &str = "signed_in";
pub const CANCELLED: &str = "cancelled";
pub const TIMED_OUT: &str = "timed_out";
pub const FAILED: &str = "failed";
pub const OUTCOMES: [&str; 4] = [SIGNED_IN, CANCELLED, TIMED_OUT, FAILED];
pub const KINDS: [&str; 2] = ["chatgpt", "apikey"];
pub use crate::state::seam::accounts::HIDDEN;
pub const SALT_BYTES: usize = 32;
pub const DIGEST_HEX: usize = 16;

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::new(key), value);
    }
    Value::Object(map)
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

fn space(point: u32) -> bool {
    char::from_u32(point).is_some_and(car_machine::pytext::is_space)
}

/// `text.strip()` by code points.
pub fn strip(text: &Str) -> Vec<u32> {
    let points: Vec<u32> = text.code_points().collect();
    let start = points
        .iter()
        .position(|point| !space(*point))
        .unwrap_or(points.len());
    let end = points
        .iter()
        .rposition(|point| !space(*point))
        .map_or(start, |index| index + 1);
    points[start..end.max(start)].to_vec()
}

fn lower_points(points: &[u32]) -> Vec<u32> {
    let mut out = Vec::new();
    for point in points {
        car_policy::classify::text::lower_point(*point, &mut out);
    }
    out
}

fn from_points(points: Vec<u32>) -> Value {
    Str::from_code_points(points).map_or(Value::Null, Value::Str)
}

fn points_of(word: &str) -> Vec<u32> {
    word.chars().map(u32::from).collect()
}

/// `plan_word(value)`: Codex's plan type as a closed word - one of PlanWord, `other` for any other string, None for
/// none.
pub fn plan_word(value: &Value) -> Value {
    let Value::Str(found) = value else {
        return Value::Null;
    };
    if found.is_empty() {
        return Value::Null;
    }
    let word = lower_points(&strip(found));
    match PlanWord::ALL
        .iter()
        .find(|plan| points_of(plan.as_str()) == word)
    {
        Some(plan) => text(plan.as_str()),
        None => text(PlanWord::Other.as_str()),
    }
}

fn unknown() -> Value {
    object(vec![
        ("present", Value::Null),
        ("plan_word", Value::Null),
        ("email", Value::Null),
        ("kind", Value::Null),
    ])
}

/// `parse(reply)`: {present, plan_word, email, kind} of an account/read answer. `present` None - and nothing else -
/// where `reply` is not one Codex gives: a failed read is never taken as signed out (E1). Pure.
pub fn parse(reply: &Value) -> Value {
    let Some(account) = get(reply, "account") else {
        return unknown();
    };
    let account = match account {
        Value::Null => {
            return object(vec![
                ("present", Value::Bool(false)),
                ("plan_word", Value::Null),
                ("email", Value::Null),
                ("kind", Value::Null),
            ]);
        }
        Value::Object(_) => account,
        _ => return unknown(),
    };
    let kind = match get(account, "type") {
        Some(Value::Str(found)) => {
            let lowered = car_policy::classify::text::lower(found);
            if KINDS.iter().any(|kind| points_of(kind) == lowered) {
                from_points(lowered)
            } else {
                Value::Null
            }
        }
        _ => Value::Null,
    };
    let email = match get(account, "email") {
        Some(Value::Str(found)) => {
            let stripped = strip(found);
            if stripped.contains(&u32::from(b'@')) && stripped.len() <= 320 {
                from_points(stripped)
            } else {
                Value::Null
            }
        }
        _ => Value::Null,
    };
    let plan = match get(account, "planType") {
        Some(found) => found.clone(),
        None => get(account, "plan_type").cloned().unwrap_or(Value::Null),
    };
    object(vec![
        ("present", Value::Bool(true)),
        ("plan_word", plan_word(&plan)),
        ("email", email),
        ("kind", kind),
    ])
}

/// `identity(found)`: the text an account is told apart by - its address in lower case, or its kind where it has none
/// ("kind:apikey") - or None where neither is known. What the reference raises on a `found` no read gives (an address
/// that is not text, a kind that is not text) is raised here too.
pub fn identity(found: &Value) -> Result<Option<Value>, Fault> {
    if !matches!(get(found, "present"), Some(Value::Bool(true))) {
        return Ok(None);
    }
    if let Some(email) = get(found, "email").filter(|email| car_machine::pyval::truthy(email)) {
        return match email {
            Value::Str(found) => Ok(Some(from_points(car_policy::classify::text::lower(found)))),
            _ => Err(Fault::new("AttributeError", "object has no attribute 'lower'")),
        };
    }
    match get(found, "kind").filter(|kind| car_machine::pyval::truthy(kind)) {
        None => Ok(None),
        Some(Value::Str(kind)) => {
            let mut points = points_of("kind:");
            points.extend(kind.code_points());
            Ok(Some(from_points(points)))
        }
        Some(_) => Err(Fault::new(
            "TypeError",
            "can only concatenate str (not \"int\") to str",
        )),
    }
}

/// `bytes.fromhex(text)`: two hexadecimal digits a byte, ASCII white space between the bytes skipped; ValueError
/// otherwise.
pub fn from_hex(text: &Str) -> Result<Vec<u8>, Fault> {
    let refused = || Fault::new("ValueError", "non-hexadecimal number found in fromhex() arg");
    let bytes = text.as_str().filter(|text| text.is_ascii()).ok_or_else(refused)?;
    let bytes = bytes.as_bytes();
    let white = |b: u8| matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c);
    let digit = |b: u8| (b as char).to_digit(16);
    let mut out = Vec::new();
    let mut at = 0;
    while at < bytes.len() {
        if white(bytes[at]) {
            while at < bytes.len() && white(bytes[at]) {
                at += 1;
            }
            if at >= bytes.len() {
                break;
            }
        }
        let top = digit(bytes[at]).ok_or_else(refused)?;
        let bottom = bytes.get(at + 1).and_then(|b| digit(*b)).ok_or_else(refused)?;
        out.push((top * 16 + bottom) as u8);
        at += 2;
    }
    Ok(out)
}

/// HMAC-SHA256 (RFC 2104) over car-machine's SHA-256.
pub fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    let mut block = [0u8; 64];
    if key.len() > 64 {
        block[..32].copy_from_slice(&car_machine::hash::sha256(key));
    } else {
        block[..key.len()].copy_from_slice(key);
    }
    let mut inner: Vec<u8> = block.iter().map(|b| b ^ 0x36).collect();
    inner.extend_from_slice(message);
    let mut outer: Vec<u8> = block.iter().map(|b| b ^ 0x5c).collect();
    outer.extend_from_slice(&car_machine::hash::sha256(&inner));
    car_machine::hash::sha256(&outer)
}

/// `digest(text, salt)`: 16 hex characters of HMAC-SHA256 over `text`, keyed by `salt` (hex): what the watcher keeps
/// of an account, never the address. ValueError for anything but two non-empty texts (and a salt that is not hex, or
/// a text that UTF-8 cannot write).
pub fn digest(text: &Value, salt: &Value) -> Result<String, Fault> {
    let (Value::Str(found), Value::Str(key)) = (text, salt) else {
        return Err(Fault::new("ValueError", "an identity and a salt"));
    };
    if found.is_empty() || key.is_empty() {
        return Err(Fault::new("ValueError", "an identity and a salt"));
    }
    let key = from_hex(key)?;
    let message = found
        .as_str()
        .ok_or_else(|| Fault::new("UnicodeEncodeError", "surrogates not allowed"))?;
    let made = car_machine::hash::hex(&hmac_sha256(&key, message.as_bytes()));
    Ok(made[..DIGEST_HEX].to_owned())
}

/// `new_salt()`: 32 random bytes, as hex.
pub fn new_salt(tokens: &dyn Tokens) -> String {
    tokens.hex(SALT_BYTES)
}

/// `mask(email)`: the address as the card shows it, or None.
pub fn mask(email: &Value) -> Value {
    crate::state::seam::accounts::mask(email).map_or(Value::Null, Value::Str)
}

// ------------------------------------------------------------------------------------------------ the seams
/// One session's `call` (`protocol.Session.call`, or a test's).
pub trait Session {
    fn call(&mut self, method: &str, params: Value) -> Result<Value, Fault>;
}

/// `session_for(home)` / `Session(inuse.backend(paths), capability=...)` entered: a session on Codex's home `home` (None:
/// the installation's own), or what its making or starting raised. Dropping it is `__exit__`.
pub trait Opener {
    fn open(&self, home: Option<&Path>) -> Result<Box<dyn Session + '_>, Fault>;
}

/// `read(paths, session=...)`: account/read through a finite session of this capability's own, parsed -
/// {present: None, ...} where Codex could not be found or asked.
pub fn read(opener: &dyn Opener) -> Value {
    let answer = (|| -> Result<Value, Fault> {
        let mut session = opener.open(None)?;
        session.call(READ, Value::Object(Map::new()))
    })();
    match answer {
        Ok(reply) => parse(&reply),
        Err(_) => parse(&Value::Null),
    }
}

/// Core's Backend as `switch` uses it.
pub trait Backend {
    /// `backend._argv()`.
    fn argv(&self) -> Result<Vec<String>, Fault>;
    /// `backend._environment()`.
    fn environment(&self) -> Result<Vec<(String, String)>, Fault>;
    /// `str(backend.codex_home)`.
    fn codex_home(&self) -> String;
}

/// Why a runner gave no answer: gh's own `GhTimeout`, or what it raised (OSError and ValueError are a failed run; any
/// other exception goes on).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Ran {
    Timeout,
    Raised(Fault),
}

/// report/github.run_process's shape: what it returned (the reference unpacks three values), or why not.
pub trait Runner {
    fn run(
        &self,
        argv: &[String],
        env: &[(String, String)],
        cwd: &str,
        timeout: f64,
    ) -> Result<Value, Ran>;
}

/// The product's runner: report/github's process runner (windowless, suspended, in the job), as account.switch hands
/// it its argv, environment and folder.
pub struct ProcessRunner<'a>(pub &'a dyn crate::report::github::Runner);

impl Runner for ProcessRunner<'_> {
    fn run(
        &self,
        argv: &[String],
        env: &[(String, String)],
        cwd: &str,
        timeout: f64,
    ) -> Result<Value, Ran> {
        use crate::report::github::{Call, FLAGS, RunError};
        let call = Call {
            argv: argv.to_vec(),
            env: env.to_vec(),
            cwd: cwd.to_owned(),
            stdin: None,
            timeout: timeout as u64,
            flags: FLAGS,
        };
        match self.0.run(&call) {
            Ok((code, out, err)) => Ok(Value::Array(vec![
                Value::from(code),
                text(&out),
                text(&err),
            ])),
            Err(RunError::Timeout) => Err(Ran::Timeout),
            Err(RunError::Failed(class)) => Err(Ran::Raised(Fault::new(class, "the run failed"))),
            Err(RunError::Raised(class)) => Err(Ran::Raised(Fault::new(&class, "the run raised"))),
        }
    }
}

/// What `_run_codex` came to: the child's exit code, or the outcome word where it could not run or did not end.
#[derive(Clone, Debug, PartialEq)]
pub enum Exit {
    Code(Value),
    Word(&'static str),
}

/// `_run_codex(run, argv, backend, seconds)`: one `codex` child in the job.
pub fn run_codex(
    runner: &dyn Runner,
    argv: &[String],
    backend: &dyn Backend,
    seconds: f64,
) -> Result<Exit, Fault> {
    let env = match backend.environment() {
        Ok(env) => env,
        Err(fault) if fault.is_os() || is_value_error(&fault) => return Ok(Exit::Word(FAILED)),
        Err(fault) => return Err(fault),
    };
    let returned = match runner.run(argv, &env, &backend.codex_home(), seconds) {
        Ok(returned) => returned,
        Err(Ran::Timeout) => return Ok(Exit::Word(TIMED_OUT)),
        Err(Ran::Raised(fault)) if fault.is_os() || is_value_error(&fault) => {
            return Ok(Exit::Word(FAILED));
        }
        Err(Ran::Raised(fault)) => return Err(fault),
    };
    // `code, _out, _err = returned`: three values or ValueError (a failed run); a text of three characters unpacks.
    let code = match &returned {
        Value::Array(items) if items.len() == 3 => items[0].clone(),
        Value::Array(_) => return Ok(Exit::Word(FAILED)),
        Value::Str(found) if found.code_points().count() == 3 => return Ok(Exit::Word(FAILED)),
        Value::Str(_) | Value::Object(_) => return Ok(Exit::Word(FAILED)),
        _ => {
            return Err(Fault::new(
                "TypeError",
                "cannot unpack non-iterable object",
            ));
        }
    };
    Ok(match code {
        Value::Int(_) => Exit::Code(code),
        _ => Exit::Word(FAILED),
    })
}

fn is_value_error(fault: &Fault) -> bool {
    matches!(
        fault.class.as_str(),
        "ValueError" | "UnicodeDecodeError" | "UnicodeEncodeError" | "JSONDecodeError"
    )
}

fn failed_word(exit: &Exit) -> Option<&'static str> {
    match exit {
        Exit::Word(word) if [TIMED_OUT, FAILED].contains(word) => Some(word),
        _ => None,
    }
}

/// `switch(paths, backend=, runner=, reader=, login_seconds=)`: Codex's own `codex logout`, then `codex login`, and
/// what it came to, read back: SIGNED_IN, CANCELLED (left signed out), TIMED_OUT or FAILED. `backend` is what
/// `inuse.backend(paths)` made, or why it could not be made.
pub fn switch(
    backend: Result<&dyn Backend, Fault>,
    runner: &dyn Runner,
    reader: &dyn Fn() -> Value,
    login_seconds: f64,
) -> Result<&'static str, Fault> {
    let Ok(backend) = backend else {
        return Ok(FAILED);
    };
    let Ok(argv) = backend.argv() else {
        return Ok(FAILED);
    };
    let with = |word: &str| {
        let mut all = argv.clone();
        all.push(word.to_owned());
        all
    };
    let out = run_codex(runner, &with("logout"), backend, LOGOUT_SECONDS)?;
    if failed_word(&out).is_some() {
        return Ok(FAILED);
    }
    // A logout that says no one was signed in is not a failure: the sign-in follows all the same.
    let signed = run_codex(runner, &with("login"), backend, login_seconds)?;
    if let Some(word) = failed_word(&signed) {
        return Ok(word);
    }
    let found = reader();
    let Value::Object(map) = &found else {
        return Err(Fault::new(
            "AttributeError",
            "object has no attribute 'get'",
        ));
    };
    Ok(match map.get("present") {
        Some(Value::Bool(true)) => SIGNED_IN,
        Some(Value::Bool(false)) => CANCELLED,
        _ => FAILED,
    })
}

// ------------------------------------------------------------------------------------------------ the product's hands
/// The product's own session hands: `Session(inuse.backend(paths), capability=...)` on the installation's Codex home,
/// or `swap.default_session_for(paths)` on any other (core's Backend on that home with the Codex the installation
/// drives, checked). `product_version` is what `config.version()` answers, the entry point's to give.
pub struct Live {
    pub installation: String,
    pub settings_file: std::path::PathBuf,
    pub capability: &'static str,
    pub product_version: String,
}

impl Live {
    /// account_switch's own sessions for the installation of `paths`.
    pub fn new(paths: &car_config::Paths) -> Live {
        Live::for_capability(paths, CAPABILITY)
    }

    /// `capability`'s own sessions for the installation of `paths`.
    pub fn for_capability(paths: &car_config::Paths, capability: &'static str) -> Live {
        let root = std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|folder| folder.to_string_lossy().into_owned()))
            .unwrap_or_default();
        Live {
            installation: paths.home.clone(),
            settings_file: std::path::PathBuf::from(&paths.settings_file),
            capability,
            product_version: car_config::codex::version(&root, &mut |_| {}),
        }
    }

    /// Core's Backend on `home` (None: the installation's own), checked.
    pub fn backend(&self, home: Option<&Path>) -> Result<car_codex::transport::Backend, Fault> {
        use super::inuse::{self, BackendError, Discovery};
        let platform = std::sync::Arc::new(car_codex::system::Platform::new());
        let system: std::sync::Arc<dyn car_codex::system::System> = platform.clone();
        let env = |name: &str| std::env::var(name).ok();
        let discovery = Discovery {
            system: std::sync::Arc::clone(&system),
            env: &env,
            os: &platform.config,
            product_version: self.product_version.clone(),
        };
        let refused = |error: BackendError| match error {
            BackendError::Adapter(code) | BackendError::Check(code) => Fault::new("AdapterError", &code),
            BackendError::Config(text) => Fault::new("ConfigError", &text),
            BackendError::Raised(class) => Fault::new(class, "raised by discovery"),
        };
        let own = inuse::backend(Some(&self.installation), Some(&self.settings_file), &discovery)
            .map_err(refused)?;
        let Some(home) = home else {
            return Ok(own);
        };
        let mut made = car_codex::transport::Backend::new(
            system,
            &home.to_string_lossy(),
            &own.codex_exe,
            false,
            &self.product_version,
        );
        made.compatible()
            .map_err(|error| Fault::new("AdapterError", &format!("{error:?}")))?;
        Ok(made)
    }
}

struct LiveSession(super::session::Session);

impl Session for LiveSession {
    fn call(&mut self, method: &str, params: Value) -> Result<Value, Fault> {
        use super::session::Channel;
        self.0
            .call(method, Some(params))
            .map_err(|error| Fault::new(error.class(), error.text()))
    }
}

impl Drop for LiveSession {
    fn drop(&mut self) {
        use super::session::Channel;
        self.0.exit();
    }
}

impl Opener for Live {
    fn open(&self, home: Option<&Path>) -> Result<Box<dyn Session + '_>, Fault> {
        use super::session::Channel;
        let backend = self.backend(home)?;
        let mut session = super::session::Session::new(backend, None, Some(self.capability), Vec::new())
            .map_err(|error| Fault::new(error.class(), error.text()))?;
        session
            .enter()
            .map_err(|error| Fault::new(error.class(), error.text()))?;
        Ok(Box::new(LiveSession(session)))
    }
}

impl Backend for car_codex::transport::Backend {
    fn argv(&self) -> Result<Vec<String>, Fault> {
        Ok(car_codex::transport::Backend::argv(self))
    }
    fn environment(&self) -> Result<Vec<(String, String)>, Fault> {
        Ok(car_codex::transport::Backend::environment(self)
            .into_iter()
            .map(|(name, value)| {
                (
                    name.to_string_lossy().into_owned(),
                    value.to_string_lossy().into_owned(),
                )
            })
            .collect())
    }
    fn codex_home(&self) -> String {
        self.codex_home.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_digest_is_hmac_sha256_cut_to_sixteen() {
        // RFC 4231 test case 2: key "Jefe", "what do ya want for nothing?".
        let made = car_machine::hash::hex(&hmac_sha256(b"Jefe", b"what do ya want for nothing?"));
        assert_eq!(
            made,
            "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        );
        assert_eq!(
            digest(&text("a@b.c"), &text("4a656665")).expect("made").len(),
            16
        );
    }
}

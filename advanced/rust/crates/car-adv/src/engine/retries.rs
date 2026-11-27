//! `codex_retry_settings`' code (seat S7.2e1; `engine/retries.py`): Codex's own retry settings, by a provider of our
//! own, on our own server only (v0.6.22; hidden until MB2 passes, `registry.WAITING`).
//!
//! A set of `-c` settings (`overrides`) the app server this product starts for its own turns takes
//! (`codex::headless::live_session`), held in force by the P8 tick while the provider fits (`fits`), looked at again at
//! most once a LOOK_SECONDS and lapsing after FRESH_SECONDS not renewed. It answers DEFER always.

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::View;

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::headless::Opener;
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "codex_retry_settings";
pub const ATTEMPTS: [i64; 6] = [6, 8, 10, 12, 16, 20];
pub const DEFAULT_ATTEMPTS: i64 = 8;
/// Our provider's id: never a built-in one, and one a person is unlikely to own.
pub const PROVIDER: &str = "codex_auto_resume_retries";
/// The built-in provider's base URL for a ChatGPT sign-in.
pub const CHATGPT_BASE_URL: &str = "https://chatgpt.com/backend-api/codex";
pub const BUILT_IN: &str = "openai";
pub const LOOK_SECONDS: f64 = 600.0;
pub const FRESH_SECONDS: f64 = 180.0;
pub const READ: &str = "config/read";
pub const ACCOUNT: &str = "account/read";

/// `_toml(value)`: a bool, an int, or a plain string as a TOML literal; Err (ValueError) for anything else.
pub fn toml(value: &Value) -> Result<String, Raised> {
    match value {
        Value::Bool(true) => Ok("true".into()),
        Value::Bool(false) => Ok("false".into()),
        Value::Int(int) => Ok(int.to_string()),
        Value::Str(text)
            if text.code_points().all(|point| {
                car_codex::labels::is_printable(point) && point != 0x22 && point != 0x5c
            }) =>
        {
            // Every point printable: no lone surrogate (none is printable), so the text is whole.
            Ok(format!("\"{}\"", text.as_str().unwrap_or_default()))
        }
        _ => Err(Raised::new("ValueError")),
    }
}

/// `overrides(attempts)`: the `-c` settings that make our server's turns use PROVIDER with both retries at
/// `attempts`. Refuses an Attempts it does not offer (ValueError).
pub fn overrides(attempts: &Value) -> Result<Vec<(String, String)>, Raised> {
    if !super::parallel::chosen_in(attempts, &ATTEMPTS) || matches!(attempts, Value::Bool(_)) {
        return Err(Raised::new("ValueError"));
    }
    let entry: [(&str, Value); 6] = [
        ("name", Value::Str("OpenAI".into())),
        ("base_url", Value::Str(CHATGPT_BASE_URL.into())),
        ("wire_api", Value::Str("responses".into())),
        ("requires_openai_auth", Value::Bool(true)),
        ("request_max_retries", attempts.clone()),
        ("stream_max_retries", attempts.clone()),
    ];
    let mut found = Vec::new();
    for (key, value) in entry {
        found.push((format!("model_providers.{PROVIDER}.{key}"), toml(&value)?));
    }
    found.push(("model_provider".into(), toml(&Value::Str(PROVIDER.into()))?));
    Ok(found)
}

fn config_of(read: &Value) -> Option<&Map> {
    match read {
        Value::Object(map) => match map.get("config") {
            Some(Value::Object(config)) => Some(config),
            _ => None,
        },
        _ => None,
    }
}

/// `codex/account.parse(reply)["kind"]`: the account's kind in lower case where it is one Codex names ("chatgpt",
/// "apikey"), else None - S7.2b's `codex::account::parse` itself, as the tag imports it (`parse as parse_account`;
/// Integration 10 pointed this here from the one field S7.2e1 read on its own).
pub fn account_kind(reply: &Value) -> Option<String> {
    match crate::codex::account::parse(reply) {
        Value::Object(found) => match found.get("kind") {
            Some(Value::Str(kind)) => kind.as_str().map(str::to_owned),
            _ => None,
        },
        _ => None,
    }
}

/// `fits(config_read, account_read)`: whether PROVIDER is a true copy of what the person's Codex uses.
pub fn fits(config_read: &Value, account_read: &Value) -> bool {
    let Some(config) = config_of(config_read) else {
        return false;
    };
    match config.get("model_provider") {
        None | Some(Value::Null) => {}
        Some(provider) if car_machine::pyval::eq(provider, &Value::Str(BUILT_IN.into())) => {}
        Some(_) => return false,
    }
    if !matches!(config.get("openai_base_url"), None | Some(Value::Null)) {
        return false;
    }
    match config.get("model_providers") {
        None | Some(Value::Null) => {}
        Some(Value::Object(providers)) if !providers.contains_key(PROVIDER) => {}
        Some(_) => return false,
    }
    account_kind(account_read).as_deref() == Some("chatgpt")
}

/// `in_force(now)`: the settings our own servers start with for this capability now, or none.
pub fn in_force(now: Option<f64>) -> Vec<(String, String)> {
    crate::codex::headless::retry_settings(now)
}

fn hold(settings: Vec<(String, String)>, now: f64) {
    let until = if settings.is_empty() {
        0.0
    } else {
        now + FRESH_SECONDS
    };
    crate::codex::headless::hold_retry_settings(settings, until);
}

/// A monotonic clock in seconds (`time.monotonic`).
pub type Monotonic = Arc<dyn Fn() -> f64 + Send + Sync>;

/// `time.monotonic()`: seconds since this process first asked.
pub fn monotonic() -> f64 {
    static START: std::sync::OnceLock<std::time::Instant> = std::sync::OnceLock::new();
    START
        .get_or_init(std::time::Instant::now)
        .elapsed()
        .as_secs_f64()
}

/// `RetrySettings(paths, session=..., clock=...)`: its P8 tick.
pub struct RetrySettings {
    pub paths: Paths,
    binding: Option<Binding>,
    open: Arc<Mutex<Opener>>,
    clock: Monotonic,
    looked: Option<f64>,
    fits: bool,
}

impl RetrySettings {
    /// `session` opens the look's session (a live one on our own server where none is given: S7.3d's world), `clock`
    /// is the monotonic clock.
    pub fn new(paths: Paths, open: Arc<Mutex<Opener>>, clock: Monotonic) -> RetrySettings {
        RetrySettings {
            paths,
            binding: None,
            open,
            clock,
            looked: None,
            fits: false,
        }
    }

    /// `_look()`: one look on our own server (config/read, account/read); anything that fails is no.
    fn look(&self) -> bool {
        let opened = {
            let mut open = self.open.lock().unwrap_or_else(PoisonError::into_inner);
            (open)(CAPABILITY)
        };
        let Ok(mut session) = opened else {
            return false;
        };
        if session.enter().is_err() {
            return false;
        }
        let mut layers = Map::new();
        layers.insert("includeLayers".into(), Value::Bool(false));
        let found = match session.call(READ, Some(Value::Object(layers))) {
            Ok(read) => match session.call(ACCOUNT, Some(Value::Object(Map::new()))) {
                Ok(account) => fits(&read, &account),
                Err(_) => false,
            },
            Err(_) => false,
        };
        session.exit();
        found
    }
}

impl Code for RetrySettings {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(binding);
        Some(Ok(()))
    }

    /// P8: look again whether the provider fits (at most once a LOOK_SECONDS) and keep the settings in force. DEFER.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let now = (self.clock)();
        if self
            .looked
            .is_none_or(|looked| now - looked >= LOOK_SECONDS)
        {
            self.fits = self.look();
            self.looked = Some(now);
        }
        let settings = if self.fits {
            let wanted = self
                .binding
                .as_ref()
                .and_then(|binding| {
                    binding.with(|scoped| {
                        super::parallel::option_in(
                            scoped.options().map_err(|_| ()),
                            OptionKey::Attempts,
                            &ATTEMPTS,
                            DEFAULT_ATTEMPTS,
                        )
                    })
                })
                .unwrap_or(Value::from(DEFAULT_ATTEMPTS));
            overrides(&wanted)?
        } else {
            Vec::new()
        };
        hold(settings, now);
        Ok(Said::Defer)
    }
}

/// `make(paths)`: no session of our own server until the entry points hand one (each look fails: nothing in force).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    make_with(
        paths,
        Arc::new(Mutex::new(Box::new(|_: &str| Err(())))),
        Arc::new(monotonic),
    )
}

/// `RetrySettings(paths, session=..., clock=...)` with an entry point's or a test's own.
pub fn make_with(
    paths: &Paths,
    open: Arc<Mutex<Opener>>,
    clock: Monotonic,
) -> Option<Box<dyn Code>> {
    Some(Box::new(RetrySettings::new(paths.clone(), open, clock)))
}

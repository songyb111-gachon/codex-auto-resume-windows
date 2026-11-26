//! `engine/account.py` (seat S7.2b): the watcher's side of account_switch - which account is signed in, and what waits
//! when it changes.
//!
//! At P8, as an errand, on the watcher's first tick and then at most every LOOK_EVERY seconds while the capability
//! stands on, the account is read (`codex::account::read`). What is kept of it is a digest (HMAC-SHA256 over its address
//! in lower case, keyed by this installation's salt in Credential Manager) and its plan word, in state `account_seen`.
//! Never the address, never the salt.
//!
//! * The first reading since the capability was last turned on keeps the digest under a new salt, and holds nothing.
//! * The same digest again holds nothing, whatever the plan says now.
//! * Another digest holds every recovery of core's still waiting for a usage limit (core's `hold_waiting`, kind
//!   `account_changed`) - unless account_auto_switch itself put that account in (`profiles.switched_to`) - and every
//!   reset rule still counting (held as over a gap in the count); stamps ACCOUNT_CHANGED_AT; counts `changed` and one
//!   `held` for each; and leaves one notice of how many wait ([`AccountWatch::notice_view`], for the surfaces).
//! * A reading that failed, or that finds no one signed in, changes nothing (E1).
//!
//! Turned off, the row and the salt are taken away ([`forget`]). The seams are the reference's: the read, Credential
//! Manager, core's hold and the automatic switch's own record.

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::plug::{Errand, Guards, HookFailed, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::account;
use crate::codex::authfile::Fault;
use crate::seam_p7::ResetWatch;
use crate::state::scoped::Scoped;
use crate::state::seam::Tokens;
use crate::vocabulary::{OptionKey, RuleReason, RuleState};

pub const CAPABILITY: &str = account::CAPABILITY;
pub const SALT: &str = "salt";
pub const LOOK_EVERY: f64 = 1800.0;
pub const HOLD: &str = "account_changed";
pub const USAGE_LIMIT: &str = "usage_limit";

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn state_fault(error: crate::state::errors::Error) -> Fault {
    Fault::new("StateError", &format!("{error:?}"))
}

/// Credential Manager as the code asks it (`credentials.Secrets`' shape).
pub trait SaltStore: Send + Sync {
    fn read(&self, capability: &str, name: &str) -> Result<Option<String>, Fault>;
    fn write(&self, capability: &str, name: &str, secret: &str) -> Result<(), Fault>;
    fn delete(&self, capability: &str, name: &str) -> Result<bool, Fault>;
}

impl SaltStore for crate::credentials::Secrets<'_> {
    fn read(&self, capability: &str, name: &str) -> Result<Option<String>, Fault> {
        crate::credentials::Secrets::read(self, capability, &text(name))
            .map_err(|error| Fault::new("SecretError", error.0))
    }
    fn write(&self, capability: &str, name: &str, secret: &str) -> Result<(), Fault> {
        crate::credentials::Secrets::write(self, capability, &text(name), &text(secret))
            .map_err(|error| Fault::new("SecretError", error.0))
    }
    fn delete(&self, capability: &str, name: &str) -> Result<bool, Fault> {
        crate::credentials::Secrets::delete(self, capability, &text(name))
            .map_err(|error| Fault::new("SecretError", error.0))
    }
}

/// `engine/resetwatch.count(rule, row)` (S7.2d's module; the seam `seam_p7::ResetWatch`), as the tag has it: fills for a
/// credit, resets for a message. The integration points `TagCount` at S7.2d's own.
pub struct TagCount;

impl ResetWatch for TagCount {
    fn count(&self, rule: &Value, row: &Value) -> i64 {
        let field = if rule_get(rule, "capability")
            .is_some_and(|capability| pyval::is(capability, crate::state::resets::CREDIT))
        {
            "hits"
        } else {
            "resets"
        };
        rule_get(row, field)
            .and_then(crate::state::py::small)
            .unwrap_or(0)
    }
}

fn rule_get<'a>(row: &'a Value, key: &str) -> Option<&'a Value> {
    match row {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

/// `forget(state, secrets=)`: account_switch is off - the salt out of Credential Manager and then the account seen out
/// of the state, where there is a row. Whether both went.
pub fn forget(state: &crate::state::session::AdvancedState, secrets: &dyn SaltStore) -> bool {
    match state.account_seen() {
        Ok(None) | Err(_) => false,
        Ok(Some(_)) => {
            if secrets.delete(CAPABILITY, SALT).is_err() {
                return false;
            }
            state.end_account_seen().unwrap_or(false)
        }
    }
}

/// The seams of [`AccountWatch`].
pub struct Seams {
    /// `read(paths)`: codex/account.read's shape.
    pub read: Box<dyn Fn() -> Value + Send + Sync>,
    /// Credential Manager.
    pub secrets: Box<dyn SaltStore>,
    /// `hold(paths, keys, now)`: core's records held for the person; how many.
    pub hold: Box<dyn Fn(&[String], f64) -> Result<i64, Fault> + Send + Sync>,
    /// `ours(paths, text, after)`: whether account_auto_switch put that account in at or after `after`.
    pub ours: Box<dyn Fn(&Value, &Value) -> bool + Send + Sync>,
    /// `account.new_salt()`'s random source.
    pub tokens: Arc<dyn Tokens>,
    /// `engine/resetwatch.count`.
    pub count: Box<dyn ResetWatch + Send + Sync>,
}

struct Inner {
    seams: Seams,
    looked: Option<f64>,
    notice: Option<Value>,
}

/// account_switch's code: its P8 errand, and the notice it asks the watcher to show.
pub struct AccountWatch {
    binding: Option<Arc<Binding>>,
    inner: Arc<Mutex<Inner>>,
}

fn lock(inner: &Mutex<Inner>) -> std::sync::MutexGuard<'_, Inner> {
    inner.lock().unwrap_or_else(PoisonError::into_inner)
}

impl AccountWatch {
    pub fn new(seams: Seams) -> AccountWatch {
        AccountWatch {
            binding: None,
            inner: Arc::new(Mutex::new(Inner {
                seams,
                looked: None,
                notice: None,
            })),
        }
    }

    /// `notice()`: {"key", "count"} of the last change that held anything, for the watcher to show once - or None.
    pub fn notice_view(&self) -> Value {
        lock(&self.inner).notice.clone().unwrap_or(Value::Null)
    }

    /// `look(view, now)` on this capability's own `Scoped`: one reading, compared with the account seen.
    pub fn look(&self, scoped: &Scoped<'_>, view: &dyn View, now: f64) -> Result<(), Fault> {
        look(&mut lock(&self.inner), scoped, view, now)
    }
}

fn look(inner: &mut Inner, scoped: &Scoped<'_>, view: &dyn View, now: f64) -> Result<(), Fault> {
    let found = (inner.seams.read)();
    let Some(identity) = account::identity(&found)? else {
        return Ok(()); // failed, or no one signed in: nothing changes
    };
    let plan = match &found {
        Value::Object(map) => map.get("plan_word").cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    scoped.handle().account_guard(false).map_err(state_fault)?;
    let row = scoped.state.account_seen().map_err(state_fault)?;
    let since = scoped.since().map_err(state_fault)?;
    let mut salt: Option<String> = None;
    if let Some(row) = &row {
        let read_at = row.get("read_at").cloned().unwrap_or(Value::Null);
        let older = matches!(since, Value::Int(_) | Value::Float(_) | Value::Bool(_))
            && pyval::less(&read_at, &since).map_err(|class| Fault::new(class, "<"))?;
        if !older {
            salt = inner.seams.secrets.read(CAPABILITY, SALT)?;
        }
    }
    let at = Value::Float(now);
    let save = |digest: &str| -> Result<(), Fault> {
        scoped.handle().account_guard(true).map_err(state_fault)?;
        scoped
            .state
            .save_account_seen(&text(digest), &plan, &at)
            .map_err(state_fault)
    };
    let Some(salt) = salt else {
        // The first reading since it was turned on (or a salt that is gone): a new salt, and nothing held.
        let salt = account::new_salt(inner.seams.tokens.as_ref());
        inner.seams.secrets.write(CAPABILITY, SALT, &salt)?;
        save(&account::digest(&identity, &text(&salt))?)?;
        return Ok(());
    };
    let seen = account::digest(&identity, &text(&salt))?;
    let row = row.unwrap_or_default();
    if row
        .get("identity_digest")
        .is_some_and(|kept| pyval::eq(kept, &text(&seen)))
    {
        save(&seen)?;
        return Ok(());
    }
    let read_at = row.get("read_at").cloned().unwrap_or(Value::Null);
    let ours = (inner.seams.ours)(&identity, &read_at);
    let waiting = if ours {
        0
    } else {
        hold_waiting(inner, view, now)?
    };
    let held = waiting + hold_rules(inner, scoped)?;
    save(&seen)?;
    // v0.6.20 (the pair audit, V20-2): when, for window_anchor - whose window stamps are the other account's.
    scoped
        .stamp(
            &text(OptionKey::AccountChangedAt.as_str()),
            &Value::from((now.trunc() as i64).max(1)),
        )
        .map_err(state_fault)?;
    let _ = scoped.count(&text("changed"));
    for _ in 0..held {
        let _ = scoped.count(&text("held"));
    }
    if held > 0 {
        let mut notice = Map::new();
        notice.insert(
            Str::new("key"),
            text(&format!("account:{}", now.trunc() as i64)),
        );
        notice.insert(Str::new("count"), Value::from(held));
        inner.notice = Some(Value::Object(notice));
    }
    Ok(())
}

/// `_hold_waiting(view, now)`: every recovery of core's still waiting for a usage limit, held for the person.
fn hold_waiting(inner: &Inner, view: &dyn View, now: f64) -> Result<i64, Fault> {
    let rows = view
        .records_in(car_machine::vocab_gen::domain_states::WAITING)
        .map_err(|failed| Fault::new(failed.0, "a view read failed"))?;
    let mut keys: Vec<String> = Vec::new();
    for row in &rows {
        if !rule_get(row, "category").is_some_and(|category| pyval::is(category, USAGE_LIMIT)) {
            continue;
        }
        let key = rule_get(row, "interruption_id")
            .ok_or_else(|| Fault::new("KeyError", "interruption_id"))?;
        let key = match key {
            Value::Str(found) => found.as_str().unwrap_or_default().to_owned(),
            other => car_machine::pytext::py_str(other),
        };
        if !keys.contains(&key) {
            keys.push(key);
        }
    }
    keys.sort();
    if keys.is_empty() {
        return Ok(0);
    }
    (inner.seams.hold)(&keys, now)
}

fn minus(a: &Value, b: &Value) -> Value {
    match (a, b) {
        (Value::Int(_), Value::Int(_)) => match (crate::state::py::small(a), crate::state::py::small(b)) {
            (Some(x), Some(y)) => Value::from(x - y),
            _ => Value::Float(pyval::minus(a, b).unwrap_or(0.0)),
        },
        _ => Value::Float(pyval::minus(a, b).unwrap_or(0.0)),
    }
}

/// `max(low, value)` as Python picks: the first of the greatest.
fn at_least(low: i64, value: &Value) -> Value {
    if pyval::greater(value, &Value::from(low)).unwrap_or(false) {
        value.clone()
    } else {
        Value::from(low)
    }
}

/// `_hold_rules()`: every reset rule still counting, held as over a gap in its count, for what it had left to count.
fn hold_rules(inner: &Inner, scoped: &Scoped<'_>) -> Result<i64, Fault> {
    let windows = scoped.state.windows().map_err(state_fault)?;
    let rules = scoped
        .state
        .reset_rules(&Value::Null, &Value::Bool(true))
        .map_err(state_fault)?;
    let mut held = 0;
    for rule in rules {
        let rule = Value::Object(rule);
        if !rule_get(&rule, "state").is_some_and(|state| pyval::is(state, RuleState::Counting.as_str())) {
            continue;
        }
        let key = (
            rule_get(&rule, "bucket").cloned().unwrap_or(Value::Null),
            rule_get(&rule, "minutes").cloned().unwrap_or(Value::Null),
        );
        let row = windows
            .iter()
            .find(|((bucket, minutes), _)| pyval::eq(bucket, &key.0) && pyval::eq(minutes, &key.1))
            .map(|(_, row)| Value::Object(row.clone()));
        let base = rule_get(&rule, "base").cloned().unwrap_or(Value::Null);
        let counted = match &row {
            Some(row) if !matches!(base, Value::Null) => {
                minus(&Value::from(inner.seams.count.count(&rule, row)), &base)
            }
            _ => Value::from(0),
        };
        let ordinal = rule_get(&rule, "ordinal").cloned().unwrap_or(Value::Null);
        let left = minus(&ordinal, &at_least(0, &counted));
        let changes = vec![
            ("state".to_owned(), text(RuleState::Held.as_str())),
            ("reason".to_owned(), text(RuleReason::CountGap.as_str())),
            ("ordinal".to_owned(), at_least(1, &left)),
            ("base".to_owned(), Value::Null),
            ("adopted_at".to_owned(), Value::Null),
        ];
        if scoped.handle().resets_writing().is_err() {
            continue;
        }
        if let Ok(true) = scoped.state.change_rule(
            rule_get(&rule, "rule_id").unwrap_or(&Value::Null),
            &text(RuleState::Counting.as_str()),
            &changes,
        ) {
            held += 1;
        }
    }
    Ok(held)
}

/// The P8 errand: one look, outside the tick; whatever it raises is a reading that changed nothing.
struct LookErrand {
    inner: Arc<Mutex<Inner>>,
    binding: Arc<Binding>,
    now: f64,
}

impl Errand for LookErrand {
    fn run(&self, view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let mut inner = lock(&self.inner);
        let _ = self
            .binding
            .with(|scoped| look(&mut inner, scoped, view, self.now));
        Ok(Value::Null)
    }
}

impl Code for AccountWatch {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(Arc::new(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = &self.binding else {
            return Ok(Said::Defer);
        };
        let Some(now) = binding.with(|scoped| scoped.now()) else {
            return Ok(Said::Defer);
        };
        let mut inner = lock(&self.inner);
        if let Some(looked) = inner.looked
            && (0.0..LOOK_EVERY).contains(&(now - looked))
        {
            return Ok(Said::Defer);
        }
        inner.looked = Some(now);
        Ok(Said::Errand(Box::new(LookErrand {
            inner: Arc::clone(&self.inner),
            binding: Arc::clone(binding),
            now,
        })))
    }

    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        Some(self)
    }
}

/// `make(paths)`: the code with the product's own hands - account/read through this capability's own session,
/// Credential Manager, core's store and the saved accounts' record (`make_with` for an entry point's or a test's).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(AccountWatch::new(live_seams(paths))))
}

/// `make` with the code's hands given.
pub fn make_with(seams: Seams) -> Option<Box<dyn Code>> {
    Some(Box::new(AccountWatch::new(seams)))
}

/// The product's own hands for `paths`.
pub fn live_seams(paths: &Paths) -> Seams {
    let reading = paths.clone();
    let holding = paths.clone();
    let switching = paths.clone();
    Seams {
        read: Box::new(move || account::read(&crate::codex::account::Live::new(&reading))),
        secrets: Box::new(LiveSecrets),
        hold: Box::new(move |keys: &[String], now: f64| {
            let store = car_store::Store::open(
                std::path::Path::new(&holding.state_dir),
                Arc::new(car_control::host::Probe),
            )
            .map_err(|error| Fault::new("StoreError", &error.to_string()))?;
            store
                .hold_waiting(keys, HOLD, now, "engine")
                .map_err(|error| Fault::new("StoreError", &error.to_string()))
        }),
        ours: Box::new(move |identity: &Value, after: &Value| {
            crate::state::seam::accounts::live_profiles(std::path::Path::new(&switching.home))
                .switched_to(identity, after)
                .unwrap_or(false)
        }),
        tokens: Arc::new(crate::credentials::SystemTokens),
        count: Box::new(TagCount),
    }
}

/// Credential Manager under the registry the edition ships.
struct LiveSecrets;

impl LiveSecrets {
    fn with<T>(&self, body: impl FnOnce(&dyn SaltStore) -> Result<T, Fault>) -> Result<T, Fault> {
        let registry = crate::registry::shipped(false)
            .map_err(|error| Fault::new("SecretError", &format!("{error:?}")))?;
        body(&crate::credentials::Secrets::windows(&registry))
    }
}

impl SaltStore for LiveSecrets {
    fn read(&self, capability: &str, name: &str) -> Result<Option<String>, Fault> {
        self.with(|secrets| secrets.read(capability, name))
    }
    fn write(&self, capability: &str, name: &str, secret: &str) -> Result<(), Fault> {
        self.with(|secrets| secrets.write(capability, name, secret))
    }
    fn delete(&self, capability: &str, name: &str) -> Result<bool, Fault> {
        self.with(|secrets| secrets.delete(capability, name))
    }
}

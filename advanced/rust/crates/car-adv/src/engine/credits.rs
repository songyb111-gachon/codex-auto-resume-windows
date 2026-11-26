//! `engine/credits.py` (seat S7.2d): use a reset credit when the limit a person picked is reached (v0.6.14) -
//! reset_credit, at P8 and P7.
//!
//! When the window a rule waits for fills ([`super::resetwatch`]), and only while a recovery waits for usage, the
//! errand spends one: a fresh detailed reading (still full, or the rule lapses); the count and the soonest expiry both
//! readable (or it asks the person); two in a day and seven in a week at most, one for each filling; on its own only
//! where MR passed and the person did not choose Ask me first; the spend written with a key of its own before Codex is
//! asked; the one request inside core's errand guard; what came of it kept. An outcome unknown ten minutes on is asked
//! once more with the same key where MR passed, else the rule ends unknown and the capability turns itself off.
//!
//! Nothing but that one request is sent, never a turn. The session is the capability's own (`codex::session`), opened
//! once a look, at its first need; [`Opener`] is the seam a probe fills.

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::{Alternative, Errand, Guards, HookFailed, View};

use super::resetwatch::{self, Failed, Family, Resets, Row, Watch, num};
use super::usage::{Bound, field, is_word};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::credits;
use crate::codex::session::{Channel, SessionError};

pub const CAPABILITY: &str = "reset_credit";
/// One spend for each filling of a window, two in a day, seven in a week.
pub const DAILY: usize = 2;
pub const WEEKLY: usize = 7;
pub const DAY: f64 = 86400.0;
pub const WEEK: f64 = 7.0 * 86400.0;
/// A spend whose outcome is not known this long after it was written is unknown.
pub const UNKNOWN_AFTER: f64 = 600.0;
/// How long a person's Use now stands, and how long after a reset waiting recoveries are looked at early.
pub const USE_NOW: f64 = 900.0;
pub const EARLY_FOR: f64 = 900.0;
/// What a due rule waits for a person for.
pub const WAITS_FOR_A_PERSON: [&str; 2] = ["ask_first", "no_method"];
/// Codex's error code for a method it does not have.
pub const METHOD_NOT_FOUND: i64 = -32601;
/// `ladder.EARLY_STATES`.
pub const EARLY_STATES: [&str; 3] = ["waiting_reset", "waiting_poll", "waiting_for_usage"];

/// `OUTCOME_REASONS[outcome]`, `OUTCOME_CODES[outcome]`.
fn outcome_reason(outcome: &str) -> Option<(&'static str, &'static str)> {
    match outcome {
        "reset" | "already_redeemed" => Some(("spent", "spent")),
        "nothing_to_reset" => Some(("nothing_to_reset", "nothing")),
        "no_credit" => Some(("no_credit", "no_credit")),
        _ => None,
    }
}

/// The outcomes that spent a credit, or may have (None among them).
fn spending(outcome: &Value) -> bool {
    matches!(outcome, Value::Null)
        || ["reset", "already_redeemed", "unknown"]
            .iter()
            .any(|word| is_word(outcome, word))
}

/// `str(uuid.uuid4())`: the spend's own key (car-platform's random source in the product).
pub type Keys = Arc<dyn Fn() -> String + Send + Sync>;

/// Opens the capability's own session: `Session(inuse.backend(paths), capability=...)` in the product.
pub type Opener = Arc<dyn Fn(&Paths, &str) -> Result<Box<dyn Channel>, SessionError> + Send + Sync>;

/// The product's opener: the told (or discovered) backend, a session of the capability's own.
pub fn system_opener() -> Opener {
    Arc::new(|paths: &Paths, capability: &str| {
        let backend = super::usage::system_backend(paths)
            .map_err(|_| SessionError::Adapter("backend_unavailable"))?;
        let session =
            crate::codex::session::Session::new(backend, None, Some(capability), Vec::new())?;
        Ok(Box::new(session) as Box<dyn Channel>)
    })
}

/// `_Lazy(make)`: one session for one look, opened the first time it is needed and closed at the look's end.
pub struct Lazy<'a> {
    make: Box<dyn FnMut() -> Result<Box<dyn Channel>, SessionError> + 'a>,
    session: Option<Box<dyn Channel>>,
}

impl<'a> Lazy<'a> {
    pub fn new(make: impl FnMut() -> Result<Box<dyn Channel>, SessionError> + 'a) -> Lazy<'a> {
        Lazy {
            make: Box::new(make),
            session: None,
        }
    }

    /// `session()`: made and entered once; a make or an enter that raises leaves none.
    pub fn get(&mut self) -> Result<&mut Box<dyn Channel>, SessionError> {
        if self.session.is_none() {
            let mut made = (self.make)()?;
            made.enter()?;
            self.session = Some(made);
        }
        Ok(self.session.as_mut().expect("made above"))
    }

    pub fn close(&mut self) {
        if let Some(mut session) = self.session.take() {
            session.exit();
        }
    }
}

fn session_raise(error: &SessionError) -> Raised {
    Raised::new(error.class())
}

/// Whether an exception is an AdapterError (or a kind of one) the reference's `except AdapterError` catches.
fn is_adapter(error: &SessionError) -> bool {
    matches!(
        error,
        SessionError::Adapter(_) | SessionError::ByCodex { .. }
    )
}

/// `awaits_usage(view)`: whether a recovery waits for usage now.
pub fn awaits_usage(view: &dyn View) -> Result<bool, Raised> {
    let Ok(rows) = view.records_in(resetwatch::waiting_states()) else {
        return Ok(false);
    };
    for row in &rows {
        if is_word(super::usage::get_of(row, "category")?, "usage_limit") {
            return Ok(true);
        }
    }
    Ok(false)
}

fn get<'a>(row: &'a Row, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    row.get(&car_machine::json::Str::new(name)).unwrap_or(&NULL)
}

fn failed(error: Failed) -> Raised {
    error.raised()
}

/// What the errand keeps between looks: the rules that read usage lately (`_tried`), in this process.
pub struct Inner {
    pub paths: Paths,
    bound: Option<Bound>,
    open: Opener,
    keys: Keys,
    pub tried: Vec<(Value, f64)>,
}

/// `ResetCredit(paths, session=None)`.
pub struct ResetCredit {
    inner: Arc<Mutex<Inner>>,
}

impl ResetCredit {
    pub fn new(paths: Paths, open: Opener, keys: Keys) -> ResetCredit {
        ResetCredit {
            inner: Arc::new(Mutex::new(Inner {
                paths,
                bound: None,
                open,
                keys,
                tried: Vec::new(),
            })),
        }
    }

    pub fn bind_to(&mut self, bound: Bound) {
        self.lock().bound = Some(bound);
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The errand's look, as a probe runs it (`_Errand.run`).
    pub fn look(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, Raised> {
        self.lock().look(view, guards)
    }

    /// `_tried`, for a probe.
    pub fn tried(&self) -> Vec<(Value, f64)> {
        self.lock().tried.clone()
    }
}

/// P8's errand.
struct CreditErrand {
    inner: Arc<Mutex<Inner>>,
}

impl Errand for CreditErrand {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let mut inner = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        inner.look(view, guards).map_err(|_| HookFailed)
    }
}

impl Inner {
    fn resets(&self) -> Option<Resets> {
        self.bound.clone().map(|bound| Resets { bound })
    }

    fn count(&self, code: &str) {
        if let Some(bound) = &self.bound {
            bound.with(|scoped| {
                let _ = scoped.count(&Value::from(code));
            });
        }
    }

    fn measured(&self, measurement: &str, passed: bool) -> bool {
        self.bound
            .as_ref()
            .and_then(|bound| {
                bound.with(|scoped| {
                    let word = Value::from(measurement);
                    if passed {
                        scoped.passed(&word)
                    } else {
                        scoped.failed(&word)
                    }
                })
            })
            .unwrap_or(false)
    }

    /// `look(view, guard)`: count, then act on every rule that is due; `{"trip": reason}` where the runtime is asked
    /// to trip it.
    pub fn look(&mut self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, Raised> {
        let Some(handle) = self.resets() else {
            return Err(Raised::new("AttributeError"));
        };
        if !handle.on() {
            return Ok(Value::Null);
        }
        let open = self.open.clone();
        let paths = self.paths.clone();
        let mut session = Lazy::new(move || open(&paths, CAPABILITY));
        let done = self.looked(view, guards, &handle, &mut session);
        session.close();
        done
    }

    fn looked(
        &mut self,
        view: &dyn View,
        guards: &mut Guards<'_>,
        handle: &Resets,
        session: &mut Lazy<'_>,
    ) -> Result<Value, Raised> {
        let early = !self.measured("mu", false);
        let light = self.measured("mu", true);
        let looked = {
            let mut reader = |params: &Value| -> Result<Value, Raised> {
                let opened = session.get().map_err(|error| session_raise(&error))?;
                opened
                    .call(credits::READ, Some(params.clone()))
                    .map_err(|error| session_raise(&error))
            };
            let mut watch = Watch {
                resets: handle,
                reader: Some(&mut reader),
                early,
                light,
                keep_credits: true,
            };
            watch.step(Some(view), false)?
        };
        let now = handle.now();
        self.tried
            .retain(|(_, at)| (0.0..resetwatch::READ_SPACING).contains(&(now - at)));
        let mut detailed: Option<Option<Value>> = None;
        let mut trip = self.spend_unknown(handle, session, guards)?;
        let rules = handle
            .reset_rules(Some(CAPABILITY), &Value::Bool(true))
            .map_err(failed)?;
        for rule in rules {
            let found =
                self.consider(&rule, &looked, handle, session, guards, view, &mut detailed)?;
            if trip.is_none() {
                trip = found;
            }
        }
        Ok(match trip {
            Some(reason) => {
                let mut map = Map::new();
                map.insert("trip".into(), Value::from(reason));
                Value::Object(map)
            }
            None => Value::Null,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn consider(
        &mut self,
        rule: &Row,
        looked: &resetwatch::Looked,
        handle: &Resets,
        session: &mut Lazy<'_>,
        guards: &mut Guards<'_>,
        view: &dyn View,
        detailed: &mut Option<Option<Value>>,
    ) -> Result<Option<&'static str>, Raised> {
        let family: Family = (get(rule, "bucket").clone(), get(rule, "minutes").clone());
        let row = resetwatch::find(&looked.rows, &family).cloned();
        let now = handle.now();
        for event in looked.events_of(&family) {
            if event == "gap" || event == "gone" {
                self.count(event);
            }
        }
        let Some(row) = row else { return Ok(None) };
        if is_word(get(rule, "state"), "held") {
            return Ok(None);
        }
        let full = car_machine::pyval::truthy(get(&row, "open_reset_at"))
            && car_machine::pyval::truthy(get(&row, "open_full"));
        if car_machine::pyval::eq(get(rule, "ordinal"), &Value::from(0)) {
            if now - num(get(rule, "created_at"))? >= USE_NOW || !full {
                return self.lapse(rule, &row, handle);
            }
            if !awaits_usage(view)? {
                self.ready(handle, rule, "nothing_waiting")?;
                return Ok(None);
            }
            return self.spend(rule, &row, handle, session, guards, detailed, true);
        }
        let mut rule = rule.clone();
        if is_word(get(&rule, "state"), "counting") {
            if !resetwatch::due(&rule, Some(&row))? {
                return Ok(None);
            }
            self.count("hit");
            handle
                .change_rule(
                    get(&rule, "rule_id"),
                    &Value::from("counting"),
                    &[
                        ("state", Value::from("ready")),
                        ("due_at", Value::from(now)),
                        ("reason", Value::Null),
                    ],
                )
                .map_err(failed)?;
            rule = resetwatch::with(
                &rule,
                &[
                    ("state", Value::from("ready")),
                    ("due_at", Value::from(now)),
                ],
            );
        }
        if !full {
            return self.lapse(&rule, &row, handle);
        }
        let reason = get(&rule, "reason");
        if WAITS_FOR_A_PERSON.iter().any(|word| is_word(reason, word)) {
            return Ok(None);
        }
        if !awaits_usage(view)? {
            self.ready(handle, &rule, "nothing_waiting")?;
            return Ok(None);
        }
        self.spend(&rule, &row, handle, session, guards, detailed, false)
    }

    fn ready(&self, handle: &Resets, rule: &Row, reason: &str) -> Result<(), Raised> {
        if !is_word(get(rule, "reason"), reason) {
            handle
                .change_rule(
                    get(rule, "rule_id"),
                    &Value::from("ready"),
                    &[("reason", Value::from(reason))],
                )
                .map_err(failed)?;
            if reason == "ask_first" {
                self.count("asked");
            }
        }
        Ok(())
    }

    fn lapse(
        &self,
        rule: &Row,
        row: &Row,
        handle: &Resets,
    ) -> Result<Option<&'static str>, Raised> {
        self.count("lapsed");
        self.finished(rule, row, handle, "lapsed")?;
        Ok(None)
    }

    fn finished(&self, rule: &Row, row: &Row, handle: &Resets, reason: &str) -> Result<(), Raised> {
        let repeat = car_machine::pyval::truthy(get(rule, "repeat"));
        if repeat && num(get(rule, "ordinal"))? > 0.0 {
            handle
                .change_rule(
                    get(rule, "rule_id"),
                    &Value::Null,
                    &[
                        ("state", Value::from("counting")),
                        ("reason", Value::Null),
                        ("base", get(row, "hits").clone()),
                        ("ordinal", Value::from(1)),
                        ("adopted_at", Value::from(handle.now())),
                        ("due_at", Value::Null),
                    ],
                )
                .map_err(failed)?;
        } else {
            handle
                .end_rule(get(rule, "rule_id"), "done", reason)
                .map_err(failed)?;
        }
        Ok(())
    }

    fn tried_at(&self, rule_id: &Value) -> Option<f64> {
        self.tried
            .iter()
            .find(|(held, _)| car_machine::pyval::eq(held, rule_id))
            .map(|(_, at)| *at)
    }

    fn set_tried(&mut self, rule_id: &Value, at: f64) {
        match self
            .tried
            .iter_mut()
            .find(|(held, _)| car_machine::pyval::eq(held, rule_id))
        {
            Some(held) => held.1 = at,
            None => self.tried.push((rule_id.clone(), at)),
        }
    }

    /// `_spend(...)`: steps 1 to 7 for one due rule; a trip's reason, or None.
    #[allow(clippy::too_many_arguments)]
    fn spend(
        &mut self,
        rule: &Row,
        row: &Row,
        handle: &Resets,
        session: &mut Lazy<'_>,
        guards: &mut Guards<'_>,
        detailed: &mut Option<Option<Value>>,
        clicked: bool,
    ) -> Result<Option<&'static str>, Raised> {
        let now = handle.now();
        let rule_id = get(rule, "rule_id").clone();
        if detailed.is_none() {
            if let Some(last) = self.tried_at(&rule_id)
                && (0.0..resetwatch::READ_SPACING).contains(&(now - last))
            {
                return Ok(None);
            }
            let early = !self.measured("mu", false);
            let mut reader = |params: &Value| -> Result<Value, Raised> {
                let opened = session.get().map_err(|error| session_raise(&error))?;
                opened
                    .call(credits::READ, Some(params.clone()))
                    .map_err(|error| session_raise(&error))
            };
            let mut watch = Watch {
                resets: handle,
                reader: Some(&mut reader),
                early,
                light: false,
                keep_credits: true,
            };
            *detailed = Some(watch.read(&credits::detailed()));
        }
        self.set_tried(&rule_id, now);
        let Some(Some(reading)) = detailed.clone() else {
            self.ready(handle, rule, "count_unknown")?;
            return Ok(None);
        };
        let known = car_machine::pyval::truthy(field(&reading, "expiry_known"));
        handle
            .set_reading(&[
                ("credits".to_owned(), field(&reading, "credits").clone()),
                ("expiry_known".to_owned(), Value::from(i64::from(known))),
                (
                    "nearest_expiry".to_owned(),
                    field(&reading, "nearest_expiry").clone(),
                ),
                ("read_at".to_owned(), Value::from(handle.now())),
            ])
            .map_err(failed)?;
        let family: Family = (get(rule, "bucket").clone(), get(rule, "minutes").clone());
        let window = resetwatch::family_window(field(&reading, "windows"), &family)?;
        let lapsed = match &window {
            None => true,
            Some(window) => {
                num(field(window, "used_percent"))? < 100.0
                    || matches!(field(window, "reset_at"), Value::Null)
            }
        };
        if lapsed {
            return self.lapse(rule, row, handle);
        }
        let count = field(&reading, "credits");
        if matches!(count, Value::Null) {
            self.ready(handle, rule, "count_unknown")?;
            return Ok(None);
        }
        if !known {
            self.ready(handle, rule, "expiry_unknown")?;
            return Ok(None);
        }
        if car_machine::pyval::eq(count, &Value::from(0)) {
            self.count("no_credit");
            self.finished(rule, row, handle, "no_credit")?;
            return Ok(None);
        }
        let now = handle.now();
        let recent = handle
            .credit_spends(&Value::from(now - WEEK))
            .map_err(failed)?;
        let mine = recent.iter().find(|spend| {
            car_machine::pyval::eq(get(spend, "bucket"), get(rule, "bucket"))
                && car_machine::pyval::eq(get(spend, "minutes"), get(rule, "minutes"))
                && car_machine::pyval::eq(get(spend, "occasion"), get(row, "hits"))
        });
        if let Some(mine) = mine {
            return self.settled(rule, row, handle, get(mine, "outcome"));
        }
        let spent: Vec<&Row> = recent
            .iter()
            .filter(|spend| spending(get(spend, "outcome")))
            .collect();
        let mut today = 0;
        for spend in &spent {
            if now - num(get(spend, "created_at"))? < DAY {
                today += 1;
            }
        }
        if today >= DAILY || spent.len() >= WEEKLY {
            self.ready(handle, rule, "bound")?;
            return Ok(None);
        }
        if !clicked
            && (car_machine::pyval::truthy(get(rule, "ask_first")) || !self.measured("mr", true))
        {
            self.ready(handle, rule, "ask_first")?;
            return Ok(None);
        }
        let key = (self.keys)();
        let spend = handle
            .add_credit_spend(
                &rule_id,
                get(rule, "bucket"),
                get(rule, "minutes"),
                get(row, "hits"),
                &key,
            )
            .map_err(failed)?;
        let Some(spend) = spend else {
            return Ok(None);
        };
        let asked = self.ask(
            rule,
            row,
            handle,
            session,
            guards,
            &Value::from(spend),
            &key,
            false,
        );
        *detailed = None;
        asked
    }

    fn settled(
        &self,
        rule: &Row,
        row: &Row,
        handle: &Resets,
        outcome: &Value,
    ) -> Result<Option<&'static str>, Raised> {
        if matches!(outcome, Value::Null) {
            return Ok(None);
        }
        if is_word(outcome, "unknown") {
            handle
                .end_rule(get(rule, "rule_id"), "done", "unknown")
                .map_err(failed)?;
        } else {
            let word = car_machine::pyval::text(outcome).unwrap_or_default();
            let Some((reason, _)) = outcome_reason(word) else {
                return Err(Raised::new("KeyError"));
            };
            self.finished(rule, row, handle, reason)?;
        }
        Ok(None)
    }

    /// `_ask(...)`: (6) and (7) - the one request inside the guard, its answer outside it.
    #[allow(clippy::too_many_arguments)]
    fn ask(
        &self,
        rule: &Row,
        row: &Row,
        handle: &Resets,
        session: &mut Lazy<'_>,
        guards: &mut Guards<'_>,
        spend: &Value,
        key: &str,
        retry: bool,
    ) -> Result<Option<&'static str>, Raised> {
        let mut opened = session.get().ok();
        let mut sequence: Option<i64> = None;
        let mut written = false;
        if let Some(channel) = opened.as_mut() {
            let mut submitted: Option<Result<i64, SessionError>> = None;
            let mut params = Map::new();
            params.insert("idempotencyKey".into(), Value::from(key));
            let guarded = guards(&mut |permitted| {
                if permitted {
                    written = true;
                    submitted =
                        Some(channel.submit(credits::CONSUME, Some(Value::Object(params.clone()))));
                }
                Value::Null
            });
            if guarded.is_err() {
                return Err(Raised::new("Exception"));
            }
            match submitted {
                None => {}
                Some(Ok(found)) => sequence = Some(found),
                Some(Err(error)) if is_adapter(&error) => sequence = None,
                Some(Err(error)) => return Err(session_raise(&error)),
            }
        }
        let (Some(sequence), Some(channel)) = (sequence, opened) else {
            if !retry && !written {
                handle.drop_credit_spend(spend).map_err(failed)?;
            }
            return Ok(None);
        };
        let reply = channel.receive(credits::CONSUME, sequence, None);
        let outcome = match reply {
            Ok(reply) => credits::outcome(&reply).as_str(),
            Err(error) if is_adapter(&error) => {
                let not_found = matches!(
                    error,
                    SessionError::ByCodex {
                        code: Some(METHOD_NOT_FOUND),
                        ..
                    }
                );
                if !not_found {
                    return Ok(None);
                }
                if !handle.drop_credit_spend(spend).map_err(failed)? {
                    handle
                        .finish_credit_spend(spend, "nothing_to_reset")
                        .map_err(failed)?;
                }
                self.ready(handle, rule, "no_method")?;
                return Ok(None);
            }
            Err(error) => return Err(session_raise(&error)),
        };
        if outcome == "unknown" {
            return Ok(None);
        }
        handle.finish_credit_spend(spend, outcome).map_err(failed)?;
        if outcome == "reset" || outcome == "already_redeemed" {
            let watch = Watch {
                resets: handle,
                reader: None,
                early: true,
                light: false,
                keep_credits: false,
            };
            let family: Family = (get(rule, "bucket").clone(), get(rule, "minutes").clone());
            watch.own_reset(&family, &Value::from(handle.now()))?;
        }
        let Some((reason, code)) = outcome_reason(outcome) else {
            return Err(Raised::new("KeyError"));
        };
        self.count(code);
        self.finished(rule, row, handle, reason)?;
        Ok(None)
    }

    /// `_spend_unknown(...)`: every spend with no outcome ten minutes on - asked once more with its key where MR
    /// passed, else (or a second time unknown) its rule ends unknown and the capability turns itself off.
    fn spend_unknown(
        &self,
        handle: &Resets,
        session: &mut Lazy<'_>,
        guards: &mut Guards<'_>,
    ) -> Result<Option<&'static str>, Raised> {
        let now = handle.now();
        for spend in handle
            .credit_spends(&Value::from(now - WEEK))
            .map_err(failed)?
        {
            if !matches!(get(&spend, "outcome"), Value::Null) {
                continue;
            }
            let tries = num(get(&spend, "tries"))?;
            if now - num(get(&spend, "created_at"))? < UNKNOWN_AFTER * tries {
                continue;
            }
            let rule = handle.reset_rule(get(&spend, "rule_id")).map_err(failed)?;
            if tries == 1.0
                && self.measured("mr", true)
                && let Some(rule) = &rule
            {
                let retried = handle
                    .retry_credit_spend(get(&spend, "spend_id"))
                    .map_err(failed)?;
                if retried {
                    let family: Family = (
                        get(&spend, "bucket").clone(),
                        get(&spend, "minutes").clone(),
                    );
                    let stored = handle.windows().map_err(failed)?;
                    let row = resetwatch::find(&stored, &family)
                        .filter(|row| !row.is_empty())
                        .cloned()
                        .unwrap_or_else(|| resetwatch::blank(&family.0, &family.1));
                    let key = car_machine::pytext::py_str(get(&spend, "attempt_id"));
                    self.ask(
                        rule,
                        &row,
                        handle,
                        session,
                        guards,
                        get(&spend, "spend_id"),
                        &key,
                        true,
                    )?;
                    continue;
                }
            }
            handle
                .finish_credit_spend(get(&spend, "spend_id"), "unknown")
                .map_err(failed)?;
            if let Some(rule) = rule {
                let state = get(&rule, "state");
                if ["counting", "ready", "held"]
                    .iter()
                    .any(|word| is_word(state, word))
                {
                    handle
                        .end_rule(get(&rule, "rule_id"), "done", "unknown")
                        .map_err(failed)?;
                }
            }
            self.count("unknown");
            return Ok(Some("submission_unknown"));
        }
        Ok(None)
    }
}

impl Code for ResetCredit {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.lock().bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    /// P7: EARLY for a usage-limited record core holds as waiting for its reset, for fifteen minutes after one of
    /// this capability's spends reset a window; DEFER for everything else.
    fn schedule(&mut self, record: &Value, due: &Value) -> Spoke {
        let inner = self.lock();
        let Some(handle) = inner.resets() else {
            return Ok(Said::Defer);
        };
        let Value::Object(_) = record else {
            return Ok(Said::Defer);
        };
        let state = field(record, "state");
        if !is_word(field(record, "category"), "usage_limit")
            || !EARLY_STATES.iter().any(|word| is_word(state, word))
            || !matches!(due, Value::Int(_) | Value::Float(_) | Value::Bool(_))
        {
            return Ok(Said::Defer);
        }
        let now = handle.now();
        if num(due)? <= now {
            return Ok(Said::Defer);
        }
        let Ok(recent) = handle.credit_spends(&Value::from(now - EARLY_FOR)) else {
            return Ok(Said::Defer);
        };
        let mut reset = false;
        for spend in &recent {
            let finished = get(spend, "finished_at");
            if is_word(get(spend, "outcome"), "reset")
                && !matches!(finished, Value::Null)
                && (0.0..EARLY_FOR).contains(&(now - num(finished)?))
            {
                reset = true;
                break;
            }
        }
        Ok(if reset {
            Said::Word(Alternative::Early)
        } else {
            Said::Defer
        })
    }

    /// P8: an errand, while a rule of this capability waits; DEFER otherwise.
    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let pending = {
            let inner = self.lock();
            let Some(handle) = inner.resets() else {
                return Ok(Said::Defer);
            };
            match handle.reset_rules(Some(CAPABILITY), &Value::Bool(true)) {
                Ok(found) => !found.is_empty(),
                Err(_) => return Ok(Said::Defer),
            }
        };
        if !pending {
            return Ok(Said::Defer);
        }
        Ok(Said::Errand(Box::new(CreditErrand {
            inner: self.inner.clone(),
        })))
    }
}

/// `make(paths)`: the capability's code for one installation, its session the product's own.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(ResetCredit::new(
        paths.clone(),
        system_opener(),
        Arc::new(car_platform::ipc_pipe::uuid4),
    )))
}

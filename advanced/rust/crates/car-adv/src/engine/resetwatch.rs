//! `engine/resetwatch.py` (seat S7.2d): counting the usage windows' resets and fills (v0.6.14) - what "the Nth next
//! 5-hour limit" is, across restarts.
//!
//! One row a family (bucket, length in minutes), kept while a pending rule names it; each successful reading at time t
//! applies [`advance`]: closed by time (t >= R + 60), replaced early (the reset time moved by more than TOL, where MU did
//! not fail), opened (used above 0 % with a reset ahead that is not the one last closed), filled (100 % once per window),
//! and this edition's own credit closing the open window ([`closed`]). A gap longer than the window holds its rules
//! (`count_gap`), a family missing from three readings is gone (`window_gone`).
//!
//! [`Watch`] is the runner: the reset action's own view of the state (`scoped.resets`, writes only while it is on), the
//! readings, the rules adopted and held. Kept from the reference: a rule's families are a set there, so the order in
//! which the windows are saved and the events listed is Python's hash order; here it is the order the rules name them
//! (AUDIT-v0628.md) - nothing reads that order but the table's own row ids.

use car_machine::json::{Map, Value};

use super::usage::{Bound, field, is_word, number, raised};
use crate::capabilities::Raised;
use crate::codex::credits;
use crate::state::Error;

/// The reset credit's rules count fills; the message's, resets.
pub const CREDIT: &str = "reset_credit";
/// How far a window's reset time may move before it is another window.
pub const TOL: i64 = 600;
/// A window open until R is closed by time this long after R.
pub const CLOSE_AFTER: i64 = 60;
/// This edition's own readings: at most one in five minutes, every fifteen while a rule is pending.
pub const READ_SPACING: f64 = 300.0;
pub const POLL: f64 = 900.0;
/// Successful readings in a row a family may be missing from before it is gone.
pub const MISSES: i64 = 3;

/// A row, as the reference's dicts are (insertion order kept, a key set again kept in its place).
pub type Row = Map;
/// (bucket, minutes).
pub type Family = (Value, Value);
/// `{family: row}`, in the order the reference's dict keeps.
pub type Rows = Vec<(Family, Row)>;

fn key(name: &str) -> car_machine::json::Str {
    car_machine::json::Str::new(name)
}

fn get<'a>(row: &'a Row, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    row.get(&key(name)).unwrap_or(&NULL)
}

/// `dict(row, **changes)`.
pub fn with(row: &Row, changes: &[(&str, Value)]) -> Row {
    let mut out = row.clone();
    for (name, value) in changes {
        out.insert(key(name), value.clone());
    }
    out
}

/// A number as arithmetic and comparisons read it; TypeError for anything else (None among them).
pub fn num(value: &Value) -> Result<f64, Raised> {
    number(value).ok_or_else(|| Raised::new("TypeError"))
}

/// `value + 1`.
fn plus_one(value: &Value) -> Result<Value, Raised> {
    crate::state::py::plus_one(value).map_err(|error| raised(&error))
}

/// `int(value)` of a time.
fn int_of(value: &Value) -> Result<Value, Raised> {
    match value {
        Value::Int(_) => Ok(value.clone()),
        Value::Bool(flag) => Ok(Value::from(i64::from(*flag))),
        Value::Float(x) if x.is_finite() => Ok(Value::from(x.trunc() as i64)),
        Value::Float(x) if x.is_nan() => Err(Raised::new("ValueError")),
        Value::Float(_) => Err(Raised::new("OverflowError")),
        _ => Err(Raised::new("TypeError")),
    }
}

/// `blank(bucket, minutes)`: a family nothing has been counted of yet.
pub fn blank(bucket: &Value, minutes: &Value) -> Row {
    let mut row = Map::new();
    for (name, value) in [
        ("bucket", bucket.clone()),
        ("minutes", minutes.clone()),
        ("open_reset_at", Value::Null),
        ("open_full", Value::Bool(false)),
        ("last_closed_at", Value::Null),
        ("resets", Value::from(0)),
        ("hits", Value::from(0)),
        ("seen_at", Value::Null),
        ("misses", Value::from(0)),
    ] {
        row.insert(key(name), value);
    }
    row
}

/// `by_time(row, now)`: step 1 alone, which needs no reading - (row, whether it reset).
pub fn by_time(row: &Row, now: &Value) -> Result<(Row, bool), Raised> {
    let opened = get(row, "open_reset_at");
    if !matches!(opened, Value::Null) && num(now)? >= num(opened)? + CLOSE_AFTER as f64 {
        let resets = plus_one(get(row, "resets"))?;
        return Ok((
            with(
                row,
                &[
                    ("resets", resets),
                    ("last_closed_at", opened.clone()),
                    ("open_reset_at", Value::Null),
                    ("open_full", Value::Bool(false)),
                ],
            ),
            true,
        ));
    }
    Ok((row.clone(), false))
}

/// `closed(row, now)`: step 5 - this edition's own credit reset the open window at `now`.
pub fn closed(row: &Row, now: &Value) -> Result<Row, Raised> {
    if matches!(get(row, "open_reset_at"), Value::Null) {
        return Ok(row.clone());
    }
    Ok(with(
        row,
        &[
            ("resets", plus_one(get(row, "resets"))?),
            ("last_closed_at", int_of(now)?),
            ("open_reset_at", Value::Null),
            ("open_full", Value::Bool(false)),
        ],
    ))
}

/// `advance(row, window, now, early=True)`: one successful reading at `now` applied to one family's row - (the row
/// after, the events: "gap", "reset", "opened", "hit", "missing", "gone").
pub fn advance(
    row: &Row,
    window: Option<&Value>,
    now: &Value,
    early: bool,
) -> Result<(Row, Vec<&'static str>), Raised> {
    let mut events = Vec::new();
    let seen = get(row, "seen_at");
    if !matches!(seen, Value::Null) && num(now)? - num(seen)? > num(get(row, "minutes"))? * 60.0 {
        events.push("gap");
    }
    let (mut row, reset) = by_time(row, now)?;
    if reset {
        events.push("reset");
    }
    let Some(window) = window else {
        let misses = plus_one(get(&row, "misses"))?;
        let gone = num(&misses)? >= MISSES as f64;
        row = with(&row, &[("misses", misses)]);
        events.push(if gone { "gone" } else { "missing" });
        return Ok((row, events));
    };
    row = with(
        &row,
        &[("misses", Value::from(0)), ("seen_at", now.clone())],
    );
    let used = super::usage::get_of(window, "used_percent")
        .map_err(|_| Raised::new("TypeError"))?
        .clone();
    let reset_at = field(window, "reset_at").clone();
    let opened = get(&row, "open_reset_at").clone();
    if early
        && !matches!(opened, Value::Null)
        && (matches!(reset_at, Value::Null) || (num(&reset_at)? - num(&opened)?).abs() > TOL as f64)
    {
        row = with(
            &row,
            &[
                ("resets", plus_one(get(&row, "resets"))?),
                ("last_closed_at", int_of(now)?),
                ("open_reset_at", Value::Null),
                ("open_full", Value::Bool(false)),
            ],
        );
        events.push("reset");
    }
    if matches!(get(&row, "open_reset_at"), Value::Null)
        && num(&used)? > 0.0
        && !matches!(reset_at, Value::Null)
        && num(&reset_at)? > num(now)?
    {
        let last = get(&row, "last_closed_at");
        let last = if car_machine::pyval::truthy(last) {
            num(last)?
        } else {
            0.0
        };
        if num(&reset_at)? > last + TOL as f64 {
            row = with(
                &row,
                &[
                    ("open_reset_at", reset_at.clone()),
                    ("open_full", Value::Bool(false)),
                ],
            );
            events.push("opened");
        }
    }
    if !matches!(get(&row, "open_reset_at"), Value::Null)
        && num(&used)? >= 100.0
        && !car_machine::pyval::truthy(get(&row, "open_full"))
    {
        let hits = plus_one(get(&row, "hits"))?;
        row = with(&row, &[("open_full", Value::Bool(true)), ("hits", hits)]);
        events.push("hit");
    }
    Ok((row, events))
}

/// `family_window(windows, family)`: the family's window in a reading's windows - the fullest (the first of equals),
/// should a bucket list one length twice - or None.
pub fn family_window(windows: &Value, family: &Family) -> Result<Option<Value>, Raised> {
    let Value::Array(windows) = windows else {
        return Ok(None);
    };
    let mut best: Option<&Value> = None;
    for window in windows {
        let bucket = super::usage::get_of(window, "bucket")?;
        let minutes = field(window, "window_minutes");
        if !(car_machine::pyval::eq(bucket, &family.0)
            && car_machine::pyval::eq(minutes, &family.1))
        {
            continue;
        }
        best = match best {
            None => Some(window),
            Some(held) => {
                if num(field(window, "used_percent"))? > num(field(held, "used_percent"))? {
                    Some(window)
                } else {
                    Some(held)
                }
            }
        };
    }
    Ok(best.cloned())
}

/// `count(rule, row)`: what a rule counts on its family's row - fills for a credit, resets for a message.
pub fn count(rule: &Row, row: &Row) -> Value {
    if is_word(get(rule, "capability"), CREDIT) {
        get(row, "hits").clone()
    } else {
        get(row, "resets").clone()
    }
}

/// `due(rule, row)`: whether a rule's occasion has come - adopted, and its family's count past its base by its ordinal.
pub fn due(rule: &Row, row: Option<&Row>) -> Result<bool, Raised> {
    if !is_word(get(rule, "state"), "counting") || matches!(get(rule, "base"), Value::Null) {
        return Ok(false);
    }
    let Some(row) = row else {
        return Ok(false);
    };
    Ok(num(&count(rule, row))? >= num(get(rule, "base"))? + num(get(rule, "ordinal"))?)
}

/// A family's key of a row.
pub fn family_of(row: &Row) -> Family {
    (get(row, "bucket").clone(), get(row, "minutes").clone())
}

/// `{family: row}` lookups over the ordered pairs the reference keeps as a dict.
pub fn find<'a>(rows: &'a [(Family, Row)], family: &Family) -> Option<&'a Row> {
    rows.iter()
        .find(|(held, _)| {
            car_machine::pyval::eq(&held.0, &family.0) && car_machine::pyval::eq(&held.1, &family.1)
        })
        .map(|(_, row)| row)
}

/// What `Watch.step` answers: the rows, the events and what this look read itself (`credits.parse`), or None.
pub struct Looked {
    pub rows: Vec<(Family, Row)>,
    pub events: Vec<(Family, Vec<&'static str>)>,
    pub reading: Option<Value>,
}

impl Looked {
    pub fn events_of(&self, family: &Family) -> Vec<&'static str> {
        self.events
            .iter()
            .find(|(held, _)| {
                car_machine::pyval::eq(&held.0, &family.0)
                    && car_machine::pyval::eq(&held.1, &family.1)
            })
            .map(|(_, found)| found.clone())
            .unwrap_or_default()
    }
}

/// This edition's own reading: given the read's params, Codex's reply or a raise.
pub type Reader<'a> = dyn FnMut(&Value) -> Result<Value, Raised> + 'a;

/// What a state call answered: a refusal of the state's own (StateError and its kinds), or any other raise.
pub enum Failed {
    State(Raised),
    Other(Raised),
}

fn failed(error: Error) -> Failed {
    match error {
        Error::State { class, .. } => Failed::State(Raised::new(class)),
        other => Failed::Other(raised(&other)),
    }
}

/// The reset action's own view of the state (`scoped.resets`), as `Watch` and the two codes call it.
#[derive(Clone)]
pub struct Resets {
    pub bound: Bound,
}

fn gone() -> Raised {
    Raised::new("ReferenceError")
}

impl Resets {
    fn call<T>(
        &self,
        act: impl FnOnce(&crate::state::scoped::Scoped<'_>) -> crate::state::Result<T>,
    ) -> Result<T, Failed> {
        match self.bound.with(act) {
            None => Err(Failed::Other(gone())),
            Some(Ok(found)) => Ok(found),
            Some(Err(error)) => Err(failed(error)),
        }
    }

    pub fn on(&self) -> bool {
        self.bound
            .with(|scoped| scoped.handle().is_on())
            .unwrap_or(false)
    }

    pub fn now(&self) -> f64 {
        self.bound
            .with(|scoped| scoped.now())
            .unwrap_or_else(crate::state::session::wall_clock)
    }

    pub fn windows(&self) -> Result<Vec<(Family, Row)>, Failed> {
        self.call(|scoped| scoped.state.windows())
    }

    pub fn reading(&self) -> Result<Row, Failed> {
        self.call(|scoped| scoped.state.reading())
    }

    pub fn reset_rules(
        &self,
        capability: Option<&str>,
        pending: &Value,
    ) -> Result<Vec<Row>, Failed> {
        let capability = capability.map_or(Value::Null, Value::from);
        self.call(|scoped| scoped.state.reset_rules(&capability, pending))
    }

    pub fn reset_rule(&self, rule_id: &Value) -> Result<Option<Row>, Failed> {
        self.call(|scoped| scoped.state.reset_rule(rule_id))
    }

    pub fn credit_spends(&self, since: &Value) -> Result<Vec<Row>, Failed> {
        self.call(|scoped| scoped.state.credit_spends(since))
    }

    pub fn save_windows(&self, rows: Vec<Row>) -> Result<(), Failed> {
        let rows = Value::Array(rows.into_iter().map(Value::Object).collect());
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.save_windows(&rows)
        })
    }

    pub fn set_reading(&self, values: &[(String, Value)]) -> Result<(), Failed> {
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.set_reading(values)
        })
    }

    pub fn change_rule(
        &self,
        rule_id: &Value,
        expect: &Value,
        changes: &[(&str, Value)],
    ) -> Result<bool, Failed> {
        let changes: Vec<(String, Value)> = changes
            .iter()
            .map(|(name, value)| ((*name).to_owned(), value.clone()))
            .collect();
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.change_rule(rule_id, expect, &changes)
        })
    }

    pub fn end_rule(&self, rule_id: &Value, state: &str, reason: &str) -> Result<bool, Failed> {
        self.call(|scoped| {
            scoped.handle().resets_own(rule_id)?;
            scoped.state.end_rule(
                rule_id,
                &Value::from(state),
                &Value::from(reason),
                &Value::Null,
            )
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_credit_spend(
        &self,
        rule_id: &Value,
        bucket: &Value,
        minutes: &Value,
        occasion: &Value,
        key: &str,
    ) -> Result<Option<i64>, Failed> {
        let key = Value::from(key);
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped
                .state
                .add_credit_spend(rule_id, bucket, minutes, occasion, &key, &Value::Null)
        })
    }

    pub fn finish_credit_spend(&self, spend_id: &Value, outcome: &str) -> Result<bool, Failed> {
        let outcome = Value::from(outcome);
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped
                .state
                .finish_credit_spend(spend_id, &outcome, &Value::Null)
        })
    }

    pub fn retry_credit_spend(&self, spend_id: &Value) -> Result<bool, Failed> {
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.retry_credit_spend(spend_id)
        })
    }

    pub fn drop_credit_spend(&self, spend_id: &Value) -> Result<bool, Failed> {
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.drop_credit_spend(spend_id)
        })
    }

    pub fn carry_message(&self, rule_id: &Value) -> Result<bool, Failed> {
        self.call(|scoped| {
            scoped.handle().resets_writing()?;
            scoped.state.carry_message(rule_id, &Value::Null)
        })
    }

    pub fn carried_message(&self, rule_id: &Value, started: bool) -> Result<bool, Failed> {
        self.call(|scoped| {
            scoped
                .handle()
                .resets_carried(rule_id, &Value::Bool(started))
        })
    }

    pub fn message_expired(&self, rule_id: &Value) -> Result<bool, Failed> {
        self.call(|scoped| scoped.handle().resets_expired(rule_id))
    }
}

impl Failed {
    pub fn raised(self) -> Raised {
        match self {
            Failed::State(raised) | Failed::Other(raised) => raised,
        }
    }
}

/// `machine.WAITING`: the states a record waits in.
pub fn waiting_states() -> &'static [&'static str] {
    car_machine::vocab_gen::domain_states::WAITING
}

/// `Watch(state, clock, reader=, early=, light=, keep_credits=)`: the runner.
pub struct Watch<'a> {
    pub resets: &'a Resets,
    pub reader: Option<&'a mut Reader<'a>>,
    pub early: bool,
    pub light: bool,
    pub keep_credits: bool,
}

/// `_signal(view, reading)`: the newest usage-limit record core noticed since this edition last looked, or None.
pub fn signal(
    view: Option<&dyn car_policy::plug::View>,
    reading: &Row,
) -> Result<Option<Value>, Raised> {
    let Some(view) = view else {
        return Ok(None);
    };
    let Ok(waiting) = view.records_in(waiting_states()) else {
        return Ok(None);
    };
    let mut newest: Option<Value> = None;
    for row in &waiting {
        let detected = super::usage::get_of(row, "detected_at")?;
        if !is_word(field(row, "category"), "usage_limit") || matches!(detected, Value::Null) {
            continue;
        }
        newest = match newest {
            None => Some(detected.clone()),
            Some(held) => Some(
                if car_machine::pyval::greater(detected, &held)
                    .map_err(|_| Raised::new("TypeError"))?
                {
                    detected.clone()
                } else {
                    held
                },
            ),
        };
    }
    let since = get(reading, "signal_at");
    Ok(match newest {
        Some(newest)
            if matches!(since, Value::Null)
                || car_machine::pyval::greater(&newest, since)
                    .map_err(|_| Raised::new("TypeError"))? =>
        {
            Some(newest)
        }
        _ => None,
    })
}

impl Watch<'_> {
    /// `rows(rules)`: `{family: row}` for every family a pending rule names, as counted so far.
    pub fn rows(&self, rules: &[Row]) -> Result<Vec<(Family, Row)>, Raised> {
        let stored = self.resets.windows().map_err(Failed::raised)?;
        let mut rows: Vec<(Family, Row)> = Vec::new();
        for rule in rules {
            let family = (get(rule, "bucket").clone(), get(rule, "minutes").clone());
            if find(&rows, &family).is_some() {
                continue;
            }
            let row = find(&stored, &family)
                .filter(|row| !row.is_empty())
                .cloned()
                .unwrap_or_else(|| blank(&family.0, &family.1));
            rows.push((family, row));
        }
        Ok(rows)
    }

    /// `by_time()`: step 1 for every family a pending rule names, with no reading - what P2 asks first.
    pub fn by_time(&self) -> Result<Vec<(Family, Row)>, Raised> {
        let rules = self
            .resets
            .reset_rules(None, &Value::Bool(true))
            .map_err(Failed::raised)?;
        let now = Value::from(self.resets.now());
        let mut rows = Vec::new();
        for (family, row) in self.rows(&rules)? {
            rows.push((family, by_time(&row, &now)?.0));
        }
        self.resets
            .save_windows(rows.iter().map(|(_, row)| row.clone()).collect())
            .map_err(Failed::raised)?;
        Ok(rows)
    }

    /// `wanted(rules, rows, reading, view, now)`: whether this edition's own reading is due now.
    pub fn wanted(
        &self,
        rules: &[Row],
        rows: &[(Family, Row)],
        reading: &Row,
        view: Option<&dyn car_policy::plug::View>,
        now: f64,
    ) -> Result<bool, Raised> {
        let asked = get(reading, "asked_at");
        if !matches!(asked, Value::Null) && (0.0..READ_SPACING).contains(&(now - num(asked)?)) {
            return Ok(false);
        }
        if rules.iter().any(|rule| {
            is_word(get(rule, "state"), "counting")
                && matches!(get(rule, "adopted_at"), Value::Null)
        }) {
            return Ok(true);
        }
        for (_, row) in rows {
            let opened = get(row, "open_reset_at");
            let seen = get(row, "seen_at");
            let seen = if car_machine::pyval::truthy(seen) {
                num(seen)?
            } else {
                0.0
            };
            if !matches!(opened, Value::Null) {
                let close = num(opened)? + CLOSE_AFTER as f64;
                if now >= close && seen < close {
                    return Ok(true);
                }
            }
            let last = get(row, "last_closed_at");
            if !matches!(last, Value::Null) && seen < num(last)? + CLOSE_AFTER as f64 {
                return Ok(true);
            }
        }
        if signal(view, reading)?.is_some() {
            return Ok(true);
        }
        let read = get(reading, "read_at");
        Ok(matches!(read, Value::Null) || now - num(read)? >= POLL)
    }

    /// `read(params)`: this edition's own reading - Codex's reply parsed, or None for one that failed.
    pub fn read(&mut self, params: &Value) -> Option<Value> {
        let reader = self.reader.as_mut()?;
        let reply = reader(params).ok()?;
        let parsed = credits::parse(&reply).ok()?;
        if matches!(field(&parsed, "windows"), Value::Null) {
            return None;
        }
        Some(parsed)
    }

    fn apply(
        &self,
        rows: &mut [(Family, Row)],
        events: &mut [(Family, Vec<&'static str>)],
        windows: &Value,
        at: &Value,
    ) -> Result<(), Raised> {
        for (index, (family, row)) in rows.iter_mut().enumerate() {
            let window = family_window(windows, family)?;
            let (after, found) = advance(row, window.as_ref(), at, self.early)?;
            *row = after;
            events[index]
                .1
                .extend(found.into_iter().filter(|event| *event != "missing"));
        }
        Ok(())
    }

    /// `step(view=None, now=None, fresh=False)`: one look - the families kept, step 1 by time, core's free reading
    /// applied, this edition's own taken where it is due (or `fresh` asks one, the spacing apart) and applied, rules
    /// adopted where this look read usage itself, held over a gap or a window gone.
    pub fn step(
        &mut self,
        view: Option<&dyn car_policy::plug::View>,
        fresh: bool,
    ) -> Result<Looked, Raised> {
        let now_f = self.resets.now();
        let now = Value::from(now_f);
        let rules = self
            .resets
            .reset_rules(None, &Value::Bool(true))
            .map_err(Failed::raised)?;
        if rules.is_empty() {
            self.resets
                .save_windows(Vec::new())
                .map_err(Failed::raised)?;
            return Ok(Looked {
                rows: Vec::new(),
                events: Vec::new(),
                reading: None,
            });
        }
        let mut rows = self.rows(&rules)?;
        let mut events: Vec<(Family, Vec<&'static str>)> = rows
            .iter()
            .map(|(family, _)| (family.clone(), Vec::new()))
            .collect();
        for (index, (_, row)) in rows.iter_mut().enumerate() {
            let (after, reset) = by_time(row, &now)?;
            *row = after;
            if reset {
                events[index].1.push("reset");
            }
        }
        let reading = self.resets.reading().map_err(Failed::raised)?;
        let core = view.map_or(Value::Null, |view| view.last_usage());
        if let Value::Array(pair) = &core
            && pair.len() == 2
            && matches!(pair[0], Value::Int(_) | Value::Float(_) | Value::Bool(_))
        {
            let at = num(&pair[0])?;
            let applied = get(&reading, "applied_at");
            if (matches!(applied, Value::Null) || at > num(applied)?) && at <= now_f {
                self.apply(&mut rows, &mut events, &pair[1], &pair[0])?;
                self.resets
                    .set_reading(&[("applied_at".to_owned(), pair[0].clone())])
                    .map_err(Failed::raised)?;
            }
        }
        let mut own = None;
        let found_signal = signal(view, &reading)?;
        let asked = get(&reading, "asked_at");
        let spaced =
            !matches!(asked, Value::Null) && (0.0..READ_SPACING).contains(&(now_f - num(asked)?));
        if self.wanted(&rules, &rows, &reading, view, now_f)? || (fresh && !spaced) {
            let params = if self.light && !fresh {
                credits::light()
            } else {
                credits::detailed()
            };
            own = self.read(&params);
            let mut written: Vec<(String, Value)> = vec![("asked_at".to_owned(), now.clone())];
            if let Some(found) = found_signal {
                written.push(("signal_at".to_owned(), found));
            }
            if let Some(reading) = &own {
                self.apply(&mut rows, &mut events, field(reading, "windows"), &now)?;
                written.push(("read_at".to_owned(), now.clone()));
                written.push(("applied_at".to_owned(), now.clone()));
                if self.keep_credits && !matches!(field(reading, "credits"), Value::Null) {
                    written.push(("credits".to_owned(), field(reading, "credits").clone()));
                    let known = car_machine::pyval::truthy(field(reading, "expiry_known"));
                    written.push(("expiry_known".to_owned(), Value::from(i64::from(known))));
                    written.push((
                        "nearest_expiry".to_owned(),
                        field(reading, "nearest_expiry").clone(),
                    ));
                }
            }
            self.resets.set_reading(&written).map_err(Failed::raised)?;
        }
        self.resets
            .save_windows(rows.iter().map(|(_, row)| row.clone()).collect())
            .map_err(Failed::raised)?;
        self.rules(&rules, &rows, &events, own.is_some(), &now)?;
        Ok(Looked {
            rows,
            events,
            reading: own,
        })
    }

    /// `_rules(...)`: rules adopted on this look's own reading, and held where their family had a gap or is gone.
    fn rules(
        &self,
        rules: &[Row],
        rows: &[(Family, Row)],
        events: &[(Family, Vec<&'static str>)],
        adopt: bool,
        now: &Value,
    ) -> Result<(), Raised> {
        for rule in rules {
            let family = (get(rule, "bucket").clone(), get(rule, "minutes").clone());
            let row = find(rows, &family);
            let seen: Vec<&'static str> = events
                .iter()
                .find(|(held, _)| {
                    car_machine::pyval::eq(&held.0, &family.0)
                        && car_machine::pyval::eq(&held.1, &family.1)
                })
                .map(|(_, found)| found.clone())
                .unwrap_or_default();
            let state = get(rule, "state");
            let Some(row) = row else { continue };
            if !(is_word(state, "counting") || is_word(state, "ready")) {
                continue;
            }
            let held = if seen.contains(&"gone") {
                Some("window_gone")
            } else if seen.contains(&"gap") {
                Some("count_gap")
            } else {
                None
            };
            let rule_id = get(rule, "rule_id");
            let outcome = if let Some(reason) = held.filter(|_| is_word(state, "counting")) {
                let counted = if matches!(get(rule, "base"), Value::Null) {
                    0.0
                } else {
                    num(&count(rule, row))? - num(get(rule, "base"))?
                };
                let ordinal = num(get(rule, "ordinal"))? - counted.max(0.0);
                let ordinal = if ordinal >= 1.0 { ordinal } else { 1.0 };
                let ordinal = if ordinal.fract() == 0.0 && ordinal.abs() < 9.0e15 {
                    Value::from(ordinal as i64)
                } else {
                    Value::Float(ordinal)
                };
                self.resets.change_rule(
                    rule_id,
                    &Value::from("counting"),
                    &[
                        ("state", Value::from("held")),
                        ("reason", Value::from(reason)),
                        ("ordinal", ordinal),
                        ("base", Value::Null),
                        ("adopted_at", Value::Null),
                    ],
                )
            } else if adopt
                && is_word(state, "counting")
                && matches!(get(rule, "adopted_at"), Value::Null)
            {
                self.resets.change_rule(
                    rule_id,
                    &Value::from("counting"),
                    &[("base", count(rule, row)), ("adopted_at", now.clone())],
                )
            } else {
                continue;
            };
            match outcome {
                Ok(_) | Err(Failed::State(_)) => {}
                Err(Failed::Other(raised)) => return Err(raised),
            }
        }
        Ok(())
    }

    /// `own_reset(family, now)`: step 5, written - this edition's credit reset the family's open window.
    pub fn own_reset(&self, family: &Family, now: &Value) -> Result<(), Raised> {
        let stored = self.resets.windows().map_err(Failed::raised)?;
        if find(&stored, family).is_none() {
            return Ok(());
        }
        let again = self.resets.windows().map_err(Failed::raised)?;
        let mut rows = Vec::new();
        for (key, row) in &again {
            if car_machine::pyval::eq(&key.0, &family.0)
                && car_machine::pyval::eq(&key.1, &family.1)
            {
                rows.push(closed(row, now)?);
            } else {
                rows.push(row.clone());
            }
        }
        self.resets.save_windows(rows).map_err(Failed::raised)
    }
}

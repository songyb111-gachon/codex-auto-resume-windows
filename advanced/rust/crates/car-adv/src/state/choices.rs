//! What the capabilities that take failures up keep (`state/choices.py`): choices, rules, admissions and samples.
//!
//! Choices and rules are written only by a person in the Dashboard, against the generation the page read, and each
//! write moves the generation like any move. Admissions and samples are the runtime's. A capability's own code reads
//! its own through [`super::scoped::Scoped`].

use car_machine::json::{Str, Value};
use car_policy::classify::failures;
use car_policy::classify::vocab_gen::failures as failure_words;
use car_policy::plug::vocab_gen::domain_plug::{FAILURE_FORMS, TAKE_UP};
use rusqlite::Connection;

use super::ask::{DefinitionAsked, RegistryAsked, takes};
use super::errors::{Error, Result};
use super::journal::{day_number, prune, prune_every};
use super::py;
use super::schema::{WINDOW_CHOICES, WINDOW_FOLLOWERS};
use super::session::AdvancedState;
use super::sql::{self, Row, float, int, py_eq, string};
use crate::vocabulary::{Actor, JournalCode, OptionKey, Refusal};

pub const RULES_LIMIT: usize = 10;
pub const STATUS_RANGE: (i64, i64) = (100, 599);
pub const RECENT_DAYS: i64 = 30;
pub const DAY: f64 = 86400.0;
/// A sample's columns for what the turn left (`ITEM_COLUMNS`), in that order.
pub const ITEM_COLUMNS: &[(&str, &str)] = &[
    ("agentMessage", "items_agent"),
    ("commandExecution", "items_command"),
    ("fileChange", "items_file"),
    ("mcpToolCall", "items_tool"),
    ("userMessage", "items_user"),
    ("other", "items_other"),
];

/// `STAMPS`: the times a capability's own code keeps in `options` beside its choices.
pub fn stamps(capability: &str) -> &'static [&'static str] {
    match capability {
        "idle_update_check" => {
            const LIST: &[&str] = &[
                OptionKey::LastCheck.as_str(),
                OptionKey::OfferedVersion.as_str(),
                OptionKey::OfferedAt.as_str(),
            ];
            LIST
        }
        "usage_analytics" => {
            const LIST: &[&str] = &[OptionKey::LastIngest.as_str()];
            LIST
        }
        "early_reset" => {
            const LIST: &[&str] = &[
                OptionKey::CheckedAt.as_str(),
                OptionKey::AvailableAt.as_str(),
                OptionKey::LiftedAt.as_str(),
                OptionKey::CheckAsked.as_str(),
                OptionKey::FoundAt.as_str(),
            ];
            LIST
        }
        "window_anchor" => {
            const LIST: &[&str] = &[
                OptionKey::AnchorStartedAt.as_str(),
                OptionKey::AnchorFixedAt.as_str(),
                OptionKey::AnchorSeenReset.as_str(),
                OptionKey::AnchorSlotDone.as_str(),
                OptionKey::AnchorResetDone.as_str(),
                OptionKey::AnchorInputTokens.as_str(),
                OptionKey::AnchorOutputTokens.as_str(),
                OptionKey::AnchorAccountAt.as_str(),
                OptionKey::AnchorRetryUntil.as_str(),
                OptionKey::AnchorStoppedAt.as_str(),
                OptionKey::AnchorNextLook.as_str(),
            ];
            LIST
        }
        "account_switch" => {
            const LIST: &[&str] = &[OptionKey::AccountChangedAt.as_str()];
            LIST
        }
        "account_auto_switch" => {
            const LIST: &[&str] = &[
                OptionKey::AutoSwitchedAt.as_str(),
                OptionKey::AutoSwitchDay.as_str(),
                OptionKey::AutoSwitchCount.as_str(),
            ];
            LIST
        }
        "fleet_view" => {
            const LIST: &[&str] = &[
                OptionKey::LastFleetWrite.as_str(),
                OptionKey::FleetWaiting.as_str(),
                OptionKey::FleetWroteAt.as_str(),
            ];
            LIST
        }
        "local_api" => {
            const LIST: &[&str] = &[
                OptionKey::ApiBoundAt.as_str(),
                OptionKey::ApiTakenAt.as_str(),
                OptionKey::ApiLan1.as_str(),
                OptionKey::ApiLan2.as_str(),
                OptionKey::ApiLan3.as_str(),
                OptionKey::ApiLan4.as_str(),
            ];
            LIST
        }
        _ => {
            const LIST: &[&str] = &[];
            LIST
        }
    }
}

/// `str(key) in STAMPS.get(capability, ())`.
fn is_stamp(capability: &Value, key: &Value) -> bool {
    let Some(capability) = py::text(capability) else {
        return false;
    };
    let key = key_text(key);
    stamps(capability).iter().any(|stamp| *stamp == key)
}

/// `str(key)`.
fn key_text(key: &Value) -> String {
    py::py_str(key)
}

/// `CARRIED`: the choices whose missing row is not their default.
fn carried(capability: &Value, key: &str) -> bool {
    py::text(capability).is_some_and(|capability| WINDOW_FOLLOWERS.contains(&capability))
        && WINDOW_CHOICES.contains(&key)
}

fn status(value: &Value) -> bool {
    py::small(value).is_some_and(|value| (STATUS_RANGE.0..=STATUS_RANGE.1).contains(&value))
}

/// `_overlaps(one, other)` of two status ranges, (None, None) for every status.
fn overlaps(one: (&Value, &Value), other: (&Value, &Value)) -> Result<bool> {
    if matches!(one.0, Value::Null) || matches!(other.0, Value::Null) {
        return Ok(true);
    }
    let less_or_equal = |a: &Value, b: &Value| -> Result<bool> {
        car_machine::pyval::less_or_equal(a, b)
            .map_err(|class| Error::python(class, "'<=' not supported"))
    };
    Ok(less_or_equal(one.0, other.1)? && less_or_equal(other.0, one.1)?)
}

/// `TAG_SHAPE.fullmatch(tag)` of a value.
fn tag_shaped(tag: &Value) -> bool {
    py::text(tag).is_some_and(failures::tag_shape)
}

/// `tag in failures.CODES`.
fn known_code(tag: &Value) -> bool {
    py::text(tag).is_some_and(|tag| failures::CODES.iter().any(|(code, _)| *code == tag))
}

/// `tag_problem(tag)`: why `tag` may not be a rule's code, or None.
pub fn tag_problem(tag: &Value) -> Option<&'static str> {
    if !tag_shaped(tag) {
        return Some(Refusal::RuleShape.as_str());
    }
    if known_code(tag) {
        return Some(Refusal::RuleKnown.as_str());
    }
    if failures::decision_tag(tag) {
        return Some(Refusal::RuleDecision.as_str());
    }
    None
}

/// A sample's (tag, status, form).
type Shape = (Value, Value, Value);

/// `aggregated(samples, day=DAY)`: one entry for each code, status number and form, most seen first.
pub fn aggregated(samples: &[Row], day: f64) -> Result<Vec<Row>> {
    let mut found: Vec<(Shape, (i64, Value))> = Vec::new();
    for sample in samples {
        let key = (
            sample.get("tag").cloned().unwrap_or(Value::Null),
            sample.get("status").cloned().unwrap_or(Value::Null),
            sample.get("form").cloned().unwrap_or(Value::Null),
        );
        let at = sample.get("at").cloned().unwrap_or(Value::Null);
        let position = found.iter().position(|(each, _)| {
            py_eq(&each.0, &key.0) && py_eq(&each.1, &key.1) && py_eq(&each.2, &key.2)
        });
        let (count, last) = position.map_or((0, Value::Null), |index| found[index].1.clone());
        let later = matches!(last, Value::Null)
            || (!matches!(at, Value::Null)
                && car_machine::pyval::greater(&at, &last)
                    .map_err(|class| Error::python(class, "'>'"))?);
        let entry = (count + 1, if later { at } else { last });
        match position {
            Some(index) => found[index].1 = entry,
            None => found.push((key, entry)),
        }
    }
    let mut shown: Vec<Row> = Vec::new();
    for ((tag, status, form), (count, last)) in found {
        let mut entry = Row::new();
        entry.insert(sql::key("tag"), tag);
        entry.insert(sql::key("status"), status);
        entry.insert(sql::key("form"), form);
        entry.insert(sql::key("count"), int(count));
        let last = match last {
            Value::Null => Value::Null,
            other => {
                let at = py::float_of(&other)?;
                let whole = py::floordiv(at, day) as i64;
                string(&super::journal::utc_day((whole as f64) * day))
            }
        };
        entry.insert(sql::key("last"), last);
        shown.push(entry);
    }
    let sort_key = |entry: &Row| {
        let tag = py::text(sql::get(entry, "tag")).unwrap_or("").to_string();
        let status = py::small(sql::get(entry, "status")).unwrap_or(0);
        let form = py::text(sql::get(entry, "form")).unwrap_or("").to_string();
        let count = py::small(sql::get(entry, "count")).unwrap_or(0);
        (-count, tag, status, form)
    };
    shown.sort_by_key(sort_key);
    Ok(shown)
}

/// `rule_problem(tag, status_from, status_to, category, rules)`: why a rule may not be added, or None.
pub fn rule_problem(
    tag: &Value,
    status_from: &Value,
    status_to: &Value,
    category: &Value,
    rules: &[Row],
) -> Result<Option<&'static str>> {
    if let Some(problem) = tag_problem(tag) {
        return Ok(Some(problem));
    }
    let from_none = matches!(status_from, Value::Null);
    let to_none = matches!(status_to, Value::Null);
    if from_none != to_none
        || (!from_none
            && !(status(status_from)
                && status(status_to)
                && py::small(status_from) <= py::small(status_to)))
    {
        return Ok(Some(Refusal::RuleRange.as_str()));
    }
    if matches!(category, Value::Array(_) | Value::Object(_)) {
        return Err(Error::type_error("unhashable type"));
    }
    if !py::is_word(category, failure_words::TRANSIENT) {
        return Ok(Some(Refusal::InvalidRequest.as_str()));
    }
    if rules.len() >= RULES_LIMIT {
        return Ok(Some(Refusal::RulesFull.as_str()));
    }
    for rule in rules {
        if py_eq(sql::get(rule, "tag"), tag)
            && overlaps(
                (sql::get(rule, "status_from"), sql::get(rule, "status_to")),
                (status_from, status_to),
            )?
        {
            return Ok(Some(Refusal::RuleOverlap.as_str()));
        }
    }
    Ok(None)
}

/// `_shape(shape)`: a failure's shape as an admission row keeps it: (tag, status, form, message).
fn shape_of(shape: &Value) -> Result<(Value, Value, Value, Value)> {
    let map = match shape {
        Value::Null => return Ok((Value::Null, Value::Null, Value::Null, Value::Null)),
        Value::Object(map) => map,
        _ => return Err(Error::state("invalid shape")),
    };
    let field = |name: &str| map.get(name).cloned().unwrap_or(Value::Null);
    let (tag, status_value, form, message) = (
        field("code"),
        field("status"),
        field("form"),
        field("has_message"),
    );
    if !matches!(tag, Value::Null) && !tag_shaped(&tag) {
        return Err(Error::state("invalid shape"));
    }
    if !matches!(status_value, Value::Null) && !status(&status_value) {
        return Err(Error::state("invalid shape"));
    }
    let form = py::closed(&form, FAILURE_FORMS, "form")?;
    Ok((
        tag,
        status_value,
        string(form),
        int(i64::from(matches!(message, Value::Bool(true)))),
    ))
}

/// `_sample_row(sample, now)`: one sample's columns, every one checked, `at` rounded down to the minute.
fn sample_row(sample: &Value, now: f64) -> Result<Vec<Value>> {
    let Value::Object(map) = sample else {
        return Err(Error::state("invalid sample"));
    };
    let (tag, status_value, form, message) = shape_of(sample)?;
    let counts = match map.get("items") {
        Some(Value::Object(counts)) => Some(counts),
        _ => None,
    };
    let mut items = Vec::new();
    for (kind, _) in ITEM_COLUMNS {
        let value = counts
            .and_then(|counts| counts.get(*kind))
            .cloned()
            .unwrap_or(Value::Null);
        let kept = match &value {
            Value::Int(number) if !number.to_string().starts_with('-') => value.clone(),
            _ => Value::Null,
        };
        items.push(kept);
    }
    let duration = map.get("duration").cloned().unwrap_or(Value::Null);
    let duration = match &duration {
        Value::Int(_) | Value::Float(_) => {
            let number = py::as_f64(&duration).unwrap_or(f64::NAN);
            if (0.0..86400.0 * 7.0).contains(&number) {
                Value::Float(number)
            } else {
                Value::Null
            }
        }
        _ => Value::Null,
    };
    let mut row = vec![
        float((py::floordiv(now, 60.0) as i64 * 60) as f64),
        tag,
        status_value,
        form,
        message,
    ];
    row.extend(items);
    row.push(duration);
    Ok(row)
}

impl AdvancedState {
    // ------------------------------------------------------------------ options
    /// `options(capability)`: {key: value} for every choice it offers - the stored one where it is one it offers,
    /// its default otherwise.
    pub fn options(&self, capability: &Value) -> Result<Row> {
        let Some(definition) = self.registry.get_value(capability) else {
            return Ok(Row::new());
        };
        if definition.options.is_empty() {
            return Ok(Row::new());
        }
        let mut found = Row::new();
        for option in &definition.options {
            found.insert(Str::new(option.key.as_str()), int(option.default));
        }
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT choice, value FROM options WHERE capability=?",
                std::slice::from_ref(capability),
            ),
        })?;
        for row in rows {
            if let Some(option) = definition.option_of(sql::get(&row, "choice"))
                && takes(option, sql::get(&row, "value"))
            {
                found.insert(
                    Str::new(option.key.as_str()),
                    sql::get(&row, "value").clone(),
                );
            }
        }
        Ok(found)
    }

    /// `stamped(capability, key)`: a time its own code keeps under `key`, or None.
    pub fn stamped(&self, capability: &Value, key: &Value) -> Result<Value> {
        if !is_stamp(capability, key) {
            return Ok(Value::Null);
        }
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                "SELECT value FROM options WHERE capability=? AND choice=?",
                &[capability.clone(), string(&key_text(key))],
            ),
        })?;
        Ok(match row {
            Some(row) if py::is_int(sql::get(&row, "value")) => sql::get(&row, "value").clone(),
            _ => Value::Null,
        })
    }

    /// `stamp(capability, key, value)`: keep `value`, a whole number from 1, as its stamp `key`.
    pub fn stamp(&self, capability: &Value, key: &Value, value: &Value) -> Result<bool> {
        let whole = match value {
            Value::Int(number) => {
                !number.to_string().starts_with('-') && number.as_i64() != Some(0)
            }
            _ => false,
        };
        if !is_stamp(capability, key) || !whole {
            return Ok(false);
        }
        self.writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO options (capability, choice, value) VALUES (?,?,?) \
                 ON CONFLICT (capability, choice) DO UPDATE SET value=excluded.value",
                &[capability.clone(), string(&key_text(key)), value.clone()],
            )?;
            Ok(true)
        })
    }

    /// `unstamp(capability, key)`: its stamp taken away; whether there was one.
    pub fn unstamp(&self, capability: &Value, key: &Value) -> Result<bool> {
        if !is_stamp(capability, key) {
            return Ok(false);
        }
        self.transaction(false, |connection| match connection {
            None => Ok(false),
            Some(connection) => Ok(sql::exec(
                connection,
                "DELETE FROM options WHERE capability=? AND choice=?",
                &[capability.clone(), string(&key_text(key))],
            )? == 1),
        })
    }

    /// `set_option(capability, key, value, generation=..., actor=..., at=None)`: one choice set; the generation
    /// after.
    pub fn set_option(
        &self,
        capability: &Value,
        key: &Value,
        value: &Value,
        generation: &Value,
        actor_word: &Value,
        at: &Value,
    ) -> Result<Value> {
        let option = self
            .registry
            .get_value(capability)
            .and_then(|definition| definition.option_of(key))
            .cloned();
        let Some(option) = option.filter(|option| takes(option, value)) else {
            return Err(Error::refused(Refusal::OptionInvalid.as_str()));
        };
        let actor_word = py::closed(actor_word, Actor::ALL, "actor")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            let current = current_generation(connection, generation)?;
            if py_eq(value, &int(option.default)) && !carried(capability, option.key.as_str()) {
                sql::exec(
                    connection,
                    "DELETE FROM options WHERE capability=? AND choice=?",
                    &[capability.clone(), string(option.key.as_str())],
                )?;
            } else {
                sql::exec(
                    connection,
                    "INSERT INTO options (capability, choice, value) VALUES (?,?,?) \
                     ON CONFLICT (capability, choice) DO UPDATE SET value=excluded.value",
                    &[
                        capability.clone(),
                        string(option.key.as_str()),
                        value.clone(),
                    ],
                )?;
            }
            sql::exec(
                connection,
                "UPDATE meta SET generation = generation + 1",
                &[],
            )?;
            self.note_in(
                connection,
                now,
                &string(JournalCode::OptionChanged.as_str()),
                capability,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            py::plus_one(&current)
        })
    }

    // ------------------------------------------------------------------ wordings
    /// `wordings(capability)`: {key: text} of its own wordings - only the keys it keeps.
    pub fn wordings(&self, capability: &Value) -> Result<Row> {
        let Some(definition) = self.registry.get_value(capability) else {
            return Ok(Row::new());
        };
        if definition.wordings.is_empty() {
            return Ok(Row::new());
        }
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT choice, words FROM wordings WHERE capability=?",
                std::slice::from_ref(capability),
            ),
        })?;
        let mut found = Row::new();
        for row in rows {
            if definition.keeps_wording(sql::get(&row, "choice")) {
                found.insert(
                    Str::new(py::text(sql::get(&row, "choice")).unwrap_or_default()),
                    sql::get(&row, "words").clone(),
                );
            }
        }
        Ok(found)
    }

    /// `set_wording(capability, key, words, generation=..., actor=..., at=None)`: set, or with `words` None taken
    /// away; the generation after.
    pub fn set_wording(
        &self,
        capability: &Value,
        key: &Value,
        words: &Value,
        generation: &Value,
        actor_word: &Value,
        at: &Value,
    ) -> Result<Value> {
        let keeps = self
            .registry
            .get_value(capability)
            .is_some_and(|definition| definition.keeps_wording(key));
        if !keeps || !matches!(words, Value::Null | Value::Str(_)) {
            return Err(Error::refused(Refusal::WordingInvalid.as_str()));
        }
        let actor_word = py::closed(actor_word, Actor::ALL, "actor")?;
        let now = self.now(at)?;
        let key = string(&key_text(key));
        self.writing(|connection| {
            let current = current_generation(connection, generation)?;
            if matches!(words, Value::Null) {
                sql::exec(
                    connection,
                    "DELETE FROM wordings WHERE capability=? AND choice=?",
                    &[capability.clone(), key.clone()],
                )?;
            } else {
                sql::exec(
                    connection,
                    "INSERT INTO wordings (capability, choice, words, changed_at) VALUES (?,?,?,?) \
                     ON CONFLICT (capability, choice) DO UPDATE SET words=excluded.words, \
                     changed_at=excluded.changed_at",
                    &[capability.clone(), key.clone(), words.clone(), float(now)],
                )?;
            }
            sql::exec(
                connection,
                "UPDATE meta SET generation = generation + 1",
                &[],
            )?;
            self.note_in(
                connection,
                now,
                &string(JournalCode::OptionChanged.as_str()),
                capability,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            py::plus_one(&current)
        })
    }

    // ------------------------------------------------------------------ rules
    /// `rules()`: every rule, oldest first, with whether the product has come to know its code since (`known`).
    pub fn rules(&self) -> Result<Vec<Row>> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(connection, "SELECT * FROM rules ORDER BY rule_id", &[]),
        })?;
        Ok(rows
            .into_iter()
            .map(|mut row| {
                let known = known_code(sql::get(&row, "tag"));
                row.insert(sql::key("known"), Value::Bool(known));
                row
            })
            .collect())
    }

    /// `add_rule(tag, status_from, status_to, category, generation=..., actor=..., at=None)`: (its id, the
    /// generation after).
    #[allow(clippy::too_many_arguments)]
    pub fn add_rule(
        &self,
        tag: &Value,
        status_from: &Value,
        status_to: &Value,
        category: &Value,
        generation: &Value,
        actor_word: &Value,
        at: &Value,
    ) -> Result<(i64, Value)> {
        let actor_word = py::closed(actor_word, Actor::ALL, "actor")?;
        let now = self.now(at)?;
        self.writing(|connection| {
            let current = current_generation(connection, generation)?;
            let rules = sql::all(connection, "SELECT * FROM rules", &[])?;
            if let Some(problem) = rule_problem(tag, status_from, status_to, category, &rules)? {
                return Err(Error::refused(problem));
            }
            let rule_id = sql::insert(
                connection,
                "INSERT INTO rules (tag, status_from, status_to, category, created_at) VALUES (?,?,?,?,?)",
                &[tag.clone(), status_from.clone(), status_to.clone(), category.clone(), float(now)],
            )?;
            sql::exec(connection, "UPDATE meta SET generation = generation + 1", &[])?;
            self.note_in(
                connection,
                now,
                &string(JournalCode::RuleAdded.as_str()),
                &Value::Null,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            Ok((rule_id, py::plus_one(&current)?))
        })
    }

    /// `remove_rule(rule_id, generation=..., actor=..., at=None)`: the generation after.
    pub fn remove_rule(
        &self,
        rule_id: &Value,
        generation: &Value,
        actor_word: &Value,
        at: &Value,
    ) -> Result<Value> {
        let actor_word = py::closed(actor_word, Actor::ALL, "actor")?;
        let now = self.now(at)?;
        if !py::is_int(rule_id) {
            return Err(Error::refused(Refusal::UnknownRule.as_str()));
        }
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Err(Error::refused(Refusal::UnknownRule.as_str()));
            };
            let current = current_generation(connection, generation)?;
            if sql::exec(
                connection,
                "DELETE FROM rules WHERE rule_id=?",
                std::slice::from_ref(rule_id),
            )? == 0
            {
                return Err(Error::refused(Refusal::UnknownRule.as_str()));
            }
            sql::exec(
                connection,
                "UPDATE meta SET generation = generation + 1",
                &[],
            )?;
            self.note_in(
                connection,
                now,
                &string(JournalCode::RuleRemoved.as_str()),
                &Value::Null,
                &Value::Null,
                &string(actor_word),
                &Value::Null,
                &Value::Null,
            )?;
            py::plus_one(&current)
        })
    }

    /// `rule_hits(since)`: {rule id: how many failures it took up since `since`}.
    pub fn rule_hits(&self, since: &Value) -> Result<Vec<(Value, Value)>> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::tuples(
                connection,
                "SELECT rule_id, count(*) FROM admissions WHERE rule_id IS NOT NULL AND sampled=1 \
                 AND created_at>=? GROUP BY rule_id",
                std::slice::from_ref(since),
            ),
        })?;
        let mut found = Vec::new();
        for row in rows {
            found.push((row[0].clone(), py::int_of(&row[1])?));
        }
        Ok(found)
    }

    // ------------------------------------------------------------------ admissions
    /// `admission(interruption_id)`: the admission row of one interruption, of a capability this registry holds,
    /// or None.
    pub fn admission(&self, interruption_id: &Value) -> Result<Option<Row>> {
        py::key(interruption_id, "interruption id")?;
        let row = self.read(|connection| match connection {
            None => Ok(None),
            Some(connection) => sql::one(
                connection,
                "SELECT * FROM admissions WHERE interruption_id=?",
                std::slice::from_ref(interruption_id),
            ),
        })?;
        Ok(row
            .filter(|row| {
                self.registry
                    .get_value(sql::get(row, "capability"))
                    .is_some()
                    && py::is_word(sql::get(row, "answer"), TAKE_UP)
            })
            .map(|mut row| {
                let sampled = sql::truthy(sql::get(&row, "sampled"));
                row.insert(sql::key("sampled"), Value::Bool(sampled));
                row
            }))
    }

    /// `admit(interruption_id, capability, answer, rule_id=None, shape=None, at=None)`: that `capability` took
    /// it up with `answer`, upserted; false where there is no file.
    pub fn admit(
        &self,
        interruption_id: &Value,
        capability: &Value,
        answer: &Value,
        rule_id: &Value,
        shape: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(interruption_id, "interruption id")?;
        if self.registry.get_value(capability).is_none() {
            return Err(Error::state("unknown capability"));
        }
        let answer = py::closed(answer, &py::alternatives(), "answer")?;
        if !TAKE_UP.contains(&answer) {
            return Err(Error::state("invalid answer"));
        }
        if !matches!(rule_id, Value::Null) && !py::is_int(rule_id) {
            return Err(Error::state("invalid rule"));
        }
        let (tag, status_value, form, message) = shape_of(shape)?;
        let now = self.now(at)?;
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            let message = if matches!(form, Value::Null) { Value::Null } else { message };
            sql::exec(
                connection,
                "INSERT INTO admissions (interruption_id, capability, answer, rule_id, tag, status, form, has_words, \
                 sampled, created_at) VALUES (?,?,?,?,?,?,?,?,0,?) \
                 ON CONFLICT (interruption_id) DO UPDATE SET capability=excluded.capability, \
                 answer=excluded.answer, rule_id=excluded.rule_id, tag=excluded.tag, status=excluded.status, \
                 form=excluded.form, has_words=excluded.has_words",
                &[
                    interruption_id.clone(),
                    capability.clone(),
                    string(answer),
                    rule_id.clone(),
                    tag,
                    status_value,
                    form,
                    message,
                    float(now),
                ],
            )?;
            Ok(true)
        })
    }

    /// `taken(interruption_id, capability, code=None, sample=None, at=None)`: what it keeps of the first time core
    /// went on with a failure it took up - once an interruption.
    pub fn taken(
        &self,
        interruption_id: &Value,
        capability: &Value,
        code: &Value,
        sample: &Value,
        at: &Value,
    ) -> Result<bool> {
        py::key(interruption_id, "interruption id")?;
        let Some(definition) = self.registry.get_value(capability) else {
            return Err(Error::state("unknown capability"));
        };
        if !matches!(code, Value::Null) && !definition.has_code(code) {
            return Err(Error::state("not its own code"));
        }
        let now = self.now(at)?;
        let row = if !matches!(sample, Value::Null) && definition.samples {
            Some(sample_row(sample, now)?)
        } else {
            None
        };
        let line = definition.code_of(code);
        self.transaction(false, |connection| {
            let Some(connection) = connection else {
                return Ok(false);
            };
            if sql::exec(
                connection,
                "UPDATE admissions SET sampled=1 WHERE interruption_id=? AND capability=? AND sampled=0",
                &[interruption_id.clone(), capability.clone()],
            )? == 0
            {
                return Ok(false);
            }
            if let Some(row) = &row {
                let columns: Vec<&str> = ITEM_COLUMNS.iter().map(|(_, column)| *column).collect();
                let made = sql::insert(
                    connection,
                    &format!(
                        "INSERT INTO samples (at, tag, status, form, has_words, {}, duration) VALUES ({})",
                        columns.join(", "),
                        sql::tight_marks(row.len())
                    ),
                    row,
                )?;
                if prune_every(made) {
                    prune(connection, now)?;
                }
            }
            if !matches!(code, Value::Null) {
                sql::exec(
                    connection,
                    "INSERT INTO sampler (capability, code, day, count) VALUES (?,?,?,1) \
                     ON CONFLICT (capability, code, day) DO UPDATE SET count = count + 1",
                    &[capability.clone(), code.clone(), int(day_number(now))],
                )?;
                self.note_in(
                    connection,
                    now,
                    &py::word_or_null(line.as_deref()),
                    capability,
                    &Value::Null,
                    &Value::Null,
                    &Value::Null,
                    &Value::Null,
                )?;
            }
            Ok(true)
        })
    }

    /// `failure_samples(since)`: the samples kept since `since`, oldest first.
    pub fn failure_samples(&self, since: &Value) -> Result<Vec<Row>> {
        let rows = self.read(|connection| match connection {
            None => Ok(Vec::new()),
            Some(connection) => sql::all(
                connection,
                "SELECT * FROM samples WHERE at>=? ORDER BY sample_id",
                std::slice::from_ref(since),
            ),
        })?;
        Ok(rows
            .into_iter()
            .map(|mut row| {
                row.shift_remove("sample_id");
                row
            })
            .collect())
    }
}

/// `_current_generation(connection, generation)`: the stored generation, or StaleGeneration where `generation` is
/// not exactly it (an `int`).
pub(crate) fn current_generation(connection: &Connection, generation: &Value) -> Result<Value> {
    let current = sql::scalar(connection, "SELECT generation FROM meta", &[])?;
    if !py::is_int(generation) || !py_eq(generation, &current) {
        return Err(Error::stale());
    }
    Ok(current)
}

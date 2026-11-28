//! Seat S7.4b: `measure.py`'s probes of the account and the automatic check - MAL, MALR (the restart through the
//! run's `codex_restart` hand), MPROFILE, MSWAP (the `profile_read` and `account_swap` hands), MAUTO (the
//! `auto_check` hand) - and their helpers (`_account`, `_mal_read`, `_closed`), a child of [`crate::measure`].
//!
//! The account is read only through sessions the run's factory opens; the restart, the profile read and the swap are
//! hands the caller wires (S7.3d's live ones; a diff's fakes). Nothing here signals a process or reads a sign-in.

use car_machine::json::{Map, Value};
use car_machine::pyval;

use super::{Context, Found, Raised, Res, blocked, get, key, observed, text};
use crate::vocabulary::{AutoResult, Measurement, PlanWord, Verdict};

pub const MPROFILE_FIELDS: [&str; 8] = [
    "profile_given",
    "added_by_login",
    "account_read",
    "own_account",
    "usage_read",
    "real_file_unchanged",
    "app_unchanged",
    "real_still_signed_in",
];
pub const MSWAP_FIELDS: [&str; 11] = [
    "profiles_given",
    "app_was_running",
    "swapped",
    "signed_in_as_target",
    "swapped_back",
    "signed_in_as_first",
    "first_usage_read",
    "target_usage_read",
    "other_engine_alive",
    "other_engine_alive_open",
    "looked",
];
pub const STORE_WORDS: [&str; 4] = ["usable", "not_file", "no_file", "unreadable"];
pub const MAUTO_FIELDS: [&str; 10] = [
    "official",
    "engine_accepted",
    "schema_answered",
    "experimental_taken",
    "schema_written",
    "schema_whole",
    "features_answered",
    "options_without_flag",
    "flag_without_options",
    "scratch_home_signed_in",
];

/// `_account(reply)`: (signed in, or None where Codex did not answer as one; its plan word).
fn account(reply: &Value) -> (Option<bool>, Value) {
    let Value::Object(map) = reply else {
        return (None, Value::Null);
    };
    let Some(found) = map.get(&key("account")) else {
        return (None, Value::Null);
    };
    let Value::Object(fields) = found else {
        return (Some(false), Value::Null);
    };
    let plan = match fields.get(&key("planType")) {
        Some(plan) => plan,
        None => fields.get(&key("plan_type")).unwrap_or(&Value::Null),
    };
    let Value::Str(plan) = plan else {
        return (Some(true), Value::Null);
    };
    let lower = car_machine::pytext::py_str(&Value::Str(plan.clone())).to_lowercase();
    let known = PlanWord::ALL.iter().any(|word| word.as_str() == lower);
    (
        Some(true),
        text(if known {
            &lower
        } else {
            PlanWord::Other.as_str()
        }),
    )
}

/// `_mal_read(ctx)`: one account/read on a session of its own, or None where the read could not be made.
fn mal_read(ctx: &mut Context<'_>) -> Res<Option<(Option<bool>, Value)>> {
    let found = ctx.with_session(|_ctx, session| {
        Ok(account(
            &session.call("account/read", Some(Value::Object(Map::new())))?,
        ))
    });
    match found {
        Ok(found) => Ok(Some(found)),
        Err(raised) if raised.is_read_failure() => Ok(None),
        Err(raised) => Err(raised),
    }
}

fn first_read(ctx: &mut Context<'_>) -> Res<(Option<bool>, Value)> {
    ctx.with_session(|_ctx, session| {
        Ok(account(
            &session.call("account/read", Some(Value::Object(Map::new())))?,
        ))
    })
}

/// MAL's and MALR's follow: (signed out seen, signed in again seen, the plan then, reads, failed reads).
fn follow_account(ctx: &mut Context<'_>) -> Res<(bool, bool, Value, i64, i64)> {
    let (mut out, mut back, mut after, mut reads, mut failed) = (false, false, Value::Null, 0, 0);
    let deadline = ctx.world.monotonic() + ctx.timing.mal;
    while ctx.world.monotonic() < deadline {
        let poll = ctx.timing.mal_poll;
        ctx.world.sleep(poll);
        let found = mal_read(ctx)?;
        reads += 1;
        let Some((now, word)) = found else {
            failed += 1;
            continue;
        };
        if now == Some(false) {
            out = true;
        } else if now == Some(true) && out {
            back = true;
            after = word;
            break;
        }
    }
    Ok((out, back, after, reads, failed))
}

fn maybe_bool(found: Option<bool>) -> Value {
    found.map_or(Value::Null, Value::Bool)
}

pub(super) fn mal(ctx: &mut Context<'_>) -> Res<Found> {
    let (present, plan) = first_read(ctx)?;
    if present != Some(true) {
        return blocked(
            "sign in to Codex first, then run mal again",
            observed(vec![
                ("account_read", Value::Bool(present.is_some())),
                ("signed_in_before", Value::Bool(false)),
                ("fresh_session_each_read", Value::Bool(true)),
            ]),
        );
    }
    let (out, back, after, reads, failed) = follow_account(ctx)?;
    blocked(
        "with the app open and signed in, run `codex logout` and then `codex login` with the app's own engine (the codex.exe in the app's bin folder under LOCALAPPDATA, never a codex on PATH) within ten minutes of starting this; the person signs in in the browser only and never with the app's own sign-in buttons; confirm the running app shows the new sign-in without a restart, then set the verdict",
        observed(vec![
            ("account_read", Value::Bool(true)),
            ("signed_in_before", Value::Bool(true)),
            ("plan_before", plan),
            ("signed_out_seen", Value::Bool(out)),
            ("signed_in_again_seen", Value::Bool(back)),
            ("plan_after", after),
            ("fresh_session_each_read", Value::Bool(true)),
            ("reads", Value::from(reads)),
            ("reads_failed", Value::from(failed)),
        ]),
    )
}

/// `for word in value or ()` over the words the reference lists (a text's characters; a number that is true is the
/// reference's TypeError).
fn words_of(value: Option<&Value>) -> Res<Vec<Value>> {
    let Some(value) = value.filter(|value| pyval::truthy(value)) else {
        return Ok(vec![]);
    };
    Ok(match value {
        Value::Array(items) => items.clone(),
        Value::Object(map) => map.keys().map(|name| Value::Str(name.clone())).collect(),
        Value::Str(found) => car_machine::pytext::py_str(&Value::Str(found.clone()))
            .chars()
            .map(|c| text(&c.to_string()))
            .collect(),
        _ => return Err(Raised::Other("TypeError".into())),
    })
}

pub(super) fn malr(ctx: &mut Context<'_>) -> Res<Found> {
    use crate::codex::restart::{OUTCOMES, QUEUED, RECOVERY, TURN_RUNNING, UNKNOWN};
    let (present, plan) = first_read(ctx)?;
    let mut seen = observed(vec![
        ("account_read", Value::Bool(present.is_some())),
        ("signed_in_before", Value::Bool(present == Some(true))),
        ("plan_before", plan),
        ("signed_out_seen", Value::Bool(false)),
        ("signed_in_again_seen", Value::Bool(false)),
        ("plan_after", Value::Null),
        ("fresh_session_each_read", Value::Bool(true)),
        ("reads", Value::from(0i64)),
        ("reads_failed", Value::from(0i64)),
        ("busy_turn_running", Value::Null),
        ("busy_queued", Value::Null),
        ("busy_unknown", Value::Null),
        ("restart_outcome", Value::Null),
        ("codex_ended_by", Value::Null),
        ("signed_in_after_restart", Value::Null),
        ("plan_after_restart", Value::Null),
    ]);
    if present != Some(true) {
        return blocked("sign in to Codex first, then run malr again", seen);
    }
    let (out, back, after, reads, failed) = follow_account(ctx)?;
    for (name, value) in [
        ("reads", Value::from(reads)),
        ("reads_failed", Value::from(failed)),
        ("plan_after", after),
        ("signed_out_seen", Value::Bool(out)),
        ("signed_in_again_seen", Value::Bool(back)),
    ] {
        seen.insert(key(name), value);
    }
    if !back {
        return blocked(
            "run `codex logout` and then `codex login` with the app's own engine within ten minutes of starting malr, and sign in in the browser; then run malr again",
            seen,
        );
    }
    // `ctx._hand("codex_restart", home, read)`: None where there is no hand or it raised.
    let home = ctx.home();
    let mut later: Option<(Option<bool>, Value)> = None;
    let answered = match ctx.seams.restart.take() {
        None => None,
        Some(mut hand) => {
            let mut read = || -> Res<Value> {
                let found = mal_read(ctx)?;
                Ok(match found {
                    None => super::object(vec![("present", Value::Null)]),
                    Some((present, plan)) => {
                        later = Some((present, plan));
                        super::object(vec![("present", maybe_bool(present))])
                    }
                })
            };
            let answer = hand(home.as_deref(), &mut read).ok();
            ctx.seams.restart = Some(hand);
            answer
        }
    };
    let answered = match answered {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let busy: Vec<String> = words_of(get(&answered, "busy"))?
        .iter()
        .filter(|word| pyval::in_tuple(word, &[TURN_RUNNING, QUEUED, UNKNOWN, RECOVERY]))
        .filter_map(|word| super::as_text(Some(word)))
        .collect();
    let outcome = get(&answered, "outcome").cloned().unwrap_or(Value::Null);
    let outcome_word = pyval::text(&outcome)
        .filter(|word| OUTCOMES.contains(word))
        .map(str::to_owned);
    let how = get(&answered, "how")
        .filter(|how| pyval::in_tuple(how, &["closed", "ended"]))
        .cloned()
        .unwrap_or(Value::Null);
    let has = |word: &str| busy.iter().any(|each| each == word);
    let (after_present, after_plan) = match &later {
        Some((present, plan)) => (maybe_bool(*present), plan.clone()),
        None => (Value::Null, Value::Null),
    };
    for (name, value) in [
        ("busy_turn_running", Value::Bool(has(TURN_RUNNING))),
        ("busy_queued", Value::Bool(has(QUEUED))),
        ("busy_unknown", Value::Bool(has(UNKNOWN))),
        (
            "restart_outcome",
            outcome_word.as_deref().map_or(Value::Null, text),
        ),
        ("codex_ended_by", how),
        ("signed_in_after_restart", after_present),
        ("plan_after_restart", after_plan),
    ] {
        seen.insert(key(name), value);
    }
    if !busy.is_empty() {
        return blocked(
            "a turn ran, something was queued in Codex or that could not be read, so Codex was not restarted: let it finish, then run malr again",
            seen,
        );
    }
    let outcome_is = |wanted: &str| pyval::text(&outcome) == Some(wanted);
    if outcome_is("not_ended") || outcome_is("not_started") {
        return Ok((
            Verdict::Fail,
            seen,
            Some(
                if outcome_is("not_ended") {
                    "the product's restart did not end the Codex app"
                } else {
                    "the product's restart ended the Codex app but did not start it again"
                }
                .into(),
            ),
        ));
    }
    if !(outcome_is("restarted") || outcome_is("restarted_signed_out")) {
        return blocked(
            "the Codex app was not running, or could not be told apart, so it was not restarted: open the Codex app, signed in, and run malr again",
            seen,
        );
    }
    blocked(
        "confirm the restarted Codex app shows the new account (Settings > Account) without its own sign-in page, then set the verdict",
        seen,
    )
}

/// `_closed(answered, fields)`.
fn closed(answered: Option<Value>, fields: &[&str]) -> Map {
    let answered = match answered {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let mut found = Map::new();
    for field in fields {
        let value = match get(&answered, field) {
            Some(Value::Bool(value)) => Value::Bool(*value),
            _ => Value::Null,
        };
        found.insert(key(field), value);
    }
    let word = get(&answered, "store_word")
        .filter(|word| pyval::in_tuple(word, &STORE_WORDS))
        .cloned()
        .unwrap_or(Value::Null);
    found.insert(key("store_word"), word);
    found
}

fn home_value(ctx: &Context<'_>) -> Value {
    ctx.home_text().map_or(Value::Null, |home| text(&home))
}

fn field(seen: &Map, name: &str) -> Option<bool> {
    match seen.get(&key(name)) {
        Some(Value::Bool(value)) => Some(*value),
        _ => None,
    }
}

fn store_held(seen: &Map) -> bool {
    !matches!(seen.get(&key("store_word")), None | Some(Value::Null))
        && !matches!(seen.get(&key("store_word")), Some(Value::Str(word)) if word.as_bytes() == b"usable")
}

pub(super) fn mprofile(ctx: &mut Context<'_>) -> Res<Found> {
    let home = home_value(ctx);
    let seen = closed(ctx.hand("profile_read", &[home]), &MPROFILE_FIELDS);
    if store_held(&seen) {
        return blocked(
            "Codex keeps its sign-in outside a file here (cli_auth_credentials_store), so no account can be switched: set it to file or leave it unset, sign in again, then run mprofile again",
            seen,
        );
    }
    if field(&seen, "profile_given") != Some(true) {
        return blocked(
            "no other account of yours was saved: run mprofile again and sign in in the browser with another account of your own when Codex's page opens",
            seen,
        );
    }
    if field(&seen, "app_unchanged").is_none() && field(&seen, "real_file_unchanged") != Some(false)
    {
        return blocked(
            "the Codex app was not running, or its process could not be read, so nothing shows it was left alone: open Codex, then run mprofile again",
            seen,
        );
    }
    if [
        "real_file_unchanged",
        "app_unchanged",
        "real_still_signed_in",
    ]
    .iter()
    .any(|name| field(&seen, name) == Some(false))
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("a read on a saved account changed the real Codex home, the running app or the account signed in".into()),
        ));
    }
    if ["account_read", "own_account", "usage_read"]
        .iter()
        .all(|name| field(&seen, name) == Some(true))
    {
        return Ok((Verdict::Pass, seen, None));
    }
    Ok((
        Verdict::Fail,
        seen,
        Some("the saved account did not answer as itself with its usage on a scratch home".into()),
    ))
}

pub(super) fn mswap(ctx: &mut Context<'_>) -> Res<Found> {
    let home = home_value(ctx);
    let seen = closed(ctx.hand("account_swap", &[home]), &MSWAP_FIELDS);
    if store_held(&seen) {
        return blocked(
            "Codex keeps its sign-in outside a file here, so no account can be switched",
            seen,
        );
    }
    if field(&seen, "profiles_given") != Some(true) {
        return blocked(
            "save a second account of yours first (run mprofile), let no turn run and nothing be queued in Codex, then run mswap again",
            seen,
        );
    }
    if field(&seen, "swapped") != Some(true) {
        return blocked(
            "the switch was not made: a turn ran, something was queued, another Codex engine ran, the app could not be closed or the file could not be put in place; run mswap again once Codex is idle and nothing else of Codex runs",
            seen,
        );
    }
    if field(&seen, "signed_in_as_target") == Some(false)
        || field(&seen, "signed_in_as_first") == Some(false)
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("the app did not come up signed in as the account the switch put in, or the first account's sign-in no longer works after coming back".into()),
        ));
    }
    if field(&seen, "swapped_back") == Some(true) && field(&seen, "first_usage_read") == Some(false)
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("after coming back, the first account's usage could not be read".into()),
        ));
    }
    if field(&seen, "signed_in_as_target") == Some(true)
        && field(&seen, "swapped_back") != Some(true)
    {
        return blocked(
            "the switch back did not happen: Codex is still signed in as the other account; switch back on the Saved accounts card or run mswap again",
            seen,
        );
    }
    if field(&seen, "looked") != Some(true) {
        return blocked(
            "no one said they had looked at the other account before the switch back; confirm only what you saw, or run mswap again and look at Settings > Account after the first restart",
            seen,
        );
    }
    blocked(
        "confirm the Codex app showed the other account, then yours again, each without its own sign-in page, then set the verdict",
        seen,
    )
}

pub(super) fn mauto(ctx: &mut Context<'_>) -> Res<Found> {
    let answered = match ctx.hand("auto_check", &[]) {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let mut seen = Map::new();
    for name in MAUTO_FIELDS {
        let value = match get(&answered, name) {
            Some(Value::Bool(value)) => Value::Bool(*value),
            _ => Value::Null,
        };
        seen.insert(key(name), value);
    }
    seen.insert(
        key("scratch_home_files"),
        match get(&answered, "scratch_home_files") {
            Some(found @ Value::Int(_)) => found.clone(),
            _ => Value::Null,
        },
    );
    // `(answered.get("results") or {}).items()`: something true that is no dict has no `items`.
    let listed = match get(&answered, "results") {
        Some(found) if pyval::truthy(found) => match found {
            Value::Object(map) => map.clone(),
            _ => return Err(Raised::Other("AttributeError".into())),
        },
        _ => Map::new(),
    };
    let mut results: Vec<(Measurement, AutoResult)> = Vec::new();
    for (name, word) in &listed {
        let name = car_machine::pytext::py_str(&Value::Str(name.clone()));
        let Some(measurement) = crate::vocabulary::parse::<Measurement>(&name) else {
            continue;
        };
        // `word in words`: a set asks for a hash.
        pyval::hashable(word).map_err(|class| Raised::Other(class.into()))?;
        let Some(result) = pyval::text(word).and_then(crate::vocabulary::parse::<AutoResult>)
        else {
            continue;
        };
        results.push((measurement, result));
    }
    for (measurement, result) in &results {
        seen.insert(
            key(&format!("result_{}", measurement.as_str())),
            text(result.as_str()),
        );
    }
    let table: crate::autocheck::Results = results.iter().copied().collect();
    let version = match ctx.versions.get(&key("codex_version")) {
        Some(Value::Str(found)) => Some(car_machine::pytext::py_str(&Value::Str(found.clone()))),
        _ => None,
    };
    let measured = crate::measured::table();
    let mut definitions = crate::registry::definitions();
    definitions.extend(crate::registry::waiting().into_iter().map(|(each, _)| each));
    for definition in definitions {
        let mut rests: Vec<Measurement> = definition.measurements.clone();
        rests.extend(definition.narrowed_by.iter().copied());
        let (word, _earlier) =
            crate::autocheck::grade(&rests, version.as_deref(), &measured, &table);
        seen.insert(
            key(&format!("grade_{}", definition.id)),
            text(word.as_str()),
        );
    }
    if field(&seen, "engine_accepted") != Some(true) {
        return blocked(
            "the engine could not be run on a scratch Codex home: check the Codex in force, then run mauto again",
            seen,
        );
    }
    if field(&seen, "experimental_taken") != Some(true)
        || field(&seen, "schema_whole") != Some(true)
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("the schema's command did not answer with the whole schema behind the options the check runs it with, so the check gives no answer on this Codex".into()),
        ));
    }
    if field(&seen, "features_answered") != Some(true) {
        return Ok((
            Verdict::Fail,
            seen,
            Some(
                "the feature list did not answer, so MHK's row has no answer on this Codex".into(),
            ),
        ));
    }
    Ok((Verdict::Pass, seen, None))
}

/// The measurements this module answers.
pub(super) const PORTED: [Measurement; 5] = [
    Measurement::Mal,
    Measurement::Malr,
    Measurement::Mprofile,
    Measurement::Mswap,
    Measurement::Mauto,
];

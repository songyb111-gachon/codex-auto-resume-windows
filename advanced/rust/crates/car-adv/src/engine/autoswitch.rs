//! `engine/autoswitch.py` (seat S7.2b): the watcher's side of account_auto_switch - at a usage limit, switch to another
//! saved account with room.
//!
//! At P8, as an errand, at most every LOOK_EVERY seconds while it stands on: what a kill left in plain text is swept; a
//! switch a crash left unfinished is settled first (`swap::recover`); it may act only when recovery is neither paused
//! nor only observed, Codex keeps its sign-in in a file, a recovery has waited for a usage limit at least SETTLE seconds,
//! nothing runs or is queued in Codex and no other recovery waits (`restart::busy`), no other engine runs and nobody has
//! used this PC for IDLE seconds; one attempt for each set of waiting records and at most PER_DAY switches in 24 hours;
//! the account in use is read on the real home and left out, every other saved account with a chance is read on a
//! scratch home (`swap::read_profile`), and the one with the most room is switched in (`swap::switch`); none with room
//! says so once; a switch that did not finish says so once. After a switch P7 answers EARLY for every record waiting
//! for a usage limit, for EARLY_FOR seconds. A person's own Switch to this account is [`AutoSwitch::put_in`] with
//! `manual`. While off or watched, `tend` settles a switch left unfinished and nothing else.
//!
//! Every seam is the reference's: the store, the session factory, the restart, the account read on the real home,
//! the idle time, the busy rule, the Codex home - and the world of `swap` (its process list, clock and sleep).

use std::path::PathBuf;
use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::plug::{Alternative, Errand, Guards, HookFailed, View};

use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::account::{self, Opener};
use crate::codex::authfile::{self, Fault};
use crate::codex::swap::{self, World};
use crate::profiles::{self, Profiles};
use crate::state::scoped::Scoped;
use crate::vocabulary::OptionKey;

pub const CAPABILITY: &str = "account_auto_switch";
pub const LOOK_EVERY: f64 = 60.0;
pub const SETTLE: f64 = 300.0;
pub const IDLE: f64 = 120.0;
pub const EARLY_FOR: f64 = 900.0;
pub const PER_DAY: usize = 10;
pub const DAY: f64 = 86400.0;
pub const USAGE_LIMIT: &str = "usage_limit";
pub const NOT_FINISHED: [&str; 7] = [
    "not_signed_in",
    "not_put_back",
    "not_started",
    "changed_under",
    "failed",
    "left",
    "engine_alive",
];
pub const MANUAL_SWITCHED: &str = "manual_switched";
pub const MANUAL_NOT_FINISHED: &str = "manual_not_finished";
pub const MANUAL_NOT_DONE: &str = "manual_not_done";
pub const MANUAL_NOTHING: [&str; 4] = ["not_closed", "held", "locked", "not_usable"];
pub const REPEATING: [&str; 3] = ["not_put_back", "locked", "unverified"];
pub const TOLD_KEPT: usize = 8;

fn text(value: &str) -> Value {
    Value::Str(Str::new(value))
}

fn get<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    match value {
        Value::Object(map) => map.get(key),
        _ => None,
    }
}

fn number(value: Option<&Value>) -> bool {
    matches!(
        value,
        Some(Value::Int(_) | Value::Float(_) | Value::Bool(_))
    )
}

fn state_fault(error: crate::state::errors::Error) -> Fault {
    Fault::new("StateError", &format!("{error:?}"))
}

/// What `restart(between)` is: codex/restart.restart's shape.
pub type RestartSeam = Box<
    dyn FnMut(&mut dyn FnMut() -> Result<(), Fault>) -> Result<Option<(Value, Value)>, Fault>
        + Send,
>;

/// The world of `swap` as this code holds it (its own, or a test's).
pub trait Worldly: Send {
    fn world(&self) -> World<'_>;
}

impl Worldly for swap::Live {
    fn world(&self) -> World<'_> {
        swap::Live::world(self)
    }
}

/// The seams of [`AutoSwitch`].
pub struct Seams {
    /// `profiles.Profiles(paths.home)`.
    pub store: Profiles,
    /// `inuse.home(paths)`, or why it cannot be told.
    pub home: Box<dyn Fn() -> Result<PathBuf, Fault> + Send>,
    /// `session_for`: a session on a scratch home.
    pub session_for: Box<dyn Opener + Send>,
    /// `read_real`: the account read on the real home.
    pub read_real: Box<dyn Fn() -> Value + Send>,
    /// `swap`'s world.
    pub world: Box<dyn Worldly>,
    /// What the restart hands ask: the busy rule, the idle time and the restart itself.
    pub hands: Hands,
}

/// The seams `_restart_now` reads.
pub struct Hands {
    /// `restart`: None for codex/restart.restart with the product's own hands.
    pub restart: Option<RestartSeam>,
    /// `idle`: seconds since anybody used this PC (a number, or None).
    pub idle: Box<dyn Fn() -> Value + Send>,
    /// `busy`: codex/restart.busy(paths, usage_waiting_ok=True)'s truth.
    pub busy: Box<dyn Fn() -> Result<bool, Fault> + Send>,
    /// The product's paths, for the live restart.
    pub paths: Paths,
}

/// What a look's settling left told: (word, from, to, put_in, step).
type Told = (String, Value, Value, Value, Value);

struct Inner {
    seams: Seams,
    looked: Option<f64>,
    episode: Option<Vec<Value>>,
    switched_at: Option<f64>,
    notice: Option<Value>,
    others: i64,
    told: Vec<Told>,
}

fn lock(inner: &Mutex<Inner>) -> std::sync::MutexGuard<'_, Inner> {
    inner.lock().unwrap_or_else(PoisonError::into_inner)
}

/// account_auto_switch's code: its P8 errand, its P7 answer and its tend.
pub struct AutoSwitch {
    binding: Option<Arc<Binding>>,
    inner: Arc<Mutex<Inner>>,
}

impl AutoSwitch {
    pub fn new(seams: Seams) -> AutoSwitch {
        AutoSwitch {
            binding: None,
            inner: Arc::new(Mutex::new(Inner {
                seams,
                looked: None,
                episode: None,
                switched_at: None,
                notice: None,
                others: 0,
                told: Vec::new(),
            })),
        }
    }

    /// `notice()`: {"key"} of the last look that found every saved account at its limit, or {"key", "why":
    /// "not_finished"} of a switch that did not finish; or None.
    pub fn notice_view(&self) -> Value {
        lock(&self.inner).notice.clone().unwrap_or(Value::Null)
    }

    /// `look(view, now)` on this capability's own `Scoped`.
    pub fn look(&self, scoped: &Scoped<'_>, view: &dyn View, now: f64) -> Result<(), Fault> {
        look(&mut lock(&self.inner), scoped, view, now)
    }

    /// `settle()`.
    pub fn settle(&self, scoped: &Scoped<'_>) -> Result<(), Fault> {
        settle(&mut lock(&self.inner), scoped)
    }

    /// `put_in(target, now, manual=)`: (the switch's outcome, how it closed the Codex app each time it did).
    pub fn put_in(
        &self,
        target: &Value,
        now: f64,
        manual: bool,
    ) -> Result<(&'static str, Vec<Value>), Fault> {
        put_in(&mut lock(&self.inner), target, now, manual)
    }

    /// `schedule(record, eligible_at)` on this capability's own `Scoped`.
    pub fn schedule_in(&self, scoped: &Scoped<'_>, record: &Value, eligible_at: &Value) -> Spoke {
        schedule(&lock(&self.inner), scoped, record, eligible_at)
    }

    /// The fields a diff compares after a look: the episode, the last switch, the notice, the others counted, what
    /// was told.
    pub fn memory(&self) -> Value {
        let inner = lock(&self.inner);
        let mut found = Map::new();
        found.insert(
            Str::new("episode"),
            inner.episode.as_ref().map_or(Value::Null, |each| {
                let mut sorted = each.clone();
                sorted.sort_by_key(|value| car_machine::pytext::py_str(value));
                Value::Array(sorted)
            }),
        );
        found.insert(
            Str::new("switched_at"),
            inner.switched_at.map_or(Value::Null, Value::Float),
        );
        found.insert(
            Str::new("notice"),
            inner.notice.clone().unwrap_or(Value::Null),
        );
        found.insert(Str::new("others"), Value::from(inner.others));
        found.insert(
            Str::new("told"),
            Value::Array(
                inner
                    .told
                    .iter()
                    .map(|(word, from, to, put_in, step)| {
                        Value::Array(vec![
                            text(word),
                            from.clone(),
                            to.clone(),
                            put_in.clone(),
                            step.clone(),
                        ])
                    })
                    .collect(),
            ),
        );
        found.insert(
            Str::new("looked"),
            inner.looked.map_or(Value::Null, Value::Float),
        );
        Value::Object(found)
    }
}

fn count(scoped: &Scoped<'_>, code: &str) {
    let _ = scoped.count(&text(code));
}

fn busy(inner: &Inner) -> Result<bool, Fault> {
    (inner.seams.hands.busy)()
}

/// `_restart_now(between, away=)`: codex/restart.restart for a switch or a later look's put-back - None where it may
/// not restart now (something runs or is queued, or someone uses this PC), looked at again right before the close.
fn restart_now(
    seams: &mut Hands,
    between: &mut dyn FnMut() -> Result<(), Fault>,
    away: bool,
) -> Result<Option<(Value, Value)>, Fault> {
    if (seams.busy)()? {
        return Ok(None);
    }
    let idle = if away {
        (seams.idle)()
    } else {
        Value::Float(IDLE)
    };
    if !number(Some(&idle)) || pyval::less(&idle, &Value::Float(IDLE)).unwrap_or(true) {
        return Ok(None);
    }
    if let Some(restart) = seams.restart.as_mut() {
        return restart(between);
    }
    let hands = crate::codex::restart::LiveHands::new(&seams.paths);
    let mut adapter = || {
        let _ = between();
    };
    let (outcome, how) = crate::codex::restart::restart(&hands, Some(&mut adapter))?;
    Ok(Some((text(outcome), how.map_or(Value::Null, text))))
}

/// `waiting(view, now)`: core's records that have waited for a usage limit at least SETTLE seconds.
pub fn waiting(view: &dyn View, now: f64) -> Result<Vec<Value>, Fault> {
    let rows = view
        .records_in(car_machine::vocab_gen::domain_states::WAITING)
        .map_err(|failed| Fault::new(failed.0, "a view read failed"))?;
    Ok(rows
        .into_iter()
        .filter(|row| {
            get(row, "category").is_some_and(|category| pyval::is(category, USAGE_LIMIT))
                && !get(row, "hold").is_some_and(pyval::truthy)
                && !get(row, "cancel_requested").is_some_and(pyval::truthy)
                && number(get(row, "detected_at"))
                && pyval::minus(
                    &Value::Float(now),
                    get(row, "detected_at").unwrap_or(&Value::Null),
                )
                .is_ok_and(|waited| waited >= SETTLE)
        })
        .collect())
}

/// `_why_not(view, rows)`.
fn why_not(
    inner: &mut Inner,
    view: &dyn View,
    rows: &[Value],
) -> Result<Option<&'static str>, Fault> {
    let settings = view.settings().unwrap_or(Value::Null);
    if !matches!(settings, Value::Object(_))
        || !matches!(get(&settings, "enabled"), Some(Value::Bool(true)))
        || get(&settings, "observe_only").is_some_and(pyval::truthy)
    {
        return Ok(Some("paused"));
    }
    if rows.is_empty() {
        return Ok(Some("nothing_waits"));
    }
    let home = (inner.seams.home)()?;
    if authfile::usable(&home)? != authfile::USABLE {
        return Ok(Some("not_usable"));
    }
    if busy(inner)? {
        return Ok(Some("busy"));
    }
    let world = inner.seams.world.world();
    let rows_now = (world.inventory)();
    if swap::other_engines(rows_now.as_deref(), true, &(world.own)(), world.system)? {
        return Ok(Some("engine_alive")); // a TUI, IDE or exec-server engine of its own: it waits
    }
    let idle = (inner.seams.hands.idle)();
    if !number(Some(&idle)) || pyval::less(&idle, &Value::Float(IDLE)).unwrap_or(true) {
        return Ok(Some("in_use"));
    }
    Ok(None)
}

/// `_recent(now)`: the switch times within the last DAY seconds, or None where they were kept and cannot be read.
fn recent(inner: &mut Inner, scoped: &Scoped<'_>, now: f64) -> Result<Option<Vec<i64>>, Fault> {
    let kept = match inner.seams.store.attempts() {
        Ok(Value::Array(times)) => Some(times),
        Ok(_) => None,
        Err(error) => {
            let fault = Fault::from(error);
            if fault.is_os() {
                return Ok(None); // kept but unreadable: not "none made" (M4)
            }
            None
        }
    };
    let times: Vec<Value> = match kept {
        Some(times) => times,
        None => {
            // Before v0.6.23 the count was the UTC day's, in two stamps: kept as switches made now.
            let day = Value::from((now / DAY).floor() as i64 + 1);
            let legacy = scoped
                .stamped(&text(OptionKey::AutoSwitchCount.as_str()))
                .map_err(state_fault)?;
            let legacy = if pyval::truthy(&legacy) {
                legacy
            } else {
                Value::from(0)
            };
            let same_day = pyval::eq(
                &scoped
                    .stamped(&text(OptionKey::AutoSwitchDay.as_str()))
                    .map_err(state_fault)?,
                &day,
            );
            let legacy = if same_day { legacy } else { Value::from(0) };
            let legacy = crate::state::py::int_of(&legacy)
                .ok()
                .and_then(|value| crate::state::py::small(&value))
                .ok_or_else(|| Fault::new("ValueError", "int()"))?;
            let made: Vec<Value> = (0..legacy.clamp(0, PER_DAY as i64))
                .map(|_| Value::from(now.trunc() as i64))
                .collect();
            if !made.is_empty() {
                keep(
                    inner,
                    &made
                        .iter()
                        .filter_map(crate::state::py::small)
                        .collect::<Vec<_>>(),
                );
            }
            made
        }
    };
    Ok(Some(
        times
            .iter()
            .filter(|value| {
                pyval::minus(&Value::Float(now), value).is_ok_and(|age| (0.0..DAY).contains(&age))
            })
            .filter_map(crate::state::py::small)
            .collect(),
    ))
}

fn keep(inner: &Inner, times: &[i64]) {
    let _ = inner.seams.store.note_attempts(times);
}

/// `_today(now)`: how many switches in the last DAY seconds - PER_DAY where the times kept cannot be read.
fn today(inner: &mut Inner, scoped: &Scoped<'_>, now: f64) -> Result<usize, Fault> {
    match recent(inner, scoped, now)? {
        None => {
            keep(inner, &vec![now.trunc() as i64; PER_DAY]);
            Ok(PER_DAY)
        }
        Some(found) => Ok(found.len()),
    }
}

/// `_attempted(now)`: one more switch counted toward the ceiling.
fn attempted(inner: &mut Inner, scoped: &Scoped<'_>, now: f64) -> Result<(), Fault> {
    let times = match recent(inner, scoped, now)? {
        None => vec![now.trunc() as i64; PER_DAY],
        Some(mut found) => {
            found.push(now.trunc() as i64);
            let skip = found.len().saturating_sub(PER_DAY);
            found[skip..].to_vec()
        }
    };
    keep(inner, &times);
    Ok(())
}

fn switched(inner: &mut Inner, scoped: &Scoped<'_>, now: f64) -> Result<(), Fault> {
    inner.switched_at = Some(now);
    scoped
        .stamp(
            &text(OptionKey::AutoSwitchedAt.as_str()),
            &Value::from((now.trunc() as i64).max(1)),
        )
        .map_err(state_fault)?;
    Ok(())
}

fn not_finished(inner: &mut Inner, target: &Value) {
    let named = match target {
        Value::Str(found) => found.as_str().unwrap_or_default().to_owned(),
        _ => "unknown".to_owned(),
    };
    let mut notice = Map::new();
    notice.insert(
        Str::new("key"),
        text(&format!("autoswitch:not_finished:{named}")),
    );
    notice.insert(Str::new("why"), text("not_finished"));
    inner.notice = Some(Value::Object(notice));
}

/// `_settled(settled, intent)`: what a look's settling of a switch left came to, in the journal - once for each switch
/// left where it only waits again (REPEATING), every other word as it comes.
fn settled_word(inner: &mut Inner, scoped: &Scoped<'_>, settled: &str, intent: &Value) {
    if REPEATING.contains(&settled) {
        let field = |key: &str| get(intent, key).cloned().unwrap_or(Value::Null);
        let key: Told = (
            settled.to_owned(),
            field("from"),
            field("to"),
            field("put_in"),
            field("step"),
        );
        let same = |each: &Told| {
            each.0 == key.0
                && pyval::eq(&each.1, &key.1)
                && pyval::eq(&each.2, &key.2)
                && pyval::eq(&each.3, &key.3)
                && pyval::eq(&each.4, &key.4)
        };
        if inner.told.iter().any(same) {
            let _ = scoped.sample(&text(settled));
            return;
        }
        inner.told.push(key);
        let skip = inner.told.len().saturating_sub(TOLD_KEPT);
        inner.told.drain(..skip);
    }
    count(scoped, settled);
}

fn intent_of(inner: &Inner) -> Result<Value, Fault> {
    Ok(inner.seams.store.intent()?)
}

/// `swap.recover(paths, store, home, read_real=, restart=_restart_now)`.
fn recover_now(inner: &mut Inner, home: &std::path::Path) -> Result<Option<&'static str>, Fault> {
    let Seams {
        store,
        world,
        read_real,
        hands,
        ..
    } = &mut inner.seams;
    let mut restart =
        |between: &mut dyn FnMut() -> Result<(), Fault>| restart_now(hands, between, true);
    let world = world.world();
    swap::recover(
        &world,
        store,
        home,
        &|| read_real(),
        Some(&mut restart as &mut swap::Restart),
    )
}

/// `look(view, now)`: one look; see the module. What it did is in the journal and the stamps.
fn look(inner: &mut Inner, scoped: &Scoped<'_>, view: &dyn View, now: f64) -> Result<(), Fault> {
    let home = (inner.seams.home)()?;
    let intent = intent_of(inner)?;
    // What a kill or a held file left in plain text goes first.
    let (_removed, failed) = authfile::sweep(
        &inner.seams.store.directory,
        Some(&home),
        crate::state::session::wall_clock(),
        authfile::SCRATCH_STALE,
    );
    if failed > 0 {
        count(scoped, "sweep_failed");
    }
    let settled = recover_now(inner, &home)?;
    match settled {
        Some(word) if word == swap::SWITCHED => {
            switched(inner, scoped, now)?;
            settled_word(inner, scoped, word, &intent);
        }
        Some(word) => {
            settled_word(inner, scoped, word, &intent);
            if NOT_FINISHED.contains(&word) && matches!(intent, Value::Object(_)) {
                let to = get(&intent, "to").cloned().unwrap_or(Value::Null);
                not_finished(inner, &to);
            }
        }
        None => {}
    }
    if !matches!(intent_of(inner)?, Value::Null) {
        return Ok(()); // a switch not settled yet: no other
    }
    let rows = waiting(view, now)?;
    if why_not(inner, view, &rows)?.is_some() {
        return Ok(());
    }
    let mut episode: Vec<Value> = Vec::new();
    for row in &rows {
        let key = get(row, "interruption_id")
            .cloned()
            .ok_or_else(|| Fault::new("KeyError", "interruption_id"))?;
        if !episode.iter().any(|each| pyval::eq(each, &key)) {
            episode.push(key);
        }
    }
    let same = inner.episode.as_ref().is_some_and(|kept| {
        kept.len() == episode.len()
            && kept
                .iter()
                .all(|each| episode.iter().any(|other| pyval::eq(each, other)))
    });
    if same {
        return Ok(()); // one attempt for each set of waiting records
    }
    inner.episode = Some(episode);
    let unread = recent(inner, scoped, now)?.is_none();
    if today(inner, scoped, now)? >= PER_DAY {
        count(scoped, "ceiling");
        if unread {
            not_finished(inner, &text("ceiling")); // M4: no switch, said once in the not-finished words
        }
        return Ok(());
    }
    let target = choose(inner, now)?;
    let Some(target) = target else {
        if inner.others == 0 {
            return Ok(()); // nothing saved but the account in use: nothing to be at a limit
        }
        count(scoped, "all_exhausted");
        let first = rows
            .iter()
            .filter_map(|row| get(row, "detected_at"))
            .cloned()
            .reduce(|low, each| {
                if pyval::less(&each, &low).unwrap_or(false) {
                    each
                } else {
                    low
                }
            })
            .unwrap_or(Value::Null);
        let at = car_machine::pytext::to_float(&first).unwrap_or(0.0).trunc() as i64;
        let mut notice = Map::new();
        notice.insert(Str::new("key"), text(&format!("autoswitch:{at}")));
        inner.notice = Some(Value::Object(notice));
        return Ok(());
    };
    let (outcome, closed) = put_in(inner, &target, now, false)?;
    // A switch that leaves a wait is told once, here: the looks after it only count the day's repeats.
    let left = if REPEATING.contains(&outcome) {
        intent_of(inner)?
    } else {
        Value::Null
    };
    settled_word(inner, scoped, outcome, &left);
    if NOT_FINISHED.contains(&outcome) {
        not_finished(inner, &target);
    }
    if outcome == swap::SWITCHED {
        switched(inner, scoped, now)?; // NOT_STARTED: the app is closed, so P7 releases nothing early
    }
    if outcome == swap::SWITCHED || outcome == swap::NOT_STARTED || !closed.is_empty() {
        attempted(inner, scoped, now)?;
    }
    Ok(())
}

/// `put_in(target, now, manual=)`: the switch itself through this capability's restart hands.
fn put_in(
    inner: &mut Inner,
    target: &Value,
    now: f64,
    manual: bool,
) -> Result<(&'static str, Vec<Value>), Fault> {
    let home = (inner.seams.home)()?;
    let mut closed: Vec<Value> = Vec::new();
    let Seams {
        store,
        world,
        read_real,
        hands,
        ..
    } = &mut inner.seams;
    let mut restart = |between: &mut dyn FnMut() -> Result<(), Fault>| {
        let found = restart_now(hands, between, !manual)?;
        if let Some((_, how)) = &found
            && !matches!(how, Value::Null)
        {
            closed.push(how.clone());
        }
        Ok(found)
    };
    let world = world.world();
    let outcome = swap::switch(
        &world,
        store,
        &home,
        target,
        &mut restart,
        &|| read_real(),
        Some(now),
    )?;
    Ok((outcome, closed))
}

/// `choose(store, now)`: the saved account to switch to - the most room, ties to the least recently used - or None;
/// how many saved accounts other than the one in use there are is kept in `others`.
fn choose(inner: &mut Inner, now: f64) -> Result<Option<Value>, Fault> {
    inner.others = 0;
    let Some(current) = account::identity(&(inner.seams.read_real)())? else {
        return Ok(None); // who is signed in cannot be told: nothing is read or switched
    };
    let mut candidates: Vec<(Value, Value, Value)> = Vec::new();
    for profile_id in inner.seams.store.ids() {
        let id = text(&profile_id);
        let profile = match inner.seams.store.get(&id) {
            Ok(profile) => profile,
            Err(error) => {
                let fault = Fault::from(error);
                if fault.is_profile() {
                    continue;
                }
                return Err(fault);
            }
        };
        let email = match profile.get("email") {
            Some(found) if pyval::truthy(found) => match found {
                Value::Str(email) => {
                    Str::from_code_points(car_policy::classify::text::lower(email))
                        .map_or(Value::Null, Value::Str)
                }
                _ => {
                    return Err(Fault::new(
                        "AttributeError",
                        "object has no attribute 'lower'",
                    ));
                }
            },
            _ => text(""),
        };
        if pyval::eq(&email, &current) {
            seen(&inner.seams.store, &id, now);
            continue;
        }
        inner.others += 1;
        if inner.seams.store.state(&profile, Some(now)) != profiles::READY {
            continue;
        }
        let world = inner.seams.world.world();
        let found = swap::read_profile(
            &world,
            &inner.seams.store,
            &id,
            inner.seams.session_for.as_ref(),
            Some(now),
        )?;
        candidates.push((
            id,
            Value::Object(found),
            profile.get("used_at").cloned().unwrap_or(Value::Null),
        ));
    }
    best(&candidates)
}

/// `(a0, a1) < (b0, b1)` as Python compares tuples.
fn tuple_less(a: &(Value, Value), b: &(Value, Value)) -> Result<bool, Fault> {
    let raised = |class: &'static str| Fault::new(class, "<");
    if !pyval::eq(&a.0, &b.0) {
        return pyval::less(&a.0, &b.0).map_err(raised);
    }
    pyval::less(&a.1, &b.1).map_err(raised)
}

/// `best(candidates)`: of (profile id, a read's found, when it was last switched to), the one a switch picks - its own
/// account with room, the lowest most-used window, ties to the least recently used - or None.
pub fn best(candidates: &[(Value, Value, Value)]) -> Result<Option<Value>, Fault> {
    let mut picked: Option<((Value, Value), Value)> = None;
    for (profile_id, found, used_at) in candidates {
        if !swap::has_room(found) {
            continue;
        }
        let used = if pyval::truthy(used_at) {
            used_at.clone()
        } else {
            Value::from(0)
        };
        let rank = (
            get(found, "most_used").cloned().unwrap_or(Value::Null),
            used,
        );
        let better = match &picked {
            None => true,
            Some((held, _)) => tuple_less(&rank, held)?,
        };
        if better {
            picked = Some((rank, profile_id.clone()));
        }
    }
    Ok(picked.map(|(_, id)| id))
}

/// `seen(store, profile_id, now)`: the saved account found signed in now marked so. Never fatal.
pub fn seen(store: &Profiles, profile_id: &Value, now: f64) {
    let _ = swap::locked(store, profiles::KEEP_SECONDS, || {
        Ok(store.update(
            profile_id,
            &[("seen_at".to_owned(), Value::from(now.trunc() as i64))],
        )?)
    });
}

/// `settle()`: the unfinished switch settled, nothing else.
fn settle(inner: &mut Inner, scoped: &Scoped<'_>) -> Result<(), Fault> {
    let intent = intent_of(inner)?;
    let home = (inner.seams.home)()?;
    if let Some(word) = recover_now(inner, &home)? {
        settled_word(inner, scoped, word, &intent);
    }
    Ok(())
}

/// `schedule(record, eligible_at)`: EARLY for a record that waits for a usage limit, for EARLY_FOR seconds after this
/// capability (or a person's Switch to this account) switched the account; DEFER for anything else.
fn schedule(inner: &Inner, scoped: &Scoped<'_>, record: &Value, eligible_at: &Value) -> Spoke {
    if !matches!(record, Value::Object(_))
        || !get(record, "category").is_some_and(|category| pyval::is(category, USAGE_LIMIT))
    {
        return Ok(Said::Defer);
    }
    let now = scoped.now();
    let Ok(stamped) = scoped.stamped(&text(OptionKey::AutoSwitchedAt.as_str())) else {
        return Ok(Said::Defer);
    };
    let kept: Vec<Value> = [inner.switched_at.map(Value::Float), Some(stamped)]
        .into_iter()
        .flatten()
        .filter(|at| matches!(at, Value::Int(_) | Value::Float(_) | Value::Bool(_)))
        .collect();
    let switched = match kept.len() {
        0 => None,
        _ => {
            let all: Vec<&Value> = kept.iter().collect();
            match pyval::max(&all) {
                Ok(found) => Some(found.clone()),
                Err(_) => return Ok(Said::Defer),
            }
        }
    };
    let Some(switched) = switched else {
        return Ok(Said::Defer);
    };
    let since = pyval::minus(&Value::Float(now), &switched).unwrap_or(f64::NAN);
    if !(0.0..EARLY_FOR).contains(&since) {
        return Ok(Said::Defer);
    }
    let state = get(record, "state").cloned().unwrap_or(Value::Null);
    let waiting = pyval::in_set(&state, car_machine::vocab_gen::domain_states::WAITING)
        .map_err(Raised::new)?;
    if !waiting
        || !number(Some(eligible_at))
        || pyval::less_or_equal(eligible_at, &Value::Float(now)).unwrap_or(true)
    {
        return Ok(Said::Defer);
    }
    Ok(Said::Word(Alternative::Early))
}

/// The P8 errand: one look.
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

/// tend's errand: the unfinished switch settled, nothing else.
struct SettleErrand {
    inner: Arc<Mutex<Inner>>,
    binding: Arc<Binding>,
}

impl Errand for SettleErrand {
    fn run(&self, _view: &dyn View, _guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let mut inner = lock(&self.inner);
        let _ = self.binding.with(|scoped| settle(&mut inner, scoped));
        Ok(Value::Null)
    }
}

impl AutoSwitch {
    fn due(&self, binding: &Binding) -> Option<f64> {
        let now = binding.with(|scoped| scoped.now())?;
        let mut inner = lock(&self.inner);
        if let Some(looked) = inner.looked
            && (0.0..LOOK_EVERY).contains(&(now - looked))
        {
            return None;
        }
        inner.looked = Some(now);
        Some(now)
    }
}

impl Code for AutoSwitch {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.binding = Some(Arc::new(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, _view: &dyn View) -> Spoke {
        let Some(binding) = self.binding.clone() else {
            return Ok(Said::Defer);
        };
        let Some(now) = self.due(&binding) else {
            return Ok(Said::Defer);
        };
        Ok(Said::Errand(Box::new(LookErrand {
            inner: Arc::clone(&self.inner),
            binding,
            now,
        })))
    }

    fn schedule(&mut self, record: &Value, due: &Value) -> Spoke {
        let Some(binding) = self.binding.clone() else {
            return Ok(Said::Defer);
        };
        let inner = lock(&self.inner);
        binding
            .with(|scoped| schedule(&inner, scoped, record, due))
            .unwrap_or(Ok(Said::Defer))
    }

    fn tend(&mut self, _view: &dyn View) -> Option<Spoke> {
        let Some(binding) = self.binding.clone() else {
            return Some(Ok(Said::Defer));
        };
        if self.due(&binding).is_none() {
            return Some(Ok(Said::Defer));
        }
        let pending = matches!(lock(&self.inner).seams.store.intent(), Ok(Value::Object(_)));
        if !pending {
            return Some(Ok(Said::Defer));
        }
        Some(Ok(Said::Errand(Box::new(SettleErrand {
            inner: Arc::clone(&self.inner),
            binding,
        }))))
    }

    fn as_any(&mut self) -> Option<&mut dyn std::any::Any> {
        Some(self)
    }
}

/// `make(paths)`: the code with the product's own hands (`make_with` for an entry point's or a test's).
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(AutoSwitch::new(live_seams(paths))))
}

/// `make` with the code's hands given.
pub fn make_with(seams: Seams) -> Option<Box<dyn Code>> {
    Some(Box::new(AutoSwitch::new(seams)))
}

/// The product's own hands for `paths`: the saved accounts of its home, the Codex home in use, this capability's own
/// sessions, codex/restart with its own hands, account_switch's read, Windows' idle time and the busy rule.
pub fn live_seams(paths: &Paths) -> Seams {
    let homing = paths.clone();
    let reading = account::Live::new(paths);
    let busying = paths.clone();
    Seams {
        store: crate::state::seam::accounts::live_profiles(std::path::Path::new(&paths.home)),
        home: Box::new(move || {
            let env = |name: &str| std::env::var(name).ok();
            let os = car_codex::system::Platform::new().config;
            crate::codex::inuse::home(Some(&homing.home), &env, &os)
                .map(PathBuf::from)
                .map_err(|class| Fault::new(class, "the Codex home cannot be told"))
        }),
        session_for: Box::new(account::Live::for_capability(paths, CAPABILITY)),
        read_real: Box::new(move || account::read(&reading)),
        world: Box::new(swap::Live::new()),
        hands: Hands {
            restart: None,
            idle: Box::new(|| {
                car_platform::powerdown::idle_seconds().map_or(Value::Null, Value::Float)
            }),
            busy: Box::new(move || Ok(!live_busy(&busying).is_empty())),
            paths: paths.clone(),
        },
    }
}

/// `restart.busy(paths, usage_waiting_ok=True)` with core's store and LocalSource on the Codex home in use, now the
/// wall clock's.
pub fn live_busy(paths: &Paths) -> Vec<&'static str> {
    use crate::codex::restart::{self, Activity, BusyStore};
    struct Store(car_store::Store);
    impl BusyStore for Store {
        fn pending(&self) -> Result<Vec<Value>, Fault> {
            self.0
                .pending()
                .map(|rows| rows.into_iter().map(Value::Object).collect())
                .map_err(|error| Fault::new("StoreError", &format!("{error:?}")))
        }
        fn watcher_status(&self) -> Result<Value, Fault> {
            self.0
                .watcher_status()
                .map(|row| row.map_or(Value::Null, Value::Object))
                .map_err(|error| Fault::new("StoreError", &format!("{error:?}")))
        }
    }
    struct Source(car_codex::source::LocalSource);
    impl Activity for Source {
        fn activity(&self, now: &Value, booted: &Value) -> Result<Value, Fault> {
            self.0
                .activity(&[], now, &Value::Float(3600.0), booted)
                .map(Value::Object)
                .map_err(|error| Fault::new("OSError", &format!("{error:?}")))
        }
    }
    let store = car_store::Store::open(
        std::path::Path::new(&paths.state_dir),
        Arc::new(car_control::host::Probe),
    )
    .map(Store)
    .map_err(|error| Fault::new("StoreError", &format!("{error:?}")));
    let env = |name: &str| std::env::var(name).ok();
    let os = car_codex::system::Platform::new().config;
    let source = crate::codex::inuse::home(Some(&paths.home), &env, &os)
        .map_err(|class| Fault::new(class, "the Codex home cannot be told"))
        .and_then(|home| {
            car_codex::source::LocalSource::new(Arc::new(car_codex::system::PolicyOs), &home, None)
                .map(Source)
                .map_err(|error| Fault::new("OSError", &format!("{error:?}")))
        });
    restart::busy(
        store
            .as_ref()
            .map(|store| store as &dyn BusyStore)
            .map_err(Clone::clone),
        source
            .as_ref()
            .map(|source| source as &dyn Activity)
            .map_err(Clone::clone),
        &Value::Float(crate::state::session::wall_clock()),
        true,
    )
    .unwrap_or_else(|_| vec![restart::UNKNOWN])
}

//! `engine/usagestop.py` (seat S7.2d): the forced stop near a usage limit (v0.6.16-beta.4, item (h)) - usage_pause.
//!
//! At the stop percentage a person chose for a window, the window is held until it resets, as the plain pause held it
//! ([`super::usage::PauseCore`]); and each conversation switched on whose turn is running is stopped through the Codex
//! app's own channel (`codex::ipc`, the Stop button's), once for that window. When the window resets, a conversation it
//! stopped is continued once by a turn the app starts (Continue after the reset), which also lets the queue the app
//! paused go; where that is off, a notice asks the person to press Resume. From v0.6.26 (R2, review V1, audit4 B3/B4)
//! a person's reset message falling due there is carried by that very turn, once, in the continuation's place.
//!
//! Every request to the app is written inside one of core's errand guards. Core's guard is a scope around a body
//! (`Guards`), the app's channel asks its gate just before the write (`ipc::Gate`): the request runs inside the guard's
//! body with the guard's answer as its gate (AUDIT-v0628.md: the guard is held over the request's greeting too).

use std::sync::{Arc, Mutex, PoisonError};

use car_config::Paths;
use car_machine::json::{Map, Value};
use car_policy::plug::{Errand, Guards, HookFailed, View};

use super::continued::{answer_key, words_pass};
use super::resetwatch::{self, Family, Resets, Row, num};
use super::usage::{
    AFTER_RESET_KEY, Bound, NOTICE_FOR, ON, PauseCore, Source, TurnSeen, WRAP_UP, World, cell,
    codex_home, enabled_latest, is_time, is_word, meter_rows, reset_since, source_of, windows,
};
use crate::capabilities::{Binding, Code, Raised, Said, Spoke};
use crate::codex::ipc::{Gate, GateRaised};

pub const FINAL: [&str; 3] = ["completed", "failed", "interrupted"];
/// How many notices the stop keeps for the icon to show.
pub const NOTICES_KEPT: usize = 16;
/// A start after the reset that failed is asked again after this long, doubled at each failure up to BACKOFF_MOST.
pub const BACKOFF_SECONDS: f64 = 300.0;
pub const BACKOFF_MOST: f64 = 3600.0;
pub const RESET_MESSAGE: &str = "reset_message";
pub const MESSAGE_INSTEAD: &str = "message_instead";
pub const CARRY: &str = "carry";
pub const INSTEAD: &str = "instead";
pub const QUEUED: &str = "queued";
pub const CONTINUE: &str = "continue";
/// The app's own answers that the turn was not started.
pub const REFUSED_STARTS: [&str; 3] = ["no_client", "version_mismatch", "refused"];
pub const STOPPED: &str = "stopped";
pub const UNCONFIRMED: &str = "unconfirmed";
pub const HELD: &str = "held";
pub const BROKEN: &str = "broken";
pub const STARTED: &str = "started";

/// The app's channel: `ipc.stop_turn(thread, turn_id, gate=)` and `ipc.start_turn(thread, text, gate=)` - each its
/// closed word, or a raise.
pub trait Ipc: Send + Sync {
    fn stop_turn(
        &self,
        thread: &Value,
        turn_id: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised>;
    fn start_turn(
        &self,
        thread: &Value,
        text: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised>;
}

/// The product's channel: the Desktop's own pipe, request ids from car-platform's random source.
pub struct SystemIpc;

impl Ipc for SystemIpc {
    fn stop_turn(
        &self,
        thread: &Value,
        turn_id: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        let mut ids = car_platform::ipc_pipe::uuid4;
        Ok(crate::codex::ipc::stop_turn(thread, turn_id, None, Some(gate), &mut ids).to_owned())
    }
    fn start_turn(
        &self,
        thread: &Value,
        text: &Value,
        gate: &mut dyn Gate,
    ) -> Result<String, Raised> {
        let mut ids = car_platform::ipc_pipe::uuid4;
        Ok(crate::codex::ipc::start_turn(thread, text, None, Some(gate), &mut ids).to_owned())
    }
}

/// A gate whose answer the guard already gave (the request runs inside the guard's body).
struct Given(bool);

impl Gate for Given {
    fn enter(&mut self) -> Result<Value, GateRaised> {
        Ok(Value::Bool(self.0))
    }
    fn exit(&mut self) -> Result<(), GateRaised> {
        Ok(())
    }
}

/// `launch()`: core's guard, then the message's launch written inside it (`resets.carry_message`).
struct Launch<'a> {
    permitted: bool,
    resets: &'a Resets,
    rule_id: Value,
    launched: bool,
}

impl Gate for Launch<'_> {
    fn enter(&mut self) -> Result<Value, GateRaised> {
        let mut permitted = self.permitted;
        if permitted {
            permitted = matches!(self.resets.carry_message(&self.rule_id), Ok(true));
            if permitted {
                self.launched = true;
            }
        }
        Ok(Value::Bool(permitted))
    }
    fn exit(&mut self) -> Result<(), GateRaised> {
        Ok(())
    }
}

/// `body(gate)` run inside core's guard, the guard's answer its gate; a guard that raised raises.
fn guarded<R>(guards: &mut Guards<'_>, body: impl FnOnce(bool) -> R) -> Result<Option<R>, Raised> {
    let mut body = Some(body);
    let mut out = None;
    guards(&mut |permitted| {
        if let Some(body) = body.take() {
            out = Some(body(permitted));
        }
        Value::Null
    })
    .map_err(|_| Raised::new("Exception"))?;
    Ok(out)
}

fn record_key(row: &Row) -> Value {
    cell(row, "record_id").clone()
}

fn eq(one: &Value, other: &Value) -> bool {
    car_machine::pyval::eq(one, other)
}

/// A notice for the icon (`_notices`): its key, kind, window and reset, and when.
#[derive(Clone, Debug)]
pub struct Notice {
    pub key: String,
    pub kind: String,
    pub window_minutes: Value,
    pub at: f64,
    pub reset_at: Value,
}

/// What the stop keeps in this process.
pub struct StopInner {
    pub core: PauseCore,
    pub home: Option<String>,
    pub notices: Vec<Notice>,
    pub backoff: Vec<(Value, (i64, f64))>,
    pub stopped: Vec<(Value, Value, Value)>,
    pub unsure: Vec<(Value, bool)>,
    pub missing: Vec<(Value, f64)>,
}

/// `UsageStop(paths)`: usage_pause's code - the pause's holding, the forced stop and its continuation after the reset.
pub struct UsageStop {
    inner: Arc<Mutex<StopInner>>,
}

struct StopErrand {
    inner: Arc<Mutex<StopInner>>,
    targets: Vec<(String, TurnSeen)>,
    window: Option<Row>,
}

impl Errand for StopErrand {
    fn run(&self, view: &dyn View, guards: &mut Guards<'_>) -> Result<Value, HookFailed> {
        let mut inner = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        inner
            .run(view, guards, self.targets.clone(), self.window.clone())
            .map_err(|_| HookFailed)
    }
}

fn find<'a, T>(list: &'a [(Value, T)], key: &Value) -> Option<&'a T> {
    list.iter()
        .find(|(held, _)| eq(held, key))
        .map(|(_, found)| found)
}

fn put<T>(list: &mut Vec<(Value, T)>, key: &Value, value: T) {
    match list.iter_mut().find(|(held, _)| eq(held, key)) {
        Some(slot) => slot.1 = value,
        None => list.push((key.clone(), value)),
    }
}

fn pop<T>(list: &mut Vec<(Value, T)>, key: &Value) -> Option<T> {
    let at = list.iter().position(|(held, _)| eq(held, key))?;
    Some(list.remove(at).1)
}

/// The window a notice names: `{"minutes": chain, "reset_at": None, "bucket": "codex"}`.
fn codex_window(row: &Row) -> Row {
    let mut window = Map::new();
    window.insert("minutes".into(), cell(row, "chain").clone());
    window.insert("reset_at".into(), Value::Null);
    window.insert("bucket".into(), Value::from("codex"));
    window
}

/// `_counts_here(rule, window, row, rows, now)`: whether a counting message falls due at the very reset continuation
/// `row` waits for, by reset_message's own guard - or its occasion counted already since the stop.
pub fn counts_here(
    rule: &Row,
    window: Option<&Row>,
    row: &Row,
    rows: &[(Family, Row)],
    now: f64,
) -> Result<bool, Raised> {
    if let Some(window) = window
        && resetwatch::due(rule, Some(window))?
        && is_time(cell(window, "last_closed_at"))
        && num(cell(window, "last_closed_at"))? >= num(cell(row, "created_at"))?
    {
        return Ok(true);
    }
    let found: Vec<Row> = windows(rows)
        .into_iter()
        .filter(|meter| eq(cell(meter, "minutes"), cell(row, "chain")))
        .collect();
    let reset = found
        .first()
        .map_or(Value::Null, |meter| cell(meter, "reset_at").clone());
    if !is_time(&reset) {
        return Ok(false);
    }
    let length = num(cell(row, "chain"))? * 60.0;
    let mut reset_at = num(&reset)?;
    if reset_at - length > num(cell(row, "created_at"))? {
        reset_at -= length;
    }
    let reset_value = if reset_at.fract() == 0.0
        && matches!(reset, Value::Int(_))
        && matches!(cell(row, "chain"), Value::Int(_))
    {
        Value::from(reset_at as i64)
    } else {
        Value::from(reset_at)
    };
    let mut record = Map::new();
    record.insert("category".into(), Value::from("usage_limit"));
    record.insert("reset_at".into(), reset_value);
    super::resetmessage::same_reset(rule, window, &Value::Object(record), now)
}

impl UsageStop {
    pub fn new(paths: Paths, world: World) -> UsageStop {
        UsageStop {
            inner: Arc::new(Mutex::new(StopInner {
                core: PauseCore {
                    paths,
                    world,
                    bound: None,
                },
                home: None,
                notices: Vec::new(),
                backoff: Vec::new(),
                stopped: Vec::new(),
                unsure: Vec::new(),
                missing: Vec::new(),
            })),
        }
    }

    pub fn bind_to(&mut self, bound: Bound) {
        self.lock().core.bound = Some(bound);
    }

    pub fn set_home(&mut self, home: Option<String>) {
        self.lock().home = home;
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, StopInner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// What a probe reads and runs of the stop.
    pub fn with<R>(&self, act: impl FnOnce(&mut StopInner) -> R) -> R {
        act(&mut self.lock())
    }
}

impl StopInner {
    fn world(&self) -> &World {
        &self.core.world
    }

    fn bound(&self) -> Option<&Bound> {
        self.core.bound.as_ref()
    }

    fn count(&self, code: &str) {
        self.core.count(code);
    }

    fn source(&self) -> Result<Source, Raised> {
        source_of(
            self.world(),
            &self.core.paths,
            self.home.as_deref(),
            self.bound(),
        )
    }

    fn locale(&self) -> Option<String> {
        (self.world().locale)(&self.core.paths).ok()
    }

    /// `_StopErrand.run(guard)`: a window newly over its percentage in this very tick marked first and its running
    /// turns stopped; the stops due; then the continuations after a reset.
    pub fn run(
        &mut self,
        view: &dyn View,
        guards: &mut Guards<'_>,
        targets: Vec<(String, TurnSeen)>,
        window: Option<Row>,
    ) -> Result<Value, Raised> {
        let mut targets = targets;
        let mut window = window;
        let marked = self.core.mark();
        let newly = self.once(marked);
        if !newly.is_empty() {
            if let Ok(found) = self.running(view) {
                for one in found {
                    if !targets
                        .iter()
                        .any(|held| held.0 == one.0 && held.1 == one.1)
                    {
                        targets.push(one);
                    }
                }
            }
            if window.is_none() {
                window = newly.first().cloned();
            }
        }
        if !targets.is_empty() {
            self.stop_all(&targets, window.as_ref(), guards)?;
        }
        let _ = self.after_reset(view, guards);
        Ok(Value::Null)
    }

    /// `_once(newly)`: the windows newly held that were not stopped already for this reset.
    pub fn once(&mut self, newly: Vec<Row>) -> Vec<Row> {
        let mut fresh = Vec::new();
        for row in newly {
            let key = (
                cell(&row, "bucket").clone(),
                cell(&row, "minutes").clone(),
                cell(&row, "reset_at").clone(),
            );
            if !self
                .stopped
                .iter()
                .any(|held| eq(&held.0, &key.0) && eq(&held.1, &key.1) && eq(&held.2, &key.2))
            {
                self.stopped.push(key);
                fresh.push(row);
            }
        }
        if self.stopped.len() > NOTICES_KEPT {
            let extra = self.stopped.len() - NOTICES_KEPT;
            self.stopped.drain(..extra);
        }
        fresh
    }

    /// `_running(view)`: (thread, turn) of each conversation switched on, of the kind core recovers, whose latest turn
    /// runs.
    pub fn running(&self, view: &dyn View) -> Result<Vec<(String, TurnSeen)>, Raised> {
        let home = codex_home(self.world(), &self.core.paths, self.home.as_deref())?;
        let source = self.source()?;
        let mut found = Vec::new();
        for thread in self.world().codex.running(&home, &self.core.paths)? {
            let Ok(Some(Some(turn))) = enabled_latest(self.world(), view, &source, &thread) else {
                continue;
            };
            if turn.status == "inProgress" {
                found.push((thread, turn));
            }
        }
        Ok(found)
    }

    /// `stop_all(targets, window, guard)`: each running turn stopped through the app inside core's guard; what came of
    /// each journalled and, where it matters, said in a notice; each one stopped remembered for its continuation.
    pub fn stop_all(
        &mut self,
        targets: &[(String, TurnSeen)],
        window: Option<&Row>,
        guards: &mut Guards<'_>,
    ) -> Result<(), Raised> {
        let empty = Map::new();
        let window = window.unwrap_or(&empty);
        for (thread, turn) in targets {
            let ipc = self.world().ipc.clone();
            let thread_value = Value::from(thread.as_str());
            let word = match guarded(guards, |permitted| {
                ipc.stop_turn(&thread_value, &turn.turn_id, &mut Given(permitted))
            }) {
                Ok(Some(Ok(word))) => word,
                _ => BROKEN.to_owned(),
            };
            if word == HELD {
                self.count("held");
                continue;
            }
            if word != STOPPED && word != UNCONFIRMED {
                self.count("not_stopped");
                self.notice("not_stopped", window);
                continue;
            }
            self.count(if word == STOPPED {
                "stopped"
            } else {
                "stop_unconfirmed"
            });
            if !self.remember(thread, turn, window) {
                self.count("resume_unproven");
                self.notice("press_resume", window);
            }
        }
        Ok(())
    }

    /// `_continue_on()`: whether Continue after the reset (the wrap-up's choice) is on; off where it cannot be read.
    fn continue_on(&self) -> bool {
        let Some(bound) = self.bound() else {
            return false;
        };
        match bound.call(|scoped| scoped.options_of(&Value::from(WRAP_UP))) {
            Ok(options) => options
                .get("wrap_after_reset")
                .is_none_or(|value| super::wrapwords::num_eq(value, ON)),
            Err(_) => false,
        }
    }

    /// `_remember(thread, turn, window)`: a conversation it stopped, kept for one turn after its window resets.
    fn remember(&self, thread: &str, turn: &TurnSeen, window: &Row) -> bool {
        self.remembering(thread, turn, window).unwrap_or(false)
    }

    fn remembering(&self, thread: &str, turn: &TurnSeen, window: &Row) -> Result<bool, Raised> {
        let Some(bound) = self.bound() else {
            return Err(Raised::new("AttributeError"));
        };
        let going = self.continue_on();
        let thread_value = Value::from(thread);
        let key = Value::from(answer_key(&[
            Value::from("after_reset"),
            thread_value.clone(),
            cell(window, "bucket").clone(),
            cell(window, "minutes").clone(),
            cell(window, "reset_at").clone(),
        ]));
        if bound
            .call(|scoped| scoped.handle().continuation(&key))?
            .is_some()
        {
            return Ok(going);
        }
        if !going {
            bound.call(|scoped| {
                scoped.handle().continuations_writing()?;
                scoped.state.add_held_continuation(
                    &key,
                    &scoped.capability,
                    &Value::from("after_reset"),
                    &thread_value,
                    &turn.ordinal,
                    cell(window, "minutes"),
                    &Value::Null,
                )
            })?;
            return Ok(false);
        }
        let words = self
            .world()
            .text(AFTER_RESET_KEY, self.locale().as_deref())?;
        let words = words.map_or(Value::Null, Value::from);
        if !words_pass(&words) {
            return Ok(false);
        }
        bound.call(|scoped| {
            scoped.handle().continuations_writing()?;
            scoped.state.add_continuation(
                &key,
                &scoped.capability,
                &Value::from("after_reset"),
                &thread_value,
                &words,
                &turn.ordinal,
                cell(window, "minutes"),
                &Value::Null,
            )
        })?;
        Ok(true)
    }

    /// `_waiting()`: the continuations after a reset that wait - with words, or held with none.
    pub fn waiting(&self) -> Vec<Row> {
        let Some(bound) = self.bound() else {
            return Vec::new();
        };
        bound
            .call(|scoped| {
                scoped
                    .state
                    .continuations(&scoped.capability, &Value::Null, &Value::Bool(true))
            })
            .map(|rows| {
                rows.into_iter()
                    .filter(|row| {
                        is_word(cell(row, "record_state"), "waiting")
                            && is_word(cell(row, "kind"), "after_reset")
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    fn end_superseded(&self, thread: &Value) -> Result<(), Raised> {
        let Some(bound) = self.bound() else {
            return Ok(());
        };
        bound.call(|scoped| {
            scoped.handle().continuations_writing()?;
            scoped.state.end_continuations(
                &Value::from("superseded"),
                &scoped.capability,
                thread,
                &Value::Null,
            )
        })?;
        Ok(())
    }

    fn end_sent(&self, thread: &Value) -> Result<(), Raised> {
        let Some(bound) = self.bound() else {
            return Ok(());
        };
        bound.call(|scoped| {
            scoped.handle().continuations_writing()?;
            scoped.state.end_continuations(
                &Value::from("sent"),
                &scoped.capability,
                thread,
                &Value::Null,
            )
        })?;
        Ok(())
    }

    fn backoff_after(&mut self, key: &Value, failures: i64, now: f64) {
        let wait = (BACKOFF_SECONDS * 2f64.powi(failures.clamp(0, 62) as i32)).min(BACKOFF_MOST);
        put(&mut self.backoff, key, (failures + 1, now + wait));
    }

    /// `after_reset(view, guard)`: each conversation it stopped whose window has reset, continued once by a turn the
    /// app starts inside core's guard - while the stopped turn is still its latest and ended, the app holds it, no window
    /// the stop holds is still held; ended where newer work came; the person's reset message carried in its place.
    pub fn after_reset(&mut self, view: &dyn View, guards: &mut Guards<'_>) -> Result<(), Raised> {
        let Some(bound) = self.bound().cloned() else {
            return Err(Raised::new("AttributeError"));
        };
        let waiting = self.waiting();
        if waiting.is_empty() {
            return Ok(());
        }
        let held = self.core.holding()?;
        let now = bound.now();
        let rows = bound.call(|scoped| meter_rows(scoped))?;
        let home = codex_home(self.world(), &self.core.paths, self.home.as_deref())?;
        let source = self.source()?;
        let going = self.continue_on();
        for row in waiting {
            let thread_value = cell(&row, "thread_id").clone();
            let thread = car_machine::pytext::py_str(&thread_value);
            let record = record_key(&row);
            let doubted = cell(&row, "launching_at").clone();
            let unsure = find(&self.unsure, &record).is_some() || is_time(&doubted);
            if !reset_since(&rows, cell(&row, "chain"), cell(&row, "created_at"), now)?
                || (held && !unsure)
            {
                self.newer_ends(&row, view, &source, &home)?;
                continue;
            }
            let Some((found, rule)) = self.message_instead(&row, &rows, now)? else {
                continue;
            };
            if held && !unsure {
                continue;
            }
            if found == INSTEAD && !unsure {
                self.end_superseded(&thread_value)?;
                self.count(MESSAGE_INSTEAD);
                continue;
            }
            if found == QUEUED && self.notice("press_resume", &codex_window(&row)) {
                self.count("resume_unproven");
            }
            // Some(true): on and found by core's reader; Some(false): on, not found; None: off.
            let read = (|| -> Result<Option<bool>, Raised> {
                let enabled = view
                    .thread_enabled(&thread)
                    .map_err(|failed| Raised::new(failed.0))?;
                if !enabled {
                    return Ok(None);
                }
                Ok(Some(source.latest(self.world(), &thread)?.is_some()))
            })();
            match read {
                Err(_) | Ok(None) => continue,
                Ok(Some(false)) => {
                    if found == CARRY
                        && let Some(rule) = &rule
                    {
                        self.message_gone(&row, rule, now);
                    }
                    continue;
                }
                Ok(Some(true)) => {}
            }
            pop(&mut self.missing, &record);
            let Ok(latest) = self.world().codex.latest(&home, &thread) else {
                continue;
            };
            let ordinal = cell(&row, "ordinal");
            if latest
                .as_ref()
                .is_none_or(|latest| !eq(&latest.ordinal, ordinal))
            {
                self.end_superseded(&thread_value)?;
                if unsure {
                    pop(&mut self.unsure, &record);
                    self.count(MESSAGE_INSTEAD);
                }
                continue;
            }
            let latest = latest.expect("checked above");
            if unsure {
                let first = if car_machine::pyval::truthy(&doubted) {
                    num(&doubted)?
                } else {
                    now
                };
                let again = find(&self.backoff, &record)
                    .map_or(first + BACKOFF_SECONDS, |(_, again)| *again);
                let said = find(&self.unsure, &record).copied().unwrap_or(false);
                if !said && now >= again {
                    put(&mut self.unsure, &record, true);
                    if self.notice("press_resume", &codex_window(&row)) {
                        self.count("resume_unproven");
                    }
                }
                continue;
            }
            if !FINAL.contains(&latest.status.as_str()) || found == QUEUED {
                continue;
            }
            let words = cell(&row, "words");
            let worded = car_machine::pyval::truthy(words);
            if found == CONTINUE && !(going && worded) && worded {
                let _ = bound.call(|scoped| {
                    scoped.handle().continuations_writing()?;
                    scoped
                        .state
                        .hold_continuation(cell(&row, "answer_id"), &scoped.capability)
                });
                if self.notice("press_resume", &codex_window(&row)) {
                    self.count("resume_unproven");
                }
                continue;
            }
            if found == CONTINUE && !(going && worded) {
                continue;
            }
            let (failures, again) = find(&self.backoff, &record).copied().unwrap_or((0, 0.0));
            if now < again {
                continue;
            }
            if found == CARRY {
                if let Some(rule) = rule {
                    self.carry(&row, &rule, guards, now, failures)?;
                }
                continue;
            }
            let marker =
                car_machine::domain::ids::short_marker(&car_machine::pytext::py_str(&record));
            let text = Value::from(format!(
                "{}\n\n{marker}",
                car_machine::pytext::py_str(words)
            ));
            let ipc = self.world().ipc.clone();
            let word = match guarded(guards, |permitted| {
                ipc.start_turn(&thread_value, &text, &mut Given(permitted))
            })? {
                Some(Ok(word)) => word,
                Some(Err(raised)) => return Err(raised),
                None => return Err(Raised::new("Exception")),
            };
            if word == HELD {
                continue;
            }
            if word == UNCONFIRMED {
                self.backoff_after(&record, failures, now);
                continue;
            }
            if word == STARTED {
                pop(&mut self.backoff, &record);
                self.end_sent(&thread_value)?;
                self.count("continued");
            } else {
                self.backoff_after(&record, failures, now);
                self.count("not_continued");
                self.notice("not_continued", &codex_window(&row));
            }
        }
        Ok(())
    }

    /// `_newer_ends(row, view, source, turns)`: ended superseded where its conversation has newer work than the turn it
    /// stopped; nothing ended on what cannot be read.
    fn newer_ends(
        &self,
        row: &Row,
        view: &dyn View,
        source: &Source,
        home: &str,
    ) -> Result<(), Raised> {
        let thread_value = cell(row, "thread_id").clone();
        let thread = car_machine::pytext::py_str(&thread_value);
        let _ = home;
        let Ok(Some(Some(latest))) = enabled_latest(self.world(), view, source, &thread) else {
            return Ok(());
        };
        if !eq(&latest.ordinal, cell(row, "ordinal")) {
            self.end_superseded(&thread_value)?;
        }
        Ok(())
    }

    /// `_message_gone(row, rule, now)`: a message the stop's turn would carry, its conversation not found - a day's
    /// grace, the person told at once, then ended as reset_message ends one that waited too long.
    fn message_gone(&mut self, row: &Row, rule: &Row, now: f64) {
        let record = record_key(row);
        let first = match find(&self.missing, &record) {
            Some(first) => *first,
            None => {
                self.missing.push((record.clone(), now));
                now
            }
        };
        if first == now {
            self.count("not_continued");
            self.notice("not_continued", &codex_window(row));
        }
        if now - first < super::resetmessage::DUE_FOR {
            return;
        }
        let Some(bound) = self.bound() else { return };
        let resets = Resets {
            bound: bound.clone(),
        };
        if let Ok(true) = resets.message_expired(cell(rule, "rule_id")) {
            pop(&mut self.missing, &record);
        }
    }

    /// `_carry(row, rule, start, guard, now, failures)`: the stop's turn after the reset carrying the person's reset
    /// message instead - its launch written inside core's guard just before the one request.
    fn carry(
        &mut self,
        row: &Row,
        rule: &Row,
        guards: &mut Guards<'_>,
        now: f64,
        failures: i64,
    ) -> Result<(), Raised> {
        let Some(bound) = self.bound().cloned() else {
            return Err(Raised::new("AttributeError"));
        };
        let resets = Resets {
            bound: bound.clone(),
        };
        let thread_value = cell(row, "thread_id").clone();
        let record = record_key(row);
        let marker = car_machine::domain::ids::short_marker(&car_machine::pytext::py_str(cell(
            rule,
            "record_id",
        )));
        let text = Value::from(format!(
            "{}\n\n{marker}",
            car_machine::pytext::py_str(cell(rule, "words"))
        ));
        let ipc = self.world().ipc.clone();
        let mut launched = false;
        let asked = guarded(guards, |permitted| {
            let mut gate = Launch {
                permitted,
                resets: &resets,
                rule_id: cell(rule, "rule_id").clone(),
                launched: false,
            };
            let word = ipc.start_turn(&thread_value, &text, &mut gate);
            launched = gate.launched;
            word
        });
        let word = match asked {
            Ok(Some(Ok(word))) => word,
            _ => BROKEN.to_owned(),
        };
        if launched && !REFUSED_STARTS.contains(&word.as_str()) {
            let _ = resets.carried_message(cell(rule, "rule_id"), true);
            if word != STARTED {
                put(&mut self.unsure, &record, false);
                self.backoff_after(&record, failures, now);
                let _ = bound.call(|scoped| {
                    scoped.handle().continuations_writing()?;
                    scoped.state.doubt_continuation(
                        cell(row, "answer_id"),
                        &scoped.capability,
                        &Value::Null,
                    )
                });
                return Ok(());
            }
            pop(&mut self.backoff, &record);
            self.end_superseded(&thread_value)?;
            self.count(MESSAGE_INSTEAD);
            return Ok(());
        }
        if launched {
            let _ = resets.carried_message(cell(rule, "rule_id"), false);
        }
        if word == HELD && !launched {
            return Ok(());
        }
        self.backoff_after(&record, failures, now);
        self.count("not_continued");
        self.notice("not_continued", &codex_window(row));
        Ok(())
    }

    /// `_message_instead(row, rows, now)`: what of the person's reset messages stands for continuation `row` at the
    /// reset it waits for - (CARRY, rule), (INSTEAD, rule), (QUEUED, rule), (CONTINUE, None), or None (not known now).
    pub fn message_instead(
        &self,
        row: &Row,
        rows: &[(Family, Row)],
        now: f64,
    ) -> Result<Option<(&'static str, Option<Row>)>, Raised> {
        let Some(bound) = self.bound() else {
            return Ok(None);
        };
        let resets = Resets {
            bound: bound.clone(),
        };
        let read = (|| -> Result<(Vec<Row>, Vec<(Family, Row)>, bool), resetwatch::Failed> {
            let rules: Vec<Row> = resets
                .reset_rules(Some(RESET_MESSAGE), &Value::Null)?
                .into_iter()
                .filter(|rule| eq(cell(rule, "thread_id"), cell(row, "thread_id")))
                .collect();
            let counted = if rules.is_empty() {
                Vec::new()
            } else {
                resets.windows()?
            };
            let on = !rules.is_empty() && bound.armed(RESET_MESSAGE);
            Ok((rules, counted, on))
        })();
        let Ok((rules, counted, on)) = read else {
            return Ok(None);
        };
        let since = num(cell(row, "created_at"))?;
        let mut waiting = false;
        for rule in rules {
            let state = cell(&rule, "state");
            let flying = is_word(cell(&rule, "record_state"), "in_flight");
            let sent = ["sent_at", "launching_at"]
                .iter()
                .map(|name| cell(&rule, name))
                .find(|value| is_time(value))
                .cloned();
            if is_word(state, "done")
                && is_time(cell(&rule, "sent_at"))
                && num(cell(&rule, "sent_at"))? >= since
            {
                return Ok(Some((INSTEAD, Some(rule))));
            }
            if !is_word(state, "ready") {
                let family: Family = (
                    cell(&rule, "bucket").clone(),
                    cell(&rule, "minutes").clone(),
                );
                if is_word(state, "counting")
                    && on
                    && counts_here(&rule, resetwatch::find(&counted, &family), row, rows, now)?
                {
                    waiting = true;
                }
                continue;
            }
            if flying {
                match sent {
                    None => waiting = true,
                    Some(sent) if num(&sent)? >= since => {
                        let word = if matches!(cell(&rule, "queue_id"), Value::Null) {
                            INSTEAD
                        } else {
                            QUEUED
                        };
                        return Ok(Some((word, Some(rule))));
                    }
                    Some(_) => {}
                }
                continue;
            }
            if on
                && is_word(cell(&rule, "record_state"), "waiting")
                && car_machine::pyval::truthy(cell(&rule, "words"))
                && is_time(cell(&rule, "due_at"))
                && num(cell(&rule, "due_at"))? >= since
            {
                return Ok(Some((CARRY, Some(rule))));
            }
        }
        Ok(if waiting {
            None
        } else {
            Some((CONTINUE, None))
        })
    }

    /// `_notice(kind, window)`: a notice for the icon, once by its key - whether it is new.
    pub fn notice(&mut self, kind: &str, window: &Row) -> bool {
        let now = self
            .bound()
            .map_or_else(crate::state::session::wall_clock, Bound::now);
        let minutes = cell(window, "minutes").clone();
        let reset = cell(window, "reset_at").clone();
        let tail = if car_machine::pyval::truthy(&reset) {
            car_machine::pytext::py_str(&reset)
        } else {
            format!("{}", (now / NOTICE_FOR).floor() as i64)
        };
        let key = format!("{kind}:{}:{tail}", car_machine::pytext::py_str(&minutes));
        if self.notices.iter().any(|notice| notice.key == key) {
            return false;
        }
        self.notices.push(Notice {
            key,
            kind: kind.to_owned(),
            window_minutes: minutes,
            at: now,
            reset_at: reset,
        });
        if self.notices.len() > NOTICES_KEPT {
            let extra = self.notices.len() - NOTICES_KEPT;
            self.notices.drain(..extra);
        }
        true
    }

    /// `notices(now)`: what the stop has to say to the icon now - the notices of the last NOTICE_FOR seconds.
    pub fn notices(&self, now: f64) -> Vec<Value> {
        self.notices
            .iter()
            .filter(|notice| (0.0..NOTICE_FOR).contains(&(now - notice.at)))
            .map(|notice| {
                let mut map = Map::new();
                map.insert("key".into(), Value::from(notice.key.as_str()));
                map.insert("kind".into(), Value::from(notice.kind.as_str()));
                map.insert("window_minutes".into(), notice.window_minutes.clone());
                map.insert("reset_at".into(), notice.reset_at.clone());
                Value::Object(map)
            })
            .collect()
    }

    /// P8: the windows marked; an errand where turns are to be stopped or a continuation after a reset waits.
    pub fn tick_errand(
        &mut self,
        view: &dyn View,
    ) -> Option<(Vec<(String, TurnSeen)>, Option<Row>)> {
        self.bound()?;
        let marked = self.core.mark();
        let newly = self.once(marked);
        let mut targets = Vec::new();
        if !newly.is_empty() {
            targets = self.running(view).unwrap_or_default();
        }
        if targets.is_empty() && self.waiting().is_empty() {
            return None;
        }
        Some((targets, newly.first().cloned()))
    }
}

impl Code for UsageStop {
    fn bind(&mut self, binding: Binding) -> Option<Result<(), Raised>> {
        self.lock().core.bound = Some(Bound::of(binding));
        Some(Ok(()))
    }

    fn tick(&mut self, view: &dyn View) -> Spoke {
        let due = self.lock().tick_errand(view);
        let Some((targets, window)) = due else {
            return Ok(Said::Defer);
        };
        Ok(Said::Errand(Box::new(StopErrand {
            inner: self.inner.clone(),
            targets,
            window,
        })))
    }

    fn gate(&mut self, _name: &Value, record: &Value, _facts: &Value) -> Spoke {
        Ok(self.lock().core.gate(record))
    }

    fn holds(&mut self, record: &Value) -> Option<Result<Value, Raised>> {
        Some(Ok(Value::Bool(self.lock().core.holds(record))))
    }
}

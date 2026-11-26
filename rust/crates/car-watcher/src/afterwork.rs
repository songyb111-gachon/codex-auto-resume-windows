//! `runtime/afterwork.py`: the watcher's side of the power action after usage-limit recoveries (v0.6.12;
//! car-policy's `poweraction` decides).
//!
//! Asked by the loop on the thread that ticks, right after it has kept this PC awake or let it go. Each look follows
//! poweraction's order: the file first - with none, or nothing armed, nothing else is read and Windows is asked
//! nothing (H14) - then the records, then Codex's history and counts (`engine.activity`), then Windows. Only then
//! does a countdown start, with its notice, and the loop looks every 15 seconds while it runs (`cap`). Nothing here
//! sends anything to Codex, changes a record, or changes a setting of Windows'.

use car_config::logbook::{Clock, render};
use car_machine::json::{Map, Value};
use car_machine::pytext::py_str;
use car_machine::pyval;
use car_policy::settings::managed::Managed;
use car_policy::settings::poweraction as decision;
use car_store::Store;

use crate::fail::{Failed, Res};
use crate::waking::Waking;

/// The notices this raises, by their event names (notifier.POWER_EVENTS).
pub const GRACE: &str = "power_grace";
pub const NOW: &str = "power_now";
pub const FAILED: &str = "power_failed";
pub const NOT_MET: &str = "power_not_met";
/// Why a countdown ended, beside a PowerWait or a PowerEnd.
pub const INPUT: &str = "input";
pub const GAP: &str = "gap";
pub const TURNED_OFF: &str = "turned_off";
pub const FAILED_LOOK: &str = "failed";
pub const STOPPING: &str = "watcher_stopped";

/// The control layer's power-action methods, as AfterWork asks them.
pub trait PowerControl {
    /// `read_power_action(now)`: (why, document).
    fn read_power_action(&self, now: f64) -> Res<(String, Value)>;
    fn power_batch_end(&self, nonce: &Value, result: &str, now: f64) -> Res<bool>;
    fn power_batch_finish(&self, nonce: &Value, now: f64) -> Res<Option<String>>;
    fn power_refused(&self, now: f64) -> Res<bool>;
    fn power_show(&self, nonce: &Value, shown: &Value) -> Res<bool>;
    /// `control.plug.power(facts)`: P21's checked answer, or None.
    fn plug_power(&self, facts: &Value) -> Res<Option<Value>>;
}

impl PowerControl for car_control::Control {
    fn read_power_action(&self, now: f64) -> Res<(String, Value)> {
        let (why, document) = self.read_power_action_at(now)?;
        Ok((why.to_owned(), document))
    }
    fn power_batch_end(&self, nonce: &Value, result: &str, now: f64) -> Res<bool> {
        Ok(car_control::Control::power_batch_end(
            self,
            nonce,
            &Value::from(result),
            Some(now),
        ))
    }
    fn power_batch_finish(&self, nonce: &Value, now: f64) -> Res<Option<String>> {
        Ok(car_control::Control::power_batch_finish(self, nonce, Some(now)).map(str::to_owned))
    }
    fn power_refused(&self, now: f64) -> Res<bool> {
        Ok(car_control::Control::power_refused(self, Some(now)))
    }
    fn power_show(&self, nonce: &Value, shown: &Value) -> Res<bool> {
        Ok(car_control::Control::power_show(self, nonce, shown, None))
    }
    fn plug_power(&self, facts: &Value) -> Res<Option<Value>> {
        Ok(self.plug().power(facts))
    }
}

/// `win/powerdown.py`, or a test's stand-in with the same names.
pub trait Powerdown {
    /// (whether Windows lets this account do it here, why not).
    fn available(&self, action: &Value) -> Res<(bool, Option<String>)>;
    /// How many other people are signed in, or None.
    fn other_sessions(&self) -> Res<Value>;
    /// Seconds since the last input, or None.
    fn idle_seconds(&self) -> Res<Value>;
    fn act(&self, action: &Value) -> Res<Value>;
    fn last_error(&self) -> Res<Value>;
}

/// This PC.
pub struct ThisPowerdown;

impl Powerdown for ThisPowerdown {
    fn available(&self, action: &Value) -> Res<(bool, Option<String>)> {
        let (found, why) = car_platform::powerdown::available(&py_str(action));
        Ok((found, why.map(str::to_owned)))
    }
    fn other_sessions(&self) -> Res<Value> {
        Ok(
            car_platform::powerdown::other_sessions()
                .map_or(Value::Null, |n| Value::from(n as i64)),
        )
    }
    fn idle_seconds(&self) -> Res<Value> {
        Ok(car_platform::powerdown::idle_seconds().map_or(Value::Null, Value::Float))
    }
    fn act(&self, action: &Value) -> Res<Value> {
        Ok(Value::Bool(car_platform::powerdown::act(&py_str(action))))
    }
    fn last_error(&self) -> Res<Value> {
        Ok(
            car_platform::powerdown::last_error()
                .map_or(Value::Null, |n| Value::from(i64::from(n))),
        )
    }
}

/// What the engine is asked: `engine.activity(threads)` and its follow window.
pub trait Activity {
    fn activity(&mut self, threads: &[String]) -> Res<Value>;
    /// `engine.options["unknown_reconcile_window_seconds"]`, as it is (a failure to read is None).
    fn follow_option(&self) -> Option<Value>;
}

/// `notice(event, detail, final=False)`: a power notice raised.
pub type Notice<'a> = &'a dyn Fn(&str, Map, bool) -> Res<()>;

#[derive(Clone, Debug)]
struct Countdown {
    nonce: Value,
    started: f64,
    last_look: f64,
    until: f64,
}

/// `AfterWork(control=, log=, notice=, port=, clock=)`: one watcher's countdown and what it remembers between looks.
pub struct AfterWork {
    pub control: Box<dyn PowerControl>,
    port: Box<dyn Powerdown>,
    clock: Box<dyn Fn() -> f64>,
    countdown: Option<Countdown>,
    seen: (Value, bool),
    said: Option<(Value, String)>,
    shown: Option<(Value, Vec<(String, Value)>)>,
    known: Value,
    invalid: bool,
}

fn field(value: &Value, key: &str) -> Value {
    match value {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    }
}

/// `armed[key]`: a KeyError where the arming lacks it.
fn key(armed: &Value, name: &str) -> Res<Value> {
    match armed {
        Value::Object(map) => map
            .get(name)
            .cloned()
            .ok_or_else(|| Failed::new("KeyError", name)),
        _ => Err(Failed::new("TypeError", "")),
    }
}

fn number(value: &Value) -> Res<f64> {
    car_machine::pytext::to_float(value).map_err(|class| Failed::new(class, ""))
}

fn map<const N: usize>(pairs: [(&str, Value); N]) -> Map {
    let mut found = Map::new();
    for (name, value) in pairs {
        found.insert(name.into(), value);
    }
    found
}

fn shown_map(phase: &str, waiting_for: Option<&str>, grace_until: Option<f64>) -> Map {
    map([
        ("phase", Value::from(phase)),
        ("waiting_for", waiting_for.map_or(Value::Null, Value::from)),
        ("grace_until", grace_until.map_or(Value::Null, Value::Float)),
    ])
}

fn py(class: &'static str) -> Failed {
    Failed::new(class, "")
}

/// `_for(armed, detail)`: `tasks` True for an arming for tasks a person picked.
fn for_tasks(armed: &Value, mut detail: Map) -> Map {
    if decision::for_tasks(armed) {
        detail.insert("tasks".into(), Value::Bool(true));
    }
    detail
}

/// `_follow_window(engine)`.
fn follow_window(engine: Option<&dyn Activity>) -> Value {
    let Some(window) = engine.and_then(Activity::follow_option) else {
        return Value::Float(decision::FOLLOW_SECONDS);
    };
    match window {
        Value::Int(_) | Value::Float(_)
            if pyval::less(&Value::from(0), &window).unwrap_or(false) =>
        {
            Value::Float(number(&window).unwrap_or(decision::FOLLOW_SECONDS))
        }
        _ => Value::Float(decision::FOLLOW_SECONDS),
    }
}

/// What one look is handed.
pub struct Look<'a> {
    pub store: &'a Store,
    pub engine: Option<&'a mut dyn Activity>,
    pub ok: bool,
    pub waking: Option<&'a mut Waking>,
    pub settings: &'a Value,
    pub managed: &'a Managed,
    pub log: &'a dyn Fn(&str),
    pub notice: Notice<'a>,
    pub clock: &'a dyn Clock,
}

impl AfterWork {
    pub fn new(
        control: Box<dyn PowerControl>,
        port: Box<dyn Powerdown>,
        clock: Box<dyn Fn() -> f64>,
    ) -> AfterWork {
        AfterWork {
            control,
            port,
            clock,
            countdown: None,
            seen: (Value::Null, false),
            said: None,
            shown: None,
            known: Value::Null,
            invalid: false,
        }
    }

    pub fn counting(&self) -> bool {
        self.countdown.is_some()
    }

    /// `cap(interval)`: the loop's wait - at most COUNTDOWN_LOOK_SECONDS while a countdown runs.
    pub fn cap(&self, interval: f64) -> f64 {
        if self.countdown.is_some() {
            interval.min(decision::COUNTDOWN_LOOK_SECONDS)
        } else {
            interval
        }
    }

    /// `look(store, engine, ok=, waking=, settings=, managed=)`: one look after a tick.
    pub fn look(&mut self, mut look: Look) -> Res<()> {
        let now = (self.clock)();
        let (why, document) = self.control.read_power_action(now)?;
        let armed = if why == decision::READ_OK {
            match field(&document, "armed") {
                Value::Null => None,
                found => Some(found),
            }
        } else {
            None
        };
        self.note(&why, armed.as_ref(), &look);
        let held = look.managed.disable_power_action;
        let (mut paused, mut rows, mut follow, mut tasks) = (
            false,
            Vec::new(),
            Value::Float(decision::FOLLOW_SECONDS),
            None,
        );
        if let Some(armed) = &armed
            && !held
            && matches!(key(armed, "stop_at")?, Value::Null)
            && look.ok
        {
            paused = Self::paused(look.store, look.settings, look.managed)?;
            if !paused {
                rows = look
                    .store
                    .all_records()?
                    .into_iter()
                    .map(Value::Object)
                    .collect();
                follow = follow_window(look.engine.as_deref().map(|e| e as &dyn Activity));
                if decision::for_tasks(armed) {
                    tasks = Some(self.tasks(armed, now));
                }
            }
        }
        let nonce = match &armed {
            Some(armed) => key(armed, "nonce")?,
            None => Value::Null,
        };
        if let Some(countdown) = &self.countdown
            && !pyval::eq(&countdown.nonce, &nonce)
        {
            self.stop_countdown(TURNED_OFF, &look);
        }
        let saw = if pyval::eq(&self.seen.0, &nonce) && !matches!(nonce, Value::Null) {
            self.seen.1
        } else {
            false
        };
        let facts = decision::Facts {
            now: Value::Float(now),
            read: why.clone(),
            document: document.clone(),
            managed: Value::Bool(held),
            ok: Value::Bool(look.ok),
            paused: Value::Bool(paused),
            rows: rows.clone(),
            saw_open: saw,
            follow_window: follow,
            tasks: match &tasks {
                None => Value::Null,
                Some(None) => Value::Null,
                Some(Some(found)) => field(found, "tasks"),
            },
        };
        let found = decision::decide(&facts).map_err(py)?;
        if !matches!(nonce, Value::Null) {
            self.seen = (nonce.clone(), found.saw_open);
        }
        match found.verdict {
            decision::OFF => {
                self.off(armed.as_ref(), found.word, &look);
                Ok(())
            }
            decision::WAIT => self.wait(armed.as_ref(), found.word, false, &look),
            decision::END => {
                let armed = armed.ok_or_else(|| py("TypeError"))?;
                self.end(&armed, found.word.unwrap_or_default(), now, &look)
            }
            _ => {
                let armed = armed.ok_or_else(|| py("TypeError"))?;
                self.go(&armed, &rows, now, tasks.flatten(), &mut look)
            }
        }
    }

    /// `_tasks(armed, now)`: P21 - the plug's checked answer, or None (on which the look waits).
    fn tasks(&self, armed: &Value, now: f64) -> Option<Value> {
        let facts = Value::Object(map([
            ("nonce", field(armed, "nonce")),
            ("armed_at", field(armed, "armed_at")),
            ("now", Value::Float(now)),
        ]));
        self.control.plug_power(&facts).ok().flatten()
    }

    /// `_go`: steps 11 to 16, once steps 1 to 10 have passed.
    fn go(
        &mut self,
        armed: &Value,
        rows: &[Value],
        now: f64,
        tasks: Option<Value>,
        look: &mut Look,
    ) -> Res<()> {
        let threads: Vec<String> = if decision::for_tasks(armed) {
            let mut threads: Vec<String> = match tasks.as_ref().map(|found| field(found, "threads"))
            {
                Some(Value::Array(items)) => items.iter().map(py_str).collect(),
                _ => Vec::new(),
            };
            threads.sort();
            threads
        } else {
            let batch = decision::members(rows, armed).map_err(py)?;
            let mut threads: Vec<String> = batch
                .iter()
                .filter_map(|row| match field(row, "thread_id") {
                    Value::Str(text) => Some(crate::fail::lossy(&text)),
                    _ => None,
                })
                .collect();
            threads.sort();
            threads.dedup();
            threads
        };
        let activity = match look.engine.as_deref_mut() {
            Some(engine) => engine.activity(&threads)?,
            None => Value::Null,
        };
        if let Some(word) = decision::judge_activity(&activity) {
            return self.wait(Some(armed), Some(word), false, look);
        }
        let action = key(armed, "action")?;
        let (available, _reason) = self.port.available(&action)?;
        if !available {
            return self.end(armed, "unavailable", now, look);
        }
        if pyval::is(&action, "shut_down") {
            let others = self.port.other_sessions()?;
            if let Some(word) =
                decision::judge_presence(&action, &others, &Value::Float(decision::IDLE_SECONDS))
            {
                return self.wait(Some(armed), Some(word), false, look);
            }
        }
        let idle = self.port.idle_seconds()?;
        let Some(countdown) = self.countdown.clone() else {
            if let Some(word) =
                decision::judge_presence(&Value::from("sleep"), &Value::from(0), &idle)
            {
                return self.wait(Some(armed), Some(word), false, look);
            }
            return self.start(armed, now, look);
        };
        let idle_known = match &idle {
            Value::Int(_) => !pyval::less(&idle, &Value::from(0)).unwrap_or(true),
            Value::Float(seconds) => !seconds.is_nan() && *seconds >= 0.0,
            _ => false,
        };
        if !idle_known {
            return self.wait(Some(armed), Some("idle_unknown"), false, look);
        }
        if !decision::countdown_holds(
            &Value::Float(countdown.started),
            &Value::Float(countdown.last_look),
            &Value::Float(now),
            &idle,
        )
        .map_err(py)?
        {
            let gap = (now - countdown.last_look).abs() > decision::GAP_SECONDS;
            self.stop_countdown(if gap { GAP } else { INPUT }, look);
            return self.wait(
                Some(armed),
                if gap { None } else { Some("person_active") },
                true,
                look,
            );
        }
        if let Some(running) = self.countdown.as_mut() {
            running.last_look = now;
        }
        if now >= countdown.until {
            return self.finish(armed, now, look);
        }
        Ok(())
    }

    /// `_note(why, armed)`: a file that cannot be believed logged once, an arming made in the Dashboard once, and an
    /// arming that went once.
    fn note(&mut self, why: &str, armed: Option<&Value>, look: &Look) {
        if why == decision::READ_INVALID {
            if !self.invalid {
                self.line("power_file_invalid", None, None, look);
            }
            self.invalid = true;
        } else if why != decision::READ_UNREADABLE {
            self.invalid = false;
        }
        if why == decision::READ_UNREADABLE {
            return;
        }
        let nonce = armed.map_or(Value::Null, |armed| field(armed, "nonce"));
        if let Some(armed) = armed
            && !pyval::eq(&nonce, &self.known)
            && pyval::eq(&field(armed, "since"), &field(armed, "armed_at"))
        {
            let carried = match field(armed, "carried") {
                Value::Array(items) => items.len().to_string(),
                Value::Object(items) => items.len().to_string(),
                Value::Str(text) => text.len().to_string(),
                _ => "0".to_owned(),
            };
            self.line(
                "power_armed",
                Some(py_str(&field(armed, "action"))),
                Some(carried),
                look,
            );
        } else if armed.is_none() && !matches!(self.known, Value::Null) {
            self.line("power_off", Some(TURNED_OFF.into()), None, look);
        }
        self.known = nonce;
    }

    fn off(&mut self, armed: Option<&Value>, word: Option<&str>, look: &Look) {
        self.stop_countdown(word.unwrap_or(TURNED_OFF), look);
        if word == Some(decision::OFF_MANAGED)
            && let Some(armed) = armed
        {
            let said = (field(armed, "nonce"), decision::OFF_MANAGED.to_owned());
            if !self.said_is(&said) {
                self.said = Some(said);
                self.line("power_off", Some(decision::OFF_MANAGED.into()), None, look);
            }
        }
    }

    fn said_is(&self, wanted: &(Value, String)) -> bool {
        self.said
            .as_ref()
            .is_some_and(|said| pyval::eq(&said.0, &wanted.0) && said.1 == wanted.1)
    }

    /// `_wait`: any countdown ends, and what is waited for is shown and logged once per change.
    fn wait(
        &mut self,
        armed: Option<&Value>,
        word: Option<&str>,
        shown: bool,
        look: &Look,
    ) -> Res<()> {
        if self.countdown.is_some() {
            self.stop_countdown(word.unwrap_or(FAILED_LOOK), look);
        }
        let Some(armed) = armed else {
            return Ok(());
        };
        if word.is_none() && !shown {
            return Ok(());
        }
        self.show(armed, shown_map("waiting", word, None))?;
        if let Some(word) = word {
            let said = (key(armed, "nonce")?, word.to_owned());
            if !self.said_is(&said) {
                self.said = Some(said);
                self.line("power_waiting", Some(word.into()), None, look);
            }
        }
        Ok(())
    }

    /// `_end`: the batch ends without the power action, as `result` says.
    fn end(&mut self, armed: &Value, result: &str, now: f64, look: &Look) -> Res<()> {
        self.stop_countdown(result, look);
        if !self
            .control
            .power_batch_end(&key(armed, "nonce")?, result, now)?
        {
            return Ok(());
        }
        self.forget();
        self.line("power_batch_ended", Some(result.into()), None, look);
        let action = key(armed, "action")?;
        if result == "not_met" && pyval::is(&key(armed, "repeat")?, "once") {
            raise(look, NOT_MET, for_tasks(armed, map([("action", action)])));
        } else if result == "unavailable" {
            raise(look, FAILED, map([("action", action)]));
        }
        Ok(())
    }

    /// `_start`: step 15 - a countdown, shown, said once, and logged.
    fn start(&mut self, armed: &Value, now: f64, look: &Look) -> Res<()> {
        let grace = key(armed, "grace_seconds")?;
        let until = now + number(&grace)?;
        let nonce = key(armed, "nonce")?;
        let action = key(armed, "action")?;
        self.countdown = Some(Countdown {
            nonce: nonce.clone(),
            started: now,
            last_look: now,
            until,
        });
        self.show(armed, shown_map("grace", None, Some(until)))?;
        self.said = None;
        self.line(
            "power_countdown",
            Some(py_str(&action)),
            Some(py_str(&grace)),
            look,
        );
        raise(
            look,
            GRACE,
            for_tasks(
                armed,
                map([
                    ("action", action),
                    ("until", Value::Float(until)),
                    ("nonce", nonce),
                ]),
            ),
        );
        Ok(())
    }

    /// `_finish`: step 16 - the end written first, under the lock; then the keep-awake request let go, the line, the
    /// last notice, and Windows asked, once.
    fn finish(&mut self, armed: &Value, now: f64, look: &mut Look) -> Res<()> {
        self.countdown = None;
        let Some(ended) = self
            .control
            .power_batch_finish(&key(armed, "nonce")?, now)?
        else {
            self.line(
                "power_countdown_ended",
                Some("unwritten".into()),
                None,
                look,
            );
            return Ok(());
        };
        self.forget();
        if ended != "done" {
            self.line("power_batch_ended", Some(ended), None, look);
            return Ok(());
        }
        let action = key(armed, "action")?;
        if let Some(waking) = look.waking.as_deref_mut() {
            crate::fail::quietly(|| {
                waking.let_go(look.log);
            });
        }
        self.line("power_now", Some(py_str(&action)), None, look);
        let _ =
            crate::fail::guarded(|| (look.notice)(NOW, map([("action", action.clone())]), true));
        let done = matches!(
            crate::fail::guarded(|| self.port.act(&action)),
            Ok(Value::Bool(true))
        );
        if !done {
            let error = crate::fail::guarded(|| self.port.last_error()).unwrap_or(Value::Null);
            let error = match &error {
                Value::Int(_) if !pyval::less(&error, &Value::from(0)).unwrap_or(true) => {
                    py_str(&error)
                }
                _ => "?".to_owned(),
            };
            self.line("power_failed", None, Some(error), look);
            self.control.power_refused((self.clock)())?;
            raise(look, FAILED, map([("action", action)]));
        }
        Ok(())
    }

    /// `halt(reason)`: a look that failed, or a tick that cannot look - any countdown ends, nothing is done.
    pub fn halt(&mut self, log: &dyn Fn(&str), clock: &dyn Clock) {
        if self.countdown.take().is_some() {
            line_to(
                log,
                clock,
                "power_countdown_ended",
                Some(FAILED_LOOK.into()),
                None,
            );
        }
    }

    /// `stop()`: the watcher stops - a countdown simply ends, and the file says the watcher is not watching.
    pub fn stop(&mut self, log: &dyn Fn(&str), clock: &dyn Clock) {
        let countdown = self.countdown.take();
        if countdown.is_some() {
            line_to(
                log,
                clock,
                "power_countdown_ended",
                Some(STOPPING.into()),
                None,
            );
        }
        if let Some(countdown) = countdown {
            let shown = Value::Object(shown_map("waiting", Some("watcher"), None));
            let _ = crate::fail::guarded(|| self.control.power_show(&countdown.nonce, &shown));
        }
    }

    fn stop_countdown(&mut self, reason: &str, look: &Look) {
        if self.countdown.take().is_some() {
            self.line("power_countdown_ended", Some(reason.into()), None, look);
        }
    }

    fn forget(&mut self) {
        self.seen = (Value::Null, false);
        self.said = None;
        self.shown = None;
        self.known = Value::Null;
    }

    /// `_show(armed, shown)`: what the Dashboard shows, written only when it changed for this nonce.
    fn show(&mut self, armed: &Value, shown: Map) -> Res<()> {
        let nonce = key(armed, "nonce")?;
        let mut sorted: Vec<(String, Value)> = shown
            .iter()
            .map(|(name, value)| (crate::fail::lossy(name), value.clone()))
            .collect();
        sorted.sort_by(|a, b| a.0.cmp(&b.0));
        let same = self.shown.as_ref().is_some_and(|(was, items)| {
            pyval::eq(was, &nonce)
                && items.len() == sorted.len()
                && items
                    .iter()
                    .zip(&sorted)
                    .all(|(a, b)| a.0 == b.0 && pyval::eq(&a.1, &b.1))
        });
        if !same {
            self.control.power_show(&nonce, &Value::Object(shown))?;
            self.shown = Some((nonce, sorted));
        }
        Ok(())
    }

    fn line(&self, code: &str, reason: Option<String>, detail: Option<String>, look: &Look) {
        line_to(look.log, look.clock, code, reason, detail);
    }

    /// `_paused(store, settings, managed)`: step 5 - recovery paused, or Observe only.
    fn paused(store: &Store, settings: &Value, managed: &Managed) -> Res<bool> {
        let stored = store.settings()?;
        let enabled = stored
            .get("enabled")
            .ok_or_else(|| Failed::new("KeyError", "enabled"))?;
        Ok(!pyval::truthy(enabled)
            || managed.disable_auto_resume
            || pyval::truthy(stored.get("observe_only").unwrap_or(&Value::Null))
            || matches!(field(settings, "observe_only"), Value::Bool(true)))
    }
}

/// `_raise(event, detail)`: a notice never decides the action (E11).
fn raise(look: &Look, event: &str, detail: Map) {
    let _ = crate::fail::guarded(|| (look.notice)(event, detail, false));
}

/// `_line(code, reason, detail)`: the logbook's sentence for it; a line that cannot be made is not written.
fn line_to(
    log: &dyn Fn(&str),
    clock: &dyn Clock,
    code: &str,
    reason: Option<String>,
    detail: Option<String>,
) {
    let made = render(
        &Value::Null,
        &Value::from(code),
        &reason.map_or(Value::Null, Value::from),
        &detail.map_or(Value::Null, Value::from),
        clock,
    );
    if let Ok(line) = made {
        crate::fail::quietly(|| log(&line));
    }
}

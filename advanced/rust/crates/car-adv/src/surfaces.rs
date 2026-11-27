//! `surfaces.py` (seat S7.3a): P10 - what this edition adds to the status, the tray, the diagnostics bundle, the bridge
//! and MCP. The module's docstring at the tag is the specification; every function below names the part it ports.
//!
//! * The badge (`edition`, `on`) on the status, the tray and the diagnostics bundle, codes only; the status adds the
//!   counts and the views the Advanced page and Pending read, the tray the meter, the notices and the update offer.
//! * The bridge is the Dashboard's: every `BridgeCommand` with the arguments it takes ([`ARGUMENTS`]), each answered by
//!   `crate::arming` or its card in `crate::control`.
//! * MCP is a model's: three tools that list or only ever turn something off ([`tools`]).
//!
//! What the courier's, the remote's and the saved accounts' cards reach of Windows - the Credential Manager, the
//! courier's launcher, a pairing code - is the entry points' [`World`] ([`install_world`], S7.3d); until one is
//! installed every card works over [`World::bare`], which reaches nothing real.

use std::cmp::Ordering;
use std::collections::{BTreeSet, HashMap};
use std::sync::{Arc, Mutex, OnceLock, PoisonError};
use std::time::Instant;

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;
use car_policy::classify::gates::{HELD, WAIT, decode_gates};
use car_policy::plug::Surface;

use crate::arming::{ArmRequest, KeepRequest};
use crate::control::resets::{
    self as kit, Result, arg, call, field, get, int, is, list, object, refusal, text, with,
};
use crate::engine;
use crate::runtime::Runtime;
use crate::state::Error;
use crate::vocabulary::{
    Actor, ArmingState, BridgeCommand, McpTool, Measurement, NoteCode, OffReason, Refusal, Verdict,
};

/// `BADGE_SURFACES`.
pub const BADGE_SURFACES: &[Surface] = &[Surface::Status, Surface::Tray, Surface::Diagnostics];
/// `REPORT`.
pub const REPORT: &str = "compat_report";
/// Pending's and History's rows read, and how long a conversation's kind is kept once read.
pub const ROWS_READ: i64 = 200;
pub const KIND_SECONDS: f64 = 600.0;

/// `ARGUMENTS[command]`: the arguments each bridge command takes; anything else refuses it.
pub fn arguments(command: BridgeCommand) -> &'static [&'static str] {
    use BridgeCommand as B;
    match command {
        B::AdvancedList
        | B::AdvancedDisarmAll
        | B::AdvancedRules
        | B::AdvancedSamples
        | B::AdvancedResets => &[],
        B::AdvancedWords => &["locale"],
        B::AdvancedStatement => &["capability", "locale"],
        B::AdvancedArm => &[
            "capability",
            "state",
            "revision",
            "generation",
            "engine_version",
            "warnings",
            "also",
            "keep_on",
        ],
        B::AdvancedDisarm | B::AdvancedWordings | B::AdvancedWatchLog => &["capability"],
        B::AdvancedWording => &["capability", "key", "words", "generation"],
        B::AdvancedCeiling => &["global_hourly", "generation"],
        B::Measure => &["measurement", "thread", "may_spend"],
        B::MeasureVerdict => &["measurement", "verdict", "note"],
        B::AdvancedOption => &["capability", "key", "value", "generation"],
        B::AdvancedRuleAdd => &["tag", "status_from", "status_to", "category", "generation"],
        B::AdvancedRuleRemove | B::AdvancedResetCancel | B::AdvancedResetGoOn => {
            &["rule", "generation"]
        }
        B::AdvancedKeepOn => &[
            "capability",
            "keep_on",
            "send_again",
            "generation",
            "confirmed",
        ],
        B::AdvancedSendNow | B::AdvancedHeadlessStop => &["interruption_id"],
        B::AdvancedResetAdd => &[
            "kind",
            "bucket",
            "minutes",
            "ordinal",
            "repeat",
            "ask_first",
            "thread_id",
            "words",
            "generation",
        ],
        B::AdvancedCreditNow => &["rule", "bucket", "minutes", "generation"],
        B::AdvancedKeepGoing
        | B::AdvancedPrompts
        | B::AdvancedEarlyCheck
        | B::AdvancedConversations
        | B::AdvancedApiTokenNew
        | B::AdvancedRemotePairStart
        | B::AdvancedRemotePairState
        | B::AdvancedAccount
        | B::AdvancedAccountSwitch
        | B::AdvancedAccounts
        | B::AdvancedAccountsAdd
        | B::AdvancedAccountsSave
        | B::AdvancedAccountsRead
        | B::AdvancedPython
        | B::AdvancedPythonCheck
        | B::AdvancedPythonBack
        | B::AdvancedPowerTasks
        | B::AdvancedFleet
        | B::AdvancedCourier
        | B::AdvancedFeedRefresh => &[],
        B::AdvancedKeepGoingSet => &["thread_id", "count", "generation"],
        B::AdvancedKeepGoingStop | B::AdvancedChatCancel => &["thread_id", "generation"],
        B::AdvancedPromptAdd => &[
            "thread_id",
            "words",
            "trigger",
            "at",
            "every",
            "occurrences",
            "depends",
            "generation",
            "while_running",
            "images",
        ],
        B::AdvancedPromptCancel | B::AdvancedPromptGoOn => &["prompt", "generation"],
        B::AdvancedReportBuild => &["login"],
        B::AdvancedReportSave => &["sha256", "path"],
        B::AdvancedReportCheck => &["sha256"],
        B::AdvancedReportSend => &["sha256", "writes", "word"],
        B::AdvancedReportJob => &["job"],
        B::AdvancedChatRead => &["thread_id"],
        B::AdvancedChatSend | B::AdvancedSteer => &["thread_id", "words", "generation"],
        B::AdvancedPromptFollow => &["prompt"],
        B::AdvancedApi => &["copy", "host", "copy_token"],
        B::AdvancedAccountRestart => &["now"],
        B::AdvancedAccountsDelete => &["id", "all"],
        B::AdvancedAccountsSwitch => &["id"],
        B::AdvancedPythonUse => &["version"],
        B::AdvancedPowerTasksArm => &[
            "threads",
            "action",
            "grace_minutes",
            "failed",
            "interrupted",
            "generation",
        ],
        B::AdvancedFleetSave => &["alias", "folder", "generation"],
        B::AdvancedAnalytics => &["days"],
        B::AdvancedAnalyticsCsv => &["days", "path", "replace"],
        B::AdvancedPromptsClearDone => &["prompts", "generation"],
        B::AdvancedPromptEdit => &[
            "prompt",
            "words",
            "trigger",
            "at",
            "every",
            "occurrences",
            "depends",
            "while_running",
            "generation",
            "images",
        ],
        B::AdvancedCourierSave => &[
            "channel", "url", "token", "host", "port", "user", "password", "from", "to", "pair",
        ],
        B::AdvancedCourierForget | B::AdvancedCourierTest => &["channel"],
    }
}

// ------------------------------------------------------------------ the world of the cards that reach Windows

/// What the courier's, the remote's and the accounts' cards reach of Windows; the entry points' to hand (S7.3d).
#[derive(Clone)]
pub struct World {
    /// The Credential Manager (`credentials.Secrets`' backend).
    pub backend: Arc<dyn car_platform::credman::Backend>,
    /// Telegram's pairing code (`courier.telegram.pairing_code`).
    pub code: Arc<dyn Fn() -> String + Send + Sync>,
    /// The courier started with these arguments (`courier.launch.start`).
    pub start: Arc<dyn Fn(&[&str]) -> bool + Send + Sync>,
    /// The courier run with these arguments and waited for (`courier.launch.run`).
    pub run: Arc<dyn Fn(&[&str], i64) -> Option<i32> + Send + Sync>,
    /// The resident courier running (`courier.resident.running`).
    pub running: Arc<dyn Fn() -> bool + Send + Sync>,
    /// A watcher running here.
    pub watcher: Arc<dyn Fn() -> bool + Send + Sync>,
    /// This PC's own addresses, where the entry points know them.
    pub addresses: Option<Arc<dyn Fn() -> Vec<String> + Send + Sync>>,
    /// A new local API token.
    pub token: Arc<dyn Fn() -> String + Send + Sync>,
    /// `codex/account.read(paths)`: the account signed in, as Codex says it (an app-server session of its own).
    pub account_read: Arc<dyn Fn(&car_config::Paths) -> Value + Send + Sync>,
    /// `codex/account.switch(paths)`: Codex's own sign-out and sign-in, and what it came to.
    pub account_switch: Arc<dyn Fn(&car_config::Paths) -> &'static str + Send + Sync>,
    /// `codex/restart.busy(paths)`: why Codex may not be restarted now.
    pub restart_busy: Arc<dyn Fn(&car_config::Paths) -> Vec<&'static str> + Send + Sync>,
    /// `codex/restart.restart(paths)`: (what the restart came to, how the app ended).
    pub restart_run:
        Arc<dyn Fn(&car_config::Paths) -> (&'static str, Option<&'static str>) + Send + Sync>,
    /// `threading.Thread(target=job, daemon=True).start()`; false where it could not start.
    pub spawn: Arc<dyn Fn(Box<dyn FnOnce() + Send>) -> bool + Send + Sync>,
    /// The Windows user's preferred UI languages (`GetUserPreferredUILanguages`, which `l10n` reads for `system`):
    /// none in the bare world, as car-control's system host (car-platform has no reader yet).
    pub windows_languages: Arc<dyn Fn() -> Vec<String> + Send + Sync>,
}

impl World {
    /// No entry point handed one: an empty Credential Manager of this process's own, no courier, no watcher, and
    /// no Codex asked (an account read says Codex could not be asked; a switch or a restart fails).
    pub fn bare() -> World {
        World {
            backend: Arc::new(car_platform::credman::Memory::default()),
            code: Arc::new(String::new),
            start: Arc::new(|_| false),
            run: Arc::new(|_, _| None),
            running: Arc::new(|| false),
            watcher: Arc::new(|| false),
            addresses: None,
            token: Arc::new(String::new),
            account_read: Arc::new(|_| crate::codex::account::parse(&Value::Null)),
            account_switch: Arc::new(|_| crate::codex::account::FAILED),
            restart_busy: Arc::new(|_| vec![crate::codex::restart::UNKNOWN]),
            restart_run: Arc::new(|_| (crate::codex::restart::FAILED, None)),
            spawn: Arc::new(|job| {
                std::thread::Builder::new()
                    .name("account-switch".into())
                    .spawn(job)
                    .is_ok()
            }),
            windows_languages: Arc::new(Vec::new),
        }
    }
}

static WORLD: OnceLock<World> = OnceLock::new();

/// The entry points' world, once (S7.3d).
pub fn install_world(world: World) -> bool {
    WORLD.set(world).is_ok()
}

/// The world the cards reach: the installed one, else [`World::bare`].
pub fn world() -> World {
    WORLD.get().cloned().unwrap_or_else(World::bare)
}

// ------------------------------------------------------------------ answer

/// `answer(runtime, name, facts)`: what this edition shows on surface `name`, or None for DEFER. Err is what the
/// reference lets out (the plug's hook then fails, as a Python hook that raised).
pub fn answer(runtime: &Runtime, name: Surface, facts: &Value) -> Result<Option<Value>> {
    match name {
        Surface::Diagnostics => return Ok(Some(Value::Object(diagnostics(runtime)))),
        Surface::Status => return status(runtime).map(|shown| Some(Value::Object(shown))),
        Surface::Tray => {
            let mut shown = badge(runtime);
            for part in [
                meter_view(runtime)?,
                notice_view(runtime),
                update_view(runtime),
                account_view(runtime),
                autoswitch_view(runtime),
            ] {
                shown.extend(part);
            }
            return Ok(Some(Value::Object(shown)));
        }
        _ => {}
    }
    let Value::Object(_) = facts else {
        return Ok(None);
    };
    match name {
        Surface::Bridge => bridge(runtime, &field(facts, "command"), &field(facts, "argument")),
        Surface::Mcp => mcp(runtime, facts),
        _ => Ok(None),
    }
}

// ------------------------------------------------------------------ the badge and the views

/// `badge(runtime)`: which edition this is, and how many capabilities are armed. Codes only.
pub fn badge(runtime: &Runtime) -> Map {
    let on = runtime
        .states(false, &[])
        .0
        .iter()
        .filter(|(_, state)| *state == ArmingState::Armed)
        .count();
    let mut shown = Map::new();
    shown.insert(Str::new("edition"), text("advanced"));
    shown.insert(Str::new("on"), int(on as i64));
    shown
}

fn armed(runtime: &Runtime, capability: &str) -> bool {
    runtime.states(false, &[]).get(capability) == Some(ArmingState::Armed)
}

/// `status(runtime)`.
pub fn status(runtime: &Runtime) -> Result<Map> {
    let mut shown = badge(runtime);
    shown.extend(crate::control::resets::counts(runtime));
    shown.extend(crate::control::prompts::counts(runtime));
    shown.extend(meter_view(runtime)?);
    shown.extend(feed_view(runtime));
    shown.extend(fleet_view(runtime));
    let found = runs(runtime);
    if !found.is_empty() {
        shown.insert(Str::new("runs"), Value::Array(found));
    }
    shown.extend(rows(runtime));
    shown.extend(crate::control::earlycheck::view(runtime));
    // `anchor.view(runtime)`: the stamps read only while it stands on.
    let anchored = armed(runtime, engine::anchor::CAPABILITY);
    let now = if anchored { runtime.now() } else { 0.0 };
    let stamped = |key: crate::vocabulary::OptionKey| -> Option<Value> {
        runtime
            .state
            .stamped(&text(engine::anchor::CAPABILITY), &text(key.as_str()))
            .ok()
    };
    if let Value::Object(found) = engine::anchor::view(anchored, &stamped, now) {
        shown.extend(found);
    }
    let supervised = armed(runtime, engine::supervise::CAPABILITY);
    let there = |pid: i64| {
        u32::try_from(pid).is_ok_and(|pid| car_platform::kernel::process_identity(pid).is_ok())
    };
    if let Value::Object(found) = engine::supervise::view(
        supervised,
        std::path::Path::new(&runtime.paths.logs_dir),
        &there,
    ) {
        shown.extend(found);
    }
    Ok(shown)
}

/// A capability's code, downcast to its own type, and `act` on it; None where it cannot be made or is not that type.
fn code_of<T: 'static, R>(
    runtime: &Runtime,
    capability: &str,
    act: impl FnOnce(&mut T) -> R,
) -> Option<R> {
    let definition = runtime.registry.get(capability)?;
    runtime
        .call(definition, |code| {
            Ok(code
                .as_any()
                .and_then(|any| any.downcast_mut::<T>())
                .map(act))
        })
        .ok()
        .flatten()
}

/// `meter_view(runtime)`: the usage meter's last reading, for the tooltip and the popup - only while the meter is on.
pub fn meter_view(runtime: &Runtime) -> Result<Map> {
    use engine::usage::{METER, NOTICE_FOR, PAUSE, WRAP_UP};
    let mut answer = Map::new();
    let states = runtime.states(false, &[]);
    if states.get(METER) != Some(ArmingState::Armed) {
        return Ok(answer);
    }
    let read = || -> Result<_> {
        let rows = kit::state(runtime, "meter")?.meter()?;
        let now = runtime.now();
        let mut options = Vec::new();
        for capability in [METER, WRAP_UP, PAUSE] {
            options.push((
                capability,
                kit::state(runtime, "options")?.options(&text(capability))?,
            ));
        }
        Ok((rows, now, options))
    };
    let Ok((mut rows, now, options)) = read() else {
        return Ok(answer);
    };
    if rows.is_empty() {
        return Ok(answer);
    }
    let option_of = |capability: &str| -> &Map {
        &options
            .iter()
            .find(|(id, _)| *id == capability)
            .expect("the three stages")
            .1
    };
    let on: Vec<(&str, Vec<i64>)> = [METER, WRAP_UP, PAUSE]
        .into_iter()
        .map(|capability| (capability, engine::usage::acting(option_of(capability))))
        .collect();
    let acting_of = |capability: &str| -> &Vec<i64> {
        &on.iter()
            .find(|(id, _)| *id == capability)
            .expect("stage")
            .1
    };
    let current: Vec<(Value, Value)> = match current_windows(runtime, &rows) {
        Some(found) => found,
        None => rows.iter().map(|(key, _)| key.clone()).collect(),
    };
    rows.sort_by(|(a, _), (b, _)| {
        pyval::order(&a.0, &b.0)
            .ok()
            .flatten()
            .unwrap_or(Ordering::Equal)
            .then_with(|| {
                pyval::order(&a.1, &b.1)
                    .ok()
                    .flatten()
                    .unwrap_or(Ordering::Equal)
            })
    });
    let (mut shown, mut notices) = (Vec::new(), Vec::new());
    for ((bucket, minutes), row) in &rows {
        let acts = current
            .iter()
            .any(|(b, m)| pyval::eq(b, bucket) && pyval::eq(m, minutes));
        let mut band = "none";
        for (capability, word) in [(PAUSE, "pause"), (WRAP_UP, "wrap_up"), (METER, "warn")] {
            let in_on =
                kit::small(minutes).is_some_and(|minutes| acting_of(capability).contains(&minutes));
            if acts && in_on && states.get(capability) == Some(ArmingState::Armed) {
                let threshold = engine::usage::percent(option_of(capability), capability, minutes);
                let reached = engine::usage::reached(row, threshold.as_ref(), now)
                    .map_err(|raised| Error::python(kit::class_of(&raised.class), ""))?;
                if reached {
                    band = word;
                    break;
                }
            }
        }
        shown.push(object(vec![
            ("bucket", bucket.clone()),
            ("window_minutes", minutes.clone()),
            ("used_percent", get(row, "used_percent")),
            ("reset_at", get(row, "reset_at")),
            ("band", text(band)),
        ]));
        let warned = get(row, "warned_at");
        let reset = get(row, "reset_at");
        let recent =
            kit::number_of(&warned).is_some_and(|at| 0.0 <= now - at && now - at < NOTICE_FOR);
        if acts
            && !matches!(warned, Value::Null)
            && recent
            && pyval::eq(&get(row, "warned_reset_at"), &reset)
            && !matches!(reset, Value::Null)
        {
            let key = format!(
                "{}:{}:{}",
                crate::state::py::py_str(bucket),
                kit::number_of(minutes).map_or(0, |at| at.trunc() as i64),
                kit::number_of(&reset).map_or(0, |at| at.trunc() as i64)
            );
            notices.push(object(vec![
                ("key", text(&key)),
                ("window_minutes", minutes.clone()),
                ("used_percent", get(row, "used_percent")),
                ("reset_at", reset),
                ("kind", text("warn")),
            ]));
        }
    }
    if states.get(PAUSE) == Some(ArmingState::Armed) {
        let said = code_of(runtime, PAUSE, |stop: &mut engine::usagestop::UsageStop| {
            stop.with(|inner| inner.notices(now))
        })
        .unwrap_or_default();
        for notice in said {
            notices.push(with(notice, vec![("used_percent", Value::Null)]));
        }
    }
    let read_at: Vec<Value> = rows.iter().map(|(_, row)| get(row, "read_at")).collect();
    let refs: Vec<&Value> = read_at.iter().collect();
    let newest = pyval::max(&refs)
        .cloned()
        .map_err(|class| Error::python(class, ""))?;
    answer.insert(
        Str::new("meter"),
        object(vec![
            ("read_at", newest),
            ("windows", Value::Array(shown)),
            ("notices", Value::Array(notices)),
        ]),
    );
    Ok(answer)
}

/// `{(row["bucket"], row["minutes"]) for row in usage.of_account(rows, paths, state.stamped)}`; None where it raised.
fn current_windows(
    runtime: &Runtime,
    rows: &[((Value, Value), crate::state::sql::Row)],
) -> Option<Vec<(Value, Value)>> {
    let binding = crate::capabilities::Binding {
        runtime: runtime.me.borrow().clone(),
        capability: engine::usage::METER.to_owned(),
    };
    let bound = engine::usage::Bound::of(binding);
    let world = engine::usage::World::installed();
    let keyed: Vec<_> = rows
        .iter()
        .map(|(key, row)| (key.clone(), row.clone()))
        .collect();
    let kept = engine::usage::of_account(&world, &keyed, &runtime.paths, Some(&bound)).ok()?;
    Some(
        kept.iter()
            .map(|row| (get(row, "bucket"), get(row, "minutes")))
            .collect(),
    )
}

/// `notice_view(runtime)`: {"notice": {"open_codex": true, "chat": true}}, each only while it holds; {} otherwise.
pub fn notice_view(runtime: &Runtime) -> Map {
    let mut found = Map::new();
    let open = crate::control::opencodex::CAPABILITY;
    if runtime.registry.get(open).is_some() && armed(runtime, open) {
        let available = runtime.action(open).ok().and_then(|cell| {
            let mut code = cell.try_borrow_mut().ok()?;
            let button = code
                .as_any()?
                .downcast_mut::<crate::control::opencodex::OpenCodexButton>()?;
            Some(button.available())
        });
        if available == Some(true) {
            found.insert(Str::new("open_codex"), Value::Bool(true));
        }
    }
    let chat = engine::chat::CAPABILITY;
    if runtime.registry.get(chat).is_some() && armed(runtime, chat) {
        found.insert(Str::new("chat"), Value::Bool(true));
    }
    let mut answer = Map::new();
    if !found.is_empty() {
        answer.insert(Str::new("notice"), Value::Object(found));
    }
    answer
}

/// `update_view(runtime)`: what the weekly update check offers, while it stands on and offered one.
pub fn update_view(runtime: &Runtime) -> Map {
    let capability = engine::updatecheck::CAPABILITY;
    let mut answer = Map::new();
    if runtime.registry.get(capability).is_none() || !armed(runtime, capability) {
        return answer;
    }
    let Some(Some((version, prerelease))) = code_of(
        runtime,
        capability,
        |code: &mut engine::updatecheck::IdleUpdateCheck| code.offered(),
    ) else {
        return answer;
    };
    let notice = object(vec![
        ("key", text(&format!("update:{version}"))),
        ("version", text(&version)),
        ("prerelease", Value::Bool(prerelease)),
    ]);
    answer.insert(
        Str::new("update"),
        object(vec![("notices", Value::Array(vec![notice]))]),
    );
    answer
}

/// `{name: {"notices": [dict(found)]}}` for a code's notice, while its capability stands on.
fn notices_of(runtime: &Runtime, capability: &str, name: &str, found: Option<Value>) -> Map {
    let mut answer = Map::new();
    if runtime.registry.get(capability).is_none() || !armed(runtime, capability) {
        return answer;
    }
    if let Some(found @ Value::Object(_)) = found {
        if pyval::truthy(&found) {
            answer.insert(
                Str::new(name),
                object(vec![("notices", Value::Array(vec![found]))]),
            );
        }
    }
    answer
}

/// `autoswitch_view(runtime)`.
pub fn autoswitch_view(runtime: &Runtime) -> Map {
    let capability = engine::autoswitch::CAPABILITY;
    if runtime.registry.get(capability).is_none() || !armed(runtime, capability) {
        return Map::new();
    }
    let found = code_of(
        runtime,
        capability,
        |code: &mut engine::autoswitch::AutoSwitch| code.notice_view(),
    );
    notices_of(runtime, capability, "autoswitch", found)
}

/// `account_view(runtime)`.
pub fn account_view(runtime: &Runtime) -> Map {
    let capability = engine::account::CAPABILITY;
    if runtime.registry.get(capability).is_none() || !armed(runtime, capability) {
        return Map::new();
    }
    let found = code_of(
        runtime,
        capability,
        |code: &mut engine::account::AccountWatch| code.notice_view(),
    );
    notices_of(runtime, capability, "account", found)
}

/// `diagnostics(runtime)`: the badge, the samples, the watched capabilities' log and the automatic check's grade.
pub fn diagnostics(runtime: &Runtime) -> Map {
    let mut shown = badge(runtime);
    let found = runtime.arming().samples_view();
    let samples = field(&found, "samples");
    if pyval::truthy(&samples) {
        shown.insert(Str::new("samples"), samples);
    }
    let watch = crate::watchlog::exported(&runtime.state, runtime.now()).unwrap_or_default();
    if !watch.is_empty() {
        shown.insert(
            Str::new("watch"),
            Value::Array(watch.into_iter().map(Value::Object).collect()),
        );
    }
    if let Ok(Some(check)) =
        crate::autocheck::diagnostics(std::path::Path::new(&runtime.paths.advanced_dir))
    {
        if pyval::truthy(&check) {
            shown.insert(Str::new("auto_check"), check);
        }
    }
    shown
}

/// `feed_view(runtime)`: what OpenAI's status page last said, only while something is wrong or it could not be read.
pub fn feed_view(runtime: &Runtime) -> Map {
    use crate::courier::feed;
    let mut answer = Map::new();
    if runtime.registry.get(feed::CAPABILITY).is_none() || !armed(runtime, feed::CAPABILITY) {
        return answer;
    }
    let Ok(row) = kit::state(runtime, "feed").and_then(feed::read) else {
        return answer;
    };
    let row = row.map_or(Value::Null, Value::Object);
    if feed::unreached(&row) {
        answer.insert(
            Str::new("feed"),
            object(vec![
                ("word", Value::Null),
                ("codex_word", Value::Null),
                ("incidents", Value::Null),
                ("checked_at", field(&row, "checked_at")),
                ("reached", Value::Bool(false)),
            ]),
        );
        return answer;
    }
    let wrong = |name: &str| kit::among(&field(&row, name), &["degraded", "outage"]);
    if !pyval::truthy(&row) || !(wrong("word") || wrong("codex_word")) {
        return answer;
    }
    answer.insert(
        Str::new("feed"),
        object(vec![
            ("word", field(&row, "word")),
            ("codex_word", field(&row, "codex_word")),
            ("incidents", field(&row, "incidents")),
            ("checked_at", field(&row, "checked_at")),
            ("reached", Value::Bool(true)),
        ]),
    );
    answer
}

/// `fleet_view(runtime)`: {"fleet_on": True} while See your other PCs is on.
pub fn fleet_view(runtime: &Runtime) -> Map {
    let mut answer = Map::new();
    let capability = engine::fleet::CAPABILITY;
    if runtime.registry.get(capability).is_some() && armed(runtime, capability) {
        answer.insert(Str::new("fleet_on"), Value::Bool(true));
    }
    answer
}

/// `headless_stop(runtime, interruption_id)`: advanced-headless-stop.
pub fn headless_stop(runtime: &Runtime, interruption_id: &Value) -> Result<Value> {
    if !ids::is_interruption_id(interruption_id, false) {
        return Ok(refusal(Refusal::InvalidRequest));
    }
    let at = Value::Float(runtime.now());
    let stopped = match call(
        runtime,
        "run_stop",
        &[interruption_id.clone()],
        &[("at", at)],
    ) {
        Ok(stopped) => stopped,
        Err(error) if error.is_state() => return Ok(refusal(Refusal::StateUnavailable)),
        Err(error) => return Err(error),
    };
    if !pyval::truthy(&stopped) {
        return Ok(refusal(Refusal::NotOn));
    }
    kit::wake(runtime);
    Ok(object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
    ]))
}

/// `runs(runtime)`: the turns run here now, as Pending shows them.
pub fn runs(runtime: &Runtime) -> Vec<Value> {
    let Ok(found) = call(runtime, "runs", &[], &[("live", Value::Bool(true))]) else {
        return Vec::new();
    };
    list(&found)
        .iter()
        .map(|row| {
            object(vec![
                ("interruption_id", get(row, "interruption_id")),
                ("capability", get(row, "capability")),
                ("started_at", get(row, "started_at")),
                ("ends_by", get(row, "ends_by")),
                (
                    "stopping",
                    Value::Bool(!matches!(get(row, "stop_requested_at"), Value::Null)),
                ),
            ])
        })
        .collect()
}

// ------------------------------------------------------------------ Pending's and History's rows

/// `_KINDS`: {(Codex home, conversation id): (its kind or None, when it was read)}, for the life of the process.
type Kinds = HashMap<(String, String), (Option<&'static str>, f64)>;

fn kinds() -> &'static Mutex<Kinds> {
    static KINDS: OnceLock<Mutex<Kinds>> = OnceLock::new();
    KINDS.get_or_init(|| Mutex::new(HashMap::new()))
}

fn monotonic() -> f64 {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_secs_f64()
}

/// `rows(runtime)`: what Pending and History say beside a row this edition had a hand in, keyed by interruption id.
pub fn rows(runtime: &Runtime) -> Map {
    /// `registry.MODEL_FALLBACK.id`, `OTHER_SESSIONS.id`, `COMPACT_CONTINUE.id`.
    mod capability {
        pub const MODEL_FALLBACK: &str = "model_fallback";
        pub const OTHER_SESSIONS: &str = "other_sessions";
        pub const COMPACT_CONTINUE: &str = "compact_continue";
    }
    let mut shown = Map::new();
    let states = runtime.states(false, &[]);
    let owed: Vec<Value> = call(
        runtime,
        "runs_owed",
        &[text(capability::MODEL_FALLBACK)],
        &[],
    )
    .map(|found| {
        list(&found)
            .iter()
            .filter(|row| !matches!(get(row, "ended_at"), Value::Null))
            .map(|row| get(row, "interruption_id"))
            .collect()
    })
    .unwrap_or_default();
    if !owed.is_empty() {
        shown.insert(Str::new("model_not_restored"), Value::Array(owed));
    }
    let silent = silent(runtime);
    if !silent.is_empty() {
        shown.insert(Str::new("silent"), Value::Array(silent));
    }
    let kinds_wanted = states.state_of(capability::OTHER_SESSIONS) != ArmingState::Off;
    let compact_wanted = states.state_of(capability::COMPACT_CONTINUE) == ArmingState::Armed;
    if !(kinds_wanted || compact_wanted) {
        return shown;
    }
    let Ok(listed) = listed(runtime) else {
        return shown;
    };
    if kinds_wanted {
        let found = (|| -> Option<Map> {
            let home = kit::codex_home(runtime).ok()?;
            let source = car_codex::source::LocalSource::new(kit::codex_os(), &home, None).ok()?;
            let mut found = Map::new();
            for row in &listed {
                if pyval::truthy(&get(row, "home_key")) {
                    continue;
                }
                let kind = kind_of(&source, &get(row, "thread_id"))?;
                if let Some(kind) = kind {
                    let key = crate::state::py::py_str(&get(row, "interruption_id"));
                    found.insert(Str::new(&key), text(kind));
                }
            }
            Some(found)
        })()
        .unwrap_or_default();
        if !found.is_empty() {
            shown.insert(Str::new("kinds"), Value::Object(found));
        }
    }
    if compact_wanted {
        let compacting: Vec<Value> = listed
            .iter()
            .filter(|row| compacting(row))
            .map(|row| get(row, "interruption_id"))
            .collect();
        if !compacting.is_empty() {
            shown.insert(Str::new("compacting"), Value::Array(compacting));
        }
    }
    shown
}

/// `_silent(runtime, store)`: the interruptions a turn run here continued with no words, proved by id.
fn silent(runtime: &Runtime) -> Vec<Value> {
    let Ok(found) = call(
        runtime,
        "runs",
        &[],
        &[("live", Value::Bool(false)), ("limit", int(ROWS_READ))],
    ) else {
        return Vec::new();
    };
    let keys: Vec<Value> = list(&found)
        .iter()
        .filter(|row| {
            kit::among(
                &get(row, "capability"),
                &["headless_run", "compact_continue"],
            ) && !matches!(get(row, "ended_at"), Value::Null)
        })
        .map(|row| get(row, "interruption_id"))
        .collect();
    if keys.is_empty() {
        return Vec::new();
    }
    let Ok(store) = kit::core(runtime) else {
        return Vec::new();
    };
    let mut proved = Vec::new();
    for key in keys {
        let Some(text_key) = (match &key {
            Value::Str(text) => text.as_str().map(str::to_owned),
            _ => None,
        }) else {
            return Vec::new();
        };
        match store.get(&text_key) {
            Ok(Some(row)) => {
                if is(
                    &get(&row, "recovery_client_id"),
                    &ids::continuation_client_id(&text_key),
                ) {
                    proved.push(key);
                }
            }
            Ok(None) => {}
            Err(_) => return Vec::new(),
        }
    }
    proved
}

/// `_compacting(row)`: a full conversation compact_continue holds for the person's /compact.
fn compacting(row: &Map) -> bool {
    if !is(&get(row, "category"), engine::compact::KIND)
        || !kit::among(
            &get(row, "state"),
            car_machine::vocab_gen::domain_states::WAITING,
        )
        || !pyval::truthy(&get(row, "gate_eval"))
    {
        return false;
    }
    decode_gates(&get(row, "gate_eval"))
        .get("thread_available")
        .cloned()
        == Some((WAIT.to_owned(), HELD.to_owned()))
}

/// `_listed(runtime, store)`: the records Pending and History list, each once.
fn listed(runtime: &Runtime) -> Result<Vec<Map>> {
    let store = kit::core(runtime)?;
    let failed = |_| Error::state("cannot read core's state");
    let mut found = store.pending().map_err(failed)?;
    found.extend(store.history(false, ROWS_READ).map_err(failed)?);
    let mut seen: Vec<Value> = Vec::new();
    let mut once = Vec::new();
    for row in found {
        let key = get(&row, "interruption_id");
        if !seen.iter().any(|each| pyval::eq(each, &key)) {
            seen.push(key);
            once.push(row);
        }
    }
    Ok(once)
}

/// `_kind(source, thread_id)`: "cli" or "ide" for a conversation of a terminal's Codex TUI or of VS Code, kept
/// KIND_SECONDS; Err (None) where it cannot be read.
fn kind_of(
    source: &car_codex::source::LocalSource,
    thread: &Value,
) -> Option<Option<&'static str>> {
    let thread = match thread {
        Value::Str(text) => text.as_str()?.to_owned(),
        _ => return None,
    };
    let key = (source.home.clone(), thread.clone());
    let now = monotonic();
    if let Some((kind, at)) = kinds()
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .get(&key)
    {
        if 0.0 <= now - at && now - at < KIND_SECONDS {
            return Some(*kind);
        }
    }
    let mut found = None;
    if !source.taken(&thread, &BTreeSet::new(), None).ok()? {
        for kind in ["cli", "ide"] {
            if source
                .taken(&thread, &BTreeSet::from([kind.to_owned()]), None)
                .ok()?
            {
                found = Some(kind);
                break;
            }
        }
    }
    let mut held = kinds().lock().unwrap_or_else(PoisonError::into_inner);
    if held.len() > 4096 {
        held.clear();
    }
    held.insert(key, (found, now));
    Some(found)
}

// ------------------------------------------------------------------ the Dashboard

/// `_locale(asked)`: the Interface language the window names, else the one this process resolves to.
fn locale(asked: &Value) -> &'static str {
    let environ = |name: &str| std::env::var(name).ok();
    let languages = world().windows_languages;
    let windows = || languages();
    match asked {
        Value::Str(text) if !text.is_empty() => {
            car_words::l10n::resolve(text.as_str(), &environ, &windows)
        }
        _ => car_words::l10n::current(&environ, &windows),
    }
}

fn dashboard() -> Value {
    text(Actor::Dashboard.as_str())
}

/// `bridge(runtime, command, argument)`.
pub fn bridge(runtime: &Runtime, command: &Value, argument: &Value) -> Result<Option<Value>> {
    let Some(command) = (match command {
        Value::Str(text) => text.as_str().and_then(BridgeCommand::parse),
        _ => None,
    }) else {
        return Ok(None);
    };
    let Value::Object(argument) = argument else {
        return Ok(None);
    };
    if unported(command) {
        return Ok(None);
    }
    let allowed = arguments(command);
    if argument
        .keys()
        .any(|key| !key.as_str().is_some_and(|key| allowed.contains(&key)))
    {
        return Ok(Some(refusal(Refusal::InvalidRequest)));
    }
    Ok(Some(dispatch(runtime, command, argument)?))
}

/// The commands whose cards are not ported yet (`control/autoswitch`, `control/powertasks`, `control/analytics`):
/// passed over, as the tag's `UNANSWERED` passes a command whose card is not built (rust/GROUNDWORK.md, "Seat S7.3a").
pub fn unported(command: BridgeCommand) -> bool {
    use BridgeCommand as B;
    matches!(
        command,
        B::AdvancedAccounts
            | B::AdvancedAccountsAdd
            | B::AdvancedAccountsSave
            | B::AdvancedAccountsRead
            | B::AdvancedAccountsSwitch
            | B::AdvancedAccountsDelete
            | B::AdvancedPowerTasks
            | B::AdvancedPowerTasksArm
            | B::AdvancedAnalytics
            | B::AdvancedAnalyticsCsv
    )
}

fn dispatch(runtime: &Runtime, command: BridgeCommand, argument: &Map) -> Result<Value> {
    use crate::control as card;
    use BridgeCommand as B;
    let a = |name: &str| arg(argument, name);
    let arming = runtime.arming();
    let world = world();
    let secrets = crate::credentials::Secrets::new(&runtime.registry, world.backend.clone());
    let seams = card::courier::Seams {
        code: world.code.as_ref(),
        start: world.start.as_ref(),
        run: world.run.as_ref(),
    };
    let card_seams = card::remote::CardSeams {
        running: world.running.as_ref(),
        watcher: world.watcher.as_ref(),
        addresses: world
            .addresses
            .as_deref()
            .map(|found| found as &dyn Fn() -> Vec<String>),
        token: world.token.as_ref(),
    };
    Ok(match command {
        B::AdvancedReportBuild
        | B::AdvancedReportSave
        | B::AdvancedReportCheck
        | B::AdvancedReportSend
        | B::AdvancedReportJob => report(runtime, command, &Value::Object(argument.clone())),
        B::AdvancedList => with(arming.listing(), vec![("done", Value::Bool(true))]),
        B::AdvancedWords => {
            let locale = locale(&a("locale"));
            let words = runtime
                .arming()
                .catalogs()
                .words(Some(locale))
                .map_err(|_| Error::python("UnicodeDecodeError", "a catalog could not be read"))?;
            let words = Value::Object(
                words
                    .into_iter()
                    .map(|(key, value)| (Str::new(&key), text(&value)))
                    .collect(),
            );
            object(vec![
                ("done", Value::Bool(true)),
                ("locale", text(locale)),
                ("words", words),
            ])
        }
        B::AdvancedStatement => {
            let capability = a("capability");
            let definition = match &capability {
                Value::Str(text) => text.as_str().and_then(|id| runtime.registry.get(id)),
                _ => None,
            };
            let Some(definition) = definition else {
                return Ok(refusal(Refusal::UnknownCapability));
            };
            let locale = locale(&a("locale"));
            let statement = arming
                .statement(definition, Some(locale))
                .map_err(|_| Error::python("UnicodeDecodeError", "a catalog could not be read"))?;
            with(statement, vec![("done", Value::Bool(true))])
        }
        B::AdvancedArm => arming
            .arm(&ArmRequest {
                capability: a("capability"),
                state: a("state"),
                revision: a("revision"),
                generation: a("generation"),
                acknowledged_version: a("engine_version"),
                warnings: a("warnings"),
                also: a("also"),
                keep_on: argument
                    .get("keep_on")
                    .cloned()
                    .unwrap_or(Value::Bool(false)),
                actor: dashboard(),
            })
            .map_err(|_| Error::python("UnicodeDecodeError", "a catalog could not be read"))?,
        B::AdvancedDisarm => arming.disarm(&a("capability"), &dashboard()),
        B::AdvancedWordings => arming.wordings_view(&a("capability")),
        B::AdvancedWording => arming.set_wording(
            &a("capability"),
            &a("key"),
            &a("words"),
            &a("generation"),
            &dashboard(),
        ),
        B::AdvancedDisarmAll => arming.all_off(&dashboard()),
        B::Measure => measure(
            runtime,
            &a("measurement"),
            &a("thread"),
            argument
                .get("may_spend")
                .cloned()
                .unwrap_or(Value::Bool(false)),
        ),
        B::MeasureVerdict => measure_verdict(runtime, &a("measurement"), &a("verdict"), &a("note")),
        B::AdvancedOption => arming.set_option(
            &a("capability"),
            &a("key"),
            &a("value"),
            &a("generation"),
            &dashboard(),
        ),
        B::AdvancedRules => arming.rules_view(),
        B::AdvancedRuleAdd => arming.add_rule(
            &a("tag"),
            &a("status_from"),
            &a("status_to"),
            &a("category"),
            &a("generation"),
            &dashboard(),
        ),
        B::AdvancedRuleRemove => arming.remove_rule(&a("rule"), &a("generation"), &dashboard()),
        B::AdvancedSamples => arming.samples_view(),
        B::AdvancedSendNow => card::sendnow::request(runtime, &a("interruption_id"))?,
        B::AdvancedHeadlessStop => headless_stop(runtime, &a("interruption_id"))?,
        B::AdvancedEarlyCheck => card::earlycheck::check(runtime),
        B::AdvancedChatRead => card::chat::view(runtime, &a("thread_id"))?,
        B::AdvancedChatSend => card::chat::add(runtime, argument)?,
        B::AdvancedChatCancel => card::chat::cancel(runtime, argument)?,
        B::AdvancedConversations => card::conversations::view(runtime)?,
        B::AdvancedWatchLog => Value::Object(crate::watchlog::view(
            &runtime.state,
            &a("capability"),
            runtime.now(),
        )?),
        B::AdvancedResets => card::resets::view(runtime),
        B::AdvancedResetAdd => card::resets::add(runtime, argument)?,
        B::AdvancedResetCancel => card::resets::cancel(runtime, &a("rule"), &a("generation"))?,
        B::AdvancedResetGoOn => card::resets::go_on(runtime, &a("rule"), &a("generation"))?,
        B::AdvancedCreditNow => card::resets::credit_now(runtime, argument)?,
        B::AdvancedSteer => card::steer::request(runtime, argument)?,
        B::AdvancedPrompts => card::prompts::view(runtime),
        B::AdvancedPromptAdd => card::prompts::add(runtime, argument)?,
        B::AdvancedPromptCancel => card::prompts::cancel(runtime, &a("prompt"), &a("generation"))?,
        B::AdvancedPromptsClearDone => card::prompts::clear_done(runtime, argument)?,
        B::AdvancedPromptEdit => card::prompts::edit(runtime, argument)?,
        B::AdvancedPromptFollow => card::follow::view(runtime, &a("prompt"), None)?,
        B::AdvancedPromptGoOn => card::prompts::go_on(runtime, &a("prompt"), &a("generation"))?,
        B::AdvancedCourier => card::courier::view(runtime, &secrets),
        B::AdvancedCourierSave => {
            card::courier::save(runtime, &Value::Object(argument.clone()), &secrets, &seams)
        }
        B::AdvancedCourierForget => card::courier::forget(runtime, &a("channel"), &secrets),
        B::AdvancedCourierTest => card::courier::test(runtime, &a("channel"), &secrets, &seams),
        B::AdvancedFeedRefresh => card::courier::feed_refresh(runtime, &seams),
        B::AdvancedKeepGoing => card::keepgoing::view(runtime)?,
        B::AdvancedKeepGoingSet => card::keepgoing::set_one(runtime, argument)?,
        B::AdvancedKeepGoingStop => card::keepgoing::stop(runtime, argument)?,
        B::AdvancedAccount => card::account::view(runtime)?,
        B::AdvancedAccountSwitch => card::account::switch(runtime)?,
        B::AdvancedAccountRestart => card::account::restart(runtime, argument)?,
        // python_choice (D8, Q1 (a)): never offered and no choice ever recorded, so each answers as the tag's does
        // for a capability that does not stand: not_on.
        B::AdvancedPython
        | B::AdvancedPythonCheck
        | B::AdvancedPythonUse
        | B::AdvancedPythonBack => refusal(Refusal::NotOn),
        B::AdvancedFleet => card::fleet::view(runtime)?,
        B::AdvancedFleetSave => {
            card::fleet::save(runtime, &a("alias"), &a("folder"), &a("generation"))?
        }
        B::AdvancedRemotePairStart => {
            card::remote::pair_start(runtime, &secrets, world.code.as_ref(), world.start.as_ref())
        }
        B::AdvancedRemotePairState => card::remote::pair_state(runtime, &secrets, &card_seams),
        B::AdvancedApi => card::remote::api_view(
            runtime,
            &argument.get("copy").cloned().unwrap_or(Value::Bool(false)),
            &a("host"),
            &argument
                .get("copy_token")
                .cloned()
                .unwrap_or(Value::Bool(false)),
            &secrets,
            &card_seams,
        ),
        B::AdvancedApiTokenNew => card::remote::api_token_new(runtime, &secrets, &card_seams),
        B::AdvancedKeepOn => arming.set_keep_on(&KeepRequest {
            capability: a("capability"),
            keep_on: a("keep_on"),
            send_again: argument
                .get("send_again")
                .cloned()
                .unwrap_or(Value::Bool(false)),
            generation: a("generation"),
            confirmed: a("confirmed"),
            actor: dashboard(),
        }),
        B::AdvancedCeiling => {
            arming.set_global_hourly(&a("global_hourly"), &a("generation"), &dashboard())
        }
        B::AdvancedAccounts
        | B::AdvancedAccountsAdd
        | B::AdvancedAccountsSave
        | B::AdvancedAccountsRead
        | B::AdvancedAccountsSwitch
        | B::AdvancedAccountsDelete
        | B::AdvancedPowerTasks
        | B::AdvancedPowerTasksArm
        | B::AdvancedAnalytics
        | B::AdvancedAnalyticsCsv => unreachable!("passed over before"),
    })
}

/// `report(runtime, command, argument)`: one of the compatibility report's commands, put to the action's own code.
fn report(runtime: &Runtime, command: BridgeCommand, argument: &Value) -> Value {
    let Some(definition) = runtime.registry.get(REPORT) else {
        return refusal(Refusal::UnknownCapability);
    };
    let answered = (|| -> std::result::Result<Value, ()> {
        let cell = runtime.action(REPORT).map_err(|_| ())?;
        let flow = {
            let mut code = cell.try_borrow_mut().map_err(|_| ())?;
            let any = code.as_any().ok_or(())?;
            any.downcast_mut::<crate::capabilities::report::ReportCode>()
                .ok_or(())?
                .flow()
                .clone()
        };
        let shared = runtime.me.borrow().upgrade().ok_or(())?;
        let shared: Arc<dyn crate::report::seam::Runtime> = shared;
        let definition = Arc::new(definition.clone());
        flow.answer(&shared, &definition, command.as_str(), argument)
            .map_err(|_| ())
    })();
    match answered {
        Ok(found) => found,
        Err(()) => {
            let _ = runtime.arming().trip(REPORT, OffReason::HookException);
            refusal(Refusal::StateUnavailable)
        }
    }
}

/// `measure(runtime, measurement, thread, may_spend)`: one measurement the person named. Running it is S7.4's
/// (`runtime::measurement`): until then the run raises, which the reference answers as STATE_UNAVAILABLE.
fn measure(runtime: &Runtime, measurement: &Value, thread: &Value, may_spend: Value) -> Value {
    let _ = runtime;
    let known = matches!(measurement, Value::Str(text) if text.as_str().and_then(Measurement::parse).is_some());
    if !known {
        return refusal(Refusal::InvalidRequest);
    }
    if !(matches!(thread, Value::Null | Value::Str(_))) || !matches!(may_spend, Value::Bool(_)) {
        return refusal(Refusal::InvalidRequest);
    }
    refusal(Refusal::StateUnavailable)
}

/// `measure_verdict(runtime, measurement, verdict, note)`: a person's completion of a blocked measurement (S7.4's run).
fn measure_verdict(runtime: &Runtime, measurement: &Value, verdict: &Value, note: &Value) -> Value {
    let _ = runtime;
    let word = |value: &Value| match value {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    };
    let which = word(measurement).and_then(|text| Measurement::parse(&text));
    let chosen = word(verdict).and_then(|text| Verdict::parse(&text));
    let code = word(note).and_then(|text| NoteCode::parse(&text));
    let (Some(_), Some(chosen), Some(_)) = (which, chosen, code) else {
        return refusal(Refusal::InvalidRequest);
    };
    if !matches!(chosen, Verdict::Pass | Verdict::Fail) {
        return refusal(Refusal::InvalidRequest);
    }
    refusal(Refusal::StateUnavailable)
}

// ------------------------------------------------------------------ a model

const OFF_ONLY: &str = "Turning a capability on is not something any tool does: the user does it in the \
Codex Auto Resume Dashboard, after reading what it does.";

/// `TOOLS`: the three tools, as `tools/list` shows them after core's.
pub fn tools() -> Value {
    let no_arguments = || {
        object(vec![
            ("type", text("object")),
            ("properties", Value::Object(Map::new())),
            ("additionalProperties", Value::Bool(false)),
        ])
    };
    let hints = |read_only: bool| {
        object(vec![
            ("readOnlyHint", Value::Bool(read_only)),
            ("destructiveHint", Value::Bool(false)),
            ("idempotentHint", Value::Bool(true)),
            ("openWorldHint", Value::Bool(false)),
        ])
    };
    Value::Array(vec![
        object(vec![
            ("name", text(McpTool::ListAdvancedCapabilities.as_str())),
            ("title", text("List advanced capabilities")),
            (
                "description",
                text(&format!(
                    "The advanced edition's capabilities, each with its id, whether it is on, watched or off, since \
when and why, the standards it departs from, the choices set for it and whether it is kept on, and sends again when \
unsure. Read-only. {OFF_ONLY}"
                )),
            ),
            ("inputSchema", no_arguments()),
            ("annotations", hints(true)),
        ]),
        object(vec![
            ("name", text(McpTool::DisarmAdvancedCapability.as_str())),
            ("title", text("Turn one advanced capability off")),
            (
                "description",
                text(&format!(
                    "Turn off one advanced capability, by the exact id list_advanced_capabilities gives. Only ever \
reduces automation, so it needs no confirmation. {OFF_ONLY}"
                )),
            ),
            (
                "inputSchema",
                object(vec![
                    ("type", text("object")),
                    ("additionalProperties", Value::Bool(false)),
                    ("required", Value::Array(vec![text("capability")])),
                    (
                        "properties",
                        object(vec![(
                            "capability",
                            object(vec![
                                ("type", text("string")),
                                ("description", text("The capability's exact id.")),
                            ]),
                        )]),
                    ),
                ]),
            ),
            ("annotations", hints(false)),
        ]),
        object(vec![
            ("name", text(McpTool::DisarmAllAdvanced.as_str())),
            ("title", text("Turn all advanced features off")),
            (
                "description",
                text(&format!(
                    "Turn off every advanced capability at once. Only ever reduces automation, so it needs no \
confirmation. {OFF_ONLY}"
                )),
            ),
            ("inputSchema", no_arguments()),
            ("annotations", hints(false)),
        ]),
    ])
}

/// `mcp(runtime, facts)`.
pub fn mcp(runtime: &Runtime, facts: &Value) -> Result<Option<Value>> {
    let request = field(facts, "request");
    if is(&request, "tools") {
        return Ok(Some(object(vec![("tools", tools())])));
    }
    let (tool, arguments) = (field(facts, "tool"), field(facts, "arguments"));
    let Some(tool) = (match &tool {
        Value::Str(text) => text.as_str().and_then(McpTool::parse),
        _ => None,
    }) else {
        return Ok(None);
    };
    let Value::Object(arguments) = arguments else {
        return Ok(None);
    };
    if !is(&request, "call") {
        return Ok(None);
    }
    let declared: &[&str] = match tool {
        McpTool::DisarmAdvancedCapability => &["capability"],
        _ => &[],
    };
    if arguments
        .keys()
        .any(|key| !key.as_str().is_some_and(|key| declared.contains(&key)))
    {
        return Ok(Some(object(vec![(
            "refused",
            text("unrecognized tool arguments"),
        )])));
    }
    let arming = runtime.arming();
    let actor = text(Actor::Mcp.as_str());
    Ok(Some(match tool {
        McpTool::ListAdvancedCapabilities => {
            let listing = arming.listing();
            let mut shown = Vec::new();
            for item in match field(&listing, "capabilities") {
                Value::Array(items) => items,
                _ => Vec::new(),
            } {
                let Value::Object(item) = item else {
                    return Err(Error::type_error(
                        "list indices must be integers or slices, not str",
                    ));
                };
                let mut entry = Map::new();
                for key in [
                    "id",
                    "state",
                    "since",
                    "by",
                    "reason",
                    "departs_from",
                    "keep_on",
                    "send_again",
                    "notice",
                ] {
                    let Some(value) = item.get(key) else {
                        return Err(Error::python("KeyError", key));
                    };
                    entry.insert(Str::new(key), value.clone());
                }
                let mut options = Map::new();
                if let Some(Value::Array(found)) = item.get("options") {
                    for option in found {
                        let key = crate::state::py::py_str(&field(option, "key"));
                        options.insert(Str::new(&key), field(option, "value"));
                    }
                }
                entry.insert(Str::new("options"), Value::Object(options));
                shown.push(Value::Object(entry));
            }
            let on = field(&listing, "on");
            let summary = format!(
                "{} advanced capabilit{}, {} on.",
                shown.len(),
                if shown.len() == 1 { "y" } else { "ies" },
                crate::state::py::py_str(&on)
            );
            object(vec![
                ("summary", text(&summary)),
                (
                    "data",
                    object(vec![("capabilities", Value::Array(shown)), ("on", on)]),
                ),
            ])
        }
        McpTool::DisarmAdvancedCapability => {
            let capability = arg(&arguments, "capability");
            let result = arming.disarm(&capability, &actor);
            if !pyval::truthy(&field(&result, "done")) {
                let refused = if is(
                    &field(&result, "refusal"),
                    Refusal::UnknownCapability.as_str(),
                ) {
                    "no advanced capability has that id"
                } else {
                    "the advanced state could not be changed"
                };
                return Ok(Some(object(vec![("refused", text(refused))])));
            }
            let changed = field(&result, "changed");
            let summary = format!(
                "{} is {}.",
                crate::state::py::py_str(&capability),
                if pyval::truthy(&changed) {
                    "now off"
                } else {
                    "off"
                }
            );
            object(vec![
                ("summary", text(&summary)),
                (
                    "data",
                    object(vec![
                        ("capability", capability),
                        ("state", text(ArmingState::Off.as_str())),
                        ("changed", changed),
                    ]),
                ),
            ])
        }
        McpTool::DisarmAllAdvanced => {
            let result = arming.all_off(&actor);
            if !pyval::truthy(&field(&result, "done")) {
                return Ok(Some(object(vec![(
                    "refused",
                    text("the advanced state could not be changed"),
                )])));
            }
            let count = field(&result, "count");
            object(vec![
                (
                    "summary",
                    text(&format!(
                        "All advanced features are off ({} turned off).",
                        crate::state::py::py_str(&count)
                    )),
                ),
                ("data", object(vec![("count", count)])),
            ])
        }
    }))
}

//! advusage: the Rust side of seat S7.2d's differential tests (`tests/rustdiff/diffs_advusage_*.py`). Dev only, never
//! shipped.
//!
//! `advusage <request.json>` runs one request and writes one JSON line per op: `{"ok": value}` or `{"raised": class}` -
//! what `tests/rustdiff/advusage.py`'s reference runner writes for the same request. The request names a scratch home, a
//! pinned clock, a token counter, the catalogs directory and a world: what the codes read of the outside, scripted -
//! Codex's files (`turns`, `source`), the view, the backend the meter looks through, the capability's own session, the
//! app's channel (`ipc`), core's guard, the saved accounts' switch, the continuation language and the Codex home. Nothing
//! is started, nothing is sent; every call the codes make of the world is written to a log the ops read back.

mod world;

use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::capabilities::{Code, Raised, Said};
use car_adv::engine::{
    capacity, continued, credits, earlyreset, resetmessage, resetwatch, usage, usagestop, wrapwords,
};
use car_adv::jsonx::object;
use car_adv::registry::{self, Registry};
use car_adv::state::calls::{self, Call};
use car_adv::state::scoped::Scoped;
use car_adv::state::seam::Tokens;
use car_adv::state::{AdvancedState, Error};
use car_adv::statement::Catalogs;
use car_machine::json::{Map, Value};
use car_policy::plug::Errand;

use world::{Shared, get};

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

/// `secrets.token_hex(n)` as both sides stand it in: a counter.
struct Counter(Mutex<u64>);

impl Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        *held += 1;
        format!("{:0>width$x}", *held, width = count * 2)
    }
}

enum Made {
    Meter(usage::UsageMeter),
    Wrap(usage::UsageWrapUp),
    Pause(usage::UsagePause),
    Stop(usagestop::UsageStop),
    Credit(credits::ResetCredit),
    Message(resetmessage::ResetMessage),
    Early(earlyreset::EarlyReset),
    Capacity(capacity::CapacityRetry),
}

impl Made {
    fn code(&mut self) -> &mut dyn Code {
        match self {
            Made::Meter(code) => code,
            Made::Wrap(code) => code,
            Made::Pause(code) => code,
            Made::Stop(code) => code,
            Made::Credit(code) => code,
            Made::Message(code) => code,
            Made::Early(code) => code,
            Made::Capacity(code) => code,
        }
    }
}

fn raised_of(raised: &Raised) -> Value {
    object([("raised", Value::from(raised.class.as_str()))])
}

fn ok(value: Value) -> Value {
    object([("ok", value)])
}

fn said(found: Result<Said, Raised>, pending: &mut Option<Box<dyn Errand>>) -> Value {
    match found {
        Err(raised) => raised_of(&raised),
        Ok(Said::Defer) => ok(Value::from("DEFER")),
        Ok(Said::Word(word)) => ok(Value::from(word.as_str())),
        Ok(Said::Value(value)) => ok(value),
        Ok(Said::Tuple(items)) | Ok(Said::Set(items)) => ok(Value::Array(items)),
        Ok(Said::Errand(errand)) => {
            *pending = Some(errand);
            ok(Value::from("ERRAND"))
        }
        Ok(_) => ok(Value::from("OBJECT")),
    }
}

fn opt_f64(value: Option<f64>) -> Value {
    value.map_or(Value::Null, Value::from)
}

fn row_of(value: &Value) -> resetwatch::Row {
    match value {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    }
}

fn keyed(value: &Value) -> Vec<(resetwatch::Family, resetwatch::Row)> {
    let Value::Array(items) = value else {
        return Vec::new();
    };
    let mut out: Vec<(resetwatch::Family, resetwatch::Row)> = Vec::new();
    for item in items {
        let row = row_of(item);
        let family = resetwatch::family_of(&row);
        match out.iter_mut().find(|(held, _)| {
            car_machine::pyval::eq(&held.0, &family.0) && car_machine::pyval::eq(&held.1, &family.1)
        }) {
            Some(slot) => slot.1 = row,
            None => out.push((family, row)),
        }
    }
    out
}

fn num(value: &Value) -> f64 {
    usage::number(value).unwrap_or(0.0)
}

fn pure(
    shared: &Arc<Shared>,
    state: &AdvancedState,
    name: &str,
    args: &[Value],
    kwargs: &Map,
) -> Result<Value, Raised> {
    let arg = |at: usize| args.get(at).cloned().unwrap_or(Value::Null);
    let kw = |name: &str| kwargs.get(name).cloned().unwrap_or(Value::Null);
    let world = shared.world_of();
    Ok(match name {
        "continued.answer_key" => Value::from(continued::answer_key(args)),
        "continued.handed" => continued::handed(&arg(0)).unwrap_or(Value::Null),
        "continued.words_pass" => Value::Bool(continued::words_pass(&arg(0))),
        "wrapwords.check_custom" => match wrapwords::check_custom(&arg(0)) {
            Ok(text) => Value::from(text),
            Err(error) => object([("error", Value::from(error.code()))]),
        },
        "wrapwords.window_words" => {
            let locale = car_store::value::text(&arg(1)).map(str::to_owned);
            wrapwords::window_words(&world.words(), &arg(0), locale.as_deref())
                .map_err(Raised::new)?
                .map_or(Value::Null, Value::from)
        }
        "wrapwords.reset_words" => {
            let locale = car_store::value::text(&arg(2)).map(str::to_owned);
            wrapwords::reset_words(&world.words(), &arg(0), &arg(1), locale.as_deref())
                .map_err(Raised::new)?
                .map_or(Value::Null, Value::from)
        }
        "wrapwords.render" => {
            let locale = car_store::value::text(&kw("locale")).map(str::to_owned);
            let ask = wrapwords::Ask {
                style: &kw("style"),
                minutes: &kw("minutes"),
                used: &kw("used"),
                stop_at: &kw("stop_at"),
                locale: locale.as_deref(),
                reset_at: &kw("reset_at"),
                include_reset: car_machine::pyval::truthy(&kw("include_reset")),
                custom: &kw("custom"),
            };
            wrapwords::render(&world.words(), &ask)
                .map_err(Raised::new)?
                .map_or(Value::Null, Value::from)
        }
        "resetwatch.blank" => Value::Object(resetwatch::blank(&arg(0), &arg(1))),
        "resetwatch.by_time" => {
            let (row, reset) = resetwatch::by_time(&row_of(&arg(0)), &arg(1))?;
            Value::Array(vec![Value::Object(row), Value::Bool(reset)])
        }
        "resetwatch.closed" => Value::Object(resetwatch::closed(&row_of(&arg(0)), &arg(1))?),
        "resetwatch.advance" => {
            let window = arg(1);
            let window = (!matches!(window, Value::Null)).then_some(window);
            let early = !matches!(arg(3), Value::Bool(false));
            let (row, events) =
                resetwatch::advance(&row_of(&arg(0)), window.as_ref(), &arg(2), early)?;
            Value::Array(vec![
                Value::Object(row),
                Value::Array(events.into_iter().map(Value::from).collect()),
            ])
        }
        "resetwatch.family_window" => {
            let family = match arg(1) {
                Value::Array(pair) if pair.len() == 2 => (pair[0].clone(), pair[1].clone()),
                _ => (Value::Null, Value::Null),
            };
            resetwatch::family_window(&arg(0), &family)?.unwrap_or(Value::Null)
        }
        "resetwatch.count" => resetwatch::count(&row_of(&arg(0)), &row_of(&arg(1))),
        "resetwatch.due" => {
            let row = arg(1);
            let row = (!matches!(row, Value::Null)).then(|| row_of(&row));
            Value::Bool(resetwatch::due(&row_of(&arg(0)), row.as_ref())?)
        }
        "usage.percent" => usage::percent(
            &row_of(&arg(0)),
            car_store::value::text(&arg(1)).unwrap_or_default(),
            &arg(2),
        )
        .unwrap_or(Value::Null),
        "usage.reached" => {
            let threshold = arg(1);
            let threshold = (!matches!(threshold, Value::Null)).then_some(threshold);
            Value::Bool(usage::reached(
                &row_of(&arg(0)),
                threshold.as_ref(),
                num(&arg(2)),
            )?)
        }
        "usage.acting" => Value::Array(
            usage::acting(&row_of(&arg(0)))
                .into_iter()
                .map(Value::from)
                .collect(),
        ),
        "usage.touched" => Value::Array(
            usage::touched(car_store::value::text(&arg(0)).unwrap_or_default())
                .into_iter()
                .map(Value::from)
                .collect(),
        ),
        "usage.order_problem" => {
            let windows: Vec<i64> = match arg(1) {
                Value::Array(items) => items.iter().map(|item| num(item) as i64).collect(),
                _ => usage::WINDOWS.to_vec(),
            };
            let (refusal, warning) = usage::order_problem(&row_of(&arg(0)), &windows)?;
            Value::Array(vec![
                refusal.map_or(Value::Null, Value::from),
                warning.map_or(Value::Null, Value::from),
            ])
        }
        "usage.stale" => {
            let resets: Vec<(resetwatch::Family, Value)> = match arg(1) {
                Value::Array(items) => items
                    .iter()
                    .filter_map(|item| match item {
                        Value::Array(three) if three.len() == 3 => {
                            Some(((three[0].clone(), three[1].clone()), three[2].clone()))
                        }
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            Value::Bool(usage::stale(&row_of(&arg(0)), &resets)?)
        }
        "usage.reset_since" => Value::Bool(usage::reset_since(
            &keyed(&arg(0)),
            &arg(1),
            &arg(2),
            num(&arg(3)),
        )?),
        "usage.previews" => {
            let found = usage::previews(&world, state, num(&arg(0)))?;
            let mut map = Map::new();
            for (minutes, words) in found {
                map.insert(
                    minutes.to_string().as_str().into(),
                    words.map_or(Value::Null, Value::from),
                );
            }
            Value::Object(map)
        }
        "resetmessage.carried_by_stop" => {
            let stops: Vec<resetwatch::Row> = match arg(1) {
                Value::Array(items) => items.iter().map(row_of).collect(),
                _ => Vec::new(),
            };
            Value::Bool(resetmessage::carried_by_stop(&row_of(&arg(0)), &stops)?)
        }
        "resetmessage.same_reset" => {
            let row = arg(1);
            let row = (!matches!(row, Value::Null)).then(|| row_of(&row));
            Value::Bool(resetmessage::same_reset(
                &row_of(&arg(0)),
                row.as_ref(),
                &arg(2),
                num(&arg(3)),
            )?)
        }
        "usagestop.counts_here" => {
            let window = arg(1);
            let window = (!matches!(window, Value::Null)).then(|| row_of(&window));
            Value::Bool(usagestop::counts_here(
                &row_of(&arg(0)),
                window.as_ref(),
                &row_of(&arg(2)),
                &keyed(&arg(3)),
                num(&arg(4)),
            )?)
        }
        _ => return Err(Raised::new("UnknownFunction")),
    })
}

fn main() {
    let path = std::env::args().nth(1).expect("the request file");
    let raw = std::fs::read_to_string(&path).expect("the request");
    let Ok(Value::Object(request)) = car_machine::compat::loads(&raw) else {
        eprintln!("the request is not a JSON object");
        std::process::exit(2);
    };
    let home = std::path::PathBuf::from(car_machine::pytext::py_str(get(&request, "home")));
    let clock = Arc::new(Mutex::new(
        usage::number(get(&request, "clock")).unwrap_or(0.0),
    ));
    let seed = match get(&request, "tokens") {
        Value::Int(int) => int.as_i64().unwrap_or(0) as u64,
        _ => 0,
    };
    let counter = Arc::new(Counter(Mutex::new(seed)));
    let registry: Arc<Registry> = Arc::new(registry::shipped(false).expect("the shipped registry"));
    let no_env = |_: &str| None;
    let paths = car_config::Paths::new(
        Some(&home.to_string_lossy()),
        &home.to_string_lossy(),
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths");
    let reading = Arc::clone(&clock);
    let state = Arc::new(AdvancedState::new(
        paths.clone(),
        registry,
        Box::new(move || *reading.lock().unwrap_or_else(PoisonError::into_inner)),
        counter.clone() as Arc<dyn Tokens>,
    ));
    let catalogs = Arc::new(Catalogs::new(
        car_machine::pytext::py_str(get(&request, "catalogs")),
        Box::new(|| "en".to_owned()),
    ));
    let shared = Shared::new(get(&request, "world").clone(), catalogs);
    let switches: Arc<Mutex<Map>> = Arc::new(Mutex::new(Map::new()));
    let mut made: HashMap<String, Made> = HashMap::new();
    let mut pending: HashMap<String, Box<dyn Errand>> = HashMap::new();
    let empty = Map::new();
    let mut out = String::new();
    let ops = match get(&request, "ops") {
        Value::Array(ops) => ops.clone(),
        _ => Vec::new(),
    };
    for op in ops {
        let Value::Object(op) = op else { continue };
        let args = match get(&op, "args") {
            Value::Array(args) => args.clone(),
            _ => Vec::new(),
        };
        let kwargs = match get(&op, "kwargs") {
            Value::Object(kwargs) => kwargs.clone(),
            _ => empty.clone(),
        };
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Value {
            if let Some(at) = usage::number(get(&op, "clock")) {
                *clock.lock().unwrap_or_else(PoisonError::into_inner) = at;
                return ok(Value::Null);
            }
            if let Value::Object(changes) = get(&op, "world") {
                shared.merge(changes);
                return ok(Value::Null);
            }
            if let Value::Object(changes) = get(&op, "switches") {
                let mut held = switches.lock().unwrap_or_else(PoisonError::into_inner);
                for (key, value) in changes {
                    held.insert(key.clone(), value.clone());
                }
                return ok(Value::Null);
            }
            if matches!(get(&op, "log"), Value::Bool(true)) {
                return ok(shared.take_log());
            }
            if let Value::Str(method) = get(&op, "method") {
                let call = Call {
                    args: &args,
                    kwargs: &kwargs,
                };
                return match calls::call(&state, method.as_str().unwrap_or_default(), call) {
                    Ok(value) => ok(value),
                    Err(error) => object([("raised", Value::from(Error::class(&error)))]),
                };
            }
            if let Value::Str(name) = get(&op, "fn") {
                return match pure(
                    &shared,
                    &state,
                    name.as_str().unwrap_or_default(),
                    &args,
                    &kwargs,
                ) {
                    Ok(value) => ok(value),
                    Err(raised) => raised_of(&raised),
                };
            }
            if let Value::Str(what) = get(&op, "inuse") {
                return ok(world::inuse_op(
                    &paths,
                    what.as_str().unwrap_or_default(),
                    &args,
                ));
            }
            if let Value::Str(capability) = get(&op, "make") {
                let capability = capability.as_str().unwrap_or_default().to_owned();
                let name = car_machine::pytext::py_str(get(&op, "as"));
                let bound = bind(&state, &switches, &capability);
                let world = shared.world_of();
                let home = match get(&op, "home") {
                    Value::Str(home) => Some(home.as_str().unwrap_or_default().to_owned()),
                    _ => None,
                };
                let code = match capability.as_str() {
                    "usage_meter" => {
                        let mut code = usage::UsageMeter::new(paths.clone(), world);
                        code.bind_to(bound);
                        Made::Meter(code)
                    }
                    "usage_wrap_up" => {
                        let mut code = usage::UsageWrapUp::new(paths.clone(), world);
                        code.home = home;
                        code.bind_to(bound);
                        Made::Wrap(code)
                    }
                    "usage_pause" if matches!(get(&op, "plain"), Value::Bool(true)) => {
                        let mut code = usage::UsagePause::new(paths.clone(), world);
                        code.core.bound = Some(bound);
                        Made::Pause(code)
                    }
                    "usage_pause" => {
                        let mut code = usagestop::UsageStop::new(paths.clone(), world);
                        code.set_home(home);
                        code.bind_to(bound);
                        Made::Stop(code)
                    }
                    "reset_credit" => {
                        let mut code = credits::ResetCredit::new(
                            paths.clone(),
                            world.open.clone(),
                            world.keys.clone(),
                        );
                        code.bind_to(bound);
                        Made::Credit(code)
                    }
                    "reset_message" => {
                        let mut code =
                            resetmessage::ResetMessage::new(paths.clone(), world.open.clone());
                        code.bind_to(bound);
                        Made::Message(code)
                    }
                    "early_reset" => {
                        let mut code = earlyreset::EarlyReset::new(paths.clone());
                        code.bind_to(bound);
                        Made::Early(code)
                    }
                    "capacity_retry" => {
                        let mut code = capacity::CapacityRetry::new(paths.clone());
                        if !matches!(get(&op, "unbound"), Value::Bool(true)) {
                            code.bind_to(bound);
                        }
                        Made::Capacity(code)
                    }
                    _ => return object([("raised", Value::from("UnknownCapability"))]),
                };
                made.insert(name, code);
                return ok(Value::Null);
            }
            if let Value::Str(hook) = get(&op, "hook") {
                let name = car_machine::pytext::py_str(get(&op, "code"));
                let Some(code) = made.get_mut(&name) else {
                    return object([("raised", Value::from("NoCode"))]);
                };
                let view = world::ScriptView(&shared);
                let arg = |at: usize| args.get(at).cloned().unwrap_or(Value::Null);
                let mut errand = None;
                let answer = match hook.as_str().unwrap_or_default() {
                    "tick" => said(code.code().tick(&view), &mut errand),
                    "records" => said(code.code().records(&view), &mut errand),
                    "gate" => said(code.code().gate(&arg(0), &arg(1), &arg(2)), &mut errand),
                    "schedule" => said(code.code().schedule(&arg(0), &arg(1)), &mut errand),
                    "admission" => said(code.code().admission(&arg(0)), &mut errand),
                    "holds" => match code.code().holds(&arg(0)) {
                        None => object([("raised", Value::from("AttributeError"))]),
                        Some(Ok(value)) => ok(value),
                        Some(Err(raised)) => raised_of(&raised),
                    },
                    "not_taken" => match code.code().not_taken(&arg(0)) {
                        None => object([("raised", Value::from("AttributeError"))]),
                        Some(Ok(())) => ok(Value::Null),
                        Some(Err(raised)) => raised_of(&raised),
                    },
                    "watched_due" => match code.code().watched_due(&view) {
                        None => object([("raised", Value::from("AttributeError"))]),
                        Some(found) => said(found, &mut errand),
                    },
                    _ => object([("raised", Value::from("UnknownHook"))]),
                };
                if let Some(errand) = errand {
                    pending.insert(name, errand);
                }
                return answer;
            }
            if let Value::Str(name) = get(&op, "run") {
                let name = name.as_str().unwrap_or_default().to_owned();
                let Some(errand) = pending.remove(&name) else {
                    return object([("raised", Value::from("NoErrand"))]);
                };
                let view = world::ScriptView(&shared);
                let mut guards = shared.guards();
                return match errand.run(&view, &mut guards) {
                    Ok(value) => ok(value),
                    Err(_) => object([("raised", Value::from("Exception"))]),
                };
            }
            if let Value::Str(name) = get(&op, "kept") {
                let now = *clock.lock().unwrap_or_else(PoisonError::into_inner);
                let Some(code) = made.get_mut(name.as_str().unwrap_or_default()) else {
                    return object([("raised", Value::from("NoCode"))]);
                };
                return ok(kept(code, now));
            }
            object([("raised", Value::from("UnknownOp"))])
        }));
        let line = match result {
            Ok(value) => value,
            Err(_) => object([("raised", Value::from("Panic"))]),
        };
        out.push_str(
            &car_machine::json::to_string(&line, &car_machine::json::Options::new()).expect("JSON"),
        );
        out.push('\n');
    }
    state.close();
    print!("{out}");
}

/// What each code keeps in this process, as the reference's attributes read.
fn kept(code: &mut Made, now: f64) -> Value {
    match code {
        Made::Meter(meter) => {
            let kept = meter.kept();
            object([
                ("looked", opt_f64(kept.looked)),
                ("why", kept.why.map_or(Value::Null, Value::from)),
                ("said", kept.said.map_or(Value::Null, Value::from)),
                ("skipped_at", opt_f64(kept.skipped_at)),
                (
                    "held",
                    kept.held.map_or(Value::Null, |(exe, home)| {
                        Value::Array(vec![Value::from(exe), Value::from(home)])
                    }),
                ),
            ])
        }
        Made::Wrap(wrap) => object([
            ("looked", opt_f64(wrap.looked)),
            ("turn", Value::from(wrap.turn as i64)),
        ]),
        Made::Early(early) => {
            let mut released = early.released.clone();
            released.sort_by_key(car_machine::pytext::py_str);
            object([
                ("probe_at", opt_f64(early.probe_at)),
                ("reached", Value::Bool(early.reached)),
                ("first_available_at", opt_f64(early.first_available_at)),
                ("lifted_at", opt_f64(early.lifted_at)),
                ("released", Value::Array(released)),
            ])
        }
        Made::Credit(credit) => Value::Array(
            credit
                .tried()
                .into_iter()
                .map(|(rule, at)| Value::Array(vec![rule, Value::from(at)]))
                .collect(),
        ),
        Made::Stop(stop) => stop.with(|inner| {
            let pairs = |list: &[(Value, (i64, f64))]| {
                Value::Array(
                    list.iter()
                        .map(|(key, (failures, again))| {
                            Value::Array(vec![
                                key.clone(),
                                Value::from(*failures),
                                Value::from(*again),
                            ])
                        })
                        .collect(),
                )
            };
            object([
                ("notices", Value::Array(inner.notices(now))),
                ("backoff", pairs(&inner.backoff)),
                (
                    "stopped",
                    Value::Array(
                        inner
                            .stopped
                            .iter()
                            .map(|(a, b, c)| Value::Array(vec![a.clone(), b.clone(), c.clone()]))
                            .collect(),
                    ),
                ),
                (
                    "unsure",
                    Value::Array(
                        inner
                            .unsure
                            .iter()
                            .map(|(key, said)| Value::Array(vec![key.clone(), Value::Bool(*said)]))
                            .collect(),
                    ),
                ),
                (
                    "missing",
                    Value::Array(
                        inner
                            .missing
                            .iter()
                            .map(|(key, at)| Value::Array(vec![key.clone(), Value::from(*at)]))
                            .collect(),
                    ),
                ),
            ])
        }),
        _ => Value::Null,
    }
}

/// The code's `Scoped`: `state.scoped(capability, on=..., verdict=..., armed=...)` over the switches the ops set.
fn bind(state: &Arc<AdvancedState>, switches: &Arc<Mutex<Map>>, capability: &str) -> usage::Bound {
    let state = Arc::clone(state);
    let switches = Arc::clone(switches);
    let capability = capability.to_owned();
    usage::Bound::new(Arc::new(move |act: &mut dyn FnMut(&Scoped<'_>)| {
        let held = switches
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone();
        let table = |name: &str| match held.get(name) {
            Some(Value::Object(map)) => map.clone(),
            _ => Map::new(),
        };
        let on_table = table("on");
        let verdicts = table("verdict");
        let armed_table = table("armed");
        let me = capability.clone();
        let on = move || !matches!(on_table.get(me.as_str()), Some(Value::Bool(false)));
        let verdict = move |measurement: &Value| {
            verdicts
                .get(car_machine::pytext::py_str(measurement).as_str())
                .cloned()
                .unwrap_or(Value::Null)
        };
        let armed = move |other: &Value| {
            matches!(
                armed_table.get(car_machine::pytext::py_str(other).as_str()),
                Some(Value::Bool(true))
            )
        };
        let scoped = Scoped {
            state: &state,
            capability: Value::from(capability.as_str()),
            on: Some(&on),
            verdict: Some(&verdict),
            armed: Some(&armed),
        };
        act(&scoped);
        true
    }))
}

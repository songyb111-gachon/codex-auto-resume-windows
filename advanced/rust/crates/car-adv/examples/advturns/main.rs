//! `advturns` (seat S7.2e1): car-adv's runtime over the edition's own capabilities - the engine's codes for sends and
//! turns, each made with the scenario's fakes - for `tests/rustdiff/diffs_advturns_*.py` (`advturns.py`).
//!
//! One request on stdin - `{"scenario": ..., "home": <scratch folder>, "catalogs": <the folder the reference wrote>}` -
//! one answer on stdout: `{"results": [{"ok": ...} | {"error": class}, ...], "asked": [...]}`, the same shape
//! `advturns.REFERENCE` prints. Every home is the caller's scratch folder; no Codex is started or looked for: every
//! session, turn reader and app look is the scenario's fake (`world.rs`).

mod world;

use std::io::{Read, Write};
use std::sync::{Arc, Mutex, PoisonError};

use car_adv::arming::ArmRequest;
use car_adv::capabilities::{Code, Said};
use car_adv::measured::Table;
use car_adv::registry::{CapabilityDef, Registry};
use car_adv::runtime::{Options, Shared};
use car_adv::seam::{Edges, Unavailable};
use car_adv::statement::Catalogs;
use car_adv::vocabulary::AutoResult;
use car_adv::vocabulary::Verdict;
use car_adv::vocabulary::{Measurement, OptionKey};
use car_machine::json::{Map, Value};
use car_policy::plug::{Point, ReadFailed, View};

use world::Asked;

fn text(word: &str) -> Value {
    Value::Str(word.into())
}

fn get<'a>(value: &'a Value, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(name).unwrap_or(&NULL),
        _ => &NULL,
    }
}

/// The edges of `Arming` a trace reaches: the view and the measurements are handed in, so the defaults are never
/// asked; nothing follows, nothing is forgotten.
struct TraceEdges;

impl Edges for TraceEdges {
    fn default_view(&self) -> Result<Value, Unavailable> {
        Err(Unavailable)
    }
    fn default_live_view(&self) -> Result<Value, Unavailable> {
        Err(Unavailable)
    }
    fn table_for(&self, _engine: Option<&str>) -> Result<Table, Unavailable> {
        Ok(Table::new())
    }
    fn checked_for(
        &self,
        _engine: Option<&str>,
    ) -> Result<std::collections::BTreeMap<Measurement, AutoResult>, Unavailable> {
        Ok(Default::default())
    }
    fn sending_points(&self) -> Vec<Point> {
        [
            Point::Gates,
            Point::Text,
            Point::Sender,
            Point::Schedule,
            Point::Outcome,
            Point::Delivery,
            Point::Unloaded,
            Point::Admission,
        ]
        .into_iter()
        .collect()
    }
    fn hook_follow(&self, _armed: bool) {}
    fn power_tasks_follow(&self, _armed: bool) {}
    fn account_forget(&self) {}
    fn usage_touched(&self, _key: OptionKey) -> Vec<i64> {
        Vec::new()
    }
    fn usage_order_problem(
        &self,
        _values: &std::collections::BTreeMap<String, std::collections::BTreeMap<OptionKey, i64>>,
        _windows: &[i64],
    ) -> (Option<String>, Option<String>) {
        (None, None)
    }
    fn usage_previews(&self, _now: f64) -> Vec<(i64, Option<String>)> {
        Vec::new()
    }
    fn wording_problem(&self, _words: &Value) -> Option<String> {
        None
    }
    fn wording_limit(&self) -> i64 {
        0
    }
    fn wording_placeholders(&self) -> Vec<String> {
        Vec::new()
    }
}

/// No path of a trace's home is a link (the homes are the caller's scratch folders).
#[derive(Debug)]
struct NoLinks;

impl car_config::Links for NoLinks {
    fn is_symlink(&self, _path: &std::path::Path) -> bool {
        false
    }
}

/// `secrets.token_hex` as one counter, as the reference's side replaces it.
struct Counter(Mutex<u64>);

impl car_adv::state::seam::Tokens for Counter {
    fn hex(&self, count: usize) -> String {
        let mut held = self.0.lock().unwrap_or_else(PoisonError::into_inner);
        *held += 1;
        let digits = format!("{:x}", *held);
        let width = count * 2;
        let padded = format!("{digits:0>width$}");
        padded[padded.len() - width..].to_owned()
    }
}

/// The engine's view as a trace shows it: `get` from the scenario's core records, and the moment.
struct TraceView {
    now: f64,
    core: Value,
    enabled: Value,
}

impl View for TraceView {
    fn now(&self) -> f64 {
        self.now
    }
    fn get(&self, interruption_id: &str) -> Result<Value, ReadFailed> {
        Ok(get(&self.core, interruption_id).clone())
    }
    fn thread_enabled(&self, thread_id: &str) -> Result<bool, ReadFailed> {
        match get(&self.enabled, thread_id) {
            Value::Null => Ok(true),
            Value::Str(word) if word.as_str() == Some("raise") => Err(ReadFailed("RuntimeError")),
            found => Ok(car_machine::pyval::truthy(found)),
        }
    }
}

fn said(found: &Said) -> Value {
    let mut map = Map::new();
    match found {
        Said::Defer => return text("DEFER"),
        Said::Backend => return text("BACKEND"),
        Said::Word(word) => {
            map.insert("word".into(), text(word.as_str()));
        }
        Said::Value(value) => {
            map.insert("value".into(), value.clone());
        }
        Said::Tuple(items) => {
            map.insert("value".into(), Value::Array(items.clone()));
        }
        Said::Set(items) => {
            let mut items = items.clone();
            items.sort_by_key(|item| format!("{item:?}"));
            map.insert("value".into(), Value::Array(items));
        }
        Said::Channel(_) => {
            map.insert("object".into(), text("channel"));
        }
        Said::Route(_) => {
            map.insert("object".into(), text("route"));
        }
        Said::Errand(_) => {
            map.insert("object".into(), text("errand"));
        }
        Said::StartRoute(_) => {
            map.insert("object".into(), text("start"));
        }
    }
    Value::Object(map)
}

fn value(found: Value) -> Value {
    let mut map = Map::new();
    map.insert("value".into(), found);
    Value::Object(map)
}

fn words(found: Option<Vec<String>>) -> Value {
    match found {
        None => text("DEFER"),
        Some(words) => value(Value::Array(
            words.into_iter().map(|word| text(&word)).collect(),
        )),
    }
}

fn main() {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).expect("stdin");
    let request = car_machine::json::from_str(&input).expect("request");
    let scenario = get(&request, "scenario").clone();
    let home = get(&request, "home").as_text().expect("home").to_owned();
    let catalogs_dir = get(&request, "catalogs")
        .as_text()
        .expect("catalogs")
        .to_owned();
    let every: Vec<CapabilityDef> = car_adv::registry::definitions()
        .into_iter()
        .chain(
            car_adv::registry::waiting()
                .into_iter()
                .map(|(definition, _)| definition),
        )
        .chain(car_adv::registry::installed_only())
        .collect();
    let mut definitions: Vec<CapabilityDef> = Vec::new();
    if let Value::Array(items) = get(&scenario, "capabilities") {
        for item in items {
            let id = item.as_text().expect("capability");
            definitions.push(
                every
                    .iter()
                    .find(|definition| definition.id == id)
                    .cloned()
                    .expect("a shipped capability"),
            );
        }
    }
    let registry = Arc::new(Registry::new(definitions).expect("registry"));
    let start = match get(&scenario, "now") {
        Value::Float(now) => *now,
        Value::Int(now) => now.as_i64().unwrap_or(0) as f64,
        _ => 1_800_000_000.0,
    };
    let clock = Arc::new(Mutex::new(start));
    let asked: Asked = Arc::new(Mutex::new(Vec::new()));
    let world = world::World::new(
        get(&scenario, "seams").clone(),
        asked.clone(),
        clock.clone(),
        &catalogs_dir,
    );
    let maker_world = world.clone();
    let mut table = Table::new();
    if let Value::Object(map) = get(&scenario, "measured") {
        for (name, entry) in map.iter() {
            let (Some(measurement), Value::Array(pair)) =
                (Measurement::parse(name.as_str().unwrap_or_default()), entry)
            else {
                continue;
            };
            let verdict = pair
                .first()
                .and_then(|v| v.as_text())
                .and_then(Verdict::parse);
            let on = pair
                .get(1)
                .and_then(|v| v.as_text())
                .unwrap_or_default()
                .to_owned();
            if let Some(verdict) = verdict {
                table.insert(measurement, (verdict, on));
            }
        }
    }
    let compat_state = get(&scenario, "compat_state")
        .as_text()
        .unwrap_or("COMPATIBLE")
        .to_owned();
    // Every compat capability the registry's definitions name, at the scenario's state (one word for all).
    let mut compat_names: Vec<String> = vec!["not_loaded_recovery".to_owned()];
    for definition in registry.iter() {
        if let Some(name) = &definition.compat
            && !compat_names.contains(name)
        {
            compat_names.push(name.clone());
        }
    }
    let mut capabilities = Map::new();
    for name in &compat_names {
        let mut entry = Map::new();
        entry.insert("state".into(), text(&compat_state));
        entry.insert("reason".into(), text("local_checks_passed"));
        capabilities.insert(name.as_str().into(), Value::Object(entry));
    }
    let mut view_map = car_machine::json::from_str(
        r#"{"status": "ok", "engine": {"found": true, "version": "0.155.0"}}"#,
    )
    .expect("view");
    if let Value::Object(map) = &mut view_map {
        map.insert("capabilities".into(), Value::Object(capabilities));
    }
    let view_json = view_map;
    let paths = car_config::Paths::new(
        Some(&home),
        &home,
        &|_| None,
        car_config::Os::here(false, Arc::new(NoLinks)),
    )
    .expect("paths");
    let options = {
        let clock = clock.clone();
        Options {
            registry: registry.clone(),
            clock: Arc::new(move || *clock.lock().unwrap_or_else(PoisonError::into_inner)),
            policy: Arc::new(|| Ok(car_adv::policy::none())),
            view: Some(Arc::new(move || Ok(view_json.clone()))),
            measured: Some(Arc::new(move || Ok(table.clone()))),
            live: None,
            catalogs: Catalogs::new(catalogs_dir, Box::new(|| "en".to_owned())),
            edges: Box::new(TraceEdges),
            maker: Arc::new(
                move |definition: &CapabilityDef,
                      paths: &car_config::Paths|
                      -> Option<Box<dyn Code>> {
                    maker_world.make(definition, paths)
                },
            ),
            tokens: Arc::new(Counter(Mutex::new(0))),
            log: None,
            auto_check: None,
        }
    };
    let shared: Arc<Shared> = Shared::new(paths, options);
    let core = get(&scenario, "core").clone();
    let enabled = get(&scenario, "enabled").clone();
    let now = || *clock.lock().unwrap_or_else(PoisonError::into_inner);
    let mut results = Vec::new();
    let mut last: Option<car_adv::runtime::tick::Errands> = None;
    let steps = match get(&scenario, "steps") {
        Value::Array(steps) => steps.clone(),
        _ => Vec::new(),
    };
    for step in steps {
        let Value::Array(step) = step else { continue };
        let op = step
            .first()
            .and_then(|op| op.as_text())
            .unwrap_or_default()
            .to_owned();
        let args: Vec<Value> = step.into_iter().skip(1).collect();
        let arg = |index: usize| args.get(index).cloned().unwrap_or(Value::Null);
        let view = || TraceView {
            now: now(),
            core: core.clone(),
            enabled: enabled.clone(),
        };
        let out: Result<Value, String> = shared.enter(|runtime| match op.as_str() {
            "clock" => {
                if let Some(at) = match arg(0) {
                    Value::Float(at) => Some(at),
                    Value::Int(at) => at.as_i64().map(|at| at as f64),
                    _ => None,
                } {
                    *clock.lock().unwrap_or_else(PoisonError::into_inner) = at;
                }
                Ok(Value::Null)
            }
            "arm" => {
                let capability = arg(0);
                let revision = capability
                    .as_text()
                    .and_then(|id| runtime.registry.get(id))
                    .map_or(Value::Null, |definition| Value::from(definition.revision));
                let generation = runtime
                    .state
                    .meta()
                    .ok()
                    .and_then(|meta| meta.get("generation").cloned())
                    .unwrap_or(Value::Null);
                let changes = arg(2);
                let pick = |name: &str, default: Value| match &changes {
                    Value::Object(map) => map.get(name).cloned().unwrap_or(default),
                    _ => default,
                };
                let mut warnings = pick("warnings", Value::Null);
                if warnings.as_text() == Some("AUTO") {
                    warnings = match capability.as_text().and_then(|id| runtime.registry.get(id)) {
                        Some(definition) => Value::Array(
                            runtime
                                .arming()
                                .warnings(definition, None)
                                .into_iter()
                                .map(|word| text(word.as_str()))
                                .collect(),
                        ),
                        None => Value::Array(Vec::new()),
                    };
                }
                runtime
                    .arming()
                    .arm(&ArmRequest {
                        capability: capability.clone(),
                        state: arg(1),
                        revision: pick("revision", revision),
                        generation: pick("generation", generation),
                        acknowledged_version: pick("acknowledged_version", text("0.155.0")),
                        warnings,
                        also: pick("also", Value::Null),
                        keep_on: pick("keep_on", Value::Bool(false)),
                        actor: pick("actor", text("dashboard")),
                    })
                    .map_err(|_| "UnicodeDecodeError".to_owned())
            }
            "ask" => {
                let point = arg(0)
                    .as_text()
                    .and_then(Point::parse)
                    .ok_or("ValueError")?;
                let rest: Vec<Value> = args.iter().skip(1).cloned().collect();
                let refs: Vec<&Value> = rest.iter().collect();
                runtime
                    .ask(point, &refs)
                    .map(|found| said(&found))
                    .map_err(|raise| raise.0.to_owned())
            }
            "tick" | "resident" => {
                let view = view();
                let found = if op == "tick" {
                    runtime.tick(&view)
                } else {
                    runtime.resident(&view)
                };
                match found {
                    Ok(Some(errands)) => {
                        last = Some(errands);
                        Ok(car_machine::json::from_str(r#"{"object": "errands"}"#).expect("json"))
                    }
                    Ok(None) => {
                        last = None;
                        Ok(text("DEFER"))
                    }
                    Err(raise) => Err(raise.0.to_owned()),
                }
            }
            "records" => runtime
                .records(&view())
                .map(|found| {
                    if found.is_empty() {
                        text("DEFER")
                    } else {
                        value(Value::Array(found))
                    }
                })
                .map_err(|raise| raise.0.to_owned()),
            "partition" => runtime
                .partition(&arg(0))
                .map(|found| found.map_or_else(|| text("DEFER"), value))
                .map_err(|raise| raise.0.to_owned()),
            "moved" => runtime
                .moved(&arg(0), arg(1).as_text().unwrap_or_default())
                .map(|()| text("DEFER"))
                .map_err(|raise| raise.0.to_owned()),
            "sessions" => runtime
                .sessions()
                .map(words)
                .map_err(|raise| raise.0.to_owned()),
            "eligibility" => runtime
                .eligibility()
                .map(words)
                .map_err(|raise| raise.0.to_owned()),
            "wants" => Ok(Value::Bool(
                arg(0)
                    .as_text()
                    .and_then(Point::parse)
                    .is_some_and(|point| runtime.wants(point)),
            )),
            "start_route" => runtime
                .start_route(&arg(0))
                .map(|found| said(&found))
                .map_err(|raise| raise.0.to_owned()),
            "start_held" => Ok(runtime.start_held()),
            "supervise" => runtime
                .supervise(&arg(0))
                .map(|found| said(&found))
                .map_err(|raise| raise.0.to_owned()),
            "supervise_held" => Ok(runtime.supervise_held()),
            "conversation_off" => runtime
                .conversation_off(&arg(0))
                .map(|()| value(Value::Null))
                .map_err(|raise| raise.0.to_owned()),
            "states" => {
                let found = runtime.states(car_machine::pyval::truthy(&arg(0)), &[]);
                let mut pairs: Vec<(String, car_adv::vocabulary::ArmingState)> = found.0.clone();
                pairs.sort_by(|a, b| a.0.cmp(&b.0));
                let mut map = Map::new();
                for (capability, state) in pairs {
                    map.insert(capability.as_str().into(), text(state.as_str()));
                }
                Ok(Value::Object(map))
            }
            "run" => Ok(Value::Null),
            "choose" => {
                let generation = runtime
                    .state
                    .meta()
                    .ok()
                    .and_then(|meta| meta.get("generation").cloned())
                    .unwrap_or(Value::Null);
                Ok(runtime.arming().set_option(
                    &arg(0),
                    &arg(1),
                    &arg(2),
                    &generation,
                    &text("dashboard"),
                ))
            }
            _ => world
                .step(&op, &args, &runtime.state)
                .ok_or_else(|| "UnknownOp".to_owned())?,
        });
        // `run` goes outside the runtime's lock, as core runs an errand last in the tick.
        let out = if op == "run" {
            match &last {
                None => Ok(Value::Null),
                Some(errands) => {
                    let view = view();
                    let mut guards = |body: &mut dyn FnMut(bool) -> Value| Ok(body(true));
                    car_policy::plug::Errand::run(errands, &view, &mut guards)
                        .map_err(|_| "Exception".to_owned())
                }
            }
        } else {
            out
        };
        let mut entry = Map::new();
        match out {
            Ok(found) => entry.insert("ok".into(), found),
            Err(class) => entry.insert("error".into(), text(&class)),
        };
        results.push(Value::Object(entry));
    }
    shared.enter(|runtime| runtime.state.close());
    let asked = asked.lock().unwrap_or_else(PoisonError::into_inner).clone();
    let mut answer = Map::new();
    answer.insert("results".into(), Value::Array(results));
    answer.insert("asked".into(), Value::Array(asked));
    let written =
        car_machine::json::to_string(&Value::Object(answer), &car_machine::json::Options::wire())
            .expect("json");
    std::io::stdout()
        .write_all(written.as_bytes())
        .expect("stdout");
}

trait AsText {
    fn as_text(&self) -> Option<&str>;
}

impl AsText for Value {
    fn as_text(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}

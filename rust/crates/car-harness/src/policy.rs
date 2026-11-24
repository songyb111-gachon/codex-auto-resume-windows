//! car-policy's calls of the S2.2 seat (settings and the plug), one batch at a time: `policy.batch`.
//!
//! The request is read as Python's `json.loads` reads it (NaN, lone surrogates and ints of any size kept: the
//! settings files hold them), so `main.rs` hands this module the raw line. `cases` is a list of `[name, arg, ...]`;
//! the answer is a list with one entry per case: `{"ok": value}`, or `{"error": class, ...}` with what the exception
//! carries (a settings refusal's sentence, an Unreadable's reason). The shape is what `tests/rustdiff/settingsdiff.py`'s
//! reference side writes. The functions are car-policy's own: nothing here decides anything.
//!
//! The `Os` the settings take is built here over car-platform (`links`, `widepath`, `paths::realpath`), as the entry
//! points will build it.

use std::path::{Path, PathBuf};

use car_machine::json::{Map, Str, Value};
use car_machine::pyval::Py;
use car_policy::plug::{self, Alternative, Answer, Guarded, HookFailed, Plug, Point, hands};
use car_policy::settings::{
    self, SettingsError, config, demo, homes, managed, memguard, notice_kinds, os, ownvalues,
    poweraction, schema, selfcheck, statusfile,
};

/// `Os` over car-platform: the one link probe, LCMapStringEx, GetFullPathNameW and `realpath`.
pub struct PlatformOs;

impl os::Os for PlatformOs {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }

    fn is_junction(&self, path: &Path) -> bool {
        car_platform::links::reparse_tag(path) == Some(car_platform::links::MOUNT_POINT_TAG)
    }

    fn normcase(&self, text: &[u16]) -> Vec<u16> {
        car_platform::widepath::normcase(text)
    }

    fn abspath(&self, text: &[u16]) -> Vec<u16> {
        let normal = os::normpath(text);
        car_platform::widepath::full_path(&normal).unwrap_or(normal)
    }

    fn resolve(&self, text: &[u16]) -> Result<Vec<u16>, &'static str> {
        match String::from_utf16(text) {
            Ok(plain) => Ok(car_platform::paths::realpath(&plain)
                .encode_utf16()
                .collect()),
            // Half of a pair: the key's `.encode("utf-8")` refuses it whatever the resolution says.
            Err(_) => Ok(text.to_vec()),
        }
    }
}

static OS: PlatformOs = PlatformOs;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn ok(value: Value) -> Value {
    object(vec![("ok", value)])
}

fn error(class: &str) -> Value {
    object(vec![("error", Value::from(class))])
}

fn settings_error(refused: &SettingsError) -> Value {
    match refused {
        SettingsError::Refused(text) => object(vec![
            ("error", Value::from("SettingsError")),
            ("message", Value::Str(text.clone())),
        ]),
        SettingsError::Unreadable { reason, transient } => object(vec![
            ("error", Value::from("Unreadable")),
            ("message", Value::Str(refused.message())),
            ("reason", Value::from(reason.as_str())),
            ("transient", Value::Bool(*transient)),
        ]),
        SettingsError::Raised(class) => error(class),
    }
}

fn config_failure(failure: &config::ConfigFailure) -> Value {
    match failure {
        config::ConfigFailure::ConfigError(text) => object(vec![
            ("error", Value::from("ConfigError")),
            ("message", Value::Str(text.clone())),
        ]),
        config::ConfigFailure::Raised(class) => error(class),
    }
}

fn of_py(found: Py<Value>) -> Value {
    match found {
        Ok(value) => ok(value),
        Err(class) => error(class),
    }
}

fn text(value: &Value) -> &str {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default(),
        _ => "",
    }
}

fn texts(items: Vec<&str>) -> Value {
    Value::Array(items.into_iter().map(Value::from).collect())
}

fn strings(items: Vec<String>) -> Value {
    Value::Array(items.into_iter().map(Value::from).collect())
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn unhex(value: &Value) -> Vec<u8> {
    let digits = text(value);
    (0..digits.len() / 2)
        .filter_map(|i| u8::from_str_radix(&digits[i * 2..i * 2 + 2], 16).ok())
        .collect()
}

fn own_spec(name: &Value) -> Option<&'static ownvalues::Own> {
    settings::own(text(name))
}

fn measured(found: Option<ownvalues::Measured>) -> Value {
    match found {
        None => Value::Null,
        Some(ownvalues::Measured::Number(number) | ownvalues::Measured::Minute(number)) => {
            Value::from(number)
        }
        Some(ownvalues::Measured::Days(mask)) => Value::Array(
            (0..7)
                .filter(|day| mask & (1 << day) != 0)
                .map(Value::from)
                .collect(),
        ),
    }
}

fn map_value(found: &Map) -> Value {
    Value::Object(found.clone())
}

fn managed_value(held: &managed::Managed) -> Value {
    object(vec![
        ("disable_auto_resume", Value::Bool(held.disable_auto_resume)),
        ("force_observe_only", Value::Bool(held.force_observe_only)),
        (
            "disable_update_check",
            Value::Bool(held.disable_update_check),
        ),
        ("disable_status_file", Value::Bool(held.disable_status_file)),
        (
            "max_recovery_attempts",
            held.max_recovery_attempts.map_or(Value::Null, Value::from),
        ),
        (
            "quiet_hours",
            Value::Array(held.quiet_hours.iter().map(map_value).collect()),
        ),
        (
            "disable_power_action",
            Value::Bool(held.disable_power_action),
        ),
        ("codes", texts(held.codes())),
        ("active", Value::Bool(held.active())),
        ("fields", texts(managed::fields(held))),
        ("ceilings", Value::Object(managed::ceilings(held))),
    ])
}

fn as_map(value: &Value) -> Map {
    match value {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    }
}

/// The policy values car-platform reads from a stand-in registry, as `policykeys.read()` hands them to `parse`.
fn registry_places(request: &Value) -> Value {
    use car_platform::registry::{FakeRegistry, Root, Value as Reg};
    use car_platform::registry_reads::{PolicyValue, read_policies};
    let root = |name: &Value| {
        if text(name) == "HKLM" {
            Root::LocalMachine
        } else {
            Root::CurrentUser
        }
    };
    let registry = FakeRegistry::new();
    let list = |key: &str| match request {
        Value::Object(map) => match map.get(key) {
            Some(Value::Array(items)) => items.clone(),
            _ => Vec::new(),
        },
        _ => Vec::new(),
    };
    for seed in list("seed") {
        let Value::Array(parts) = seed else { continue };
        let mut values: Vec<(String, Reg, u32)> = Vec::new();
        if let Some(Value::Object(named)) = parts.get(2) {
            for (name, pair) in named {
                let Value::Array(pair) = pair else { continue };
                let data = match &pair[0] {
                    Value::Str(found) => Reg::Str(found.as_str().unwrap_or_default().to_owned()),
                    Value::Int(found) => Reg::Int(found.as_u64().unwrap_or(0) as u32),
                    _ => Reg::Bytes(Vec::new()),
                };
                let kind = match &pair[1] {
                    Value::Int(found) => found.as_u64().unwrap_or(1) as u32,
                    _ => 1,
                };
                values.push((name.as_str().unwrap_or_default().to_owned(), data, kind));
            }
        }
        let borrowed: Vec<(&str, Reg, u32)> = values
            .iter()
            .map(|(n, v, k)| (n.as_str(), v.clone(), *k))
            .collect();
        registry.seed(root(&parts[0]), text(&parts[1]), &borrowed);
    }
    for deny in list("deny_keys") {
        let Value::Array(parts) = deny else { continue };
        registry.deny_key(root(&parts[0]), text(&parts[1]));
    }
    for deny in list("deny_values") {
        let Value::Array(parts) = deny else { continue };
        registry.deny_value(root(&parts[0]), text(&parts[1]), text(&parts[2]));
    }
    Value::Array(
        read_policies(&registry)
            .into_iter()
            .map(|place| {
                let mut entries = Map::new();
                for (name, found) in place {
                    let pair = match found {
                        PolicyValue::Data((Reg::Str(data), kind)) => {
                            vec![Value::from(data), Value::from(kind)]
                        }
                        PolicyValue::Data((Reg::Int(data), kind)) => {
                            vec![Value::from(data), Value::from(kind)]
                        }
                        PolicyValue::Data((Reg::Bytes(_), kind)) => {
                            vec![Value::Null, Value::from(kind)]
                        }
                        PolicyValue::Unreadable => vec![Value::Null, Value::from(-1)],
                    };
                    entries.insert(Str::from(name.as_str()), Value::Array(pair));
                }
                Value::Object(entries)
            })
            .collect(),
    )
}

// ------------------------------------------------------------------------------------------ files

/// A scratch folder of this process for one file case.
fn scratch(index: usize) -> PathBuf {
    let folder = std::env::temp_dir().join(format!("car-policy-{}-{index}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    let _ = std::fs::create_dir_all(&folder);
    folder
}

/// Lays out `setup` at `target`: absent, bytes (hex), a folder, or bytes held open with no sharing while the call runs.
fn lay(target: &Path, setup: &Value) -> Option<std::fs::File> {
    let get = |key: &str| match setup {
        Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
        _ => Value::Null,
    };
    match text(&get("kind")) {
        "bytes" | "locked" | "readonly" => {
            let _ = std::fs::write(target, unhex(&get("hex")));
            if text(&get("kind")) == "readonly"
                && let Ok(found) = std::fs::metadata(target)
            {
                let mut permissions = found.permissions();
                permissions.set_readonly(true);
                let _ = std::fs::set_permissions(target, permissions);
            }
            if text(&get("kind")) == "locked" {
                use std::os::windows::fs::OpenOptionsExt;
                return std::fs::OpenOptions::new()
                    .read(true)
                    .share_mode(0)
                    .open(target)
                    .ok();
            }
            None
        }
        "dir" => {
            let _ = std::fs::create_dir_all(target);
            None
        }
        _ => None,
    }
}

/// What is left at `target`, and the other names in its folder.
fn after(target: &Path) -> Value {
    let found = match std::fs::metadata(target) {
        Ok(meta) if meta.is_file() => {
            if meta.permissions().readonly() {
                let mut permissions = meta.permissions();
                // Windows: the read-only attribute alone, as Python's os.chmod clears it.
                #[allow(clippy::permissions_set_readonly_false)]
                permissions.set_readonly(false);
                let _ = std::fs::set_permissions(target, permissions);
            }
            std::fs::read(target)
                .map_or(Value::from("unreadable"), |bytes| Value::from(hex(&bytes)))
        }
        Ok(_) => Value::from("dir"),
        Err(_) => Value::Null,
    };
    let mut others: Vec<String> = std::fs::read_dir(target.parent().unwrap_or(Path::new(".")))
        .map(|listing| {
            listing
                .filter_map(Result::ok)
                .map(|entry| entry.file_name().to_string_lossy().into_owned())
                .filter(|name| Some(name.as_str()) != target.file_name().and_then(|n| n.to_str()))
                .collect()
        })
        .unwrap_or_default();
    others.sort();
    object(vec![("file", found), ("others", strings(others))])
}

fn settings_result(found: Result<Map, SettingsError>) -> Value {
    match found {
        Ok(values) => ok(Value::Object(values)),
        Err(refused) => settings_error(&refused),
    }
}

fn file_case(index: usize, setup: &Value, op: &str, argument: &Value) -> Value {
    let folder = scratch(index);
    let target = folder.join("config").join("settings.json");
    let _ = std::fs::create_dir_all(target.parent().unwrap_or(&folder));
    let held = lay(&target, setup);
    let result = match op {
        "read" => settings_result(settings::read(&OS, &target)),
        "load" => settings_result(settings::load(&OS, &target)),
        "save" => settings_result(settings::save(&OS, &target, argument)),
        "update" => settings_result(settings::update(&OS, &target, argument)),
        _ => error("NotPorted"),
    };
    drop(held);
    let left = after(&target);
    let _ = std::fs::remove_dir_all(&folder);
    object(vec![("result", result), ("after", left)])
}

/// The home a `config.*` case runs in: car-config's `Paths`, its `ensure()`.
struct ConfigHome(car_config::Paths);

impl config::Home for ConfigHome {
    fn settings_file(&self) -> PathBuf {
        PathBuf::from(&self.0.settings_file)
    }

    fn ensure(&self) -> Result<(), config::ConfigFailure> {
        self.0
            .ensure()
            .map_err(|refused| config::ConfigFailure::ConfigError(Str::from(refused.0)))
    }
}

fn config_case(index: usize, setup: &Value, op: &str, argument: &Value) -> Value {
    let folder = scratch(index);
    let home = folder.join("home");
    let target = home.join("config").join("settings.json");
    let _ = std::fs::create_dir_all(target.parent().unwrap_or(&folder));
    let held = lay(&target, setup);
    let no_env = |_: &str| None;
    let paths = car_config::Paths::new(
        Some(&home.to_string_lossy()),
        &folder.to_string_lossy(),
        &no_env,
        car_config::Os::here(false, crate::links::for_config()),
    );
    let result = match paths {
        Err(class) => error(class),
        Ok(paths) => {
            let home = ConfigHome(paths);
            let answer = match op {
                "load" => config::load_settings(&OS, &home),
                "save" => config::save_settings(&OS, &home, argument),
                "update" => config::update_settings(&OS, &home, argument),
                _ => Err(config::ConfigFailure::Raised("NotPorted")),
            };
            match answer {
                Ok(values) => ok(Value::Object(values)),
                Err(failure) => config_failure(&failure),
            }
        }
    };
    drop(held);
    let left = after(&target);
    let _ = std::fs::remove_dir_all(&folder);
    object(vec![("result", result), ("after", left)])
}

fn status_case(index: usize, setup: &Value, op: &str, argument: &Value) -> Value {
    let folder = scratch(index);
    let target = folder.join("status.json");
    let held = lay(&target, setup);
    let result = match op {
        "write" => match statusfile::write(&OS, &target, argument) {
            Ok(()) => ok(Value::Null),
            Err(class) => error(class),
        },
        "remove" => of_py(statusfile::remove(&OS, &target).map(Value::Bool)),
        "ours" => of_py(statusfile::ours(&OS, &target).map(Value::Bool)),
        _ => error("NotPorted"),
    };
    drop(held);
    let left = after(&target);
    let _ = std::fs::remove_dir_all(&folder);
    object(vec![("result", result), ("after", left)])
}

// ------------------------------------------------------------------------------------------ the plug

/// A plug that answers one word at every decision point, or raises (`None`): `consult`'s filter, point by point.
struct Answering(Option<Alternative>);

impl Answering {
    fn answer(&self) -> Result<Answer<Alternative>, HookFailed> {
        self.0.map(Answer::Is).ok_or(HookFailed)
    }
}

impl Plug for Answering {
    fn edition(&self) -> plug::Edition {
        plug::Edition::Advanced
    }
    fn gate(&self, _: &str, _: &Value, _: &Value) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn outcome(&self, _: &Value, _: &str) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn schedule(&self, _: &Value, _: &Value) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn claim_ledger(
        &self,
        _: &mut dyn plug::Ledger,
        _: &Value,
        _: f64,
        _: &[Point],
    ) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn supervise(&self, _: &Value) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn delivery(&self, _: &Value) -> plug::Hook<Alternative> {
        self.answer()
    }
    fn admission(&self, _: &Value) -> plug::Hook<Alternative> {
        self.answer()
    }
}

/// A plug that wants P21 and answers it with one value: `Guarded.power`'s check, end to end.
struct Powered(Value);

impl Plug for Powered {
    fn edition(&self) -> plug::Edition {
        plug::Edition::Advanced
    }
    fn wants(&self, point: Point) -> Result<bool, HookFailed> {
        Ok(point == Point::Power)
    }
    fn power(&self, _: &Value) -> plug::Hook<Value> {
        Ok(Answer::Is(self.0.clone()))
    }
}

struct NoLedger;
impl plug::Ledger for NoLedger {}
struct NoView;
impl plug::View for NoView {}

fn alternative_value(found: Answer<Alternative>) -> Value {
    match found {
        Answer::Defer => Value::from("DEFER"),
        Answer::Is(word) => Value::from(word.as_str()),
    }
}

/// `consult` at a decision point, for a plug answering `word` (null: a hook that raises): [answer, failures].
fn consult(point: &str, word: &Value) -> Py<Value> {
    let point = Point::parse(point).ok_or("ValueError")?;
    let answering = match word {
        Value::Null => None,
        other => Some(Alternative::parse(text(other)).ok_or("ValueError")?),
    };
    let guarded = Guarded::new(Box::new(Answering(answering)));
    let record = Value::Object(Map::new());
    let answer = match point {
        Point::Gates => guarded.gate("consent", &record, &record),
        Point::Outcome => guarded.outcome(&record, "recovered"),
        Point::Schedule => guarded.schedule(&record, &Value::Float(0.0)),
        Point::ClaimLedger => guarded.claim_ledger(&mut NoLedger, &record, 0.0, &[]),
        Point::Supervision => guarded.supervise(&record),
        Point::Delivery => guarded.delivery(&record),
        Point::Admission => guarded.admission(&record),
        _ => return Err("ValueError"),
    };
    Ok(Value::Array(vec![
        alternative_value(answer),
        Value::from(guarded.failures() as i64),
    ]))
}

/// What NULL answers at every hook, and what core takes of it through `Guarded` - in the reference's own words.
fn null_answers() -> Value {
    let null = &plug::NULL;
    let record = Value::Object(Map::new());
    let defer = |found: bool| Value::from(if found { "DEFER" } else { "?" });
    let is_defer = |answer: &Result<Answer<()>, HookFailed>| matches!(answer, Ok(Answer::Defer));
    let decided = |answer: plug::Hook<Alternative>| matches!(answer, Ok(Answer::Defer));
    let hooks = object(vec![
        (
            "records",
            defer(matches!(null.records(&NoView), Ok(Answer::Defer))),
        ),
        (
            "gate",
            defer(decided(null.gate("consent", &record, &record))),
        ),
        (
            "text",
            defer(matches!(
                null.text(&record, &Str::from("x")),
                Ok(Answer::Defer)
            )),
        ),
        (
            "sender",
            Value::from(if matches!(null.sender(&record), Ok(Answer::Defer)) {
                "BACKEND"
            } else {
                "?"
            }),
        ),
        (
            "outcome",
            defer(decided(null.outcome(&record, "recovered"))),
        ),
        (
            "schedule",
            defer(decided(null.schedule(&record, &Value::Float(0.0)))),
        ),
        (
            "tick",
            defer(matches!(null.tick(&NoView), Ok(Answer::Defer))),
        ),
        (
            "start_route",
            defer(matches!(null.start_route(&record), Ok(Answer::Defer))),
        ),
        (
            "surface",
            defer(matches!(
                null.surface(plug::Surface::Status, &record),
                Ok(Answer::Defer)
            )),
        ),
        (
            "claim_ledger",
            defer(decided(null.claim_ledger(&mut NoLedger, &record, 0.0, &[]))),
        ),
        (
            "partition",
            defer(matches!(null.partition(&[]), Ok(Answer::Defer))),
        ),
        ("supervise", defer(decided(null.supervise(&record)))),
        ("moved", defer(is_defer(&null.moved(&record, "recovered")))),
        ("delivery", defer(decided(null.delivery(&record)))),
        (
            "unloaded",
            defer(matches!(null.unloaded(&record), Ok(Answer::Defer))),
        ),
        ("admission", defer(decided(null.admission(&record)))),
        (
            "sessions",
            defer(matches!(null.sessions(), Ok(Answer::Defer))),
        ),
        (
            "eligibility",
            defer(matches!(null.eligibility(), Ok(Answer::Defer))),
        ),
        ("notice", defer(is_defer(&null.notice(&record)))),
        (
            "power",
            defer(matches!(null.power(&record), Ok(Answer::Defer))),
        ),
        (
            "resident",
            defer(matches!(null.resident(&NoView), Ok(Answer::Defer))),
        ),
    ]);
    let points: Vec<&str> = Point::ALL.iter().map(|point| point.as_str()).collect();
    let wants = Value::Array(
        Point::ALL
            .iter()
            .map(|point| Value::Bool(null.wants(*point).unwrap_or(true)))
            .collect(),
    );
    let guarded = Guarded::null();
    let told = std::cell::Cell::new(false);
    guarded.notice(&|| {
        told.set(true);
        Some(Value::Null)
    });
    let sender = match guarded.sender(&record) {
        plug::Sender::Backend => "backend",
        plug::Sender::Channel { .. } => "channel",
    };
    let unloaded = matches!(guarded.unloaded(&record), plug::UnloadedAnswer::Defer);
    let held = object(vec![
        ("null", Value::Bool(guarded.is_null())),
        ("edition", Value::from(guarded.edition().as_str())),
        ("badge", Value::from(guarded.badge())),
        (
            "records",
            Value::Array(guarded.records(&NoView).unwrap_or_default()),
        ),
        (
            "gate",
            alternative_value(guarded.gate("consent", &record, &record)),
        ),
        (
            "text",
            Value::from(
                if matches!(guarded.text(&record, &Str::from("x")), Answer::Defer) {
                    "DEFER"
                } else {
                    "?"
                },
            ),
        ),
        ("sender", Value::from(sender)),
        (
            "outcome",
            alternative_value(guarded.outcome(&record, "recovered")),
        ),
        (
            "schedule",
            alternative_value(guarded.schedule(&record, &Value::Float(0.0))),
        ),
        (
            "tick",
            Value::from(if matches!(guarded.tick(&NoView), Answer::Defer) {
                "DEFER"
            } else {
                "?"
            }),
        ),
        (
            "resident",
            Value::from(if matches!(guarded.resident(&NoView), Answer::Defer) {
                "DEFER"
            } else {
                "?"
            }),
        ),
        (
            "start_route",
            Value::from(if matches!(guarded.start_route(&record), Answer::Defer) {
                "DEFER"
            } else {
                "?"
            }),
        ),
        (
            "surface",
            match guarded.surface(plug::Surface::Status, &record) {
                Answer::Defer => Value::from("DEFER"),
                Answer::Is(found) => found,
            },
        ),
        (
            "claim_ledger",
            Value::Array(vec![
                alternative_value(
                    guarded
                        .claim_ledger_checked(&mut NoLedger, &record, 0.0, &[])
                        .0,
                ),
                Value::Bool(false),
            ]),
        ),
        ("partition", Value::from(guarded.partition(&[]))),
        ("supervise", alternative_value(guarded.supervise(&record))),
        (
            "notice",
            if told.get() {
                Value::from("made")
            } else {
                Value::Null
            },
        ),
        ("power", guarded.power(&record).unwrap_or(Value::Null)),
        ("delivery", alternative_value(guarded.delivery(&record))),
        (
            "unloaded",
            Value::from(if unloaded { "DEFER" } else { "?" }),
        ),
        ("admission", alternative_value(guarded.admission(&record))),
        ("eligibility", strings(guarded.eligibility())),
        ("sessions", strings(guarded.sessions())),
        (
            "wants",
            Value::Array(
                Point::ALL
                    .iter()
                    .map(|point| Value::Bool(guarded.wants(*point)))
                    .collect(),
            ),
        ),
        ("start_held", guarded.start_held()),
        ("supervise_held", guarded.supervise_held()),
        ("failures", Value::from(guarded.failures() as i64)),
        ("shown", Value::from(plug::edition::shown(&guarded))),
    ]);
    guarded.codex("codex.exe", "home");
    guarded.conversation_off("0a1b2c3d-0001-7000-8000-000000000001");
    object(vec![
        ("edition", Value::from(null.edition().as_str())),
        ("badge", Value::from(null.badge())),
        ("hooks", hooks),
        ("points", texts(points)),
        ("wants", wants),
        (
            "edition_changed",
            if null.edition_changed(plug::Edition::Advanced).is_ok() {
                Value::Null
            } else {
                Value::from("?")
            },
        ),
        (
            "codex",
            if null.codex("codex.exe", "home").is_ok() {
                Value::Null
            } else {
                Value::from("?")
            },
        ),
        (
            "conversation_off",
            if null.conversation_off("x").is_ok() {
                Value::Null
            } else {
                Value::from("?")
            },
        ),
        ("guarded", held),
        ("failures_after", Value::from(guarded.failures() as i64)),
    ])
}

/// The interface's tables, as the reference's module holds them (sets sorted).
fn plug_tables() -> Value {
    let words = |items: &[Alternative]| {
        let mut listed: Vec<&str> = items.iter().map(|word| word.as_str()).collect();
        listed.sort_unstable();
        texts(listed)
    };
    let mut hooks = Map::new();
    let mut alternatives = Map::new();
    let mut every: Vec<Alternative> = plug::QUEUED.to_vec();
    for point in Point::ALL {
        hooks.insert(
            Str::from(point.as_str()),
            Value::from(plug::hook_name(*point)),
        );
        if let Some(accepted) = plug::alternatives(*point) {
            every.extend(accepted.iter().copied());
            alternatives.insert(Str::from(point.as_str()), words(&accepted));
        }
    }
    every.sort_unstable_by_key(|word| word.as_str());
    every.dedup();
    let mut paced = Map::new();
    for word in Alternative::ALL {
        if let Some(kind) = plug::paced_as(*word) {
            paced.insert(Str::from(word.as_str()), Value::from(kind));
        }
    }
    object(vec![
        ("PLUG_API", Value::from(plug::PLUG_API)),
        (
            "POINTS",
            texts(Point::ALL.iter().map(|point| point.as_str()).collect()),
        ),
        ("POWER_TASKS", texts(plug::POWER_TASKS.to_vec())),
        ("POWER_THREADS", Value::from(plug::POWER_THREADS as i64)),
        ("EXTRA", Value::from(plug::EXTRA)),
        ("HOOKS", Value::Object(hooks)),
        ("ALTERNATIVES", Value::Object(alternatives)),
        ("PACED_AS", Value::Object(paced)),
        ("QUEUED", words(plug::QUEUED)),
        ("ANSWERS", words(&every)),
        ("RECORDS_LIMIT", Value::from(hands::RECORDS_LIMIT as i64)),
        ("MAX_WORKERS", Value::from(hands::MAX_WORKERS)),
        ("WORDS_LIMIT", Value::from(hands::WORDS_LIMIT as i64)),
        ("ERRAND_GUARDS", Value::from(hands::ERRAND_GUARDS as i64)),
        ("NOT_LOADED", Value::from(plug::edition::NOT_LOADED)),
    ])
}

/// `[kind, items]`: a set or tuple (`"tuple"`) as P18/P19 answer it, or any other value (`"other"`).
fn collection(value: &Value) -> Option<Vec<Value>> {
    match value {
        Value::Array(parts) if parts.len() == 2 && text(&parts[0]) == "tuple" => match &parts[1] {
            Value::Array(items) => Some(items.clone()),
            _ => None,
        },
        _ => None,
    }
}

// ------------------------------------------------------------------------------------------ the cases

/// Arguments of one case.
struct Args<'a>(&'a [Value]);

impl<'a> Args<'a> {
    fn get(&self, at: usize) -> &'a Value {
        static NULL: Value = Value::Null;
        self.0.get(at).unwrap_or(&NULL)
    }
}

fn facts(value: &Value) -> poweraction::Facts {
    let map = as_map(value);
    let get = |key: &str| map.get(key).cloned();
    let mut facts = poweraction::Facts::new(get("now").unwrap_or(Value::Float(0.0)));
    if let Some(read) = get("read") {
        facts.read = text(&read).to_owned();
    }
    if let Some(found) = get("document") {
        facts.document = found;
    }
    if let Some(found) = get("managed") {
        facts.managed = found;
    }
    if let Some(found) = get("ok") {
        facts.ok = found;
    }
    if let Some(found) = get("paused") {
        facts.paused = found;
    }
    if let Some(Value::Array(rows)) = get("rows") {
        facts.rows = rows;
    }
    if let Some(Value::Bool(saw)) = get("saw_open") {
        facts.saw_open = saw;
    }
    if let Some(found) = get("follow_window") {
        facts.follow_window = found;
    }
    if let Some(found) = get("tasks") {
        facts.tasks = found;
    }
    facts
}

fn case(index: usize, name: &str, a: &Args) -> Value {
    let words = |found: Option<&'static str>| found.map_or(Value::Null, Value::from);
    match name {
        // settings
        "settings.defaults" => ok(Value::Object(settings::defaults())),
        "settings.coerce" => ok(Value::Object(settings::coerce(&OS, a.get(0)))),
        "settings.validate" => settings_result(settings::validate_update(&OS, a.get(0))),
        "settings.migrate" => ok(Value::Object(settings::migrate(a.get(0)))),
        "settings.field_type" => ok(Value::from(settings::field_type(text(a.get(0))))),
        "settings.ranges" => {
            ok(settings::ranges(text(a.get(0))).map_or(Value::Null, Value::Object))
        }
        "settings.describe" => ok(Value::Array(schema::describe(&|| "en".to_owned()))),
        "settings.whole_text" => ok(Value::Bool(settings::whole_text(a.get(0)))),
        "settings.is_custom_text" => ok(Value::Bool(settings::is_custom_text(text(a.get(0))))),
        "settings.high_limits" => ok(texts(settings::high_limits(a.get(0)))),
        "settings.theme_preference" => ok(settings::theme_preference(a.get(0))),
        "settings.design_preference" => ok(settings::design_preference(a.get(0))),
        "settings.tier_of" => ok(settings::tier_of(a.get(0), a.get(1))),
        "settings.category_enabled" => {
            of_py(settings::category_enabled(a.get(0), text(a.get(1))).map(Value::Bool))
        }
        "settings.notification_enabled" => {
            of_py(settings::notification_enabled(a.get(0), text(a.get(1))).map(Value::Bool))
        }
        "settings.bytes" => match settings::file_bytes(&settings::coerce(&OS, a.get(0))) {
            Ok(bytes) => ok(Value::from(hex(&bytes))),
            Err(refused) => settings_error(&refused),
        },
        "settings.file" => ok(file_case(index, a.get(0), text(a.get(1)), a.get(2))),
        "config.file" => ok(config_case(index, a.get(0), text(a.get(1)), a.get(2))),
        // ownvalues
        "own.amount" => match own_spec(a.get(0)) {
            Some(spec) => ok(measured(ownvalues::amount(spec, a.get(1)))),
            None => error("KeyError"),
        },
        "own.canonical" => match own_spec(a.get(0)) {
            Some(spec) => {
                ok(ownvalues::canonical(Some(spec), a.get(1), &[]).unwrap_or(Value::Null))
            }
            None => error("KeyError"),
        },
        "own.published" => match own_spec(a.get(0)) {
            Some(spec) => ok(ownvalues::published(spec)),
            None => error("KeyError"),
        },
        // homes
        "homes.well_formed" => ok(Value::Bool(homes::well_formed(&OS, a.get(0)))),
        "homes.coerce" => ok(homes::coerce(&OS, a.get(0), &Value::Array(Vec::new()))),
        "homes.unmeasured" => ok(Value::Bool(homes::unmeasured(a.get(0)))),
        "homes.problem" => match a.get(0) {
            Value::Str(path) => ok(words(homes::problem(&OS, path))),
            _ => error("TypeError"),
        },
        "homes.key" => match a.get(0) {
            Value::Str(path) => match homes::key(&OS, path) {
                Ok(key) => ok(Value::from(key)),
                Err(class) => error(class),
            },
            _ => error("TypeError"),
        },
        "homes.as_written" => match a.get(0) {
            Value::Str(path) => ok(Value::Str(homes::as_written(&OS, path))),
            _ => error("TypeError"),
        },
        "homes.view" => of_py(homes::view(
            &OS,
            a.get(0),
            a.get(1),
            a.get(2),
            matches!(a.get(3), Value::Bool(true)),
        )),
        "homes.strict" => {
            let identity = |path: &Str| -> Option<Value> {
                std::fs::metadata(os::os_path(path))
                    .ok()
                    .filter(|meta| meta.is_dir())?;
                homes::key(&OS, path).ok().map(Value::from)
            };
            let default_home = match a.get(1) {
                Value::Str(home) => Some(home.clone()),
                _ => None,
            };
            match homes::strict(&OS, a.get(0), default_home.as_ref(), &identity) {
                Ok(()) => ok(Value::Null),
                Err(sentence) => object(vec![
                    ("error", Value::from("ValueError")),
                    ("message", Value::Str(sentence)),
                ]),
            }
        }
        // notice kinds
        "kinds.coerce" => ok(notice_kinds::coerce(a.get(0), &Value::Array(Vec::new()))),
        "kinds.register" => match notice_kinds::register(a.get(0), a.get(1), a.get(2)) {
            Ok(kind) => ok(Value::from(kind.id)),
            Err(sentence) => object(vec![
                ("error", Value::from("KindError")),
                ("message", Value::from(sentence)),
            ]),
        },
        "kinds.ids" => ok(strings(notice_kinds::ids())),
        "kinds.chosen" => {
            let mut chosen = notice_kinds::chosen(a.get(0));
            chosen.sort();
            chosen.dedup();
            ok(strings(chosen))
        }
        "kinds.stays" => ok(Value::Bool(notice_kinds::stays(text(a.get(0)), a.get(1)))),
        "kinds.labels" => ok(notice_kinds::edition_labels(text(a.get(0)))),
        // memory guard
        "mem.mode" => ok(Value::from(memguard::mode(a.get(0)))),
        "mem.limit_mib" => ok(Value::from(memguard::limit_mib(a.get(0)))),
        "mem.mib" => ok(memguard::mib(a.get(0))),
        "mem.verdict" => ok(Value::from(memguard::verdict(a.get(0), a.get(1), a.get(2)))),
        // managed
        "managed.parse" => ok(managed_value(&managed::parse(a.get(0)))),
        "managed.registry" => {
            let places = registry_places(a.get(0));
            ok(object(vec![
                ("places", places.clone()),
                ("managed", managed_value(&managed::parse(&places))),
            ]))
        }
        "managed.quiet_window" => {
            ok(managed::quiet_window(a.get(0)).map_or(Value::Null, Value::Object))
        }
        "managed.clamp" => ok(Value::Object(managed::clamp(
            &as_map(a.get(1)),
            &managed::parse(a.get(0)),
        ))),
        "managed.admit" => {
            let (kept, refused) = managed::admit(
                &as_map(a.get(1)),
                &as_map(a.get(2)),
                &managed::parse(a.get(0)),
            );
            ok(Value::Array(vec![
                Value::Object(kept),
                refused.map_or(Value::Null, Value::Str),
            ]))
        }
        "managed.quiet_sources" => ok(Value::Array(managed::quiet_sources(
            a.get(1),
            &managed::parse(a.get(0)),
        ))),
        // status file
        "status.wanted" => ok(Value::Bool(statusfile::wanted(a.get(0)))),
        "status.content" => {
            let k = as_map(a.get(0));
            let get = |key: &str| k.get(key).cloned().unwrap_or(Value::Null);
            of_py(statusfile::content(
                &get("now"),
                &get("version"),
                &get("running"),
                &get("enabled"),
                &get("observe_only"),
                &get("engine"),
                &get("rows"),
                &get("reading"),
            ))
        }
        "status.clean" => of_py(statusfile::clean(a.get(0))),
        "status.file" => ok(status_case(index, a.get(0), text(a.get(1)), a.get(2))),
        // power action
        "power.read_document" => of_py(poweraction::read_document(a.get(0), a.get(1))),
        "power.blank" => ok(poweraction::blank()),
        "power.view" => of_py(poweraction::view(a.get(0))),
        "power.for_tasks" => ok(Value::Bool(poweraction::for_tasks(a.get(0)))),
        "power.choice_problem" => {
            ok(poweraction::choice_problem(a.get(0)).map_or(Value::Null, Value::from))
        }
        "power.is_member" => of_py(poweraction::is_member(a.get(0), a.get(1)).map(Value::Bool)),
        "power.is_open" => of_py(poweraction::is_open(a.get(0)).map(Value::Bool)),
        "power.classify" => of_py(poweraction::classify(a.get(0)).map(words)),
        "power.met" => {
            let classes: Vec<Option<&str>> = match a.get(1) {
                Value::Array(items) => items
                    .iter()
                    .map(|item| match text(item) {
                        "success" => Some("success"),
                        "person" => Some("person"),
                        "other" => Some("other"),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            ok(Value::Bool(poweraction::met(a.get(0), &classes)))
        }
        "power.newest" => match a.get(0) {
            Value::Array(rows) => of_py(poweraction::newest(rows)),
            _ => error("TypeError"),
        },
        "power.decide" => match poweraction::decide(&facts(a.get(0))) {
            Ok(found) => ok(Value::Array(vec![
                Value::from(found.verdict),
                words(found.word),
                Value::Bool(found.saw_open),
            ])),
            Err(class) => error(class),
        },
        "power.judge_activity" => ok(words(poweraction::judge_activity(a.get(0)))),
        "power.judge_presence" => ok(words(poweraction::judge_presence(
            a.get(0),
            a.get(1),
            a.get(2),
        ))),
        "power.countdown_holds" => of_py(
            poweraction::countdown_holds(a.get(0), a.get(1), a.get(2), a.get(3)).map(Value::Bool),
        ),
        // demo, self-check
        "demo.detail" => of_py(demo::detail(a.get(0))),
        "demo.rows" => of_py(demo::rows(a.get(0))),
        "selfcheck" => of_py(selfcheck::self_check(a.get(0), a.get(1))),
        // the plug
        "plug.tables" => ok(plug_tables()),
        "plug.null" => ok(null_answers()),
        "plug.consult" => of_py(consult(text(a.get(0)), a.get(1))),
        "plug.records_of" => {
            let items = match a.get(0) {
                Value::Array(items) => Some(items.as_slice()),
                _ => None,
            };
            of_py(hands::records_of(items).map(Value::Array))
        }
        "plug.workers" => ok(Value::from(hands::workers(Some(a.get(0))))),
        "plug.fields" => ok(hands::fields(a.get(0)).unwrap_or_else(|| Value::from("DEFER"))),
        "plug.kinds_of" => ok(strings(hands::kinds_of(collection(a.get(0)).as_deref()))),
        "plug.widening_of" => ok(strings(hands::widening_of(collection(a.get(0)).as_deref()))),
        "plug.power" => {
            let guarded = Guarded::new(Box::new(Powered(a.get(0).clone())));
            let facts = Value::Object(Map::new());
            ok(guarded.power(&facts).unwrap_or(Value::Null))
        }
        "policy.vocab" => ok(car_machine::vocab::export(&[
            car_policy::settings::vocab_gen::MODULES,
            car_policy::plug::vocab_gen::MODULES,
        ])),
        "edition.name" => ok(Value::from(
            plug::edition::name(Path::new(text(a.get(0)))).as_str(),
        )),
        "edition.cached_copy" => ok(plug::edition::cached_copy(
            Path::new(text(a.get(0))),
            &car_platform::links::is_symlink,
        )
        .map_or(Value::Null, |found| Value::from(found.as_str()))),
        _ => error(&format!("NotPorted:{name}")),
    }
}

/// `policy.batch`: every case of `cases`, in order.
pub fn batch(cases: &Value) -> Value {
    let Value::Array(cases) = cases else {
        return Value::Null;
    };
    let mut answers = Vec::with_capacity(cases.len());
    for (index, each) in cases.iter().enumerate() {
        let Value::Array(parts) = each else {
            answers.push(error("TypeError"));
            continue;
        };
        let name = text(parts.first().unwrap_or(&Value::Null)).to_owned();
        answers.push(case(index, &name, &Args(&parts[1..])));
    }
    Value::Array(answers)
}

/// The request line as Python's `json.loads` reads it: `(id, the reply)` for a `policy.*` call, or None.
pub fn answer(line: &str) -> Option<(Value, Value)> {
    let Ok(Value::Object(request)) = car_machine::compat::loads(line) else {
        return None;
    };
    let id = match request.get("id") {
        Some(Value::Int(int)) => int.as_i64().map_or(Value::Null, Value::from),
        _ => Value::Null,
    };
    match request.get("call") {
        Some(call) if text(call) == "policy.batch" => {
            let cases = request.get("cases").cloned().unwrap_or(Value::Null);
            Some((id, ok_reply(batch(&cases))))
        }
        _ => None,
    }
}

fn ok_reply(value: Value) -> Value {
    object(vec![("ok", Value::Bool(true)), ("value", value)])
}

//! Seat S7.4b: `measure.py`'s probes that work on a scratch folder or Codex home of their own, or on a hand - MB, MB2,
//! MF, MHK, M4B, MANCHOR, MWAKE, MIMG - and their helpers (`_config_value`, `_version_of`, `_listed`, `_model_of`,
//! `_default_model`, `_one_turn`, `_resumed_model`, `_schema_documents`, `_definitions`, `_enum_words`, `_strings`,
//! `_generated_schema`, `_feature`, `_hook_words`, `_manchor_read`, `_kept`, `_power_source`, `_queued_images`,
//! `_mimg_pictures`, `_queued_image_count`), a child of [`crate::measure`].
//!
//! A scratch folder is `tempfile.mkdtemp`'s (car-adv's `autocheck::mkdtemp`) and is removed however the probe ends;
//! no configuration of the person's is opened.

use std::path::{Path, PathBuf};

use car_machine::json::{Map, Value};
use car_machine::pyval::{self, Num};

use super::held::{HOOK_INPUT_KEYS, client_recorded, letters, seconds, turn_started_after};
use super::stage4::{follow, unsubscribed};
use super::{
    Context, Found, M2B_PROMPT, MeasureSession, Raised, Res, as_text, await_taken_on,
    await_turn_value, blocked, get, is_dict, is_str_eq, key, object, observed, started_turn_id,
    text,
};
use crate::vocabulary::{Measurement, ObservedWord, Verdict};

pub const RETRY_KEYS: [&str; 2] = [
    "model_providers.openai.request_max_retries",
    "model_providers.openai.stream_max_retries",
];
pub const MB_VALUE: i64 = 8;
pub const SCHEMA_FILES: usize = 2000;
pub const SCHEMA_FILE_BYTES: u64 = 4 * 1024 * 1024;
pub const SCHEMA_ARGUMENTS: [&str; 3] = ["app-server", "generate-json-schema", "--out"];
pub const MWAKE_SECONDS: i64 = 180;
pub const MWAKE_BOUND: i64 = 900;
pub const MWAKE_SLEPT: i64 = 60;
pub const MWAKE_LATE: i64 = 120;
pub const MANCHOR_EARLY: i64 = 300;
pub const MANCHOR_LATE: i64 = 60;
pub const SAMPLE_MIMG_CLIENT_IDS: [&str; 2] = [
    "00000000-0000-7000-8000-00000000000b",
    "00000000-0000-7000-8000-00000000000c",
];
pub const MIMG_PNG_BASE64: &str = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
pub const MIMG_IMAGE_TYPES: [&str; 2] = ["image", "localImage"];
pub const MIMG_UNDER: usize = 1024;

fn os_error<E>(_: E) -> Raised {
    Raised::Other("OSError".into())
}

/// `scratch = Path(tempfile.mkdtemp(prefix=...)); try: body finally: shutil.rmtree(scratch, ignore_errors=True)`.
pub(super) fn with_scratch<T>(
    ctx: &mut Context<'_>,
    prefix: &str,
    body: impl FnOnce(&mut Context<'_>, &Path) -> Res<T>,
) -> Res<T> {
    let scratch = crate::autocheck::mkdtemp(prefix).map_err(os_error)?;
    let answer = body(ctx, &scratch);
    let _ = std::fs::remove_dir_all(&scratch);
    answer
}

fn path_value(path: &Path) -> Value {
    text(&path.to_string_lossy())
}

/// `ctx.scratch_cli(home, arguments)`: the engine's stdout on the scratch home, or None.
fn scratch_cli(ctx: &mut Context<'_>, home: &Path, arguments: &[String]) -> Option<String> {
    let given = Value::Array(arguments.iter().map(|each| text(each)).collect());
    match ctx.hand("scratch_cli", &[path_value(home), given]) {
        Some(Value::Str(found)) => Some(car_machine::pytext::py_str(&Value::Str(found))),
        _ => None,
    }
}

/// `pathlib`'s Windows ordering of two paths: part by part, each case-folded as `normcase` folds it.
fn path_order(a: &Path, b: &Path) -> std::cmp::Ordering {
    let parts = |path: &Path| -> Vec<String> {
        path.components()
            .map(|part| part.as_os_str().to_string_lossy().to_lowercase())
            .collect()
    };
    parts(a).cmp(&parts(b))
}

fn walk(folder: &Path, found: &mut Vec<PathBuf>) {
    let Ok(entries) = std::fs::read_dir(folder) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let link = car_platform::links::is_symlink(&path);
        let name = entry.file_name().to_string_lossy().to_lowercase();
        if name.ends_with(".json") {
            found.push(path.clone());
        }
        if !link && entry.file_type().is_ok_and(|kind| kind.is_dir()) {
            walk(&path, found);
        }
    }
}

/// `_schema_documents(folder)`: (stem, document) of each JSON file a schema generation wrote, a link never followed.
fn schema_documents(folder: &Path) -> Res<Vec<(String, Value)>> {
    let mut paths = Vec::new();
    walk(folder, &mut paths);
    paths.sort_by(|a, b| path_order(a, b));
    paths.truncate(SCHEMA_FILES);
    let mut found = Vec::new();
    for path in paths {
        if car_platform::links::is_symlink(&path) {
            continue;
        }
        let Ok(meta) = std::fs::metadata(&path) else {
            continue;
        };
        if meta.len() > SCHEMA_FILE_BYTES {
            continue;
        }
        let Ok(raw) = std::fs::read(&path) else {
            continue;
        };
        let Ok(decoded) = String::from_utf8(raw) else {
            continue;
        };
        // `read_text` reads with universal newlines.
        let decoded = decoded.replace("\r\n", "\n").replace('\r', "\n");
        let document = match car_machine::compat::loads(&decoded) {
            Ok(document) => document,
            Err(car_machine::compat::LoadsError::Recursion) => {
                return Err(Raised::Other("RecursionError".into()));
            }
            Err(_) => continue,
        };
        let stem = path
            .file_stem()
            .map(|stem| stem.to_string_lossy().into_owned())
            .unwrap_or_default();
        found.push((stem, document));
    }
    Ok(found)
}

/// `_generated_schema(ctx, scratch)`.
pub(super) fn generated_schema(ctx: &mut Context<'_>, scratch: &Path) -> Res<Vec<(String, Value)>> {
    let (home, out) = (scratch.join("codex-home"), scratch.join("schema"));
    for folder in [&home, &out] {
        if let Err(error) = std::fs::create_dir(folder)
            && error.kind() != std::io::ErrorKind::AlreadyExists
        {
            return Err(os_error(error));
        }
    }
    let mut arguments: Vec<String> = SCHEMA_ARGUMENTS
        .iter()
        .map(|each| (*each).to_owned())
        .collect();
    arguments.push(out.to_string_lossy().into_owned());
    if scratch_cli(ctx, &home, &arguments).is_none() {
        return Ok(vec![]);
    }
    schema_documents(&out)
}

/// `_strings(value)`: every string, keys and values alike.
pub(super) fn strings(value: &Value, each: &mut dyn FnMut(&str)) {
    match value {
        Value::Str(found) => each(&car_machine::pytext::py_str(&Value::Str(found.clone()))),
        Value::Object(map) => {
            for (name, item) in map {
                each(&car_machine::pytext::py_str(&Value::Str(name.clone())));
                strings(item, each);
            }
        }
        Value::Array(items) => {
            for item in items {
                strings(item, each);
            }
        }
        _ => {}
    }
}

/// `for item in value or ()`: a list's items, a dict's keys, a text's characters; a number that is true is the
/// reference's TypeError.
fn iterate(value: Option<&Value>) -> Res<Vec<Value>> {
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

/// `_enum_words(schema)`.
fn enum_words(schema: Option<&Value>, words: &mut Vec<String>) -> Res<()> {
    let Some(schema) = schema.filter(|schema| is_dict(schema)) else {
        return Ok(());
    };
    let add = |word: String, words: &mut Vec<String>| {
        if !word.is_empty() && !words.contains(&word) {
            words.push(word);
        }
    };
    for word in iterate(get(schema, "enum"))? {
        add(letters(Some(&word)), words);
    }
    if let Some(constant) = get(schema, "const") {
        add(letters(Some(constant)), words);
    }
    for name in ["oneOf", "anyOf"] {
        for item in iterate(get(schema, name))? {
            enum_words(Some(&item), words)?;
        }
    }
    Ok(())
}

/// `_definitions(documents)`.
fn definitions(documents: &[(String, Value)]) -> Vec<(String, Value)> {
    let mut found = Vec::new();
    for (stem, document) in documents {
        if !is_dict(document) {
            continue;
        }
        found.push((stem.clone(), document.clone()));
        for name in ["definitions", "$defs"] {
            if let Some(Value::Object(table)) = get(document, name) {
                for (entry, schema) in table {
                    if is_dict(schema) {
                        found.push((
                            car_machine::pytext::py_str(&Value::Str(entry.clone())),
                            schema.clone(),
                        ));
                    }
                }
            }
        }
    }
    found
}

/// `_hook_words(documents)`.
fn hook_words(documents: &[(String, Value)]) -> Res<Vec<(String, Value)>> {
    let (mut events, mut sources, mut keys, mut decisions) = (vec![], vec![], vec![], vec![]);
    for (name, schema) in definitions(documents) {
        let word = letters(Some(&text(&name)));
        let empty = Value::Object(Map::new());
        let properties = get(&schema, "properties")
            .filter(|found| is_dict(found))
            .unwrap_or(&empty);
        if word == "hookeventname" {
            enum_words(Some(&schema), &mut events)?;
        } else if word == "hooksource" {
            enum_words(Some(&schema), &mut sources)?;
        } else if word.contains("stop") && (word.contains("input") || word.contains("payload")) {
            if let Value::Object(map) = properties {
                for name in map.keys() {
                    let found = letters(Some(&Value::Str(name.clone())));
                    if !keys.contains(&found) {
                        keys.push(found);
                    }
                }
            }
        } else if word.contains("stop") && word.contains("output") {
            enum_words(get(properties, "decision"), &mut decisions)?;
        }
    }
    let has = |words: &Vec<String>, wanted: &str| words.iter().any(|each| each == wanted);
    let mut found = vec![
        (
            "hook_event_names".to_owned(),
            Value::from(events.len() as i64),
        ),
        ("stop_event".to_owned(), Value::Bool(has(&events, "stop"))),
        ("hook_sources".to_owned(), Value::from(sources.len() as i64)),
        (
            "plugin_source".to_owned(),
            Value::Bool(has(&sources, "plugin")),
        ),
        ("stop_input_keys".to_owned(), Value::from(keys.len() as i64)),
        (
            "decision_words".to_owned(),
            Value::from(decisions.len() as i64),
        ),
        (
            "decision_block".to_owned(),
            Value::Bool(has(&decisions, "block")),
        ),
    ];
    for name in HOOK_INPUT_KEYS {
        found.push((
            format!("input_{name}"),
            Value::Bool(has(&keys, &letters(Some(&text(name))))),
        ));
    }
    Ok(found)
}

// ------------------------------------------------------------------------------------------------ MB
/// `_config_value(read, key)`.
pub(super) fn config_value(read: &Value, path: &str) -> Option<Value> {
    let mut value = get(read, "config")?;
    for part in path.split('.') {
        value = get(value, part)?;
    }
    Some(value.clone())
}

fn is_none(value: &Option<Value>) -> bool {
    matches!(value, None | Some(Value::Null))
}

/// `_version_of(read)`.
fn version_of(read: &Value) -> Value {
    if let Some(found @ (Value::Str(_) | Value::Int(_))) = get(read, "version") {
        return found.clone();
    }
    if let Some(Value::Array(layers)) = get(read, "layers") {
        for layer in layers {
            let Some(name) = get(layer, "name").filter(|name| is_dict(name)) else {
                continue;
            };
            if is_str_eq(get(name, "type"), "user") {
                return match get(layer, "version") {
                    Some(found @ Value::Str(_)) => found.clone(),
                    _ => Value::Null,
                };
            }
        }
    }
    Value::Null
}

fn equals(found: &Option<Value>, wanted: i64) -> bool {
    found
        .as_ref()
        .is_some_and(|found| pyval::eq(found, &Value::from(wanted)))
}

fn write_params(path: &str, value: Value, strategy: &str, version: Value) -> Option<Value> {
    Some(object(vec![
        ("keyPath", text(path)),
        ("value", value),
        ("mergeStrategy", text(strategy)),
        ("expectedVersion", version),
    ]))
}

impl Context<'_> {
    /// `ctx.open_scratch(home)`.
    fn open_scratch(&mut self, home: &Path) -> Res<Box<dyn MeasureSession>> {
        let measurement = self.measurement;
        let Some(factory) = self.seams.session_factory.as_mut() else {
            return Err(Raised::Unavailable("no session was provided"));
        };
        if !factory.takes_home() {
            return Err(Raised::Unavailable(
                "this session cannot be opened on a scratch Codex home",
            ));
        }
        factory.open(measurement, Some(home), None)
    }

    /// `ctx.open_with(config, home)`.
    fn open_with(
        &mut self,
        config: &[(String, String)],
        home: Option<&Path>,
    ) -> Res<Box<dyn MeasureSession>> {
        let measurement = self.measurement;
        let Some(factory) = self.seams.session_factory.as_mut() else {
            return Err(Raised::Unavailable("no session was provided"));
        };
        if !(factory.takes_home() && factory.takes_config()) {
            return Err(Raised::Unavailable(
                "this session cannot be opened with settings of its own",
            ));
        }
        factory.open(measurement, home, Some(config.to_vec()))
    }

    /// `with opened as session: body(session)`.
    fn within<T>(
        &mut self,
        mut session: Box<dyn MeasureSession>,
        body: impl FnOnce(&mut Self, &mut dyn MeasureSession) -> Res<T>,
    ) -> Res<T> {
        session.enter()?;
        let answer = body(self, session.as_mut());
        session.exit();
        answer
    }
}

pub(super) fn mb(ctx: &mut Context<'_>) -> Res<Found> {
    let (written, before, back, removed, conflict) =
        with_scratch(ctx, "car-mb-", |ctx, scratch| {
            let session = ctx.open_scratch(scratch)?;
            ctx.within(session, |_ctx, session| {
                let read = || Some(object(vec![("includeLayers", Value::Bool(true))]));
                let before = session.call("config/read", read())?;
                let mut back = before.clone();
                let mut written = Vec::new();
                for path in RETRY_KEYS {
                    written.push(session.call(
                        "config/value/write",
                        write_params(path, Value::from(MB_VALUE), "upsert", version_of(&back)),
                    )?);
                    back = session.call("config/read", read())?;
                }
                session.call(
                    "config/value/write",
                    write_params(RETRY_KEYS[0], Value::Null, "replace", version_of(&back)),
                )?;
                let removed = session.call("config/read", read())?;
                let conflict = match session.call(
                    "config/value/write",
                    write_params(
                        RETRY_KEYS[1],
                        Value::from(MB_VALUE + 1),
                        "upsert",
                        version_of(&before),
                    ),
                ) {
                    Ok(_) => false,
                    Err(Raised::Adapter { method, .. }) => method.is_some(),
                    Err(raised) => return Err(raised),
                };
                Ok((written, before, back, removed, conflict))
            })
        })?;
    let seen = [
        ("write_accepted", written.iter().all(is_dict)),
        (
            "read_back",
            RETRY_KEYS
                .iter()
                .all(|path| equals(&config_value(&back, path), MB_VALUE)),
        ),
        (
            "removal_restores",
            is_none(&config_value(&removed, RETRY_KEYS[0]))
                && is_none(&config_value(&before, RETRY_KEYS[0])),
        ),
        ("version_conflict_refused", conflict),
    ];
    let passed = seen.iter().all(|(_, value)| *value);
    let mut map: Map = seen
        .iter()
        .map(|(name, value)| (key(name), Value::Bool(*value)))
        .collect();
    map.insert(key("scratch_home"), Value::Bool(true));
    Ok((
        if passed { Verdict::Pass } else { Verdict::Fail },
        map,
        (!passed).then(|| {
            "a write, its read back, its removal or the stale version did not hold".to_owned()
        }),
    ))
}

// ------------------------------------------------------------------------------------------------ MB2
/// `_listed(listed, thread)`.
fn listed(found: &Value, thread: &str) -> bool {
    matches!(get(found, "data"), Some(Value::Array(rows)) if rows.iter().any(|row| is_dict(row) && is_str_eq(get(row, "id"), thread)))
}

fn list_params() -> Option<Value> {
    Some(object(vec![
        ("limit", Value::from(100i64)),
        ("sortKey", text("updated_at")),
    ]))
}

pub(super) fn mb2(ctx: &mut Context<'_>) -> Res<Found> {
    use crate::engine::retries::{BUILT_IN, DEFAULT_ATTEMPTS, PROVIDER, overrides};
    let mut settings: Vec<(String, String)> = crate::codex::headless::HEADLESS_CONFIG
        .iter()
        .map(|(name, value)| ((*name).to_owned(), (*value).to_owned()))
        .collect();
    settings.extend(
        overrides(&Value::from(DEFAULT_ATTEMPTS)).map_err(|raised| Raised::Other(raised.class))?,
    );
    let (read, written) = with_scratch(ctx, "car-mb2-", |ctx, scratch| {
        let session = ctx.open_with(&settings, Some(scratch))?;
        let read = ctx.within(session, |_ctx, session| {
            session.call(
                "config/read",
                Some(object(vec![("includeLayers", Value::Bool(true))])),
            )
        })?;
        Ok((read, scratch.join("config.toml").exists()))
    })?;
    let mut seen = observed(vec![
        ("scratch_home", Value::Bool(true)),
        (
            "override_in_force",
            Value::Bool(
                matches!(config_value(&read, "model_provider"), Some(Value::Str(found)) if found.as_bytes() == PROVIDER.as_bytes()),
            ),
        ),
        (
            "retries_read",
            Value::Bool(
                ["request_max_retries", "stream_max_retries"]
                    .iter()
                    .all(|name| {
                        equals(
                            &config_value(&read, &format!("model_providers.{PROVIDER}.{name}")),
                            DEFAULT_ATTEMPTS,
                        )
                    }),
            ),
        ),
        ("nothing_written", Value::Bool(!written)),
    ]);
    let flag = |seen: &Map, name: &str| matches!(seen.get(&key(name)), Some(Value::Bool(true)));
    if !(flag(&seen, "override_in_force") && flag(&seen, "nothing_written")) {
        return Ok((
            Verdict::Fail,
            seen,
            Some("our server did not take the retry provider, or it wrote a configuration".into()),
        ));
    }
    if !ctx.thread_given {
        return blocked(
            "the scratch part held: run mb2 again with -Thread <a throwaway conversation> for the turn",
            seen,
        );
    }
    let thread = ctx.probe_thread.clone();
    let session = ctx.open_with(&settings, None)?;
    let (signed_in, listed_ours, status) = ctx.within(session, |ctx, session| {
        let account = crate::codex::account::parse(
            &session.call("account/read", Some(Value::Object(Map::new())))?,
        );
        let signed_in = is_str_eq(get(&account, "kind"), "chatgpt");
        let listed_ours = listed(&session.call("thread/list", list_params())?, &thread);
        let mut status = None;
        if signed_in {
            session.call(
                "thread/resume",
                Some(object(vec![
                    ("threadId", text(&thread)),
                    ("modelProvider", text(PROVIDER)),
                ])),
            )?;
            let started = session.call(
                "turn/start",
                Some(object(vec![
                    ("threadId", text(&thread)),
                    (
                        "input",
                        Value::Array(vec![object(vec![
                            ("type", text("text")),
                            ("text", text(M2B_PROMPT)),
                        ])]),
                    ),
                ])),
            )?;
            // `(started.get("turn") or {}).get("id")`: a turn that is true and no dict has no `get`.
            let turn = match &started {
                Value::Object(_) => match get(&started, "turn") {
                    Some(turn) if pyval::truthy(turn) => match turn {
                        Value::Object(_) => get(turn, "id").cloned().unwrap_or(Value::Null),
                        _ => return Err(Raised::Other("AttributeError".into())),
                    },
                    _ => Value::Null,
                },
                _ => Value::Null,
            };
            if pyval::truthy(&turn) {
                let bound = ctx.timing.m6_turn;
                status = await_turn_value(ctx, session, Some(&turn), bound, None);
                if status.is_none() {
                    session.call(
                        "turn/interrupt",
                        Some(object(vec![
                            ("threadId", text(&thread)),
                            ("turnId", turn.clone()),
                        ])),
                    )?;
                }
            }
            session.call(
                "thread/unsubscribe",
                Some(object(vec![("threadId", text(&thread))])),
            )?;
        }
        Ok((signed_in, listed_ours, status))
    })?;
    seen.insert(key("signed_in_chatgpt"), Value::Bool(signed_in));
    seen.insert(key("listed_under_ours"), Value::Bool(listed_ours));
    seen.insert(
        key("turn_completed"),
        Value::Bool(status.as_deref() == Some("completed")),
    );
    let session = ctx.open_with(&[], None)?;
    let (found, after) = ctx.within(session, |_ctx, session| {
        let found = session.call(
            "thread/read",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("includeTurns", Value::Bool(false)),
            ])),
        )?;
        let after = session.call("thread/list", list_params())?;
        Ok((found, after))
    })?;
    let kept = get(&found, "thread")
        .filter(|found| is_dict(found))
        .is_some_and(|found| is_str_eq(get(found, "modelProvider"), BUILT_IN));
    seen.insert(key("thread_kept_openai"), Value::Bool(kept));
    seen.insert(key("listed_after"), Value::Bool(listed(&after, &thread)));
    if ![
        "signed_in_chatgpt",
        "turn_completed",
        "thread_kept_openai",
        "listed_after",
    ]
    .iter()
    .all(|name| flag(&seen, name))
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("no ChatGPT sign-in, no turn completed under the retry provider, or the conversation's provider rewritten or no longer listed".into()),
        ));
    }
    blocked(
        "confirm in the Codex app that the throwaway conversation is still in the sidebar, opens and shows the new turn, and that an older conversation is still listed, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MF
/// `_model_of(resumed)`.
fn model_of(resumed: &Value) -> Option<String> {
    as_text(get(resumed, "model")).filter(|model| !model.is_empty())
}

/// `_default_model(listed)`.
fn default_model(found: &Value) -> Option<Value> {
    let Some(Value::Array(data)) = get(found, "data") else {
        return None;
    };
    for entry in data {
        if is_dict(entry) && matches!(get(entry, "isDefault"), Some(Value::Bool(true))) {
            let model = match get(entry, "model") {
                Some(model) if pyval::truthy(model) => Some(model),
                _ => get(entry, "id"),
            };
            return match model {
                Some(Value::Str(found)) if !found.as_bytes().is_empty() => {
                    Some(Value::Str(found.clone()))
                }
                _ => None,
            };
        }
    }
    None
}

fn thread_resume(thread: &str, extra: Vec<(&str, Value)>) -> Option<Value> {
    let mut pairs = extra;
    pairs.push(("threadId", text(thread)));
    pairs.push(("excludeTurns", Value::Bool(true)));
    Some(object(pairs))
}

fn prompt_input() -> Value {
    Value::Array(vec![object(vec![
        ("type", text("text")),
        ("text", text(M2B_PROMPT)),
    ])])
}

/// `_resumed_model(ctx)`.
fn resumed_model(ctx: &mut Context<'_>) -> Res<Option<String>> {
    let thread = ctx.probe_thread.clone();
    ctx.with_session(|ctx, session| {
        let model = model_of(&session.call("thread/resume", thread_resume(&thread, vec![]))?);
        unsubscribed(ctx, session)?;
        Ok(model)
    })
}

pub(super) fn mf(ctx: &mut Context<'_>) -> Res<Found> {
    let thread = ctx.probe_thread.clone();
    let (original, default) = ctx.with_session(|ctx, session| {
        let original = model_of(&session.call("thread/resume", thread_resume(&thread, vec![]))?);
        let default = default_model(&session.call("model/list", Some(Value::Object(Map::new())))?);
        unsubscribed(ctx, session)?;
        Ok((original, default))
    })?;
    let differs = match (&default, &original) {
        (Some(Value::Str(default)), Some(original)) => default.as_bytes() != original.as_bytes(),
        _ => false,
    };
    let mut seen = observed(vec![
        ("default_found", Value::Bool(default.is_some())),
        ("default_differs", Value::Bool(differs)),
    ]);
    if !differs {
        return blocked(
            "name a throwaway conversation that is not on Codex's default model",
            seen,
        );
    }
    let default = default.unwrap_or(Value::Null);
    let original_value = original.as_deref().map_or(Value::Null, text);
    let status = ctx.with_session(|ctx, session| {
        session.call(
            "thread/resume",
            thread_resume(&thread, vec![("model", default.clone())]),
        )?;
        let started = session.call(
            "turn/start",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("input", prompt_input()),
            ])),
        )?;
        let turn = started_turn_id(&started);
        let bound = ctx.timing.m6_turn;
        let (status, _ended) = follow(ctx, session, turn.as_deref(), bound)?;
        unsubscribed(ctx, session)?;
        Ok(status)
    })?;
    let once = resumed_model(ctx)? == original;
    seen.insert(key("resume_override_session_only"), Value::Bool(once));
    ctx.with_session(|ctx, session| {
        session.call("thread/resume", thread_resume(&thread, vec![]))?;
        let started = session.call(
            "turn/start",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("model", default.clone()),
                ("input", prompt_input()),
            ])),
        )?;
        let turn = started_turn_id(&started);
        let bound = ctx.timing.m6_turn;
        follow(ctx, session, turn.as_deref(), bound)?;
        session.call(
            "thread/settings/update",
            Some(object(vec![
                ("threadId", text(&thread)),
                ("model", original_value.clone()),
            ])),
        )?;
        unsubscribed(ctx, session)?;
        Ok(())
    })?;
    let restored = resumed_model(ctx)? == original;
    seen.insert(key("restore_read_back"), Value::Bool(restored));
    if let Some(status) = status {
        seen.insert(key("turn_status"), text(&status));
    }
    let passed = once || restored;
    Ok((
        if passed { Verdict::Pass } else { Verdict::Fail },
        seen,
        (!passed).then(|| "neither route left the conversation on its own model".to_owned()),
    ))
}

// ------------------------------------------------------------------------------------------------ MHK, M4B
/// `_feature(text, name)`: (listed, on or None).
fn feature(found: Option<&str>, name: &str) -> (bool, Option<bool>) {
    let Some(found) = found else {
        return (false, None);
    };
    let Some(words) = crate::autocheck::feature_words(found, name) else {
        return (false, None);
    };
    let states: Vec<String> = words.iter().map(|word| word.to_lowercase()).collect();
    let any = |wanted: [&str; 4]| states.iter().any(|state| wanted.contains(&state.as_str()));
    if any(["true", "enabled", "on", "yes"]) {
        return (true, Some(true));
    }
    if any(["false", "disabled", "off", "no"]) {
        return (true, Some(false));
    }
    (true, None)
}

fn maybe_bool(found: Option<bool>) -> Value {
    found.map_or(Value::Null, Value::Bool)
}

pub(super) fn mhk(ctx: &mut Context<'_>) -> Res<Found> {
    let (documents, features) = with_scratch(ctx, "car-mhk-", |ctx, scratch| {
        let documents = generated_schema(ctx, scratch)?;
        let arguments = vec!["features".to_owned(), "list".to_owned()];
        let features = scratch_cli(ctx, &scratch.join("codex-home"), &arguments);
        Ok((documents, features))
    })?;
    let (listed_now, on) = feature(features.as_deref(), "plugin_hooks");
    let words = hook_words(&documents)?;
    let mut seen = observed(vec![
        ("features_read", Value::Bool(features.is_some())),
        ("plugin_hooks_listed", Value::Bool(listed_now)),
        ("plugin_hooks_on", maybe_bool(on)),
        ("schema_read", Value::Bool(!documents.is_empty())),
        ("scratch_home", Value::Bool(true)),
    ]);
    for (name, value) in words {
        seen.insert(key(&name), value);
    }
    if features.is_none() || documents.is_empty() {
        return blocked(
            "the engine could not be run on a scratch Codex home: check the Codex in force, then run mhk again",
            seen,
        );
    }
    if listed_now && matches!(seen.get(&key("stop_event")), Some(Value::Bool(true))) {
        return Ok((Verdict::Pass, seen, None));
    }
    Ok((
        Verdict::Fail,
        seen,
        Some("plugin hooks are not a feature, or Stop is not one of their events".into()),
    ))
}

pub(super) fn m4b(ctx: &mut Context<'_>) -> Res<Found> {
    let hooks = ctx.with_session(|_ctx, session| {
        session.call(
            "hooks/list",
            Some(object(vec![("cwds", Value::Array(vec![]))])),
        )
    })?;
    let ours = match ctx.hand("stop_hook", &[]) {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let commands: Vec<String> = iterate(get(&ours, "commands"))?
        .iter()
        .filter_map(|each| as_text(Some(each)))
        .collect();
    let mut listed_ours = false;
    if !commands.is_empty() {
        strings(&hooks, &mut |found: &str| {
            listed_ours = listed_ours || commands.iter().any(|each| each == found);
        });
    }
    let declared = matches!(get(&ours, "declared"), Some(Value::Bool(true)));
    let seen = observed(vec![
        (
            "hooks_listed",
            Value::Bool(matches!(hooks, Value::Object(_) | Value::Array(_))),
        ),
        ("declared", Value::Bool(declared)),
        ("ours_listed", Value::Bool(listed_ours)),
    ]);
    if !declared {
        return blocked(
            "turn Continue inside the turn on in a throwaway installation, so its Stop hook is declared, then run m4b again",
            seen,
        );
    }
    blocked(
        "with this edition's Stop hook declared, fail a turn: confirm the hook's block continued the turn, where the history keeps its reason, that no console window appeared and the trust prompt appeared once, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MANCHOR
fn py_class(class: &'static str) -> Raised {
    Raised::Other(class.into())
}

/// `_manchor_read(session)`: `{"at", "windows"}`.
fn manchor_read(ctx: &mut Context<'_>, session: &mut dyn MeasureSession) -> Res<Value> {
    let at = ctx.world.time();
    let reply = session.call(crate::codex::credits::READ, Some(Value::Object(Map::new())))?;
    let parsed = crate::codex::credits::parse(&reply).map_err(py_class)?;
    let Some(windows) = get(&parsed, "windows") else {
        return Err(py_class("KeyError"));
    };
    Ok(object(vec![
        ("at", Value::from(at)),
        ("windows", windows.clone()),
    ]))
}

fn reads_twice(ctx: &mut Context<'_>) -> Res<(Value, Value)> {
    ctx.with_session(|ctx, session| {
        let first = manchor_read(ctx, session)?;
        let gap = ctx.timing.manchor_gap;
        ctx.world.sleep(gap);
        let second = manchor_read(ctx, session)?;
        Ok((first, second))
    })
}

fn ge(a: &Value, b: f64) -> bool {
    matches!(
        Num::of(a).and_then(|a| pyval::compare(a, Num::Real(b))),
        Some(std::cmp::Ordering::Greater | std::cmp::Ordering::Equal)
    )
}

fn le(a: &Value, b: f64) -> bool {
    matches!(
        Num::of(a).and_then(|a| pyval::compare(a, Num::Real(b))),
        Some(std::cmp::Ordering::Less | std::cmp::Ordering::Equal)
    )
}

pub(super) fn manchor(ctx: &mut Context<'_>) -> Res<Found> {
    use crate::engine::anchor;
    let (first, second) = reads_twice(ctx)?;
    let found = anchor::judge(&first, &second).map_err(py_class)?;
    let read = |value: &Value| !matches!(get(value, "windows"), None | Some(Value::Null));
    let mut seen = observed(vec![
        ("windows_read", Value::Bool(read(&first) && read(&second))),
        ("idle_before", Value::Bool(found == anchor::IDLE)),
    ]);
    if found != anchor::IDLE {
        return blocked(
            "wait until the 5-hour window is idle - no Codex use since its reset - then run manchor again",
            seen,
        );
    }
    let asked_at = ctx.world.time();
    let ran = match ctx.hand("anchor_request", &[]) {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let (after, later) = reads_twice(ctx)?;
    let windows = get(&later, "windows").cloned().unwrap_or(Value::Null);
    let (five, _weekly) = anchor::windows_of(&windows).map_err(py_class)?;
    let reset = match &five {
        Some(five) => match five {
            Value::Object(_) => get(five, "reset_at").cloned(),
            _ => return Err(py_class("AttributeError")),
        },
        None => None,
    };
    let window = anchor::WINDOW_SECONDS as f64;
    let near = matches!(&reset, Some(Value::Int(_)))
        && reset.as_ref().is_some_and(|reset| {
            ge(reset, asked_at + window - MANCHOR_EARLY as f64)
                && le(reset, asked_at + window + MANCHOR_LATE as f64)
        });
    let started = anchor::judge(&after, &later).map_err(py_class)? == anchor::RUNNING;
    let code_zero = get(&ran, "code").is_some_and(|code| pyval::eq(code, &Value::from(0i64)));
    seen.insert(key("request_exit_zero"), Value::Bool(code_zero));
    seen.insert(key("window_started"), Value::Bool(started));
    seen.insert(key("reset_near_five_hours"), Value::Bool(near));
    seen.insert(
        key("folder_empty_after"),
        Value::Bool(matches!(
            get(&ran, "folder_empty_after"),
            Some(Value::Bool(true))
        )),
    );
    for name in ["input", "cached", "output"] {
        let value = match get(&ran, name) {
            Some(found @ Value::Int(_)) => found.clone(),
            _ => Value::Null,
        };
        seen.insert(key(&format!("{name}_tokens")), value);
    }
    if !(code_zero && started && near) {
        return Ok((
            Verdict::Fail,
            seen,
            Some(
                "the request did not start the idle 5-hour window with its reset five hours on"
                    .into(),
            ),
        ));
    }
    blocked(
        "confirm in Codex's /usage that the 5-hour reset is five hours after the request, and that the app's list has no new conversation, then set the verdict",
        seen,
    )
}

// ------------------------------------------------------------------------------------------------ MWAKE
/// `_kept(found, key, int)`.
fn kept_int(found: &Value, name: &str) -> Value {
    match get(found, name) {
        Some(value @ Value::Int(_)) => value.clone(),
        _ => Value::Null,
    }
}

fn kept_bool(found: &Value, name: &str) -> Option<bool> {
    match get(found, name) {
        Some(Value::Bool(value)) => Some(*value),
        _ => None,
    }
}

fn is_real(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Int(_) | Value::Float(_)))
}

pub(super) fn mwake(ctx: &mut Context<'_>) -> Res<Found> {
    let dict_or_empty = |found: Option<Value>| match found {
        Some(found @ Value::Object(_)) => found,
        _ => Value::Object(Map::new()),
    };
    let power = dict_or_empty(ctx.hand("power", &[]));
    let woke = dict_or_empty(ctx.hand(
        "wake_after",
        &[Value::from(MWAKE_SECONDS), Value::from(MWAKE_BOUND)],
    ));
    let (slept, late) = (get(&woke, "slept_seconds"), get(&woke, "late_seconds"));
    let asleep = is_real(slept) && slept.is_some_and(|slept| ge(slept, MWAKE_SLEPT as f64));
    let fired = matches!(get(&woke, "fired"), Some(Value::Bool(true)));
    let on_time =
        fired && asleep && is_real(late) && late.is_some_and(|late| le(late, MWAKE_LATE as f64));
    let source = match kept_bool(&power, "on_battery") {
        None => ObservedWord::Unknown,
        Some(true) => ObservedWord::Battery,
        Some(false) => ObservedWord::Ac,
    };
    let set = matches!(get(&woke, "set"), Some(Value::Bool(true)));
    let seen = observed(vec![
        ("wake_timers_ac", kept_int(&power, "wake_ac")),
        ("wake_timers_dc", kept_int(&power, "wake_dc")),
        ("power_source", text(source.as_str())),
        (
            "modern_standby",
            maybe_bool(kept_bool(&power, "modern_standby")),
        ),
        ("lid_present", maybe_bool(kept_bool(&power, "lid_present"))),
        ("timer_set", Value::Bool(set)),
        ("timer_fired", Value::Bool(fired)),
        ("slept", Value::Bool(asleep)),
        ("woke_on_time", Value::Bool(on_time)),
    ]);
    if !set {
        return blocked("the wake timer could not be set", seen);
    }
    if !asleep {
        return blocked(
            "put the PC to sleep within three minutes of starting this, then run mwake again",
            seen,
        );
    }
    if on_time {
        return Ok((Verdict::Pass, seen, None));
    }
    Ok((
        Verdict::Fail,
        seen,
        Some("the PC slept and did not wake within two minutes of its wake timer".into()),
    ))
}

// ------------------------------------------------------------------------------------------------ MIMG
/// zlib's CRC-32.
fn crc32(data: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for (index, slot) in table.iter_mut().enumerate() {
        let mut value = index as u32;
        for _ in 0..8 {
            value = if value & 1 != 0 {
                0xEDB8_8320 ^ (value >> 1)
            } else {
                value >> 1
            };
        }
        *slot = value;
    }
    let mut crc = 0xFFFF_FFFFu32;
    for byte in data {
        crc = table[((crc ^ u32::from(*byte)) & 0xFF) as usize] ^ (crc >> 8);
    }
    crc ^ 0xFFFF_FFFF
}

/// `_mimg_pictures(folder)`.
fn mimg_pictures(folder: &Path) -> Res<Vec<PathBuf>> {
    use crate::images::{MOST_BYTES, MOST_IMAGES};
    let pixel = crate::profiles::base64_decode(MIMG_PNG_BASE64).unwrap_or_default();
    let end = pixel
        .windows(4)
        .rposition(|window| window == b"IEND")
        .ok_or_else(|| py_class("ValueError"))?
        - 4;
    let pad = MOST_BYTES - MIMG_UNDER - pixel.len() - 12;
    let body = vec![0u8; pad];
    let mut named = b"caRp".to_vec();
    named.extend_from_slice(&body);
    let mut chunk = (pad as u32).to_be_bytes().to_vec();
    chunk.extend_from_slice(&named);
    chunk.extend_from_slice(&crc32(&named).to_be_bytes());
    let mut found = Vec::new();
    for index in 1..=MOST_IMAGES {
        let path = folder.join(format!("sample-{index}.png"));
        let bytes = if index < MOST_IMAGES {
            pixel.clone()
        } else {
            let mut made = pixel[..end].to_vec();
            made.extend_from_slice(&chunk);
            made.extend_from_slice(&pixel[end..]);
            made
        };
        std::fs::write(&path, bytes).map_err(os_error)?;
        found.push(path);
    }
    Ok(found)
}

fn queued_items(added: &Value) -> Option<&Vec<Value>> {
    match get(added, "queuedSubmission").and_then(|found| get(found, "input")) {
        Some(Value::Array(items)) => Some(items),
        _ => None,
    }
}

fn is_image(item: &Value) -> bool {
    is_dict(item) && get(item, "type").is_some_and(|kind| pyval::in_tuple(kind, &MIMG_IMAGE_TYPES))
}

pub(super) fn mimg(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.thread_given {
        return blocked(
            "name a throwaway conversation the app holds, idle",
            observed(vec![("add_calls", Value::from(0i64))]),
        );
    }
    let thread = ctx.probe_thread.clone();
    with_scratch(ctx, "car-mimg-", |ctx, scratch| {
        let pictures = mimg_pictures(scratch)?;
        let local: Vec<Value> = pictures
            .iter()
            .map(|picture| {
                object(vec![
                    ("type", text("localImage")),
                    ("path", path_value(picture)),
                ])
            })
            .collect();
        let mut addresses = Vec::new();
        for picture in &pictures {
            let raw = std::fs::read(picture).map_err(os_error)?;
            addresses.push(object(vec![
                ("type", text("image")),
                (
                    "url",
                    text(&format!(
                        "data:image/png;base64,{}",
                        crate::profiles::base64_encode(&raw)
                    )),
                ),
            ]));
        }
        let shapes = [("local_image", local), ("data_address", addresses)];
        let count = pictures.len();
        let mut seen = observed(vec![
            ("add_calls", Value::from(0i64)),
            ("pictures_sent", Value::from(count as i64)),
        ]);
        let answer = ctx.with_session(|ctx, session| {
            let mut taken_id: Option<&str> = None;
            let mut calls = 0i64;
            for ((name, sent), client_id) in shapes.iter().zip(SAMPLE_MIMG_CLIENT_IDS) {
                calls += 1;
                seen.insert(key("add_calls"), Value::from(calls));
                let mut input = vec![object(vec![
                    ("type", text("text")),
                    ("text", text(M2B_PROMPT)),
                ])];
                input.extend(sent.iter().cloned());
                let added = match session.call(
                    "thread/queue/add",
                    Some(object(vec![
                        ("threadId", text(&thread)),
                        ("clientUserMessageId", text(client_id)),
                        ("input", Value::Array(input)),
                    ])),
                ) {
                    Ok(added) => added,
                    Err(Raised::Adapter { method, code, .. }) => {
                        seen.insert(key(&format!("{name}_accepted")), Value::Bool(false));
                        if method.is_none() {
                            seen.insert(key("add_answer_uncertain"), Value::Bool(true));
                            return Ok(Err(()));
                        }
                        seen.insert(key(&format!("{name}_refusal_code")), code);
                        continue;
                    }
                    Err(raised) => return Err(raised),
                };
                if is_dict(&added)
                    && matches!(
                        get(&added, car_codex::appserver::OVERSIZE),
                        Some(Value::Bool(true))
                    )
                {
                    seen.insert(key(&format!("{name}_accepted")), Value::Bool(true));
                    seen.insert(key("add_answer_oversize"), Value::Bool(true));
                    taken_id = Some(client_id);
                    break;
                }
                let items = queued_items(&added);
                let (length, keeps) = items.map_or((0, false), |items| {
                    (items.len(), items.iter().any(is_image))
                });
                let held = items.map_or(0, |items| {
                    items.iter().filter(|item| is_image(item)).count()
                });
                for (field, value) in [
                    (format!("{name}_accepted"), Value::Bool(true)),
                    ("queued_input_items".to_owned(), Value::from(length as i64)),
                    ("queued_keeps_image".to_owned(), Value::Bool(keeps)),
                    ("queued_images".to_owned(), Value::from(held as i64)),
                    ("queued_keeps_all".to_owned(), Value::Bool(held == count)),
                ] {
                    seen.insert(key(&field), value);
                }
                taken_id = Some(client_id);
                break;
            }
            let Some(taken_id) = taken_id else {
                return Ok(Ok(None));
            };
            let began = ctx.world.monotonic();
            let bound = ctx.timing.mc1_queue;
            let taken = await_taken_on(ctx, session, &thread, taken_id, bound)?;
            Ok(Ok(Some((taken_id, began, taken))))
        })?;
        let (taken_id, began, taken) = match answer {
            Err(()) => {
                return blocked(
                    "the answer to the add did not come: look in Codex whether the message is queued or shown - it was not added again - and remove it from the queue yourself if it is there; then run mimg again",
                    seen,
                );
            }
            Ok(None) => {
                return Ok((
                    Verdict::Fail,
                    seen,
                    Some(format!(
                        "Codex refused the message with {count} pictures in both shapes, as local files and as data addresses"
                    )),
                ));
            }
            Ok(Some(found)) => found,
        };
        let waited = ctx.world.monotonic() - began;
        let started = turn_started_after(ctx, taken);
        let recorded = client_recorded(ctx, taken_id);
        seen.insert(key("taken"), Value::Bool(taken));
        seen.insert(key("taken_seconds"), seconds(waited));
        seen.insert(key("turn_started"), Value::Bool(started));
        seen.insert(key("client_id_on_user_item"), Value::Bool(recorded));
        blocked(
            &format!(
                "confirm the message showed in Codex at once as your own, with all {count} pictures in it (each one half-transparent red pixel) and its line of words, nothing marked it as sent by a program, and the turn ran as one you typed, then set the verdict; if it was not taken, remove it from the conversation's queue in Codex"
            ),
            seen,
        )
    })
}

/// The measurements this module answers.
pub(super) const PORTED: [Measurement; 8] = [
    Measurement::Mb,
    Measurement::Mb2,
    Measurement::Mf,
    Measurement::Mhk,
    Measurement::M4b,
    Measurement::Manchor,
    Measurement::Mwake,
    Measurement::Mimg,
];

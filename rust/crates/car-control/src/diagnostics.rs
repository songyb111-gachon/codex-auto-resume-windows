//! `diagnostics.py`: a diagnostics bundle a person can read before deciding whether to share it - built here, written
//! to a file the person picks, sent nowhere, and redacted before it is written: ids become aliases valid only inside
//! the one bundle (the key is random and discarded with it), and paths, the Windows user name and e-mail addresses
//! are replaced.
//!
//! The redactor's patterns are Python's `re` patterns, matched here by hand over code points with Python's own word
//! characters (car-policy `classify::text::is_word`) and white space (car-machine `pytext::is_space`).

use std::io::Write;
use std::path::{Path, PathBuf};

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::pytext::{is_space, py_str};
use car_machine::pyval;
use car_policy::classify::text::is_word;
use car_policy::plug::{Answer, EXTRA, Surface};
use car_policy::settings::{homefind, homes, is_custom_text};
use car_store::value::get;

use crate::error::{ControlError, Failure, Res, refuse};
use crate::layer::{Control, State};

/// `LOG_LINES`: the tail of each log the bundle carries.
pub const LOG_LINES: i64 = 300;
pub const FORMAT: &str = "codex-auto-resume-diagnostics/1";
pub const NOTE: &str = "Redacted: ids are aliases valid only inside this file; paths, the Windows user name and e-mail addresses are removed. The logs never held prompts or replies. errors.log holds exception messages that are not filtered - read it before sharing this file.";
/// `ids.INTERRUPTION_ID_LENGTH`.
const KEY_LONGEST: usize = 64;
const UUID_GROUPS: [usize; 5] = [8, 4, 4, 4, 12];
const LOGS: &[&str] = &[
    "auto-resume.log",
    "errors.log",
    "launcher.log",
    "codex-start.log",
];

/// `Redactor`: aliases and replacements for one bundle. The key never leaves it.
pub struct Redactor {
    key: Vec<u8>,
    user: Option<String>,
}

fn word_at(chars: &[char], at: usize) -> bool {
    chars.get(at).is_some_and(|c| is_word(*c as u32))
}

/// `\b` before position `at`.
fn boundary(chars: &[char], at: usize) -> bool {
    let before = at > 0 && word_at(chars, at - 1);
    before != word_at(chars, at)
}

fn hex_any_case(c: char) -> bool {
    c.is_ascii_hexdigit()
}

fn hex_lower(c: char) -> bool {
    c.is_ascii_digit() || ('a'..='f').contains(&c)
}

/// `pattern.sub(replace, text)` for a pattern given as a matcher: `matcher(chars, at)` is the end of a match that
/// starts at `at`, or None. Matches are found leftmost first and never overlap, as `re.sub` finds them.
fn substitute(
    text: &str,
    matcher: impl Fn(&[char], usize) -> Option<usize>,
    mut replace: impl FnMut(&str) -> String,
) -> String {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::new();
    let mut at = 0;
    while at <= chars.len() {
        match matcher(&chars, at) {
            Some(end) if end > at => {
                let found: String = chars[at..end].iter().collect();
                out.push_str(&replace(&found));
                at = end;
            }
            _ => {
                if at < chars.len() {
                    out.push(chars[at]);
                }
                at += 1;
            }
        }
    }
    out
}

/// `UUID_RE`: `\b` + the UUID's groups of either case + `\b`.
fn uuid_at(chars: &[char], at: usize) -> Option<usize> {
    if !boundary(chars, at) {
        return None;
    }
    let mut end = at;
    for (index, size) in UUID_GROUPS.iter().enumerate() {
        if index > 0 {
            if chars.get(end) != Some(&'-') {
                return None;
            }
            end += 1;
        }
        for _ in 0..*size {
            if !chars.get(end).is_some_and(|c| hex_any_case(*c)) {
                return None;
            }
            end += 1;
        }
    }
    boundary(chars, end).then_some(end)
}

/// `KEY_RE`: `\b[0-9a-f]{12,64}\b`, the longest that ends at a boundary.
fn key_at(chars: &[char], at: usize) -> Option<usize> {
    if !boundary(chars, at) {
        return None;
    }
    let run = chars[at..].iter().take_while(|c| hex_lower(**c)).count();
    (12..=run.min(KEY_LONGEST))
        .rev()
        .map(|length| at + length)
        .find(|end| boundary(chars, *end))
}

fn email_local(c: char) -> bool {
    c.is_ascii_alphanumeric() || "._%+-".contains(c)
}

fn email_domain(c: char) -> bool {
    c.is_ascii_alphanumeric() || ".-".contains(c)
}

/// `EMAIL_RE`: `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`, backtracking as `re` does.
fn email_at(chars: &[char], at: usize) -> Option<usize> {
    let local = chars[at..].iter().take_while(|c| email_local(**c)).count();
    for split in (1..=local).rev() {
        if chars.get(at + split) != Some(&'@') {
            continue;
        }
        let start = at + split + 1;
        let domain = chars[start..]
            .iter()
            .take_while(|c| email_domain(**c))
            .count();
        for length in (1..=domain).rev() {
            let dot = start + length;
            if chars.get(dot) != Some(&'.') {
                continue;
            }
            let letters = chars[dot + 1..]
                .iter()
                .take_while(|c| c.is_ascii_alphabetic())
                .count();
            if letters >= 2 {
                return Some(dot + 1 + letters);
            }
        }
    }
    None
}

/// `PATH_RE`: `(?:[A-Za-z]:[\\/]|\\\\\?\\|\\\\)[^\s'"<>|]*`.
fn path_at(chars: &[char], at: usize) -> Option<usize> {
    let lead = if chars.get(at).is_some_and(char::is_ascii_alphabetic)
        && chars.get(at + 1) == Some(&':')
        && chars.get(at + 2).is_some_and(|c| *c == '\\' || *c == '/')
    {
        3
    } else if chars.get(at) == Some(&'\\') && chars.get(at + 1) == Some(&'\\') {
        2
    } else {
        return None;
    };
    let body = chars[at + lead..]
        .iter()
        .take_while(|c| !is_space(**c) && !"'\"<>|".contains(**c))
        .count();
    Some(at + lead + body)
}

/// One character under `re.IGNORECASE`: its simple lower case.
fn folded(c: char) -> char {
    let mut lower = c.to_lowercase();
    match (lower.next(), lower.next()) {
        (Some(one), None) => one,
        _ => c,
    }
}

impl Redactor {
    /// `Redactor()`: a key of 16 random bytes, and the Windows user name when it is three characters or more.
    pub fn new(control: &Control) -> Redactor {
        let user = control.host.environ("USERNAME").unwrap_or_default();
        Redactor {
            key: control.host.token_bytes(16),
            user: (user.chars().count() >= 3).then_some(user),
        }
    }

    /// `Redactor()` whose key is `key` (the bundle's own, handed to `checkup.for_bundle`'s check): no random bytes
    /// are asked for.
    pub fn with_key(control: &Control, key: &[u8]) -> Redactor {
        let user = control.host.environ("USERNAME").unwrap_or_default();
        Redactor {
            key: key.to_vec(),
            user: (user.chars().count() >= 3).then_some(user),
        }
    }

    pub fn key(&self) -> &[u8] {
        &self.key
    }

    /// `alias(value, prefix)`.
    pub fn alias(&self, value: &Value, prefix: &str) -> String {
        let mut data = self.key.clone();
        data.extend_from_slice(py_str(value).to_lowercase().as_bytes());
        let digest = car_machine::hash::hex(&car_machine::hash::sha256(&data));
        format!("{prefix}-{}", &digest[..8])
    }

    fn alias_text(&self, value: &str, prefix: &str) -> String {
        self.alias(&Value::from(value), prefix)
    }

    /// `text(value)`: a log line or any other text, redacted.
    pub fn text(&self, value: &str) -> String {
        let value = substitute(value, uuid_at, |found| self.alias_text(found, "thread"));
        let value = substitute(&value, key_at, |found| self.alias_text(found, "record"));
        let value = substitute(&value, email_at, |_| "<email>".to_owned());
        let value = substitute(&value, path_at, |_| "<path>".to_owned());
        match &self.user {
            Some(user) => {
                let wanted: Vec<char> = user.chars().map(folded).collect();
                substitute(
                    &value,
                    |chars, at| {
                        let end = at + wanted.len();
                        (end <= chars.len()
                            && chars[at..end]
                                .iter()
                                .zip(&wanted)
                                .all(|(c, w)| folded(*c) == *w))
                        .then_some(end)
                    },
                    |_| "<user>".to_owned(),
                )
            }
            None => value,
        }
    }

    /// `_redacted(value, redact)`: a plug's fields with every word in them - keys too - redacted.
    pub fn redacted(&self, value: &Value) -> Value {
        match value {
            Value::Str(text) => Value::from(self.text(&text.as_str().map_or_else(
                || String::from_utf8_lossy(text.as_bytes()).into_owned(),
                str::to_owned,
            ))),
            Value::Array(items) => {
                Value::Array(items.iter().map(|item| self.redacted(item)).collect())
            }
            Value::Object(map) => {
                let mut out = Map::new();
                for (key, item) in map {
                    let key = self.text(&key.as_str().map_or_else(
                        || String::from_utf8_lossy(key.as_bytes()).into_owned(),
                        str::to_owned,
                    ));
                    out.insert(Str::from(key), self.redacted(item));
                }
                Value::Object(out)
            }
            other => other.clone(),
        }
    }
}

fn first(text: &str, count: usize) -> String {
    text.chars().take(count).collect()
}

fn put(map: &mut Map, name: &str, value: Value) {
    map.insert(Str::from(name), value);
}

/// `str(exc)` of what a part of the bundle raised: the refusal's sentence; another exception's text is not carried
/// across the port (only its class is), so it is empty.
fn said(failure: &Failure) -> String {
    match failure {
        Failure::Control(error) => py_str(&Value::Str(error.message.clone())),
        Failure::Other(_) => String::new(),
    }
}

fn class_of(failure: &Failure) -> String {
    match failure {
        Failure::Control(_) => "ControlError".to_owned(),
        Failure::Other(class) => class.clone(),
    }
}

impl Control {
    /// `_record(row, redact)`.
    fn bundle_record(&self, row: &Map, redact: &Redactor) -> Res<Value> {
        let record = Value::Object(row.clone());
        let held = |name: &str| get(row, name).clone();
        let gates = if row.get("gate_eval").is_some_and(pyval::truthy) {
            let decoded = car_policy::classify::gates::decode_gates(get(row, "gate_eval"));
            let mut map = Map::new();
            for (name, (result, reason)) in decoded.0 {
                put(
                    &mut map,
                    &name,
                    Value::Array(vec![Value::from(result), Value::from(reason)]),
                );
            }
            if map.is_empty() {
                Value::Null
            } else {
                Value::Object(map)
            }
        } else {
            Value::Null
        };
        let code = car_machine::domain::public::public_code(&record)
            .map_err(|class| Failure::Other(class.to_owned()))?;
        let reason = car_machine::domain::public::public_reason(&record)
            .map_err(|class| Failure::Other(class.to_owned()))?;
        let flag = |name: &str| Value::Bool(pyval::truthy(get(row, name)));
        let mut out = Map::new();
        put(
            &mut out,
            "record",
            Value::from(redact.alias(get(row, "interruption_id"), "record")),
        );
        put(
            &mut out,
            "thread",
            Value::from(redact.alias(get(row, "thread_id"), "thread")),
        );
        put(
            &mut out,
            "chain",
            Value::from(redact.alias(get(row, "chain_origin_id"), "record")),
        );
        put(&mut out, "state", held("state"));
        put(&mut out, "code", Value::from(code));
        put(&mut out, "reason", reason);
        for name in [
            "category",
            "detected_at",
            "next_retry_at",
            "reset_at",
            "submitted_at",
            "first_queued_at",
            "turn_started_at",
            "outcome_at",
            "recovery_turn_status",
        ] {
            put(&mut out, name, held(name));
        }
        put(&mut out, "attempts", held("attempt_count"));
        for name in [
            "recovery_attempts",
            "no_progress_count",
            "chain_continuations",
            "budget_resets",
        ] {
            put(&mut out, name, held(name));
        }
        for name in [
            "cancel_requested",
            "user_joined",
            "after_user_work",
            "legacy",
        ] {
            put(&mut out, name, flag(name));
        }
        put(
            &mut out,
            "hidden",
            Value::Bool(!matches!(get(row, "history_hidden_at"), Value::Null)),
        );
        put(&mut out, "gates", gates);
        Ok(Value::Object(out))
    }

    /// `_installation(control)`: whether the pieces outside the state file are where they should be.
    fn installation(&self) -> Value {
        let mut found = Map::new();
        let language = match self.get_settings() {
            Ok(values) => {
                let host = &*self.host;
                let environ = |name: &str| host.environ(name);
                let windows = || host.windows_languages();
                let chosen = values
                    .get("interface_language")
                    .cloned()
                    .unwrap_or(Value::Null);
                match &chosen {
                    Value::Null => {
                        Value::from(car_words::interface::resolve(None, &environ, &windows))
                    }
                    Value::Str(text) => match text.as_str() {
                        Some(word) => Value::from(car_words::interface::resolve(
                            Some(word),
                            &environ,
                            &windows,
                        )),
                        None => Value::Null,
                    },
                    _ => Value::from(car_words::interface::resolve(Some(""), &environ, &windows)),
                }
            }
            Err(_) => Value::Null,
        };
        put(&mut found, "language", language);
        let home = self.paths.home.clone();
        for (name, read) in [
            ("startup_entry", self.host.startup_read()),
            ("protocol_handler", self.host.protocol_value()),
        ] {
            let word = match read {
                Err(_) => "unreadable",
                Ok(None) => "absent",
                Ok(Some(value)) if value.is_empty() => "absent",
                Ok(Some(value)) => {
                    if car_platform::startup::belongs_to(&value, &home) {
                        "ours"
                    } else {
                        "another"
                    }
                }
            };
            put(&mut found, name, Value::from(word));
        }
        let identity = match self.host.notification_identity_owner(&home) {
            Ok(Some(true)) => "ours",
            Ok(Some(false)) => "another",
            Ok(None) => "absent",
            Err(_) => "unreadable",
        };
        put(&mut found, "notification_identity", Value::from(identity));
        let root = PathBuf::from(&home);
        for (name, relative) in [
            ("owner_marker", car_config::paths::OWNER_MARKER),
            ("runtime_record", "runtime.json"),
            ("mcp_manifest", "app/.mcp.json"),
            ("mcp_launcher", "app/mcp/codex-auto-resume-mcp.exe"),
            ("settings_window", "CodexAutoResumeSettings.exe"),
            ("bundled_runtime", "runtime/python.exe"),
            ("windowless_runtime", "runtime/pythonw.exe"),
        ] {
            put(&mut found, name, Value::Bool(root.join(relative).exists()));
        }
        Value::Object(found)
    }

    /// `_compatibility(control)`: the registry's view as a reader checks it, content-free.
    pub fn bundle_compatibility(&self) -> Value {
        match self.get_settings() {
            Ok(values) => {
                let mut explicit = Map::new();
                put(
                    &mut explicit,
                    "codex_exe",
                    values.get("codex_exe").cloned().unwrap_or(Value::Null),
                );
                self.host.compat_view(&self.state_dir(), &explicit)
            }
            Err(failure) => {
                let mut out = Map::new();
                put(&mut out, "status", Value::from("invalid"));
                put(&mut out, "error", Value::from(class_of(&failure)));
                Value::Object(out)
            }
        }
    }

    /// `collect(control, redact=..., check=..., report=...)`: the whole bundle, redacted.
    pub fn collect_bundle(&self, redact: &Redactor) -> Res<Value> {
        let now = self.host.now();
        let mut bundle = Map::new();
        put(&mut bundle, "format", Value::from(FORMAT));
        put(&mut bundle, "created_at", Value::Float(now));
        put(&mut bundle, "note", Value::from(NOTE));
        let mut product = Map::new();
        put(&mut product, "version", Value::from(self.host.version()));
        put(&mut bundle, "product", Value::Object(product));
        put(&mut bundle, "system", self.host.system());
        let mut settings = self.get_settings()?;
        let set = |value: Option<&Value>| {
            if value.is_some_and(pyval::truthy) {
                Value::from("<set>")
            } else {
                Value::Null
            }
        };
        let exe = set(settings.get("codex_exe"));
        settings.insert(Str::from("codex_exe"), exe);
        for field in [homes::FIELD, homefind::DISMISSED] {
            if let Some(named) = settings.get(field) {
                let count = match named {
                    Value::Array(items) => Value::from(items.len() as i64),
                    _ => Value::Null,
                };
                settings.insert(Str::from(field), count);
            }
        }
        let names: Vec<Str> = settings.keys().cloned().collect();
        for name in names {
            if name.as_str().is_some_and(is_custom_text) {
                let value = set(settings.get(&name));
                settings.insert(name, value);
            }
        }
        put(&mut bundle, "settings", Value::Object(settings));
        let status = match self.get_status() {
            Ok(Value::Object(status)) => {
                let mut out = Map::new();
                for key in [
                    "enabled",
                    "watcher",
                    "upgrade_pending",
                    "startup_enabled",
                    "pending",
                    "states",
                    "codes",
                ] {
                    put(
                        &mut out,
                        key,
                        status.get(key).cloned().unwrap_or(Value::Null),
                    );
                }
                if let Some(Value::Object(managed)) = status.get("managed") {
                    put(
                        &mut out,
                        "managed",
                        Value::Array(managed.keys().map(|key| Value::Str(key.clone())).collect()),
                    );
                } else if let Some(Value::Array(managed)) = status.get("managed") {
                    put(&mut out, "managed", Value::Array(managed.clone()));
                }
                if let Some(power) = status.get("power_action") {
                    put(&mut out, "power_action", power.clone());
                }
                Value::Object(out)
            }
            Ok(_) => Value::Null,
            Err(failure) => {
                let mut out = Map::new();
                put(
                    &mut out,
                    "error",
                    Value::from(first(&redact.text(&said(&failure)), 200)),
                );
                Value::Object(out)
            }
        };
        put(&mut bundle, "status", status);
        let count = crate::oncewords::OnceWords::of(&self.paths.once_words_file, &*self.host)
            .count()
            .map_or(Value::Null, |count| Value::from(count as i64));
        let mut once = Map::new();
        put(&mut once, "count", count);
        put(&mut bundle, "once_words", Value::Object(once));
        let stored = (|| -> Result<(), Failure> {
            let store = match self.open(false)? {
                State::Current(store) => store,
                State::Legacy(_) => {
                    return refuse(car_store::open::UPGRADE_PENDING, "upgrade_pending");
                }
            };
            let store_failure = |error: car_store::Error| {
                Failure::Control(ControlError::new(error.message(), "store"))
            };
            put(
                &mut bundle,
                "schema_version",
                Value::from(store.schema_version().map_err(store_failure)?),
            );
            let mut records = Vec::new();
            for row in store.all_records().map_err(store_failure)? {
                records.push(self.bundle_record(&row, redact)?);
            }
            put(&mut bundle, "records", Value::Array(records));
            let mut events = Vec::new();
            for event in store.events(None, None, 2000).map_err(store_failure)? {
                let mut event = event;
                if event.get("interruption_id").is_some_and(pyval::truthy) {
                    let alias = redact.alias(get(&event, "interruption_id"), "record");
                    event.insert(Str::from("interruption_id"), Value::from(alias));
                }
                events.push(Value::Object(event));
            }
            put(&mut bundle, "events", Value::Array(events));
            put(
                &mut bundle,
                "statistics",
                Value::Object(store.statistics(0.0, None).map_err(store_failure)?),
            );
            Ok(())
        })();
        if let Err(failure) = stored {
            put(&mut bundle, "records", Value::Array(Vec::new()));
            put(&mut bundle, "events", Value::Array(Vec::new()));
            put(
                &mut bundle,
                "state_error",
                Value::from(first(&redact.text(&said(&failure)), 200)),
            );
        }
        put(&mut bundle, "installation", self.installation());
        put(&mut bundle, "compatibility", self.bundle_compatibility());
        let check = match self
            .host
            .checkup_for_bundle(&PathBuf::from(&self.paths.home), redact.key())
        {
            Ok(found) => found,
            Err(raised) => {
                let mut out = Map::new();
                put(&mut out, "error", Value::from(raised.class));
                Value::Object(out)
            }
        };
        put(&mut bundle, "detection_check", check);
        let report = match self.own_report_for_bundle() {
            Ok(found) => found,
            Err(class) => {
                let mut out = Map::new();
                put(&mut out, "error", Value::from(class));
                Value::Object(out)
            }
        };
        put(&mut bundle, "compatibility_report", report);
        if let Answer::Is(added) = self
            .plug()
            .surface(Surface::Diagnostics, &Value::Object(Map::new()))
        {
            put(&mut bundle, EXTRA, redact.redacted(&added));
        }
        let mut logs = Map::new();
        let folder = PathBuf::from(&self.paths.logs_dir);
        for name in LOGS {
            let path = folder.join(name);
            if path.is_file() {
                let lines = car_config::logbook::tail(&path, LOG_LINES)
                    .iter()
                    .map(|line| Value::from(redact.text(line)))
                    .collect();
                put(&mut logs, name, Value::Array(lines));
            }
        }
        put(&mut bundle, "logs", Value::Object(logs));
        Ok(Value::Object(bundle))
    }

    /// `diagnostics.write(control, target, check=..., report=...)`: the bundle as one JSON file, never over another.
    pub fn write_bundle(&self, target: &Path) -> Res<PathBuf> {
        let exists = || {
            Failure::Control(ControlError::new(
                "that file already exists; choose a new name",
                "file_exists",
            ))
        };
        if target.exists() {
            return Err(exists());
        }
        let redact = Redactor::new(self);
        let bundle = self.collect_bundle(&redact)?;
        let text = to_string(&bundle, &Options::new().indent(1).ensure_ascii(false))
            .map_err(|_| Failure::Other("ValueError".to_owned()))?;
        if let Some(parent) = target.parent()
            && !parent.as_os_str().is_empty()
        {
            // `mkdir(parents=True, exist_ok=True)` over a file of that name raises FileExistsError, which the
            // bridge answers as the name taken.
            match std::fs::create_dir_all(parent) {
                Ok(()) => {}
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                    return Err(exists());
                }
                Err(_) => return Err(Failure::Other("OSError".to_owned())),
            }
        }
        let mut file = match self.host.create_file(target) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => return Err(exists()),
            Err(_) => return Err(Failure::Other("OSError".to_owned())),
        };
        // A text-mode file on Windows writes each "\n" as "\r\n".
        file.write_all(text.replace('\n', "\r\n").as_bytes())
            .map_err(|_| Failure::Other("OSError".to_owned()))?;
        Ok(target.to_path_buf())
    }

    /// The bridge's `diagnostics`: a `.json` name, and the bundle written there.
    pub fn diagnostics(&self, path: &Value) -> Res<Value> {
        let target = match path {
            Value::Str(text) => match text.as_str() {
                Some(plain) if plain.to_lowercase().ends_with(".json") => plain.to_owned(),
                _ => return refuse("choose a .json file to write", crate::error::FALLBACK_CODE),
            },
            _ => return refuse("choose a .json file to write", crate::error::FALLBACK_CODE),
        };
        let shown = car_platform::paths::pathlib_text(&target);
        let written = self.write_bundle(Path::new(&shown))?;
        let mut out = Map::new();
        put(
            &mut out,
            "path",
            Value::from(written.to_string_lossy().into_owned()),
        );
        Ok(Value::Object(out))
    }
}

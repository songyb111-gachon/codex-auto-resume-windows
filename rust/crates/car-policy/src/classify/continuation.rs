//! `continuation.py`: the one place a continuation message is built - every continuation sent, and every preview of
//! one, comes out of [`build`].
//!
//! The text depends on the classified category, the language, the style and a person's Custom settings, and on a
//! little metadata this product counted itself; never on the prompt, the reply, a title, a path, an account name or
//! an error's text. The placeholder list is a whitelist.

use std::sync::OnceLock;

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::py_str;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_ids::MARKER_PREFIX;
use car_words::l10n;

use super::clock::LocalClock;
use super::failures::{CATEGORIES, USAGE_LIMIT, is_recoverable};
use super::reasons::{self, RECOVERABLE, Reason};
use super::text::{casefold, has_non_space, strip};
use super::value::{get, in_tuple, or_empty, python_int, text, truthy};
pub use super::vocab_gen::continuation::{
    ALLOWED_PLACEHOLDERS, BY_THREAD_FIELD, CUSTOM_MODES, DEFAULT_CUSTOM_MODE, DEFAULT_STYLE, STYLES,
};

/// `FOLDED_STYLES`: a style a pre-release had, and the one it reads as.
pub const FOLDED_STYLES: &[(&str, &str)] = &[("careful", "detailed")];
/// How many conversations may have a message of their own.
pub const MAX_CONVERSATIONS: usize = 50;
/// The longest Custom message.
pub const MAX_CUSTOM_LENGTH: usize = 2000;
/// `FORBIDDEN_PLACEHOLDERS`, in the dict's order: each with what it would put into a message.
pub const FORBIDDEN_PLACEHOLDERS: &[(&str, &str)] = &[
    ("prompt", "the text you sent"),
    ("reply", "the assistant's answer"),
    ("conversation_title", "the conversation's title"),
    ("project_path", "a path on this machine"),
    ("path", "a path on this machine"),
    ("cwd", "a path on this machine"),
    ("username", "your Windows account name"),
    ("user", "your Windows account name"),
    ("raw_error", "the unredacted error"),
    ("error", "the unredacted error"),
    ("account", "your account"),
    ("email", "your e-mail address"),
    ("credential", "a credential"),
    ("token", "a token"),
];
/// What core's one send may carry at most.
pub const PROMPT_SEND_LIMIT: usize = 30000;
/// `"\n\n" + short_marker("0" * 64)`: the blank line and marker a send ends with.
fn sent_after() -> String {
    format!(
        "\n\n{}",
        ids::short_marker(&"0".repeat(ids::INTERRUPTION_ID_LENGTH))
    )
}
/// `PROMPT_LIMIT`.
pub fn prompt_limit() -> usize {
    PROMPT_SEND_LIMIT - sent_after().chars().count()
}
/// The longest command line Windows starts a process with, in UTF-16 code units less its end.
pub const COMMAND_LINE_UNITS: usize = 32766;
/// The most the send puts on that line beside the message.
pub const SEND_ARGV_ROOM: usize = 600;
/// The edition's own continuation words: at most this long.
pub const CONTINUATION_LIMIT: usize = MAX_CUSTOM_LENGTH;
/// The words for this time come after the continuation, one blank line between.
pub const ONCE_SEPARATOR: &str = "\n\n";

/// A Custom message that will not be stored (`CustomMessageError`): the sentence, the machine code and its detail.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CustomMessageError {
    pub message: String,
    pub code: &'static str,
    pub detail: Option<String>,
}

/// `PLACEHOLDER.finditer(text)`: each `{name}` (an identifier of ASCII letters, digits and `_`) as (start, end,
/// name), in character positions.
fn placeholders(chars: &[char]) -> Vec<(usize, usize, String)> {
    let mut found = Vec::new();
    let mut at = 0;
    while at < chars.len() {
        if chars[at] == '{'
            && let Some(first) = chars.get(at + 1)
            && (first.is_ascii_alphabetic() || *first == '_')
        {
            let mut end = at + 2;
            while chars
                .get(end)
                .is_some_and(|c| c.is_ascii_alphanumeric() || *c == '_')
            {
                end += 1;
            }
            if chars.get(end) == Some(&'}') {
                found.push((at, end + 1, chars[at + 1..end].iter().collect()));
                at = end + 1;
                continue;
            }
        }
        at += 1;
    }
    found
}

fn refusal(message: String, code: &'static str, detail: Option<String>) -> CustomMessageError {
    CustomMessageError {
        message,
        code,
        detail,
    }
}

/// `validate_custom(text)`: the text unchanged, or a refusal a person can act on.
pub fn validate_custom(value: &Value) -> Result<String, CustomMessageError> {
    let Value::Str(said) = value else {
        return Err(refusal(
            "A custom message has to be text.".into(),
            "not_text",
            None,
        ));
    };
    if !has_non_space(said) {
        return Err(refusal(
            "A custom message cannot be empty.".into(),
            "empty",
            None,
        ));
    }
    let length = said.len();
    if length > MAX_CUSTOM_LENGTH {
        return Err(refusal(
            format!(
                "A custom message can be at most {MAX_CUSTOM_LENGTH} characters; this one is {length}."
            ),
            "too_long",
            Some(length.to_string()),
        ));
    }
    let owned = String::from_utf8_lossy(said.as_bytes()).into_owned();
    let chars: Vec<char> = owned.chars().collect();
    for (_, _, name) in placeholders(&chars) {
        let lowered = name.to_ascii_lowercase();
        if let Some((_, what)) = FORBIDDEN_PLACEHOLDERS
            .iter()
            .find(|(each, _)| *each == lowered)
        {
            return Err(refusal(
                format!("{{{name}}} is not available: it would put {what} into the message."),
                "forbidden_placeholder",
                Some(format!("{{{name}}}")),
            ));
        }
        if !ALLOWED_PLACEHOLDERS.contains(&name.as_str()) {
            let available: Vec<String> = ALLOWED_PLACEHOLDERS
                .iter()
                .map(|each| format!("{{{each}}}"))
                .collect();
            return Err(refusal(
                format!(
                    "{{{name}}} is not a placeholder this product knows. Available: {}.",
                    available.join(", ")
                ),
                "unknown_placeholder",
                Some(format!("{{{name}}}")),
            ));
        }
    }
    Ok(owned)
}

/// `joined_command_line(argv)`: the line Windows is given for `argv`, as `subprocess.list2cmdline` makes it.
pub fn joined_command_line(argv: &[String]) -> String {
    let mut line = String::new();
    for (index, argument) in argv.iter().enumerate() {
        if index > 0 {
            line.push(' ');
        }
        let quoted = argument.contains(' ') || argument.contains('\t') || argument.is_empty();
        if quoted {
            line.push('"');
        }
        let mut slashes = 0;
        for character in argument.chars() {
            if character == '\\' {
                slashes += 1;
                continue;
            }
            if character == '"' {
                line.push_str(&"\\".repeat(slashes * 2 + 1));
                line.push('"');
            } else {
                line.push_str(&"\\".repeat(slashes));
                line.push(character);
            }
            slashes = 0;
        }
        line.push_str(&"\\".repeat(if quoted { slashes * 2 } else { slashes }));
        if quoted {
            line.push('"');
        }
    }
    line
}

/// `command_line_units(argv)`: how long `argv` is as Windows will see it, in UTF-16 code units.
pub fn command_line_units(argv: &[String]) -> usize {
    joined_command_line(argv).encode_utf16().count()
}

/// `fits_command_line(text)`: whether `text`, sent with its blank line and marker, fits Windows' command line.
pub fn fits_command_line(said: &str) -> bool {
    SEND_ARGV_ROOM + 1 + command_line_units(&[format!("--message={said}{}", sent_after())])
        <= COMMAND_LINE_UNITS
}

/// `_folded(text)`: stripped and casefolded.
fn folded(said: &str) -> String {
    casefold(strip(said))
}

/// `product_texts()`: every continuation this product says, in every language it speaks, stripped and casefolded.
pub fn product_texts() -> &'static std::collections::BTreeSet<String> {
    static TEXTS: OnceLock<std::collections::BTreeSet<String>> = OnceLock::new();
    TEXTS.get_or_init(|| {
        let mut found = std::collections::BTreeSet::new();
        let mut recovered: Vec<&str> = CATEGORIES
            .iter()
            .copied()
            .filter(|each| is_recoverable(each))
            .collect();
        recovered.sort_unstable();
        for locale in l10n::LOCALES {
            for (key, value) in l10n::catalog(locale) {
                if key.starts_with("continuation.") {
                    found.insert(folded(&value));
                }
            }
            for category in &recovered {
                for style in ["minimal", "standard", "detailed"] {
                    if let Ok(text) = build(
                        &Value::from(*category),
                        locale,
                        &Value::from(style),
                        &Value::Null,
                        &Value::Null,
                    ) {
                        found.insert(folded(&text));
                    }
                }
            }
        }
        found
    })
}

/// The control characters a message may hold: a tab and the two ends of a line.
fn control(said: &str) -> bool {
    said.chars()
        .any(|c| ((c as u32) < 32 && !matches!(c, '\t' | '\r' | '\n')) || c == '\x7f')
}

/// `validate_prompt(text)`: a message a person wrote, for the plug to have core send (P2); the error is
/// PromptError's code.
pub fn validate_prompt(value: &Value) -> Result<String, &'static str> {
    let Value::Str(said) = value else {
        return Err("not_text");
    };
    if !has_non_space(said) {
        return Err("empty");
    }
    let said = String::from_utf8_lossy(said.as_bytes()).into_owned();
    if said.chars().count() > prompt_limit() || !fits_command_line(&said) {
        return Err("too_long");
    }
    if control(&said) {
        return Err("control");
    }
    if said.contains(MARKER_PREFIX) {
        return Err("marker");
    }
    if product_texts().contains(&folded(&said)) {
        return Err("product_text");
    }
    Ok(said)
}

/// `validate_continuation(text)`: words of the edition's own catalog that continue a conversation (P2's
/// CONTINUATION); the error is PromptError's code.
pub fn validate_continuation(value: &Value) -> Result<String, &'static str> {
    let Value::Str(said) = value else {
        return Err("not_text");
    };
    if !has_non_space(said) {
        return Err("empty");
    }
    if said.len() > CONTINUATION_LIMIT {
        return Err("too_long");
    }
    let said = String::from_utf8_lossy(said.as_bytes()).into_owned();
    if control(&said) {
        return Err("control");
    }
    if said.contains(MARKER_PREFIX) {
        return Err("marker");
    }
    if said.contains(['{', '}']) {
        return Err("placeholder");
    }
    Ok(said)
}

/// `coerce_by_thread(value, default)`: the per-conversation messages that are each one, or `default`.
pub fn coerce_by_thread(value: &Value, default: &Value) -> Value {
    let Value::Object(map) = value else {
        return default.clone();
    };
    if map.is_empty() || map.len() > MAX_CONVERSATIONS {
        return default.clone();
    }
    let mut kept = Map::new();
    for (thread, said) in map {
        if !ids::is_uuid(&Value::Str(thread.clone())) {
            continue;
        }
        // The text as it was written, whole: a lone surrogate in it is kept, as Python keeps it.
        if validate_custom(said).is_ok() {
            kept.insert(thread.clone(), said.clone());
        }
    }
    if kept.is_empty() {
        default.clone()
    } else {
        Value::Object(kept)
    }
}

/// `conversation_text(values, thread_id)`: this conversation's own message, as stored and checked again, or None.
pub fn conversation_text(values: &Value, thread_id: &Value) -> Py<Value> {
    let values = or_empty(values)?;
    let held = coerce_by_thread(get(values, BY_THREAD_FIELD), &Value::Null);
    Ok(match (&held, thread_id) {
        (Value::Object(held), Value::Str(thread)) => {
            held.get(thread).cloned().unwrap_or(Value::Null)
        }
        _ => Value::Null,
    })
}

/// `_fill(template, values)`: substitute only what is known; a placeholder with no value is removed and only the gap
/// it leaves is closed.
pub fn fill(template: &str, values: &Map) -> String {
    let chars: Vec<char> = template.chars().collect();
    let found = placeholders(&chars);
    if found.is_empty() {
        return template.to_owned();
    }
    let mut out: Vec<char> = Vec::new();
    let mut position = 0;
    for (start, end, name) in found {
        out.extend(&chars[position..start]);
        position = end;
        let value = match values.get(name.as_str()) {
            None | Some(Value::Null) => String::new(),
            Some(value) => py_str(value),
        };
        if !value.is_empty() {
            out.extend(value.chars());
            continue;
        }
        let blank = |c: &char| *c == ' ' || *c == '\t';
        let kept_len = out.len() - out.iter().rev().take_while(|c| blank(c)).count();
        let after = &chars[position..];
        let right_len = after.iter().take_while(|c| blank(c)).count();
        let left = out[kept_len..].to_vec();
        let right = after[..right_len].to_vec();
        if left.is_empty() && right.is_empty() {
            continue;
        }
        let rest = &after[right_len..];
        out.truncate(kept_len);
        let closes = out.is_empty()
            || out.last() == Some(&'\n')
            || rest.is_empty()
            || matches!(rest[0], '\r' | '\n' | ',' | '.' | ';' | ':' | '!' | '?');
        if !closes {
            out.extend(if left.is_empty() { right.clone() } else { left });
        }
        position += right.len();
    }
    out.extend(&chars[position..]);
    out.into_iter().collect()
}

fn label(category: &Value, locale: &str) -> Py<String> {
    let key = reasons::label_key(category)?;
    l10n::text(&key, locale, &[]).ok_or("KeyError")
}

/// A record as `row.keys()` reads it: None, or a dict (anything else has no `.keys()`).
fn record(row: &Value) -> Py<Option<&Map>> {
    match row {
        Value::Null => Ok(None),
        Value::Object(map) => Ok(Some(map)),
        _ => Err("AttributeError"),
    }
}

/// `metadata_for(row, locale=, limits=, reset_time=)`: the safe values a message may refer to, from one record.
pub fn metadata_for(row: &Value, locale: &str, limits: &Value, reset_time: &Value) -> Py<Map> {
    let mut values = Map::new();
    let row = record(row)?;
    let category = row.map_or(&Value::Null, |row| get(row, "category"));
    let counted = !pyval::is(category, USAGE_LIMIT);
    if let Some(row) = row
        && counted
        && let Some(spent) = row.get("recovery_attempts")
        && !matches!(spent, Value::Null)
    {
        let spent = if truthy(spent) { python_int(spent)? } else { 0 };
        values.insert("attempt".into(), Value::from((spent + 1) as i64));
    }
    if truthy(category) {
        values.insert("category".into(), category.clone());
        values.insert("reason".into(), Value::from(label(category, locale)?));
    }
    if truthy(limits) && counted {
        let maximum = super::value::dict_get(limits, "max_recovery_attempts")?;
        if truthy(maximum) {
            values.insert(
                "max_attempts".into(),
                Value::from(python_int(maximum)? as i64),
            );
        }
    }
    if truthy(reset_time) && (matches!(category, Value::Null) || reasons::has_reset_time(category)?)
    {
        values.insert("reset_time".into(), reset_time.clone());
    }
    Ok(values)
}

/// `_message_values(entry, locale, metadata)`.
fn message_values(entry: &Reason, locale: &str, metadata: &Value) -> Py<Map> {
    let mut values = match metadata {
        Value::Object(map) => map.clone(),
        other if !truthy(other) => Map::new(),
        _ => return Err("TypeError"),
    };
    if !values.contains_key("category") {
        values.insert("category".into(), Value::from(entry.category));
    }
    if !values.contains_key("reason") {
        let said = l10n::text(&entry.label_key(), locale, &[]).ok_or("KeyError")?;
        values.insert("reason".into(), Value::from(said));
    }
    Ok(values)
}

/// `_conversation_choice(entry, custom, values)`: this conversation's own message, filled in, when it says something.
fn conversation_choice(entry: &Reason, custom: &Value, values: &Map) -> Option<String> {
    let Value::Object(custom) = custom else {
        return None;
    };
    if !entry.recoverable {
        return None;
    }
    match get(custom, "conversation") {
        Value::Str(said) if has_non_space(said) => {
            let filled = fill(&String::from_utf8_lossy(said.as_bytes()), values);
            has_non_space(&Str::new(&filled)).then_some(filled)
        }
        _ => None,
    }
}

/// `_custom_choice(category, custom, values)`: which Custom text is sent, and what it says, or None.
fn custom_choice(
    category: &Value,
    custom: &Value,
    values: &Map,
) -> Py<Option<(&'static str, String)>> {
    let Value::Object(custom) = custom else {
        return Ok(None);
    };
    let mut candidates: Vec<(&'static str, Value)> = Vec::new();
    let per = get(custom, "per_reason");
    let mode = get(custom, "mode");
    let mode_is_per_reason = if truthy(mode) {
        pyval::is(mode, "per_reason")
    } else {
        DEFAULT_CUSTOM_MODE == "per_reason"
    };
    if mode_is_per_reason && let Value::Object(per) = per {
        pyval::hashable(category)?;
        let found = text(category)
            .and_then(|word| per.get(word))
            .cloned()
            .unwrap_or(Value::Null);
        candidates.push(("per_reason", found));
    }
    candidates.push(("global", get(custom, "text").clone()));
    for (source, candidate) in candidates {
        if let Value::Str(said) = &candidate
            && has_non_space(said)
        {
            let filled = fill(&String::from_utf8_lossy(said.as_bytes()), values);
            if has_non_space(&Str::new(&filled)) {
                return Ok(Some((source, filled)));
            }
        }
    }
    Ok(None)
}

/// `fold_style(style)`: a folded style as the style it became.
pub fn fold_style(style: &Value) -> Value {
    match text(style).and_then(|word| FOLDED_STYLES.iter().find(|(each, _)| *each == word)) {
        Some((_, became)) => Value::from(*became),
        None => style.clone(),
    }
}

/// `build(category, locale=, style=, custom=, metadata=)`: the exact text that would be sent for this interruption.
pub fn build(
    category: &Value,
    locale: &str,
    style: &Value,
    custom: &Value,
    metadata: &Value,
) -> Py<String> {
    let entry = reasons::get_value(category)?;
    let values = message_values(entry, locale, metadata)?;
    let mut style = fold_style(style);
    if let Some(own) = conversation_choice(entry, custom, &values) {
        return Ok(own);
    }
    if pyval::is(&style, "custom") && entry.recoverable {
        if let Some((_, said)) = custom_choice(&Value::from(entry.category), custom, &values)? {
            return Ok(said);
        }
        style = Value::from(DEFAULT_STYLE);
    }
    let catalog = |key: &str| l10n::text(key, locale, &[]).ok_or("KeyError");
    if pyval::is(&style, "minimal") {
        return Ok(fill(&catalog("continuation.minimal")?, &values));
    }
    if pyval::is(&style, "detailed")
        && let Some(key) = entry.detailed_key()
    {
        return Ok(fill(&catalog(&key)?, &values));
    }
    let key = entry
        .standard_key()
        .unwrap_or_else(|| "continuation.minimal".to_owned());
    Ok(fill(&catalog(&key)?, &values))
}

/// The environment and Windows' preferred languages, as `l10n.resolve` reads them.
pub struct Environ<'a> {
    pub variable: l10n::Environ<'a>,
    pub windows: &'a dyn Fn() -> Vec<String>,
}

/// `resolve_locale(values, environ)`: the language a continuation is written in.
pub fn resolve_locale(values: &Value, environ: &Environ) -> Py<&'static str> {
    let values = or_empty(values)?;
    let chosen = get(values, "continuation_language");
    if let Some(word) = text(chosen)
        && let Some(offered) = l10n::OFFERED.iter().copied().find(|each| *each == word)
    {
        return Ok(offered);
    }
    let preference = text(get(values, "interface_language"));
    Ok(l10n::resolve(preference, environ.variable, environ.windows))
}

/// `style_from(values)`.
pub fn style_from(values: &Value) -> Py<String> {
    let style = fold_style(get(or_empty(values)?, "continuation_style"));
    Ok(STYLES
        .iter()
        .copied()
        .find(|each| in_tuple(&style, &[each]))
        .unwrap_or(DEFAULT_STYLE)
        .to_owned())
}

/// `custom_from(values, thread_id)`: `{mode, text, per_reason, conversation}`.
pub fn custom_from(values: &Value, thread_id: &Value) -> Py<Value> {
    let map = or_empty(values)?;
    let mode = get(map, "custom_message_mode");
    let mode = CUSTOM_MODES
        .iter()
        .copied()
        .find(|each| in_tuple(mode, &[each]))
        .unwrap_or(DEFAULT_CUSTOM_MODE);
    let mut per = Map::new();
    for category in RECOVERABLE {
        per.insert(
            (*category).into(),
            get(map, &format!("custom_message_{category}")).clone(),
        );
    }
    let mut custom = Map::new();
    custom.insert("mode".into(), Value::from(mode));
    custom.insert("text".into(), get(map, "custom_message").clone());
    custom.insert("per_reason".into(), Value::Object(per));
    custom.insert("conversation".into(), conversation_text(values, thread_id)?);
    Ok(Value::Object(custom))
}

/// `_thread_of(row)`.
fn thread_of(row: &Value) -> Py<Value> {
    Ok(record(row)?.map_or(Value::Null, |row| get(row, "thread_id").clone()))
}

/// `format_reset_time(stamp)`: a reset time as a person reads it on this machine (`%H:%M`), or None.
pub fn format_reset_time(stamp: &Value, clock: &dyn LocalClock) -> Value {
    if !truthy(stamp) {
        return Value::Null;
    }
    let Ok(seconds) = car_machine::pytext::to_float(stamp) else {
        return Value::Null;
    };
    match clock.localtime(seconds) {
        Ok(tm) => Value::from(format!("{:02}:{:02}", tm.hour, tm.min)),
        Err(_) => Value::Null,
    }
}

/// `_settings_metadata(values, row, limits, environ)`: the locale, and the metadata `for_settings` builds with.
fn settings_metadata(
    values: &Value,
    row: &Value,
    limits: &Value,
    environ: &Environ,
    clock: &dyn LocalClock,
) -> Py<(&'static str, Map)> {
    let locale = resolve_locale(values, environ)?;
    let reset_at = record(row)?.map_or(&Value::Null, |row| get(row, "reset_at"));
    let reset_time = format_reset_time(reset_at, clock);
    Ok((locale, metadata_for(row, locale, limits, &reset_time)?))
}

/// What `for_settings`, `source_for` and `with_once_words` are given beside the category.
pub struct Settings<'a> {
    pub values: &'a Value,
    pub row: &'a Value,
    pub limits: &'a Value,
    pub environ: &'a Environ<'a>,
    pub clock: &'a dyn LocalClock,
}

/// `source_for(category, values, row=, limits=, environ=)`: which text a continuation for this category uses -
/// `conversation`, `per_reason`, `global`, `standard`, or None for a style other than Custom.
pub fn source_for(category: &Value, at: &Settings) -> Py<Option<&'static str>> {
    let (locale, metadata) = settings_metadata(at.values, at.row, at.limits, at.environ, at.clock)?;
    let entry = reasons::get_value(category)?;
    let filled = message_values(entry, locale, &Value::Object(metadata))?;
    let custom = custom_from(at.values, &thread_of(at.row)?)?;
    if conversation_choice(entry, &custom, &filled).is_some() {
        return Ok(Some("conversation"));
    }
    if style_from(at.values)? != "custom" {
        return Ok(None);
    }
    Ok(Some(
        custom_choice(category, &custom, &filled)?.map_or("standard", |(source, _)| source),
    ))
}

/// `for_settings(category, values, row=, limits=, environ=)`: the exact continuation for one interruption.
pub fn for_settings(category: &Value, at: &Settings) -> Py<String> {
    let (locale, metadata) = settings_metadata(at.values, at.row, at.limits, at.environ, at.clock)?;
    let style = Value::from(style_from(at.values)?);
    let custom = custom_from(at.values, &thread_of(at.row)?)?;
    build(category, locale, &style, &custom, &Value::Object(metadata))
}

/// `with_once_words(message, words, category, values, ...)`: `message` with the words for this time after it.
pub fn with_once_words(
    message: &Value,
    words: &Value,
    category: &Value,
    at: &Settings,
) -> Py<Value> {
    if matches!(words, Value::Null) || !matches!(message, Value::Str(_)) {
        return Ok(message.clone());
    }
    let entry = reasons::get_value(category)?;
    if !entry.recoverable {
        return Ok(message.clone());
    }
    let Ok(words) = validate_custom(words) else {
        return Ok(message.clone());
    };
    let (locale, metadata) = settings_metadata(at.values, at.row, at.limits, at.environ, at.clock)?;
    let filled = fill(
        &words,
        &message_values(entry, locale, &Value::Object(metadata))?,
    );
    if !has_non_space(&Str::new(&filled)) {
        return Ok(message.clone());
    }
    let Value::Str(message) = message else {
        unreachable!("checked above")
    };
    Ok(Value::from(format!(
        "{}{ONCE_SEPARATOR}{filled}",
        String::from_utf8_lossy(message.as_bytes())
    )))
}

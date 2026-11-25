//! `control/preview.py`: the exact continuation the watcher would send, under settings that are being edited.
//!
//! Read-only, and the one place this layer builds a message at all: it saves nothing, sends nothing, and is why a
//! person can see what a setting will do before storing it. The text comes from `continuation.for_settings`, the same
//! function the watcher calls when it sends: there is no second rendering of a continuation anywhere.

use car_machine::json::{Map, Str, Value};
use car_policy::classify::continuation::{
    self, BY_THREAD_FIELD, CustomMessageError, Environ, Settings, coerce_by_thread, resolve_locale,
    source_for, style_from, validate_custom, with_once_words,
};
use car_policy::classify::reasons;
use car_policy::settings;

use crate::error::{Res, refuse, thread_id};
use crate::layer::Control;
use crate::status::other_class;

fn blank(value: &Value) -> bool {
    match value {
        Value::Str(text) => match text.as_str() {
            Some(plain) => car_machine::pytext::strip(plain).is_empty(),
            None => false,
        },
        _ => false,
    }
}

/// The first refusal a Custom message met: its sentence, its code and its detail.
type Refusal = (String, &'static str, Option<String>);

fn refusal_of(error: CustomMessageError) -> Refusal {
    (error.message, error.code, error.detail)
}

impl Control {
    /// `preview_continuation(category, changes=None, *, now=None, thread_id=None, once_words=None)`.
    pub fn preview_continuation(
        &self,
        category: &Value,
        changes: &Value,
        thread: &Value,
        once: &Value,
    ) -> Res<Value> {
        let recoverable = match category {
            Value::Str(text) => text
                .as_str()
                .is_some_and(|word| reasons::RECOVERABLE.contains(&word)),
            _ => false,
        };
        if !recoverable {
            return refuse(
                "a preview is only available for a recoverable kind of interruption",
                "request_failed",
            );
        }
        let os = self.host.os();
        let mut values = self.get_settings()?;
        let mut refusal: Option<Refusal> = None;
        if !matches!(changes, Value::Null) {
            let Value::Object(changes) = changes else {
                return refuse("changes must be an object", "request_failed");
            };
            let mut unknown: Vec<Str> = changes
                .keys()
                .filter(|name| {
                    name.as_str()
                        .is_none_or(|plain| settings::field_named(plain).is_none())
                })
                .cloned()
                .collect();
            unknown.sort();
            if !unknown.is_empty() {
                let mut text = b"unknown setting: ".to_vec();
                for (at, name) in unknown.iter().enumerate() {
                    if at > 0 {
                        text.extend_from_slice(b", ");
                    }
                    text.extend_from_slice(name.as_bytes());
                }
                return refuse(
                    Str::from_surrogatepass(text).unwrap_or_default(),
                    "request_failed",
                );
            }
            for (name, value) in changes {
                let plain = name.as_str().unwrap_or_default();
                let is_text = settings::is_custom_text(plain);
                if plain == BY_THREAD_FIELD {
                    // One conversation's own messages: each checked as a Custom message is, and a text that would
                    // be refused is said beside the preview and left out of it.
                    let texts: Vec<&Value> = match value {
                        Value::Object(map) => map.values().collect(),
                        Value::Null => Vec::new(),
                        other => vec![other],
                    };
                    for text in texts {
                        if let Err(error) = validate_custom(text)
                            && refusal.is_none()
                        {
                            refusal = Some(refusal_of(error));
                        }
                    }
                    values.insert(name.clone(), coerce_by_thread(value, &Value::Null));
                } else if is_text && !matches!(value, Value::Null) && !blank(value) {
                    if let Err(error) = validate_custom(value) {
                        if refusal.is_none() {
                            refusal = Some(refusal_of(error));
                        }
                        continue;
                    }
                    values.insert(name.clone(), value.clone());
                } else if is_text {
                    values.insert(name.clone(), Value::Null);
                } else {
                    values.insert(name.clone(), value.clone());
                }
            }
            values = settings::coerce(&*os, &Value::Object(values));
        }
        let moment = self.host.now();
        let has_reset = reasons::has_reset_time(category).map_err(other_class)?;
        let mut sample = Map::new();
        sample.insert(Str::from("category"), category.clone());
        sample.insert(Str::from("recovery_attempts"), Value::from(0));
        sample.insert(
            Str::from("reset_at"),
            if has_reset {
                Value::Float(moment + 3600.0)
            } else {
                Value::Null
            },
        );
        if !matches!(thread, Value::Null) {
            sample.insert(Str::from("thread_id"), Value::from(thread_id(thread)?));
        }
        let row = Value::Object(sample);
        let mut limit = Map::new();
        limit.insert(
            Str::from("max_recovery_attempts"),
            values
                .get("max_recovery_attempts")
                .cloned()
                .unwrap_or(Value::Null),
        );
        let limits = Value::Object(limit);
        let values = Value::Object(values);
        let host = &*self.host;
        let variable = |name: &str| host.environ(name);
        let windows = || host.windows_languages();
        let environ = Environ {
            variable: &variable,
            windows: &windows,
        };
        let clock = host.local_clock();
        let at = Settings {
            values: &values,
            row: &row,
            limits: &limits,
            environ: &environ,
            clock: &*clock,
        };
        let mut text = Value::from(continuation::for_settings(category, &at).map_err(other_class)?);
        if !matches!(once, Value::Null) && !blank(once) {
            match validate_custom(once) {
                Ok(_) => {
                    text = with_once_words(&text, once, category, &at).map_err(other_class)?;
                }
                Err(error) => {
                    if refusal.is_none() {
                        refusal = Some(refusal_of(error));
                    }
                }
            }
        }
        let locale = resolve_locale(&values, &environ).map_err(other_class)?;
        let style = style_from(&values).map_err(other_class)?;
        let source = source_for(category, &at).map_err(other_class)?;
        let (message, code, detail) = match refusal {
            Some((message, code, detail)) => (
                Value::from(message),
                Value::from(code),
                detail.map_or(Value::Null, Value::from),
            ),
            None => (Value::Null, Value::Null, Value::Null),
        };
        let mut reply = Map::new();
        let mut put = |name: &str, value: Value| {
            reply.insert(Str::from(name), value);
        };
        put("category", category.clone());
        put("locale", Value::from(locale));
        put("style", Value::from(style));
        put("source", source.map_or(Value::Null, Value::from));
        put("text", text);
        put("refusal", message);
        put("refusal_code", code);
        put("refusal_detail", detail);
        Ok(Value::Object(reply))
    }
}

//! `courier/channels.py` (seat S7.3b): the four channels a notice is pushed on, what a push says, and Telegram's
//! one-time pairing.
//!
//! What a push says ([`lines`]), in the person's language, at most three short lines: the event in words, then
//! `task N`, core's category word and the local time, then the edition - closed words and numbers alone.
//!
//! * ntfy: the lines POSTed as plain text, `Title` the product's name, `Tags` the event's word;
//! * webhook: `{"event", "category", "task", "at", "edition"}` as JSON, `Authorization: Bearer` where a token is kept;
//! * Telegram: the lines by `sendMessage` to the chat the pairing kept, the bot's token only in the request's path;
//! * e-mail: one plain-text message over SMTP on 465 (TLS from the start) or 587 (STARTTLS), after signing in.
//!
//! Every address and secret comes from Credential Manager under push_notices' names (`keep`). The opener
//! (`http::Opener`) and the SMTP wire (`smtp::Wire`) are the seams a test fills.

#![allow(clippy::result_unit_err)]

pub mod mime;
pub mod smtp;

use car_machine::json::{Map, Options, Str, Value, to_string};
use car_machine::localclock::LocalClock;

use crate::courier::address::{self, Shape};
use crate::courier::http::{self, Failure, Opener};
use crate::courier::keep::{self, BAD_CODES, CAPABILITY, PAIR_SECONDS};
use crate::courier::main::{EXIT_DONE, EXIT_NOT_PAIRED, EXIT_REFUSED, Runtime, exit_test};
use crate::courier::outbox;
use crate::credentials::Secrets;
use crate::state::sql::{self, Row, float, int, string};
use crate::statement::Catalogs;
use crate::vocabulary::{Actor, ArmingState, OffReason};

pub const TELEGRAM_API: &str = "https://api.telegram.org/bot";
pub const PRODUCT: &str = "Codex Auto Resume";
pub const EDITION: &str = "advanced";
/// Seconds Telegram is asked to hold one read open, while pairing.
pub const PAIR_POLL: f64 = 25.0;
pub const CONFLICT: i64 = 409;
pub const REMOTE: &str = "telegram_remote";
pub const ON: i64 = 1;
pub const OFF: i64 = 2;
/// One message's time in all over SMTP: four of the courier's timeouts.
pub const MAIL_SECONDS: i64 = 4 * http::TIMEOUT;

/// Where a push's words come from: this edition's catalogs, the person's language (None: the process's own), and the
/// local clock (`time.localtime`).
pub struct Words<'a> {
    pub catalogs: &'a Catalogs,
    pub locale: Option<&'a str>,
    pub local: &'a dyn LocalClock,
}

/// What sends: the opener for HTTPS, and a fresh SMTP wire for each message (its own time in all).
pub struct Seams<'a> {
    pub opener: &'a dyn Opener,
    pub smtp: &'a dyn Fn() -> Box<dyn smtp::Wire>,
    pub words: Words<'a>,
}

fn undecodable(_: crate::statement::Undecodable) -> Failure {
    Failure::raised("UnicodeDecodeError")
}

fn as_text(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => Some(address::text_of(&Value::Str(text.clone())).unwrap_or_default()),
        _ => None,
    }
}

fn is_number(value: &Value) -> bool {
    matches!(value, Value::Int(_) | Value::Float(_))
}

fn number(value: &Value) -> f64 {
    crate::state::py::as_f64(value).unwrap_or(f64::NAN)
}

// ------------------------------------------------------------------------------------------ what a push says
/// `lines(event, category, task, at, locale)`.
pub fn lines(
    event: &str,
    category: &Value,
    task: &Value,
    at: &Value,
    words: &Words<'_>,
) -> Result<Vec<String>, Failure> {
    let said = words
        .catalogs
        .text(&format!("page.push.{event}"), words.locale, &[])
        .map_err(undecodable)?
        .filter(|said| !said.is_empty())
        .unwrap_or_else(|| event.to_owned());
    let mut detail: Vec<String> = [as_text(task), as_text(category)]
        .into_iter()
        .flatten()
        .filter(|part| !part.is_empty())
        .collect();
    if is_number(at) {
        let tm = words.local.localtime(number(at)).map_err(Failure::raised)?;
        detail.push(format!("{:02}:{:02}", tm.hour, tm.min));
    }
    let mut found = vec![said];
    if !detail.is_empty() {
        found.push(detail.join(" \u{b7} "));
    }
    found.push(
        words
            .catalogs
            .text("page.push.edition", words.locale, &[])
            .map_err(undecodable)?
            .filter(|said| !said.is_empty())
            .unwrap_or_else(|| format!("{PRODUCT} ({EDITION})")),
    );
    found.truncate(3);
    Ok(found)
}

/// `int(x)` of a number as a JSON value (a float truncated towards zero); `Err` for NaN (ValueError) or an infinity
/// (OverflowError).
fn py_int(value: &Value) -> Result<Value, Failure> {
    match value {
        Value::Int(_) => Ok(value.clone()),
        Value::Float(x) if x.is_nan() => Err(Failure::raised("ValueError")),
        Value::Float(x) if x.is_infinite() => Err(Failure::raised("OverflowError")),
        Value::Float(x) => {
            let whole = x.trunc();
            if whole.abs() < 9.0e18 {
                Ok(Value::from(whole as i64))
            } else {
                car_machine::json::Int::parse(&format!("{whole:.0}"))
                    .map(Value::Int)
                    .ok_or_else(|| Failure::raised("OverflowError"))
            }
        }
        _ => Err(Failure::raised("TypeError")),
    }
}

/// `webhook_body(event, category, task, at)`.
pub fn webhook_body(
    event: &str,
    category: &Value,
    task: &Value,
    at: &Value,
) -> Result<Value, Failure> {
    let keep_text = |value: &Value| {
        if matches!(value, Value::Str(_)) {
            value.clone()
        } else {
            Value::Null
        }
    };
    let mut body = Map::new();
    body.insert(Str::from("event"), Value::from(event));
    body.insert(Str::from("category"), keep_text(category));
    body.insert(Str::from("task"), keep_text(task));
    body.insert(
        Str::from("at"),
        if is_number(at) {
            py_int(at)?
        } else {
            Value::Null
        },
    );
    body.insert(Str::from("edition"), Value::from(EDITION));
    Ok(Value::Object(body))
}

fn dumps(value: &Value, options: &Options) -> Result<Vec<u8>, Failure> {
    to_string(value, options)
        .map(String::into_bytes)
        .map_err(|_| Failure::raised("UnicodeEncodeError"))
}

fn saved_text(secrets: &Secrets<'_>, name: &str) -> Result<Option<String>, Failure> {
    keep::read(secrets, name).map_err(|_| Failure::raised("SecretError"))
}

// ------------------------------------------------------------------------------------------ sending
/// `send(channel, row, secrets, opener=, smtp=, locale=)`: "2xx", or Failed, NotSaved or AddressRefused.
pub fn send(
    channel: &str,
    row: &Row,
    secrets: &Secrets<'_>,
    seams: &Seams<'_>,
) -> Result<&'static str, Failure> {
    let get = |key: &str| row.get(key).cloned().unwrap_or(Value::Null);
    let Some(event_value) = row.get("event") else {
        return Err(Failure::raised("KeyError"));
    };
    let event = car_machine::pytext::py_str(event_value);
    let (category, task, at) = (get("category"), get("alias"), get("at"));
    let text = lines(&event, &category, &task, &at, &seams.words)?.join("\n");
    match channel {
        "ntfy" => {
            let url = saved_text(secrets, "ntfy_url")?.ok_or(Failure::NotSaved)?;
            let url = address::checked_url_text(&url)?;
            http::post(
                &url,
                text.as_bytes(),
                &[
                    ("Title", PRODUCT),
                    ("Tags", &event),
                    ("Content-Type", "text/plain; charset=utf-8"),
                ],
                http::TIMEOUT,
                seams.opener,
            )
        }
        "webhook" => {
            let url = saved_text(secrets, "webhook_url")?;
            let token = saved_text(secrets, "webhook_token")?;
            let url = url.ok_or(Failure::NotSaved)?;
            let mut headers: Vec<(&str, String)> =
                vec![("Content-Type", "application/json".into())];
            if let Some(token) = &token {
                let token = address::checked_token(&Value::from(token.as_str()), Shape::Printable)?;
                headers.push(("Authorization", format!("Bearer {token}")));
            }
            let body = dumps(
                &webhook_body(&event, &category, &task, &at)?,
                &Options::new().separators(",", ":"),
            )?;
            let url = address::checked_url_text(&url)?;
            let headers: Vec<(&str, &str)> =
                headers.iter().map(|(n, v)| (*n, v.as_str())).collect();
            http::post(&url, &body, &headers, http::TIMEOUT, seams.opener)
        }
        "telegram" => {
            let token = saved_text(secrets, "telegram_token")?;
            let chat = saved_text(secrets, "telegram_chat")?;
            let (Some(token), Some(chat)) = (token, chat) else {
                return Err(Failure::NotSaved);
            };
            address::checked_token(&Value::from(token.as_str()), Shape::TelegramToken)?;
            address::checked_token(&Value::from(chat.as_str()), Shape::TelegramChat)?;
            let chat_id = car_machine::json::Int::parse(&chat)
                .map(Value::Int)
                .ok_or_else(|| Failure::raised("ValueError"))?;
            let mut body = Map::new();
            body.insert(Str::from("chat_id"), chat_id);
            body.insert(Str::from("text"), Value::from(text.as_str()));
            body.insert(Str::from("disable_web_page_preview"), Value::Bool(true));
            let body = dumps(&Value::Object(body), &Options::new().ensure_ascii(false))?;
            http::post(
                &format!("{TELEGRAM_API}{token}/sendMessage"),
                &body,
                &[("Content-Type", "application/json")],
                http::TIMEOUT,
                seams.opener,
            )
        }
        "email" => {
            let blob = saved_text(secrets, "smtp")?.ok_or(Failure::NotSaved)?;
            let loaded = match crate::courier::feed::loads_bytes(blob.as_bytes()) {
                Ok(Some(value)) => value,
                Ok(None) => return Err(Failure::Refused("smtp")),
                Err(()) => return Err(Failure::raised("RecursionError")),
            };
            let settings = address::checked_smtp(&loaded).map_err(|_| Failure::Refused("smtp"))?;
            mail(&settings, &event, &text, (seams.smtp)().as_ref())
        }
        _ => Err(Failure::raised("ValueError")),
    }
}

/// `mail(settings, event, text, smtp=)`: one plain-text message over SMTP as `settings` say: "2xx", or Failed -
/// "4xx" for a refusal (a 5xx reply, the sign-in refused), "5xx" for the server's own trouble (a 4xx reply), "tls" for
/// a server that would not verify or offer STARTTLS, "timeout" for no answer.
pub fn mail(
    settings: &Value,
    event: &str,
    text: &str,
    wire: &dyn smtp::Wire,
) -> Result<&'static str, Failure> {
    let field = |key: &str| match settings {
        Value::Object(map) => map
            .get(key)
            .map(car_machine::pytext::py_str)
            .unwrap_or_default(),
        _ => String::new(),
    };
    let port = match settings {
        Value::Object(map) => map
            .get("port")
            .and_then(crate::state::py::small)
            .unwrap_or(0),
        _ => 0,
    };
    let (host, from, to) = (field("host"), field("from"), field("to"));
    let message = mime::flatten(&format!("{PRODUCT}: {event}"), &from, &to, text);
    let mut kept: Option<smtp::Session> = None;
    let done = (|| -> Result<(), smtp::Error> {
        let session = if port == 465 {
            smtp::open(wire, &host, 465, http::TIMEOUT, true)?
        } else {
            let session = smtp::open(wire, &host, 587, http::TIMEOUT, false)?;
            match session.starttls(wire, &host) {
                Ok(session) => session,
                Err((error, back)) => {
                    kept = back;
                    return Err(error);
                }
            }
        };
        let session = kept.insert(session);
        session.login(&field("user"), &field("password"))?;
        session.send_message(&from, &to, &message)
    })();
    if let Some(session) = kept {
        session.quit();
    }
    match done {
        Ok(()) => Ok("2xx"),
        Err(smtp::Error::NotSupported) => Err(Failure::failed("tls", None)),
        Err(smtp::Error::Authentication(_)) => Err(Failure::failed("4xx", Some(535))),
        Err(smtp::Error::Response(code)) => Err(Failure::failed(
            if code >= 500 { "4xx" } else { "5xx" },
            Some(code),
        )),
        Err(smtp::Error::Recipients) => Err(Failure::failed("4xx", None)),
        Err(smtp::Error::Tls) => Err(Failure::failed("tls", None)),
        Err(smtp::Error::Value) => Err(Failure::raised("Error")),
        Err(smtp::Error::Smtp | smtp::Error::Os) => Err(Failure::failed("timeout", None)),
    }
}

/// `test(runtime, channel, secrets, ...)`: the Dashboard's Send a test - the fixed test notice on `channel`, now; its
/// outcome as the courier's exit code.
pub fn test(runtime: &dyn Runtime, channel: &str, secrets: &Secrets<'_>, seams: &Seams<'_>) -> i32 {
    if !keep::saved(secrets, channel) {
        return EXIT_REFUSED;
    }
    let mut row = Row::new();
    row.insert(Str::from("event"), Value::from("test"));
    row.insert(Str::from("at"), Value::Float(runtime.clock()));
    let word = match send(channel, &row, secrets, seams) {
        Ok(word) => word,
        Err(Failure::Failed { word, .. }) => word,
        Err(failure) if failure.is_value_error() || failure == Failure::NotSaved => {
            return EXIT_REFUSED;
        }
        Err(_) => return EXIT_REFUSED,
    };
    exit_test(word).unwrap_or(EXIT_REFUSED)
}

/// What `drain` and `pair` raise beyond their own answers: the state's error or an exception out of a send.
#[derive(Debug)]
pub enum Raised {
    State(crate::state::Error),
    Send(Failure),
}

impl From<crate::state::Error> for Raised {
    fn from(error: crate::state::Error) -> Raised {
        Raised::State(error)
    }
}

fn counted(
    runtime: &dyn Runtime,
    capability: &str,
    code: &str,
) -> Result<bool, crate::state::Error> {
    runtime
        .state()
        .counted(&string(capability), &string(code), &Value::Null)
}

/// `drain(runtime, secrets, ...)`: one pass over the outbox; how many went.
pub fn drain(
    runtime: &dyn Runtime,
    secrets: &Secrets<'_>,
    seams: &Seams<'_>,
    now: Option<f64>,
) -> Result<i64, Raised> {
    let state = runtime.state();
    let now = now.unwrap_or_else(|| runtime.clock());
    for channel in outbox::expire(state, now)? {
        counted(
            runtime,
            CAPABILITY,
            &format!("dropped_{}", car_machine::pytext::py_str(&channel)),
        )?;
    }
    let since = state
        .arming()
        .ok()
        .and_then(|arming| match arming.get(CAPABILITY) {
            Some(Value::Object(row)) => row.get("since").cloned(),
            _ => None,
        })
        .unwrap_or(Value::Null);
    for channel in outbox::stale(state, &since, now)? {
        counted(
            runtime,
            CAPABILITY,
            &format!("dropped_{}", car_machine::pytext::py_str(&channel)),
        )?;
    }
    let mut sent = 0;
    for row in outbox::due(state, now)? {
        let channel = car_machine::pytext::py_str(sql::get(&row, "channel"));
        let item = sql::get(&row, "item_id").clone();
        let options = state.options(&string(CAPABILITY))?;
        if !sql::py_eq(sql::get(&options, &channel), &int(ON)) {
            drop_row(runtime, &item, &channel, now)?;
            continue;
        }
        match send(&channel, &row, secrets, seams) {
            Ok(_) => {}
            Err(failure) if failure == Failure::NotSaved || failure.is_value_error() => {
                drop_row(runtime, &item, &channel, now)?;
                continue;
            }
            Err(Failure::Failed { word, .. }) => {
                let word = if outbox::FAILED.contains(&word) {
                    word
                } else {
                    "timeout"
                };
                counted(runtime, CAPABILITY, &format!("refused_{channel}_{word}"))?;
                if outbox::settle(state, &item, false, now)? == "dropped" {
                    counted(runtime, CAPABILITY, &format!("dropped_{channel}"))?;
                }
                if outbox::REFUSING.contains(&word)
                    && outbox::refusals_today(state, &Value::from(channel.as_str()), now)?
                        >= outbox::TRIPWIRE
                {
                    let tripped = (|| -> Result<(), crate::state::Error> {
                        let generation = sql::get(&state.meta()?, "generation").clone();
                        state.set_option(
                            &string(CAPABILITY),
                            &string(&channel),
                            &int(OFF),
                            &generation,
                            &string(Actor::Tripwire.as_str()),
                            &Value::Null,
                        )?;
                        counted(runtime, CAPABILITY, &format!("off_{channel}"))?;
                        Ok(())
                    })();
                    let _ = tripped;
                }
                continue;
            }
            Err(other) => return Err(Raised::Send(other)),
        }
        outbox::settle(state, &item, true, now)?;
        counted(runtime, CAPABILITY, &format!("sent_{channel}"))?;
        sent += 1;
    }
    Ok(sent)
}

fn drop_row(
    runtime: &dyn Runtime,
    item: &Value,
    channel: &str,
    now: f64,
) -> Result<(), crate::state::Error> {
    runtime.state().writing(|connection| {
        sql::exec(
            connection,
            "UPDATE outbox SET state = 'dropped', finished_at = ? WHERE item_id = ? AND state = 'waiting'",
            &[float(now), item.clone()],
        )?;
        Ok(())
    })?;
    counted(runtime, CAPABILITY, &format!("dropped_{channel}"))?;
    Ok(())
}

// ------------------------------------------------------------------------------------------ Telegram's pairing
fn end_pairing(
    runtime: &dyn Runtime,
    offset: &Value,
    paired_at: &Value,
    bad: &Value,
) -> Result<(), crate::state::Error> {
    runtime.state().writing(|connection| {
        sql::exec(
            connection,
            "UPDATE remote SET code_digest = NULL, code_expires_at = NULL, paired_at = ?, \
             update_offset = coalesce(?, update_offset), bad_codes = coalesce(?, bad_codes) WHERE channel = 'telegram'",
            &[paired_at.clone(), offset.clone(), bad.clone()],
        )?;
        Ok(())
    })
}

/// `_updates(reply)` / `telegram.readable`: the updates of a getUpdates reply, or None for one that cannot be read as
/// one; `Err` is the RecursionError of a reply nested too deep.
pub fn readable(reply: &[u8]) -> Result<Option<Vec<Map>>, ()> {
    let Some(Value::Object(found)) = crate::courier::feed::loads_bytes(reply)? else {
        return Ok(None);
    };
    if !matches!(found.get("ok"), Some(Value::Bool(true))) {
        return Ok(None);
    }
    match found.get("result") {
        Some(Value::Array(result)) => Ok(Some(
            result
                .iter()
                .filter_map(|entry| match entry {
                    Value::Object(entry) => Some(entry.clone()),
                    _ => None,
                })
                .collect(),
        )),
        _ => Ok(None),
    }
}

fn trip_remote(runtime: &dyn Runtime) {
    if runtime.registry().get(REMOTE).is_none() {
        return;
    }
    if let Ok(states) = runtime.states()
        && states.state_of(REMOTE) != ArmingState::Off
    {
        let _ = runtime.trip(REMOTE, OffReason::BadCodes);
    }
}

/// `row[key] or 0` of a whole number the state kept.
fn or_zero(value: &Value) -> i64 {
    crate::state::py::small(value).unwrap_or(0)
}

/// `pair(runtime, secrets, opener=, clock=, sleep=)`: the bot's messages read until the one-time code arrives, it
/// expires, PAIR_SECONDS pass or BAD_CODES other codes came; the courier's exit code.
pub fn pair(
    runtime: &dyn Runtime,
    secrets: &Secrets<'_>,
    opener: &dyn Opener,
    clock: &dyn Fn() -> f64,
    sleep: &dyn Fn(f64),
) -> Result<i32, Raised> {
    let token = match keep::read(secrets, "telegram_token") {
        Ok(token) => token.unwrap_or_default(),
        Err(_) => return Ok(EXIT_REFUSED),
    };
    if !address::fits(&token, Shape::TelegramToken) {
        return Ok(EXIT_REFUSED);
    }
    let row = keep::pairing(runtime.state())?;
    let start = clock();
    let Some(row) = row else {
        return Ok(EXIT_REFUSED);
    };
    let digest = sql::get(&row, "code_digest").clone();
    let expires = match sql::get(&row, "code_expires_at") {
        Value::Float(at) if !matches!(digest, Value::Null) && *at > start => *at,
        _ => return Ok(EXIT_REFUSED),
    };
    let deadline = expires.min(start + PAIR_SECONDS);
    let mut offset = or_zero(sql::get(&row, "update_offset"));
    let mut bad = or_zero(sql::get(&row, "bad_codes"));
    while clock() < deadline {
        let wait = (deadline - clock()).clamp(1.0, PAIR_POLL) as i64;
        let url = format!(
            "{TELEGRAM_API}{token}/getUpdates?timeout={wait}&offset={}",
            offset
        );
        let reply = match http::get(&url, wait + http::TIMEOUT, opener, http::MAX_REPLY) {
            Ok(reply) => reply,
            Err(Failure::Failed { word, status }) => {
                if outbox::REFUSING.contains(&word) && status != Some(CONFLICT) {
                    end_pairing(runtime, &int(offset), &Value::Null, &int(bad))?;
                    return Ok(EXIT_REFUSED);
                }
                sleep(2.0);
                continue;
            }
            Err(other) => return Err(Raised::Send(other)),
        };
        let updates = readable(&reply)
            .map_err(|()| Raised::Send(Failure::raised("RecursionError")))?
            .unwrap_or_default();
        for update in updates {
            if let Some(number) = update.get("update_id").and_then(crate::state::py::small)
                && number >= offset
            {
                offset = number + 1;
            }
            let message = match update.get("message") {
                Some(Value::Object(message)) => message.clone(),
                _ => Map::new(),
            };
            let text = match message.get("text") {
                Some(Value::Str(text)) => car_machine::pytext::strip(
                    &as_text(&Value::Str(text.clone())).unwrap_or_default(),
                )
                .to_owned(),
                _ => String::new(),
            };
            let chat = match message.get("chat") {
                Some(Value::Object(chat)) => chat.get("id").cloned(),
                _ => None,
            };
            let Some(Value::Int(chat)) = chat else {
                continue;
            };
            if !keep::is_code(&text) {
                continue;
            }
            if sql::py_eq(&Value::from(keep::digest(&text)), &digest) {
                secrets
                    .write(
                        CAPABILITY,
                        &string("telegram_chat"),
                        &Value::from(car_machine::pytext::py_str(&Value::Int(chat.clone()))),
                    )
                    .map_err(|_| Raised::Send(Failure::raised("SecretError")))?;
                keep::keep_chat_name(secrets, message.get("chat").unwrap_or(&Value::Null));
                end_pairing(runtime, &int(offset), &float(clock()), &int(0))?;
                return Ok(EXIT_DONE);
            }
            bad += 1;
            if bad >= BAD_CODES {
                end_pairing(runtime, &int(offset), &Value::Null, &int(BAD_CODES))?;
                trip_remote(runtime);
                return Ok(EXIT_NOT_PAIRED);
            }
        }
        runtime.state().writing(|connection| {
            sql::exec(
                connection,
                "UPDATE remote SET update_offset = ?, bad_codes = ? WHERE channel = 'telegram'",
                &[int(offset), int(bad)],
            )?;
            Ok(())
        })?;
    }
    end_pairing(runtime, &int(offset), &Value::Null, &int(bad))?;
    Ok(EXIT_NOT_PAIRED)
}

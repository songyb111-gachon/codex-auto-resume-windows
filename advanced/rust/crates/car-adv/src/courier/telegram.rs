//! `courier/telegram.py` (seat S7.3b): remote control over Telegram (telegram_remote, telegram_continue) - the resident
//! courier's long poll of the bot push_notices keeps, obeying the one chat its pairing kept.
//!
//! [`Poller::once`] asks Telegram for the bot's new messages (getUpdates, held open up to [`POLL`] seconds, the offset
//! kept in the `remote` table) and waits while a pairing is under way. A message from any chat but the paired one is
//! ignored without an answer, and so is one older than [`FRESH`] seconds (or more than [`AHEAD`] newer than this PC's
//! clock). The paired chat's text is read as one of [`COMMANDS`] and nothing else; a command addressed to another bot
//! by name is passed over. No command sends to Codex. Answers are closed words, numbers and `task N` alone. The offset
//! is kept before a message is acted on: a command is carried out at most once. A reply that cannot be read makes the
//! next read ask for one message alone, and one that alone is still too long is passed over by its update_id.

#![allow(clippy::result_unit_err)]

use std::sync::{Arc, Condvar, Mutex};

use car_machine::json::{Map, Str, Value};
use car_machine::localclock::LocalClock;
use car_platform::credman::Backend;

use crate::control::remote::{self as remote_layer, Failed, Layer};
use crate::courier::address;
use crate::courier::channels::{self, TELEGRAM_API};
use crate::courier::http::{self, Failure, Opener};
use crate::courier::keep;
use crate::courier::main::SharedRuntime;
use crate::credentials::Secrets;
use crate::state::sql::{self, int, string};
use crate::statement::Catalogs;
use crate::vocabulary::ArmingState;

pub const TELEGRAM: &str = "telegram_remote";
pub const TELEGRAM_CONTINUE: &str = "telegram_continue";
pub const POLL: i64 = 50;
pub const IDLE: f64 = 30.0;
pub const AFTER_REFUSAL: f64 = 60.0;
pub const AFTER_FAILURE: f64 = 10.0;
pub const CONFLICT: i64 = 409;
pub const FRESH: i64 = 300;
pub const AHEAD: i64 = FRESH;
pub const UPDATES: i64 = 2;
pub const IGNORED_EVERY: f64 = 3600.0;
pub const MAX_TEXT: usize = 64;
pub const LISTED: usize = 20;
pub const TAKES_TASK: [&str; 2] = ["/cancel", "/continue"];
pub const CODES: [&str; 6] = [
    "status",
    "listed",
    "cancelled",
    "paused",
    "list_again",
    "ignored",
];

/// `COMMANDS`: every command, with the capability that allows it.
pub const COMMANDS: [(&str, &str); 6] = [
    ("/status", TELEGRAM),
    ("/list", TELEGRAM),
    ("/cancel", TELEGRAM),
    ("/pause", TELEGRAM),
    ("/continue", TELEGRAM_CONTINUE),
    ("/recovery-on", TELEGRAM_CONTINUE),
];

fn command_capability(command: &str) -> Option<&'static str> {
    COMMANDS
        .iter()
        .find(|(name, _)| *name == command)
        .map(|(_, capability)| *capability)
}

/// `threading.Event`: set once, waited on with a timeout.
#[derive(Clone, Default)]
pub struct Stop(Arc<(Mutex<bool>, Condvar)>);

impl Stop {
    pub fn new() -> Stop {
        Stop::default()
    }

    pub fn set(&self) {
        let (flag, wake) = &*self.0;
        *flag
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = true;
        wake.notify_all();
    }

    pub fn is_set(&self) -> bool {
        *self
            .0
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// `wait(seconds)`: whether it was set.
    pub fn wait(&self, seconds: f64) -> bool {
        let (flag, wake) = &*self.0;
        let held = flag
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let limit = std::time::Duration::from_secs_f64(seconds.clamp(0.0, 86400.0));
        let (held, _) = wake
            .wait_timeout_while(held, limit, |set| !*set)
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *held
    }
}

/// `str.split()` of a Python text: on runs of Unicode white space.
fn py_split(text: &str) -> Vec<&str> {
    text.split(car_machine::pytext::is_space)
        .filter(|part| !part.is_empty())
        .collect()
}

/// `parse(text)`: (command, `task N` or None) of a message's text, or (None, None) for anything that is not one.
pub fn parse(text: &Value) -> (Option<&'static str>, Option<String>) {
    let Value::Str(raw) = text else {
        return (None, None);
    };
    if raw.code_points().count() > MAX_TEXT {
        return (None, None);
    }
    let text = address::text_of(text).unwrap_or_default();
    let words = py_split(car_machine::pytext::strip(&text));
    let Some(first) = words.first() else {
        return (None, None);
    };
    let command = first.split('@').next().unwrap_or("").to_lowercase();
    let Some((name, _)) = COMMANDS.iter().find(|(name, _)| *name == command) else {
        return (None, None);
    };
    let mut rest: Vec<&str> = words[1..].to_vec();
    if !TAKES_TASK.contains(name) {
        return if rest.is_empty() {
            (Some(name), None)
        } else {
            (None, None)
        };
    }
    if rest.len() == 2 && rest[0].to_lowercase() == "task" {
        rest.remove(0);
    }
    if rest.len() == 1 {
        let number = rest[0];
        if number.is_ascii()
            && !number.is_empty()
            && number.bytes().all(|b| b.is_ascii_digit())
            && !number.starts_with('0')
            && number.len() <= 4
        {
            return (Some(name), Some(format!("task {number}")));
        }
    }
    (None, None)
}

/// `readable(reply)`: the updates of a getUpdates reply, or None for a reply that cannot be read as one. `Err` is the
/// RecursionError of a reply nested too deep.
pub fn readable(reply: &[u8]) -> Result<Option<Vec<Map>>, ()> {
    channels::readable(reply)
}

/// `UPDATE_ID.search(reply)`: the first `"update_id": N` after `{` or `,` (N of 1 to 19 digits), as a number.
pub fn first_update_id(reply: &[u8]) -> Option<i64> {
    let key = b"\"update_id\"";
    let mut at = 0;
    while at < reply.len() {
        if reply[at] == b'{' || reply[at] == b',' {
            let mut cursor = at + 1;
            while cursor < reply.len() && is_regex_space(reply[cursor]) {
                cursor += 1;
            }
            if reply[cursor..].starts_with(key) {
                cursor += key.len();
                while cursor < reply.len() && is_regex_space(reply[cursor]) {
                    cursor += 1;
                }
                if reply.get(cursor) == Some(&b':') {
                    cursor += 1;
                    while cursor < reply.len() && is_regex_space(reply[cursor]) {
                        cursor += 1;
                    }
                    let start = cursor;
                    while cursor < reply.len()
                        && reply[cursor].is_ascii_digit()
                        && cursor - start < 19
                    {
                        cursor += 1;
                    }
                    if cursor > start {
                        let digits = std::str::from_utf8(&reply[start..cursor]).ok()?;
                        return digits.parse::<i64>().ok().or(Some(i64::MAX));
                    }
                }
            }
        }
        at += 1;
    }
    None
}

/// `\s` of a bytes pattern: ASCII white space.
fn is_regex_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c)
}

/// The words of answers: this edition's catalogs, core's (for a state code), the person's language and the local
/// clock.
pub struct Words {
    pub catalogs: Arc<Catalogs>,
    /// The person's language, or None for the process's own (`current`).
    pub locale: Option<String>,
    pub current: Arc<dyn Fn() -> String + Send + Sync>,
    pub local: Arc<dyn LocalClock + Send + Sync>,
}

/// `Poller(runtime, secrets=, opener=, layer=, clock=, locale=)`: one bot read at a time, and what the paired chat
/// last listed.
pub struct Poller {
    pub runtime: SharedRuntime,
    pub backend: Arc<dyn Backend>,
    pub opener: Arc<dyn Opener>,
    pub layer: Arc<dyn Layer + Send + Sync>,
    pub clock: Arc<dyn Fn() -> f64 + Send + Sync>,
    pub words: Words,
    pub listed: Option<String>,
    pub offered: Option<String>,
    pub ignored_at: Option<f64>,
    pub name: Option<String>,
    pub alone: bool,
}

impl Poller {
    fn secrets(&self) -> Secrets<'_> {
        Secrets::new(self.runtime.registry(), self.backend.clone())
    }

    fn counted(&self, capability: &str, code: &str) -> Result<bool, crate::state::Error> {
        self.runtime
            .state()
            .counted(&string(capability), &string(code), &Value::Null)
    }

    /// `_kept()`: (token, chat) the pairing kept, each checked - or None.
    fn kept(&self) -> Option<(String, Value)> {
        let secrets = self.secrets();
        let token = keep::read(&secrets, "telegram_token").ok()?;
        let chat = keep::read(&secrets, "telegram_chat").ok()?;
        let (Some(token), Some(chat)) = (token, chat) else {
            return None;
        };
        if !address::telegram_token(&token) || !address::telegram_chat(&chat) {
            return None;
        }
        let chat = car_machine::json::Int::parse(&chat).map(Value::Int)?;
        Some((token, chat))
    }

    fn pairing_row(&self) -> Map {
        keep::pairing(self.runtime.state())
            .ok()
            .flatten()
            .unwrap_or_default()
    }

    fn pairing_now(&self) -> bool {
        let row = self.pairing_row();
        car_machine::pyval::truthy(sql::get(&row, "code_digest"))
            && crate::state::py::as_f64(sql::get(&row, "code_expires_at")).unwrap_or(0.0)
                > (self.clock)()
    }

    fn offset(&self) -> i64 {
        match sql::get(&self.pairing_row(), "update_offset") {
            Value::Int(found) => found.as_i64().filter(|found| *found >= 0).unwrap_or(0),
            _ => 0,
        }
    }

    fn keep_offset(&self, offset: i64) -> Result<(), crate::state::Error> {
        self.runtime.state().writing(|connection| {
            sql::exec(
                connection,
                "INSERT INTO remote (channel, paired_at, bad_codes, update_offset) VALUES ('telegram', NULL, 0, ?) \
                 ON CONFLICT(channel) DO UPDATE SET update_offset = excluded.update_offset",
                &[int(offset)],
            )?;
            Ok(())
        })
    }

    /// `once(stop)`: one read of the bot and every message it brought, answered; the seconds to wait before the next.
    pub fn once(&mut self, stop: Option<&Stop>) -> Result<f64, crate::state::Error> {
        let Some((token, chat)) = self.kept() else {
            return Ok(IDLE);
        };
        if self.pairing_now() {
            return Ok(IDLE);
        }
        let mut offset = self.offset();
        let alone = std::mem::replace(&mut self.alone, false);
        let url = format!(
            "{TELEGRAM_API}{token}/getUpdates?timeout={POLL}&offset={offset}&limit={}",
            if alone { 1 } else { UPDATES }
        );
        let reply = match http::get(
            &url,
            POLL + http::TIMEOUT,
            self.opener.as_ref(),
            http::MAX_REPLY,
        ) {
            Ok(reply) => reply,
            Err(Failure::Failed { word, status }) => {
                if status == Some(CONFLICT) {
                    return Ok(AFTER_FAILURE);
                }
                return Ok(if word == "4xx" || word == "tls" {
                    AFTER_REFUSAL
                } else {
                    AFTER_FAILURE
                });
            }
            Err(_) => return Ok(AFTER_FAILURE),
        };
        if stop.is_some_and(Stop::is_set) {
            return Ok(0.0);
        }
        let found = match readable(&reply) {
            Ok(Some(found)) => found,
            _ => {
                if alone {
                    if let Some(first) = first_update_id(&reply)
                        && first >= offset
                    {
                        self.keep_offset(first.saturating_add(1))?;
                    }
                } else {
                    self.alone = true;
                }
                return Ok(AFTER_FAILURE);
            }
        };
        let start = offset;
        for update in &found {
            if let Some(Value::Int(number)) = update.get("update_id")
                && let Some(number) = number.as_i64()
                && number >= offset
            {
                offset = number.saturating_add(1);
            }
        }
        self.keep_offset(offset)?;
        let mut ignored = false;
        let now = (self.clock)();
        for update in &found {
            let message = match update.get("message") {
                Some(Value::Object(message)) => message.clone(),
                _ => Map::new(),
            };
            let sender = match message.get("chat") {
                Some(Value::Object(chat)) => chat.get("id").cloned(),
                _ => None,
            };
            let sent_at = message.get("date").cloned();
            let fresh = match (&sender, &sent_at) {
                (Some(Value::Int(_)), Some(Value::Int(at))) => match at.as_i64() {
                    Some(at) => {
                        let age = now - at as f64;
                        sql::py_eq(sender.as_ref().unwrap_or(&Value::Null), &chat)
                            && -(AHEAD as f64) <= age
                            && age <= FRESH as f64
                    }
                    None => false,
                },
                _ => false,
            };
            if !fresh {
                ignored = true;
                continue;
            }
            keep::keep_chat_name(&self.secrets(), message.get("chat").unwrap_or(&Value::Null));
            let text = message.get("text").cloned().unwrap_or(Value::Null);
            if self.elsewhere(&token, &text) {
                continue;
            }
            self.offered = None;
            let said = self.answer(&text);
            if self.reply(&token, &chat, &said).is_err() {
                continue;
            }
            if self.offered.is_some() {
                self.listed = self.offered.clone();
            }
        }
        if ignored
            && self
                .ignored_at
                .is_none_or(|at| !(0.0 <= now - at && now - at < IGNORED_EVERY))
        {
            self.ignored_at = Some(now);
            self.counted(TELEGRAM, "ignored")?;
        }
        Ok(if !found.is_empty() && offset == start {
            AFTER_FAILURE
        } else {
            0.0
        })
    }

    /// `own_name(token)`: this bot's name (getMe), lower case - asked once and kept - or None.
    pub fn own_name(&mut self, token: &str) -> Option<String> {
        if self.name.is_none() {
            let reply = http::get(
                &format!("{TELEGRAM_API}{token}/getMe"),
                http::TIMEOUT,
                self.opener.as_ref(),
                http::MAX_REPLY,
            )
            .ok()?;
            let Ok(Some(Value::Object(found))) = crate::courier::feed::loads_bytes(&reply) else {
                return None;
            };
            let name = if matches!(found.get("ok"), Some(Value::Bool(true))) {
                match found.get("result") {
                    Some(Value::Object(result)) => result.get("username").cloned(),
                    Some(_) => return None,
                    None => None,
                }
            } else {
                None
            };
            self.name = match name {
                Some(Value::Str(name)) if !name.is_empty() => {
                    address::text_of(&Value::Str(name)).map(|name| name.to_lowercase())
                }
                _ => None,
            };
        }
        self.name.clone()
    }

    /// `elsewhere(token, text)`: a command addressed by name to another bot (or to a name this one cannot confirm).
    pub fn elsewhere(&mut self, token: &str, text: &Value) -> bool {
        let Some(text) = (match text {
            Value::Str(_) => address::text_of(text),
            _ => None,
        }) else {
            return false;
        };
        let stripped = car_machine::pytext::strip(&text);
        if !stripped.starts_with('/') {
            return false;
        }
        let first = py_split(stripped).first().copied().unwrap_or("");
        let Some((_, name)) = first.split_once('@') else {
            return false;
        };
        Some(name.to_lowercase()) != self.own_name(token)
    }

    /// `reply(token, chat, text)`: the paired chat answered (sendMessage).
    pub fn reply(&self, token: &str, chat: &Value, text: &str) -> Result<&'static str, Failure> {
        let mut body = Map::new();
        body.insert(Str::from("chat_id"), chat.clone());
        body.insert(Str::from("text"), Value::from(text));
        body.insert(Str::from("disable_web_page_preview"), Value::Bool(true));
        let body = car_machine::json::to_string(
            &Value::Object(body),
            &car_machine::json::Options::new().ensure_ascii(false),
        )
        .map_err(|_| Failure::raised("UnicodeEncodeError"))?;
        http::post(
            &format!("{TELEGRAM_API}{token}/sendMessage"),
            body.as_bytes(),
            &[("Content-Type", "application/json")],
            http::TIMEOUT,
            self.opener.as_ref(),
        )
    }

    // ---------------------------------------------------------------------------- the commands
    fn word(&self, key: &str, fallback: &str, fields: &[(&str, String)]) -> String {
        let found = self
            .words
            .catalogs
            .text(key, self.words.locale.as_deref(), fields)
            .ok()
            .flatten()
            .filter(|said| !said.is_empty());
        found.unwrap_or_else(|| {
            let mut text = fallback.to_owned();
            for (name, value) in fields {
                text = text.replace(&format!("{{{name}}}"), value);
            }
            text
        })
    }

    fn allowed(&self, capability: &str) -> bool {
        self.runtime
            .states()
            .is_ok_and(|states| states.get(capability) == Some(ArmingState::Armed))
    }

    fn help(&self) -> String {
        let names: Vec<&str> = COMMANDS
            .iter()
            .filter(|(_, capability)| self.allowed(capability))
            .map(|(name, _)| *name)
            .collect();
        self.word(
            "page.remote.answer.help",
            "Commands: {commands}",
            &[("commands", names.join(", "))],
        )
    }

    /// `answer(text)`: what the paired chat is answered - and, for an allowed command, it carried out.
    pub fn answer(&mut self, text: &Value) -> String {
        let (command, alias) = parse(text);
        let Some(command) = command else {
            return self.help();
        };
        let capability = command_capability(command).unwrap_or(TELEGRAM);
        if !self.allowed(TELEGRAM) || !self.allowed(capability) {
            return self.word(
                "page.remote.answer.not_allowed",
                "That command is not turned on.",
                &[],
            );
        }
        match self.carry(command, alias) {
            Ok(said) => said,
            Err(Failed::Stale) => {
                let _ = self.counted(TELEGRAM, "list_again");
                self.word(
                    "page.remote.answer.list_again",
                    "The list has changed. Send /list again.",
                    &[],
                )
            }
            Err(Failed::Raised(_)) => {
                self.word("page.remote.answer.refused", "That could not be done.", &[])
            }
        }
    }

    fn count_or_raise(&self, capability: &str, code: &str) -> Result<(), Failed> {
        self.counted(capability, code)
            .map(|_| ())
            .map_err(|error| Failed::Raised(error.class().to_owned()))
    }

    fn carry(&mut self, command: &str, alias: Option<String>) -> Result<String, Failed> {
        match command {
            "/status" => {
                self.count_or_raise(TELEGRAM, "status")?;
                self.status()
            }
            "/list" => {
                self.count_or_raise(TELEGRAM, "listed")?;
                self.list()
            }
            "/pause" => {
                remote_layer::pause(self.layer.as_ref())?;
                self.count_or_raise(TELEGRAM, "paused")?;
                Ok(self.word("page.remote.answer.paused", "Recovery is paused.", &[]))
            }
            "/recovery-on" => {
                remote_layer::lift_pause(self.layer.as_ref())?;
                self.count_or_raise(TELEGRAM_CONTINUE, "pause_lifted")?;
                Ok(self.word(
                    "page.remote.answer.pause_lifted",
                    "Recovery is on again.",
                    &[],
                ))
            }
            _ => self.by_task(command, &alias.unwrap_or_default()),
        }
    }

    fn by_task(&mut self, command: &str, alias: &str) -> Result<String, Failed> {
        let number = alias
            .split_once(' ')
            .map_or("", |(_, number)| number)
            .to_owned();
        let listed = self.listed.clone().map_or(Value::Null, Value::from);
        if command == "/cancel" {
            remote_layer::cancel(self.layer.as_ref(), &Value::from(alias), &listed)?;
            self.count_or_raise(TELEGRAM, "cancelled")?;
            return Ok(self.word(
                "page.remote.answer.cancelled",
                "task {n} is cancelled.",
                &[("n", number)],
            ));
        }
        remote_layer::release(self.layer.as_ref(), &Value::from(alias), &listed)?;
        self.count_or_raise(TELEGRAM_CONTINUE, "continued")?;
        Ok(self.word(
            "page.remote.answer.continued",
            "task {n} goes on. Nothing is sent until every check passes.",
            &[("n", number)],
        ))
    }

    fn status(&self) -> Result<String, Failed> {
        let document = self.layer.status_document((self.clock)())?;
        let get = |key: &str| match &document {
            Value::Object(map) => map
                .get(key)
                .cloned()
                .ok_or_else(|| Failed::Raised("KeyError".into())),
            _ => Err(Failed::Raised("TypeError".into())),
        };
        let (watcher, recovery) = (
            car_machine::pytext::py_str(&get("watcher")?),
            car_machine::pytext::py_str(&get("recovery")?),
        );
        let pending = car_machine::pytext::py_str(&get("pending")?);
        let watcher = self.word(&format!("page.remote.word.{watcher}"), &watcher, &[]);
        let recovery = self.word(&format!("page.remote.word.{recovery}"), &recovery, &[]);
        Ok(self.word(
            "page.remote.answer.status",
            "Watcher {watcher}, recovery {recovery}, {n} waiting.",
            &[("watcher", watcher), ("recovery", recovery), ("n", pending)],
        ))
    }

    fn list(&mut self) -> Result<String, Failed> {
        let found = remote_layer::pending(self.layer.as_ref())?;
        let (snapshot, rows) = match &found {
            Value::Object(map) => (
                map.get("snapshot").cloned().unwrap_or(Value::Null),
                match map.get("pending") {
                    Some(Value::Array(rows)) => rows.clone(),
                    _ => Vec::new(),
                },
            ),
            _ => (Value::Null, Vec::new()),
        };
        self.offered = crate::state::py::text(&snapshot).map(str::to_owned);
        if rows.is_empty() {
            return Ok(self.word("page.remote.answer.list_none", "Nothing waits.", &[]));
        }
        let mut lines = Vec::new();
        for row in rows.iter().take(LISTED) {
            let field = |key: &str| match row {
                Value::Object(map) => map.get(key).cloned().unwrap_or(Value::Null),
                _ => Value::Null,
            };
            let at = field("next_check_at");
            let when = if car_machine::pyval::truthy(&at) {
                let tm = self
                    .words
                    .local
                    .localtime(crate::state::py::as_f64(&at).unwrap_or(f64::NAN))
                    .map_err(|class| Failed::Raised(class.to_owned()))?;
                format!("{:02}:{:02}", tm.hour, tm.min)
            } else {
                "-".to_owned()
            };
            let state = car_machine::pytext::py_str(&field("state"));
            lines.push(self.word(
                "page.remote.answer.list_item",
                "{task}: {state}, next check {at}",
                &[
                    ("task", car_machine::pytext::py_str(&field("task"))),
                    ("state", self.state_word(&state)),
                    ("at", when),
                ],
            ));
        }
        Ok(lines.join("\n"))
    }

    /// `_state_word(code)`: a public state code in the person's language, core's word for it, else the code.
    fn state_word(&self, code: &str) -> String {
        let locale = self
            .words
            .locale
            .clone()
            .unwrap_or_else(|| (self.words.current)());
        match car_words::l10n::text(&format!("code.{code}"), &locale, &[]) {
            Some(said) if !said.is_empty() && said != format!("code.{code}") => said,
            _ => code.to_owned(),
        }
    }
}

/// `run(runtime, stop, ...)`: read the bot until `stop` is set.
pub fn run(mut poller: Poller, stop: &Stop) {
    while !stop.is_set() {
        let wait = poller.once(Some(stop)).unwrap_or(AFTER_FAILURE);
        if wait > 0.0 {
            stop.wait(wait);
        }
    }
}

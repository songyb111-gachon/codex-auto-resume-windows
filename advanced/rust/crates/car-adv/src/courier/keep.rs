//! `courier/keep.py` (seat S7.3b): what the courier keeps, and where - with no network: push_notices' secrets in Windows
//! Credential Manager (through `crate::credentials`), and Telegram's one-time pairing in the `remote` table.
//!
//! Secrets: the ntfy topic's address, the webhook's address and its optional bearer token, the Telegram bot's token and
//! the paired chat, and the e-mail channel's settings as one JSON blob. None is kept anywhere else and none is ever
//! answered to the Dashboard. One beside them is no secret: the paired chat's name as Telegram gave it.
//!
//! The pairing: the Dashboard shows a code of six digits and keeps only its SHA-256 digest and when it expires
//! ([`PAIR_SECONDS`]); a courier run with `--pair` keeps the chat whose message is that code (`channels::pair`).

use car_machine::json::Value;

use crate::credentials::{SecretError, Secrets};
use crate::state::sql::{self, Row, float, string};
use crate::state::{AdvancedState, Error, Result};

pub const CAPABILITY: &str = "push_notices";
pub const CHAT_NAME: &str = "telegram_chat_name";
/// Characters of a chat's name the card shows.
pub const MAX_CHAT_NAME: usize = 64;
pub const SECRETS: [&str; 7] = [
    "ntfy_url",
    "webhook_url",
    "webhook_token",
    "telegram_token",
    "telegram_chat",
    CHAT_NAME,
    "smtp",
];
pub const PAIR_SECONDS: f64 = 120.0;
pub const BAD_CODES: i64 = 5;

/// `CHANNEL_SECRETS[channel]`: what each channel keeps.
pub fn channel_secrets(channel: &str) -> &'static [&'static str] {
    match channel {
        "ntfy" => &["ntfy_url"],
        "webhook" => &["webhook_url", "webhook_token"],
        "telegram" => &["telegram_token", "telegram_chat", CHAT_NAME],
        "email" => &["smtp"],
        _ => &[],
    }
}

/// `NEEDED[channel]`: what it must have kept to send; None for a channel that is not one (Python's KeyError).
pub fn needed(channel: &str) -> Option<&'static [&'static str]> {
    match channel {
        "ntfy" => Some(&["ntfy_url"]),
        "webhook" => Some(&["webhook_url"]),
        "telegram" => Some(&["telegram_token", "telegram_chat"]),
        "email" => Some(&["smtp"]),
        _ => None,
    }
}

/// `CODE.match(text)`: `[0-9]{6}\Z`.
pub fn is_code(text: &str) -> bool {
    text.len() == 6 && text.bytes().all(|b| b.is_ascii_digit())
}

/// `NotSaved`: the channel's address or secret is not in Credential Manager.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NotSaved;

/// `read(secrets, name)`: the secret, where it is a non-empty text.
pub fn read(secrets: &Secrets<'_>, name: &str) -> std::result::Result<Option<String>, SecretError> {
    Ok(secrets
        .read(CAPABILITY, &string(name))?
        .filter(|found| !found.is_empty()))
}

/// `saved(secrets, channel)`: whether everything `channel` needs to send is kept; False where it cannot be read.
pub fn saved(secrets: &Secrets<'_>, channel: &str) -> bool {
    let Some(names) = needed(channel) else {
        return false;
    };
    names
        .iter()
        .all(|name| matches!(read(secrets, name), Ok(Some(_))))
}

/// `chat_label(chat)`: a Telegram chat object's name for the card - its title or its @username, control characters
/// taken out, at most MAX_CHAT_NAME characters - or None.
pub fn chat_label(chat: &Value) -> Option<String> {
    let Value::Object(chat) = chat else {
        return None;
    };
    let text = |key: &str| match chat.get(key) {
        Some(Value::Str(found)) => Some(found.clone()),
        _ => None,
    };
    let title = text("title").filter(|title| {
        let points: String = title
            .code_points()
            .map(|point| char::from_u32(point).unwrap_or('\u{FFFD}'))
            .collect();
        !car_machine::pytext::strip(&points).is_empty()
    });
    let found = match title {
        Some(title) => title,
        None => {
            let user = text("username").filter(|user| !user.is_empty())?;
            let mut made = car_machine::json::Str::new("@").as_bytes().to_vec();
            made.extend_from_slice(user.as_bytes());
            car_machine::json::Str::from_surrogatepass(made)?
        }
    };
    let kept: String = found
        .code_points()
        .filter(|point| car_codex::labels::is_printable(*point))
        .filter_map(char::from_u32)
        .collect();
    let cut: String = car_machine::pytext::strip(&kept)
        .chars()
        .take(MAX_CHAT_NAME)
        .collect();
    if cut.is_empty() { None } else { Some(cut) }
}

/// `chat_name(secrets)`: the paired chat's name as kept, or None.
pub fn chat_name(secrets: &Secrets<'_>) -> std::result::Result<Option<String>, SecretError> {
    read(secrets, CHAT_NAME)
}

/// `keep_chat_name(secrets, chat)`: `chat`'s name kept where it has one and it is not the one kept already; whether
/// it was written. Never fatal.
pub fn keep_chat_name(secrets: &Secrets<'_>, chat: &Value) -> bool {
    let Some(label) = chat_label(chat) else {
        return false;
    };
    match chat_name(secrets) {
        Ok(Some(kept)) if kept == label => false,
        Ok(_) => secrets
            .write(CAPABILITY, &string(CHAT_NAME), &Value::from(label))
            .is_ok(),
        Err(_) => false,
    }
}

/// `digest(code)`: the SHA-256 of the code's ASCII, in hex.
pub fn digest(code: &str) -> String {
    car_machine::hash::hex(&car_machine::hash::sha256(code.as_bytes()))
}

/// `begin_pairing(state, code, now)`: the digest of the one-time `code` kept, and when it expires.
pub fn begin_pairing(state: &AdvancedState, code: &Value, now: f64) -> Result<()> {
    let code = match code {
        Value::Str(text) => text.as_str().filter(|text| is_code(text)),
        _ => None,
    };
    let Some(code) = code else {
        return Err(Error::python("ValueError", "code"));
    };
    let made = digest(code);
    state.writing(|connection| {
        sql::exec(
            connection,
            "INSERT INTO remote (channel, paired_at, bad_codes, update_offset, code_digest, code_expires_at) \
             VALUES ('telegram', NULL, 0, NULL, ?, ?) ON CONFLICT(channel) DO UPDATE SET paired_at = NULL, \
             bad_codes = 0, code_digest = excluded.code_digest, code_expires_at = excluded.code_expires_at",
            &[string(&made), float(now + PAIR_SECONDS)],
        )?;
        Ok(())
    })
}

/// `pairing(state)`: the `remote` row of telegram, or None.
pub fn pairing(state: &AdvancedState) -> Result<Option<Row>> {
    state.read(|connection| match connection {
        None => Ok(None),
        Some(connection) => sql::one(
            connection,
            "SELECT * FROM remote WHERE channel = 'telegram'",
            &[],
        ),
    })
}

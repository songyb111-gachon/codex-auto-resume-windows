//! The capability URIs a notice's buttons carry, read as `activate` reads them: car-surface's `notice_uris.parse_*` and
//! `codex_link.parse_chat_uri` (the one port of them, over its `urlsplit` and `parse_qs`). S5.2 read them here with a
//! copy of its own while car-surface was another seat's; Integration 8 hands every reading to car-surface's.

use car_machine::json::Value;
use car_surface::{codex_link, notice_uris};

/// What a URI asks for, in the order `cmd_activate` asks.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Activation {
    Chat(String),
    Open(String),
    PowerStop,
    Cancel { id: String, open_codex: bool },
    Malformed,
}

/// `parse_cancel_uri(uri)`.
pub fn parse_cancel_uri(uri: &str) -> Option<String> {
    notice_uris::parse_cancel_uri(&Value::from(uri))
}

/// `cancel_asks_open_codex(uri)`.
pub fn cancel_asks_open_codex(uri: &str) -> bool {
    notice_uris::cancel_asks_open_codex(&Value::from(uri))
}

/// `parse_open_uri(uri)`.
pub fn parse_open_uri(uri: &str) -> Option<String> {
    notice_uris::parse_open_uri(&Value::from(uri))
}

/// `parse_power_stop_uri(uri)`.
pub fn parse_power_stop_uri(uri: &str) -> Option<String> {
    notice_uris::parse_power_stop_uri(&Value::from(uri))
}

/// `codex_link.parse_chat_uri(uri)`.
pub fn parse_chat_uri(uri: &str) -> Option<String> {
    codex_link::parse_chat_uri(&Value::from(uri))
}

/// `cmd_activate`'s reading, in its order.
pub fn parse(uri: &str) -> Activation {
    if let Some(thread) = parse_chat_uri(uri) {
        return Activation::Chat(thread);
    }
    if let Some(page) = parse_open_uri(uri) {
        return Activation::Open(page);
    }
    if parse_power_stop_uri(uri).is_some() {
        return Activation::PowerStop;
    }
    match parse_cancel_uri(uri) {
        Some(id) => Activation::Cancel {
            open_codex: cancel_asks_open_codex(uri),
            id,
        },
        None => Activation::Malformed,
    }
}

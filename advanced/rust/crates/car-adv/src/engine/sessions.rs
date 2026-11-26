//! `other_sessions`' code (seat S7.2e1; `engine/sessions.py`): a terminal's and VS Code's conversations recovered too
//! (P18), and a conversation another Codex session holds handed to that session (P16, TO_SESSION).

use car_config::Paths;
use car_machine::json::Value;
use car_policy::plug::Alternative;

use crate::capabilities::{Code, Said, Spoke};

pub const CAPABILITY: &str = "other_sessions";
/// `KINDS`: both other kinds of conversation (a frozenset; said in this order).
pub const KINDS: [&str; 2] = ["cli", "ide"];
/// Where core asks P16 for a conversation another Codex session holds.
pub const SESSION: &str = "session";

/// `OtherSessions(paths)`: its hooks at P18 and P16; it holds nothing and reads nothing.
pub struct OtherSessions {
    pub paths: Paths,
}

impl Code for OtherSessions {
    /// P18: both other kinds, watched.
    fn sessions(&mut self) -> Spoke {
        Ok(Said::Set(
            KINDS
                .iter()
                .map(|kind| Value::Str((*kind).into()))
                .collect(),
        ))
    }

    /// P16: TO_SESSION for a conversation another Codex session holds; DEFER for everything else - the watch of an
    /// item queued for opening (`queued_since`) among them.
    fn unloaded(&mut self, record: &Value) -> Spoke {
        let Value::Object(map) = record else {
            return Ok(Said::Defer);
        };
        let holder = map.get("holder").cloned().unwrap_or(Value::Null);
        if !car_machine::pyval::eq(&holder, &Value::Str(SESSION.into()))
            || map.contains_key("queued_since")
        {
            return Ok(Said::Defer);
        }
        Ok(Said::Word(Alternative::ToSession))
    }
}

/// `make(paths)`.
pub fn make(paths: &Paths) -> Option<Box<dyn Code>> {
    Some(Box::new(OtherSessions {
        paths: paths.clone(),
    }))
}

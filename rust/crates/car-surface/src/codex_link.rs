//! `codex_link.py`: the Codex app's own link to one conversation, and opening it; and this product's link to the
//! advanced edition's chat at one conversation (v0.6.19).
//!
//! Only a UUID in its canonical text is ever put in a link, and only exactly such a link is ever read. Opening one is
//! explorer.exe given the link as its one argument, started through car-platform (`CREATE_NO_WINDOW`, no shell).

use std::path::PathBuf;

use car_machine::domain::ids;
use car_machine::json::Value;
use car_machine::pyval::Py;
use car_platform::spawn::Spawn;

use crate::seam::Launch;

/// v0.6.16: the Codex app's own link to one conversation (measured 2026-10-16, Codex app 26.1007).
pub const CODEX_THREAD_LINK: &str = "codex://threads/";
/// v0.6.19: this product's own link to the advanced edition's chat at one conversation.
pub const CHAT_LINK: &str = "codex-auto-resume:chat?thread=";

fn canonical(thread_id: &Value) -> Option<&str> {
    if ids::is_uuid(thread_id) {
        match thread_id {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    } else {
        None
    }
}

/// `codex_thread_uri(thread_id)`: the Codex app's link to one conversation, or None unless `thread_id` is a UUID
/// in its canonical text.
pub fn codex_thread_uri(thread_id: &Value) -> Option<String> {
    canonical(thread_id).map(|id| format!("{CODEX_THREAD_LINK}{id}"))
}

fn after<'a>(uri: &'a Value, prefix: &str) -> Option<&'a str> {
    match uri {
        Value::Str(text) => text.as_str()?.strip_prefix(prefix),
        _ => None,
    }
}

/// `parse_codex_thread_uri(uri)`: the conversation a Codex link names, or None for anything but exactly the link
/// and a canonical UUID.
pub fn parse_codex_thread_uri(uri: &Value) -> Option<String> {
    let id = after(uri, CODEX_THREAD_LINK)?;
    ids::is_uuid(&Value::from(id)).then(|| id.to_owned())
}

/// `chat_uri(thread_id)`: the link that opens the chat at `thread_id`, or None unless it is a canonical UUID.
pub fn chat_uri(thread_id: &Value) -> Option<String> {
    canonical(thread_id).map(|id| format!("{CHAT_LINK}{id}"))
}

/// `parse_chat_uri(uri)`: the conversation a chat link names, or None.
pub fn parse_chat_uri(uri: &Value) -> Option<String> {
    let id = after(uri, CHAT_LINK)?;
    ids::is_uuid(&Value::from(id)).then(|| id.to_owned())
}

/// The explorer.exe `open_in_codex` starts: `%SystemRoot%\explorer.exe` (`C:\Windows` where SystemRoot is unset or
/// empty).
pub fn explorer(system_root: Option<&str>) -> PathBuf {
    let root = system_root
        .filter(|root| !root.is_empty())
        .unwrap_or(r"C:\Windows");
    PathBuf::from(root).join("explorer.exe")
}

/// `open_in_codex(link)`: show one conversation in the Codex app - the link read again here and handed, alone, to
/// explorer.exe. Err("ValueError") for anything but exactly a Codex conversation link; Ok(false) when there is no
/// explorer.exe; an error starting it is the launcher's (`OSError`), as `subprocess.Popen` raises it.
pub fn open_in_codex(link: &Value, system_root: Option<&str>, launch: &dyn Launch) -> Py<bool> {
    let Some(thread_id) = parse_codex_thread_uri(link) else {
        return Err("ValueError");
    };
    let program = explorer(system_root);
    if !launch.is_file(&program) {
        return Ok(false);
    }
    let uri = format!("{CODEX_THREAD_LINK}{thread_id}");
    let spawn = Spawn::new([program.to_string_lossy().into_owned(), uri]);
    launch.start(&spawn)?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    const ID: &str = "0a1b2c3d-0000-7000-8000-000000000001";

    #[test]
    fn links() {
        let id = Value::from(ID);
        let link = codex_thread_uri(&id).unwrap();
        assert_eq!(
            parse_codex_thread_uri(&Value::from(link.as_str())),
            Some(ID.into())
        );
        assert_eq!(
            parse_codex_thread_uri(&Value::from(format!("{link}?x").as_str())),
            None
        );
        let chat = chat_uri(&id).unwrap();
        assert_eq!(parse_chat_uri(&Value::from(chat.as_str())), Some(ID.into()));
        assert_eq!(
            codex_thread_uri(&Value::from(ID.to_uppercase().as_str())),
            None
        );
    }
}

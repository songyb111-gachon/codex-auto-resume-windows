//! `ui/tray/dashboard.py`'s two openers (cut C6), as the host's `open_dashboard` and `open_chat` actions and a card's
//! buttons reach them: the Dashboard of this installation, by its own file beside the watcher, asked first to come
//! forward (`win/handover.py`), else started with `CREATE_NO_WINDOW` like every start of ours.

use std::path::Path;

use car_machine::json::Value;
use car_machine::vocab_gen::domain_public::PAGES;
use car_platform::spawn::{Spawn, SpawnError, SystemStarter};

/// The Dashboard's own dialogs a row of the popup's menu can open it on (`ROW_DIALOGS`).
pub use car_surface::popup::model::ROW_DIALOGS;

/// A refusal of a value that is not one of ours (`ValueError`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ValueError(pub &'static str);

/// Why an open raised: a value that is not one of ours (`ValueError`), or Windows refusing the start (the `OSError`
/// `subprocess.Popen` raises, by its Python class: `FileNotFoundError`, `PermissionError`, ...).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OpenError {
    Value(ValueError),
    Os(&'static str),
}

impl OpenError {
    /// The Python class the reference raises.
    pub fn class(&self) -> &'static str {
        match self {
            OpenError::Value(_) => "ValueError",
            OpenError::Os(class) => class,
        }
    }
}

impl From<ValueError> for OpenError {
    fn from(refused: ValueError) -> Self {
        OpenError::Value(refused)
    }
}

/// The start's error as the reference's `OSError` class.
fn os_error(error: &SpawnError) -> OpenError {
    match error {
        SpawnError::Os(error) => OpenError::Os(car_machine::pyfile::os_error_class(error)),
        SpawnError::Timeout => OpenError::Os("TimeoutExpired"),
    }
}

/// `row_argument(row)`: (dialog, interruption id, thread id) as `<dialog>:<interruption id>:<thread id>`.
///
/// `dialog, interruption_id, thread_id = row` unpacks any three-item iterable a JSON value can be: an array, a text of
/// three characters (each a one-character text, so never a dialog of ours) and an object by its three keys; anything
/// else is "not a row".
pub fn row_argument(row: &Value) -> Result<String, ValueError> {
    let keys: Vec<Value>;
    let parts: &[Value] = match row {
        Value::Array(parts) => parts.as_slice(),
        Value::Str(text) if text.len() == 3 => {
            return Err(ValueError("not a dialog of the window"));
        }
        Value::Object(map) => {
            keys = map.keys().cloned().map(Value::Str).collect();
            keys.as_slice()
        }
        _ => return Err(ValueError("not a row of the window")),
    };
    let [dialog, interruption_id, thread_id] = parts else {
        return Err(ValueError("not a row of the window"));
    };
    let dialog = match dialog {
        Value::Str(text) => text.as_str().filter(|text| ROW_DIALOGS.contains(text)),
        _ => None,
    }
    .ok_or(ValueError("not a dialog of the window"))?;
    if !car_machine::domain::ids::is_interruption_id(interruption_id, false) {
        return Err(ValueError("not a row of the window"));
    }
    if !car_machine::domain::ids::is_uuid(thread_id) {
        return Err(ValueError("not a row of the window"));
    }
    let text = |value: &Value| match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    Ok(format!(
        "{dialog}:{}:{}",
        text(interruption_id),
        text(thread_id)
    ))
}

/// `open_dashboard(home, page, row)`: whether a window took it or was started.
pub fn open_dashboard(
    home: &Path,
    page: Option<&str>,
    row: Option<&Value>,
) -> Result<bool, OpenError> {
    if let Some(page) = page
        && !PAGES.contains(&page)
    {
        return Err(ValueError("not a page of the window").into());
    }
    let mut page = page.map(str::to_owned);
    let mut asked = None;
    if let Some(row) = row {
        if !matches!(page.as_deref(), None | Some("pending")) {
            return Err(ValueError("a row is on Pending").into());
        }
        page = Some("pending".into());
        asked = Some(row_argument(row)?);
    }
    let exe = home.join("CodexAutoResumeSettings.exe");
    if !exe.is_file() {
        return Ok(false);
    }
    let exe_text = exe.to_string_lossy().into_owned();
    if car_platform::handover::hand_over(&exe_text, page.as_deref(), asked.as_deref()) {
        return Ok(true);
    }
    let mut arguments = vec![exe_text];
    if let Some(page) = &page {
        arguments.push(format!("--page={page}"));
    }
    if let Some(asked) = &asked {
        arguments.push(format!("--dialog={asked}"));
    }
    // `subprocess.Popen(arguments, cwd=str(home), close_fds=True, creationflags=CREATE_NO_WINDOW)`: no handle
    // inherited, and what Windows refuses raised as its OSError.
    SystemStarter
        .start_inheriting_nothing(&Spawn::new(arguments).with_cwd(home), cfg!(test))
        .map_err(|error| os_error(&error))?;
    Ok(true)
}

/// `open_chat(home, thread_id)`: the advanced window at its chat with one conversation.
pub fn open_chat(home: &Path, thread_id: &Value) -> Result<bool, OpenError> {
    if !car_machine::domain::ids::is_uuid(thread_id) {
        return Err(ValueError("not a conversation").into());
    }
    let exe = home.join("CodexAutoResumeSettings.exe");
    if !exe.is_file() {
        return Ok(false);
    }
    let thread = match thread_id {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    };
    let arguments = [
        exe.to_string_lossy().into_owned(),
        "--page=advanced".into(),
        "--capability=codex_chat".into(),
        format!("--chat={thread}"),
    ];
    SystemStarter
        .start_inheriting_nothing(&Spawn::new(arguments).with_cwd(home), cfg!(test))
        .map_err(|error| os_error(&error))?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use car_machine::json::{Map, Str};

    const KEY: &str = "abababababababababababababababababababababababababababababababab";
    const THREAD: &str = "12345678-89ab-7cde-8f01-23456789abcd";

    fn keys(names: &[&str]) -> Value {
        let mut map = Map::new();
        for name in names {
            map.insert(Str::new(name), Value::Null);
        }
        Value::Object(map)
    }

    #[test]
    fn a_row_is_any_three_item_value_python_unpacks() {
        let row = Value::Array(vec![
            Value::from("message"),
            Value::from(KEY),
            Value::from(THREAD),
        ]);
        let said = format!("message:{KEY}:{THREAD}");
        assert_eq!(row_argument(&row), Ok(said.clone()));
        // A dict unpacks to its keys, in order.
        assert_eq!(row_argument(&keys(&["message", KEY, THREAD])), Ok(said));
        assert_eq!(
            row_argument(&keys(&["message", KEY])),
            Err(ValueError("not a row of the window"))
        );
        // A text of three characters unpacks to three one-character texts: never a dialog.
        for three in ["abc", "\u{e9}\u{4e2d}\u{1f600}"] {
            assert_eq!(
                row_argument(&Value::from(three)),
                Err(ValueError("not a dialog of the window"))
            );
        }
        for other in [
            Value::from("ab"),
            Value::from("abcd"),
            Value::from(""),
            Value::Null,
            Value::Bool(true),
        ] {
            assert_eq!(
                row_argument(&other),
                Err(ValueError("not a row of the window"))
            );
        }
    }

    #[test]
    fn a_failed_start_is_its_oserror_class() {
        let error = SpawnError::Os(std::io::Error::from_raw_os_error(5));
        assert_eq!(os_error(&error), OpenError::Os("PermissionError"));
        assert_eq!(os_error(&error).class(), "PermissionError");
        assert_eq!(OpenError::from(ValueError("x")).class(), "ValueError");
    }
}

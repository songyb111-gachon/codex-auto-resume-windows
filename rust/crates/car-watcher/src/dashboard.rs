//! `ui/tray/dashboard.py`'s two openers (cut C6), as the host's `open_dashboard` and `open_chat` actions and a card's
//! buttons reach them: the Dashboard of this installation, by its own file beside the watcher, asked first to come
//! forward (`win/handover.py`), else started with `CREATE_NO_WINDOW` like every start of ours.

use std::path::Path;

use car_machine::json::Value;
use car_machine::vocab_gen::domain_public::PAGES;
use car_platform::spawn::{Spawn, SystemStarter};

/// The Dashboard's own dialogs a row of the popup's menu can open it on (`ROW_DIALOGS`).
pub use car_surface::popup::model::ROW_DIALOGS;

/// A refusal of a value that is not one of ours (`ValueError`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ValueError(pub &'static str);

/// `row_argument(row)`: (dialog, interruption id, thread id) as `<dialog>:<interruption id>:<thread id>`.
pub fn row_argument(row: &Value) -> Result<String, ValueError> {
    let Value::Array(parts) = row else {
        return Err(ValueError("not a row of the window"));
    };
    let [dialog, interruption_id, thread_id] = parts.as_slice() else {
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
) -> Result<bool, ValueError> {
    if let Some(page) = page
        && !PAGES.contains(&page)
    {
        return Err(ValueError("not a page of the window"));
    }
    let mut page = page.map(str::to_owned);
    let mut asked = None;
    if let Some(row) = row {
        if !matches!(page.as_deref(), None | Some("pending")) {
            return Err(ValueError("a row is on Pending"));
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
    let _ = SystemStarter.start(&Spawn::new(arguments).with_cwd(home));
    Ok(true)
}

/// `open_chat(home, thread_id)`: the advanced window at its chat with one conversation.
pub fn open_chat(home: &Path, thread_id: &Value) -> Result<bool, ValueError> {
    if !car_machine::domain::ids::is_uuid(thread_id) {
        return Err(ValueError("not a conversation"));
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
    let _ = SystemStarter.start(&Spawn::new(arguments).with_cwd(home));
    Ok(true)
}

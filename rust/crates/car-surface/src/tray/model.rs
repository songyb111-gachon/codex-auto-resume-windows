//! `ui/tray/model.py`: what the icon shows, as data - the snapshot it is updated from, and what the open popup says.
//! Read by the watcher's loop rather than by the icon itself; pure but for the store it is given.

use car_machine::domain::public::eligible_at;
use car_machine::json::Value;
use car_machine::pyval::{self, Py};
use car_machine::vocab_gen::domain_states::WAITING;

use crate::popup::model::PopupModel;
use crate::py::{self, object, str_of};
use crate::seam::TrayStore;

/// `popup_attention(popup)`: whether the open popup says nothing can recover until a person acts - only while it is
/// open (`visible`, the C# host's window's).
pub fn popup_attention(popup: Option<(bool, &PopupModel)>) -> Py<bool> {
    match popup {
        Some((true, model)) => model.attention(),
        _ => Ok(false),
    }
}

/// `row[key]` of a dict: a KeyError where it has none, a TypeError where it is no dict.
fn item(row: &Value, key: &str) -> Py<Value> {
    match row {
        Value::Object(map) => map.get(key).cloned().ok_or("KeyError"),
        _ => Err("TypeError"),
    }
}

/// `snapshot_from(store, now)`: what the icon shows, from our own store only - no Codex read, no content.
pub fn snapshot_from(store: &dyn TrayStore) -> Py<Value> {
    let (mut waiting, mut running, mut held, mut unmatched) = (0i64, 0i64, 0i64, 0i64);
    let mut due: Vec<Value> = Vec::new();
    for row in store.pending()? {
        let state = item(&row, "state")?;
        if pyval::in_set(&state, WAITING)? {
            waiting += 1;
            if !matches!(pyval::get(&row, "hold")?, Value::Null) {
                held += 1;
            } else {
                let error = str_of(py::or(pyval::get(&row, "last_error")?, &Value::from("")));
                if error.split(':').next() == Some("app_server_unmatched") {
                    let thread = item(&row, "thread_id")?;
                    pyval::hashable(&thread)?;
                    let disabled = store.disabled_threads()?;
                    if !disabled.iter().any(|each| pyval::eq(each, &thread)) {
                        unmatched += 1;
                    }
                }
            }
            let at = eligible_at(&row)?;
            if pyval::truthy(&at) {
                due.push(at);
            }
        } else {
            running += 1;
        }
    }
    let enabled = item(&store.settings()?, "enabled")?;
    let next_at = if due.is_empty() {
        Value::Null
    } else {
        let listed: Vec<&Value> = due.iter().collect();
        py::min_of(&listed)?.clone()
    };
    Ok(object([
        ("enabled", enabled),
        ("waiting", Value::from(waiting)),
        ("running", Value::from(running)),
        ("held", Value::from(held)),
        ("unmatched", Value::from(unmatched)),
        ("next_at", next_at),
        ("failures", store.failure_marks()?),
    ]))
}

//! `notice_uris.py`: the capability URIs a notice's buttons carry, and the one reader of each.
//!
//! Windows hands a toast's button back to this product as a `codex-auto-resume:` URI, in a process that starts for it.
//! A URI can only name what it may do: cancel one interruption, open one page from a closed list, stop one batch's
//! power action. Each reader refuses anything else, so a page that merely knows the scheme can at worst open a window.

use car_machine::domain::ids;
use car_machine::json::Value;
use car_machine::pytext;
use car_machine::vocab_gen::domain_public::PAGES;

use crate::py::str_of;
use crate::pyurl::{Split, parse_qs, urlsplit};

pub const SCHEME: &str = "codex-auto-resume";
/// v0.6.18: the flag a cancel URI carries when its notice offered Open Codex.
pub const OPEN_CODEX_FLAG: &str = "c";

/// `cancel_uri(interruption_id)`: the capability URI for one interruption.
pub fn cancel_uri(interruption_id: &Value) -> String {
    format!("{SCHEME}:cancel?i={}", str_of(interruption_id))
}

/// The parts of `str(uri)` and its action (`(path or netloc or "").strip("/").lower()`), or None where the URI is
/// not of this scheme or does not split.
fn action_of(uri: &Value) -> Option<(Split, String)> {
    let parts = urlsplit(&str_of(uri)).ok()?;
    if parts.scheme.to_lowercase() != SCHEME {
        return None;
    }
    let named = if !parts.path.is_empty() {
        parts.path.as_str()
    } else {
        parts.netloc.as_str()
    };
    let action = named.trim_matches('/').to_lowercase();
    Some((parts, action))
}

/// `parse_cancel_uri(uri)`: the interruption id, or None when the URI is not a valid cancel request.
pub fn parse_cancel_uri(uri: &Value) -> Option<String> {
    let (parts, action) = action_of(uri)?;
    if action != "cancel" {
        return None;
    }
    let values = parse_qs(&parts.query, false)
        .swap_remove("i")
        .unwrap_or_default();
    if values.len() != 1 {
        return None;
    }
    ids::read_interruption_id(&values[0])
}

/// `with_open_codex_flag(uri)`: a cancel URI with the Open Codex flag on it; any other URI as it is.
pub fn with_open_codex_flag(uri: &Value) -> Value {
    if parse_cancel_uri(uri).is_none() || cancel_asks_open_codex(uri) {
        return uri.clone();
    }
    Value::from(format!("{}&{OPEN_CODEX_FLAG}=1", str_of(uri)))
}

/// `cancel_asks_open_codex(uri)`: whether a valid cancel URI carries the flag, exactly once and exactly 1.
pub fn cancel_asks_open_codex(uri: &Value) -> bool {
    if parse_cancel_uri(uri).is_none() {
        return false;
    }
    let Ok(parts) = urlsplit(&str_of(uri)) else {
        return false;
    };
    parse_qs(&parts.query, false)
        .get(OPEN_CODEX_FLAG)
        .is_some_and(|values| values.len() == 1 && values[0] == "1")
}

/// `open_uri(page)`: the capability URI that opens one page of the Dashboard.
pub fn open_uri(page: &Value) -> String {
    format!("{SCHEME}:open?page={}", str_of(page))
}

/// `open_uri` of a page named by the product itself.
pub fn open_page(page: &str) -> String {
    format!("{SCHEME}:open?page={page}")
}

/// `parse_open_uri(uri)`: the page, or None when the URI is not a valid open request.
pub fn parse_open_uri(uri: &Value) -> Option<String> {
    let (parts, action) = action_of(uri)?;
    if action != "open" {
        return None;
    }
    let values = parse_qs(&parts.query, false)
        .swap_remove("page")
        .unwrap_or_default();
    if values.len() != 1 {
        return None;
    }
    let page = pytext::strip(&values[0]).to_lowercase();
    PAGES.contains(&page.as_str()).then_some(page)
}

/// `power_stop_uri(nonce)`: the capability URI that stops the power action for one batch (v0.6.12).
pub fn power_stop_uri(nonce: &Value) -> String {
    format!("{SCHEME}:power-stop?n={}", str_of(nonce))
}

/// `parse_power_stop_uri(uri)`: the batch's nonce, or None unless the URI is exactly one `n` of 16 lowercase hex
/// digits and nothing else.
pub fn parse_power_stop_uri(uri: &Value) -> Option<String> {
    let (parts, action) = action_of(uri)?;
    if action != "power-stop" {
        return None;
    }
    let fields = parse_qs(&parts.query, true);
    let values = fields.get("n").cloned().unwrap_or_default();
    if values.len() != 1 || fields.len() != 1 || !fields.contains_key("n") {
        return None;
    }
    let nonce = Value::from(values[0].as_str());
    ids::is_power_nonce(&nonce).then(|| values[0].clone())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readers() {
        let id = "a".repeat(64);
        let uri = Value::from(cancel_uri(&Value::from(id.as_str())));
        assert_eq!(parse_cancel_uri(&uri), Some(id.clone()));
        let flagged = with_open_codex_flag(&uri);
        assert!(cancel_asks_open_codex(&flagged));
        assert_eq!(with_open_codex_flag(&flagged), flagged);
        assert_eq!(
            parse_open_uri(&Value::from(" codex-auto-resume:open?page= History ")),
            Some("history".into())
        );
        assert_eq!(
            parse_open_uri(&Value::from("codex-auto-resume:open?page=x")),
            None
        );
        let nonce = "0123456789abcdef";
        let stop = Value::from(power_stop_uri(&Value::from(nonce)));
        assert_eq!(parse_power_stop_uri(&stop), Some(nonce.into()));
        let extra = Value::from(format!("{}&x=", power_stop_uri(&Value::from(nonce))));
        assert_eq!(parse_power_stop_uri(&extra), None);
    }
}

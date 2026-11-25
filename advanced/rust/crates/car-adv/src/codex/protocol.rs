//! `codex/protocol.py`'s tables and pure functions: which App Server methods each measurement and each capability may
//! call, the methods never called, and the one reply this edition's session gives a request Codex makes of it (seat
//! S7.2c).
//!
//! The one-turn `Session` over `codex app-server --stdio` (`Session`, `submitted`) is not ported here: it is the
//! measurement harness's and the capabilities' channel (S7.2a's runtime, S7.2e1's routes), opened only where a person runs
//! a measurement or core hands a capability a send. The tables are what `autocheck` and every route read.

use std::collections::BTreeSet;

use car_codex::appserver::PROTOCOL_METHODS;
use car_machine::json::{Map, Value};

use crate::vocabulary::Measurement;

/// `MEASUREMENT_METHODS`: the methods each measurement may call beyond `initialize`, in the tag's order.
pub const MEASUREMENT_METHODS: &[(Measurement, &[&str])] = &[
    (
        Measurement::M1,
        &["thread/loaded/list", "thread/queue/list"],
    ),
    (
        Measurement::M2,
        &["thread/loaded/list", "thread/goal/get", "thread/goal/set"],
    ),
    (
        Measurement::M2b,
        &[
            "thread/goal/get",
            "thread/goal/set",
            "thread/queue/add",
            "thread/queue/list",
        ],
    ),
    (Measurement::M3, &["thread/queue/add", "thread/queue/list"]),
    (
        Measurement::M4,
        &[
            "hooks/list",
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (
        Measurement::M5,
        &["thread/loaded/list", "thread/queue/list"],
    ),
    (
        Measurement::M6,
        &[
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (Measurement::M7, &["thread/queue/add", "thread/queue/list"]),
    (Measurement::Mh, &["thread/loaded/list"]),
    (Measurement::Ma, &["account/read"]),
    (Measurement::Mw, &[]),
    (Measurement::Mp1, &["mcpServerStatus/list"]),
    (Measurement::Mp2, &[]),
    (Measurement::Mp3, &[]),
    (Measurement::Mu, &["account/rateLimits/read"]),
    (
        Measurement::Mn,
        &[
            "account/rateLimits/read",
            "account/rateLimitResetCredit/consume",
        ],
    ),
    (
        Measurement::Mr,
        &[
            "account/rateLimits/read",
            "account/rateLimitResetCredit/consume",
        ],
    ),
    (Measurement::Mq, &["thread/loaded/list"]),
    (Measurement::Me, &[]),
    (Measurement::Ms, &[]),
    (Measurement::Mk, &[]),
    (Measurement::Mt, &["thread/loaded/list"]),
    (Measurement::Mipc, &[]),
    (Measurement::Maws, &[]),
    (Measurement::Mcloud, &[]),
    (
        Measurement::M6b,
        &[
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (Measurement::Mo, &[]),
    (
        Measurement::Mx,
        &[
            "thread/resume",
            "thread/compact/start",
            "thread/unsubscribe",
        ],
    ),
    (Measurement::Mxa, &[]),
    (
        Measurement::Mf,
        &[
            "thread/resume",
            "model/list",
            "turn/start",
            "turn/interrupt",
            "thread/settings/update",
            "thread/unsubscribe",
        ],
    ),
    (
        Measurement::M3b,
        &[
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (Measurement::Mb, &["config/read", "config/value/write"]),
    (Measurement::Mc1, &["thread/queue/add", "thread/queue/list"]),
    (Measurement::Mc2, &[]),
    (Measurement::Mqo, &["thread/queue/add", "thread/queue/list"]),
    (Measurement::Mqp, &["thread/queue/add", "thread/queue/list"]),
    (
        Measurement::Mqg,
        &[
            "thread/goal/get",
            "thread/goal/set",
            "thread/queue/add",
            "thread/queue/list",
        ],
    ),
    (Measurement::Mtok, &[]),
    (Measurement::Mopen, &[]),
    (Measurement::Mal, &["account/read"]),
    (Measurement::Malr, &["account/read"]),
    (Measurement::Mwake, &[]),
    (Measurement::Mhk, &[]),
    (Measurement::M4b, &["hooks/list"]),
    (Measurement::Manchor, &["account/rateLimits/read"]),
    (
        Measurement::Mimg,
        &["thread/queue/add", "thread/queue/list"],
    ),
    (Measurement::Msteer, &["turn/steer"]),
    (Measurement::Msteer2, &[]),
    (Measurement::Mgave, &[]),
    (
        Measurement::Mb2,
        &[
            "config/read",
            "account/read",
            "thread/list",
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
            "thread/read",
        ],
    ),
    (
        Measurement::Mprofile,
        &["account/read", "account/rateLimits/read"],
    ),
    (
        Measurement::Mswap,
        &["account/read", "account/rateLimits/read"],
    ),
    (Measurement::Mauto, &[]),
];

/// `CAPABILITY_METHODS`: the methods a capability's own route may call beyond `initialize`.
pub const CAPABILITY_METHODS: &[(&str, &[&str])] = &[
    ("marker_free_continuation", &["thread/queue/add"]),
    (
        "goal_continuation",
        &["thread/goal/set", "thread/queue/add"],
    ),
    (
        "reset_credit",
        &[
            "account/rateLimits/read",
            "account/rateLimitResetCredit/consume",
        ],
    ),
    ("reset_message", &["account/rateLimits/read"]),
    (
        "headless_run",
        &[
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (
        "compact_continue",
        &[
            "thread/resume",
            "thread/compact/start",
            "turn/start",
            "turn/interrupt",
            "thread/unsubscribe",
        ],
    ),
    (
        "model_fallback",
        &[
            "thread/resume",
            "model/list",
            "turn/start",
            "turn/interrupt",
            "thread/settings/update",
            "thread/unsubscribe",
        ],
    ),
    ("codex_chat", &["thread/queue/add"]),
    ("prompt_queue", &["thread/queue/add"]),
    ("usage_meter", &["account/rateLimits/read"]),
    (
        "window_anchor",
        &["account/rateLimits/read", "account/read"],
    ),
    ("account_switch", &["account/read"]),
    ("codex_retry_settings", &["config/read", "account/read"]),
    (
        "account_auto_switch",
        &["account/read", "account/rateLimits/read"],
    ),
];

/// `FORBIDDEN_METHODS`: never asked, whatever an allow-list says.
pub const FORBIDDEN_METHODS: &[&str] = &[
    "account/login/start",
    "account/login",
    "account/logout",
    "account/chatgptAuthTokens/refresh",
    "chatgptAuthTokens/refresh",
    "attestation/generate",
    "item/tool/call",
];

/// `_REJECTION`.
pub const REJECTION: &str = "declined by codex-auto-resume";

/// `DECLINE_ANSWERS`' methods, in the tag's order: the requests Codex may make of a client that a session answers with
/// the schema's own refusal (`decline_answer`).
pub const DECLINED_REQUESTS: [&str; 7] = [
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "execCommandApproval",
    "applyPatchApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
];

/// `ACCEPTING_WORDS`: every word the schema's response types grant something with.
pub const ACCEPTING_WORDS: &[&str] = &[
    "accept",
    "acceptForSession",
    "acceptWithExecpolicyAmendment",
    "applyNetworkPolicyAmendment",
    "approved",
    "approved_for_session",
    "approved_execpolicy_amendment",
    "approved_mcp_policy_amendment",
    "network_policy_amendment",
    "allow",
    "session",
];

fn object<const N: usize>(pairs: [(&str, Value); N]) -> Value {
    Value::Object(
        pairs
            .into_iter()
            .map(|(key, value)| (key.into(), value))
            .collect(),
    )
}

/// `DECLINE_ANSWERS[method]`: the refusal Codex's own schema gives a request, or none for a method not listed.
pub fn decline_answer(method: &str) -> Option<Value> {
    let denied = || {
        object([(
            "decision",
            object([("denied", object([("rejection", Value::from(REJECTION))]))]),
        )])
    };
    Some(match method {
        "item/commandExecution/requestApproval" | "item/fileChange/requestApproval" => {
            object([("decision", Value::from("decline"))])
        }
        "item/permissions/requestApproval" => object([
            ("permissions", Value::Object(Map::new())),
            ("scope", Value::from("turn")),
        ]),
        "execCommandApproval" | "applyPatchApproval" => denied(),
        "item/tool/requestUserInput" => object([("answers", Value::Object(Map::new()))]),
        "mcpServer/elicitation/request" => {
            object([("action", Value::from("decline")), ("content", Value::Null)])
        }
        _ => return None,
    })
}

/// `_words(value)`: every key and every string inside `value`.
fn words(value: &Value, out: &mut Vec<String>) {
    match value {
        Value::Object(map) => {
            for (key, item) in map {
                out.push(String::from_utf8_lossy(key.as_bytes()).into_owned());
                words(item, out);
            }
        }
        Value::Array(items) => items.iter().for_each(|item| words(item, out)),
        Value::Str(text) => out.push(String::from_utf8_lossy(text.as_bytes()).into_owned()),
        _ => {}
    }
}

/// `_grants_nothing(refusal)`.
pub fn grants_nothing(refusal: &Value) -> bool {
    let Value::Object(map) = refusal else {
        return false;
    };
    let mut found = Vec::new();
    words(refusal, &mut found);
    if found
        .iter()
        .any(|word| ACCEPTING_WORDS.contains(&word.as_str()))
    {
        return false;
    }
    let empty = |key: &str| {
        map.get(key)
            .is_none_or(|value| matches!(value, Value::Object(inner) if inner.is_empty()))
    };
    empty("permissions")
        && empty("answers")
        && map
            .get("content")
            .is_none_or(|value| matches!(value, Value::Null))
        && map
            .get("scope")
            .is_none_or(|value| matches!(value, Value::Str(word) if word.as_bytes() == b"turn"))
}

/// `_NOT_ANSWERED`.
fn not_answered() -> Value {
    object([
        ("code", Value::from(-32601)),
        ("message", Value::from(REJECTION)),
    ])
}

/// `reply_to(request)`: the schema's own refusal for an approval, a permission, an input or an elicitation request, and
/// an error for anything else. Only the method's name chooses between them.
pub fn reply_to(request: &Value) -> Value {
    let (ident, method) = match request {
        Value::Object(map) => (
            map.get("id").cloned().unwrap_or(Value::Null),
            map.get("method"),
        ),
        _ => (Value::Null, None),
    };
    if let Some(Value::Str(method)) = method
        && let Some(method) = method.as_str()
        && !FORBIDDEN_METHODS.contains(&method)
        && let Some(refusal) = decline_answer(method)
        && grants_nothing(&refusal)
    {
        return object([("id", ident), ("result", refusal)]);
    }
    object([("id", ident), ("error", not_answered())])
}

/// `MEASURED_METHODS`: every method some measurement declared.
pub fn measured_methods() -> BTreeSet<&'static str> {
    MEASUREMENT_METHODS
        .iter()
        .flat_map(|(_, methods)| methods.iter().copied())
        .collect()
}

/// `ADVANCED_METHODS`: every method this edition may ever ask beyond core's three.
pub fn advanced_methods() -> BTreeSet<&'static str> {
    let mut found = measured_methods();
    for method in PROTOCOL_METHODS {
        found.remove(method);
    }
    found
}

/// `methods_for(measurement)`: the methods `measurement` may call, `initialize` always among them and a forbidden method
/// never.
pub fn methods_for(measurement: Measurement) -> BTreeSet<&'static str> {
    let mut allowed: BTreeSet<&'static str> = MEASUREMENT_METHODS
        .iter()
        .find(|(each, _)| *each == measurement)
        .map(|(_, methods)| methods.iter().copied().collect())
        .unwrap_or_default();
    allowed.retain(|method| !FORBIDDEN_METHODS.contains(method));
    allowed.insert("initialize");
    allowed.insert("initialized");
    allowed
}

/// `methods_for_capability(capability)`: the capability's own row, of that only what some measurement declared,
/// `initialize` always among them and a forbidden method never.
pub fn methods_for_capability(capability: &str) -> BTreeSet<&'static str> {
    let measured = measured_methods();
    let mut allowed: BTreeSet<&'static str> = CAPABILITY_METHODS
        .iter()
        .find(|(each, _)| *each == capability)
        .map(|(_, methods)| {
            methods
                .iter()
                .copied()
                .filter(|method| measured.contains(method) && !FORBIDDEN_METHODS.contains(method))
                .collect()
        })
        .unwrap_or_default();
    allowed.insert("initialize");
    allowed.insert("initialized");
    allowed
}

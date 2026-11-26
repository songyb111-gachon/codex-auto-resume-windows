//! Seat S7.4: `measure.py`'s MP1-MP3 (the side panel) and MU, MN, MR (the usage read and the reset credit), a child
//! of [`crate::measure`] (declared there with `#[path]`, so no `mod.rs` or `lib.rs` changes).

use super::{
    Context, Found, MeasureSession, Raised, Res, blocked, get, is_dict, is_str_eq, key, object,
    observed, text,
};
use car_machine::json::{Map, Value};
use car_machine::pyval;

use crate::codex::credits;
use crate::vocabulary::{SpendOutcome, Verdict};

// ------------------------------------------------------------------------------------------------ MP1-MP3
pub const MP1_SERVER: &str = "codex-auto-resume";
pub const MP1_PAGE: i64 = 10;
pub const MP1_PAGES: usize = 10;

/// `_mcp_servers(session, params, pages=pages)`.
fn mcp_servers(session: &mut dyn MeasureSession, params: &Map, pages: usize) -> Res<Vec<Value>> {
    let mut servers = Vec::new();
    let mut cursor: Option<Value> = None;
    for _ in 0..pages {
        let mut asked = params.clone();
        if let Some(found) = &cursor {
            asked.insert(key("cursor"), found.clone());
        }
        let answer = session.call("mcpServerStatus/list", Some(Value::Object(asked)))?;
        if let Some(Value::Array(data)) = get(&answer, "data") {
            servers.extend(data.iter().filter(|each| is_dict(each)).cloned());
        }
        cursor = get(&answer, "nextCursor").cloned();
        if !matches!(&cursor, Some(Value::Str(found)) if !found.is_empty()) {
            break;
        }
    }
    Ok(servers)
}

/// `_settings_tool(servers)`.
fn settings_tool(servers: &[Value]) -> Option<Value> {
    let mut found = Vec::new();
    for server in servers {
        let tools: Vec<Value> = match get(server, "tools") {
            Some(Value::Object(map)) => map.values().cloned().collect(),
            Some(Value::Array(items)) => items.clone(),
            _ => vec![],
        };
        found.extend(
            tools
                .into_iter()
                .filter(|tool| is_dict(tool) && is_str_eq(get(tool, "name"), "open_settings")),
        );
    }
    for tool in &found {
        let template = get(tool, "_meta")
            .filter(|each| is_dict(each))
            .and_then(|meta| get(meta, "openai/outputTemplate"));
        if is_str_eq(template, car_control::mcp::tools::SETTINGS_UI) {
            return Some(tool.clone());
        }
    }
    found.into_iter().next()
}

pub(super) fn mp1(ctx: &mut Context<'_>) -> Res<Found> {
    let (servers, tool, named) = ctx.with_session(|_, session| {
        let mut first = Map::new();
        first.insert(key("serverName"), text(MP1_SERVER));
        first.insert(key("detail"), text("full"));
        let mut servers = match mcp_servers(session, &first, 1) {
            Ok(found) => found,
            Err(Raised::Adapter {
                method: Some(_), ..
            }) => vec![],
            Err(raised) => return Err(raised),
        };
        let mut tool = settings_tool(&servers);
        let named = tool.is_some();
        if !named {
            let mut wide = Map::new();
            wide.insert(key("detail"), text("toolsAndAuthOnly"));
            wide.insert(key("limit"), Value::from(MP1_PAGE));
            servers = mcp_servers(session, &wide, MP1_PAGES)?;
            tool = settings_tool(&servers);
        }
        Ok((servers, tool, named))
    })?;
    let empty = Value::Object(Map::new());
    let meta = tool
        .as_ref()
        .and_then(|found| get(found, "_meta"))
        .filter(|each| is_dict(each))
        .unwrap_or(&empty);
    let ui = get(meta, "openai/ui")
        .filter(|each| is_dict(each))
        .unwrap_or(&empty);
    let entrypoints = match get(ui, "entrypoints") {
        Some(Value::Array(items)) => items.clone(),
        _ => vec![],
    };
    let thread = object(vec![("type", text("thread"))]);
    let template = is_str_eq(
        get(meta, "openai/outputTemplate"),
        car_control::mcp::tools::SETTINGS_UI,
    );
    let entry = entrypoints.iter().any(|each| pyval::eq(each, &thread));
    let listed = tool.is_some();
    let seen = observed(vec![
        ("servers", Value::from(servers.len() as i64)),
        ("named_lookup", Value::Bool(named)),
        ("server_listed", Value::Bool(listed)),
        ("template_kept", Value::Bool(template)),
        ("entrypoint_kept", Value::Bool(entry)),
    ]);
    if !listed {
        return blocked(
            "Codex lists no server with the settings panel's tool: is the plugin installed and enabled in this Codex home? Then run mp1 again",
            seen,
        );
    }
    if template && !entry {
        return Ok((
            Verdict::Fail,
            seen,
            Some(
                "the engine keeps the panel's template and drops its side-panel entrypoint".into(),
            ),
        ));
    }
    if !template {
        return blocked(
            "the listing carries no template for the panel's tool, so the harness cannot tell whether the engine keeps the entrypoint; confirm in the app as below, then set the verdict",
            seen,
        );
    }
    blocked(
        "open a throwaway conversation's right side panel, New tab, More tools...: confirm Open Auto Resume settings is under Plugins and MCPs and opens the panel with the state the Dashboard shows, then set the verdict",
        seen,
    )
}

pub(super) fn mp2(_ctx: &mut Context<'_>) -> Res<Found> {
    blocked(
        "in a throwaway conversation ask Codex to open auto resume settings and press Open beside the chat: confirm a right side panel tab shows the panel, scrollable to Save, with the same state, and that closing the tab puts it back in the conversation with the button; then set the verdict",
        observed(vec![("session_opened", Value::Bool(false))]),
    )
}

pub(super) fn mp3(_ctx: &mut Context<'_>) -> Res<Found> {
    blocked(
        "in that side panel tab press Preview, click away for 15 seconds and back (the panel redraws), set Theme to Dark and Save, then back and Save: confirm each works and no new item appears in the conversation, note whether an approval prompt appeared, then set the verdict",
        observed(vec![("session_opened", Value::Bool(false))]),
    )
}

// ------------------------------------------------------------------------------------------------ MU, MN, MR
pub const MU_READS: usize = 3;
pub const MU_TOLERANCE: f64 = 600.0;
pub const FIVE_HOURS: i64 = 300;
pub const WEEK: i64 = 10080;

fn py(class: &'static str) -> Raised {
    Raised::Other(class.into())
}

/// `window[name]`: a KeyError where it is missing, a TypeError where the window is no mapping.
fn item<'a>(window: &'a Value, name: &str) -> Res<&'a Value> {
    match window {
        Value::Object(map) => map.get(&key(name)).ok_or_else(|| py("KeyError")),
        _ => Err(py("TypeError")),
    }
}

/// `for window in windows or ()`: a falsy value iterates nothing; a list its items; anything else raises TypeError.
fn windows_of(windows: &Value) -> Res<Vec<Value>> {
    match windows {
        Value::Array(items) => Ok(items.clone()),
        other if !pyval::truthy(other) => Ok(vec![]),
        _ => Err(py("TypeError")),
    }
}

/// `_read(session, params)`: (reply, parsed).
fn read_usage(session: &mut dyn MeasureSession, params: Value) -> Res<(Value, Value)> {
    let reply = session.call(credits::READ, Some(params))?;
    let parsed = credits::parse(&reply).map_err(py)?;
    Ok((reply, parsed))
}

fn field(parsed: &Value, name: &str) -> Value {
    get(parsed, name).cloned().unwrap_or(Value::Null)
}

fn same_key(a: &(Value, Value), b: &(Value, Value)) -> bool {
    pyval::eq(&a.0, &b.0) && pyval::eq(&a.1, &b.1)
}

type Keyed = Vec<((Value, Value), Value)>;

/// `_running(windows)`: ((bucket, minutes), reset time) of each running window, in order; a later window with an
/// equal key replaces the earlier one's value in place, as a dict does.
fn running(windows: &Value) -> Res<Keyed> {
    let mut found: Keyed = Vec::new();
    for window in windows_of(windows)? {
        let used = item(&window, "used_percent")?;
        if !pyval::greater(used, &Value::from(0)).map_err(py)? {
            continue;
        }
        if *item(&window, "reset_at")? == Value::Null {
            continue;
        }
        let bucket = item(&window, "bucket")?.clone();
        let minutes = item(&window, "window_minutes")?.clone();
        let reset = item(&window, "reset_at")?.clone();
        let pair = (bucket, minutes);
        match found.iter_mut().find(|(seen, _)| same_key(seen, &pair)) {
            Some(slot) => slot.1 = reset,
            None => found.push((pair, reset)),
        }
    }
    Ok(found)
}

pub(super) fn mu(ctx: &mut Context<'_>) -> Res<Found> {
    let (detailed, light, first, seen) = ctx.with_session(|ctx, session| {
        let (detailed, first) = read_usage(session, credits::detailed())?;
        let (light, second) = read_usage(session, credits::light())?;
        let mut seen = vec![first.clone(), second];
        for _ in 0..MU_READS - 1 {
            let spacing = ctx.timing.mu_spacing;
            ctx.world.sleep(spacing);
            seen.push(read_usage(session, credits::light())?.1);
        }
        Ok((detailed, light, first, seen))
    })?;
    let windows = field(&first, "windows");
    let running_now = running(&windows)?;
    let mut drift = 0.0f64;
    for (family, reset_at) in &running_now {
        for reading in &seen[1..] {
            let later = running(&field(reading, "windows"))?;
            if let Some((_, later)) = later.iter().find(|(seen, _)| same_key(seen, family)) {
                let moved = pyval::minus(later, reset_at).map_err(py)?.abs();
                if moved > drift {
                    drift = moved;
                }
            }
        }
    }
    let windows_read = windows != Value::Null;
    let count_read = field(&first, "credits") != Value::Null;
    let full_read = credits::details_listed(&detailed);
    let left_out = !credits::details_listed(&light) && field(&seen[1], "credits") != Value::Null;
    let seen_map = observed(vec![
        ("windows_read", Value::Bool(windows_read)),
        ("count_read", Value::Bool(count_read)),
        ("details_with_full_read", Value::Bool(full_read)),
        ("details_left_out", Value::Bool(left_out)),
        ("running_windows", Value::from(running_now.len() as i64)),
        ("max_drift_seconds", Value::from(drift.trunc() as i64)),
    ]);
    if !(windows_read && count_read && full_read && left_out) {
        return Ok((
            Verdict::Fail,
            seen_map,
            Some("the usage read does not carry the reset credits as the schema says".into()),
        ));
    }
    if running_now.is_empty() {
        return blocked(
            "use Codex until a 5-hour window is running, then run mu again",
            seen_map,
        );
    }
    if drift > MU_TOLERANCE {
        return Ok((
            Verdict::Fail,
            seen_map,
            Some("a running window's reset time moved between reads".into()),
        ));
    }
    blocked(
        "use no Codex from ten minutes before the 5-hour reset /usage shows until after it, then send one short message in a throwaway conversation: confirm /usage shows the 5-hour window reset about five hours after that message, then set the verdict",
        seen_map,
    )
}

fn consume(session: &mut dyn MeasureSession, id: &str) -> Res<SpendOutcome> {
    let reply = session.call(
        credits::CONSUME,
        Some(object(vec![("idempotencyKey", text(id))])),
    )?;
    Ok(credits::outcome(&reply))
}

pub(super) fn mn(ctx: &mut Context<'_>) -> Res<Found> {
    ctx.with_session(|ctx, session| {
        let before = read_usage(session, credits::detailed())?.1;
        let count = field(&before, "credits");
        if count == Value::Null {
            return Ok((
                Verdict::Fail,
                observed(vec![("count_read", Value::Bool(false))]),
                Some("the usage read carries no count of reset credits".into()),
            ));
        }
        if !pyval::eq(&count, &Value::from(0)) {
            return blocked(
                "this account has reset credits: measure mr at a limit instead",
                observed(vec![
                    ("count_read", Value::Bool(true)),
                    ("has_credits", Value::Bool(true)),
                ]),
            );
        }
        let id = ctx.world.uuid4();
        let first = consume(session, &id)?;
        let after = read_usage(session, credits::detailed())?.1;
        let second = consume(session, &id)?;
        let unchanged = pyval::eq(&field(&after, "credits"), &Value::from(0));
        let seen = observed(vec![
            ("count_read", Value::Bool(true)),
            ("has_credits", Value::Bool(false)),
            ("first_outcome", text(first.as_str())),
            ("second_outcome", text(second.as_str())),
            ("count_unchanged", Value::Bool(unchanged)),
        ]);
        let refused = |found: SpendOutcome| {
            matches!(found, SpendOutcome::NoCredit | SpendOutcome::NothingToReset)
        };
        if refused(first) && refused(second) && unchanged {
            return Ok((Verdict::Pass, seen, None));
        }
        Ok((
            Verdict::Fail,
            seen,
            Some("a consume with no credit did not refuse, or the count moved".into()),
        ))
    })
}

/// `_changed(before, after)`: (window minutes, whether it changed), in order.
fn changed(before: &Value, after: &Value) -> Res<Vec<(Value, bool)>> {
    let mut old: Keyed = Vec::new();
    for window in windows_of(before)? {
        let pair = (
            item(&window, "bucket")?.clone(),
            item(&window, "window_minutes")?.clone(),
        );
        match old.iter_mut().find(|(seen, _)| same_key(seen, &pair)) {
            Some(slot) => slot.1 = window.clone(),
            None => old.push((pair, window.clone())),
        }
    }
    let hundred = Value::from(100);
    let mut found: Vec<(Value, bool)> = Vec::new();
    for window in windows_of(after)? {
        let pair = (
            item(&window, "bucket")?.clone(),
            item(&window, "window_minutes")?.clone(),
        );
        let Some((_, earlier)) = old.iter().find(|(seen, _)| same_key(seen, &pair)) else {
            continue;
        };
        let was_full =
            pyval::less_or_equal(&hundred, item(earlier, "used_percent")?).map_err(py)?;
        let moved = (was_full
            && pyval::greater(&hundred, item(&window, "used_percent")?).map_err(py)?)
            || !pyval::eq(item(earlier, "reset_at")?, item(&window, "reset_at")?);
        let minutes = item(&window, "window_minutes")?.clone();
        match found.iter_mut().find(|(seen, _)| pyval::eq(seen, &minutes)) {
            Some(slot) => slot.1 = slot.1 || moved,
            None => found.push((minutes, moved)),
        }
    }
    Ok(found)
}

enum Spent {
    NoLimit,
    NoCredit,
    Done(Box<(Value, SpendOutcome, Value, SpendOutcome, Value)>),
}

pub(super) fn mr(ctx: &mut Context<'_>) -> Res<Found> {
    if !ctx.may_spend {
        return blocked(
            "mr spends one real reset credit: run it again with may_spend",
            observed(vec![("may_spend", Value::Bool(false))]),
        );
    }
    let spent = ctx.with_session(|ctx, session| {
        let before = read_usage(session, credits::detailed())?.1;
        let listed = match field(&before, "windows") {
            Value::Array(items) => items,
            _ => return Err(py("TypeError")),
        };
        if credits::full(&listed).map_err(py)?.is_empty() {
            return Ok(Spent::NoLimit);
        }
        if !pyval::truthy(&field(&before, "credits")) {
            return Ok(Spent::NoCredit);
        }
        let id = ctx.world.uuid4();
        let first = consume(session, &id)?;
        let after = read_usage(session, credits::detailed())?.1;
        let second = consume(session, &id)?;
        let last = read_usage(session, credits::detailed())?.1;
        Ok(Spent::Done(Box::new((before, first, after, second, last))))
    })?;
    let (before, first, after, second, last) = match spent {
        Spent::NoLimit => {
            return blocked(
                "no usage window is full now: run mr when Codex says a limit is reached",
                observed(vec![
                    ("may_spend", Value::Bool(true)),
                    ("limit_reached", Value::Bool(false)),
                ]),
            );
        }
        Spent::NoCredit => {
            return blocked(
                "no reset credit is there to spend: run mr when /usage shows one",
                observed(vec![
                    ("may_spend", Value::Bool(true)),
                    ("limit_reached", Value::Bool(true)),
                    ("has_credits", Value::Bool(false)),
                ]),
            );
        }
        Spent::Done(found) => *found,
    };
    let moved = changed(&field(&before, "windows"), &field(&after, "windows"))?;
    let changed_at = |minutes: i64| {
        moved
            .iter()
            .find(|(seen, _)| pyval::eq(seen, &Value::from(minutes)))
            .is_some_and(|(_, on)| *on)
    };
    let after_count = field(&after, "credits");
    // `after["credits"] == before["credits"] - 1`: the count is an int (codex/credits' `_count`) or None.
    let expected = pyval::minus(&field(&before, "credits"), &Value::from(1)).map_err(py)?;
    let down_by_one = matches!(&after_count, Value::Int(found) if found.as_i64().is_some_and(|n| n as f64 == expected));
    let unchanged = pyval::eq(&field(&last, "credits"), &after_count);
    let seen = observed(vec![
        ("may_spend", Value::Bool(true)),
        ("limit_reached", Value::Bool(true)),
        ("has_credits", Value::Bool(true)),
        ("first_outcome", text(first.as_str())),
        ("count_down_by_one", Value::Bool(down_by_one)),
        ("five_hour_changed", Value::Bool(changed_at(FIVE_HOURS))),
        ("weekly_changed", Value::Bool(changed_at(WEEK))),
        (
            "ordinary_usage_allowed",
            Value::Bool(matches!(
                field(&after, "ordinary_usage_allowed"),
                Value::Bool(true)
            )),
        ),
        ("second_outcome", text(second.as_str())),
        ("count_unchanged_on_retry", Value::Bool(unchanged)),
    ]);
    if !(first == SpendOutcome::Reset
        && down_by_one
        && second == SpendOutcome::AlreadyRedeemed
        && unchanged)
    {
        return Ok((
            Verdict::Fail,
            seen,
            Some("the consume did not reset, spent other than one credit, or spent again".into()),
        ));
    }
    blocked(
        "send a message in Codex and confirm it runs - the limit lifted -, then set the verdict",
        seen,
    )
}

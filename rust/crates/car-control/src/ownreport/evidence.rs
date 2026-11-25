//! `ownreport/evidence.py`: what a compatibility report says of records already read - pure, and counted as
//! codex-compat-reporter 1.5.0 counts it, rule for rule and in its order.
//!
//! Python's `re` reads `\d` and `\s` as Unicode classes in a `str` pattern; the matchers here are written out by
//! hand over code points for that reason (car-machine's `decimal_value`, `is_space`), not with an ASCII regex.

use car_machine::compat::loads;
use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::{decimal_value, is_space, py_str, strip};
use car_machine::pyval;
use car_machine::vocab_gen::compat_model::SEND_GATE;
use car_machine::vocab_gen::domain_reason_vocabulary::ReasonCode;
use car_machine::vocab_gen::domain_states::OUTCOMES as MACHINE_OUTCOMES;
use car_machine::vocab_gen::domain_vocabulary::{FailureCategory, RecordState, TurnStatus};

/// `MAX_RECORDS`: the receiving side's limit.
pub const MAX_RECORDS: usize = 500;
/// `OTHER`: a word the report may not carry.
pub const OTHER: &str = "other";
/// `compat.VERIFIED`, `compat.CHECKED`.
pub const VERIFIED: &str = "VERIFIED";
pub const CHECKED: &str = "CHECKED";
/// `gates.PASS`, `gates.PLUGGED`, `gates.HELD`, `GateName.CONSENT`.
const PASS: &str = "PASS";
const PLUG_WORDS: &[&str] = &["plugged", "held"];
const CONSENT: &str = "consent";
/// `ENGINE_LOG_BEFORE_0_6_5`.
pub const ENGINE_LOG_BEFORE_0_6_5: &str = "accepted because `codex queue` still offers";
/// `runtime.app.ENGINE_LOG_WORDS` without "incompatible", and `ENGINE_LOG_CHECKS_ONLY` (crate-map cut C5: they move
/// to car-config with the watcher; written out here until then, and held to the tag by the own report's diffs).
const ENGINE_LOG_PASSES: &[&str] = &[
    "is verified: its local checks pass, and the registry data in force verifies this build",
    "is compatible: its local checks pass (`codex queue` still offers --thread/--message), and the registry data in \
     force does not verify this build",
    "is checked: its local checks pass, and the registry data in force records the maintainer's checks passing on \
     this build; no real recovery has verified it yet",
    "passes its local checks (`codex queue` still offers --thread/--message)",
    ENGINE_LOG_BEFORE_0_6_5,
];
/// `LOCAL_PASS_REASONS`.
const LOCAL_PASS_REASONS: &[&str] = &[
    "local_checks_passed",
    "registry_verified",
    "registry_checked",
];

/// `Unplaced`, in its order.
pub const UNPLACED: &[&str] = &[
    "no_engine_line_before",
    "engine_changed_during",
    "next_line_other_version",
    "engine_changed_after",
];

/// `EXERCISED`'s names in its order, and `REPORTABLE` (sorted).
pub const EXERCISED: &[&str] = &[
    "usage_limit_detection",
    "usage_reset_hint",
    "engine_present",
    "projection_freshness",
    "loaded_state_detection",
    "usage_probe",
    "thread_eligibility",
    "exact_thread_recovery",
    "recovery_turn_tracking",
    "outcome_observation",
];

pub fn reportable() -> Vec<&'static str> {
    let mut names = EXERCISED.to_vec();
    names.sort_unstable();
    names
}

/// `PROGRESS`.
pub const PROGRESS: &[&str] = &[
    "agentMessage",
    "commandExecution",
    "fileChange",
    "mcpToolCall",
];

pub fn categories() -> Vec<&'static str> {
    FailureCategory::ALL
        .iter()
        .map(|each| each.as_str())
        .collect()
}
pub fn states() -> Vec<&'static str> {
    RecordState::ALL.iter().map(|each| each.as_str()).collect()
}
pub fn reasons() -> Vec<&'static str> {
    ReasonCode::ALL.iter().map(|each| each.as_str()).collect()
}
pub fn turn_statuses() -> Vec<&'static str> {
    TurnStatus::ALL.iter().map(|each| each.as_str()).collect()
}
/// `OUTCOMES`: an outcome the product observed.
fn outcomes() -> Vec<&'static str> {
    MACHINE_OUTCOMES
        .iter()
        .copied()
        .filter(|word| *word != "outcome_unverified")
        .collect()
}

/// A record as reading.py hands it: the state's 17 columns.
pub type Row = Map;

fn col<'a>(row: &'a Row, name: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    row.get(name).unwrap_or(&NULL)
}

// ------------------------------------------------------------------------------ small readers
/// `moment(value)`: a stored time as a number, or None when it is not one.
pub fn moment(value: &Value) -> Option<f64> {
    let x = match value {
        Value::Int(int) => car_store::value::int_as_f64(int),
        Value::Float(x) => *x,
        _ => return None,
    };
    (x.is_finite() && x > 0.0).then_some(x)
}

/// `iso(when)`: `datetime.fromtimestamp(when, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`. The error is the class
/// Python raises: OverflowError past `time_t`, OSError past the C runtime's `gmtime` (measured on 3.13.15 here: its
/// last second is 32536850399, 3001-01-19T21:59:59Z), the microseconds rounded half to even first.
pub fn iso(when: f64) -> Result<String, &'static str> {
    if !when.is_finite() {
        return Err("ValueError");
    }
    let mut seconds = when.floor();
    // `time_t`'s range, 2^63 either side.
    let limit = (1u64 << 63) as f64;
    if !(-limit..limit).contains(&seconds) {
        return Err("OverflowError");
    }
    let micro = ((when - seconds) * 1e6).round_ties_even();
    if micro >= 1e6 {
        seconds += 1.0;
    }
    if !(-43200.0..=32_536_850_399.0).contains(&seconds) {
        return Err("OSError");
    }
    let total = seconds as i64;
    let days = total.div_euclid(86_400);
    let rest = total.rem_euclid(86_400);
    let (year, month, day) = civil(days);
    Ok(format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        rest % 3600 / 60,
        rest % 60
    ))
}

/// Days since 1970-01-01 as (year, month, day) in the proleptic Gregorian calendar.
fn civil(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `known(value, vocabulary)`: the word itself when the report may carry it, OTHER when not.
pub fn known(value: &Value, vocabulary: &[&str]) -> Value {
    match value {
        Value::Null => Value::Null,
        Value::Str(text) if text.as_str().is_some_and(|word| vocabulary.contains(&word)) => {
            value.clone()
        }
        _ => Value::from(OTHER),
    }
}

/// `full(version)`.
pub fn full(version: &str) -> String {
    let version = strip(version);
    if version.starts_with("codex-cli ") {
        version.to_owned()
    } else {
        format!("codex-cli {version}")
    }
}

/// A run of `\d` (Unicode decimal digits) at the start of `chars`: (its length, its value).
fn digits(chars: &[char]) -> (usize, u64) {
    let mut value: u64 = 0;
    let mut count = 0;
    for c in chars {
        match decimal_value(*c) {
            Some(digit) => {
                value = value.saturating_mul(10).saturating_add(u64::from(digit));
                count += 1;
            }
            None => break,
        }
    }
    (count, value)
}

/// `VERSION.match(text)`: `\Acodex-cli \d[0-9A-Za-z.\-]{0,39}\Z`.
pub fn version_matches(text: &str) -> bool {
    let Some(rest) = text.strip_prefix("codex-cli ") else {
        return false;
    };
    let chars: Vec<char> = rest.chars().collect();
    let Some(first) = chars.first() else {
        return false;
    };
    decimal_value(*first).is_some()
        && chars.len() <= 40
        && chars[1..]
            .iter()
            .all(|c| c.is_ascii_alphanumeric() || *c == '.' || *c == '-')
}

/// `GRAMMAR.match(text).groups()` as numbers: `\Acodex-cli (\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-alpha\.(\d{1,9})
/// (?:\.(\d{1,9}))?)?\Z`.
pub fn grammar(text: &str) -> Option<[Option<u64>; 5]> {
    let rest = text.strip_prefix("codex-cli ")?;
    let chars: Vec<char> = rest.chars().collect();
    let mut at = 0;
    let mut parts = [None; 5];
    for (index, slot) in parts.iter_mut().enumerate().take(3) {
        let (count, value) = digits(&chars[at..]);
        if !(1..=6).contains(&count) {
            return None;
        }
        *slot = Some(value);
        at += count;
        if index < 2 {
            if chars.get(at) != Some(&'.') {
                return None;
            }
            at += 1;
        }
    }
    let tail: String = chars[at..].iter().collect();
    if tail.is_empty() {
        return Some(parts);
    }
    let alpha: Vec<char> = tail.strip_prefix("-alpha.")?.chars().collect();
    let (count, value) = digits(&alpha);
    if !(1..=9).contains(&count) {
        return None;
    }
    parts[3] = Some(value);
    let after = &alpha[count..];
    if after.is_empty() {
        return Some(parts);
    }
    if after[0] != '.' {
        return None;
    }
    let (count, value) = digits(&after[1..]);
    if !(1..=9).contains(&count) || after.len() != count + 1 {
        return None;
    }
    parts[4] = Some(value);
    Some(parts)
}

/// `canonical_version(value)`: `codex-cli <version>` in the one spelling the product writes, or None.
pub fn canonical_version(value: &Value) -> Option<String> {
    let text = value.as_str_value()?;
    let version = full(text);
    let parts = grammar(&version)?;
    if !version_matches(&version) {
        return None;
    }
    let [major, minor, patch, alpha, sub] = parts;
    let mut written = format!(
        "codex-cli {}.{}.{}",
        major.unwrap_or(0),
        minor.unwrap_or(0),
        patch.unwrap_or(0)
    );
    if let Some(alpha) = alpha {
        written.push_str(&format!("-alpha.{alpha}"));
        if let Some(sub) = sub
            && sub != 0
        {
            written.push_str(&format!(".{sub}"));
        }
    }
    (written == version).then_some(version)
}

/// `_order(version)`.
pub fn order(version: &str) -> Vec<u64> {
    match grammar(version) {
        Some(parts) => parts.iter().map(|part| part.unwrap_or(0)).collect(),
        None => Vec::new(),
    }
}

trait AsText {
    fn as_str_value(&self) -> Option<&str>;
}

impl AsText for Value {
    fn as_str_value(&self) -> Option<&str> {
        match self {
            Value::Str(text) => text.as_str(),
            _ => None,
        }
    }
}

// ------------------------------------------------------------------------------ one record
/// `json.loads(row["gate_eval"] or "{}")`, or None where that raises.
fn gate_document(row: &Row) -> Option<Value> {
    let stored = col(row, "gate_eval");
    if !pyval::truthy(stored) {
        return loads("{}").ok();
    }
    match stored {
        Value::Str(text) => loads(text.as_str()?).ok(),
        _ => None,
    }
}

/// `gate_vector(row)`.
pub fn gate_vector(row: &Row) -> Map {
    match gate_document(row) {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    }
}

/// `gate_passed(row, name)`: True or False, or None when the evaluation is not a JSON object.
fn gate_passed(row: &Row, name: &str) -> Option<bool> {
    let Some(Value::Object(found)) = gate_document(row) else {
        return None;
    };
    Some(match found.get(name) {
        Some(Value::Array(gate)) => gate.first().is_some_and(|first| pyval::is(first, PASS)),
        _ => false,
    })
}

/// `delivered(row)`: resumed_at is set.
pub fn delivered(row: &Row) -> bool {
    pyval::truthy(col(row, "resumed_at"))
}

fn state_in(row: &Row, words: &[&str]) -> bool {
    pyval::text(col(row, "state")).is_some_and(|state| words.contains(&state))
}

fn settled(row: &Row) -> Option<bool> {
    (delivered(row) && !pyval::is(col(row, "state"), "turn_started"))
        .then(|| state_in(row, &outcomes()))
}

/// `EXERCISED[name](row)`: True confirmed, False missed, None not exercised.
fn exercised(name: &str, row: &Row) -> Option<bool> {
    let usage = pyval::is(col(row, "category"), "usage_limit");
    let evaluated = pyval::truthy(col(row, "gate_eval"));
    match name {
        "usage_limit_detection" => usage.then_some(true),
        "usage_reset_hint" => usage.then(|| {
            let kind = col(row, "limit_type");
            let text = if pyval::truthy(kind) {
                py_str(kind)
            } else {
                String::new()
            };
            pyval::truthy(col(row, "reset_at")) && text.starts_with("codex:")
        }),
        "engine_present" => evaluated
            .then(|| gate_passed(row, "engine_compatible"))
            .flatten(),
        "projection_freshness" => evaluated.then(|| gate_passed(row, "identity")).flatten(),
        "loaded_state_detection" => evaluated
            .then(|| gate_passed(row, "thread_available"))
            .flatten(),
        "usage_probe" => evaluated.then(|| gate_passed(row, "usage")).flatten(),
        "thread_eligibility" => pyval::truthy(col(row, "submitted_at")).then_some(true),
        "exact_thread_recovery" => {
            if delivered(row) {
                Some(true)
            } else if pyval::truthy(col(row, "submitted_at"))
                && state_in(row, &["submission_unknown", "failed"])
            {
                Some(false)
            } else {
                None
            }
        }
        _ => settled(row),
    }
}

// ------------------------------------------------------------------------------ the logs
/// `LOG_LINE.match(line)`: `^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$` - the stamp's 19 characters and the rest.
fn log_line(line: &str) -> Option<(Vec<char>, &str)> {
    let rest = line.strip_prefix('[')?;
    let chars: Vec<char> = rest.chars().take(19).collect();
    if chars.len() < 19 {
        return None;
    }
    let shape = "dddd-dd-dd dd:dd:dd";
    for (c, want) in chars.iter().zip(shape.chars()) {
        let fits = if want == 'd' {
            decimal_value(*c).is_some()
        } else {
            *c == want
        };
        if !fits {
            return None;
        }
    }
    let used: usize = chars.iter().map(|c| c.len_utf8()).sum();
    let text = rest[used..].strip_prefix("] ")?;
    if text.contains('\n') {
        return None;
    }
    Some((chars, text))
}

fn value_of(chars: &[char]) -> i64 {
    chars.iter().fold(0i64, |sum, c| {
        sum * 10 + i64::from(decimal_value(*c).unwrap_or(0))
    })
}

/// `time.strptime(stamp, "%Y-%m-%d %H:%M:%S")`'s fields, where its own patterns take the stamp and the date is one
/// (`datetime.date(year, month, day)`); None for a ValueError.
fn strptime(chars: &[char]) -> Option<(i64, i64, i64, i64, i64, i64)> {
    let ascii = |c: char, low: char, high: char| (low..=high).contains(&c);
    let digit = |c: char| decimal_value(c).is_some();
    let (m0, m1) = (chars[5], chars[6]);
    let month_fits = (m0 == '1' && ascii(m1, '0', '2')) || (m0 == '0' && ascii(m1, '1', '9'));
    let (d0, d1) = (chars[8], chars[9]);
    let day_fits = (d0 == '3' && ascii(d1, '0', '1'))
        || (ascii(d0, '1', '2') && digit(d1))
        || (d0 == '0' && ascii(d1, '1', '9'));
    let (h0, h1) = (chars[11], chars[12]);
    let hour_fits = (h0 == '2' && ascii(h1, '0', '3')) || (ascii(h0, '0', '1') && digit(h1));
    let minute_fits = ascii(chars[14], '0', '5') && digit(chars[15]);
    let (s0, s1) = (chars[17], chars[18]);
    let second_fits = (s0 == '6' && ascii(s1, '0', '1')) || (ascii(s0, '0', '5') && digit(s1));
    if !(month_fits && day_fits && hour_fits && minute_fits && second_fits) {
        return None;
    }
    let year = value_of(&chars[0..4]);
    let month = value_of(&chars[5..7]);
    let day = value_of(&chars[8..10]);
    if year < 1 {
        return None;
    }
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let last = match month {
        2 if leap => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    };
    if day > last {
        return None;
    }
    Some((
        year,
        month,
        day,
        value_of(&chars[11..13]),
        value_of(&chars[14..16]),
        value_of(&chars[17..19]),
    ))
}

/// `log_lines(texts)`: (time, text) for every line of the logs' texts, sorted by time, each time read back on this
/// PC's zone (`time.mktime`).
pub fn log_lines(
    texts: &[String],
    clock: &dyn car_policy::classify::clock::LocalClock,
) -> Vec<(f64, String)> {
    let mut lines = Vec::new();
    for text in texts {
        for line in crate::tools::splitlines(text) {
            let Some((stamp, rest)) = log_line(line) else {
                continue;
            };
            let Some((year, mon, mday, hour, min, sec)) = strptime(&stamp) else {
                continue;
            };
            let Ok(when) = clock.mktime(year, mon, mday, hour, min, sec) else {
                continue;
            };
            lines.push((when, rest.to_owned()));
        }
    }
    lines.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
    lines
}

/// `engine_version_of(text)`: `ENGINE.search(text + " ")`'s group - `engine (codex-cli \d[0-9A-Za-z.\-]*?)[\s;,)]`.
pub fn engine_version_of(text: &str) -> Option<String> {
    let padded: Vec<char> = text.chars().chain(std::iter::once(' ')).collect();
    let prefix: Vec<char> = "engine codex-cli ".chars().collect();
    let class = |c: char| c.is_ascii_alphanumeric() || c == '.' || c == '-';
    let ends = |c: char| is_space(c) || c == ';' || c == ',' || c == ')';
    for start in 0..padded.len() {
        if !padded[start..].starts_with(&prefix) {
            continue;
        }
        let mut at = start + prefix.len();
        let Some(first) = padded.get(at) else {
            continue;
        };
        if decimal_value(*first).is_none() {
            continue;
        }
        at += 1;
        while padded.get(at).is_some_and(|c| class(*c)) {
            at += 1;
        }
        if padded.get(at).is_some_and(|c| ends(*c)) {
            return Some(padded[start + 7..at].iter().collect());
        }
    }
    None
}

/// `engine_timeline(lines)`.
pub fn engine_timeline(lines: &[(f64, String)]) -> Vec<(f64, String)> {
    lines
        .iter()
        .filter_map(|(when, text)| engine_version_of(text).map(|version| (*when, version)))
        .collect()
}

/// `latest_engine(lines)`: the engine the last engine line names, or None.
pub fn latest_engine(lines: &[(f64, String)]) -> Option<String> {
    lines
        .iter()
        .rev()
        .find_map(|(_, text)| engine_version_of(text).filter(|found| version_matches(found)))
}

/// `passes_checks(text, version)`.
fn passes_checks(text: &str, version: &str) -> bool {
    engine_version_of(text).as_deref() == Some(version)
        && ENGINE_LOG_PASSES.iter().any(|said| text.contains(said))
}

// ------------------------------------------------------------------------------ which engine
fn span(row: &Row) -> (f64, f64) {
    let start = moment(col(row, "resumed_at"))
        .or_else(|| moment(col(row, "detected_at")))
        .unwrap_or(0.0);
    (start, moment(col(row, "outcome_at")).unwrap_or(start))
}

/// `placement(timeline, start, end, current)`: (version, None), or (None, why).
pub fn placement(
    timeline: &[(f64, String)],
    start: f64,
    end: f64,
    current: &str,
) -> (Option<String>, Option<&'static str>) {
    let Some((_, version)) = timeline.iter().rev().find(|(when, _)| *when <= start) else {
        return (None, Some(UNPLACED[0]));
    };
    if timeline
        .iter()
        .any(|(when, other)| start < *when && *when < end && other != version)
    {
        return (None, Some(UNPLACED[1]));
    }
    match timeline.iter().find(|(when, _)| *when >= end) {
        Some((_, after)) if after == version => (Some(version.clone()), None),
        Some(_) => (None, Some(UNPLACED[2])),
        None if version == current => (Some(version.clone()), None),
        None => (None, Some(UNPLACED[3])),
    }
}

/// `place(rows, timeline, current, version)`: (the records on `version`, oldest first; how many could not be
/// placed, by code).
pub fn place(
    rows: &[Row],
    timeline: &[(f64, String)],
    current: &str,
    version: &str,
) -> (Vec<Row>, Vec<(&'static str, i64)>) {
    let mut placed = Vec::new();
    let mut unplaced: Vec<(&'static str, i64)> = Vec::new();
    for row in rows {
        let (start, end) = span(row);
        let (found, why) = placement(timeline, start, end, current);
        match (found, why) {
            (Some(found), _) if found == version => placed.push(row.clone()),
            (Some(_), _) => {}
            (None, Some(why)) => match unplaced.iter_mut().find(|(code, _)| *code == why) {
                Some(entry) => entry.1 += 1,
                None => unplaced.push((why, 1)),
            },
            (None, None) => {}
        }
    }
    placed.sort_by(|a, b| {
        let (a, b) = (moment(col(a, "detected_at")), moment(col(b, "detected_at")));
        a.partial_cmp(&b).unwrap_or(std::cmp::Ordering::Equal)
    });
    (placed, unplaced)
}

// ------------------------------------------------------------------------------ which route
/// `another_route(row, paid={})`: carried by an advanced feature's route of its own, by the product's own marks.
fn another_route(row: &Row) -> bool {
    if let Value::Str(key) = col(row, "interruption_id")
        && let Some(key) = key.as_str()
        && pyval::eq(
            col(row, "recovery_client_id"),
            &Value::from(ids::continuation_client_id(key)),
        )
    {
        return true;
    }
    gate_vector(row).iter().any(|(name, gate)| {
        name.as_str() != Some(CONSENT)
            && matches!(gate, Value::Array(pair) if pair.len() == 2
                && pyval::text(&pair[1]).is_some_and(|word| PLUG_WORDS.contains(&word)))
    })
}

/// `beyond_reach(row, reach)`.
fn beyond_reach(row: &Row, reach: Option<f64>) -> bool {
    match (reach, moment(col(row, "last_claim_at"))) {
        (Some(reach), Some(claim)) => claim < reach,
        _ => false,
    }
}

/// `by_route(rows, {}, reach)`: (the records the standard route carried, how many another did, how many were
/// claimed before the ledger can tell).
pub fn by_route(rows: Vec<Row>, reach: Option<f64>) -> (Vec<Row>, i64, i64) {
    let (mut kept, mut routed, mut unknown) = (Vec::new(), 0, 0);
    for row in rows {
        if another_route(&row) {
            routed += 1;
        } else if beyond_reach(&row, reach) {
            unknown += 1;
        } else {
            kept.push(row);
        }
    }
    (kept, routed, unknown)
}

// ------------------------------------------------------------------------------ the body
fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (name, value) in pairs {
        map.insert(Str::from(name), value);
    }
    Value::Object(map)
}

fn iso_or_null(when: Option<f64>) -> Result<Value, &'static str> {
    match when {
        Some(when) => Ok(Value::from(iso(when)?)),
        None => Ok(Value::Null),
    }
}

/// `body(version, rows, lines, watcher, progress)` with every `progress` None: what the records show for one engine
/// version, as the reporter writes it.
pub fn body(
    version: &str,
    rows: &[Row],
    lines: &[(f64, String)],
    watcher: Option<&Value>,
) -> Result<Value, &'static str> {
    let reports: Vec<&(f64, String)> = lines
        .iter()
        .filter(|(_, text)| passes_checks(text, version))
        .collect();
    let mut checked: Vec<&str> = if reports.is_empty() {
        Vec::new()
    } else {
        SEND_GATE.to_vec()
    };
    if let Some(Value::Object(capabilities)) = watcher {
        for (name, capability) in capabilities {
            let Some(name) = name.as_str() else { continue };
            let Some(known) = EXERCISED.iter().find(|each| **each == name) else {
                continue;
            };
            if let Value::Object(entry) = capability
                && entry
                    .get("reason")
                    .and_then(pyval::text)
                    .is_some_and(|reason| LOCAL_PASS_REASONS.contains(&reason))
                && !checked.contains(known)
            {
                checked.push(known);
            }
        }
    }
    struct Entry {
        confirmed: i64,
        missed: i64,
        last: Option<f64>,
        level: Option<&'static str>,
    }
    let mut capabilities: Vec<(&str, Entry)> = Vec::new();
    for name in EXERCISED {
        let verdicts: Vec<Option<bool>> = rows.iter().map(|row| exercised(name, row)).collect();
        let last = rows
            .iter()
            .zip(&verdicts)
            .filter(|(_, verdict)| **verdict == Some(true))
            .filter_map(|(row, _)| {
                moment(col(row, "outcome_at")).or_else(|| moment(col(row, "detected_at")))
            })
            .fold(None, |best: Option<f64>, x| {
                Some(best.map_or(x, |b| b.max(x)))
            });
        capabilities.push((
            name,
            Entry {
                confirmed: verdicts.iter().filter(|v| **v == Some(true)).count() as i64,
                missed: verdicts.iter().filter(|v| **v == Some(false)).count() as i64,
                last,
                level: None,
            },
        ));
    }
    let seen = rows
        .iter()
        .any(|row| delivered(row) && state_in(row, &outcomes()));
    for (name, entry) in capabilities.iter_mut() {
        entry.level = if seen && entry.confirmed > 0 && entry.missed == 0 {
            Some(VERIFIED)
        } else if checked.contains(name) {
            Some(CHECKED)
        } else {
            None
        };
    }
    let gate_verified = SEND_GATE.iter().all(|gate| {
        capabilities
            .iter()
            .any(|(name, entry)| name == gate && entry.level == Some(VERIFIED))
    });
    if seen && !gate_verified {
        for (name, entry) in capabilities.iter_mut() {
            if entry.level == Some(VERIFIED) {
                entry.level = checked.contains(name).then_some(CHECKED);
            }
        }
    }
    let levels: Vec<&str> = capabilities
        .iter()
        .filter_map(|(_, entry)| entry.level)
        .collect();
    let verdict = if levels.contains(&VERIFIED) {
        "PASS"
    } else if levels.is_empty() {
        "NONE"
    } else {
        "CHECKED"
    };
    let mut covers = checked.clone();
    covers.sort_unstable();
    let local = object(vec![
        ("reports", Value::from(reports.len() as i64)),
        ("first", iso_or_null(reports.first().map(|each| each.0))?),
        ("last", iso_or_null(reports.last().map(|each| each.0))?),
        (
            "covers",
            Value::Array(covers.into_iter().map(Value::from).collect()),
        ),
    ]);
    let (categories, states, reasons, turns) = (categories(), states(), reasons(), turn_statuses());
    let mut records = Vec::new();
    for row in rows {
        let passed = gate_vector(row)
            .values()
            .filter(|gate| {
                matches!(gate, Value::Array(items) if items.first().is_some_and(|first| pyval::is(first, PASS)))
            })
            .count() as i64;
        records.push(object(vec![
            ("detected_at", iso_or_null(moment(col(row, "detected_at")))?),
            ("delivered_at", iso_or_null(moment(col(row, "resumed_at")))?),
            ("outcome_at", iso_or_null(moment(col(row, "outcome_at")))?),
            ("category", known(col(row, "category"), &categories)),
            ("state", known(col(row, "state"), &states)),
            ("reason", known(col(row, "last_error"), &reasons)),
            (
                "turn_status",
                known(col(row, "recovery_turn_status"), &turns),
            ),
            ("gates_passed", Value::from(passed)),
            ("progress_items", Value::Null),
        ]));
    }
    let mut sorted: Vec<&(&str, Entry)> = capabilities.iter().collect();
    sorted.sort_by_key(|(name, _)| *name);
    let mut out = Map::new();
    for (name, entry) in sorted {
        out.insert(
            Str::from(*name),
            object(vec![
                ("confirmed", Value::from(entry.confirmed)),
                ("missed", Value::from(entry.missed)),
                (
                    "last_confirmed",
                    match entry.last {
                        Some(last) if last != 0.0 => Value::from(iso(last)?),
                        _ => Value::Null,
                    },
                ),
                ("level", entry.level.map_or(Value::Null, Value::from)),
            ]),
        );
    }
    Ok(object(vec![
        ("codex_version", Value::from(version)),
        ("verdict", Value::from(verdict)),
        ("local_checks", local),
        ("records", Value::Array(records)),
        ("capabilities", Value::Object(out)),
    ]))
}

// ------------------------------------------------------------------------------ how a report counts
/// `graded(records)`.
pub fn graded(records: &[Value]) -> Value {
    let delivered: Vec<&Value> = records
        .iter()
        .filter(|record| pyval::get(record, "delivered_at").is_ok_and(pyval::truthy))
        .collect();
    let state = |record: &&Value| {
        pyval::get(record, "state")
            .ok()
            .and_then(pyval::text)
            .map(str::to_owned)
    };
    let worked = delivered
        .iter()
        .any(|record| state(record).as_deref() == Some("recovered"));
    let failed = delivered.iter().any(|record| {
        matches!(
            state(record).as_deref(),
            Some("recovery_turn_failed" | "failed" | "terminal_failure")
        )
    });
    object(vec![
        ("worked", Value::Bool(worked)),
        ("failed", Value::Bool(failed)),
        ("neither", Value::Bool(!(worked || failed))),
        ("both", Value::Bool(worked && failed)),
    ])
}

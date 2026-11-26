//! The host contracts (P6 step 0, seat S6.2; `outputs/plans/v0627-rust/P6-DESIGN.md` 1.2, 1.3, 1.5).
//!
//! `car_core.dll` is the core the C# watcher host `CodexAutoResume.exe` loads (D1 = U2, one process). Between the two
//! there are exactly the six exports of [`EXPORTS`], made by [`export_core!`](crate::export_core), and nothing else:
//!
//! ```c
//! // Every reply is a buffer the core allocated; the host hands it back to car_free exactly once.
//! uint8_t* car_start(const uint8_t* req, size_t req_len, size_t* out_len);
//! int32_t  car_stop(void);
//! uint8_t* car_bridge(const uint8_t* line, size_t len, size_t* out_len);
//! uint8_t* car_next_event(uint32_t timeout_ms, size_t* out_len);   // NULL on timeout
//! uint8_t* car_post_action(const uint8_t* req, size_t len, size_t* out_len);
//! void     car_free(uint8_t* buffer, size_t len);
//! ```
//!
//! * **The wire.** Every request and every reply is UTF-8 JSON over a pointer and a length, the window's wire format;
//!   replies are written by car-machine's writer ([`Options::wire`], D5/D12). `car_start`'s reply always carries
//!   `"abi": 1` ([`ABI`]); a host given any other number (or none) exits `EXIT_ERROR` (1) with one launcher-log line.
//! * **One allocator.** Rust allocates each reply as a `Box<[u8]>` and leaks it; `car_free` takes it back with the
//!   same length. The core keeps the address and length of every reply it handed out, so a second `car_free` of the
//!   same buffer, a wrong length or a pointer the core never made frees nothing (a leak, never undefined behaviour).
//!   The host copies the bytes out and frees in a `finally`; no pointer is held across calls, and the core never
//!   keeps a pointer the host gave it.
//! * **No callback.** The core never calls into managed code. Everything it has to say goes through
//!   [`car_next_event`](next_event), which the host's pump pulls.
//! * **No export sends.** `car_post_action` takes only the closed [`ActionKind`] table (a `popup` call only one of
//!   [`POPUP_CALLS`]); any other name is answered `{"ok":false,"error":"unknown_action"}`.
//! * **Panics (D15).** Every export body runs inside `catch_unwind` (car-machine's `caught::catch`, the one
//!   catcher). A caught panic is answered `{"ok":false,"error":"panic"}` (`car_start`'s with `"abi": 1` first;
//!   `car_stop` returns -1; `car_free` frees nothing more) and counted ([`panics`]). The exports stay `extern "C"`, not `"C-unwind"`: anything that still
//!   escapes aborts the process instead of unwinding into the CLR.
//! * **A null `out_len`.** The call does nothing and answers NULL: a reply the host cannot measure is a reply it
//!   cannot free.
//!
//! **The empty core.** Until S6.1's watcher is here there is nothing to start: `car_start` reads the request and
//! answers `{"abi": 1, "ok": false, "error": "not_ported"}` (as the stub core refuses every command, car-bin
//! `NOT_PORTED`: it never answers success for work it did not do); `car_stop` has nothing to stop and answers 0;
//! `car_bridge` and every known action answer `{"ok":false,"error":"not_started"}`; `car_next_event` has no event to
//! give and answers NULL when `timeout_ms` has passed. S6.2b fills these bodies over car-watcher; the six signatures,
//! the tables and the rules above change only by the main session's word (P6-DESIGN 4.1).
//!
//! **One generic entry (Q3, P7-DESIGN 2.4).** One `CodexAutoResume.exe` serves both editions; what differs is in each
//! edition's `car_core.dll`, and only in the [`Factory`] it hands [`export_core!`](crate::export_core): car-host's own
//! build is `export_core!(Guarded::null)` (feature `exports`, on by default), and the other edition's host crate
//! depends on car-host with `default-features = false` and is the same call with its own plug.

use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Condvar, Mutex, MutexGuard, PoisonError};
use std::time::{Duration, Instant};

use car_machine::json::{self, Map, Options, Str, Value};
use car_policy::plug::Guarded;

/// The contract's version, in every `car_start` reply. A host and a core of different versions never run together.
pub const ABI: i64 = 1;

/// The whole export table of `car_core.dll`, in the order of P6-DESIGN 1.2. The DLL exports these names and no other
/// (the export-table test reads the built DLL's PE export directory), and `gui/HostCore.cs` imports exactly these.
pub const EXPORTS: [&str; 6] = [
    "car_start",
    "car_stop",
    "car_bridge",
    "car_next_event",
    "car_post_action",
    "car_free",
];

/// What an edition hands the generic entry: how its watcher's plug is made (`Guarded::null` in the standard edition).
/// The empty core never calls it; S6.1's watcher is built with `factory()` at `car_start`.
pub type Factory = fn() -> Guarded;

/// The closed table of events, Rust to C# (P6-DESIGN 1.5). Every event is `{"kind": <name>, <fields>...}`, its fields
/// in [`EventKind::fields`]' order; `ended` is always the last.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum EventKind {
    /// The surfaces to build: `App._start_tray` building `tray.Tray(...)` (runtime/app.py:612-652), with the catalog's
    /// locale and the fonts' lacks rule, so the first frame is drawn in that language (DECISIONS.md's addendum). The core
    /// then waits up to 5 s for `tray_started` (`Tray.start`, ui/tray/icon.py:169-174).
    Surfaces,
    /// `tray.snapshot_from` with `EXTRA` and `blocked` in it, once per tick (`_update_tray`, runtime/app.py:654-669), and
    /// the popup's ready view beside it (car-surface `PopupModel.view`: rows, status, header, row menus), so the host
    /// computes no row or status (DECISIONS.md, "The popup's model at the host boundary").
    Snapshot,
    /// A new catalog after a language change (`refresh_settings`, runtime/app.py:443-447), with the catalog's locale and
    /// the fonts' lacks rule (`letters`), which the host has no catalog to derive.
    Strings,
    /// The adopted settings (`popup.adopt_settings(values)`, runtime/app.py:439-440).
    Settings,
    /// One card notice (`Inbox.post` from `notifier.deliver`), only while the host has the card stack attached.
    Notice,
    /// One made-up card (`notifier.show_demo`, runtime/app.py:537-547).
    Demo,
    /// Take the surfaces down; the core waits up to 5 s for `closed` (`Tray.stop`, ui/tray/icon.py:191-195).
    Close,
    /// `run` returned with this exit code (runtime/loop.py:44-52). Always the last event.
    Ended,
}

impl EventKind {
    /// Every event, in the table's order.
    pub const ALL: [EventKind; 8] = [
        EventKind::Surfaces,
        EventKind::Snapshot,
        EventKind::Strings,
        EventKind::Settings,
        EventKind::Notice,
        EventKind::Demo,
        EventKind::Close,
        EventKind::Ended,
    ];

    /// Its `kind` on the wire.
    pub const fn name(self) -> &'static str {
        match self {
            EventKind::Surfaces => "surfaces",
            EventKind::Snapshot => "snapshot",
            EventKind::Strings => "strings",
            EventKind::Settings => "settings",
            EventKind::Notice => "notice",
            EventKind::Demo => "demo",
            EventKind::Close => "close",
            EventKind::Ended => "ended",
        }
    }

    /// The fields it carries beside `kind`, in the order they are written.
    ///
    /// * `surfaces`: `icon` (the icon file's path), `strings` (`interface.catalog()`), `settings` (the settings the
    ///   surfaces adopt: theme, design, reduce_motion, as `adopt_settings` reads them), `edition` (`edition.shown`),
    ///   `demo` (the demo's name, `str(paths.state_dir)`), `locale` (the catalog's locale), `letters` (the fonts' lacks
    ///   rule);
    /// * `snapshot`: `snapshot` (the tray's snapshot), `popup` (the popup's view, `PopupModel.view`'s output);
    /// * `strings`: `strings` (the catalog), `locale` (its locale), `letters` (the fonts' lacks rule);
    /// * `settings`: `settings`;
    /// * `notice` and `demo`: `notice` (one card: its id, view and buttons);
    /// * `close`: none; `ended`: `exit_code`.
    pub const fn fields(self) -> &'static [&'static str] {
        match self {
            EventKind::Surfaces => &[
                "icon", "strings", "settings", "edition", "demo", "locale", "letters",
            ],
            EventKind::Snapshot => &["snapshot", "popup"],
            EventKind::Strings => &["strings", "locale", "letters"],
            EventKind::Settings => &["settings"],
            EventKind::Notice | EventKind::Demo => &["notice"],
            EventKind::Close => &[],
            EventKind::Ended => &["exit_code"],
        }
    }

    /// The event named `name`, or None for a name outside the table.
    pub fn from_name(name: &str) -> Option<EventKind> {
        EventKind::ALL.into_iter().find(|kind| kind.name() == name)
    }
}

/// The `surfaces` event's fields, in [`EventKind::fields`]' order.
#[derive(Clone, Debug, PartialEq)]
pub struct Surfaces {
    pub icon: Value,
    pub strings: Value,
    pub settings: Value,
    pub edition: Value,
    pub demo: Value,
    pub locale: Value,
    pub letters: Value,
}

/// One event, as the core queues it for `car_next_event`.
#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    Surfaces(Box<Surfaces>),
    Snapshot {
        snapshot: Value,
        popup: Value,
    },
    Strings {
        strings: Value,
        locale: Value,
        letters: Value,
    },
    Settings {
        settings: Value,
    },
    Notice {
        notice: Value,
    },
    Demo {
        notice: Value,
    },
    Close,
    Ended {
        exit_code: i32,
    },
}

impl Event {
    pub fn kind(&self) -> EventKind {
        match self {
            Event::Surfaces(_) => EventKind::Surfaces,
            Event::Snapshot { .. } => EventKind::Snapshot,
            Event::Strings { .. } => EventKind::Strings,
            Event::Settings { .. } => EventKind::Settings,
            Event::Notice { .. } => EventKind::Notice,
            Event::Demo { .. } => EventKind::Demo,
            Event::Close => EventKind::Close,
            Event::Ended { .. } => EventKind::Ended,
        }
    }

    /// `{"kind": ..., <fields>...}` in [`EventKind::fields`]' order.
    pub fn to_json(&self) -> Value {
        let values: Vec<Value> = match self {
            Event::Surfaces(surfaces) => vec![
                surfaces.icon.clone(),
                surfaces.strings.clone(),
                surfaces.settings.clone(),
                surfaces.edition.clone(),
                surfaces.demo.clone(),
                surfaces.locale.clone(),
                surfaces.letters.clone(),
            ],
            Event::Snapshot { snapshot, popup } => vec![snapshot.clone(), popup.clone()],
            Event::Strings {
                strings,
                locale,
                letters,
            } => vec![strings.clone(), locale.clone(), letters.clone()],
            Event::Settings { settings } => vec![settings.clone()],
            Event::Notice { notice } | Event::Demo { notice } => vec![notice.clone()],
            Event::Close => vec![],
            Event::Ended { exit_code } => vec![int(i64::from(*exit_code))],
        };
        let kind = self.kind();
        let mut map = Map::new();
        map.insert(Str::new("kind"), Value::Str(Str::new(kind.name())));
        for (name, value) in kind.fields().iter().zip(values) {
            map.insert(Str::new(name), value);
        }
        Value::Object(map)
    }
}

/// The closed table of actions, C# to Rust (P6-DESIGN 1.5, Q2: the actors stay as today). A request is
/// `{"action": <name>, <fields>...}`; a field left out reads as null.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ActionKind {
    /// `Tray.start`'s result: the surfaces are up.
    TrayStarted,
    /// `Tray.stop` returning: the surfaces are down.
    Closed,
    /// The card stack attached to the inbox (notice_inbox.py:8-21).
    CardsAttached,
    /// The card stack detached, handing back what it had not taken.
    CardsDetached,
    /// `{paused}`: `Control.set_enabled` (runtime/app.py:621-622).
    Toggle,
    /// The Stop item: `StopEvent.signal()` (runtime/app.py:640).
    Stop,
    /// `{page, row}`: `tray.open_dashboard` (ui/tray/dashboard.py:44-92).
    OpenDashboard,
    /// `{thread}`: `tray.open_chat`.
    OpenChat,
    /// `{uri}`: `App._notice_action` -> `notifier.activate`, actor `"toast"` (runtime/app.py:516-536).
    NoticeAction,
    /// `{id, shown}`: `notifier.complete` (notifier.py:472).
    NoticeComplete,
    /// `{call, args}`: one of [`POPUP_CALLS`], done as `perform` does it (ui/popup/model.py:372), with the popup's own
    /// `pending_source`.
    Popup,
    /// The menu's `disarm_power_action(actor="tray")` (ui/tray/menu.py:202).
    DisarmPower,
    /// The popup marking what it showed as seen (ui/tray/clicks.py).
    MarkSeen,
    /// The popup marking the failure it showed as seen.
    FailureSeen,
}

impl ActionKind {
    /// Every action, in the table's order.
    pub const ALL: [ActionKind; 14] = [
        ActionKind::TrayStarted,
        ActionKind::Closed,
        ActionKind::CardsAttached,
        ActionKind::CardsDetached,
        ActionKind::Toggle,
        ActionKind::Stop,
        ActionKind::OpenDashboard,
        ActionKind::OpenChat,
        ActionKind::NoticeAction,
        ActionKind::NoticeComplete,
        ActionKind::Popup,
        ActionKind::DisarmPower,
        ActionKind::MarkSeen,
        ActionKind::FailureSeen,
    ];

    /// Its `action` on the wire.
    pub const fn name(self) -> &'static str {
        match self {
            ActionKind::TrayStarted => "tray_started",
            ActionKind::Closed => "closed",
            ActionKind::CardsAttached => "cards_attached",
            ActionKind::CardsDetached => "cards_detached",
            ActionKind::Toggle => "toggle",
            ActionKind::Stop => "stop",
            ActionKind::OpenDashboard => "open_dashboard",
            ActionKind::OpenChat => "open_chat",
            ActionKind::NoticeAction => "notice_action",
            ActionKind::NoticeComplete => "notice_complete",
            ActionKind::Popup => "popup",
            ActionKind::DisarmPower => "disarm_power",
            ActionKind::MarkSeen => "mark_seen",
            ActionKind::FailureSeen => "failure_seen",
        }
    }

    /// The fields it reads beside `action`.
    pub const fn fields(self) -> &'static [&'static str] {
        match self {
            ActionKind::Toggle => &["paused"],
            ActionKind::OpenDashboard => &["page", "row"],
            ActionKind::OpenChat => &["thread"],
            ActionKind::NoticeAction => &["uri"],
            ActionKind::NoticeComplete => &["id", "shown"],
            ActionKind::Popup => &["call", "args"],
            _ => &[],
        }
    }

    /// The action named `name`, or None for a name outside the table.
    pub fn from_name(name: &str) -> Option<ActionKind> {
        ActionKind::ALL.into_iter().find(|kind| kind.name() == name)
    }
}

/// The whole of what the popup may ask of the control layer: `CONTROL_CALLS` (ui/popup/model.py:34-35), in its order.
pub const POPUP_CALLS: [&str; 10] = [
    "list_pending",
    "get_status",
    "set_enabled",
    "set_interruption_recovery",
    "postpone",
    "unpostpone",
    "release_hold",
    "set_thread_tier",
    "set_project_rule",
    "set_once_words",
];

/// One action as `car_post_action` read it: its kind and its fields (each one null where the request left it out),
/// in [`ActionKind::fields`]' order.
#[derive(Clone, Debug, PartialEq)]
pub struct Action {
    pub kind: ActionKind,
    pub fields: Vec<Value>,
}

impl Action {
    /// The request read against the table: a request that is not an object with a text `action` is
    /// [`Refusal::BadRequest`]; a name outside the table, or a `popup` whose `call` is not a text in
    /// [`POPUP_CALLS`], is [`Refusal::UnknownAction`]. A field's type is not checked here: the action reads it as the
    /// reference reads it (`bool(paused)`, ...).
    pub fn parse(request: &Value) -> Result<Action, Refusal> {
        let Value::Object(map) = request else {
            return Err(Refusal::BadRequest);
        };
        let Some(Value::Str(name)) = map.get(&Str::new("action")) else {
            return Err(Refusal::BadRequest);
        };
        let kind = name
            .as_str()
            .and_then(ActionKind::from_name)
            .ok_or(Refusal::UnknownAction)?;
        let fields: Vec<Value> = kind
            .fields()
            .iter()
            .map(|field| map.get(&Str::new(field)).cloned().unwrap_or(Value::Null))
            .collect();
        if kind == ActionKind::Popup {
            let known = match &fields[0] {
                Value::Str(call) => call
                    .as_str()
                    .is_some_and(|call| POPUP_CALLS.contains(&call)),
                _ => false,
            };
            if !known {
                return Err(Refusal::UnknownAction);
            }
        }
        Ok(Action { kind, fields })
    }
}

/// Why an export said no: the `error` of `{"ok": false, "error": ...}`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// The request was not JSON of the export's shape (or its bytes could not be read).
    BadRequest,
    /// An action outside the closed table.
    UnknownAction,
    /// The core has no watcher to start (the empty core, until S6.1).
    NotPorted,
    /// Nothing is started, so there is nothing to ask.
    NotStarted,
    /// A panic was caught at the export's boundary (D15).
    Panic,
}

impl Refusal {
    pub const fn word(self) -> &'static str {
        match self {
            Refusal::BadRequest => "bad_request",
            Refusal::UnknownAction => "unknown_action",
            Refusal::NotPorted => "not_ported",
            Refusal::NotStarted => "not_started",
            Refusal::Panic => "panic",
        }
    }
}

/// What the core holds between calls: the replies handed out and not yet freed (address -> length), and the events
/// not yet pulled.
struct State {
    live: BTreeMap<usize, usize>,
    events: VecDeque<Event>,
}

static STATE: Mutex<State> = Mutex::new(State {
    live: BTreeMap::new(),
    events: VecDeque::new(),
});
/// Rung when an event is queued, so `car_next_event` returns as soon as there is one.
static QUEUED: Condvar = Condvar::new();
static PANICS: AtomicU64 = AtomicU64::new(0);

fn state() -> MutexGuard<'static, State> {
    STATE.lock().unwrap_or_else(PoisonError::into_inner)
}

/// How many panics the exports caught since the DLL was loaded. S6.2b also records each one as
/// `App._record_failure` does (a class-only line in the main log, the detail in `errors.log`) once the core has a home.
pub fn panics() -> u64 {
    PANICS.load(Ordering::Relaxed)
}

/// Whether `buffer` is a reply the core handed out and the host has not freed yet.
pub fn is_live(buffer: *const u8) -> bool {
    state().live.contains_key(&(buffer as usize))
}

/// Queues one event for `car_next_event`. The empty core queues none; S6.1's watcher is the caller.
pub fn queue(event: Event) {
    state().events.push_back(event);
    QUEUED.notify_all();
}

#[cfg(test)]
thread_local! {
    /// The export (by name) that panics on purpose on this thread, for the panic tests.
    static TRIP: std::cell::Cell<&'static str> = const { std::cell::Cell::new("") };
}

#[cfg(test)]
pub(crate) fn trip(name: &'static str) {
    TRIP.with(|trip| trip.set(name));
}

/// The test hook: panics where a test asked this export to. Nothing in a build that is not a test.
#[inline]
fn tripwire(_name: &str) {
    #[cfg(test)]
    if TRIP.with(|trip| trip.get()) == _name {
        panic!("tripped in {_name}");
    }
}

/// `body()`, a panic caught and counted.
fn guarded<T>(body: impl FnOnce() -> T) -> Option<T> {
    match car_machine::caught::catch(body) {
        Ok(value) => Some(value),
        Err(_) => {
            PANICS.fetch_add(1, Ordering::Relaxed);
            None
        }
    }
}

fn written(value: &Value) -> Vec<u8> {
    json::to_string(value, &Options::wire())
        .expect("a reply of texts, booleans and ints is writable")
        .into_bytes()
}

fn int(value: i64) -> Value {
    Value::Int(json::Int::parse(&value.to_string()).expect("an i64 is an int"))
}

/// `{"abi": 1, "ok": false, "error": <word>}` (with `abi` only for `car_start`).
fn refused(refusal: Refusal, abi: bool) -> Vec<u8> {
    let mut map = Map::new();
    if abi {
        map.insert(Str::new("abi"), int(ABI));
    }
    map.insert(Str::new("ok"), Value::Bool(false));
    map.insert(Str::new("error"), Value::Str(Str::new(refusal.word())));
    written(&Value::Object(map))
}

/// The request's bytes, or None where they cannot be read (a null pointer with a length, a length past `isize::MAX`).
///
/// # Safety
/// A non-null `pointer` points at `length` readable bytes for the length of the call.
unsafe fn request<'a>(pointer: *const u8, length: usize) -> Option<&'a [u8]> {
    if length == 0 {
        return Some(&[]);
    }
    if pointer.is_null() || length > isize::MAX as usize {
        return None;
    }
    // SAFETY: the caller hands `length` readable bytes at `pointer` and keeps them for the call.
    Some(unsafe { std::slice::from_raw_parts(pointer, length) })
}

/// Hands `bytes` to the host: leaked as a `Box<[u8]>`, recorded as live, its length in `*out_len`.
///
/// # Safety
/// `out_len` is non-null and writable.
unsafe fn hand_out(bytes: Vec<u8>, out_len: *mut usize) -> *mut u8 {
    let length = bytes.len();
    let buffer = Box::into_raw(bytes.into_boxed_slice()) as *mut u8;
    state().live.insert(buffer as usize, length);
    // SAFETY: the caller checked `out_len` is non-null; the host owns the place it points at.
    unsafe { out_len.write(length) };
    buffer
}

/// The body every reply-giving export shares: a null `out_len` does nothing; the work runs inside the panic
/// boundary; its bytes (or the panic's refusal) are handed out.
///
/// # Safety
/// `out_len` is null or writable.
unsafe fn answer(
    name: &str,
    out_len: *mut usize,
    abi: bool,
    work: impl FnOnce() -> Option<Vec<u8>>,
) -> *mut u8 {
    if out_len.is_null() {
        return std::ptr::null_mut();
    }
    let bytes = guarded(|| {
        tripwire(name);
        work()
    })
    .unwrap_or_else(|| Some(refused(Refusal::Panic, abi)));
    match bytes {
        // SAFETY: `out_len` is non-null (above) and the host's.
        Some(bytes) => unsafe { hand_out(bytes, out_len) },
        None => {
            // SAFETY: as above.
            unsafe { out_len.write(0) };
            std::ptr::null_mut()
        }
    }
}

/// `car_start`: `{"argv": [<text>...], "home": ..., "image": ...}` -> `{"abi": 1, "ok": ...}`. A request that is not
/// an object whose `argv` is a list of texts is `bad_request`; the empty core then answers `not_ported`.
///
/// # Safety
/// `request` points at `request_len` readable bytes (or is null with a length of 0); `out_len` is null or writable.
pub unsafe fn start(
    factory: Factory,
    request_bytes: *const u8,
    request_len: usize,
    out_len: *mut usize,
) -> *mut u8 {
    // SAFETY: the caller's promise, handed on.
    unsafe {
        answer("car_start", out_len, true, || {
            // SAFETY: the caller's promise about `request_bytes`.
            let read = request(request_bytes, request_len)
                .and_then(|bytes| json::from_slice(bytes).ok())
                .filter(start_request_holds);
            if read.is_none() {
                return Some(refused(Refusal::BadRequest, true));
            }
            // S6.1: the watcher is built here with `factory()` and the reply is `{"abi": 1, "ok": true}`.
            let _ = factory;
            Some(refused(Refusal::NotPorted, true))
        })
    }
}

fn start_request_holds(request: &Value) -> bool {
    let Value::Object(map) = request else {
        return false;
    };
    match map.get(&Str::new("argv")) {
        Some(Value::Array(words)) => words.iter().all(|word| matches!(word, Value::Str(_))),
        _ => false,
    }
}

/// `car_stop`: the in-process stop (`StopEvent.signal()`'s effect). 0 once it is signalled (the empty core has
/// nothing to stop, which is signalled at once); -1 when a panic was caught.
pub fn stop() -> i32 {
    guarded(|| {
        tripwire("car_stop");
        0
    })
    .unwrap_or(-1)
}

/// `car_bridge`: one bridge request line -> its reply, the bytes `bridge serve` writes for it. The empty core answers
/// `not_started`.
///
/// # Safety
/// As [`start`].
pub unsafe fn bridge(line: *const u8, length: usize, out_len: *mut usize) -> *mut u8 {
    // SAFETY: the caller's promise, handed on.
    unsafe {
        answer("car_bridge", out_len, false, || {
            // SAFETY: the caller's promise about `line`.
            if request(line, length).is_none() {
                return Some(refused(Refusal::BadRequest, false));
            }
            Some(refused(Refusal::NotStarted, false))
        })
    }
}

/// `car_next_event`: the next event, or NULL (and `*out_len = 0`) when none came within `timeout_ms`.
///
/// # Safety
/// `out_len` is null or writable.
pub unsafe fn next_event(timeout_ms: u32, out_len: *mut usize) -> *mut u8 {
    // SAFETY: the caller's promise, handed on.
    unsafe {
        answer("car_next_event", out_len, false, || {
            let deadline = Instant::now() + Duration::from_millis(u64::from(timeout_ms));
            let mut held = state();
            loop {
                if let Some(event) = held.events.pop_front() {
                    return Some(written(&event.to_json()));
                }
                let left = deadline.saturating_duration_since(Instant::now());
                if left.is_zero() {
                    return None;
                }
                held = QUEUED
                    .wait_timeout(held, left)
                    .unwrap_or_else(PoisonError::into_inner)
                    .0;
            }
        })
    }
}

/// `car_post_action`: one action of the closed table -> its answer. `bad_request` and `unknown_action` as
/// [`Action::parse`] says; the empty core answers every known action `not_started`.
///
/// # Safety
/// As [`start`].
pub unsafe fn post_action(request_bytes: *const u8, length: usize, out_len: *mut usize) -> *mut u8 {
    // SAFETY: the caller's promise, handed on.
    unsafe {
        answer("car_post_action", out_len, false, || {
            // SAFETY: the caller's promise about `request_bytes`.
            let Some(read) =
                request(request_bytes, length).and_then(|bytes| json::from_slice(bytes).ok())
            else {
                return Some(refused(Refusal::BadRequest, false));
            };
            match Action::parse(&read) {
                Err(refusal) => Some(refused(refusal, false)),
                Ok(_action) => Some(refused(Refusal::NotStarted, false)),
            }
        })
    }
}

/// `car_free`: takes back a reply the core handed out, with the length it was handed out with. A null pointer, one
/// the core never made, one already freed or a wrong length frees nothing.
///
/// # Safety
/// None beyond the call itself: the pointer is only compared with the replies the core recorded.
pub unsafe fn free(buffer: *mut u8, length: usize) {
    let _ = guarded(|| {
        tripwire("car_free");
        if buffer.is_null() {
            return;
        }
        let mut held = state();
        if held.live.get(&(buffer as usize)) != Some(&length) {
            return;
        }
        held.live.remove(&(buffer as usize));
        drop(held);
        let slice = std::ptr::slice_from_raw_parts_mut(buffer, length);
        // SAFETY: `buffer` and `length` are exactly a `Box<[u8]>` hand_out leaked, and it is taken back once (it left
        // the live table above, under the lock).
        drop(unsafe { Box::from_raw(slice) });
    });
}

/// The six exports of [`EXPORTS`] over one edition's [`Factory`]: the generic entry (Q3). car-host's own build is
/// `export_core!(Guarded::null)`; the other edition's host crate makes the same call with its own plug.
#[macro_export]
macro_rules! export_core {
    ($factory:expr) => {
        /// # Safety
        /// `request` points at `request_len` readable bytes (or is null with 0); `out_len` is null or writable.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn car_start(
            request: *const u8,
            request_len: usize,
            out_len: *mut usize,
        ) -> *mut u8 {
            let factory: $crate::abi::Factory = $factory;
            // SAFETY: the host's promise, handed on.
            unsafe { $crate::abi::start(factory, request, request_len, out_len) }
        }

        #[unsafe(no_mangle)]
        pub extern "C" fn car_stop() -> i32 {
            $crate::abi::stop()
        }

        /// # Safety
        /// As `car_start`.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn car_bridge(
            line: *const u8,
            len: usize,
            out_len: *mut usize,
        ) -> *mut u8 {
            // SAFETY: the host's promise, handed on.
            unsafe { $crate::abi::bridge(line, len, out_len) }
        }

        /// # Safety
        /// `out_len` is null or writable.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn car_next_event(timeout_ms: u32, out_len: *mut usize) -> *mut u8 {
            // SAFETY: the host's promise, handed on.
            unsafe { $crate::abi::next_event(timeout_ms, out_len) }
        }

        /// # Safety
        /// As `car_start`.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn car_post_action(
            request: *const u8,
            len: usize,
            out_len: *mut usize,
        ) -> *mut u8 {
            // SAFETY: the host's promise, handed on.
            unsafe { $crate::abi::post_action(request, len, out_len) }
        }

        /// # Safety
        /// None beyond the call: the pointer is only compared with the replies the core recorded.
        #[unsafe(no_mangle)]
        pub unsafe extern "C" fn car_free(buffer: *mut u8, len: usize) {
            // SAFETY: see `abi::free`.
            unsafe { $crate::abi::free(buffer, len) }
        }
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The events are process-wide: the tests that pull or queue one hold this.
    static EVENTS: Mutex<()> = Mutex::new(());

    fn events() -> MutexGuard<'static, ()> {
        EVENTS.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn null_plug() -> Guarded {
        Guarded::null()
    }

    /// The reply of one export call as text, freed once; None for a NULL reply.
    fn take(call: impl FnOnce(*mut usize) -> *mut u8) -> Option<String> {
        let mut length = usize::MAX;
        let buffer = call(&mut length);
        if buffer.is_null() {
            assert_eq!(length, 0, "a NULL reply says 0");
            return None;
        }
        assert!(is_live(buffer));
        // SAFETY: a reply of `length` bytes the core handed out.
        let text =
            String::from_utf8(unsafe { std::slice::from_raw_parts(buffer, length) }.to_vec())
                .unwrap();
        // SAFETY: handed back once with its own length.
        unsafe { free(buffer, length) };
        assert!(!is_live(buffer), "freed once is freed");
        Some(text)
    }

    fn started(request: &str) -> Option<String> {
        // SAFETY: the bytes of `request` live for the call.
        take(|out| unsafe { start(null_plug, request.as_ptr(), request.len(), out) })
    }

    fn posted(request: &str) -> Option<String> {
        // SAFETY: as above.
        take(|out| unsafe { post_action(request.as_ptr(), request.len(), out) })
    }

    #[test]
    fn start_answers_the_abi_and_the_empty_core_refuses() {
        let refused = r#"{"abi": 1, "ok": false, "error": "not_ported"}"#;
        assert_eq!(
            started(r#"{"argv": ["run"], "home": null, "image": "C:\\x"}"#).as_deref(),
            Some(refused)
        );
        assert_eq!(started(r#"{"argv": []}"#).as_deref(), Some(refused));
        let bad = r#"{"abi": 1, "ok": false, "error": "bad_request"}"#;
        for request in [
            "",
            "nope",
            "[]",
            r#"{"argv": "run"}"#,
            r#"{"argv": [1]}"#,
            r#"{"home": "x"}"#,
            "{\"argv\": [\"\u{e9}\"]",
        ] {
            assert_eq!(started(request).as_deref(), Some(bad), "{request:?}");
        }
        // Not UTF-8, and a null pointer with a length.
        let bytes = [0x7bu8, 0xff, 0x7d];
        // SAFETY: `bytes` lives for the call.
        let text = take(|out| unsafe { start(null_plug, bytes.as_ptr(), bytes.len(), out) });
        assert_eq!(text.as_deref(), Some(bad));
        // SAFETY: a null pointer is never read.
        let text = take(|out| unsafe { start(null_plug, std::ptr::null(), 5, out) });
        assert_eq!(text.as_deref(), Some(bad));
    }

    #[test]
    fn a_null_out_len_does_nothing() {
        let request = r#"{"argv": []}"#;
        // SAFETY: a null `out_len` is never written.
        let buffer = unsafe {
            start(
                null_plug,
                request.as_ptr(),
                request.len(),
                std::ptr::null_mut(),
            )
        };
        assert!(buffer.is_null());
        // SAFETY: as above.
        assert!(unsafe { next_event(0, std::ptr::null_mut()) }.is_null());
    }

    #[test]
    fn stop_bridge_and_events_on_the_empty_core() {
        assert_eq!(stop(), 0);
        let line = r#"{"id": 1, "command": "get_status"}"#;
        // SAFETY: `line` lives for the call.
        let text = take(|out| unsafe { bridge(line.as_ptr(), line.len(), out) });
        assert_eq!(
            text.as_deref(),
            Some(r#"{"ok": false, "error": "not_started"}"#)
        );
        // SAFETY: a null pointer is never read.
        let text = take(|out| unsafe { bridge(std::ptr::null(), 1, out) });
        assert_eq!(
            text.as_deref(),
            Some(r#"{"ok": false, "error": "bad_request"}"#)
        );
        let _events = events();
        let begun = Instant::now();
        // SAFETY: `out` is the test's.
        assert_eq!(take(|out| unsafe { next_event(30, out) }), None);
        assert!(
            begun.elapsed() >= Duration::from_millis(30),
            "it waited its timeout"
        );
        // SAFETY: as above.
        assert_eq!(take(|out| unsafe { next_event(0, out) }), None);
    }

    #[test]
    fn a_queued_event_is_written_in_the_tables_shape() {
        let event = Event::Ended { exit_code: 3 };
        assert_eq!(
            written(&event.to_json()),
            br#"{"kind": "ended", "exit_code": 3}"#
        );
        let surfaces = Event::Surfaces(Box::new(Surfaces {
            icon: Value::Str(Str::new("i.ico")),
            strings: Value::Object(Map::new()),
            settings: Value::Null,
            edition: Value::Str(Str::new("standard")),
            demo: Value::Str(Str::new("d")),
            locale: Value::Str(Str::new("ja")),
            letters: Value::Str(Str::new("xy")),
        }));
        assert_eq!(
            written(&surfaces.to_json()),
            br#"{"kind": "surfaces", "icon": "i.ico", "strings": {}, "settings": null, "edition": "standard", "demo": "d", "locale": "ja", "letters": "xy"}"#
        );
        assert_eq!(written(&Event::Close.to_json()), br#"{"kind": "close"}"#);
        let snapshot = Event::Snapshot {
            snapshot: Value::Object(Map::new()),
            popup: Value::Null,
        };
        assert_eq!(
            written(&snapshot.to_json()),
            br#"{"kind": "snapshot", "snapshot": {}, "popup": null}"#
        );
        let strings = Event::Strings {
            strings: Value::Object(Map::new()),
            locale: Value::Str(Str::new("ko")),
            letters: Value::Str(Str::new("ab")),
        };
        assert_eq!(
            written(&strings.to_json()),
            br#"{"kind": "strings", "strings": {}, "locale": "ko", "letters": "ab"}"#
        );
        for kind in EventKind::ALL {
            assert_eq!(EventKind::from_name(kind.name()), Some(kind));
        }
        assert_eq!(EventKind::from_name("tray_started"), None);
    }

    #[test]
    fn the_action_table_is_closed() {
        let not_started = r#"{"ok": false, "error": "not_started"}"#;
        let unknown = r#"{"ok": false, "error": "unknown_action"}"#;
        let bad = r#"{"ok": false, "error": "bad_request"}"#;
        for kind in ActionKind::ALL {
            let request = if kind == ActionKind::Popup {
                r#"{"action": "popup", "call": "list_pending", "args": []}"#.to_owned()
            } else {
                format!(r#"{{"action": "{}"}}"#, kind.name())
            };
            assert_eq!(posted(&request).as_deref(), Some(not_started), "{request}");
            assert_eq!(ActionKind::from_name(kind.name()), Some(kind));
        }
        for call in POPUP_CALLS {
            let request = format!(r#"{{"action": "popup", "call": "{call}"}}"#);
            assert_eq!(posted(&request).as_deref(), Some(not_started), "{request}");
        }
        for request in [
            r#"{"action": "send"}"#,
            r#"{"action": "Stop"}"#,
            r#"{"action": "popup"}"#,
            r#"{"action": "popup", "call": "cancel_all"}"#,
            r#"{"action": "popup", "call": 1}"#,
            r#"{"action": "surfaces"}"#,
        ] {
            assert_eq!(posted(request).as_deref(), Some(unknown), "{request}");
        }
        for request in [
            "",
            "[]",
            r#"{"action": 1}"#,
            r#"{"call": "get_status"}"#,
            "{",
        ] {
            assert_eq!(posted(request).as_deref(), Some(bad), "{request}");
        }
        let parsed = Action::parse(
            &json::from_str(r#"{"action": "open_dashboard", "page": "pending"}"#).unwrap(),
        );
        assert_eq!(
            parsed,
            Ok(Action {
                kind: ActionKind::OpenDashboard,
                fields: vec![Value::Str(Str::new("pending")), Value::Null]
            })
        );
    }

    #[test]
    fn car_free_frees_once_and_only_what_it_made() {
        let request = r#"{"argv": []}"#;
        let mut length = 0usize;
        // SAFETY: `request` lives for the call; `length` is the test's.
        let buffer = unsafe { start(null_plug, request.as_ptr(), request.len(), &mut length) };
        assert!(is_live(buffer));
        // A wrong length, a pointer inside the reply and NULL free nothing.
        // SAFETY: car_free only compares the pointer with what it recorded.
        unsafe {
            free(buffer, length + 1);
            free(buffer.wrapping_add(1), length - 1);
            free(std::ptr::null_mut(), 0);
        }
        assert!(is_live(buffer));
        // SAFETY: as above.
        unsafe { free(buffer, length) };
        assert!(!is_live(buffer));
        // A second car_free of the same buffer is nothing at all.
        // SAFETY: as above.
        unsafe { free(buffer, length) };
        assert!(!is_live(buffer));
    }

    #[test]
    fn a_panic_in_an_export_is_caught_and_answered() {
        let before = panics();
        trip("car_start");
        let text = started(r#"{"argv": []}"#);
        assert_eq!(
            text.as_deref(),
            Some(r#"{"abi": 1, "ok": false, "error": "panic"}"#)
        );
        trip("car_post_action");
        assert_eq!(
            posted(r#"{"action": "stop"}"#).as_deref(),
            Some(r#"{"ok": false, "error": "panic"}"#)
        );
        trip("car_bridge");
        let line = "{}";
        // SAFETY: `line` lives for the call.
        let text = take(|out| unsafe { bridge(line.as_ptr(), line.len(), out) });
        assert_eq!(text.as_deref(), Some(r#"{"ok": false, "error": "panic"}"#));
        trip("car_next_event");
        // SAFETY: `out` is the test's.
        let text = take(|out| unsafe { next_event(0, out) });
        assert_eq!(text.as_deref(), Some(r#"{"ok": false, "error": "panic"}"#));
        trip("car_stop");
        assert_eq!(stop(), -1);
        trip("car_free");
        // SAFETY: nothing is freed: the body panics first.
        unsafe { free(std::ptr::null_mut(), 0) };
        trip("");
        assert!(panics() >= before + 6, "every caught panic is counted");
        // And the next call runs as before.
        assert_eq!(stop(), 0);
    }

    #[test]
    fn a_queued_event_comes_out_and_wakes_a_waiting_pull() {
        let _events = events();
        let pull = std::thread::spawn(|| {
            // SAFETY: `out` is the thread's.
            take(|out| unsafe { next_event(10_000, out) })
        });
        std::thread::sleep(Duration::from_millis(50));
        let begun = Instant::now();
        queue(Event::Ended { exit_code: 0 });
        let text = pull.join().unwrap();
        assert_eq!(
            text.as_deref(),
            Some(r#"{"kind": "ended", "exit_code": 0}"#)
        );
        assert!(
            begun.elapsed() < Duration::from_secs(5),
            "the pull woke when the event came"
        );
    }
}

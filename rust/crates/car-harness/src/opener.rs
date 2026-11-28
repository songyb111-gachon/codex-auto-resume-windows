//! S6.4e: the Dashboard opener (`ui/tray/dashboard.py`, `win/handover.py`) as the port has it - car-watcher's
//! `dashboard.rs` and car-platform's `handover.rs`, their own code compiled again by `build.rs` with only the Windows
//! calls and the process start re-pointed at [`world`] - for `surface.batch`'s `opener.*` cases
//! (tests/rustdiff/diffs_ui_opener.py) and the `CODEX_AR_CORE=rust` proxy of the two openers (surfaceproxy.py).
//!
//! The world is the case's: the top-level windows `EnumWindows` would list (each one's visibility, owner, process,
//! class and the answer it gives a `WM_COPYDATA`), the program each process runs, and whether a start fails. What the
//! product does with it is recorded: the images it asked for, the processes it let come forward, every message it
//! sent (the window, the mark, the bytes), the hand-over it asked for and the process it would have started (the argv,
//! the working folder, the creation flags, the command line). Nothing is started, no window is looked at, nothing is
//! sent: the harness does not link the `windows` crate, so the copies cannot reach Windows.

use std::cell::RefCell;
use std::path::{Path, PathBuf};

use car_machine::json::{Map, Value};
use car_machine::pyval::Py;
use car_surface::py::{object, strings, text_of};

use crate::leaves::Args;

/// The stand-ins the two copies call, and what they recorded.
pub mod world {
    use super::*;

    #[derive(Clone, Default)]
    pub(super) struct Window {
        pub window: isize,
        pub pid: u32,
        pub visible: bool,
        pub owner: isize,
        pub class: String,
        pub sent: isize,
        pub answer: usize,
    }

    #[derive(Default)]
    pub(super) struct State {
        pub windows: Vec<Window>,
        pub images: Vec<(u32, Option<String>)>,
        /// The hand-over's answer when the case gives one (the proxy's ask-back); None: the product's hand-over copy.
        pub hand_over: Option<bool>,
        pub start_fails: bool,
        pub asked_images: Vec<Value>,
        pub allowed: Vec<Value>,
        pub asks: Vec<Value>,
        pub handed: Vec<Value>,
        pub started: Vec<Value>,
    }

    thread_local! {
        pub(super) static STATE: RefCell<State> = RefCell::new(State::default());
    }

    /// `crate::kernel::process_image` of handover.rs: the program the case says `pid` runs.
    pub fn process_image(pid: u32) -> Option<String> {
        STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.asked_images.push(Value::from(pid));
            state
                .images
                .iter()
                .find(|(each, _)| *each == pid)
                .and_then(|(_, image)| image.clone())
        })
    }

    /// `car_platform::handover::hand_over` as dashboard.rs calls it: recorded, then the case's answer or the product's
    /// hand-over over the case's windows.
    pub fn hand_over(exe: &str, page: Option<&str>, row: Option<&str>) -> bool {
        let answer = STATE.with(|state| {
            let mut state = state.borrow_mut();
            state.handed.push(Value::Array(vec![
                Value::from(exe),
                Value::from(page),
                Value::from(row),
            ]));
            state.hand_over
        });
        answer.unwrap_or_else(|| super::handover::hand_over(exe, page, row))
    }

    /// car-platform's `Spawn` with the working folder kept, which the real one does not show.
    pub struct Spawn {
        real: car_platform::spawn::Spawn,
        cwd: Option<PathBuf>,
    }

    impl Spawn {
        pub fn new<S: Into<String>>(argv: impl IntoIterator<Item = S>) -> Self {
            Spawn {
                real: car_platform::spawn::Spawn::new(argv),
                cwd: None,
            }
        }

        pub fn with_cwd(self, cwd: impl Into<PathBuf>) -> Self {
            let cwd = cwd.into();
            Spawn {
                real: self.real.with_cwd(cwd.clone()),
                cwd: Some(cwd),
            }
        }
    }

    /// The process start dashboard.rs makes, recorded; nothing is started.
    pub struct SystemStarter;

    impl SystemStarter {
        pub fn start_guarded(
            &self,
            spawn: &Spawn,
            _test: bool,
        ) -> Result<(), car_platform::spawn::SpawnError> {
            let fails = STATE.with(|state| {
                let mut state = state.borrow_mut();
                state.started.push(object([
                    ("argv", strings(spawn.real.argv())),
                    (
                        "cwd",
                        Value::from(
                            spawn
                                .cwd
                                .as_ref()
                                .map(|cwd| cwd.to_string_lossy().into_owned()),
                        ),
                    ),
                    ("flags", Value::from(i64::from(spawn.real.flags()))),
                    ("command_line", Value::from(spawn.real.command_line())),
                ]));
                state.start_fails
            });
            if fails {
                return Err(car_platform::spawn::SpawnError::Os(std::io::Error::other(
                    "not started",
                )));
            }
            Ok(())
        }
    }

    /// The Windows names handover.rs uses, answered from the case's windows.
    #[allow(
        non_snake_case,
        non_camel_case_types,
        clippy::upper_case_acronyms,
        clippy::missing_safety_doc,
        clippy::result_unit_err
    )]
    pub mod win {
        use super::{STATE, Value, object};
        use std::ffi::c_void;

        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct HWND(pub *mut c_void);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct LPARAM(pub isize);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct WPARAM(pub usize);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct LRESULT(pub isize);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct BOOL(pub i32);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct GET_WINDOW_CMD(pub i32);
        #[derive(Clone, Copy)]
        #[repr(transparent)]
        pub struct SEND_MESSAGE_TIMEOUT_FLAGS(pub u32);

        impl BOOL {
            pub fn as_bool(self) -> bool {
                self.0 != 0
            }
        }

        #[repr(C)]
        pub struct COPYDATASTRUCT {
            pub dwData: usize,
            pub cbData: u32,
            pub lpData: *mut c_void,
        }

        /// Windows' own numbers (WinUser.h), which handover.rs takes from the `windows` crate.
        pub const GW_OWNER: GET_WINDOW_CMD = GET_WINDOW_CMD(4);
        pub const WM_COPYDATA: u32 = 0x004A;
        pub const SMTO_ABORTIFHUNG: SEND_MESSAGE_TIMEOUT_FLAGS = SEND_MESSAGE_TIMEOUT_FLAGS(0x0002);

        type Enum = unsafe extern "system" fn(HWND, LPARAM) -> BOOL;

        fn of(window: HWND) -> Option<super::Window> {
            STATE.with(|state| {
                state
                    .borrow()
                    .windows
                    .iter()
                    .find(|each| each.window == window.0 as isize)
                    .cloned()
            })
        }

        pub unsafe fn EnumWindows(callback: Option<Enum>, lparam: LPARAM) -> Result<(), ()> {
            let listed: Vec<isize> = STATE.with(|state| {
                state
                    .borrow()
                    .windows
                    .iter()
                    .map(|each| each.window)
                    .collect()
            });
            let Some(callback) = callback else {
                return Err(());
            };
            for window in listed {
                // SAFETY: the product's own callback, given the window and the parameter it passed.
                if unsafe { callback(HWND(window as *mut c_void), lparam) }.0 == 0 {
                    break;
                }
            }
            Ok(())
        }

        pub unsafe fn IsWindowVisible(window: HWND) -> BOOL {
            BOOL(i32::from(of(window).is_some_and(|each| each.visible)))
        }

        pub unsafe fn GetWindow(window: HWND, _command: GET_WINDOW_CMD) -> Result<HWND, ()> {
            match of(window).map_or(0, |each| each.owner) {
                0 => Err(()),
                owner => Ok(HWND(owner as *mut c_void)),
            }
        }

        pub unsafe fn GetWindowThreadProcessId(window: HWND, pid: Option<&mut u32>) -> u32 {
            let found = of(window).map_or(0, |each| each.pid);
            if let Some(pid) = pid {
                *pid = found;
            }
            1
        }

        /// The class name as Windows copies it: at most the buffer less one unit, ended by a NUL; the length copied.
        pub unsafe fn GetClassNameW(window: HWND, buffer: &mut [u16]) -> i32 {
            let class: Vec<u16> = of(window)
                .map(|each| each.class)
                .unwrap_or_default()
                .encode_utf16()
                .collect();
            let room = buffer.len().saturating_sub(1);
            let length = class.len().min(room);
            buffer[..length].copy_from_slice(&class[..length]);
            if let Some(end) = buffer.get_mut(length) {
                *end = 0;
            }
            length as i32
        }

        pub unsafe fn AllowSetForegroundWindow(pid: u32) -> Result<(), ()> {
            STATE.with(|state| state.borrow_mut().allowed.push(Value::from(pid)));
            Ok(())
        }

        #[allow(clippy::too_many_arguments)]
        pub unsafe fn SendMessageTimeoutW(
            window: HWND,
            message: u32,
            wparam: WPARAM,
            lparam: LPARAM,
            flags: SEND_MESSAGE_TIMEOUT_FLAGS,
            timeout: u32,
            result: Option<&mut usize>,
        ) -> LRESULT {
            // SAFETY: the product passes a COPYDATASTRUCT that outlives the call.
            let copy = unsafe { &*(lparam.0 as *const COPYDATASTRUCT) };
            let data: Vec<u8> = if copy.lpData.is_null() {
                Vec::new()
            } else {
                // SAFETY: `cbData` bytes at `lpData`, the product's buffer.
                unsafe {
                    std::slice::from_raw_parts(copy.lpData as *const u8, copy.cbData as usize)
                }
                .to_vec()
            };
            let hex: String = data.iter().map(|byte| format!("{byte:02x}")).collect();
            let found = of(window).unwrap_or_default();
            STATE.with(|state| {
                state.borrow_mut().asks.push(object([
                    ("window", Value::from(window.0 as isize as i64)),
                    ("message", Value::from(message)),
                    ("wparam", Value::from(wparam.0 as u64)),
                    ("mark", Value::from(copy.dwData as u64)),
                    ("size", Value::from(copy.cbData)),
                    ("data", Value::from(hex)),
                    ("flags", Value::from(flags.0)),
                    ("timeout", Value::from(timeout)),
                ]))
            });
            if let Some(result) = result {
                *result = found.answer;
            }
            LRESULT(found.sent)
        }
    }
}

/// handover.rs, the product's code over [`world::win`].
#[allow(dead_code, unused_imports)]
mod handover {
    include!(concat!(env!("OUT_DIR"), "/handover.rs"));
}

/// dashboard.rs, the product's code over [`world`]'s start and hand-over.
#[allow(dead_code, unused_imports)]
mod dashboard {
    include!(concat!(env!("OUT_DIR"), "/dashboard.rs"));
}

fn int(value: Option<&Value>) -> i64 {
    match value {
        Some(Value::Int(int)) => int.as_i64().unwrap_or(0),
        Some(Value::Bool(on)) => i64::from(*on),
        _ => 0,
    }
}

fn text(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(each)) => Some(text_of(each)),
        _ => None,
    }
}

/// A case's world: `{"windows": [...], "images": [[pid, image or null], ...], "hand_over": null|bool, "start": "ok"|"oserror"}`.
fn set_world(spec: &Value) {
    let map = match spec {
        Value::Object(map) => map.clone(),
        _ => Map::new(),
    };
    let windows = match map.get("windows") {
        Some(Value::Array(each)) => each
            .iter()
            .map(|window| {
                let window = match window {
                    Value::Object(map) => map.clone(),
                    _ => Map::new(),
                };
                world::Window {
                    window: int(window.get("window")) as isize,
                    pid: int(window.get("pid")) as u32,
                    visible: matches!(window.get("visible"), Some(Value::Bool(true))),
                    owner: int(window.get("owner")) as isize,
                    class: text(window.get("class")).unwrap_or_default(),
                    sent: int(window.get("sent")) as isize,
                    answer: int(window.get("answer")) as usize,
                }
            })
            .collect(),
        _ => Vec::new(),
    };
    let images = match map.get("images") {
        Some(Value::Array(each)) => each
            .iter()
            .filter_map(|pair| match pair {
                Value::Array(pair) => Some((int(pair.first()) as u32, text(pair.get(1)))),
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    };
    let hand_over = match map.get("hand_over") {
        Some(Value::Bool(answer)) => Some(*answer),
        _ => None,
    };
    let start_fails = text(map.get("start")).is_some_and(|start| start == "oserror");
    world::STATE.with(|state| {
        *state.borrow_mut() = world::State {
            windows,
            images,
            hand_over,
            start_fails,
            ..world::State::default()
        }
    });
}

/// What the case did: its result, and everything the world recorded.
fn recorded(result: Result<bool, dashboard::ValueError>) -> Value {
    let result = match result {
        Ok(done) => object([("ok", Value::Bool(done))]),
        Err(refused) => object([
            ("error", Value::from("ValueError")),
            ("message", Value::from(refused.0)),
        ]),
    };
    world::STATE.with(|state| {
        let state = state.take();
        object([
            ("result", result),
            ("handed", Value::Array(state.handed)),
            ("images", Value::Array(state.asked_images)),
            ("allowed", Value::Array(state.allowed)),
            ("asks", Value::Array(state.asks)),
            ("started", Value::Array(state.started)),
        ])
    })
}

fn page_of(value: &Value) -> Py<Option<String>> {
    match value {
        Value::Null => Ok(None),
        Value::Str(each) => each
            .as_str()
            .map(|page| Some(page.to_owned()))
            .ok_or("TypeError"),
        _ => Err("TypeError"),
    }
}

fn refused(result: Result<String, dashboard::ValueError>) -> Value {
    match result {
        Ok(text) => object([("ok", Value::from(text))]),
        Err(refused) => object([
            ("error", Value::from("ValueError")),
            ("message", Value::from(refused.0)),
        ]),
    }
}

fn dashboard_case(a: &Args) -> Py<Value> {
    let home = a.text(0)?.to_owned();
    let page = page_of(a.get(1))?;
    let row = match a.get(2) {
        Value::Null => None,
        row => Some(row),
    };
    set_world(a.get(3));
    Ok(recorded(dashboard::open_dashboard(
        Path::new(&home),
        page.as_deref(),
        row,
    )))
}

fn chat_case(a: &Args) -> Py<Value> {
    let home = a.text(0)?.to_owned();
    set_world(a.get(2));
    Ok(recorded(dashboard::open_chat(Path::new(&home), a.get(1))))
}

fn request_text_case(a: &Args) -> Py<Value> {
    let page = page_of(a.get(0))?;
    let row = page_of(a.get(1))?;
    Ok(Value::from(handover::request_text(
        page.as_deref(),
        row.as_deref(),
    )))
}

fn windows_of_case(a: &Args) -> Py<Value> {
    let exe = a.text(0)?.to_owned();
    set_world(a.get(1));
    let found = handover::windows_of(&exe);
    let images = world::STATE.with(|state| state.take().asked_images);
    Ok(object([
        (
            "found",
            Value::Array(
                found
                    .into_iter()
                    .map(|(window, pid)| {
                        Value::Array(vec![Value::from(window as i64), Value::from(pid)])
                    })
                    .collect(),
            ),
        ),
        ("images", Value::Array(images)),
    ]))
}

/// The `opener.*` cases of `surface.batch`.
pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        "opener.dashboard" => dashboard_case(a),
        "opener.chat" => chat_case(a),
        "opener.row_argument" => Ok(refused(dashboard::row_argument(a.get(0)))),
        "opener.request_text" => request_text_case(a),
        "opener.spelled" => a.text(0).map(|path| Value::from(handover::spelled(path))),
        "opener.windows_of" => windows_of_case(a),
        "opener.consts" => Ok(Value::Array(vec![
            Value::from(handover::OPEN_REQUEST_MARK as u64),
            Value::from(handover::OPEN_REQUEST_TAKEN as u64),
            Value::from(handover::FORMS_CLASS),
            Value::from(handover::ANSWER_MILLISECONDS),
            strings(dashboard::ROW_DIALOGS.iter()),
            strings(car_machine::vocab_gen::domain_public::PAGES.iter()),
        ])),
        _ => return None,
    })
}

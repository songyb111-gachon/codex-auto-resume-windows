//! `cli.run` (seat S5.2): `codex-auto-resume.exe <argv>` - car-bin's dispatcher, the command line and plugin_setup's
//! commands - over bridgeworld's and actworld's world, with car-bin's Outside answered from it too (the registrations,
//! the engine, the watcher's mutex), every call written down in order, as `tests/rustdiff/cliworld.py` patches the tag
//! and records it. Nothing here writes the registry, makes a shortcut or starts a process.
//!
//! Request: `{"call": "cli.run", "home": H, "world": {...}, "argv": [...], "input": <hex>, "project_root": R}`.
//! Reply value: `{"output": <stdout text>, "error": <stderr text>, "code": n, "calls": [...]}`.

use std::path::Path;
use std::sync::Arc;

use car_bin::cli::{Io, Machine};
use car_bin::seam::{Backend, History, Opens, Outside, Paired, Raised, ShortcutFailure};
use car_control::host::Host;
use car_machine::json::{Map, Str, Value};

use crate::acting::Acts;
use crate::bridge::WorldHost;
use crate::{object, rejected};

/// car-bin's Outside over the world.
pub struct WorldOutside {
    acts: Arc<Acts>,
    world: Map,
}

fn text(value: &Value) -> Option<String> {
    match value {
        Value::Str(text) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

fn raised(value: &Value) -> Option<Raised> {
    let Value::Object(map) = value else {
        return None;
    };
    match map.get("raise")? {
        Value::Array(pair) => Some(Raised::new(
            &text(pair.first()?)?,
            pair.get(1).and_then(text).unwrap_or_default(),
        )),
        other => Some(Raised::new(&text(other)?, "")),
    }
}

fn opens_value(opens: &Opens) -> Value {
    object([
        ("target", Value::from(opens.target.as_str())),
        (
            "arguments",
            opens.arguments.as_deref().map_or(Value::Null, Value::from),
        ),
        (
            "icon",
            opens.icon.as_deref().map_or(Value::Null, Value::from),
        ),
        ("description", Value::from(opens.description.as_str())),
    ])
}

impl WorldOutside {
    fn get(&self, name: &str) -> Value {
        self.world.get(name).cloned().unwrap_or(Value::Null)
    }

    /// The world's answer for `name`: `{"raise": ...}`, `{"value": v}`, or the value itself; `fallback` when absent.
    fn answer(&self, name: &str, fallback: Value) -> Result<Value, Raised> {
        let found = self.get(name);
        if let Some(raised) = raised(&found) {
            return Err(raised);
        }
        Ok(match found {
            Value::Null => fallback,
            Value::Object(map) if map.contains_key("value") => {
                map.get("value").cloned().unwrap_or(Value::Null)
            }
            other => other,
        })
    }

    fn yes(&self, name: &str, fallback: bool) -> Result<bool, Raised> {
        Ok(matches!(
            self.answer(name, Value::Bool(fallback))?,
            Value::Bool(true)
        ))
    }

    fn shortcut(&self, name: &str) -> Result<bool, ShortcutFailure> {
        let found = self.get(name);
        if let Some(raised) = raised(&found) {
            return Err(if raised.class == "DesktopTaken" {
                ShortcutFailure::Taken(raised.message)
            } else {
                ShortcutFailure::Failed(raised.message)
            });
        }
        Ok(!matches!(found, Value::Bool(false)))
    }
}

impl Outside for WorldOutside {
    fn register_aumid(&self, icon: Option<&str>) -> Result<bool, Raised> {
        self.acts.call(
            "register_aumid",
            vec![icon.map_or(Value::Null, Value::from)],
        );
        self.yes("register_aumid", true)
    }
    fn unregister_aumid(&self) -> Result<bool, Raised> {
        self.acts.call("unregister_aumid", vec![]);
        self.yes("unregister_aumid", true)
    }
    fn install_protocol(&self, command: &str) -> Result<bool, Raised> {
        self.acts
            .call("install_protocol", vec![Value::from(command)]);
        self.yes("install_protocol", true)
    }
    fn uninstall_protocol(&self) -> Result<bool, Raised> {
        self.acts.call("uninstall_protocol", vec![]);
        self.yes("uninstall_protocol", true)
    }
    fn shortcut_install(&self, opens: &Opens) -> Result<bool, ShortcutFailure> {
        self.acts.call("shortcut_install", vec![opens_value(opens)]);
        self.shortcut("shortcut_install")
    }
    fn shortcut_uninstall(&self) -> bool {
        self.acts.call("shortcut_uninstall", vec![]);
        !matches!(self.get("shortcut_uninstall"), Value::Bool(false))
    }
    fn desktop_install(&self, home: &str, opens: &Opens) -> Result<bool, ShortcutFailure> {
        self.acts.call(
            "desktop_install",
            vec![Value::from(home), opens_value(opens)],
        );
        self.shortcut("desktop_install")
    }
    fn desktop_uninstall(&self, home: &str) -> Result<bool, ShortcutFailure> {
        self.acts.call("desktop_uninstall", vec![Value::from(home)]);
        self.shortcut("desktop_uninstall")
    }
    fn addremove_register(
        &self,
        home: &str,
        edition: &str,
        version: &str,
        name: &str,
    ) -> Result<(), Raised> {
        self.acts.call(
            "addremove_register",
            vec![
                Value::from(home),
                Value::from(edition),
                Value::from(version),
                Value::from(name),
            ],
        );
        self.answer("addremove_register", Value::Null).map(|_| ())
    }
    fn addremove_unregister(&self, home: &str) -> Result<bool, Raised> {
        self.acts
            .call("addremove_unregister", vec![Value::from(home)]);
        self.yes("addremove_unregister", false)
    }
    fn addremove_remove_kept(&self, home: &str) -> bool {
        self.acts
            .call("addremove_remove_kept", vec![Value::from(home)]);
        matches!(self.get("addremove_remove_kept"), Value::Bool(true))
    }
    fn watcher_mutex(
        &self,
        _state_dir: &Path,
        timeout: f64,
    ) -> Result<Box<dyn std::any::Any>, Raised> {
        self.acts.call("watcher_mutex", vec![Value::Float(timeout)]);
        match self.answer("watcher_mutex", Value::from("free"))? {
            Value::Str(word) if word.as_str() == Some("free") => Ok(Box::new(())),
            other => Err(Raised::new(
                "AdapterError",
                text(&other).unwrap_or_else(|| "mutex_busy".to_owned()),
            )),
        }
    }
    fn backend(&self, codex_exe: Option<&str>, codex_home: &str) -> Result<Backend, Raised> {
        self.acts.call(
            "backend",
            vec![
                codex_exe.map_or(Value::Null, Value::from),
                Value::from(codex_home),
            ],
        );
        let found = self.answer("backend", Value::Null)?;
        let Value::Object(map) = found else {
            return Err(Raised::new("AdapterError", "engine_discovery_not_ported"));
        };
        Ok(Backend {
            codex_exe: map.get("codex_exe").and_then(text).unwrap_or_default(),
            engine_version: map.get("engine_version").and_then(text).unwrap_or_default(),
        })
    }
    fn engine_word(&self, _state_dir: &Path, version: &str) -> Option<String> {
        self.acts.call("engine_word", vec![Value::from(version)]);
        self.answer("engine_word", Value::Null)
            .ok()
            .and_then(|value| text(&value))
    }
    fn app_paired(&self, backend: &Backend) -> Paired {
        self.acts
            .call("app_paired", vec![Value::from(backend.codex_exe.as_str())]);
        let found = self.get("app_paired");
        let Value::Object(map) = found else {
            return Paired {
                identity: None,
                looked: backend.clone(),
                app_look: "unmatched".to_owned(),
            };
        };
        let identity = match map.get("identity") {
            Some(Value::Array(pair)) if pair.len() == 2 => match (&pair[0], &pair[1]) {
                (Value::Int(a), Value::Int(b)) => {
                    Some((a.as_i64().unwrap_or(0), b.as_i64().unwrap_or(0)))
                }
                _ => None,
            },
            _ => None,
        };
        let looked = match map.get("looked") {
            Some(Value::Object(other)) => Backend {
                codex_exe: other.get("codex_exe").and_then(text).unwrap_or_default(),
                engine_version: other
                    .get("engine_version")
                    .and_then(text)
                    .unwrap_or_default(),
            },
            _ => backend.clone(),
        };
        Paired {
            identity,
            looked,
            app_look: map
                .get("app_look")
                .and_then(text)
                .unwrap_or_else(|| "unmatched".to_owned()),
        }
    }
    fn app_running_now(&self) -> Option<bool> {
        self.acts.call("app_running_now", vec![]);
        match self.get("app_running_now") {
            Value::Bool(on) => Some(on),
            _ => None,
        }
    }
    fn resource_users(&self, path: &Path) -> Option<String> {
        self.acts.call(
            "resource_users",
            vec![Value::from(path.to_string_lossy().into_owned())],
        );
        self.answer("resource_users", Value::Null)
            .err()
            .map(|raised| raised.message)
    }
    fn history(&self, _codex_home: &str, _since: f64) -> History {
        self.acts.call("history", vec![]);
        match self.get("history") {
            Value::Str(word) if word.as_str() == Some("not_yet") => History::NotYet,
            Value::Str(word) if word.as_str() == Some("readable") => History::Readable,
            Value::Str(class) => History::Failed(class.as_str().unwrap_or_default().to_owned()),
            _ => History::Readable,
        }
    }
    fn run_watcher(&self, home: &str, once: bool, poll: Option<i128>) -> i32 {
        self.acts.call(
            "run_watcher",
            vec![
                Value::from(home),
                Value::Bool(once),
                poll.map_or(Value::Null, |each| Value::from(each as i64)),
            ],
        );
        0
    }
    fn announce_cancelled(&self, thread_id: &str, open_codex: bool) {
        self.acts.call(
            "announce_cancelled",
            vec![Value::from(thread_id), Value::Bool(open_codex)],
        );
    }
    fn open_dashboard(&self, home: &str, page: &str) -> bool {
        self.acts
            .call("open_dashboard", vec![Value::from(home), Value::from(page)]);
        matches!(self.get("open_dashboard"), Value::Bool(true))
    }
    fn open_chat(&self, home: &str, thread_id: &str) -> bool {
        self.acts
            .call("open_chat", vec![Value::from(home), Value::from(thread_id)]);
        matches!(self.get("open_chat"), Value::Bool(true))
    }
    fn power_stop(&self, _home: &str, uri: &str) -> String {
        self.acts.call("power_stop", vec![Value::from(uri)]);
        text(&self.get("power_stop")).unwrap_or_else(|| "refused".to_owned())
    }
    fn doctor_live_view(
        &self,
        _state_dir: &Path,
        codex_home: &str,
        backend: &Backend,
    ) -> Result<Value, Raised> {
        self.acts.call(
            "doctor_live_view",
            vec![
                Value::from(codex_home),
                Value::from(backend.codex_exe.as_str()),
            ],
        );
        self.answer("doctor_live", Value::Null)
    }
}

/// car-bin's Machine over a world: the WorldHost (bridge.rs) and this module's WorldOutside, sharing one record.
pub fn machine_for(world: &Map, project_root: &str) -> (Machine, Arc<Acts>) {
    car_words::l10n::set_preference(None, &|_: &str| None, &Vec::new);
    let world_host = Arc::new(WorldHost::from_world(world, project_root));
    let acts = Arc::clone(&world_host.acts);
    let environ: Vec<(String, String)> = match world.get("environ") {
        Some(Value::Object(map)) => map
            .iter()
            .filter_map(|(name, value)| Some((name.as_str()?.to_owned(), text(value)?)))
            .collect(),
        _ => Vec::new(),
    };
    let host: Arc<dyn Host> = world_host;
    let machine = Machine {
        host,
        outside: Arc::new(WorldOutside {
            acts: Arc::clone(&acts),
            world: world.clone(),
        }),
        project_root: project_root.to_owned(),
        env: Arc::new(move |name: &str| {
            environ
                .iter()
                .find(|(each, _)| each.eq_ignore_ascii_case(name))
                .map(|(_, value)| value.clone())
                .or_else(|| std::env::var(name).ok())
        }),
    };
    (machine, acts)
}

fn unhex(text: &str) -> Vec<u8> {
    (0..text.len() / 2)
        .filter_map(|at| u8::from_str_radix(text.get(at * 2..at * 2 + 2)?, 16).ok())
        .collect()
}

/// `cli.run`.
pub fn run(request: &Map) -> Value {
    let world = match request.get("world") {
        Some(Value::Object(map)) => map.clone(),
        _ => return rejected("a world is required", "request_failed"),
    };
    let project_root = match request.get("project_root") {
        Some(Value::Str(root)) => root.as_str().unwrap_or_default().to_owned(),
        _ => return rejected("a project root is required", "request_failed"),
    };
    let (machine, acts) = machine_for(&world, &project_root);
    let argv: Vec<String> = match request.get("argv") {
        Some(Value::Array(items)) => items.iter().filter_map(text).collect(),
        _ => Vec::new(),
    };
    let input = match request.get("input") {
        Some(Value::Str(text)) => unhex(text.as_str().unwrap_or_default()),
        _ => Vec::new(),
    };
    let (mut out, mut err): (Vec<u8>, Vec<u8>) = (Vec::new(), Vec::new());
    let code = {
        let mut io = Io {
            out: &mut out,
            err: &mut err,
            silent: false,
        };
        let entry = match request.get("entry") {
            Some(Value::Str(text)) => text.as_str().unwrap_or_default().to_owned(),
            _ => String::new(),
        };
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            if entry == "cli" {
                match car_bin::argparse::parse_args(
                    car_bin::parsers_gen::PARSERS,
                    car_bin::parsers_gen::CLI,
                    &argv,
                ) {
                    Ok(args) => car_bin::cli::run(&machine, &args, &mut io),
                    Err(exit) => car_bin::roles::shown(exit, &mut io),
                }
            } else {
                car_bin::roles::dispatch(&machine, &[], &argv, &mut io, &mut input.as_slice())
            }
        }))
        .unwrap_or(101)
    };
    object([
        (
            "output",
            Value::Str(Str::from(String::from_utf8_lossy(&out).into_owned())),
        ),
        (
            "error",
            Value::Str(Str::from(String::from_utf8_lossy(&err).into_owned())),
        ),
        ("code", Value::from(i64::from(code))),
        ("calls", acts.calls()),
    ])
}

//! The probe `tests/rustdiff/platform_diffs.py` asks its questions of (dev only, an example, never shipped).
//!
//! JSON lines in, JSON lines out, one reply per request, framing as `car-harness serve`. A request names an `op` and
//! its arguments; the reply is `{"ok": <value>}` or `{"error": <text>}`. The probe never writes the real registry
//! (every registry op runs on `FakeRegistry`), never starts anything but through the recording starter, and never
//! acts on power (`refuse_power_actions` first). Named objects are made in the scratch home the request names.

use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};
use std::io::{BufRead, Write};
use std::path::Path;
use std::time::Duration;

use car_machine::vocab_gen::domain_vocabulary::StateAccess;
use car_platform::registry::{Call, FakeRegistry, Root, Typed, Value};
use car_platform::spawn::{Spawn, SpawnError, Starter, Stream, SystemStarter};
use car_platform::{
    acl, addremove, authenticode, cmdline, handover, homelock, inventory, kernel, names, network,
    ownprocess, paths, power, powerdown, pwsh, registry_reads, shortcut, startup, sync, typeface,
};
use serde_json::{Value as Json, json};

fn text<'a>(request: &'a Json, key: &str) -> &'a str {
    request.get(key).and_then(Json::as_str).unwrap_or("")
}

fn optional<'a>(request: &'a Json, key: &str) -> Option<&'a str> {
    request.get(key).and_then(Json::as_str)
}

fn strings(request: &Json, key: &str) -> Vec<String> {
    request
        .get(key)
        .and_then(Json::as_array)
        .map(|items| {
            items
                .iter()
                .map(|item| item.as_str().unwrap_or("").to_string())
                .collect()
        })
        .unwrap_or_default()
}

fn root_of(name: &str) -> Root {
    if name == "HKLM" {
        Root::LocalMachine
    } else {
        Root::CurrentUser
    }
}

fn value_json(value: &Value) -> Json {
    match value {
        Value::Str(text) => json!(text),
        Value::Int(number) => json!(number),
        Value::Qword(number) => json!(number),
        Value::Bytes(bytes) => json!(bytes),
    }
}

fn typed_json(typed: &Typed) -> Json {
    json!([value_json(&typed.0), typed.1])
}

fn json_value(value: &Json) -> Value {
    match value {
        Json::String(text) => Value::Str(text.clone()),
        Json::Number(number) => Value::Int(number.as_u64().unwrap_or(0) as u32),
        _ => Value::Str(String::new()),
    }
}

fn pairs(values: &[(String, Value)]) -> Json {
    Json::Object(
        values
            .iter()
            .map(|(name, value)| (name.clone(), value_json(value)))
            .collect(),
    )
}

fn calls_json(calls: &[Call]) -> Json {
    Json::Array(
        calls
            .iter()
            .map(|call| match call {
                Call::OpenKey { root, path, access } => {
                    json!(["OpenKey", root.name(), path, access])
                }
                Call::CreateKeyEx { root, path, access } => {
                    json!(["CreateKeyEx", root.name(), path, access])
                }
                Call::QueryValueEx { key, name } => json!(["QueryValueEx", key, name]),
                Call::SetValueEx {
                    key,
                    name,
                    kind,
                    value,
                } => json!(["SetValueEx", key, name, kind, value_json(value)]),
                Call::DeleteValue { key, name } => json!(["DeleteValue", key, name]),
                Call::DeleteKey { root, path } => json!(["DeleteKey", root.name(), path]),
                Call::Close { key } => json!(["Close", key]),
            })
            .collect(),
    )
}

fn store_json(registry: &FakeRegistry) -> Json {
    let mut keys = BTreeMap::new();
    for (key, values) in registry.dump() {
        let inner: BTreeMap<String, Json> = values
            .iter()
            .map(|(name, typed)| (name.clone(), typed_json(typed)))
            .collect();
        keys.insert(key, json!(inner));
    }
    json!(keys)
}

// ------------------------------------------------------------------------------------------------ registry

fn registry_scenario(request: &Json) -> Json {
    let registry = FakeRegistry::new();
    for seed in request["seed"].as_array().into_iter().flatten() {
        let values: Vec<(String, Value, u32)> = seed[2]
            .as_object()
            .into_iter()
            .flatten()
            .map(|(name, pair)| {
                (
                    name.clone(),
                    json_value(&pair[0]),
                    pair[1].as_u64().unwrap_or(1) as u32,
                )
            })
            .collect();
        let borrowed: Vec<(&str, Value, u32)> = values
            .iter()
            .map(|(n, v, k)| (n.as_str(), v.clone(), *k))
            .collect();
        registry.seed(
            root_of(seed[0].as_str().unwrap_or("HKCU")),
            seed[1].as_str().unwrap_or(""),
            &borrowed,
        );
    }
    for deny in request["deny_keys"].as_array().into_iter().flatten() {
        registry.deny_key(
            root_of(deny[0].as_str().unwrap_or("HKCU")),
            deny[1].as_str().unwrap_or(""),
        );
    }
    for deny in request["deny_values"].as_array().into_iter().flatten() {
        registry.deny_value(
            root_of(deny[0].as_str().unwrap_or("HKCU")),
            deny[1].as_str().unwrap_or(""),
            deny[2].as_str().unwrap_or(""),
        );
    }
    let mut results = Vec::new();
    for step in request["steps"].as_array().into_iter().flatten() {
        results.push(registry_step(
            &registry,
            &strings(request, "editions"),
            step,
        ));
    }
    json!({"results": results, "calls": calls_json(&registry.calls()), "store": store_json(&registry)})
}

fn startup_result<T>(
    outcome: Result<T, startup::StartupError>,
    ok: impl FnOnce(T) -> Json,
) -> Json {
    match outcome {
        Ok(value) => ok(value),
        Err(error) => json!({"error": error.0}),
    }
}

fn registry_step(registry: &FakeRegistry, editions: &[String], step: &Json) -> Json {
    let op = step[0].as_str().unwrap_or("");
    let arg = |index: usize| step[index].as_str().unwrap_or("");
    match op {
        "install" => startup_result(startup::install(registry, arg(1)), |done| json!(done)),
        "uninstall" => startup_result(startup::uninstall(registry), |done| json!(done)),
        "current_value" => startup_result(startup::current_value(registry), |value| json!(value)),
        "aumid_registration" => startup_result(startup::aumid_registration(registry), |found| {
            json!(found.map(|values| values.into_iter().collect::<BTreeMap<_, _>>()))
        }),
        "register_aumid" => {
            let icon = step[1].as_str().map(Path::new);
            startup_result(startup::register_aumid(registry, icon), |done| json!(done))
        }
        "notification_identity_owner" => startup_result(
            startup::notification_identity_owner(registry, arg(1)),
            |owner| json!(owner),
        ),
        "unregister_aumid" => json!(startup::unregister_aumid(registry)),
        "protocol_value" => startup_result(startup::protocol_value(registry), |value| json!(value)),
        "install_protocol" => startup_result(startup::install_protocol(registry, arg(1)), |done| {
            json!(done)
        }),
        "uninstall_protocol" => json!(startup::uninstall_protocol(registry)),
        "read_key" => {
            let names: Vec<String> = step[2]
                .as_array()
                .into_iter()
                .flatten()
                .map(|n| n.as_str().unwrap_or("").to_string())
                .collect();
            let borrowed: Vec<&str> = names.iter().map(String::as_str).collect();
            startup_result(startup::read_key(registry, arg(1), &borrowed), |found| {
                json!(found.map(|values| pairs(&values)))
            })
        }
        "write_key" => {
            let values: Vec<(String, Value)> = step[2]
                .as_object()
                .into_iter()
                .flatten()
                .map(|(name, value)| (name.clone(), json_value(value)))
                .collect();
            startup_result(startup::write_key(registry, arg(1), &values), |()| {
                Json::Null
            })
        }
        "delete_key" => startup_result(startup::delete_key(registry, arg(1)), |done| json!(done)),
        "ar_register" => startup_result(
            addremove::register(
                registry,
                Path::new(arg(1)),
                arg(2),
                &editions.iter().map(String::as_str).collect::<Vec<_>>(),
                arg(3),
                step[4].as_str(),
            ),
            |done| json!(done),
        ),
        "ar_unregister" => {
            let all: Vec<&str> = editions.iter().map(String::as_str).collect();
            startup_result(
                addremove::unregister(registry, Path::new(arg(1)), &all),
                |done| json!(done),
            )
        }
        "ar_remove_edition" => startup_result(
            addremove::remove_edition(registry, arg(1), Path::new(arg(2))),
            |done| json!(done),
        ),
        "ar_read" => startup_result(addremove::read(registry, arg(1)), |found| {
            json!(found.map(|values| pairs(&values)))
        }),
        "policy_read" => {
            let places = registry_reads::read_policies(registry);
            Json::Array(
                places
                    .iter()
                    .map(|place| {
                        Json::Object(
                            place
                                .iter()
                                .map(|(name, value)| {
                                    let shown = match value {
                                        registry_reads::PolicyValue::Data(typed) => {
                                            typed_json(typed)
                                        }
                                        registry_reads::PolicyValue::Unreadable => {
                                            json!([null, -1])
                                        }
                                    };
                                    (name.clone(), shown)
                                })
                                .collect(),
                        )
                    })
                    .collect(),
            )
        }
        "codex_home" => json!(registry_reads::codex_home(registry)),
        "text_size" => json!(registry_reads::text_size(registry)),
        other => json!({"error": format!("unknown step {other}")}),
    }
}

// --------------------------------------------------------------------------------------------- the starter

/// A starter that starts nothing: it records what it was asked to run, and writes the shortcut a script would.
struct Recording {
    runs: RefCell<Vec<Json>>,
    reader_code: i32,
    maker_code: i32,
}

impl Starter for Recording {
    fn run(&self, spawn: &Spawn, timeout: Duration) -> Result<i32, SpawnError> {
        let args: BTreeMap<String, String> = spawn
            .env()
            .into_iter()
            .flatten()
            .filter(|(name, _)| {
                name.to_string_lossy()
                    .to_uppercase()
                    .starts_with(pwsh::PREFIX)
            })
            .map(|(name, value)| {
                (
                    name.to_string_lossy().into_owned(),
                    value.to_string_lossy().into_owned(),
                )
            })
            .collect();
        let script = spawn.argv().get(4).cloned().unwrap_or_default();
        let is_maker = script == shortcut::maker();
        self.runs.borrow_mut().push(json!({
            "argv": spawn.argv(),
            "command_line": spawn.command_line(),
            "args": args,
            "flags": spawn.flags(),
            "timeout": timeout.as_secs_f64(),
            "maker": is_maker,
        }));
        if is_maker {
            if self.maker_code == 0
                && let Some(lnk) = args.get("CODEX_AUTO_RESUME_ARG_LNK")
            {
                let _ = std::fs::write(lnk, b"lnk");
            }
            return Ok(self.maker_code);
        }
        Ok(self.reader_code)
    }
}

fn shortcut_result<T>(
    outcome: Result<T, shortcut::ShortcutError>,
    ok: impl FnOnce(T) -> Json,
) -> Json {
    match outcome {
        Ok(value) => ok(value),
        Err(error) => {
            json!({"error": error.reason(), "taken": error == shortcut::ShortcutError::DesktopTaken})
        }
    }
}

fn shortcut_scenario(request: &Json) -> Json {
    let starter = Recording {
        runs: RefCell::new(Vec::new()),
        reader_code: request["reader_code"].as_i64().unwrap_or(0) as i32,
        maker_code: request["maker_code"].as_i64().unwrap_or(0) as i32,
    };
    let mut results = Vec::new();
    for step in request["steps"].as_array().into_iter().flatten() {
        let op = step[0].as_str().unwrap_or("");
        let arg = |index: usize| step[index].as_str().unwrap_or("");
        results.push(match op {
            "install" => shortcut_result(
                shortcut::install(
                    &starter,
                    Path::new(arg(1)),
                    arg(2),
                    step[3].as_str().map(Path::new),
                    step[4].as_str(),
                    arg(5),
                ),
                |done| json!(done),
            ),
            "install_desktop" => shortcut_result(
                shortcut::install_desktop(
                    &starter,
                    Path::new(arg(1)),
                    Path::new(arg(2)),
                    arg(3),
                    step[4].as_str().map(Path::new),
                    step[5].as_str(),
                    arg(6),
                ),
                |done| json!(done),
            ),
            "uninstall_desktop" => shortcut_result(
                shortcut::uninstall_desktop(&starter, Path::new(arg(1))),
                |done| json!(done),
            ),
            "uninstall" => json!(shortcut::uninstall()),
            "shortcut_path" => json!(shortcut::shortcut_path().to_string_lossy()),
            "desktop_path" => {
                json!(shortcut::desktop_path().map(|p| p.to_string_lossy().into_owned()))
            }
            _ => json!({"error": "unknown step"}),
        });
    }
    json!({"results": results, "runs": *starter.runs.borrow()})
}

fn pwsh_scenario(request: &Json) -> Json {
    let starter = Recording {
        runs: RefCell::new(Vec::new()),
        reader_code: 7,
        maker_code: 0,
    };
    let values: Vec<(String, Option<String>)> = request["values"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|pair| {
            (
                pair[0].as_str().unwrap_or("").to_string(),
                pair[1].as_str().map(str::to_string),
            )
        })
        .collect();
    let borrowed: Vec<(&str, Option<&str>)> = values
        .iter()
        .map(|(n, v)| (n.as_str(), v.as_deref()))
        .collect();
    let outcome = pwsh::run(
        &starter,
        text(request, "script"),
        &borrowed,
        Duration::from_secs(request["timeout"].as_u64().unwrap_or(30)),
    );
    let shown = match outcome {
        Ok(code) => json!({"code": code}),
        Err(pwsh::RunError::PowerShell(error)) => json!({"error": error.0}),
        Err(pwsh::RunError::Spawn(error)) => json!({"error": error.to_string()}),
    };
    json!({"outcome": shown, "runs": *starter.runs.borrow(), "executable": pwsh::executable().map(|p| p.to_string_lossy().into_owned())})
}

// ---------------------------------------------------------------------------------------------- the rest

fn host_table(rows: &Json) -> HashMap<u32, kernel::HostRow> {
    rows.as_array()
        .into_iter()
        .flatten()
        .map(|row| {
            (
                row[0].as_u64().unwrap_or(0) as u32,
                (
                    row[1].as_u64().unwrap_or(0) as u32,
                    row[2].as_u64().unwrap_or(0),
                    row[3].as_str().map(str::to_string),
                ),
            )
        })
        .collect()
}

fn verdict_json(verdict: &kernel::HostVerdict) -> Json {
    json!({"state": verdict.state, "family": verdict.family, "app": verdict.app})
}

fn entries(request: &Json, key: &str) -> Vec<acl::Entry> {
    request[key]
        .as_array()
        .into_iter()
        .flatten()
        .map(|pair| {
            (
                pair[0].as_str().unwrap_or("").to_string(),
                pair[1].as_u64().unwrap_or(0) as u32,
            )
        })
        .collect()
}

fn access_text(access: StateAccess) -> &'static str {
    access.as_str()
}

fn handle(request: &Json) -> Result<Json, String> {
    let op = text(request, "op");
    Ok(match op {
        "names" => {
            // The environment the reference's Path.home() reads, then everything derived from it.
            // SAFETY: the probe is single-threaded; nothing reads the environment concurrently.
            unsafe {
                std::env::set_var("USERPROFILE", text(request, "userprofile"));
                if let Some(local) = optional(request, "localappdata") {
                    std::env::set_var("LOCALAPPDATA", local);
                }
            }
            let state = text(request, "state");
            let watcher = names::watcher_names(state).ok_or("no home")?;
            let lock =
                names::home_lock_path(text(request, "codex_home"), optional(request, "base"));
            json!({
                "identity": paths::home_identity(),
                "mutex": watcher.mutex, "stop": watcher.stop, "wake": watcher.wake, "demo": watcher.demo,
                "install_lock": names::INSTALL_LOCK,
                "home_lock": lock.map(|p| p.to_string_lossy().into_owned()),
                "lock_root": names::lock_root(optional(request, "base")),
                "folder_identity": homelock::folder_identity(Path::new(text(request, "codex_home"))),
            })
        }
        "normcase" => json!(paths::normcase(text(request, "text"))),
        "realpath" => json!(paths::realpath(&paths::pathlib_text(text(request, "text")))),
        "sha256" => json!(paths::sha256_hex(text(request, "text").as_bytes())),
        "list2cmdline" => json!(cmdline::list2cmdline(&strings(request, "args"))),
        "quote_argument" => json!(cmdline::quote_argument(text(request, "value"))),
        "parse_command" => json!(cmdline::parse_command(text(request, "command"))),
        "script_index" => json!(cmdline::script_index(&strings(request, "args"))),
        "command_line" => {
            let options: Vec<String> = strings(request, "options");
            let borrowed: Vec<&str> = options.iter().map(String::as_str).collect();
            json!(startup::command_line(
                Path::new(text(request, "entry")),
                optional(request, "home").map(Path::new),
                text(request, "launcher"),
                &borrowed
            ))
        }
        "protocol_command_line" => {
            let options: Vec<String> = strings(request, "options");
            let borrowed: Vec<&str> = options.iter().map(String::as_str).collect();
            json!(startup::protocol_command_line(
                Path::new(text(request, "entry")),
                Path::new(text(request, "home")),
                text(request, "launcher"),
                &borrowed
            ))
        }
        "belongs_to" => json!(startup::belongs_to(
            text(request, "command"),
            text(request, "home")
        )),
        "uninstall_command" => json!(addremove::uninstall_command(
            Path::new(text(request, "home")),
            request["silent"].as_bool().unwrap_or(false)
        )),
        "display_name" => json!(addremove::display_name(Path::new(text(request, "path")))),
        "registry" => registry_scenario(request),
        "hive_policy" => hive_policy(request)?,
        "shortcut" => shortcut_scenario(request),
        "pwsh" => pwsh_scenario(request),
        "pwsh_names" => {
            let values = request["names"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|n| n.as_str().unwrap_or("").to_string());
            Json::Array(
                values
                    .map(|name| match pwsh::reference(&name) {
                        Ok(text) => json!(text),
                        Err(error) => json!({"error": error.0}),
                    })
                    .collect(),
            )
        }
        "script_argv" => json!(pwsh::script_argv(
            text(request, "shell"),
            text(request, "script")
        )),
        "scripts" => json!({"maker": shortcut::maker(), "reader": shortcut::READER}),
        "constants" => json!({
            "no_window": car_platform::spawn::CREATE_NO_WINDOW,
            "breakaway": car_platform::spawn::CREATE_BREAKAWAY_FROM_JOB,
            "job": [kernel::JOB_BREAKAWAY_OK, kernel::JOB_SILENT_BREAKAWAY_OK, kernel::JOB_KILL_ON_CLOSE],
            "appmodel": kernel::APPMODEL_ERROR_NO_PACKAGE,
        }),
        "spawn_flags" => {
            let spawn = Spawn::new(strings(request, "argv"))
                .with_flags(request["extra"].as_u64().unwrap_or(0) as u32);
            json!({"flags": spawn.flags(), "command_line": spawn.command_line()})
        }
        // pure kernel helpers
        "decide_host" => json!(kernel::decide_host(
            request["start"].as_u64().unwrap_or(0) as u32,
            &host_table(&request["table"])
        )),
        "host_verdict" => json!(verdict_json(&kernel::host_verdict(
            request["start"].as_u64().unwrap_or(0) as u32,
            &host_table(&request["table"]),
            request["started_by"].as_f64()
        ))),
        "app_name" => json!(kernel::app_name(optional(request, "family"))),
        "trusted_owner" => json!(kernel::trusted_owner(
            optional(request, "owner"),
            optional(request, "user")
        )),
        // acl
        "acl_verdict" => {
            let allowed = entries(request, "allowed");
            let sandbox = request["sandbox"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|s| s.as_str().unwrap_or("").to_string())
                .collect();
            let given = if request["allowed"].is_null() {
                None
            } else {
                Some(allowed.as_slice())
            };
            json!(access_text(acl::verdict(
                given,
                optional(request, "own"),
                &sandbox
            )))
        }
        "is_sandbox_group" => json!(acl::is_sandbox_group(
            text(request, "name"),
            text(request, "domain"),
            request["kind"].as_i64().unwrap_or(0) as i32,
            text(request, "computer")
        )),
        "described_entries" => json!(acl::described_entries(text(request, "sddl"))),
        "sandbox_sids" => {
            let given = entries(request, "entries");
            let table: HashMap<String, acl::Account> = request["accounts"]
                .as_object()
                .into_iter()
                .flatten()
                .map(|(sid, row)| {
                    (
                        sid.clone(),
                        (
                            row[0].as_str().unwrap_or("").to_string(),
                            row[1].as_str().unwrap_or("").to_string(),
                            row[2].as_i64().unwrap_or(0) as i32,
                        ),
                    )
                })
                .collect();
            let found = acl::sandbox_sids_with(
                &given,
                &|sid| table.get(sid).cloned(),
                Some(text(request, "computer")),
            );
            json!(found)
        }
        "state_access" => json!(access_text(acl::state_access(Path::new(text(
            request, "path"
        ))))),
        "allowed_sids" => json!(acl::allowed_sids(Path::new(text(request, "path")))),
        // authenticode
        "auth_reason" => json!(authenticode::reason(
            request["status"].as_i64().unwrap_or(0)
        )),
        "signer" => match authenticode::signer(Path::new(text(request, "path"))) {
            Ok(name) => json!({"ok": name}),
            Err(error) => json!({"error": error.0}),
        },
        // typeface
        "letters" => json!(typeface::letters(&strings(request, "texts"))),
        "face_for" => {
            let lacking: HashMap<String, String> = request["lacks"]
                .as_object()
                .into_iter()
                .flatten()
                .map(|(face, chars)| (face.clone(), chars.as_str().unwrap_or("").to_string()))
                .collect();
            let lacks = |face: &str, text: &str| -> String {
                let own = lacking.get(face).cloned().unwrap_or_default();
                text.chars().filter(|c| own.contains(*c)).collect()
            };
            json!(typeface::face_for(
                text(request, "face"),
                text(request, "text"),
                &lacks
            ))
        }
        "language_face" => {
            let lacking: HashMap<String, String> = request["lacks"]
                .as_object()
                .into_iter()
                .flatten()
                .map(|(face, chars)| (face.clone(), chars.as_str().unwrap_or("").to_string()))
                .collect();
            let installed: Vec<String> = strings(request, "installed");
            let lacks = |face: &str, text: &str| -> String {
                let own = lacking.get(face).cloned().unwrap_or_default();
                text.chars().filter(|c| own.contains(*c)).collect()
            };
            json!(typeface::language_face(
                optional(request, "locale"),
                text(request, "face"),
                text(request, "text"),
                &lacks,
                &|face| installed.iter().any(|i| i == face)
            ))
        }
        "typeface_live" => json!({
            "installed": strings(request, "faces").iter().map(|f| typeface::installed(f)).collect::<Vec<_>>(),
            "lacks": request["pairs"].as_array().into_iter().flatten().map(|p| typeface::lacks(p[0].as_str().unwrap_or(""), p[1].as_str().unwrap_or(""))).collect::<Vec<_>>(),
            "ui_face": typeface::ui_face(),
        }),
        // live, read only
        "live" => {
            powerdown::refuse_power_actions();
            let context = kernel::process_context();
            let available: Vec<Json> = ["sleep", "hibernate", "shut_down", "nonsense"]
                .iter()
                .map(|action| {
                    let (ok, why) = powerdown::available(action);
                    json!([ok, why])
                })
                .collect();
            json!({
                "internet": network::internet(), "connectivity": network::connectivity(),
                "sign_in": ownprocess::sign_in(), "memory_known": ownprocess::memory().is_some(),
                "awake": power::awake_seconds(), "mains": power::on_mains(),
                "idle": powerdown::idle_seconds(), "sessions": powerdown::other_sessions(),
                "privilege": powerdown::holds_shutdown_privilege(),
                "available": available,
                "install_in_progress": homelock::install_in_progress(),
                "rm_available": inventory::restart_manager_available(),
                "context": {"in_job": context.in_job, "kill_on_close": context.kill_on_close, "breakaway_ok": context.breakaway_ok, "silent_breakaway_ok": context.silent_breakaway_ok, "packaged": context.packaged},
                "act_refused": !powerdown::act("sleep") && !powerdown::act("shut_down"),
                "booted_at": ownprocess::booted_at(),
            })
        }
        // Start a program through the one starter, with its output piped back: what the child saw, and the creation
        // flags the starter applied.
        "echo" => {
            let spawn = Spawn::new(strings(request, "argv")).with_streams(
                Stream::Null,
                Stream::Piped,
                Stream::Null,
            );
            let child = SystemStarter.start(&spawn).map_err(|e| e.to_string())?;
            let output = child.wait_with_output().map_err(|e| e.to_string())?;
            json!({
                "stdout": String::from_utf8_lossy(&output.stdout),
                "code": output.status.code(),
                "flags": car_platform::spawn::last_started_flags(),
            })
        }
        "pid" => json!(std::process::id()),
        "process_identity" => {
            match kernel::process_identity(request["pid"].as_u64().unwrap_or(0) as u32) {
                Ok(found) => {
                    json!({"pid": found.pid, "path": found.path, "created": found.created})
                }
                Err(error) => json!({"error": error.0}),
            }
        }
        "processes_named" => {
            let names = strings(request, "names");
            let families = strings(request, "families");
            let borrowed: Vec<&str> = names.iter().map(String::as_str).collect();
            let fam: Vec<&str> = families.iter().map(String::as_str).collect();
            match kernel::processes_named(&borrowed, &fam) {
                Ok(found) => json!(found.iter().map(|p| json!({"pid": p.pid, "parent": p.parent, "path": p.path, "created": p.created, "family": p.family})).collect::<Vec<_>>()),
                Err(error) => json!({"error": error.0}),
            }
        }
        "running_images" => json!(kernel::running_images().map(|mut images| {
            images.sort();
            images.dedup();
            images
        })),
        "host_app" => json!(verdict_json(&kernel::host_app(
            request["pid"].as_u64().map(|p| p as u32),
            request["started_by"].as_f64()
        ))),
        "resource_users" => {
            let given = strings(request, "paths");
            let borrowed: Vec<&str> = given.iter().map(String::as_str).collect();
            match inventory::resource_users(&borrowed) {
                Ok(found) => json!(
                    found
                        .iter()
                        .map(|h| json!({"pid": h.pid, "created": h.created}))
                        .collect::<Vec<_>>()
                ),
                Err(error) => json!({"error": error.0}),
            }
        }
        "windows_of" => json!(handover::windows_of(text(request, "exe"))),
        "spelled" => json!(handover::spelled(text(request, "path"))),
        "request_text" => json!(handover::request_text(
            optional(request, "page"),
            optional(request, "row")
        )),
        // named objects: held across requests, so another process can be asked about them
        "hold" => return hold(request),
        other => return Err(format!("unknown op {other}")),
    })
}

thread_local! {
    static MUTEXES: RefCell<Vec<sync::Mutex>> = const { RefCell::new(Vec::new()) };
    static STOPS: RefCell<Vec<sync::StopEvent>> = const { RefCell::new(Vec::new()) };
    static WAKES: RefCell<Vec<sync::WakeEvent>> = const { RefCell::new(Vec::new()) };
    static DEMOS: RefCell<Vec<sync::DemoEvent>> = const { RefCell::new(Vec::new()) };
    static LOCKS: RefCell<Vec<homelock::HomeLock>> = const { RefCell::new(Vec::new()) };
}

fn error_code<E: std::fmt::Display>(outcome: Result<(), E>) -> Json {
    match outcome {
        Ok(()) => json!({"ok": true}),
        Err(error) => json!({"error": error.to_string()}),
    }
}

/// `hold`: make a named object here and keep it until `release`; or signal / wait / try one made elsewhere.
fn hold(request: &Json) -> Result<Json, String> {
    // SAFETY: single-threaded probe.
    unsafe {
        std::env::set_var("USERPROFILE", text(request, "userprofile"));
    }
    let name = text(request, "name");
    let timeout = request["timeout"].as_f64().unwrap_or(0.0);
    Ok(match text(request, "kind") {
        "mutex" => match text(request, "action") {
            "take" => {
                let mut mutex = sync::Mutex::new(name, timeout).map_err(|e| e.to_string())?;
                let outcome = mutex.enter();
                let abandoned = mutex.abandoned;
                if outcome.is_ok() {
                    MUTEXES.with(|held| held.borrow_mut().push(mutex));
                }
                json!({"result": error_code(outcome), "abandoned": abandoned})
            }
            _ => {
                MUTEXES.with(|held| held.borrow_mut().clear());
                json!({"result": {"ok": true}})
            }
        },
        "stop" | "wake" | "demo" => {
            let kind = text(request, "kind").to_string();
            match text(request, "action") {
                "create" => {
                    let outcome = match kind.as_str() {
                        "stop" => {
                            let mut event =
                                sync::StopEvent::new(name).map_err(|e| e.to_string())?;
                            let outcome = event.enter();
                            STOPS.with(|held| held.borrow_mut().push(event));
                            outcome
                        }
                        "wake" => {
                            let mut event =
                                sync::WakeEvent::new(name).map_err(|e| e.to_string())?;
                            let outcome = event.enter();
                            WAKES.with(|held| held.borrow_mut().push(event));
                            outcome
                        }
                        _ => {
                            let mut event =
                                sync::DemoEvent::new(name).map_err(|e| e.to_string())?;
                            let outcome = event.enter();
                            DEMOS.with(|held| held.borrow_mut().push(event));
                            outcome
                        }
                    };
                    json!({"result": error_code(outcome)})
                }
                "signal" => {
                    let done = match kind.as_str() {
                        "stop" => sync::StopEvent::new(name)
                            .map_err(|e| e.to_string())?
                            .signal(),
                        "wake" => sync::WakeEvent::new(name)
                            .map_err(|e| e.to_string())?
                            .signal(),
                        _ => sync::DemoEvent::new(name)
                            .map_err(|e| e.to_string())?
                            .signal(),
                    };
                    json!({"signalled": done})
                }
                "wait" => {
                    let seconds = request["seconds"].as_f64().unwrap_or(1.0);
                    let got = match kind.as_str() {
                        "stop" => STOPS.with(|held| {
                            held.borrow()
                                .first()
                                .is_some_and(|event| event.wait(seconds))
                        }),
                        "wake" => WAKES.with(|held| {
                            sync::wait_any(
                                &[held.borrow().first().and_then(|event| event.raw())],
                                seconds,
                            )
                            .is_some()
                        }),
                        _ => DEMOS
                            .with(|held| held.borrow().first().is_some_and(|event| event.taken())),
                    };
                    json!({"got": got})
                }
                _ => {
                    STOPS.with(|held| held.borrow_mut().clear());
                    WAKES.with(|held| held.borrow_mut().clear());
                    DEMOS.with(|held| held.borrow_mut().clear());
                    json!({"result": {"ok": true}})
                }
            }
        }
        "homelock" => match text(request, "action") {
            "take" => {
                let mut lock = homelock::HomeLock::new(
                    text(request, "codex_home"),
                    optional(request, "base"),
                    request["require_identity"].as_bool().unwrap_or(false),
                )
                .map_err(|e| e.to_string())?;
                let outcome = lock.enter();
                let identity = lock.identity.clone();
                if outcome.is_ok() {
                    LOCKS.with(|held| held.borrow_mut().push(lock));
                }
                json!({"result": error_code(outcome), "identity": identity})
            }
            _ => {
                LOCKS.with(|held| held.borrow_mut().clear());
                json!({"result": {"ok": true}})
            }
        },
        other => return Err(format!("unknown hold kind {other}")),
    })
}

/// The policy values of a private hive (a scratch file, RegLoadAppKey; never HKCU or HKLM) read by the real reader
/// (`WinRegistry` over the hive for both roots): each value as `query` gives it, and `policy_places` - what
/// `policykeys.read()` hands `managed.parse`.
fn hive_policy(request: &Json) -> Result<Json, String> {
    use car_platform::registry::{KEY_READ, PrivateHive};
    let hive = PrivateHive::load(Path::new(text(request, "hive"))).ok_or("the hive did not load")?;
    let registry = hive.registry();
    let mut raw = serde_json::Map::new();
    if let Ok(key) = car_platform::registry::Open::read(
        &registry,
        Root::LocalMachine,
        registry_reads::POLICY_KEY,
        KEY_READ,
    ) {
        for name in registry_reads::POLICY_NAMES {
            raw.insert(
                name.to_string(),
                match key.query(name) {
                    Ok(typed) => typed_json(&typed),
                    Err(error) => json!({"error": format!("{error:?}")}),
                },
            );
        }
    }
    let places: Vec<Json> = registry_reads::policy_places(&registry)
        .iter()
        .map(|place| {
            let written = car_machine::json::to_string(place, &car_machine::json::Options::new())
                .unwrap_or_default();
            serde_json::from_str(&written).unwrap_or(Json::Null)
        })
        .collect();
    Ok(json!({"raw": raw, "places": places}))
}

fn main() {
    powerdown::refuse_power_actions();
    let stdin = std::io::stdin();
    let mut out = std::io::stdout().lock();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let reply = match serde_json::from_str::<Json>(&line) {
            Ok(request) => match std::panic::catch_unwind(|| handle(&request)) {
                Ok(Ok(value)) => json!({"ok": value}),
                Ok(Err(error)) => json!({"error": error}),
                Err(_) => json!({"error": "panic"}),
            },
            Err(error) => json!({"error": error.to_string()}),
        };
        let _ = writeln!(out, "{reply}");
        let _ = out.flush();
    }
}

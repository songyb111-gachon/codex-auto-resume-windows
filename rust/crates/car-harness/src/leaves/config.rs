//! car-config's calls: `Paths`, the project root and version, Codex discovery and the log.

use car_config::codex;
use car_config::logbook::{self, Clock, Logbook};
use car_config::paths::{self, Paths};
use car_config::{ConfigError, Os};
use car_machine::json::{Map, Str, Value};
use car_machine::pytext::py_str;
use car_machine::pyval::Py;

use super::Args;

fn object(pairs: Vec<(&str, Value)>) -> Value {
    let mut map = Map::new();
    for (key, value) in pairs {
        map.insert(Str::from(key), value);
    }
    Value::Object(map)
}

fn strings(items: &[String]) -> Value {
    Value::Array(
        items
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect(),
    )
}

fn config_error(error: ConfigError) -> Value {
    object(vec![("config_error", Value::from(error.0))])
}

/// `{name: text}` as an environment lookup.
fn environment(value: &Value) -> impl Fn(&str) -> Option<String> {
    let rows: Vec<(String, String)> = match value {
        Value::Object(map) => map
            .iter()
            .map(|(name, each)| {
                (
                    String::from_utf8_lossy(name.as_bytes()).into_owned(),
                    py_str(each),
                )
            })
            .collect(),
        _ => Vec::new(),
    };
    move |name: &str| {
        rows.iter()
            .find(|(each, _)| each.eq_ignore_ascii_case(name))
            .map(|(_, text)| text.clone())
    }
}

fn optional(value: &Value) -> Option<&str> {
    match value {
        Value::Str(text) => text.as_str(),
        _ => None,
    }
}

fn os_of(cwd: &Value, long_paths: &Value) -> Os {
    Os {
        cwd: optional(cwd).unwrap_or("C:\\").to_owned(),
        long_paths: matches!(long_paths, Value::Bool(true)),
        links: crate::links::for_config(),
    }
}

fn fields(paths: &Paths) -> Value {
    object(vec![
        ("home", Value::from(paths.home.as_str())),
        ("state_dir", Value::from(paths.state_dir.as_str())),
        ("logs_dir", Value::from(paths.logs_dir.as_str())),
        ("settings_file", Value::from(paths.settings_file.as_str())),
        (
            "compat_report_file",
            Value::from(paths.compat_report_file.as_str()),
        ),
        (
            "compat_cache_file",
            Value::from(paths.compat_cache_file.as_str()),
        ),
        (
            "failure_seen_file",
            Value::from(paths.failure_seen_file.as_str()),
        ),
        ("status_file", Value::from(paths.status_file.as_str())),
        (
            "self_check_file",
            Value::from(paths.self_check_file.as_str()),
        ),
        (
            "split_chains_file",
            Value::from(paths.split_chains_file.as_str()),
        ),
        (
            "codex_layout_file",
            Value::from(paths.codex_layout_file.as_str()),
        ),
        (
            "power_action_file",
            Value::from(paths.power_action_file.as_str()),
        ),
        (
            "once_words_file",
            Value::from(paths.once_words_file.as_str()),
        ),
        (
            "edition_left_file",
            Value::from(paths.edition_left_file.as_str()),
        ),
        ("advanced_dir", Value::from(paths.advanced_dir.as_str())),
        ("accounts_dir", Value::from(paths.accounts_dir.as_str())),
        ("log_file", Value::from(paths.log_file.as_str())),
        ("error_log", Value::from(paths.error_log.as_str())),
        (
            "codex_start_log",
            Value::from(paths.codex_start_log.as_str()),
        ),
        ("entry_script", Value::from(paths.entry_script.as_str())),
        ("icon_file", Value::from(paths.icon_file.as_str())),
    ])
}

/// What an uninstall may take, and what `Paths` says it owns, as one comparable answer.
fn report(paths: &Paths, extra: &Value) -> Value {
    let by_depth = |dirs: Vec<String>| {
        // The Python's order among folders of one depth is a set's: group them, sort inside a group.
        let mut groups: Vec<(usize, Vec<String>)> = Vec::new();
        for folder in dirs {
            // `len(path.parts)`: the anchor (drive and root) is one part.
            let (drive, root, tail) = car_config::winpath::parse(&folder);
            let depth = tail.len() + usize::from(!drive.is_empty() || !root.is_empty());
            match groups.last_mut() {
                Some((last, members)) if *last == depth => members.push(folder),
                _ => groups.push((depth, vec![folder])),
            }
        }
        Value::Array(
            groups
                .into_iter()
                .map(|(depth, mut members)| {
                    members.sort_by_key(|each| each.to_lowercase());
                    Value::Array(vec![Value::from(depth as i64), strings(&members)])
                })
                .collect(),
        )
    };
    let confined: Vec<Value> = match extra {
        Value::Array(list) => list
            .iter()
            .map(|each| Value::Bool(optional(each).is_some_and(|path| paths.confined(path))))
            .collect(),
        _ => Vec::new(),
    };
    object(vec![
        ("fields", fields(paths)),
        ("owns_state", Value::Bool(paths.owns(&paths.state_dir))),
        ("owns_logs", Value::Bool(paths.owns(&paths.logs_dir))),
        ("owns_home", Value::Bool(paths.owns_home())),
        ("state_files", strings(&paths.owned_state_files())),
        ("advanced_files", strings(&paths.owned_advanced_files())),
        ("account_files", strings(&paths.owned_account_files())),
        ("account_dirs", by_depth(paths.owned_account_dirs())),
        ("log_files", strings(&paths.owned_log_files())),
        ("confined", Value::Array(confined)),
    ])
}

fn build(a: &Args) -> Py<Paths> {
    let env = environment(a.get(2));
    Paths::new(
        optional(a.get(0)),
        a.text(1)?,
        &env,
        os_of(a.get(3), a.get(4)),
    )
}

/// A fixed clock: the time now, and one offset from UTC for every moment (or none).
struct Fixed {
    now: f64,
    offset: Option<i32>,
}

impl Clock for Fixed {
    fn now(&self) -> f64 {
        self.now
    }
    fn utc_offset(&self, _seconds: i64) -> Option<i32> {
        self.offset
    }
}

fn clock(now: &Value, offset: &Value) -> Fixed {
    Fixed {
        now: car_machine::pytext::to_float(now).unwrap_or(0.0),
        offset: match offset {
            Value::Int(int) => int.as_i64().map(|each| each as i32),
            _ => None,
        },
    }
}

pub fn case(name: &str, a: &Args) -> Option<Py<Value>> {
    Some(match name {
        "paths.build" => build(a).map(|found| fields(&found)),
        "paths.report" => build(a).map(|found| report(&found, a.get(5))),
        "paths.mutate" => build(a).map(|found| {
            let ensured = match found.ensure() {
                Ok(()) => Value::Null,
                Err(refused) => config_error(refused),
            };
            let claimed = found.claim_home();
            object(vec![
                ("ensure", ensured),
                ("claim_home", Value::Bool(claimed)),
                ("after", report(&found, a.get(5))),
            ])
        }),
        "paths.installed_home" => a
            .text(0)
            .map(|root| paths::installed_home(root).map_or(Value::Null, Value::from)),
        "paths.is_link" => a.text(0).map(|path| Value::Bool(paths::is_link(path))),
        "config.project_root" => (|| {
            let levels = usize::try_from(a.int(1)?).map_err(|_| "ValueError")?;
            codex::project_root(a.text(0)?, levels, a.text(2)?).map(Value::from)
        })(),
        "config.read_version" => a
            .text(0)
            .map(|manifest| match codex::read_version(manifest) {
                Ok(found) => Value::from(found),
                Err(refused) => config_error(refused),
            }),
        "config.version" => a.text(0).map(|root| {
            codex::reset_warnings();
            let mut warned = Vec::new();
            let found = codex::version(root, &mut |line| warned.push(line.to_owned()));
            object(vec![
                ("version", Value::from(found)),
                ("warned", strings(&warned)),
            ])
        }),
        "config.codex_home" => {
            let env = environment(a.get(0));
            codex::codex_home(&env, &os_of(a.get(1), a.get(2))).map(Value::from)
        }
        "config.codex_bin_dir" => {
            let env = environment(a.get(0));
            Ok(match codex::codex_bin_dir(&env) {
                Ok(found) => Value::from(found),
                Err(refused) => config_error(refused),
            })
        }
        "config.candidates" => {
            let env = environment(a.get(0));
            Ok(
                match codex::candidate_codex_exes(&env, &os_of(a.get(1), a.get(2))) {
                    Ok(found) => strings(&found),
                    Err(refused) => config_error(refused),
                },
            )
        }
        "config.discover" => discover(a),
        "logbook.format_local" => Ok(Value::from(logbook::format_local(
            a.get(0),
            &clock(&Value::Null, a.get(1)),
        ))),
        "logbook.render" => {
            let fixed = clock(&Value::Null, a.get(4));
            logbook::render(a.get(0), a.get(1), a.get(2), a.get(3), &fixed).map(Value::from)
        }
        "logbook.skipped" => {
            logbook::skipped(a.get(0), a.get(1), a.get(2), a.get(3)).map(Value::from)
        }
        "logbook.tail" => (|| {
            let count = match a.get(1) {
                Value::Int(int) => int.as_i64().ok_or("OverflowError")?,
                _ => return Err("TypeError"),
            };
            Ok(strings(&logbook::tail(
                std::path::Path::new(a.text(0)?),
                count,
            )))
        })(),
        "logbook.write" => write_log(a),
        _ => return None,
    })
}

/// `logbook.write`: [file, mark, state_codes, [[thread, code, detail] | ["info", line]], now0, offset, step]: the lines
/// the engine and the process write, each one `step` seconds after the last.
fn write_log(a: &Args) -> Py<Value> {
    let file = a.text(0)?;
    let marks = a.text(1)?;
    let codes: Vec<String> = match a.get(2) {
        Value::Array(each) => each.iter().map(py_str).collect(),
        _ => Vec::new(),
    };
    let codes: Vec<&str> = codes.iter().map(String::as_str).collect();
    let mut log = Logbook::open(file, marks, &codes).with_rename(car_platform::files::rename);
    let mut at = car_machine::pytext::to_float(a.get(4)).unwrap_or(0.0);
    let step = car_machine::pytext::to_float(a.get(6)).unwrap_or(1.0);
    let Value::Array(events) = a.get(3) else {
        return Err("TypeError");
    };
    for event in events {
        let Value::Array(parts) = event else {
            return Err("TypeError");
        };
        let fixed = Fixed {
            now: at,
            offset: match a.get(5) {
                Value::Int(int) => int.as_i64().map(|each| each as i32),
                _ => None,
            },
        };
        match parts.first() {
            Some(Value::Str(tag)) if tag.as_str() == Some("info") => {
                log.info(&py_str(&parts[1]), &fixed);
            }
            _ => log.log(&parts[0], &parts[1], &parts[2], &fixed)?,
        }
        at += step;
    }
    Ok(digest(std::path::Path::new(file)))
}

/// `{name: [length, sha256]}` of every file beside `file`, in name order.
fn digest(file: &std::path::Path) -> Value {
    let mut names: Vec<String> = std::fs::read_dir(file.parent().unwrap_or(file))
        .map(|listing| {
            listing
                .filter_map(Result::ok)
                .map(|each| each.file_name().to_string_lossy().into_owned())
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    let mut map = Map::new();
    for name in names {
        let bytes = std::fs::read(file.parent().unwrap_or(file).join(&name)).unwrap_or_default();
        map.insert(
            Str::from(name),
            Value::Array(vec![
                Value::from(bytes.len() as i64),
                Value::from(car_machine::hash::hex(&car_machine::hash::sha256(&bytes))),
            ]),
        );
    }
    Value::Object(map)
}

/// `config.discover`: [explicit, env, cwd, rules {folder: reason}, running list | null | "fail", ask_app, ask_if_none, long].
fn discover(a: &Args) -> Py<Value> {
    let env = environment(a.get(1));
    let rules: Vec<(String, String)> = match a.get(3) {
        Value::Object(map) => map
            .iter()
            .map(|(key, each)| {
                (
                    String::from_utf8_lossy(key.as_bytes()).into_owned(),
                    py_str(each),
                )
            })
            .collect(),
        _ => Vec::new(),
    };
    let compatible = move |path: &str| -> Result<(), String> {
        let folder = car_config::winpath::split(&car_config::winpath::split(path).0).1;
        match rules.iter().find(|(name, _)| *name == folder) {
            Some((_, reason)) => Err(reason.clone()),
            None => Ok(()),
        }
    };
    let listed: Option<Vec<String>> = match a.get(4) {
        Value::Array(items) => Some(items.iter().map(py_str).collect()),
        _ => None,
    };
    let failing = matches!(a.get(4), Value::Str(_));
    let running = move || -> Option<Vec<String>> { if failing { None } else { listed.clone() } };
    let asked = !matches!(a.get(4), Value::Null);
    let answer = codex::discover_codex_exe(
        optional(a.get(0)),
        &compatible,
        if asked { Some(&running) } else { None },
        matches!(a.get(5), Value::Bool(true)),
        matches!(a.get(6), Value::Bool(true)),
        &env,
        &os_of(a.get(2), a.get(7)),
    );
    match answer {
        Ok(found) => Ok(Value::from(found)),
        Err(codex::DiscoverError::Config(refused)) => Ok(config_error(refused)),
        // the stub's own exception, raised through
        Err(codex::DiscoverError::Check(_)) => Err("RuntimeError"),
    }
}

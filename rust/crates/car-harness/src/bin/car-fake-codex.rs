//! `car-fake-codex`: a stand-in for `codex.exe` that the S3.3 diffs copy into a scratch Codex bin folder and that both
//! the reference and car-codex start (always with `CREATE_NO_WINDOW`). Dev only, never shipped; it starts nothing.
//!
//! It reads `fake.json` beside itself and appends what it was asked to `fake.log.jsonl` there: its arguments, its
//! working folder and the two variables the backend sets. `--version`, `queue --help` and `queue ...` answer with the
//! script's text and exit code; `app-server --stdio` keeps every byte it is sent in `stdin.bin` and answers each
//! request from the script's `answers` (one entry per call of a method, the last repeated):
//!
//! * `{"result": V}` / `{"error": V}`: `{"id": <id>, "result": V}` or `{"error": V, "id": <id>}`, `"{home}"` in V
//!   replaced by `CODEX_HOME`;
//! * `{"raw": "text"}`: the text as it is, `{id}` and `{home}` replaced (the script writes the line end);
//! * `{"big": {"head", "fill", "count", "tail"}}`: head, `fill` `count` times, tail, then `\n`;
//! * `{"sleep": seconds}`, `{"exit": code}`.
//!
//! `before` lines are written at the start; `on_close` is `exit` (the default) or `hang` (it then waits to be ended).

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

use serde_json::Value;

fn beside() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_default()
}

fn append(path: &Path, bytes: &[u8]) {
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = file.write_all(bytes);
        let _ = file.flush();
    }
}

fn home() -> String {
    std::env::var("CODEX_HOME").unwrap_or_default()
}

fn home_json() -> String {
    let quoted = serde_json::to_string(&home()).unwrap_or_else(|_| "\"\"".into());
    quoted[1..quoted.len() - 1].to_owned()
}

fn substitute(text: &str, id: &str) -> String {
    text.replace("{id}", id).replace("{home}", &home_json())
}

fn with_home(value: &Value) -> Value {
    match value {
        Value::String(text) if text == "{home}" => Value::String(home()),
        Value::Array(items) => Value::Array(items.iter().map(with_home).collect()),
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(key, item)| (key.clone(), with_home(item)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn out(bytes: &[u8]) {
    let mut stdout = std::io::stdout().lock();
    let _ = stdout.write_all(bytes);
    let _ = stdout.flush();
}

fn simple(entry: &Value, thread: &str) -> i32 {
    if let Some(seconds) = entry.get("sleep").and_then(Value::as_f64) {
        std::thread::sleep(Duration::from_secs_f64(seconds));
    }
    if let Some(hex) = entry.get("stdout_hex").and_then(Value::as_str) {
        let bytes: Vec<u8> = (0..hex.len() / 2)
            .filter_map(|i| u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).ok())
            .collect();
        out(&bytes);
    } else if let Some(text) = entry.get("stdout").and_then(Value::as_str) {
        out(text.replace("{thread}", thread).as_bytes());
    }
    entry.get("code").and_then(Value::as_i64).unwrap_or(0) as i32
}

fn act(action: &Value, id: &Value) -> Option<i32> {
    let ident = serde_json::to_string(id).unwrap_or_default();
    if let Some(result) = action.get("result") {
        let line = format!(
            "{{\"id\": {ident}, \"result\": {}}}\n",
            serde_json::to_string(&with_home(result)).unwrap_or_default()
        );
        out(line.as_bytes());
    } else if let Some(error) = action.get("error") {
        let line = format!(
            "{{\"error\": {}, \"id\": {ident}}}\n",
            serde_json::to_string(error).unwrap_or_default()
        );
        out(line.as_bytes());
    } else if let Some(raw) = action.get("raw").and_then(Value::as_str) {
        out(substitute(raw, &ident).as_bytes());
    } else if let Some(big) = action.get("big") {
        let text = |key: &str| big.get(key).and_then(Value::as_str).unwrap_or_default();
        let count = big.get("count").and_then(Value::as_u64).unwrap_or(0) as usize;
        let mut line = substitute(text("head"), &ident);
        line.push_str(&text("fill").repeat(count));
        line.push_str(&substitute(text("tail"), &ident));
        line.push('\n');
        out(line.as_bytes());
    } else if let Some(seconds) = action.get("sleep").and_then(Value::as_f64) {
        std::thread::sleep(Duration::from_secs_f64(seconds));
    } else if let Some(code) = action.get("exit").and_then(Value::as_i64) {
        return Some(code as i32);
    }
    None
}

fn server(script: &Value, folder: &Path) -> i32 {
    let (send, receive) = mpsc::channel::<Option<Vec<u8>>>();
    let record = folder.join("stdin.bin");
    std::thread::spawn(move || {
        let mut stdin = std::io::stdin().lock();
        let mut pending: Vec<u8> = Vec::new();
        let mut buffer = [0u8; 65536];
        loop {
            match stdin.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(read) => {
                    append(&record, &buffer[..read]);
                    pending.extend_from_slice(&buffer[..read]);
                    while let Some(at) = pending.iter().position(|b| *b == b'\n') {
                        let line: Vec<u8> = pending.drain(..=at).collect();
                        let _ = send.send(Some(line));
                    }
                }
            }
        }
        let _ = send.send(None);
    });
    if let Some(Value::Array(lines)) = script.get("before") {
        for line in lines {
            if act(line, &Value::Null).is_some() {
                return 0;
            }
        }
    }
    let mut calls: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    while let Ok(Some(line)) = receive.recv() {
        let Ok(message) = serde_json::from_slice::<Value>(&line) else {
            continue;
        };
        let (Some(method), Some(id)) = (
            message.get("method").and_then(Value::as_str),
            message.get("id"),
        ) else {
            continue;
        };
        let count = calls.entry(method.to_owned()).or_insert(0);
        let entries = script
            .get("answers")
            .and_then(|answers| answers.get(method))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        *count += 1;
        let Some(entry) = entries.get(*count - 1).or(entries.last()) else {
            continue;
        };
        let actions = entry.as_array().cloned().unwrap_or_default();
        for action in &actions {
            if let Some(code) = act(action, id) {
                return code;
            }
        }
    }
    if script.get("on_close").and_then(Value::as_str) == Some("hang") {
        std::thread::sleep(Duration::from_secs(120));
    }
    script.get("exit_code").and_then(Value::as_i64).unwrap_or(0) as i32
}

fn main() {
    // A thread with the stack for a deeply nested document (car_machine::stack).
    car_machine::stack::run_deep(run);
}

fn run() {
    let folder = beside();
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let cwd = std::env::current_dir()
        .map(|found| found.to_string_lossy().into_owned())
        .unwrap_or_default();
    let entry = serde_json::json!({
        "args": arguments,
        "cwd": cwd,
        "codex_home": std::env::var("CODEX_HOME").ok(),
        "otel": std::env::var("OTEL_SDK_DISABLED").ok(),
    });
    append(
        &folder.join("fake.log.jsonl"),
        format!("{entry}\n").as_bytes(),
    );
    let script: Value = std::fs::read(folder.join("fake.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(Value::Null);
    let mut rest = arguments.iter();
    let mut positional: Vec<&str> = Vec::new();
    while let Some(argument) = rest.next() {
        if argument == "-c" {
            rest.next();
            continue;
        }
        positional.push(argument);
    }
    let thread = arguments
        .iter()
        .position(|each| each == "--thread")
        .and_then(|at| arguments.get(at + 1))
        .cloned()
        .unwrap_or_default();
    let code = match positional.as_slice() {
        ["--version", ..] => simple(&script["version"], ""),
        ["queue", "--help", ..] => simple(&script["help"], ""),
        ["queue", ..] => simple(&script["queue"], &thread),
        ["app-server", ..] => server(&script["server"], &folder),
        _ => 2,
    };
    std::process::exit(code);
}

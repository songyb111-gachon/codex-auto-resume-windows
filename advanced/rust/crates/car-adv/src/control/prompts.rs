//! `control/prompts.py` (seat S7.3a): the Dashboard's prompt queue (v0.6.15-beta) - the queued prompts read, one
//! added, one cancelled, one held let go on, one still waiting edited, and the completed ones a person was shown
//! deleted from the list - with each prompt's pictures (v0.6.20, `images.rs`) and the steers History lists.

use std::path::Path;

use car_machine::domain::ids;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use super::resets::{
    Result, among, arg, call, field, generation, get, int, is, is_int, length, list, object, on, refusal, refused,
    refused_here, shown, stale, standing, switched_off, text, verdict, with,
};
use crate::engine::promptqueue::{CAPABILITY, LONG, SHORT_LIMIT};
use crate::images::{self, ImageError, MOST_BYTES, MOST_IMAGES};
use crate::runtime::Runtime;
use crate::state::Error;
use crate::state::prompts::{COMPLETED, PENDING, PER_CONVERSATION, PROMPTS_LIMIT};
use crate::vocabulary::{Measurement, PromptState, Refusal};

pub const SHOWN: &[&str] = &[
    "prompt_id",
    "thread_id",
    "trigger",
    "at",
    "every",
    "occurrences",
    "sent_count",
    "until",
    "depends",
    "position",
    "state",
    "reason",
    "gate",
    "gate_reason",
    "created_at",
    "due_at",
    "sent_at",
    "finished_at",
    "while_running",
];

fn folder(runtime: &Runtime) -> &Path {
    Path::new(&runtime.paths.advanced_dir)
}

/// A prompt id as `images.py` writes it (`%d`).
fn key(prompt: &Value) -> String {
    match prompt {
        Value::Int(number) => number.to_string(),
        other => crate::state::py::py_str(other),
    }
}

/// A text's own value, or "".
fn own_text(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

/// `counts(runtime)`: how many prompts are still to go, and the steers waiting for the watcher - counts only.
pub fn counts(runtime: &Runtime) -> Map {
    let mut found = Map::new();
    let Ok(rows) = call(runtime, "prompts", &[], &[]) else {
        return found;
    };
    let rows = list(&rows);
    if !rows.is_empty() {
        found.insert(Str::new("prompts"), int(rows.len() as i64));
    }
    let steers = super::steer::waiting(runtime);
    if steers != 0 {
        found.insert(Str::new("steers_waiting"), int(steers));
    }
    found
}

/// `words_limit(runtime)`.
pub fn words_limit(runtime: &Runtime) -> usize {
    if on(runtime, LONG) {
        car_policy::classify::continuation::prompt_limit()
    } else {
        SHORT_LIMIT
    }
}

/// `copies.of(paths, prompt)` as the list shows it.
fn copies_of(runtime: &Runtime, prompt: &Value) -> Value {
    Value::Array(
        images::of(folder(runtime), &key(prompt))
            .into_iter()
            .map(|(id, path)| object(vec![("id", text(&id)), ("path", text(&path))]))
            .collect(),
    )
}

/// `view(runtime)`: advanced-prompts.
pub fn view(runtime: &Runtime) -> Value {
    let read = || -> Result<(Vec<Map>, Value)> {
        let rows = list(&call(runtime, "prompts", &[], &[("pending", Value::Null)])?);
        Ok((rows, generation(runtime)?))
    };
    let Ok((rows, generation)) = read() else {
        return refusal(Refusal::StateUnavailable);
    };
    let now = runtime.now();
    let mut shown_rows = Vec::new();
    for row in &rows {
        let state = get(row, "state");
        let pending = among(
            &state,
            &[PromptState::Waiting.as_str(), PromptState::Ready.as_str(), PromptState::Held.as_str()],
        );
        if !pending && super::resets::or_zero(&get(row, "finished_at")).is_some_and(|at| at < now - 30.0 * 86400.0) {
            continue;
        }
        let mut item = shown(row, SHOWN);
        item.insert(Str::new("words"), get(row, "words"));
        let in_flight = is(&get(row, "record_state"), "in_flight");
        let sent = !matches!(get(row, "sent_at"), Value::Null);
        item.insert(Str::new("in_codex"), Value::Bool(in_flight && sent));
        item.insert(Str::new("being_sent"), Value::Bool(in_flight && !sent));
        item.insert(
            Str::new("completed"),
            Value::Bool(is(&state, PromptState::Done.as_str()) && among(&get(row, "reason"), COMPLETED)),
        );
        if among(&state, PENDING) {
            item.insert(Str::new("images"), copies_of(runtime, &get(row, "prompt_id")));
        }
        shown_rows.push(Value::Object(item));
    }
    let (unproven, after_turn_failed) = match runtime.arming().verdict(Measurement::Mt.as_str()) {
        Ok(found) => (found != Some("pass"), found == Some("fail")),
        Err(_) => (true, false),
    };
    let steers = super::steer::rows(runtime);
    let limit = words_limit(runtime);
    let unavailable = images_failed(runtime);
    let pending_ids: Vec<String> = rows
        .iter()
        .filter(|row| among(&get(row, "state"), PENDING))
        .map(|row| key(&get(row, "prompt_id")))
        .collect();
    let (count, size) = images::kept(folder(runtime), &pending_ids);
    object(vec![
        ("done", Value::Bool(true)),
        ("refusal", Value::Null),
        ("generation", generation),
        ("prompts", Value::Array(shown_rows)),
        ("after_turn_unproven", Value::Bool(unproven)),
        ("after_turn_failed", Value::Bool(after_turn_failed)),
        ("steers", Value::Array(steers)),
        (
            "limits",
            object(vec![
                ("prompts", int(PROMPTS_LIMIT as i64)),
                ("per_conversation", int(PER_CONVERSATION as i64)),
                ("words", int(limit as i64)),
                ("occurrences", int(30)),
                ("days", int(30)),
                ("images", int(MOST_IMAGES as i64)),
                ("image_bytes", int(MOST_BYTES as i64)),
            ]),
        ),
        ("images_unavailable", Value::Bool(unavailable)),
        ("images_kept", object(vec![("count", int(count)), ("bytes", int(size as i64))])),
    ])
}

/// `_images_failed(runtime)`: MIMG failed on the Codex in force.
fn images_failed(runtime: &Runtime) -> bool {
    verdict(runtime, Measurement::Mimg) == Some("fail")
}

/// `sweep(runtime)`: every copy whose prompt is no longer still to go removed.
pub fn sweep(runtime: &Runtime) {
    let Ok(rows) = call(runtime, "prompts", &[], &[("pending", Value::Bool(true))]) else {
        return;
    };
    let pending: Vec<String> = list(&rows).iter().map(|row| key(&get(row, "prompt_id"))).collect();
    images::sweep(folder(runtime), &pending);
}

/// What `_staged` made: the opaque ids chosen and the copies this made, or the refusal's word.
type Staged = std::result::Result<(Vec<String>, Vec<String>), String>;

/// `_staged(runtime, images, prompt=None)`: the opaque ids of the pictures `images` names, each new file read and
/// copied as a save's copy, each kept one checked to be `prompt`'s; or the refusal, every copy this made removed.
fn staged(runtime: &Runtime, asked: &Value, prompt: Option<&Value>) -> Result<Staged> {
    let Value::Array(asked) = asked else {
        return Ok(Err(Refusal::InvalidRequest.as_str().into()));
    };
    if asked.len() > MOST_IMAGES {
        return Ok(Err(Refusal::ImagesFull.as_str().into()));
    }
    if !asked.is_empty() && images_failed(runtime) {
        return Ok(Err(Refusal::ImagesUnavailable.as_str().into()));
    }
    let own: Vec<String> = match prompt {
        Some(prompt) => images::of(folder(runtime), &key(prompt))
            .into_iter()
            .map(|(id, _)| id)
            .collect(),
        None => Vec::new(),
    };
    let (mut made, mut chosen): (Vec<String>, Vec<String>) = (Vec::new(), Vec::new());
    for image in asked {
        let Value::Object(map) = image else {
            images::drop_staged(folder(runtime), &made);
            return Ok(Err(Refusal::InvalidRequest.as_str().into()));
        };
        if map.len() != 1 || !(map.contains_key("id") || map.contains_key("path")) {
            images::drop_staged(folder(runtime), &made);
            return Ok(Err(Refusal::InvalidRequest.as_str().into()));
        }
        if let Some(id) = map.get("id") {
            if matches!(id, Value::Array(_) | Value::Object(_)) {
                return Err(Error::type_error("unhashable type"));
            }
            let named = own_text(id);
            let known = matches!(id, Value::Str(_)) && own.iter().any(|own| own == &named);
            let again = matches!(id, Value::Str(_)) && chosen.iter().any(|seen| seen == &named);
            if !known || again {
                images::drop_staged(folder(runtime), &made);
                return Ok(Err(Refusal::InvalidRequest.as_str().into()));
            }
            chosen.push(named);
            continue;
        }
        let read = match map.get("path") {
            Some(Value::Str(path)) => match path.as_str() {
                Some(path) => images::read(path),
                None => Err(ImageError::Refused("image_refused")),
            },
            _ => Err(ImageError::Refused("image_refused")),
        };
        let copied =
            read.and_then(|(data, ext)| images::stage(folder(runtime), runtime.state.tokens.as_ref(), &data, ext));
        match copied {
            Ok(copy) => {
                made.push(copy.clone());
                chosen.push(copy);
            }
            Err(ImageError::Refused(word)) => {
                images::drop_staged(folder(runtime), &made);
                return Ok(Err(word.into()));
            }
            Err(ImageError::Os(_)) => {
                images::drop_staged(folder(runtime), &made);
                return Ok(Err(Refusal::StateUnavailable.as_str().into()));
            }
        }
    }
    Ok(Ok((chosen, made)))
}

/// The schedule keywords an add and an edit pass on.
fn schedule(argument: &Map) -> Vec<(&'static str, Value)> {
    let while_running = arg(argument, "while_running");
    vec![
        ("at", arg(argument, "at")),
        ("every", arg(argument, "every")),
        ("occurrences", argument.get("occurrences").cloned().unwrap_or(int(1))),
        ("depends", Value::Bool(matches!(arg(argument, "depends"), Value::Bool(true)))),
        (
            "while_running",
            if pyval::truthy(&while_running) {
                while_running
            } else {
                text("queue")
            },
        ),
    ]
}

/// `except Refused as refused: ... except Exception: ...`, after `copies.drop(paths, made)`.
fn write_refusal(runtime: &Runtime, error: Error) -> Value {
    if error.class() == "Refused" {
        refused(error.word().unwrap_or_default(), Some(runtime))
    } else {
        refused_here(Refusal::StateUnavailable, runtime)
    }
}

/// `add(runtime, argument)`: advanced-prompt-add.
pub fn add(runtime: &Runtime, argument: &Map) -> Result<Value> {
    if stale(runtime, &arg(argument, "generation")) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let (thread, words) = (arg(argument, "thread_id"), arg(argument, "words"));
    if !ids::is_uuid(&thread) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !standing(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    if switched_off(runtime, &thread) {
        return Ok(refused_here(Refusal::ConversationOff, runtime));
    }
    if car_policy::classify::continuation::validate_prompt(&words).is_err() || length(&words) > words_limit(runtime) {
        return Ok(refused_here(Refusal::PromptRefused, runtime));
    }
    let asked = argument.get("images").cloned().unwrap_or(Value::Array(Vec::new()));
    let (chosen, made) = match staged(runtime, &asked, None)? {
        Ok(found) => found,
        Err(word) => return Ok(refused(&word, Some(runtime))),
    };
    let mut keywords = schedule(argument);
    keywords.push(("held", Value::Bool(!chosen.is_empty())));
    let prompt = match call(runtime, "add_prompt", &[thread, words, arg(argument, "trigger")], &keywords) {
        Ok(prompt) => prompt,
        Err(error) => {
            images::drop_staged(folder(runtime), &made);
            return Ok(write_refusal(runtime, error));
        }
    };
    if !chosen.is_empty() {
        if images::place(folder(runtime), &key(&prompt), &chosen).is_err() {
            let at = Value::Float(runtime.now());
            let _ = call(runtime, "cancel_prompt", &[prompt.clone()], &[("at", at)]);
            images::drop_staged(folder(runtime), &made);
            sweep(runtime);
            return Ok(refused_here(Refusal::StateUnavailable, runtime));
        }
        if call(runtime, "placed_prompt", &[prompt.clone()], &[]).is_err() {
            return Ok(refused_here(Refusal::StateUnavailable, runtime));
        }
    }
    sweep(runtime);
    Ok(with(view(runtime), vec![("done", Value::Bool(true)), ("prompt", prompt)]))
}

/// `cancel(runtime, prompt, generation)`: advanced-prompt-cancel.
pub fn cancel(runtime: &Runtime, prompt: &Value, asked: &Value) -> Result<Value> {
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !is_int(prompt) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    let at = Value::Float(runtime.now());
    let how = match call(runtime, "cancel_prompt", &[prompt.clone()], &[("at", at)]) {
        Ok(how) => how,
        Err(error) => return Ok(write_refusal(runtime, error)),
    };
    sweep(runtime);
    Ok(with(view(runtime), vec![("done", Value::Bool(true)), ("cancelled", how)]))
}

/// `go_on(runtime, prompt, generation)`: advanced-prompt-go-on.
pub fn go_on(runtime: &Runtime, prompt: &Value, asked: &Value) -> Result<Value> {
    if stale(runtime, asked) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    if !is_int(prompt) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    let at = Value::Float(runtime.now());
    match call(runtime, "go_on_prompt", &[prompt.clone()], &[("at", at)]) {
        Ok(moved) if pyval::truthy(&moved) => {}
        Ok(_) => return Ok(refused_here(Refusal::InvalidRequest, runtime)),
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    }
    Ok(with(view(runtime), vec![("done", Value::Bool(true))]))
}

/// `edit(runtime, argument)`: advanced-prompt-edit.
pub fn edit(runtime: &Runtime, argument: &Map) -> Result<Value> {
    let asked_generation = arg(argument, "generation");
    if stale(runtime, &asked_generation) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let (prompt, words) = (arg(argument, "prompt"), arg(argument, "words"));
    if !is_int(&prompt) {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    }
    if !standing(runtime, CAPABILITY) {
        return Ok(refused_here(Refusal::NotOn, runtime));
    }
    let row = match call(runtime, "prompt", &[prompt.clone()], &[]) {
        Ok(row) => row,
        Err(_) => return Ok(refused_here(Refusal::StateUnavailable, runtime)),
    };
    let Value::Object(row) = row else {
        return Ok(refused_here(Refusal::InvalidRequest, runtime));
    };
    if switched_off(runtime, &get(&row, "thread_id")) {
        return Ok(refused_here(Refusal::ConversationOff, runtime));
    }
    if car_policy::classify::continuation::validate_prompt(&words).is_err() || length(&words) > words_limit(runtime) {
        return Ok(refused_here(Refusal::PromptRefused, runtime));
    }
    let (mut chosen, mut made) = (None, Vec::new());
    if argument.contains_key("images") {
        match staged(runtime, &arg(argument, "images"), Some(&prompt))? {
            Ok((ids, copies)) => {
                chosen = Some(ids);
                made = copies;
            }
            Err(word) => return Ok(refused(&word, Some(runtime))),
        }
    }
    let mut keywords = schedule(argument);
    keywords.push(("now", Value::Float(runtime.now())));
    keywords.push(("held", Value::Bool(chosen.is_some())));
    let edited = call(
        runtime,
        "edit_prompt",
        &[prompt.clone(), asked_generation, words, arg(argument, "trigger")],
        &keywords,
    );
    if let Err(error) = edited {
        images::drop_staged(folder(runtime), &made);
        return Ok(write_refusal(runtime, error));
    }
    if let Some(chosen) = chosen {
        let placed = images::place(folder(runtime), &key(&prompt), &chosen);
        if placed.is_err() {
            images::drop_staged(folder(runtime), &made);
        }
        let _ = call(runtime, "placed_prompt", &[prompt.clone()], &[]);
        if placed.is_err() {
            return Ok(refused_here(Refusal::StateUnavailable, runtime));
        }
    }
    Ok(with(view(runtime), vec![("done", Value::Bool(true)), ("prompt", prompt)]))
}

/// `clear_done(runtime, argument)`: advanced-prompts-clear-done.
pub fn clear_done(runtime: &Runtime, argument: &Map) -> Result<Value> {
    let asked_generation = arg(argument, "generation");
    if stale(runtime, &asked_generation) {
        return Ok(refused_here(Refusal::StaleGeneration, runtime));
    }
    let cleared = match call(runtime, "clear_done", &[arg(argument, "prompts"), asked_generation], &[]) {
        Ok(cleared) => cleared,
        Err(error) => return Ok(write_refusal(runtime, error)),
    };
    sweep(runtime);
    Ok(with(
        view(runtime),
        vec![
            ("done", Value::Bool(true)),
            ("deleted", field(&cleared, "deleted")),
            ("skipped", field(&cleared, "skipped")),
        ],
    ))
}

//! `plugin.run`: a program of the declaration writer's calls over a scratch plugin tree (never a real plugin copy, never
//! Codex's own files): write, remove, present, roots, target, follow, and the tree's own edits between them.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use car_adv::control::hookplugin::{self, Real};
use car_adv::hook::format::{FORMAT, HookFormat};
use car_adv::jsonx::object;
use car_config::Paths;
use car_machine::json::{Map, Str, Value};

use crate::util::{Failure, Out, arg, flag, list, maybe_text, text};

#[derive(Debug)]
struct Links;

impl car_config::Links for Links {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

pub fn paths_of(home: &str) -> Paths {
    let no_env = |_: &str| None;
    Paths::new(
        Some(home),
        home,
        &no_env,
        car_config::Os::here(false, Arc::new(Links)),
    )
    .expect("the home's paths")
}

fn format_named(name: &str) -> Result<HookFormat, Failure> {
    let mut found = FORMAT;
    match name {
        "shipped" => {}
        "contained" => found.command = "contained",
        "manifest" => found.manifest_key = Some("hooks"),
        "contained_manifest" => {
            found.command = "contained";
            found.manifest_key = Some("hooks");
        }
        "installation" => found.roots = &["installation"],
        "copy" => found.roots = &["codex_copy"],
        _ => return Err(Failure::new("BadArgument")),
    }
    Ok(found)
}

fn shown(path: &Path, base: &str) -> Value {
    let text = car_config::winpath::path_str(&path.to_string_lossy());
    Value::from(text.replace(base, "<base>"))
}

fn dump(base: &Path) -> Value {
    let mut files = std::collections::BTreeMap::new();
    let mut folders = Vec::new();
    fn walk(
        folder: &Path,
        base: &Path,
        files: &mut std::collections::BTreeMap<String, String>,
        folders: &mut Vec<String>,
    ) {
        let Ok(entries) = std::fs::read_dir(folder) else {
            return;
        };
        let mut entries: Vec<PathBuf> = entries.filter_map(Result::ok).map(|e| e.path()).collect();
        entries.sort();
        for path in entries {
            let name = path
                .strip_prefix(base)
                .map(|each| each.to_string_lossy().replace('\\', "/"))
                .unwrap_or_default();
            if path.is_dir() {
                folders.push(name);
                walk(&path, base, files, folders);
            } else {
                let bytes = std::fs::read(&path).unwrap_or_default();
                files.insert(name, String::from_utf8_lossy(&bytes).into_owned());
            }
        }
    }
    walk(base, base, &mut files, &mut folders);
    folders.sort();
    let mut shown = Map::new();
    let plain = base.to_string_lossy().into_owned();
    let escaped = plain.replace('\\', "\\\\");
    for (name, text) in files {
        let text = text
            .replace(&escaped, "<escaped>")
            .replace(&plain, "<base>");
        shown.insert(Str::from(name.as_str()), Value::from(text));
    }
    object([
        ("files", Value::Object(shown)),
        (
            "folders",
            Value::Array(folders.into_iter().map(Value::from).collect()),
        ),
    ])
}

pub fn run(op: &str, args: &[Value]) -> Out {
    if op != "plugin.run" {
        return Err(Failure::new("UnknownOp"));
    }
    let base = text(arg(args, 0)?)?.to_owned();
    let home = Path::new(&base).join("product");
    let paths = paths_of(&home.to_string_lossy());
    let codex = maybe_text(arg(args, 1)?)?.map(PathBuf::from);
    let format = format_named(text(arg(args, 2)?)?)?;
    let mut steps = Vec::new();
    for step in list(arg(args, 3)?)? {
        let parts = list(step)?;
        let codex = codex.as_deref();
        steps.push(match text(arg(parts, 0)?)? {
            "write" => match hookplugin::write(&paths, codex, &format, &Real) {
                Ok(many) => Value::from(many as i64),
                Err(_) => object([("error", Value::from("OSError"))]),
            },
            "remove" => match hookplugin::remove(&paths, codex, &format, &Real) {
                Ok(many) => Value::from(many as i64),
                Err(_) => object([("error", Value::from("OSError"))]),
            },
            "present" => Value::Bool(hookplugin::present(&paths, codex, &format)),
            "roots" => Value::Array(
                hookplugin::roots(&paths, codex, &format)
                    .iter()
                    .map(|root| shown(root, &base))
                    .collect(),
            ),
            "target" => {
                let root = PathBuf::from(car_config::winpath::path_str(
                    &Path::new(&base)
                        .join(text(arg(parts, 1)?)?)
                        .to_string_lossy(),
                ));
                hookplugin::target(&root, &format).map_or(Value::Null, |path| shown(&path, &base))
            }
            "command" => Value::from(hookplugin::command(&paths, &format).replace(&base, "<base>")),
            "follow" => {
                Value::from(
                    hookplugin::follow(&paths, codex, flag(arg(parts, 1)?)?, &format, &Real) as i64,
                )
            }
            "put" => {
                let path = Path::new(&base).join(text(arg(parts, 1)?)?);
                let done = match maybe_text(arg(parts, 2)?)? {
                    Some(content) => {
                        if let Some(parent) = path.parent() {
                            let _ = std::fs::create_dir_all(parent);
                        }
                        std::fs::write(&path, content)
                    }
                    None => std::fs::remove_file(&path),
                };
                match done {
                    Ok(()) => Value::Null,
                    Err(_) => object([("error", Value::from("OSError"))]),
                }
            }
            "dump" => dump(Path::new(&base)),
            _ => return Err(Failure::new("BadArgument")),
        });
    }
    Ok(object([
        ("steps", Value::Array(steps)),
        ("tree", dump(Path::new(&base))),
    ]))
}

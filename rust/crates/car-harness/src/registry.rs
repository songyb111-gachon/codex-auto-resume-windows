//! The registry's operations of `codexapp.script` (`registry.*`): car-codex's `compat` and `compatio`, each named as
//! `tests/rustdiff/appserverdiff.py`'s reference script names it. Documents are given as their JSON text and parsed
//! by both sides' `parse_document`; every other value is the dict the reference passes.

use std::ffi::OsString;
use std::sync::{Arc, Mutex};

use car_codex::compat::cache::{self, Cache};
use car_codex::compat::evaluator::{self, Evaluator, Ran, Runner};
use car_codex::compat::model::{Document, parse_document};
use car_codex::compat::views::{self, Registry};
use car_codex::compat::{files, probes, report, reported, standing};
use car_codex::errors::Error;
use car_codex::system::System;
use car_machine::json::{Map, Str, Value};
use car_machine::pyval;

use crate::appserver::{Case, failed, hex};
use crate::object;

/// The registry's part of a case's state.
#[derive(Default)]
pub struct State {
    evaluator: Option<Evaluator>,
    said: Arc<Mutex<Vec<String>>>,
}

fn field<'a>(value: &'a Value, key: &str) -> &'a Value {
    static NULL: Value = Value::Null;
    match value {
        Value::Object(map) => map.get(key).unwrap_or(&NULL),
        _ => &NULL,
    }
}

fn ok(value: Value) -> Value {
    object([("ok", value)])
}

fn text_of(value: &Value) -> String {
    match value {
        Value::Str(text) => text.as_str().unwrap_or_default().to_owned(),
        _ => String::new(),
    }
}

fn option_text(value: &Value) -> Option<String> {
    pyval::text(value).map(str::to_owned)
}

fn number(value: &Value) -> f64 {
    pyval::Num::of(value).map_or(0.0, pyval::Num::as_f64)
}

fn document_error(code: &str) -> Value {
    object([
        ("error", Value::from("DocumentError")),
        ("code", Value::from(code)),
    ])
}

fn raised(class: &str) -> Value {
    object([("error", Value::from(class))])
}

fn document(value: &Value) -> Result<Option<Document>, Value> {
    match value {
        Value::Null => Ok(None),
        Value::Str(text) => parse_document(
            text.as_str().unwrap_or_default().as_bytes(),
            car_codex::compat::MAX_DOCUMENT_BYTES,
        )
        .map(Some)
        .map_err(|refused| document_error(refused.code)),
        _ => Err(raised("TypeError")),
    }
}

fn texts(items: &[String]) -> Value {
    Value::Array(
        items
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect(),
    )
}

fn registry_of(spec: &Value, system: Arc<dyn System>) -> Registry {
    Registry {
        system,
        config: car_config::Os::here(false, crate::links::for_config()),
        bundled: text_of(field(spec, "bundled")),
        reported: text_of(field(spec, "reported")),
        cache_file: text_of(field(spec, "cache_file")),
        report_file: text_of(field(spec, "report_file")),
        version: text_of(field(spec, "version")),
    }
}

fn discovery_of(value: &Value) -> Vec<(String, Value)> {
    match value {
        Value::Array(pairs) => pairs
            .iter()
            .filter_map(|pair| match pair {
                Value::Array(parts) if parts.len() == 2 => {
                    Some((text_of(&parts[0]), parts[1].clone()))
                }
                _ => None,
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn table_value(table: &reported::Table) -> Value {
    let mut out = Map::new();
    for (version, counts) in table {
        let mut entry = Map::new();
        for (name, count) in reported::COUNTS.iter().zip(counts) {
            entry.insert(Str::from(*name), Value::from(*count));
        }
        out.insert(Str::from(version.as_str()), Value::Object(entry));
    }
    Value::Object(out)
}

/// What the stub runner was handed: the arguments, the plugin home it was given, its time.
type Seen = (Vec<String>, Option<String>, f64);

struct Stub {
    spec: Value,
    seen: Mutex<Option<Seen>>,
}

impl Runner for Stub {
    fn run(&self, argv: &[String], env: &[(OsString, OsString)], timeout: f64) -> Ran {
        let home = env
            .iter()
            .find(|(key, _)| key == "CODEX_AUTO_RESUME_PLUGIN_HOME")
            .map(|(_, value)| value.to_string_lossy().into_owned());
        *self.seen.lock().unwrap_or_else(|p| p.into_inner()) = Some((argv.to_vec(), home, timeout));
        match pyval::text(field(&self.spec, "raise")) {
            Some("timeout") => return Ran::Timeout,
            Some(_) => return Ran::Failed,
            None => {}
        }
        Ran::Done {
            code: match field(&self.spec, "code") {
                Value::Int(n) => n.as_i64().unwrap_or(-1),
                _ => -1,
            },
            stdout: option_text(field(&self.spec, "stdout")),
        }
    }
}

fn with_py<T>(found: Result<T, &'static str>, make: impl FnOnce(T) -> Value) -> Value {
    match found {
        Ok(value) => ok(make(value)),
        Err(class) => raised(class),
    }
}

/// One `registry.*` operation.
pub fn run(case: &mut Case, op: &str, args: &[Value]) -> Value {
    let arg = |at: usize| args.get(at).cloned().unwrap_or(Value::Null);
    let world: Arc<dyn System> = Arc::clone(&case.world) as Arc<dyn System>;
    let system: &dyn System = world.as_ref();
    let sources_of = |value: &Value| -> Result<Vec<(String, Option<Document>, bool)>, Value> {
        let Value::Array(items) = value else {
            return Ok(Vec::new());
        };
        let mut out = Vec::new();
        for item in items {
            let Value::Array(parts) = item else { continue };
            let name = text_of(parts.first().unwrap_or(&Value::Null));
            let doc = document(parts.get(1).unwrap_or(&Value::Null))?;
            out.push((
                name,
                doc,
                pyval::truthy(parts.get(2).unwrap_or(&Value::Null)),
            ));
        }
        Ok(out)
    };
    macro_rules! sources {
        ($value:expr) => {
            match sources_of($value) {
                Ok(found) => found,
                Err(refused) => return refused,
            }
        };
    }
    macro_rules! borrowed {
        ($owned:expr) => {
            $owned
                .iter()
                .map(|(name, doc, allowed)| (name.as_str(), doc.as_ref(), *allowed))
                .collect::<Vec<_>>()
        };
    }
    match op {
        "registry.standing" => {
            let (doc, bundled) = match (document(&arg(0)), document(&arg(2))) {
                (Ok(Some(doc)), Ok(bundled)) => (doc, bundled),
                (Err(refused), _) | (_, Err(refused)) => return refused,
                _ => return raised("TypeError"),
            };
            ok(Value::from(standing::document_standing(
                &doc,
                &text_of(&arg(1)),
                bundled.as_ref(),
                number(&arg(3)),
                pyval::is(&arg(4), "bundled"),
            )))
        }
        "registry.evidence" => {
            let owned = sources!(&arg(2));
            let (state, source, why) =
                standing::evidence_for(&text_of(&arg(0)), &arg(1), &borrowed!(owned));
            ok(Value::Array(vec![
                state.map_or(Value::Null, Value::from),
                source.map_or(Value::Null, Value::from),
                why.as_deref().map_or(Value::Null, Value::from),
            ]))
        }
        "registry.evaluate" => {
            let owned = sources!(&arg(2));
            let checks = match arg(0) {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            ok(Value::Object(standing::evaluate(
                &checks,
                &arg(1),
                &borrowed!(owned),
            )))
        }
        "registry.accepted" => {
            let owned = sources!(&arg(1));
            ok(Value::from(standing::accepted_word(
                &arg(0),
                &borrowed!(owned),
            )))
        }
        "registry.verified" => match document(&arg(0)) {
            Ok(doc) => ok(texts(&standing::verified_versions(doc.as_ref()))),
            Err(refused) => refused,
        },
        "registry.combine" => {
            let items = match arg(0) {
                Value::Array(items) => items,
                _ => Vec::new(),
            };
            let refs: Vec<&Value> = items.iter().collect();
            ok(Value::from(standing::combine(&refs)))
        }
        "registry.resolve" => {
            let local = text_of(&arg(0));
            let evidence = option_text(&arg(1));
            let (state, reason) = standing::resolve(
                if matches!(arg(0), Value::Str(_)) {
                    &local
                } else {
                    ""
                },
                evidence.as_deref(),
            );
            ok(Value::Array(vec![Value::from(state), Value::from(reason)]))
        }
        "registry.aggregate" => {
            let names: Vec<String> = match arg(1) {
                Value::Array(items) => items.iter().map(text_of).collect(),
                _ => standing::SEND_GATE
                    .iter()
                    .map(|each| (*each).to_owned())
                    .collect(),
            };
            let names: Vec<&str> = names.iter().map(String::as_str).collect();
            with_py(standing::aggregate(&arg(0), &names), Value::from)
        }
        "registry.validate_report" => {
            let now = match arg(1) {
                Value::Null => None,
                other => Some(number(&other)),
            };
            with_py(report::validate_report(&arg(0), now), |found| {
                found.unwrap_or(Value::Null)
            })
        }
        "registry.build_report" => {
            let checks = match arg(4) {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            let acting = option_text(&arg(6));
            with_py(
                report::build_report(
                    number(&arg(0)),
                    &text_of(&arg(1)),
                    arg(2),
                    arg(3),
                    &checks,
                    arg(5),
                    acting.as_deref(),
                ),
                |found| found,
            )
        }
        "registry.unusable_view" => {
            let engine = arg(3);
            ok(report::unusable_view(
                &text_of(&arg(0)),
                arg(1),
                arg(2),
                (!matches!(engine, Value::Null)).then_some(&engine),
            ))
        }
        "registry.view_of" => ok(report::view_of(&arg(0))),
        "registry.mcp_view" => with_py(report::mcp_view(&arg(0)), |found| found),
        "registry.finite_number" => with_py(report::finite_number(&arg(0)), Value::Bool),
        "registry.reported_parse" => {
            let path = text_of(&arg(0));
            match files::read_capped(&path, reported::MAX_BYTES)
                .and_then(|raw| reported::parse(&raw))
            {
                Ok(table) => ok(table_value(&table)),
                Err(refused) => document_error(refused.code),
            }
        }
        "registry.reported_read" => {
            with_py(reported::read(&text_of(&arg(0))), |(standing, table)| {
                Value::Array(vec![Value::from(standing), table_value(&table)])
            })
        }
        "registry.reported_lookup" => {
            with_py(reported::lookup(&arg(0), &text_of(&arg(1))), |found| found)
        }
        "registry.read_capped" => {
            let limit = number(&arg(1)) as usize;
            match files::read_capped(&text_of(&arg(0)), limit) {
                Ok(bytes) => ok(Value::from(hex(&bytes).as_str())),
                Err(refused) => document_error(refused.code),
            }
        }
        "registry.stamp" => with_py(files::signature(&text_of(&arg(0))), |found| found),
        "registry.product_version" => ok(Value::from(
            files::product_version(&text_of(&arg(0))).as_str(),
        )),
        "registry.load_bundled" => {
            let (doc, state) = files::load_bundled(&text_of(&arg(0)), &text_of(&arg(1)));
            ok(Value::Array(vec![
                doc.as_ref().map_or(Value::Null, Document::to_value),
                Value::from(state),
            ]))
        }
        "registry.bundled_verified" => ok(texts(&files::bundled_verified_versions(
            &text_of(&arg(0)),
            &files::product_version(&text_of(&arg(1))),
        ))),
        "registry.write_json" => {
            match files::write_json_atomic(&text_of(&arg(0)), &arg(1), &text_of(&arg(2))) {
                Ok(()) => ok(Value::Null),
                Err(_) => failed(&Error::Os),
            }
        }
        "registry.path_digest" => ok(files::path_digest(system, &text_of(&arg(0)))
            .map_or(Value::Null, |each| Value::from(each.as_str()))),
        "registry.read_cache" => {
            let product = text_of(&arg(2));
            let bundled =
                option_text(&arg(1)).and_then(|path| files::load_bundled(&path, &product).0);
            ok(cache::read_cache(
                &text_of(&arg(0)),
                bundled.as_ref(),
                &product,
                number(&arg(3)),
            )
            .to_value())
        }
        "registry.judge_cache" => {
            let product = text_of(&arg(2));
            let bundled =
                option_text(&arg(1)).and_then(|path| files::load_bundled(&path, &product).0);
            let first: Cache = cache::read_cache(
                &text_of(&arg(0)),
                bundled.as_ref(),
                &product,
                number(&arg(3)),
            );
            ok(cache::judge_cache(&first, bundled.as_ref(), &product, number(&arg(4))).to_value())
        }
        "registry.import" => {
            let ensure_ok = !matches!(arg(6), Value::Bool(false));
            let ensure = move || ensure_ok;
            let file = option_text(&arg(2));
            ok(cache::import_document(
                &text_of(&arg(0)),
                &text_of(&arg(1)),
                &ensure,
                file.as_deref(),
                &arg(3),
                &text_of(&arg(4)),
                number(&arg(5)),
            ))
        }
        "registry.engine_word" => ok(Value::from(cache::engine_word(
            &text_of(&arg(0)),
            &text_of(&arg(1)),
            &arg(2),
            &files::product_version(&text_of(&arg(3))),
            number(&arg(4)),
        ))),
        "registry.coerce" => ok(Value::from(cache::coerce(&arg(0)))),
        "registry.source_checks" => ok(Value::Object(probes::source_checks(
            system,
            &probes::source_home(&text_of(&arg(0))),
        ))),
        "registry.seed" => {
            let results = match &arg(0) {
                Value::Object(map) => map
                    .iter()
                    .filter_map(|(method, entry)| match entry {
                        Value::Array(parts) if parts.len() == 2 => Some((
                            method.as_str().unwrap_or_default().to_owned(),
                            (text_of(&parts[0]), number(&parts[1]) as u64),
                        )),
                        _ => None,
                    })
                    .collect(),
                _ => Vec::new(),
            };
            car_codex::appserver::set_results(results);
            ok(Value::Null)
        }
        "registry.api_checks" => ok(Value::Object(probes::api_checks(system))),
        "registry.protocol_check" => ok(Value::from(probes::protocol_check(&text_of(&arg(0))))),
        "registry.engine_part" => ok(Value::Object(probes::engine_part(&arg(0)))),
        "registry.engine_from_discovery" => {
            let candidates = match arg(1) {
                Value::Int(n) => n.as_i64(),
                _ => None,
            };
            match probes::engine_from_discovery(system, &discovery_of(&arg(0)), candidates) {
                Ok((checks, engine)) => ok(Value::Array(vec![Value::Object(checks), engine])),
                Err(error) => failed(&error),
            }
        }
        "registry.engine_from_backend" => match case.backend.as_mut() {
            Some(backend) => {
                let (checks, engine) = probes::engine_from_backend(backend);
                ok(Value::Array(vec![Value::Object(checks), engine]))
            }
            None => failed(&Error::Python("AttributeError")),
        },
        "registry.server_check" => match case.backend.as_ref() {
            Some(backend) => ok(Value::from(probes::server_check(backend))),
            None => failed(&Error::Python("AttributeError")),
        },
        "registry.candidate_paths" => {
            let config = car_config::Os::here(false, crate::links::for_config());
            let explicit = option_text(&arg(0));
            ok(texts(&probes::candidate_paths(
                system,
                &config,
                explicit.as_deref(),
            )))
        }
        "registry.served_engines" => ok(texts(&probes::served_engines(system))),
        "registry.package_engines" => ok(texts(
            &probes::official(system, probes::package_engines(system)).collect::<Vec<_>>(),
        )),
        "registry.read_report" => with_py(
            views::read_report(&text_of(&arg(0)), number(&arg(1))),
            |(found, status)| Value::Array(vec![found.unwrap_or(Value::Null), Value::from(status)]),
        ),
        "registry.watchers_server_check" => with_py(
            views::watchers_server_check(&text_of(&arg(0)), number(&arg(1))),
            |found| found,
        ),
        "registry.binding" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            let explicit = option_text(&arg(2));
            ok(Value::Bool(views::binding_holds(
                &registry,
                &arg(1),
                explicit.as_deref(),
            )))
        }
        "registry.read_view" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            let explicit = option_text(&arg(2));
            with_py(
                views::read_view(&registry, number(&arg(1)), explicit.as_deref()),
                |found| found,
            )
        }
        "registry.reader_view" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            with_py(
                views::reader_view(&registry, number(&arg(1)), &arg(2)),
                |found| found,
            )
        }
        "registry.reported_for" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            with_py(views::reported_for(&registry, &arg(1)), |found| found)
        }
        "registry.assemble" => {
            let product = text_of(&arg(5));
            let (bundled, bundled_state) = files::load_bundled(&text_of(&arg(3)), &product);
            let now = number(&arg(6));
            let cache = cache::read_cache(&text_of(&arg(4)), bundled.as_ref(), &product, now);
            let as_map = |value: Value| match value {
                Value::Object(map) => map,
                _ => Map::new(),
            };
            let acting = option_text(&arg(7));
            with_py(
                views::assemble(
                    &as_map(arg(0)),
                    &arg(1),
                    &as_map(arg(2)),
                    bundled.as_ref(),
                    bundled_state,
                    &cache,
                    &product,
                    now,
                    acting.as_deref(),
                ),
                |found| found,
            )
        }
        "registry.live_report" | "registry.live_view" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            let discovery = match arg(2) {
                Value::Null => None,
                other => Some(discovery_of(&other)),
            };
            let explicit = option_text(&arg(3));
            let backend = if pyval::truthy(&arg(5)) {
                case.backend.as_mut()
            } else {
                None
            };
            let found = if op == "registry.live_report" {
                views::live_report(
                    &registry,
                    &text_of(&arg(1)),
                    backend,
                    discovery,
                    explicit.as_deref(),
                    number(&arg(4)),
                )
            } else {
                views::live_view(
                    &registry,
                    &text_of(&arg(1)),
                    backend,
                    discovery,
                    explicit.as_deref(),
                    number(&arg(4)),
                )
            };
            match found {
                Ok(found) => ok(found),
                Err(error) => failed(&error),
            }
        }
        "registry.evaluator.new" => {
            let registry = registry_of(&arg(0), Arc::clone(&world));
            let said = Arc::clone(&case.registry.said);
            let clock_world = Arc::clone(&case.world);
            let explicit = option_text(&arg(2));
            let product = option_text(&arg(3));
            let recompute = match arg(4) {
                Value::Null => None,
                other => Some(number(&other)),
            };
            case.registry.evaluator = Some(Evaluator::new(
                registry,
                &text_of(&arg(1)),
                explicit.as_deref(),
                product.as_deref(),
                Box::new(move |line: &str| {
                    said.lock()
                        .unwrap_or_else(|p| p.into_inner())
                        .push(line.to_owned());
                }),
                Box::new(move || clock_world.monotonic()),
                recompute,
            ));
            ok(Value::Null)
        }
        "registry.evaluator.tick" => {
            let discovery = discovery_of(&arg(0));
            let backend = if pyval::truthy(&arg(1)) {
                case.backend.as_mut()
            } else {
                None
            };
            let Some(evaluator) = case.registry.evaluator.as_mut() else {
                return failed(&Error::Python("AttributeError"));
            };
            let found = evaluator.tick(backend, &discovery);
            let said: Vec<String> =
                std::mem::take(&mut *case.registry.said.lock().unwrap_or_else(|p| p.into_inner()));
            match found {
                Ok(acting) => ok(object([
                    ("acting", Value::from(acting)),
                    ("said", texts(&said)),
                ])),
                Err(error) => failed(&error),
            }
        }
        "registry.evaluator.state" => match case.registry.evaluator.as_ref() {
            Some(evaluator) => ok(object([
                ("report", evaluator.report.clone().unwrap_or(Value::Null)),
                ("cache", evaluator.cache.to_value()),
                ("bundled_state", Value::from(evaluator.bundled_state)),
                ("acting", evaluator.acting.map_or(Value::Null, Value::from)),
            ])),
            None => failed(&Error::Python("AttributeError")),
        },
        "registry.run_refresh" => {
            let stub = Stub {
                spec: arg(4),
                seen: Mutex::new(None),
            };
            let env: Vec<(OsString, OsString)> = std::env::vars_os().collect();
            let timeout = match arg(3) {
                Value::Null => None,
                other => Some(number(&other)),
            };
            let script = option_text(&arg(1));
            let found = evaluator::run_refresh(
                &text_of(&arg(0)),
                script.as_deref(),
                &text_of(&arg(2)),
                &env,
                timeout,
                &stub,
            );
            let seen = stub.seen.lock().unwrap_or_else(|p| p.into_inner()).clone();
            let seen = seen.map_or(Value::Null, |(argv, home, timeout)| {
                object([
                    ("argv", texts(&argv)),
                    (
                        "home",
                        home.map_or(Value::Null, |each| Value::from(each.as_str())),
                    ),
                    ("timeout", Value::Float(timeout)),
                ])
            });
            match found {
                Ok(answer) => ok(object([("answer", answer), ("seen", seen)])),
                Err(error) => failed(&error),
            }
        }
        other => object([("error", Value::from(format!("NotPorted:{other}").as_str()))]),
    }
}

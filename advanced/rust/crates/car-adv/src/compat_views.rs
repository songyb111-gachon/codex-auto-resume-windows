//! The Compatibility Registry's two views as `arming.py` asks for them (`_view_of`, `_live_view_of`), over S3.3's registry.
//!
//! `seam::Edges::default_view` and `default_live_view` are these two functions of the tag's `arming.py`:
//!
//! * `_view_of(paths)`: `compatio.reader_view(paths, settings=settings.load(paths.settings_file))` - the view the watcher last
//!   wrote, bound to the engine the settings name;
//! * `_live_view_of(paths)`: `compatio.live_view(paths, config.codex_home(), explicit=...)` - a fresh check of the Codex here,
//!   written nowhere, the explicit engine being `settings["codex_exe"]` or else `CODEX_EXE` or none.
//!
//! [`CompatViews`] is those two over car-codex's `compat::views` (S3.3). A host that implements `Edges` delegates to it; any
//! failure is `Unavailable`, as the tag's `except Exception` around each is (nothing more is said of why).

use std::path::PathBuf;

use car_codex::compat::views::{Registry, live_view, reader_view};
use car_codex::system::PolicyOs;
use car_machine::json::Value;

use crate::seam::Unavailable;

/// A clock the views read their `now` from (`time.time()`).
pub type Now = Box<dyn Fn() -> f64 + Send + Sync>;

pub struct CompatViews {
    /// Where the registry's files are and what asks the machine (`views::Registry`).
    pub registry: Registry,
    /// `config.codex_home()`.
    pub codex_home: String,
    /// `paths.settings_file`.
    pub settings_file: PathBuf,
    pub now: Now,
}

impl CompatViews {
    /// `settings.load(paths.settings_file)`.
    fn settings(&self) -> Result<car_machine::json::Map, Unavailable> {
        car_policy::settings::load(&PolicyOs, &self.settings_file).map_err(|_| Unavailable)
    }

    /// `_view_of(paths)`.
    pub fn default_view(&self) -> Result<Value, Unavailable> {
        let settings = Value::Object(self.settings()?);
        reader_view(&self.registry, (self.now)(), &settings).map_err(|_| Unavailable)
    }

    /// `_live_view_of(paths)`.
    pub fn default_live_view(&self) -> Result<Value, Unavailable> {
        let settings = self.settings()?;
        // `settings.get("codex_exe") or ...`: a non-empty text wins over CODEX_EXE, a lone surrogate in it too (the
        // path then names no file, as the reference's does).
        let named = match settings.get("codex_exe") {
            Some(Value::Str(text)) if !text.is_empty() => Some(
                text.as_str()
                    .map(str::to_owned)
                    .unwrap_or_else(|| String::from_utf8_lossy(text.as_bytes()).into_owned()),
            ),
            _ => None,
        };
        let explicit = named.or_else(|| {
            self.registry
                .system
                .env(car_config::paths::ENV_CODEX_EXE)
                .filter(|each| !each.is_empty())
        });
        live_view(
            &self.registry,
            &self.codex_home,
            None,
            None,
            explicit.as_deref(),
            (self.now)(),
        )
        .map_err(|_| Unavailable)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use car_codex::errors::Result;
    use car_codex::system::System;

    use super::*;

    /// A machine with nothing on it: no environment, no process, no engine.
    #[derive(Debug)]
    struct Empty;

    impl System for Empty {
        fn env(&self, _name: &str) -> Option<String> {
            None
        }
        fn processes_named(&self, _names: &[&str], _families: &[&str]) -> Result<Vec<Value>> {
            Ok(Vec::new())
        }
        fn resource_users(&self, _paths: &[String]) -> Result<Vec<Value>> {
            Ok(Vec::new())
        }
        fn process_identity(&self, _pid: &Value) -> Result<Value> {
            Ok(Value::Null)
        }
        fn signer(&self, _path: &str) -> std::result::Result<String, Option<&'static str>> {
            Err(None)
        }
        fn own_pid(&self) -> i64 {
            1
        }
        fn monotonic(&self) -> f64 {
            0.0
        }
        fn resolve(&self, text: &str) -> Option<String> {
            Some(text.to_owned())
        }
        fn restart_manager_available(&self) -> bool {
            false
        }

        fn package_roots(&self, _family: &str) -> car_codex::errors::Result<Vec<String>> {
            Ok(Vec::new())
        }
    }

    #[derive(Debug)]
    struct Links;

    impl car_config::Links for Links {
        fn is_symlink(&self, path: &std::path::Path) -> bool {
            car_platform::links::is_symlink(path)
        }
    }

    fn views(home: &std::path::Path) -> CompatViews {
        let config = home.join("config");
        let text = |path: PathBuf| path.to_string_lossy().into_owned();
        CompatViews {
            registry: Registry {
                system: Arc::new(Empty),
                config: car_config::Os::here(false, Arc::new(Links)),
                bundled: text(home.join("data").join("codex_compat.json")),
                reported: text(home.join("data").join("reported.json")),
                cache_file: text(config.join("compat-cache.json")),
                report_file: text(config.join("compatibility.json")),
                version: "0.0.0".into(),
            },
            codex_home: text(home.join("codex-home")),
            settings_file: config.join("settings.json"),
            now: Box::new(|| 1_800_000_000.0),
        }
    }

    #[test]
    fn both_views_are_answered_on_a_scratch_home_with_no_engine() {
        let home =
            std::env::temp_dir().join(format!("car-adv-compat-views-{}", std::process::id()));
        std::fs::create_dir_all(&home).expect("a scratch home");
        let views = views(&home);
        let seen = views.default_view();
        let live = views.default_live_view();
        let _ = std::fs::remove_dir_all(&home);
        assert!(matches!(seen, Ok(Value::Object(_))), "{seen:?}");
        assert!(matches!(live, Ok(Value::Object(_))), "{live:?}");
    }
}

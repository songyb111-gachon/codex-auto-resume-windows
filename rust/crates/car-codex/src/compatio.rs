//! `compatio.py`: the io half of the Compatibility Registry, as one front - its files, the cache, the local checks,
//! the views and the watcher's evaluator. Every name is the module's own in [`crate::compat`].

pub use crate::compat::cache::{
    Cache, cache_empty, coerce, data_in_force, engine_word, import_document, judge_cache,
    read_cache, sources_of,
};
pub use crate::compat::evaluator::{Evaluator, Ran, Runner, SystemRunner, run_refresh};
pub use crate::compat::files::{
    REFRESH_ANSWERS, REFRESH_EXIT, REFRESH_TIMEOUT_SECONDS, bundled_verified_versions,
    load_bundled, path_digest, product_version, read_capped, signature, stamp, write_json_atomic,
};
pub use crate::compat::probes::{
    api_checks, candidate_paths, discover, engine_from_backend, engine_from_discovery, engine_part,
    source_checks,
};
pub use crate::compat::views::{
    Registry, assemble, binding_holds, live_report, live_view, read_report, read_view, reader_view,
};

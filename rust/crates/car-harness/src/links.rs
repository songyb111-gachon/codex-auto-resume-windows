//! The one link probe, wired into the two crates that take it as a trait (cut C3): car-store's and car-config's `Links`
//! over car-platform's `links::is_symlink` (D3: the one place the core asks Windows for a reparse tag). The entry
//! points wire the same pair in; the harness is the first to.

use std::path::Path;
use std::sync::Arc;

/// `Path.is_symlink()` as car-platform reads it: a real symbolic link only, never a junction.
#[derive(Clone, Copy, Debug)]
pub struct Probe;

impl car_store::session::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
}

impl car_config::Links for Probe {
    fn is_symlink(&self, path: &Path) -> bool {
        car_platform::links::is_symlink(path)
    }
    fn find_first_file(&self, path: &str) -> Result<String, i32> {
        car_platform::paths::find_first_file(path)
    }
    fn engine_refused(&self, path: &str) -> bool {
        car_platform::realengine::refused(cfg!(test), path)
    }
}

/// The probe, for car-store.
pub fn for_store() -> Arc<dyn car_store::session::Links> {
    Arc::new(Probe)
}

/// The probe, for car-config.
pub fn for_config() -> Arc<dyn car_config::Links> {
    Arc::new(Probe)
}

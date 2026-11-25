//! Review 5: a save over a file another handle holds open with FILE_SHARE_DELETE (REVIEW-int5.md).
//!
//! settings.py `save` ends in `os.replace(temporary, target)`, which is `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`
//! and nothing else: with the target open by a handle that shares delete, Windows answers ERROR_ACCESS_DENIED, the
//! save raises SettingsError("cannot save settings") and the file keeps its bytes (measured with Python 3.13.15,
//! PermissionError winerror 5). `std::fs::rename` retries that error with `SetFileInformationByHandle(FileRenameInfoEx,
//! FILE_RENAME_FLAG_POSIX_SEMANTICS | FILE_RENAME_FLAG_REPLACE_IF_EXISTS)` (library/std/src/sys/fs/windows.rs, `rename`),
//! which replaces the file under the open handle. Every handle std opens shares delete, so another Rust process
//! reading the file is enough; so is any program that opens it as std does. The same rename ends statusfile.rs's
//! write, chains.rs's `write_atomically` and car-config's log rollover.

use std::os::windows::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use car_machine::json::{Map, Value};
use car_policy::settings::os::Os;
use car_policy::settings::{SettingsError, save};

struct Plain;

impl Os for Plain {
    fn is_symlink(&self, _path: &Path) -> bool {
        false
    }
    fn is_junction(&self, _path: &Path) -> bool {
        false
    }
    fn normcase(&self, text: &[u16]) -> Vec<u16> {
        text.to_vec()
    }
    fn abspath(&self, text: &[u16]) -> Vec<u16> {
        text.to_vec()
    }
    fn resolve(&self, text: &[u16]) -> Result<Vec<u16>, &'static str> {
        Ok(text.to_vec())
    }
}

fn scratch() -> PathBuf {
    let folder =
        std::env::temp_dir().join(format!("car-v0627-review5-replace-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    std::fs::create_dir_all(&folder).unwrap();
    folder
}

#[test]
fn a_save_under_a_share_delete_handle_is_refused_as_os_replace_refuses_it() {
    let folder = scratch();
    let target = folder.join("settings.json");
    std::fs::write(&target, b"{}").unwrap();
    let held = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0x1 | 0x2 | 0x4)
        .open(&target)
        .unwrap();
    let answer = save(&Plain, &target, &Value::Object(Map::new()));
    let kept = std::fs::read(&target).unwrap();
    drop(held);
    let _ = std::fs::remove_dir_all(&folder);
    assert!(
        matches!(&answer, Err(SettingsError::Refused(text)) if text.as_str() == Some("cannot save settings")),
        "the reference refuses the save (PermissionError 5 from os.replace); Rust answered {answer:?}"
    );
    assert_eq!(kept, b"{}", "the reference leaves the file as it was");
}

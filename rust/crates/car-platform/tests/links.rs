//! The link probe: a junction is a folder, as CPython's `Path.is_symlink()` has it, and a real symbolic link is a link.
//!
//! A junction cannot be made without starting `cmd /c mklink /J` (`CREATE_NO_WINDOW`); the golden test that holds
//! process starting to `spawn.rs` reads `src/` and `examples/`, not this folder.

use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::Command;

use car_platform::links::{MOUNT_POINT_TAG, SYMLINK_TAG, is_symlink, reparse_tag};

fn mklink(arguments: &[&str], link: &Path, target: &Path) -> bool {
    Command::new("cmd")
        .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
        .args(["/c", "mklink"])
        .args(arguments)
        .arg(link)
        .arg(target)
        .output()
        .is_ok_and(|made| made.status.success())
}

#[test]
fn a_junction_is_a_folder_and_a_folder_is_not_a_link() {
    let base = std::env::temp_dir().join(format!("car-platform-links-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&base);
    std::fs::create_dir_all(base.join("target")).unwrap();
    std::fs::write(base.join("target").join("file.txt"), "x").unwrap();
    assert!(
        mklink(&["/J"], &base.join("junction"), &base.join("target")),
        "mklink /J failed"
    );
    assert!(
        std::fs::symlink_metadata(base.join("junction"))
            .unwrap()
            .file_type()
            .is_symlink(),
        "std counts a junction as a link"
    );
    assert_eq!(reparse_tag(&base.join("junction")), Some(MOUNT_POINT_TAG));
    assert!(
        !is_symlink(&base.join("junction")),
        "Python's is_symlink() is false for a junction"
    );
    assert!(!is_symlink(&base.join("target")));
    assert!(!is_symlink(&base.join("target").join("file.txt")));
    assert!(!is_symlink(&base.join("missing")));
    assert_eq!(reparse_tag(&base.join("target")), None);
    // A symbolic link needs a privilege (or Developer Mode) on Windows; where it is refused there is nothing to prove.
    if mklink(&["/D"], &base.join("symlink"), &base.join("target")) {
        assert_eq!(reparse_tag(&base.join("symlink")), Some(SYMLINK_TAG));
        assert!(is_symlink(&base.join("symlink")));
        std::fs::remove_dir(base.join("symlink")).unwrap();
    }
    std::fs::remove_dir(base.join("junction")).unwrap();
    std::fs::remove_dir_all(&base).unwrap();
}

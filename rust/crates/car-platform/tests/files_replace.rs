//! `files::replace` and `files::rename` are os.replace and os.rename (review 5, S2): MoveFileExW alone. A target
//! another handle holds open with FILE_SHARE_DELETE is not replaced (5), where std's rename would replace it; an
//! existing target is not renamed over (183).

use std::os::windows::fs::OpenOptionsExt;

use car_platform::files::{rename, replace};

#[test]
fn a_held_target_is_refused_as_os_replace_refuses_it() {
    let folder = std::env::temp_dir().join(format!("car-platform-replace-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&folder);
    std::fs::create_dir_all(&folder).unwrap();
    let (from, to) = (folder.join("new"), folder.join("target"));
    std::fs::write(&from, b"new").unwrap();
    std::fs::write(&to, b"old").unwrap();
    {
        let _held = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(0x1 | 0x2 | 0x4)
            .open(&to)
            .unwrap();
        assert_eq!(replace(&from, &to).unwrap_err().raw_os_error(), Some(5));
    }
    assert_eq!(std::fs::read(&to).unwrap(), b"old");
    assert_eq!(rename(&from, &to).unwrap_err().raw_os_error(), Some(183));
    replace(&from, &to).unwrap();
    assert_eq!(std::fs::read(&to).unwrap(), b"new");
    let _ = std::fs::remove_dir_all(&folder);
}

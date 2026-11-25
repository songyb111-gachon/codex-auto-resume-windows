//! The power-action guard, as a process the Python suite starts sees it (review 4, S3): with `CAR_NO_POWER_ACTION`
//! set (every test runner of the repository sets it) `act` refuses, without it a library built for use does not. The
//! question is asked of `refuses()`; `act` is never called, so nothing here can sleep or shut down this PC.

use std::os::windows::process::CommandExt;
use std::process::Command;

use car_platform::powerdown;

const CHILD: &str = "CAR_POWER_GUARD_CHILD";
const NAME: &str = "the_variable_refuses_every_power_action";

#[test]
fn the_variable_refuses_every_power_action() {
    if let Some(expected) = std::env::var_os(CHILD) {
        assert_eq!(powerdown::refuses(), expected == "set");
        return;
    }
    let me = std::env::current_exe().unwrap();
    for set in [true, false] {
        let mut child = Command::new(&me);
        child
            .args(["--exact", NAME, "--test-threads=1", "--quiet"])
            .env(CHILD, if set { "set" } else { "unset" })
            .creation_flags(car_platform::spawn::CREATE_NO_WINDOW);
        if set {
            child.env(powerdown::NO_POWER_ACTION, "1");
        } else {
            child.env_remove(powerdown::NO_POWER_ACTION);
        }
        let done = child.output().unwrap();
        assert!(
            done.status.success(),
            "with the variable {}: {}",
            if set { "set" } else { "unset" },
            String::from_utf8_lossy(&done.stdout)
        );
    }
}

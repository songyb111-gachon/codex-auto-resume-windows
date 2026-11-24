//! The real registry writer, on a private hive (brief rule 3: never HKCU).
//!
//! `PrivateHive` loads a scratch file as an application hive (`RegLoadAppKey`): a registry of its own that only this
//! process sees, which `WinRegistry` is pointed at in place of HKEY_CURRENT_USER and HKEY_LOCAL_MACHINE. The same
//! steps then run on the real Win32 writer and on the in-memory stand-in, and the answers (and every value read back)
//! must be equal: the stand-in the differential tests use is the real thing's behaviour.

use car_platform::addremove;
use car_platform::registry::{FakeRegistry, PrivateHive, Registry, Value};
use car_platform::startup;

/// Two editions by invented names: this crate names no real edition (the standard workspace names none).
const EDITIONS: [&str; 2] = ["standard", "second"];

fn steps(registry: &dyn Registry, home: &std::path::Path) -> Vec<String> {
    let mut out = Vec::new();
    let mut note = |text: String| out.push(text);
    let command = "\"C:\\Program Files\\Codex Auto Resume\\runtime\\pythonw.exe\" \"C:\\x\\auto_resume.py\" run";
    note(format!("{:?}", startup::current_value(registry)));
    note(format!("{:?}", startup::install(registry, command)));
    note(format!("{:?}", startup::current_value(registry)));
    note(format!("{:?}", startup::install(registry, command)));
    note(format!("{:?}", startup::uninstall(registry)));
    note(format!("{:?}", startup::uninstall(registry)));
    note(format!("{:?}", startup::aumid_registration(registry)));
    note(format!("{:?}", startup::register_aumid(registry, None)));
    note(format!("{:?}", startup::register_aumid(registry, None)));
    note(format!("{:?}", startup::aumid_registration(registry)));
    note(format!("{:?}", startup::unregister_aumid(registry)));
    note(format!("{:?}", startup::protocol_value(registry)));
    note(format!(
        "{:?}",
        startup::install_protocol(registry, "x.exe \"%1\"")
    ));
    note(format!("{:?}", startup::protocol_value(registry)));
    note(format!("{:?}", startup::uninstall_protocol(registry)));
    note(format!("{:?}", startup::protocol_value(registry)));
    note(format!(
        "{:?}",
        startup::write_key(
            registry,
            "Software\\Example\\Key",
            &[
                ("A".to_string(), Value::Str("two".into())),
                ("B".to_string(), Value::Int(7))
            ]
        )
    ));
    note(format!(
        "{:?}",
        startup::read_key(registry, "Software\\Example\\Key", &["A", "B", "Missing"])
    ));
    note(format!(
        "{:?}",
        startup::delete_key(registry, "Software\\Example\\Key")
    ));
    note(format!(
        "{:?}",
        startup::delete_key(registry, "Software\\Example\\Key")
    ));
    note(format!(
        "{:?}",
        addremove::register(
            registry,
            home,
            "standard",
            &EDITIONS,
            "0.6.27",
            Some("Codex Auto Resume")
        )
    ));
    note(format!("{:?}", addremove::read(registry, "standard")));
    note(format!(
        "{:?}",
        addremove::register(registry, home, "second", &EDITIONS, "0.6.27", None)
    ));
    note(format!("{:?}", addremove::read(registry, "standard")));
    note(format!(
        "{:?}",
        addremove::unregister(registry, home, &EDITIONS)
    ));
    // A Unicode value, a value with a quote and an empty value survive the real writer.
    note(format!(
        "{:?}",
        startup::write_key(
            registry,
            "Software\\Example\\Text",
            &[
                ("한국어".to_string(), Value::Str("한국어 \"x\" 😀".into())),
                ("Empty".to_string(), Value::Str(String::new())),
            ]
        )
    ));
    note(format!(
        "{:?}",
        startup::read_key(registry, "Software\\Example\\Text", &["한국어", "Empty"])
    ));
    out
}

#[test]
fn the_real_writer_on_a_private_hive_does_what_the_stand_in_does() {
    let scratch = std::env::temp_dir().join(format!("car-platform-hive-{}", std::process::id()));
    std::fs::create_dir_all(scratch.join("home").join("uninstall")).unwrap();
    std::fs::write(
        scratch.join("home").join("uninstall").join("install.ps1"),
        "# kept",
    )
    .unwrap();
    let home = scratch.join("home");
    let hive_file = scratch.join("private.hiv");
    let hive =
        PrivateHive::load(&hive_file).expect("RegLoadAppKey: Windows refused a private hive");
    let real = hive.registry();
    let fake = FakeRegistry::new();
    let want = steps(&fake, &home);
    let got = steps(&real, &home);
    assert_eq!(got, want);
    // The writer was over the hive's own handles; HKCU is never opened by this test.
    drop(hive);
    let _ = std::fs::remove_dir_all(&scratch);
}

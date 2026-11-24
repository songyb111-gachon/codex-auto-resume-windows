//! Known answers, taken from the Python reference (tag v0.6.26-beta.2), so `cargo test` alone holds car-platform to them.
//! `tests/rustdiff/platform_diffs.py` is the proof against the reference itself, over generated corpora; these are the
//! few that never move.

use std::collections::HashMap;
use std::path::Path;
use std::time::Duration;

use car_machine::vocab_gen::domain_vocabulary::StateAccess;
use car_platform::registry::{Call, FakeRegistry, Root, Value};
use car_platform::spawn::{
    CREATE_NO_WINDOW, Spawn, SpawnError, Starter, Stream, SystemStarter, last_started_flags,
};
use car_platform::{
    acl, authenticode, cmdline, kernel, names, paths, powerdown, pwsh, registry_reads, startup,
    typeface,
};

const HOME: &str = "c:\\users\\exampleuser";

#[test]
fn object_names_are_the_references() {
    assert_eq!(
        names::mutex_name_for(HOME, "C:\\Users\\ExampleUser\\.codex-auto-resume\\state"),
        "Local\\codex-auto-resume-dc556886f0e42d9b5f81e1bc0778a72239a897c4f2353eb6589e3c416ad069fc"
    );
    assert_eq!(
        names::stop_name_for(HOME, "state"),
        "Local\\codex-auto-resume-stop-71010168b76bfb6826d19d1d744a3bab7a665d3cfeaf0a119626d47aca13215f"
    );
    assert_eq!(
        names::wake_name_for(HOME, "state"),
        "Local\\codex-auto-resume-wake-771c8872713d71187537732b4d9f995f5b1929bfe6012f31cd7ec9e22f1ce799"
    );
    assert_eq!(
        names::demo_name_for(HOME, "한국어 😀"),
        "Local\\codex-auto-resume-demo-dc0aff873934cf508a3b2da3542f649e6b2d97ef44e7aceec7d83c9cb961ac50"
    );
    assert_eq!(names::INSTALL_LOCK, "Local\\CodexAutoResume.Install");
    assert_eq!(
        paths::sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}

#[test]
fn list2cmdline_is_pythons() {
    let cases: [(&[&str], &str); 5] = [
        (&["a b", "c"], "\"a b\" c"),
        (&[""], "\"\""),
        (
            &["say \"hi\"", "x\\", "y z\\\\"],
            "\"say \\\"hi\\\"\" x\\ \"y z\\\\\\\\\"",
        ),
        (
            &["C:\\Program Files\\App\\app.exe", "--home", "D:\\"],
            "\"C:\\Program Files\\App\\app.exe\" --home D:\\",
        ),
        (&["한 국", "a\"b"], "\"한 국\" a\\\"b"),
    ];
    for (arguments, line) in cases {
        assert_eq!(cmdline::list2cmdline(arguments), line, "{arguments:?}");
    }
    assert_eq!(cmdline::quote_argument("C:\\x y\\"), "\"C:\\x y\\\\\"");
    assert_eq!(cmdline::quote_argument("a\"b"), "\"a\\\"b\"");
    assert_eq!(cmdline::quote_argument(""), "\"\"");
    // What Windows parses back is what was quoted (the first word of a command line is the program's, parsed by other
    // rules, so a program comes first).
    for value in ["C:\\x y\\", "a\"b", "한 국", "tail\\\\\\"] {
        let line = format!("x.exe {}", cmdline::quote_argument(value));
        assert_eq!(
            cmdline::parse_command(&line),
            vec!["x.exe".to_string(), value.to_string()],
            "{value:?}"
        );
    }
}

#[test]
fn a_run_value_is_written_with_the_calls_the_reference_makes() {
    let registry = FakeRegistry::new();
    assert_eq!(startup::install(&registry, "cmd run"), Ok(true));
    assert_eq!(startup::install(&registry, "cmd run"), Ok(false));
    let run = startup::RUN_KEY.to_string();
    let slot = format!("HKCU|{run}");
    let calls = registry.calls();
    assert_eq!(
        calls[..5],
        [
            Call::OpenKey {
                root: Root::CurrentUser,
                path: run.clone(),
                access: 0x20019
            },
            Call::CreateKeyEx {
                root: Root::CurrentUser,
                path: run.clone(),
                access: 2
            },
            Call::SetValueEx {
                key: slot.clone(),
                name: "CodexAutoResume".into(),
                kind: 1,
                value: Value::Str("cmd run".into())
            },
            Call::Close { key: slot.clone() },
            Call::OpenKey {
                root: Root::CurrentUser,
                path: run,
                access: 0x20019
            },
        ]
    );
}

#[test]
fn every_process_started_has_create_no_window() {
    assert_eq!(CREATE_NO_WINDOW, 0x0800_0000);
    for extra in [0, 0x0100_0000, 0x0000_0008 | 0x0000_0200, CREATE_NO_WINDOW] {
        assert_eq!(
            Spawn::new(["x.exe"]).with_flags(extra).flags() & CREATE_NO_WINDOW,
            CREATE_NO_WINDOW
        );
    }
    let spawn = Spawn::new(["cmd", "/c", "exit", "3"]);
    let code = SystemStarter
        .run(&spawn, Duration::from_secs(20))
        .expect("cmd runs");
    assert_eq!(code, 3);
    assert_eq!(
        last_started_flags(),
        CREATE_NO_WINDOW,
        "the flags the starter applied to a real child"
    );
    let slow = Spawn::new(["cmd", "/c", "ping -n 30 127.0.0.1"]).with_streams(
        Stream::Null,
        Stream::Null,
        Stream::Null,
    );
    assert!(matches!(
        SystemStarter.run(&slow, Duration::from_millis(300)),
        Err(SpawnError::Timeout)
    ));
    assert_eq!(last_started_flags(), CREATE_NO_WINDOW);
}

#[test]
fn only_the_starter_makes_a_command() {
    let crates = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let starter = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("spawn.rs");
    let mut offenders = Vec::new();
    for entry in std::fs::read_dir(crates).unwrap() {
        let crate_dir = entry.unwrap().path();
        for folder in ["src", "examples"] {
            let mut pending = vec![crate_dir.join(folder)];
            while let Some(dir) = pending.pop() {
                let Ok(listing) = std::fs::read_dir(&dir) else {
                    continue;
                };
                for item in listing {
                    let path = item.unwrap().path();
                    if path.is_dir() {
                        pending.push(path);
                    } else if path.extension().is_some_and(|e| e == "rs") && path != starter {
                        let text = std::fs::read_to_string(&path).unwrap();
                        let calls = text
                            .lines()
                            .filter(|l| !l.trim_start().starts_with("//"))
                            .any(|l| {
                                [
                                    "Command::new",
                                    "CreateProcessW",
                                    "CreateProcessA",
                                    "ShellExecute",
                                ]
                                .iter()
                                .any(|n| l.contains(n))
                            });
                        if calls {
                            offenders.push(path.display().to_string());
                        }
                    }
                }
            }
        }
    }
    assert!(
        offenders.is_empty(),
        "a process is started outside car-platform's spawn.rs: {offenders:?}"
    );
    let text = std::fs::read_to_string(&starter).unwrap();
    assert_eq!(text.matches("Command::new(").count(), 1);
}

#[test]
fn powershell_gets_values_beside_the_script() {
    let environment = pwsh::environment(&[("NAME", Some("it's")), ("OTHER", None)]).unwrap();
    let ours: Vec<_> = environment
        .iter()
        .filter(|(n, _)| n.to_string_lossy().starts_with(pwsh::PREFIX))
        .collect();
    assert_eq!(ours.len(), 2);
    assert!(pwsh::environment(&[("name", Some("x"))]).is_err());
    assert!(pwsh::environment(&[("A", Some("x\0y"))]).is_err());
    assert!(pwsh::environment(&[("A", Some(&"x".repeat(16001)))]).is_err());
    assert_eq!(
        pwsh::reference("A").unwrap(),
        "$env:CODEX_AUTO_RESUME_ARG_A"
    );
    let argv = pwsh::script_argv("powershell.exe", "Write-Output 'x'");
    assert_eq!(
        argv,
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Write-Output 'x'"
        ]
    );
}

#[test]
fn the_host_walk_and_the_owner_rule() {
    let table: HashMap<u32, kernel::HostRow> = HashMap::from([
        (10, (20, 300, None)),
        (20, (30, 200, None)),
        (30, (0, 100, Some("OpenAI.Codex_2p2nqsd0c76g0".to_string()))),
    ]);
    assert_eq!(
        kernel::decide_host(10, &table).as_deref(),
        Some("OpenAI.Codex_2p2nqsd0c76g0")
    );
    let verdict = kernel::host_verdict(10, &table, None);
    assert_eq!(
        (verdict.state, verdict.app.as_deref()),
        ("inside", Some("OpenAI.Codex"))
    );
    // a parent created after its child is not its parent
    let reused = HashMap::from([
        (10, (20, 100, None)),
        (20, (0, 200, Some("A_b".to_string()))),
    ]);
    assert_eq!(kernel::decide_host(10, &reused), None);
    assert_eq!(kernel::host_verdict(99, &table, None).state, "unknown");
    assert!(kernel::trusted_owner(
        Some("S-1-5-32-544"),
        Some("S-1-5-21-1")
    ));
    assert!(!kernel::trusted_owner(
        Some("S-1-5-21-2"),
        Some("S-1-5-21-1")
    ));
    assert!(!kernel::trusted_owner(None, Some("S-1-5-21-1")));
}

#[test]
fn access_list_verdicts() {
    let own = Some("S-1-5-21-1-2-3-1001");
    let none = std::collections::BTreeSet::new();
    let me = vec![
        ("S-1-5-21-1-2-3-1001".to_string(), 0x1F01FF),
        ("S-1-5-18".to_string(), 0x1F01FF),
    ];
    assert_eq!(acl::verdict(Some(&me), own, &none), StateAccess::OwnerOnly);
    let shared = vec![("S-1-1-0".to_string(), 0x1200A9)];
    assert_eq!(acl::verdict(Some(&shared), own, &none), StateAccess::Shared);
    let group = vec![("S-1-5-21-1-2-3-1002".to_string(), 0x1200A9)];
    let sandbox = std::collections::BTreeSet::from(["S-1-5-21-1-2-3-1002".to_string()]);
    assert_eq!(
        acl::verdict(Some(&group), own, &sandbox),
        StateAccess::CodexSandbox
    );
    let writes = vec![("S-1-5-21-1-2-3-1002".to_string(), 0x1F01FF)];
    assert_eq!(
        acl::verdict(Some(&writes), own, &sandbox),
        StateAccess::Shared
    );
    assert_eq!(acl::verdict(None, own, &none), StateAccess::Unknown);
    assert!(acl::is_sandbox_group("CodexSandboxUsers", "PC", 4, "pc"));
    assert!(!acl::is_sandbox_group("CodexSandboxUsers", "PC", 1, "PC"));
    let described = acl::described_entries("D:(A;;FA;;;BA)(D;;FA;;;WD)(A;;FR;;;WD)").unwrap();
    assert_eq!(described.len(), 2);
}

#[test]
fn signature_reasons() {
    assert_eq!(authenticode::reason(0), None);
    assert_eq!(authenticode::reason(0x800B0100), Some("unsigned"));
    assert_eq!(authenticode::reason(0x80096010), Some("signature_invalid"));
    assert_eq!(
        authenticode::reason(0x80070005),
        Some("signature_unreadable")
    );
    assert_eq!(
        authenticode::reason(0x800B0109),
        Some("signature_untrusted")
    );
    assert!(authenticode::signer(Path::new("C:\\no\\such\\file.exe")).is_err());
}

#[test]
fn faces_and_letters() {
    assert_eq!(typeface::letters(&["b a", "ab\u{200b}", "\u{ad}"]), "ab");
    let lacks = |face: &str, text: &str| -> String {
        let own = if face == "Malgun Gothic" { "ế" } else { "" };
        text.chars().filter(|c| own.contains(*c)).collect()
    };
    assert_eq!(typeface::face_for("Malgun Gothic", "ế", &lacks), "Segoe UI");
    assert_eq!(
        typeface::face_for("Malgun Gothic", "abc", &lacks),
        "Malgun Gothic"
    );
    let installed = |face: &str| face == "Malgun Gothic";
    assert_eq!(
        typeface::language_face(Some("ko"), "Segoe UI", "ế", &lacks, &installed),
        "Malgun Gothic"
    );
    assert_eq!(
        typeface::language_face(Some("ja"), "Segoe UI", "ế", &lacks, &installed),
        "Segoe UI"
    );
}

#[test]
fn text_size_factor() {
    assert_eq!(registry_reads::text_factor(Some(150)), 1.5);
    assert_eq!(registry_reads::text_factor(Some(99)), 1.0);
    assert_eq!(registry_reads::text_factor(Some(226)), 1.0);
    assert_eq!(registry_reads::text_factor(None), 1.0);
    assert_eq!(
        registry_reads::fitting(2.0, (100.0, 100.0), (150.0, 400.0)),
        1.5
    );
    assert_eq!(registry_reads::fitting(0.5, (0.0, 0.0), (0.0, 0.0)), 1.0);
}

#[test]
fn the_power_action_is_refused_in_tests() {
    powerdown::refuse_power_actions();
    assert!(!powerdown::act("sleep"));
    assert!(!powerdown::act("hibernate"));
    assert!(!powerdown::act("shut_down"));
    assert!(!powerdown::act("nonsense"));
    assert_eq!(powerdown::available("nonsense"), (false, None));
}

//! car-bin's own table (S5.2): the parsers take what argparse takes, the dispatcher's words, the role registry seam and
//! the launcher's arguments. The behaviour against the reference is `tests/rustdiff/diffs_cli.py`'s.

use car_bin::argparse::{Exit, Got, parse_args};
use car_bin::parsers_gen::{CLI, MCP, PARSERS, SETUP};

fn words(text: &[&str]) -> Vec<String> {
    text.iter().map(|each| (*each).to_owned()).collect()
}

#[test]
fn the_command_line_takes_abbreviations_explicit_values_and_negative_numbers() {
    let parsed = parse_args(
        PARSERS,
        CLI,
        &words(&["--hom=H", "--qu", "logs", "-n", "-5"]),
    )
    .expect("parsed");
    assert_eq!(parsed.get("home"), &Got::Text("H".into()));
    assert!(parsed.get("quiet").on());
    assert_eq!(parsed.get("lines").int(), Some(-5));
    let parsed = parse_args(PARSERS, CLI, &words(&["logs", "-n7"])).expect("parsed");
    assert_eq!(parsed.get("lines").int(), Some(7));
    let parsed = parse_args(PARSERS, CLI, &words(&["enable", "--", "-x"])).expect("parsed");
    assert_eq!(parsed.get("thread_id"), &Got::Text("-x".into()));
}

#[test]
fn errors_are_argparse_s_with_the_subparser_s_usage() {
    let Err(Exit::Error(text)) = parse_args(PARSERS, CLI, &words(&["--co", "x", "status"])) else {
        panic!("an ambiguous option is refused");
    };
    assert!(text.ends_with(
        "auto_resume: error: ambiguous option: --co could match --codex-exe, --codex-home\n"
    ));
    let Err(Exit::Error(text)) =
        parse_args(PARSERS, SETUP, &words(&["downgrade-state", "--to", "9"]))
    else {
        panic!("a choice is held");
    };
    assert!(text.starts_with("usage: plugin_setup downgrade-state"));
    assert!(text.ends_with("argument --to: invalid choice: '9' (choose from '3', '4')\n"));
    assert_eq!(
        parse_args(PARSERS, MCP, &words(&["-h"]))
            .err()
            .map(|exit| exit.code()),
        Some(0)
    );
}

#[test]
fn the_standard_edition_s_roles_are_the_bridge_the_mcp_server_and_the_engine_check() {
    let words: Vec<&str> = car_bin::roles::STANDARD
        .iter()
        .map(|role| role.word)
        .collect();
    assert_eq!(words, ["bridge", "mcp", "engine-trusted"]);
    let setup = car_bin::roles::setup_commands();
    for each in [
        "setup",
        "watcher-running",
        "downgrade-state",
        "remove-entry",
        "desktop-shortcut",
        "claim-home",
    ] {
        assert!(setup.contains(&each), "{each}");
    }
    assert!(!setup.contains(&"run") && !setup.contains(&"activate"));
}

#[test]
fn the_launcher_starts_the_installation_s_core_with_its_home() {
    let env = |name: &str| (name == "USERPROFILE").then(|| r"C:\Users\ExampleUser".to_owned());
    let home = car_bin::launcher::install_home(&env);
    assert_eq!(home, r"C:\Users\ExampleUser\.codex-auto-resume");
    let argv = car_bin::launcher::arguments(&home);
    assert!(argv[0].ends_with(r"app\bin\codex-auto-resume.exe"));
    assert_eq!(&argv[1..], ["mcp", "--home", home.as_str()]);
}

#[test]
fn the_registrations_carry_the_home() {
    let home = r"C:\Users\ExampleUser\.codex-auto-resume";
    let run = car_bin::cli::watcher_command(home);
    assert!(run.contains("\"--home\"") && run.ends_with("\"run\""));
    let protocol = car_bin::cli::protocol_command(home);
    assert!(
        protocol.contains("codex-auto-resume.exe\" \"--home\"")
            && protocol.ends_with("\"activate\" \"%1\"")
    );
}

#[test]
fn a_notice_s_uris_are_read_as_notice_uris_reads_them() {
    use car_bin::uris::{Activation, parse};
    let key = "8".repeat(64);
    assert_eq!(
        parse(&format!("codex-auto-resume:cancel?i={key}&c=1")),
        Activation::Cancel {
            id: key.clone(),
            open_codex: true
        }
    );
    assert_eq!(
        parse("codex-auto-resume:open?page=%20Pending%20"),
        Activation::Open("pending".into())
    );
    assert_eq!(parse("https://example.invalid/"), Activation::Malformed);
}

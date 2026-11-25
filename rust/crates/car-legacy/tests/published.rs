//! car-legacy accepts exactly the command lines published versions use (D9): every line of `data/published.txt`
//! (`rust/tools/legacy_lines.py`, from every tag's own code) is accepted and mapped, nothing in [`ACCEPTED`] is missing
//! from it, and the lines one step away from a published one are refused.

use std::ffi::OsString;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use car_legacy::{ACCEPTED, MCP_CODE, Plan, Program, Refusal, Shape, Target, plan};

const PUBLISHED: &str = include_str!("data/published.txt");
const URI: &str = "codex-auto-resume:dismiss?conversation=00000000-0000-0000-0000-000000000000";
/// What a `{value}` (a thread id, a number of lines) is filled with.
const VALUE: &str = "123e4567-e89b-42d3-a456-426614174000";

/// A scratch installation: `<temp>\car-legacy-<name>-<pid>\home` with a `runtime` folder, and the files the lines name.
struct Scratch {
    root: PathBuf,
    home: PathBuf,
}

impl Scratch {
    fn new(name: &str) -> Self {
        let root = std::env::temp_dir().join(format!("car-legacy-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let home = root.join("home");
        for folder in ["runtime", "app\\scripts", "app\\src", "app\\bin"] {
            std::fs::create_dir_all(home.join(folder)).unwrap();
        }
        std::fs::write(home.join("app\\scripts\\plugin_setup.py"), "").unwrap();
        Scratch { root, home }
    }

    fn exe(&self, program: Program) -> PathBuf {
        self.home.join("runtime").join(program.file_name())
    }

    fn fill(&self, word: &str) -> String {
        if word == "{uri}" {
            return URI.to_string();
        }
        if word == "{value}" {
            return VALUE.to_string();
        }
        word.replace("{home}", &self.home.to_string_lossy())
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn program_named(name: &str) -> Program {
    match name {
        "python.exe" => Program::Console,
        "pythonw.exe" => Program::Windowless,
        other => panic!("published.txt names a program car-legacy is not: {other}"),
    }
}

/// (program, argv template, first tag, last tag) per line of the file.
fn published() -> Vec<(Program, Vec<String>, String, String)> {
    PUBLISHED
        .lines()
        .map(|row| {
            let fields: Vec<&str> = row.split('\t').collect();
            assert!(fields.len() >= 5, "a short row: {row:?}");
            let argv = fields[4..].iter().map(|word| word.to_string()).collect();
            (
                program_named(fields[0]),
                argv,
                fields[1].to_string(),
                fields[2].to_string(),
            )
        })
        .collect()
}

/// A child of the test, with no console window (brief rule 12).
fn quiet(program: PathBuf) -> Command {
    let mut command = Command::new(program);
    command.creation_flags(car_platform::spawn::CREATE_NO_WINDOW);
    command
}

fn os(args: &[String]) -> Vec<OsString> {
    args.iter().map(OsString::from).collect()
}

fn planned(scratch: &Scratch, program: Program, args: &[String]) -> Result<Plan, Refusal> {
    plan(program, &scratch.exe(program), &os(args))
}

#[test]
fn every_published_line_is_accepted_and_handed_on_with_the_words_after_the_script() {
    let scratch = Scratch::new("published");
    let rows = published();
    assert!(rows.len() >= 44, "published.txt has {} lines", rows.len());
    for (program, template, first, last) in rows {
        let args: Vec<String> = template.iter().map(|word| scratch.fill(word)).collect();
        let found = planned(&scratch, program, &args)
            .unwrap_or_else(|refusal| panic!("{first}..{last} {template:?} refused: {refusal:?}"));
        let script = template
            .iter()
            .position(|word| word.ends_with(".py") || word == MCP_CODE)
            .expect("a line names a script or the MCP code");
        let tail: Vec<String> = if found.shape == Shape::Mcp {
            let mut words = vec!["mcp".to_string()];
            words.extend(args[script + 2..].iter().cloned());
            words
        } else {
            args[script + 1..].to_vec()
        };
        assert_eq!(found.args, tail, "{template:?}");
        let expected_target = if found.shape == Shape::Run {
            Target::Host
        } else {
            Target::Core
        };
        assert_eq!(found.target, expected_target, "{template:?}");
        assert_eq!(
            found.program,
            scratch
                .home
                .join("app\\bin")
                .join(expected_target.file_name())
        );
    }
}

#[test]
fn nothing_is_accepted_that_no_published_version_used() {
    let rows: Vec<(Program, Vec<String>)> = published()
        .into_iter()
        .map(|(program, argv, _, _)| (program, argv))
        .collect();
    for line in ACCEPTED {
        let argv: Vec<String> = line.argv.iter().map(|word| word.to_string()).collect();
        assert!(
            rows.contains(&(line.program, argv.clone())),
            "ACCEPTED has a line no tag published: {:?} {argv:?}",
            line.program
        );
    }
    assert_eq!(
        ACCEPTED.len(),
        rows.len(),
        "the file and ACCEPTED list a different number of lines"
    );
}

#[test]
fn a_line_one_step_away_from_a_published_one_is_refused() {
    let scratch = Scratch::new("near");
    let home = scratch.home.to_string_lossy().into_owned();
    let setup = format!("{home}\\app\\scripts\\plugin_setup.py");
    let other = format!("{home}-other\\app\\scripts\\plugin_setup.py");
    let launcher = format!("{home}\\watcher-launcher.py");
    let entry = format!("{home}\\app\\src\\auto_resume.py");
    let source = format!("{home}\\app\\src");
    let words = |list: &[&str]| {
        list.iter()
            .map(|word| word.to_string())
            .collect::<Vec<String>>()
    };
    let console: Vec<Vec<String>> = vec![
        vec![],
        words(&[&setup]),
        words(&[&setup, "Setup", "--keep-state"]),
        words(&[&setup, "setup", "--keep-state", "--keep-state"]),
        words(&[&setup, "setup", "--no-startup", "--keep-state"]),
        words(&[&setup, "setup", "--watcher-was-stopped"]),
        words(&[&setup, "install"]),
        words(&[&setup, "verify-home"]),
        words(&[&setup, "claim-home"]),
        // The skill's commands, one step away from a shape their parser takes.
        words(&[&setup, "Status"]),
        words(&[&setup, "status", "--json"]),
        words(&[&setup, "status", "extra"]),
        words(&[&setup, "cancel"]),
        words(&[&setup, "cancel", "-x"]),
        words(&[&setup, "cancel", "--", "a"]),
        words(&[&setup, "cancel", "a", "b"]),
        words(&[&setup, "logs", "-n"]),
        words(&[&setup, "logs", "--lines", "--purge"]),
        words(&[&setup, "uninstall", "--purge", "extra"]),
        words(&[&setup, "uninstall", "--force"]),
        words(&[&setup, "desktop-shortcut", "make"]),
        words(&[
            "-X",
            "disable-remote-debug",
            &setup,
            "desktop-shortcut",
            "open",
        ]),
        words(&["-X", "disable-remote-debug", &setup, "status"]),
        words(&[&other, "status"]),
        words(&[&setup, "downgrade-state", "--to", "2", "--stop-watcher"]),
        words(&[&setup, "downgrade-state", "--to", "3"]),
        words(&[&setup, "watcher-running", "--home", &home]),
        words(&[&other, "setup", "--keep-state"]),
        words(&["-X", "dev", &setup, "setup", "--keep-state"]),
        words(&[
            "-X",
            "disable_remote_debug",
            &setup,
            "setup",
            "--keep-state",
        ]),
        words(&["-B", &setup, "setup", "--keep-state"]),
        words(&["-m", "codex_auto_resume", "setup"]),
        words(&["-c", "print(1)"]),
        words(&["-I", "-c", "print(1)", &source, "--home", &home]),
        words(&[
            "-I",
            "-c",
            MCP_CODE,
            &source,
            "--home",
            &format!("{home}-other"),
        ]),
        words(&["-c", MCP_CODE, &source, "--home", &home]),
        words(&["-I", "-c", MCP_CODE, &source, "--home", &home, "--verbose"]),
        // The compatibility import every bootstrap guards with controlcli.py, which a Rust archive never carries.
        words(&[
            "-X",
            "disable-remote-debug",
            "-c",
            "x",
            &source,
            "--home",
            &home,
            "compat-import",
            "--file",
            "f",
            "--origin",
            "main",
        ]),
        // A pythonw line given to python.exe.
        words(&[&launcher, "run"]),
    ];
    for args in console {
        assert_eq!(
            planned(&scratch, Program::Console, &args),
            Err(Refusal::Unknown),
            "{args:?}"
        );
    }
    let windowless: Vec<Vec<String>> = vec![
        vec![],
        words(&[&launcher, "Run"]),
        words(&[&launcher, "run", "--home", &home]),
        words(&["-X", "disable-remote-debug", &launcher, "run"]),
        words(&[&launcher, "activate", "https://example.com/"]),
        words(&[&launcher, "activate", "codex-auto-resume"]),
        words(&[&launcher, "--home", &home, "status", "--json"]),
        words(&[&launcher, "--home", &format!("{home}-other"), "status"]),
        words(&[&entry, "status"]),
        words(&[&launcher, "activate"]),
        words(&[&entry, "--home", &format!("{home}-other"), "run"]),
        words(&[&entry, "--home", &home, "activate", URI]),
        words(&[&entry, "run"]),
        // A python.exe line given to pythonw.exe.
        words(&[&setup, "setup", "--keep-state"]),
    ];
    for args in windowless {
        assert_eq!(
            planned(&scratch, Program::Windowless, &args),
            Err(Refusal::Unknown),
            "{args:?}"
        );
    }
}

/// A value is what argparse would take as one: not an option, or `-` alone, a negative number or a word with a space.
#[test]
fn a_value_is_what_the_parser_takes_as_one() {
    let scratch = Scratch::new("values");
    let setup = scratch.fill("{home}\\app\\scripts\\plugin_setup.py");
    for value in [
        "",
        "-",
        "-5",
        "-1.5",
        "-.5",
        "- x",
        "123",
        "not-a-uuid",
        "x y",
    ] {
        let args = vec![setup.clone(), "cancel".to_string(), value.to_string()];
        let found = planned(&scratch, Program::Console, &args)
            .unwrap_or_else(|refusal| panic!("{value:?}: {refusal:?}"));
        assert_eq!(found.args, vec!["cancel".to_string(), value.to_string()]);
        assert_eq!(found.shape, Shape::Command);
    }
    for value in ["-x", "--", "--purge", "-5a", "-1.", "-1.2.3"] {
        let args = vec![
            setup.clone(),
            "logs".to_string(),
            "-n".to_string(),
            value.to_string(),
        ];
        assert_eq!(
            planned(&scratch, Program::Console, &args),
            Err(Refusal::Unknown),
            "{value:?}"
        );
    }
    // `codex-auto-resume:` alone is a URI of the scheme: the old handler handed it to its parser too.
    let launcher = scratch.fill("{home}\\watcher-launcher.py");
    let bare = vec![
        launcher,
        "activate".to_string(),
        "codex-auto-resume:".to_string(),
    ];
    assert!(planned(&scratch, Program::Windowless, &bare).is_ok());
}

#[test]
fn the_home_is_the_folder_above_runtime_in_any_spelling() {
    let scratch = Scratch::new("spelling");
    let upper = scratch.home.to_string_lossy().to_uppercase();
    let args = vec![
        format!("{upper}\\APP\\SCRIPTS\\PLUGIN_SETUP.PY"),
        "watcher-running".to_string(),
    ];
    let found = planned(&scratch, Program::Console, &args).expect("the same folder in capitals");
    assert_eq!(found.args, vec!["watcher-running".to_string()]);
    let slashed = vec![
        format!(
            "{}/app/scripts/plugin_setup.py",
            scratch.home.to_string_lossy()
        ),
        "remove-entry".to_string(),
    ];
    assert!(planned(&scratch, Program::Console, &slashed).is_ok());
    // The long-path prefix Windows and Python take a path with: the same script.
    let prefixed = vec![
        format!(
            "\\\\?\\{}\\app\\scripts\\plugin_setup.py",
            scratch.home.to_string_lossy()
        ),
        "status".to_string(),
    ];
    assert!(
        planned(&scratch, Program::Console, &prefixed).is_ok(),
        "{prefixed:?}"
    );
    let elsewhere = scratch.root.join("python.exe");
    assert_eq!(
        plan(Program::Console, &elsewhere, &os(&args)),
        Err(Refusal::NotInstalled)
    );
}

#[test]
fn an_argument_that_is_not_text_is_refused() {
    use std::os::windows::ffi::OsStringExt;
    let scratch = Scratch::new("text");
    let lone = OsString::from_wide(&[0xD800]);
    let args = vec![
        OsString::from(scratch.fill("{home}\\app\\scripts\\plugin_setup.py")),
        lone,
    ];
    assert_eq!(
        plan(Program::Console, &scratch.exe(Program::Console), &args),
        Err(Refusal::NotText)
    );
}

/// The stand-in run for real, in a scratch installation, with a copy of itself as the Rust program it hands on to:
/// the copy refuses what it is given (it sits in `app\bin`, not `runtime`), and its line names the words it got.
#[test]
fn the_stand_in_hands_the_words_on_and_ends_with_the_programs_code() {
    let scratch = Scratch::new("run");
    let built = Path::new(env!("CARGO_BIN_EXE_python"));
    std::fs::copy(built, scratch.exe(Program::Console)).unwrap();
    std::fs::copy(built, scratch.home.join("app\\bin\\codex-auto-resume.exe")).unwrap();
    let done = quiet(scratch.exe(Program::Console))
        .arg("-X")
        .arg("disable-remote-debug")
        .arg(scratch.fill("{home}\\app\\scripts\\plugin_setup.py"))
        .args(["setup", "--keep-state", "--no-startup"])
        .output()
        .unwrap();
    let said = String::from_utf8_lossy(&done.stderr);
    assert_eq!(done.status.code(), Some(car_legacy::REFUSED), "{said}");
    assert!(
        said.contains("`setup --keep-state --no-startup` is not one (NotInstalled)"),
        "{said}"
    );

    // Refused by the stand-in itself: nothing is started.
    let refused = quiet(scratch.exe(Program::Console))
        .args(["-c", "print(1)"])
        .output()
        .unwrap();
    assert_eq!(refused.status.code(), Some(car_legacy::REFUSED));
    assert!(String::from_utf8_lossy(&refused.stderr).contains("(Unknown). Nothing was run."));

    // The Rust program missing: MISSING, and a line that names it.
    std::fs::remove_file(scratch.home.join("app\\bin\\codex-auto-resume.exe")).unwrap();
    let missing = quiet(scratch.exe(Program::Console))
        .arg(scratch.fill("{home}\\app\\scripts\\plugin_setup.py"))
        .arg("watcher-running")
        .output()
        .unwrap();
    assert_eq!(missing.status.code(), Some(car_legacy::MISSING));
    assert!(String::from_utf8_lossy(&missing.stderr).contains("is not in this installation"));
}

/// pythonw.exe writes nothing anywhere (it has no console), refuses as python.exe does, and a Run value's line finds
/// no watcher host in a skeleton installation.
#[test]
fn the_windowless_stand_in_refuses_and_reports_by_its_code_alone() {
    let scratch = Scratch::new("windowless");
    let built = Path::new(env!("CARGO_BIN_EXE_pythonw"));
    std::fs::copy(built, scratch.exe(Program::Windowless)).unwrap();
    let refused = quiet(scratch.exe(Program::Windowless))
        .arg("--version")
        .output()
        .unwrap();
    assert_eq!(refused.status.code(), Some(car_legacy::REFUSED));
    assert!(refused.stdout.is_empty() && refused.stderr.is_empty());
    let run = quiet(scratch.exe(Program::Windowless))
        .arg(scratch.fill("{home}\\watcher-launcher.py"))
        .arg("run")
        .output()
        .unwrap();
    assert_eq!(run.status.code(), Some(car_legacy::MISSING));
    assert!(run.stdout.is_empty() && run.stderr.is_empty());
}

/// A message the stand-in cannot write (its stderr a pipe whose reader is gone) leaves its code the answer: 2 refused
/// and 1 missing, as argparse drops a message it cannot write; never 101, a panic's.
#[test]
fn a_stderr_that_cannot_be_written_changes_no_code() {
    use std::process::Stdio;
    let scratch = Scratch::new("stderr");
    let built = Path::new(env!("CARGO_BIN_EXE_python"));
    std::fs::copy(built, scratch.exe(Program::Console)).unwrap();
    let cases: [(Vec<String>, i32); 2] = [
        (vec!["-c".into(), "print(1)".into()], car_legacy::REFUSED),
        (
            vec![
                scratch.fill("{home}\\app\\scripts\\plugin_setup.py"),
                "status".into(),
            ],
            car_legacy::MISSING,
        ),
    ];
    for (args, code) in cases {
        let mut child = quiet(scratch.exe(Program::Console))
            .args(&args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        drop(child.stderr.take());
        assert_eq!(child.wait().unwrap().code(), Some(code), "{args:?}");
    }
}

//! The MCP launcher's work (`gui/McpLauncher.cs`, retargeted by D18): find the installation, start its core's MCP
//! server, relay the streams, end with the core's code once the input has closed.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::thread::JoinHandle;
use std::time::Duration;

use car_platform::spawn::{Spawn, Stream, SystemStarter};

/// `CREATE_NO_WINDOW`.
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// `InstallHome()`: the configured installation, else the account's default.
pub fn install_home(env: &dyn Fn(&str) -> Option<String>) -> String {
    for name in ["CODEX_AUTO_RESUME_PLUGIN_HOME", "CODEX_AUTO_RESUME_HOME"] {
        if let Some(found) = env(name).filter(|each| !each.is_empty()) {
            return found;
        }
    }
    let profile = env("USERPROFILE")
        .filter(|each| !each.is_empty())
        .unwrap_or_default();
    PathBuf::from(profile)
        .join(".codex-auto-resume")
        .to_string_lossy()
        .into_owned()
}

/// The core the launcher starts, inside the installation (PLAN 6.1).
pub fn core_of(home: &str) -> PathBuf {
    PathBuf::from(home)
        .join("app")
        .join("bin")
        .join("codex-auto-resume.exe")
}

/// The command line the core is started with.
pub fn arguments(home: &str) -> Vec<String> {
    vec![
        core_of(home).to_string_lossy().into_owned(),
        "mcp".to_owned(),
        "--home".to_owned(),
        home.to_owned(),
    ]
}

fn pump(from: &mut dyn Read, to: &mut dyn Write) {
    let mut buffer = [0u8; 8192];
    loop {
        match from.read(&mut buffer) {
            Ok(0) | Err(_) => return,
            Ok(read) => {
                if to
                    .write_all(&buffer[..read])
                    .and_then(|_| to.flush())
                    .is_err()
                {
                    return;
                }
            }
        }
    }
}

fn relay(
    mut from: impl Read + Send + 'static,
    mut to: impl Write + Send + 'static,
) -> JoinHandle<()> {
    std::thread::spawn(move || pump(&mut from, &mut to))
}

fn join_within(handle: JoinHandle<()>, wait: Duration) {
    let deadline = std::time::Instant::now() + wait;
    while !handle.is_finished() && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// `McpLauncher.Main`: the exit code.
pub fn run() -> i32 {
    let env = |name: &str| std::env::var(name).ok();
    let home = install_home(&env);
    let core = core_of(&home);
    if !core.is_file() || !PathBuf::from(&home).join("app").join("src").is_dir() {
        let _ = writeln!(
            std::io::stderr(),
            "Codex Auto Resume is not installed at {home}; run its installer, then reload the plugin."
        );
        return 1;
    }
    let spawn = Spawn::new(arguments(&home))
        .with_flags(CREATE_NO_WINDOW)
        .with_streams(Stream::Piped, Stream::Piped, Stream::Piped)
        .with_cwd(&home);
    let mut child = match SystemStarter.start(&spawn) {
        Ok(child) => child,
        Err(error) => {
            let _ = writeln!(
                std::io::stderr(),
                "Could not start the Codex Auto Resume MCP server: {error:?}"
            );
            return 1;
        }
    };
    let output = child
        .stdout
        .take()
        .map(|from| relay(from, std::io::stdout()));
    let errors = child
        .stderr
        .take()
        .map(|from| relay(from, std::io::stderr()));
    if let Some(mut to) = child.stdin.take() {
        pump(&mut std::io::stdin(), &mut to);
        drop(to);
    }
    let code = child
        .wait()
        .ok()
        .and_then(|status| status.code())
        .unwrap_or(1);
    for handle in [output, errors].into_iter().flatten() {
        join_within(handle, Duration::from_secs(2));
    }
    code
}

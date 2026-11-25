//! `app\mcp\codex-auto-resume-mcp.exe`, the MCP launcher at the path `.mcp.json` and every registration names (D18,
//! owner P6 Q4): it starts this installation's core as `codex-auto-resume.exe mcp --home <home>` and relays the three
//! streams, as `gui/McpLauncher.cs` relayed them to Python. It ends when its input closes: the core's stdin is closed,
//! the core ends at its EOF, and the launcher ends with the core's exit code.
//!
//! The installation is where the C# launcher looked: `CODEX_AUTO_RESUME_PLUGIN_HOME`, else `CODEX_AUTO_RESUME_HOME`,
//! else `%USERPROFILE%\.codex-auto-resume`. Its console window is Codex's choice, as today; the core is started with
//! `CREATE_NO_WINDOW` through car-platform's one starter.

fn main() {
    std::process::exit(car_bin::launcher::run());
}

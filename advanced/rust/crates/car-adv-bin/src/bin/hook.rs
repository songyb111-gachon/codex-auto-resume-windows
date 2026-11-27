//! `app\hook\codex-auto-resume-hook.exe`, the advanced edition's Stop hook launcher, at the path the hook's declaration
//! names (`control/hookplugin.py` `launcher()`: `<home>\app\hook\codex-auto-resume-hook.exe`; P6 Q4, today's path). Codex
//! starts it when a turn stops, while "Continue inside the turn" is on; it starts this installation's core as
//! `codex-auto-resume.exe hook --home <home>` and relays the handler's one answer (`hook_launcher.rs`). Built in the
//! advanced workspace only, so the standard edition has no such program; a console program, as Codex's hook runner
//! expects. Not in an archive yet: v0.6.26's advanced archive does not carry the C# launcher either (the capability is
//! hidden until its measurements pass), and packing it is the release's step with the owner's review. A panic passes like every other doubt: nothing written, exit 0 (D15).

#[path = "../hook_launcher.rs"]
mod hook_launcher;

fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    std::process::exit(std::panic::catch_unwind(hook_launcher::run).unwrap_or(0));
}

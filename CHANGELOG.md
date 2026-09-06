# Changelog

## v0.2.0 — Install and control it from inside Codex

### Install and control it from inside Codex

- **Codex plugin.** The repository root is now also a Codex plugin root, with a marketplace index
  (`.agents/plugins/marketplace.json`), a manifest (`.codex-plugin/plugin.json`) and one skill.
  Install with `codex plugin marketplace add songyb111-gachon/codex-auto-resume-windows` followed by
  `codex plugin add codex-auto-resume@codex-auto-resume-windows`, then ask Codex to set it up.
  There is exactly one copy of `src/`; the engine ships with the plugin rather than being duplicated.
- The plugin is a thin front end over the existing command-line interface. It adds no MCP server, no
  second engine, no recovery logic of its own, and never queues a message to a thread.
- **Runtime state moved out of the plugin directory** for plugin installs, to
  `%LOCALAPPDATA%\codex-auto-resume\`. Plugin updates and removals no longer risk pending resumes.
  Autostart points at a small stable launcher that re-resolves the current plugin version at every
  launch, so an update needs no re-registration. Manual installations are unchanged.
- **Two installations are refused rather than merged.** A manual checkout and a plugin install keep
  separate state and separate single-instance locks, so both watchers would run and could each resume
  the same interruption. Setup stops when a different installation already owns the sign-in autostart.
- English by default; Korean only when Korean is the most preferred UI language, read from the same
  source the ChatGPT desktop app uses for its own display language. No language is inferred from an IP
  address, time zone, user name, country or keyboard layout.

### Fixed

- **`uninstall` deleted the Windows sign-in autostart value even when it belonged to a different
  installation**, silently disabling a watcher it did not own. It now unregisters only a value that
  starts the installation being uninstalled, and reports anything else as kept. Found by running the
  plugin's uninstall against an isolated home while a manual installation was registered.
- Setup no longer crashes on a legacy-code-page console: the check mark falls back to ASCII when the
  console cannot encode it.

### Not implemented, on purpose

- A checkbox inside the Codex usage-limit notice. There is no official plugin API that can place a
  control there, and the alternatives are all forms of injection or GUI automation this project does
  not use. No substitute GUI was built. See [docs/PLUGIN.md](docs/PLUGIN.md) for the evidence.

### Also

- Survive Codex app updates instead of stopping at the first version change.
  - Local databases are discovered by schema generation (`state_5`, `thread_history_1`, ...) and
    validated by the columns actually read, so a generation bump no longer breaks detection. Extra
    columns are fine; a missing required column still refuses.
  - The exact engine-version equality check is replaced by a capability probe: a verified version is
    trusted, and an unrecognised one is accepted only when `codex queue` still offers `--thread` and
    `--message`. `status`, `doctor` and the watcher log say plainly when the engine is unverified.
- Report the engine pin actually in force in error messages instead of a hardcoded version.

## v0.1.0 — first public release

First public release of `codex-auto-resume-windows`, a local-only Windows watcher that resumes Codex
tasks interrupted by a usage limit.

### Included

- Usage-limit detection that fires only on `status=failed` together with
  `codexErrorInfo=usageLimitExceeded`. Completed, interrupted, ordinary failed, tool-error, malformed,
  and unknown states are never resumed.
- Exact-thread tracking by UUID. `--last` is never used, and one thread's failure can never resume another.
- Reset-aware waiting that uses the real reset timestamp when one is available, with conservative polling
  when it is not, and a live usage re-check immediately before sending.
- A loaded-thread safety guard: the thread must be verifiably loaded in the desktop app, determined from
  the Windows Restart Manager without ever locking the app's own files. Unknown state never sends.
- Safe waiting for unloaded threads instead of any attempt to force them open.
- Duplicate-resume protection that survives process crashes and watcher restarts.
- Durable pending state in SQLite, with support for several interrupted threads at once.
- Bounded retry backoff, a global kill switch, and per-thread enable/disable/cancel.
- CLI: `doctor`, `enable`, `disable`, `status`, `pending`, `cancel`, `logs`, `run`, `stop`, `install`,
  `uninstall`.
- Single-instance protection via a per-user named mutex.
- Optional per-user Windows login autostart, requiring no administrator rights.
- Conservative uninstall that only deletes inside directories it created, and aborts if a watcher may be
  running.
- Rotating logs that never record prompt text, error text, or account identifiers.
- Automated test suite plus an opt-in, read-only live environment check.

### Known limitations

- Only threads already loaded in the Windows ChatGPT/Codex desktop app can be auto-resumed. After an app
  restart an unloaded thread is resumed only once the user opens that conversation again. This is a
  measured limitation, not an oversight.
- The blocking usage bucket cannot always be identified from local history with certainty.
- Pinned to a verified Codex engine version and local schema; other versions are refused.
- The complete end-to-end unattended path has had limited real-world exercise so far.

### Credits

Created by Youngbin Song, with AI-assisted development by OpenAI Codex (investigation, proof of concept,
initial implementation) and Anthropic Claude Code (completion, testing, security and adversarial audit).
See `CONTRIBUTORS.md`.

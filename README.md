# codex-auto-resume-windows

**codex-auto-resume-windows** is a local-only Windows watcher that detects Codex tasks interrupted by a
usage limit and safely resumes the exact loaded Codex thread once usage becomes available again.

It watches Codex's own local state read-only. When a turn fails with `usageLimitExceeded`, it records
the exact thread, waits for the reset, re-checks that everything is still safe, and then sends one
continuation message to that same conversation through the official `codex queue` command.

## Please read this limitation first

This tool can only auto-resume a thread that the Windows ChatGPT/Codex desktop app **currently has
loaded**.

After the app restarts, a target thread is `notLoaded`. There is **no verified, supported way to wake an
unloaded thread programmatically** — a message queued for an unloaded thread stays in the queue and is
never delivered as a conversation turn. This was measured, not assumed; see
[`docs/evidence/unloaded-thread-delivery.json`](docs/evidence/unloaded-thread-delivery.json).

So an unloaded thread is resumed **only after you open that conversation in the ChatGPT app yourself**.
Until then the watcher simply waits in a `waiting_for_loaded_thread` state. It will not use GUI
automation, will not force the conversation open, and will not queue a message on the off chance.

This is not fully unattended auto-resume across app restarts, and this README will not pretend otherwise.

## Features

- Detects only genuine usage-limit interruptions (`status=failed` **and** `codexErrorInfo=usageLimitExceeded`).
- Tracks the exact thread UUID. Never `--last`, never a guessed thread.
- Waits for the real reset timestamp when one is available, instead of sleeping a fixed number of hours.
- Verifies the desktop app is running and the thread is genuinely loaded before sending anything.
- Never resumes the same interruption twice, including across a crash or a watcher restart.
- Durable pending state in SQLite that survives reboots.
- Handles several interrupted threads independently.
- Bounded retry backoff, a global kill switch, and per-thread control.
- Single-instance protection, optional per-user Windows autostart, and a conservative uninstall.

## How it works

```
usage limit reached
  -> watcher reads Codex's local history (read-only) and sees usageLimitExceeded
  -> records the exact thread UUID in its own SQLite state
  -> waits until the reset timestamp
  -> checks the ChatGPT app is running and the thread is loaded
  -> re-checks live usage availability
  -> codex queue --thread <UUID> --message "<continuation>"
  -> the same thread continues the original work
```

The continuation message asks the agent to continue the interrupted work: to first check the current
thread context and the real repository/file state, to avoid redoing finished work, and to carry on
toward the original goal.

Loaded state is determined from the Windows Restart Manager: the app's own `codex.exe` engine holds the
thread's writer lock file open for exactly as long as the thread is loaded. The tool only reads that
ownership information. It never acquires a lock on the app's file.

## Requirements

- Windows 10/11.
- Python 3.12+. Standard library only, no third-party packages.
- The official Windows ChatGPT/Codex desktop app, running, with its engine at
  `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`.
- The engine version is pinned to the version this tool was verified against. A different version is
  refused rather than guessed at.

## Installation

```bash
git clone https://github.com/songyb111-gachon/codex-auto-resume-windows.git
```

```bash
cd codex-auto-resume-windows
```

There is nothing to build. Verify your environment first:

```bash
python src\auto_resume.py doctor
```

`doctor` is read-only. It reports the discovered engine, whether the app is paired, whether the Restart
Manager probe works, and whether the local history is readable.

## Quick start

```bash
python src\auto_resume.py doctor
```

```bash
python src\auto_resume.py enable
```

```bash
python src\auto_resume.py run
```

`run` stays in the foreground and polls. Leave it running in a terminal while you work.

Check what it is doing:

```bash
python src\auto_resume.py status
```

```bash
python src\auto_resume.py pending
```

```bash
python src\auto_resume.py logs
```

Stop it:

```bash
python src\auto_resume.py disable
```

```bash
python src\auto_resume.py stop
```

`disable` is the kill switch: it immediately prevents any further resume while keeping your pending
records. `stop` asks a running watcher process to exit.

## Commands

| Command | What it does |
|---|---|
| `doctor` | Read-only environment check: engine, app pairing, Restart Manager, history. |
| `enable [thread-id]` | Turn auto-resume on globally, or for one thread. |
| `disable [thread-id]` | Kill switch: stop all automatic resumes, or just one thread. |
| `status` | Enablement, watcher state, autostart, engine, and record counts. |
| `pending` | Interruptions waiting to resume (`--all`, `--json`). |
| `cancel <thread-id>` | Cancel pending resumes for one thread and disable it. |
| `logs` | Recent log lines (`-n N`). |
| `run` | Run the watcher in the foreground (`--once`, `--poll N`). |
| `stop` | Ask a running watcher to exit. |
| `install` | Create the owned directories and state (`--startup`). |
| `uninstall` | Remove autostart and owned state/logs (`--keep-logs`). |

Global options: `--home` (where this tool keeps its own state), `--codex-exe`, `--codex-home`, `--quiet`.

By default, failures up to 6 hours old at the moment you run `enable` are still eligible. Change it with
`enable --lookback-hours N`.

## Windows startup

Optional, per-user, and never required:

```bash
python src\auto_resume.py install --startup
```

This writes a single value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. It needs no
administrator rights, touches nothing system-wide, and creates no service or scheduled task. It runs the
watcher with `pythonw.exe` so no console window appears, and it always pins the home directory that is
actually in effect so the autostarted watcher uses the same state and the same single-instance lock.

Running `install --startup` repeatedly does not create duplicate entries.

Consider running in the foreground for a while first, and enabling autostart only once you have seen a
real resume happen.

## Uninstall

```bash
python src\auto_resume.py uninstall
```

```bash
python src\auto_resume.py uninstall --keep-logs
```

Uninstall is deliberately conservative:

- It removes the autostart value, stops the watcher, and deletes this tool's own state and logs.
- It only deletes inside a directory that carries this tool's provenance marker
  (`.owned-by-codex-auto-resume`), so a directory it did not create is skipped and reported, never touched.
- Inside its own directories it still only deletes its own file names, so unrelated files survive.
- If a watcher is running, **or if it cannot verify whether one is running**, it aborts before deleting
  anything.
- It never deletes ChatGPT files, Codex files, user repositories, or a parent directory.

## Safety model

What it reads: Codex's local SQLite state and rollout files, opened read-only, plus its own state.

What it writes: only its own `config/` and `logs/`, and one continuation message to one exact thread via
the official `codex queue` CLI.

Design rules enforced in code:

- **Local only.** The Python code opens no network sockets. Model requests are made by the official,
  already-authenticated Codex binary, exactly as they would be normally.
- **Read-only on Codex data.** Codex databases are opened with `mode=ro` and `query_only`.
- **Fail closed.** Unknown loaded state, unknown usage, an unavailable probe, or any ambiguity results in
  waiting, never in sending.
- **Exact thread only.** Thread ids are validated as canonical UUIDs and passed as separate argv
  elements. No shell string is ever composed.
- **No duplicate resume.** The interruption is durably reserved before any external process can run. If
  the outcome of a send is uncertain, the tool stops and does not retry automatically.
- **No secrets in logs or state.** Prompt text, error text, and account/usage identifiers are never
  written. Log lines carry static reason codes, timestamps, and identifiers only.
- **Never used:** GUI automation, mouse or keyboard simulation, OCR, screen scraping, accessibility-API
  clicking, binary patching, DLL injection, process-memory manipulation, credential extraction.

## Known limitations

- Only threads already loaded in the app can be auto-resumed. Unloaded threads wait for you to open them.
- The blocking usage bucket cannot always be identified with certainty, so live availability is
  re-checked immediately before sending rather than trusted from history.
- The tool is pinned to a verified Codex engine version and local schema. Other versions are refused
  rather than handled speculatively.
- If the watcher process dies in the narrow window after reserving but before the send result is known,
  that interruption is deliberately left unresumed rather than risking a duplicate.
- The full end-to-end path (real usage limit, real reset, unattended resume) has had limited real-world
  exercise so far. The individual stages are tested and verified; the complete unattended run is new.

## Testing

Run the automated suite:

```bash
python -m unittest discover -s tests
```

Set `PYTHONPATH=src` first (or use `set PYTHONPATH=src` on Windows).

These tests use fakes and temporary directories. They never contact the ChatGPT app and never send a
message to any conversation, so they are safe to run anywhere and are what CI runs.

There is also an opt-in, read-only live check against your real environment. It verifies binary
discovery, app pairing, loaded-state classification, and usage reading. It never sends anything:

```bash
set CODEX_AR_LIVE=1 && python -m unittest tests.test_integration_live
```

## Security

See [SECURITY.md](SECURITY.md) for the full model, the review process, and the issues that were found
and fixed. In short: no network access from this code, no credential reads, read-only against Codex
state, fail-closed behaviour, and a conservative uninstall.

The project went through three adversarial review rounds plus mutation testing, a crash-window matrix,
and a cross-process race test. Confirmed issues were fixed and covered by regression tests.

If you find a security issue, please open an issue on this repository.

## Development and credits

Built by **Youngbin Song** with the assistance of two AI development tools:

- **OpenAI Codex** — initial Windows/Codex architecture and protocol investigation, the exact-thread
  queue proof of concept, loaded/notLoaded verification, usage-limit and reset research, and the initial
  implementation.
- **Anthropic Claude Code** — took over that prototype, completed the watcher, CLI, Windows integration
  and persistence, expanded the tests, fixed correctness bugs, and ran the security and adversarial audits.

OpenAI Codex and Anthropic Claude Code are AI development tools, not human contributors or GitHub
accounts. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the full breakdown and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the development history, including the measurements behind
the loaded/notLoaded limitation.

## License

MIT. See [LICENSE](LICENSE).

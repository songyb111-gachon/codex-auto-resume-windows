# Security

This document describes what the tool is allowed to touch, how that is enforced, how it was reviewed,
and what was actually found and fixed.

## Reporting

If you find a security issue, please open an issue on this repository.

This project operates no service of its own - no server, no endpoint, no telemetry - so there is no
vendor backend to notify. The one external service it reaches is github.com, and only to download a
release; a finding in GitHub itself belongs to GitHub's own reporting process, not here.

## What it touches

**Reads**, always read-only:

- Codex's local state (thread metadata, turn/item history, queue database, rollout JSONL files), opened
  with SQLite `mode=ro` and `PRAGMA query_only=ON`.
- Its own state and settings.
- Windows process and Restart Manager information needed to identify the desktop app and its engine.

**Writes** while running, only ever:

- Its own `config/` and `logs/` directories.
- One continuation message to one exact thread, through the official `codex queue` CLI.

**Writes** at install time, for the current user only and never system-wide: a Start Menu shortcut,
the sign-in autostart value unless you decline it, the notification sender identity Windows requires
before it will draw a toast at all, and the handler for the notification button's own URL scheme.
Uninstalling removes them.

**Never reads**: `auth.json`, tokens, cookies, authorization headers, or process memory.
**Never writes**: anything inside Codex's own databases or directories.

## Enforced properties

- **No network from the recovery runtime.** The Python source imports no networking module, so the
  watcher cannot open a connection. Model requests are made by the official, already-authenticated
  Codex binary, exactly as they would be during normal use. The one outbound request in the product is
  installation: `scripts/bootstrap.ps1` fetches the release archive from github.com over HTTPS and
  verifies it before anything in it runs. The distinction that matters either way: this tool never
  uploads anything anywhere.
- **No shell.** Every subprocess is an argv list with `shell=False`. There is no string composition, no
  `os.system`, no `eval`/`exec`.
- **Exact thread only.** Thread ids must be canonical UUIDs. `--last` is never used.
- **No secrets in logs or state.** Log lines are built from a fixed message table and carry only static
  reason codes, timestamps, and identifiers. Untrusted values are masked unless they are hex or digits.
  Prompt text, error text, and account/usage fields are discarded at parse time. Tracebacks go only to a
  separate rotating error log, and the main log records the exception class name only.
- **Fail closed.** Unknown loaded state, unknown usage, an unavailable probe, or a corrupted state file
  results in waiting or refusing, never in sending.
- **No duplicate resume.** The interruption is durably reserved (SQLite, `synchronous=FULL`,
  `BEGIN IMMEDIATE`) before any external process can accept a message. If the result of a send is
  ambiguous, the record stops in a terminal `submission_unknown` state and is never retried automatically.
- **Path confinement.** Owned directories are rejected if they are links, or if they resolve outside the
  configured home. The resolve-based check also catches NTFS junctions, which `is_symlink()` does not.
- **No interference with the app.** There is no byte-lock API anywhere in the adapter. Loaded state is
  determined purely from the Restart Manager inventory, so the tool can never contend with the app's own
  thread writer lock.
- **Least privilege.** No administrator rights are required. Optional autostart writes a single value
  under the current user's `Run` key. No service, no scheduled task, nothing system-wide.

## Destructive-operation safety

**Nothing is destroyed that this installation cannot prove it owns.** That is one rule, and it
covers every kind of resource and both directions - installing and uninstalling - because "it has
the right name" was never evidence for any of them.

- **Installing.** The install path destroys things too: it sweeps set-aside copies, moves `app/`
  and `runtime/` out of the way, and deletes what it moved. It cannot ask the question the
  uninstaller asks, because the first install happens into a directory that is not ours yet. So it
  asks the other half: is anything of ours here? A directory already holding `app`, `runtime`,
  `config`, `logs` or a set-aside copy, with no proof any of it is ours, is refused and nothing in
  it is touched. A directory holding none of them has nothing to destroy, and is marked as ours
  *before* the first file is written - never afterwards, because a marker written after the fact
  would authorise the deletions backwards.
- **Uninstalling: directories.** The installation root has to be one we created: it carries our provenance
  marker (`.owned-by-codex-auto-resume`), or its `config/` does, or its `runtime.json` names that
  very directory. The root can be pointed anywhere by `CODEX_AUTO_RESUME_PLUGIN_HOME`, so a
  directory that merely contains folders called `app`, `runtime`, `config` and `logs` is refused
  and nothing in it is touched. Every path deleted is then re-checked against the *canonical*
  root, with junctions and symlinks resolved, so a link inside the installation cannot redirect a
  recursive delete out of it. Inside an owned directory, only our own file names are removed.
- **Uninstalling: processes.** The MCP launcher is stopped only when its executable resolves inside this
  installation or inside this plugin's own Codex cache directory. Another program running under
  the same filename is left alone, and a process whose path cannot be read is skipped: not being
  able to tell is not permission to kill.
- **Uninstalling: Codex configuration.** The plugin and its marketplace are removed only while they still point
  at this installation, which is read from `codex plugin list --json` and
  `codex plugin marketplace list --json`. If you have repointed that marketplace name at a fork of
  your own, uninstalling this product leaves your configuration exactly where it is and says so.
- **Uninstalling: registry and Start Menu.** The sign-in entry, the notification identity, the Start Menu
  shortcut and the `codex-auto-resume:` handler are per-user singletons that a second installation
  would overwrite, so each is removed only when it still belongs to the installation being
  removed.

If a watcher is running, or if it cannot verify whether one is running, uninstall aborts before
removing anything at all — registrations included. ChatGPT files, Codex files, user repositories and
parent directories are never deleted.

## Review process

Three adversarial review rounds. Each round ran several independent reviewers across different
dimensions, and every finding was then given to three further independent agents whose task was to
*refute* it. Only findings that survived refutation were treated as real.

| Round | Scope | Confirmed | Rejected |
|---|---|---:|---:|
| 1 | detector, store, Windows adapter, scheduler | 12 | 6 |
| 2 | CLI, app, config, logging, autostart | 3 | 0 |
| 3 | final audit across 9 dimensions | 8 | 3 |

Empirical verification beyond review:

- **Mutation testing.** Around twenty safety guards were deliberately broken to confirm the test suite
  catches it. Three survivors exposed real gaps, all in uninstall safety, and regression tests were added.
- **Crash-window matrix.** The process was killed at four points around sending. After restart, every
  case sent at most once.
- **Cross-process race.** Four processes raced to reserve the same interruption, eight times, with
  exactly one winner each time.

## Notable issues found and fixed

- **The loaded-state probe could acquire the app's own exclusive writer lock** when the byte range was
  momentarily free, which could make the app's own lock attempt fail with a lock violation. The locking
  code was removed entirely.
- **Autostart could point at the wrong state.** With a home configured by environment variable, the
  registered command omitted it, so the autostarted watcher would use a different state database and a
  different single-instance mutex, allowing a second watcher and silently resuming nothing.
- **Uninstall could delete same-named files it never created.** Fixed with the provenance marker.
- **Uninstall treated an unverifiable watcher probe as "not running".** Now fails closed.
- **NTFS junctions bypassed directory confinement**, because `is_symlink()` does not detect them.
- **A transient engine probe failure at logon terminated the watcher** for the whole session.
- **Two inherited bugs made the prototype non-functional**: detection results were rejected by the store,
  so nothing was ever registered or resumed, and the entry point swallowed all exit codes.

## Residual risks

- The blocking usage bucket cannot always be identified from history with certainty, so live availability
  is re-checked immediately before sending. This reduces but does not eliminate the uncertainty.
- The tool no longer requires an exact engine version. An unrecognised build is accepted when the
  `codex queue` interface probe passes, which means a Codex update can change *semantics* without the
  probe noticing. This is mitigated rather than eliminated: every send is still proven afterwards by
  the per-interruption marker in that exact thread, an unproven send never becomes `resumed`, and
  `status`/`doctor`/the log state clearly when the engine is unverified.
- Unloaded threads are not resumed at all; this is a documented product limitation, not a security control.

# Security

This document describes what the tool is allowed to touch, how that is enforced, how it was reviewed,
and what was actually found and fixed.

## Reporting

If you find a security issue, please open an issue on this repository. There is no external service or
endpoint involved in this project, so there is nothing to report to a third party.

## What it touches

**Reads**, always read-only:

- Codex's local state (thread metadata, turn/item history, queue database, rollout JSONL files), opened
  with SQLite `mode=ro` and `PRAGMA query_only=ON`.
- Its own state and settings.
- Windows process and Restart Manager information needed to identify the desktop app and its engine.

**Writes**, only ever:

- Its own `config/` and `logs/` directories.
- One continuation message to one exact thread, through the official `codex queue` CLI.

**Never reads**: `auth.json`, tokens, cookies, authorization headers, or process memory.
**Never writes**: anything inside Codex's own databases or directories.

## Enforced properties

- **No network from this code.** The Python source imports no networking module. Model requests are made
  by the official, already-authenticated Codex binary, exactly as they would be during normal use. The
  distinction that matters: this tool never uploads anything anywhere.
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

## Uninstall safety

Uninstall only deletes inside a directory carrying this tool's provenance marker
(`.owned-by-codex-auto-resume`), and inside such a directory only its own file names. A directory it did
not create is skipped and reported. If a watcher is running, or if it cannot verify whether one is
running, uninstall aborts before deleting anything. ChatGPT files, Codex files, user repositories, and
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
- The repository's early Git history contains development-time environment metadata (a Windows user name
  in absolute paths, ephemeral process ids, and opaque Codex thread identifiers). It contains no
  credentials, no tokens, and no conversation content. Files published at and after the first public
  release are generalised.

---
name: codex-auto-resume
description: Set up, inspect and control automatic resume of Codex tasks that were interrupted by a usage limit on Windows. Use for requests like enable/disable auto resume, show auto resume status, show pending auto resumes, cancel auto resume for a task, start it at Windows sign-in, or uninstall it.
---

# Codex Auto Resume

Controls a small local watcher that resumes the exact Codex conversation a usage limit
interrupted, once the limit resets. This skill is a front end: every command below calls
the project's own command-line interface, which owns all detection and safety logic.

Windows only.

## Running commands

Run from the plugin root (the directory that contains this plugin's `scripts/` folder).

Use the first Python that works, in this order:

```bash
py -3 scripts/plugin_setup.py <command>
```

```bash
python scripts/plugin_setup.py <command>
```

```bash
python3 scripts/plugin_setup.py <command>
```

If none of them run, tell the user that Python 3.10 or newer is required and stop. Do not
try to install Python for them.

Commands:

| Request | Command |
| --- | --- |
| Set up / turn on for the first time | `setup` |
| Set up without Windows sign-in autostart | `setup --no-startup` |
| Turn auto resume on | `enable` |
| Turn auto resume off | `disable` |
| Show status | `status` |
| Show what is waiting to resume | `pending` |
| Stop auto resume for one task | `cancel <thread-uuid>` |
| Stop the background watcher now | `stop` |
| Check the installation | `doctor` |
| Show recent activity | `logs` |
| Remove it completely | `uninstall` |

## Cancelling one task

`cancel` needs the exact conversation UUID. Never guess it, never pass `--last`, and never
pick "the most recent thread".

1. Run `pending` and read the listed thread IDs.
2. If the user means "this conversation" and the environment variable `CODEX_SESSION_ID`
   is set and exactly equals one of those listed thread IDs, use that one.
3. Otherwise show the pending entries and ask which one to cancel.

Cancelling affects only that conversation. It does not turn off auto resume globally.

## Reporting results

Report what the command actually printed. Useful fields from `status` and `pending`:

- `auto-resume` — whether it is on at all.
- `watcher` — `running` means it is waiting in the background. `not running` means nothing
  will be resumed; offer to run `enable`, which also starts it.
- `state` on a pending entry:
  - `waiting_reset` / `waiting_poll` — waiting for the usage limit to reset.
  - `waiting_for_loaded_thread` — the limit has reset, but that conversation is not open in
    the app. Tell the user to open it; the watcher will then resume it.
  - `resumed` — the continuation was delivered and confirmed.
  - `submission_unknown` — the result could not be confirmed, so it will never be resent.
    Tell the user to check that conversation themselves.

Do not restate the reset time the Codex usage-limit notice already shows.

## What it does and does not do

- Resumes only tasks that stopped because of a **usage limit**. It is not a general retry
  tool: network errors, timeouts, server errors and failed turns are left alone.
- Resumes only the **exact** interrupted conversation.
- Does nothing while any part of the situation is uncertain. It prefers missing a resume
  over resuming twice.
- The conversation must be **open in the Codex app** at reset time. If it is not, the entry
  waits at `waiting_for_loaded_thread` until the user opens it. This is a real limitation;
  state it plainly rather than promising fully unattended recovery.
- Reads Codex's local state read-only. It never edits Codex files, never touches
  credentials, and sends nothing off the machine.

## Setup notes

- `setup` is safe to run again; it does not reset existing settings or lose pending entries.
- If `setup` reports that another auto-resume installation is already registered to start at
  sign-in, do not force it. Two watchers could resume the same task twice. Tell the user to
  remove the other installation first.
- The watcher keeps running after the Codex app is closed, and starts again at Windows
  sign-in once `setup` has registered it.
- No Codex restart is needed for these commands to take effect. Only say a restart is
  required if Codex itself reports that a newly installed plugin is not active yet.

## Removing it

`codex plugin remove` removes this skill but does not stop a watcher that is already
running. To remove everything, run `uninstall` first, then remove the plugin.

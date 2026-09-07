---
name: codex-auto-resume
description: Set up, inspect and control automatic recovery of Codex tasks interrupted by a usage limit or a temporary failure on Windows. Use for requests like enable/disable auto resume, show auto resume status, show pending auto resumes, cancel auto resume for a task, start it at Windows sign-in, or uninstall it.
---

# Codex Auto Resume

Controls a small local watcher that resumes the exact Codex conversation a usage limit
interrupted, once the limit resets. This skill is a front end: every command below calls
the project's own command-line interface, which owns all detection and safety logic.

Windows only.

## Prefer the tools when they are available

This plugin also provides tools (`open_settings`, `get_status`, `list_pending`,
`update_settings`, `set_auto_recovery`, `cancel_recovery`, `reset_recovery_budget`,
`retry_now`). When they are available, use them instead of the commands below: they are
typed, they refuse an invalid value instead of writing it, and `open_settings` shows the
user a panel they can read and change directly.

Use the commands below when the tools are not available - the plugin's server has not
started, or the user is asking to install, repair or remove the product, which the tools
deliberately cannot do.

## Installing it

**This plugin is not the product.** It carries the skills, the tools and this file; the
parts that do the work are a Windows runtime, a settings window and a background watcher,
which are not in the plugin and cannot be. So the first step is always the setup script,
which downloads the matching release, verifies it and installs it.

Run this, from the plugin root - the directory containing this plugin's `scripts/` folder:

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
```

It needs nothing installed first: no Python, no administrator rights, no manual download.
It is safe to run again - that is also the repair path and the upgrade path. Add
`-NoStartup` if the user does not want it to run at Windows sign-in.

Tell the user plainly what it is about to do before running it: it downloads this
version's release archive from the project's GitHub releases over HTTPS, checks its
SHA-256, checks the contents are this product at this version, and only then installs -
into their user profile, touching nothing outside it. If they would rather do it
themselves, the same archive is on the project's GitHub releases page and the ZIP
contains `Install.cmd`.

If it reports that it could not download, say so and stop. Do not look for another
source for the archive, do not offer a different URL, and do not try to assemble an
installation by hand.

## Running commands

Everything below needs the product to be installed, because it runs through the
interpreter the installer deploys:

```bash
%USERPROFILE%\.codex-auto-resume\runtime\python.exe %USERPROFILE%\.codex-auto-resume\app\scripts\plugin_setup.py <command>
```

If that interpreter is not there, the product is not installed: run the setup script
above instead of looking for another Python. A system Python can run these files, but it
would configure a *second*, lesser installation - a different interpreter, no settings
window, no panel - which is why `setup` refuses to do it.

Commands:

| Request | Command |
| --- | --- |
| Set up / turn on for the first time | the setup script above |
| Set up without Windows sign-in autostart | the setup script above, with `-NoStartup` |
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
  - `waiting_backoff` — a temporary failure; waiting out a short bounded delay.
  - `waiting_for_loaded_thread` — the limit has reset, but that conversation is not open in
    the app. Tell the user to open it; the watcher will then resume it.
  - `resumed` — the continuation was delivered and confirmed.
  - `submission_unknown` — the result could not be confirmed, so it will never be resent.
    Tell the user to check that conversation themselves.
  - `superseded_by_user` — a later turn exists in that conversation, so the old failure was
    dropped rather than replayed on top of newer work. This is correct, not a fault.
  - `retry_budget_exhausted` / `no_progress_exhausted` — recovery gave up on purpose, either
    after too many attempts or after repeated attempts that produced nothing. Tell the user to
    look at that conversation first. If they want it to keep trying anyway, `reset_recovery_budget`
    gives that one interruption its attempts back — it sends nothing, and every check runs again
    from the top. Never offer it as a way to "force" a resume.

`retry_now` brings a waiting recovery's next attempt forward. It is not a send: the watcher still
revalidates the interruption, still needs the conversation open, still waits for usage, and still
refuses anything uncertain. Do not describe it as making a resume happen.

Do not restate the reset time the Codex usage-limit notice already shows.

## Settings

There are three ways to change a setting, and all three write the same file through the same
validator, so a value set in one is the value the others show:

- `open_settings` — the panel, in this conversation. Best when the user wants to look.
- `update_settings` — one or more named settings. Only the named ones change.
- **Start Menu → Codex Auto Resume** — a standalone window that works with Codex closed.

Never edit `settings.json` by hand, and never tell the user to. A hand-written file is
validated on read, so a bad value is silently replaced by the default and the user is left
believing they changed something.

What can be changed: which classified failure categories are recovered, how many attempts each
interruption gets, when to stop after repeated no-progress recoveries, the retry timing preset,
and which notifications appear.

What cannot, and is not an oversight: there is no setting that retries an unclassified failure,
resolves a conversation by title, resends an uncertain submission, or forces a send. If the user
asks for one, say plainly that it does not exist by design and do not look for a way around it.

## Notifications

Windows notifications cover the lifecycle: an interruption is detected, recovery starts, how it
turned out, and when recovery stops for good. The first one carries a **Don't resume** button;
doing nothing resumes, which is the default. Each event has its own switch, and there is a master
switch for all of them.

Turning notifications off changes nothing about whether a task is recovered - say so, because
people reasonably assume otherwise.

Do not offer to build any other interface. There is no checkbox inside the Codex usage-limit
notice and none can be added; see the project's docs/PLUGIN.md if asked why.

## What it does and does not do

- Recovers a **usage limit**, and failures it can positively classify as temporary: connection
  failures, timeouts, transient 429s, server 5xx, and stream disconnections.
- It is **not** a general retry tool. User cancellation, permission, approval, policy, invalid
  requests, context-length errors and permanent authentication failures are never retried — and
  neither is any failure it cannot classify. If asked to "retry everything", explain that
  unknown failures are deliberately left alone, and do not try to work around it.
- Resumes only the **exact** interrupted conversation.
- Does nothing while any part of the situation is uncertain. It prefers missing a resume
  over resuming twice.
- The conversation must be **open in the Codex app** at reset time. If it is not, the entry
  waits at `waiting_for_loaded_thread` until the user opens it. This is a real limitation;
  state it plainly rather than promising fully unattended recovery.
- Reads Codex's local state read-only. It never edits Codex files, never touches
  credentials, and sends nothing off the machine.

## Setup notes

- The setup script is safe to run again; it does not reset existing settings or lose
  pending entries. Run again when the user asks to repair or update it: if the installed
  version already matches this plugin it re-checks the registration rather than
  downloading anything.
- There is one installation, in `%USERPROFILE%\.codex-auto-resume`, and everything points
  at it: the watcher, the sign-in entry, the notification buttons, the settings window,
  this plugin's tools and the command line. If the user has two, that is a fault worth
  reporting, not a configuration.
- If setup reports that another auto-resume installation is already registered to start at
  sign-in, do not force it. Two watchers could resume the same task twice. Tell the user to
  remove the other installation first.
- The watcher keeps running after the Codex app is closed, and starts again at Windows
  sign-in once `setup` has registered it.
- No Codex restart is needed for these commands to take effect. Only say a restart is
  required if Codex itself reports that a newly installed plugin is not active yet.

## Removing it

`codex plugin remove` removes this skill but does not stop a watcher that is already
running, and it does not remove the installation the setup script made. To remove
everything, run `uninstall` first, then remove the plugin.

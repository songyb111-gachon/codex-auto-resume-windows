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
`update_settings`, `restore_default_settings`, `pause_auto_recovery`, `resume_auto_recovery`,
`cancel_recovery`, `disable_conversation_recovery`, `enable_conversation_recovery`,
`reset_recovery_budget`, `start_watcher`, `retry_now`, `get_recovery_statistics`,
`get_recovery_timeline`, `clear_recovery_history`). When they are available, use them
instead of the commands below: they are typed, they refuse an invalid value instead of
writing it, and `open_settings` shows the user a panel they can read and change directly.

`resume_auto_recovery`, `enable_conversation_recovery`, `update_settings`,
`restore_default_settings`, `cancel_recovery`, `reset_recovery_budget`, `start_watcher` and
`clear_recovery_history` are marked so that Codex asks the user before running them in Auto
approval mode. If the user declines one, do not run the matching
command below instead.

Use the commands below when the tools are not available - the plugin's server has not
started, or the user is asking to install, repair or remove the product, which the tools
deliberately cannot do.

## Installing it

**This plugin is not the product.** It carries the skills, the tools and this file; the
parts that do the work are a Windows runtime, a settings window and a background watcher,
which are not in the plugin and cannot be. So the first step is always the setup script,
which downloads the matching release, verifies it and installs it.

Run the plugin's own setup script **by its absolute path**. This file is
`<plugin root>\skills\codex-auto-resume\SKILL.md`, so the script is
`<plugin root>\scripts\bootstrap.ps1` - two directories up from this file, then
`scripts`. Before running it, check that `<plugin root>\.codex-plugin\plugin.json` exists
and names `codex-auto-resume`; if it does not, stop and say the plugin files could not be
found.

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File '<plugin root>\scripts\bootstrap.ps1'
```

Never run it as a relative `scripts/bootstrap.ps1`. The working directory is usually the
user's project, and a project can contain a script of the same name - running that one
with `-ExecutionPolicy Bypass` would run someone else's code in the user's name.

It needs nothing installed first: no Python, no administrator rights, no manual download.
It is safe to run again - that is also the repair path and the upgrade path. Add
`-NoStartup` if the user does not want it to run at Windows sign-in.

Tell the user plainly what it is about to do before running it: it downloads this
version's release archive from the project's GitHub releases over HTTPS, checks its
SHA-256, checks the contents are this product at this version, and only then installs,
for their Windows user only and without administrator rights. Besides the files in
`%USERPROFILE%\.codex-auto-resume` it registers the watcher to start at sign-in (unless
`-NoStartup`), a Start Menu entry and a notification sender, and this plugin with Codex.

Nothing this project builds is code-signed, so Smart App Control may block its two small
programs, and SmartScreen may warn about a downloaded `Install.cmd`. Say so plainly if it
happens, and do not suggest turning either off.

If they would rather do it themselves, the same archive is on the project's GitHub
releases page and the ZIP contains `Install.cmd`. `Install.cmd` does not check the archive
it came in, so tell them to verify the ZIP before extracting it, as described in
https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md.
Never state a digest yourself.

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
| Turn it off and unregister it (program files stay) | `uninstall` |
| The same, and also delete settings and pending recoveries | `uninstall --purge` |

## Cancelling one task

`cancel` needs the exact conversation UUID. Never guess it, never pass `--last`, and never
pick "the most recent thread".

1. Run `pending` and read the listed thread IDs.
2. If the user means "this conversation" and the environment variable `CODEX_SESSION_ID`
   is set and exactly equals one of those listed thread IDs, use that one.
3. Otherwise show the pending entries and ask which one to cancel.

Cancelling affects only that conversation, but all of it: every recovery in it that has
not been sent is cancelled, and auto resume is switched off for that conversation. A
continuation already in Codex's queue is withdrawn when the watcher next checks it, if it
is still queued. It does not turn off auto resume globally.

## Reporting results

Report what the command actually printed. Useful fields from `status` and `pending`:

- `auto-resume` — whether it is on at all.
- `watcher` — `running` means it is waiting in the background. `not running` means nothing
  will be resumed; offer the `start_watcher` tool, or `enable`, which also starts it but
  switches auto resume back on if the user had paused it. `unknown` means the check itself
  could not answer; do not report it as running, and offer `doctor`.
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
    gives that one interruption its attempts back and switches auto resume back on for its
    conversation — it sends nothing, and every check runs again from the top. Never offer it as
    a way to "force" a resume.

`retry_now` brings a waiting recovery's next attempt forward. It is not a send: the watcher still
revalidates the interruption, still needs the conversation open, still waits for usage, and still
refuses anything uncertain. Do not describe it as making a resume happen.

Do not restate the reset time the Codex usage-limit notice already shows.

## Settings

There are three ways to change a setting, and all three write the same file through the same
validator, so a value set in one is the value the others show:

- `open_settings` — the panel, in this conversation. Best when the user wants to look.
- `update_settings` — one or more named settings. Only the named ones change, and it accepts
  only the settings described below.
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
notice and none can be added through the Codex plugin API; see
https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md if asked
why.

## What it does and does not do

- Recovers a **usage limit**, and failures it can positively classify as temporary from the
  error code Codex records: connection failures, rate limits, server errors and overloads, and
  stream disconnections. Only when Codex recorded no code at all does it match a short list of
  transport-failure phrases. Codex 0.153.4 records many timeouts and gateway errors (502, 503,
  504) with a generic code; those count as unknown and are not retried.
- It is **not** a general retry tool. User cancellation, permission, approval, policy, invalid
  requests, context-length errors and permanent authentication failures are never retried — and
  neither is any failure it cannot classify. If asked to "retry everything", explain that
  unknown failures are deliberately left alone, and do not try to work around it.
- Resumes only the **exact** interrupted conversation.
- Sends nothing while any part of the situation is uncertain. It prefers missing a resume
  over resuming twice.
- The conversation must be **open in the Codex app** at reset time. If it is not, the entry
  waits at `waiting_for_loaded_thread` until the user opens it. This is a real limitation;
  state it plainly rather than promising fully unattended recovery.
- Its own code opens Codex's databases and files read-only and never reads credentials.
  What changes in Codex, Codex makes itself when asked: its command-line queue adds the
  continuation to that one conversation, and its App Server withdraws that same message
  when it has to.
- Its own runtime has no network code, no telemetry and no update check. The setup script
  downloads the release from GitHub. The Codex processes it starts use the user's existing
  sign-in to check usage, and the resumed turn goes to OpenAI like any turn the user starts.
  What these tools and commands return becomes part of this conversation.

## Setup notes

- The setup script is safe to run again; it does not reset existing settings or lose
  pending entries. Run again when the user asks to repair or update it: if the installed
  version already matches this plugin it re-checks the registration rather than
  downloading anything.
- An upgrade asks the running watcher to stop and waits up to a minute; it never ends it by
  force. If setup says the previous watcher is still running, it will exit when it finishes
  what it is doing; then `start_watcher` starts the new version. Do not end the process
  yourself.
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
running, does not remove the `codex-auto-resume-windows` marketplace the setup script
registered, and does not remove the installation the setup script made.

To remove everything, in this order:

1. `uninstall` - stops the watcher, then removes the Windows registrations that belong to
   this installation (sign-in entry, notification sender, Start Menu entry). If it cannot
   confirm the watcher stopped it removes nothing and says so; report that and stop. It also
   deletes its logs. Add `--purge` to delete settings and pending recoveries too; without it
   they are kept so a later setup picks them up.
2. `codex plugin remove codex-auto-resume@codex-auto-resume-windows` - takes away this skill.
3. Run `codex plugin marketplace list --json`. If `codex-auto-resume-windows` is listed and its
   `root` is inside the installation folder, remove it with
   `codex plugin marketplace remove codex-auto-resume-windows`. If it points anywhere else,
   leave it and tell the user where it points.
4. Tell the user to delete `%USERPROFILE%\.codex-auto-resume`, which still holds the
   application, the bundled Python and the settings window. If Windows reports a file in use,
   Codex or the settings window still has it open: close both and try again. Do not delete it
   for them without asking - if they skipped `--purge` it also holds their pending recoveries.

Say which of the four you did. "Removed completely" is only true after all four.

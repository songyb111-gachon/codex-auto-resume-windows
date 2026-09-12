# Codex Auto Resume

**Safe auto-resume and auto-retry for interrupted Codex tasks on Windows.**

[![tests](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml/badge.svg)](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml)
[![latest release](https://img.shields.io/github/v/release/songyb111-gachon/codex-auto-resume-windows?label=release)](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest)
[![platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)](#install)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<sub>🇰🇷 <a href="README.ko.md">한국어 README</a></sub>

Hit a Codex usage limit, a rate limit, or a dropped connection in the middle of a long task?
Codex Auto Resume waits, checks that it is genuinely safe, and then continues **that exact
conversation** — so you come back to finished work instead of a stopped task.

It is a small local watcher for the Windows ChatGPT/Codex desktop app. It reads Codex's own state
read-only, classifies what actually went wrong, and sends one continuation message through the
official `codex queue` command. The watcher has no network code of its own, and nothing is sent
to this project. Before a resume it checks your usage by asking the official Codex binary, which
gets the answer from OpenAI; the resumed turn then runs in your desktop app under your own Codex
settings and goes to OpenAI like any turn you start; what this plugin's tools and commands return
in a Codex conversation goes to OpenAI with that conversation; setting it up from Codex downloads
the release from GitHub; and installing with v0.5.7 also has Codex refresh every Git marketplace
you have configured (naming only this one is on the main branch and ships in the release after
v0.5.7).

**It deliberately does not retry everything.** A failure it cannot name is left alone.

|  |  |
| --- | --- |
| **Recovers** | Codex usage limits, and these when Codex records a specific error code for them: rate limits (HTTP 429) · network failures · timeouts · temporary server errors (5xx) · dropped response streams. Codex 0.153.4 records many timeouts, dropped streams and 502/503/504 errors with a generic code; one that carries no HTTP status is not retried, and one that carries a status is classified from it (429 a rate limit, 408 and 425 a timeout, 500-599 a server error, any other 4xx permanent). An HTTP 429 it has given up retrying is recorded as `responseTooManyFailedAttempts`, and that one is recovered as a rate limit; the same code with any other status, or none, is not |
| **Never touches** | user cancellation · permission · approval · content policy · invalid requests · context length · permanent authentication failures · anything unclassified |
| **Identity** | the exact conversation UUID only — never `--last`, never "the most recent one", never a title or a folder name |
| **Configure it** | a Windows window from the Start Menu — on the main branch, shipping in the release after v0.5.7, a Dashboard whose settings are one of its six pages — a settings panel inside Codex, or the command line |
| **Tells you** | Windows notifications when a task is interrupted, when recovery starts, how it went, and when it gives up. While the watcher runs it also shows a notification-area icon, whose tooltip says whether recovery is paused, how many recoveries are waiting, how many are running in Codex, and how long until the next check (main branch; ships in the release after v0.5.7) |
| **Privacy** | no telemetry, no analytics, no update check, never reads your credentials. The watcher has no network code; the usage check, the resumed turn and what the plugin's tools and commands return in a conversation go to OpenAI through Codex, as Codex's traffic always does; setup downloads the release from GitHub; and the v0.5.7 installer has Codex refresh every Git marketplace you have configured (naming only this one is on the main branch and ships in the release after v0.5.7) |

> **One honest limitation, up front.** Codex has to currently have that conversation open for a
> recovery to be delivered. If the app restarted since, open the conversation once and recovery
> continues on its own. [Why this is unavoidable today](#please-read-this-limitation-first).

## Install

**Windows 10/11. No Python needed. No administrator rights.**

### From Codex (recommended)

Add the plugin, then ask Codex to **set up auto resume**.

```
codex plugin marketplace add songyb111-gachon/codex-auto-resume-windows
codex plugin add codex-auto-resume@codex-auto-resume-windows
```

Codex will run the plugin's setup script, which downloads the matching release from this
repository's releases over HTTPS and checks its SHA-256 against the digest recorded for that
version in the plugin's
[`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json).
That digest is committed to this repository after the release is published; it does not come
from the release itself. A version with no digest in the plugin's copy of `release.json` is
checked against the `.sha256` published with the release instead, and the script says so. That
covers a version newer than the last recorded digest, and always the installed plugin's own
version, because a release cannot contain its own digest and after installation the plugin runs
from the installed copy. It then checks the contents really are this product at this version,
and only then installs, for your Windows user only: files in the installation folder (by
default `%USERPROFILE%\.codex-auto-resume`), a Start Menu entry (when notifications are on, as
they are by default), per-user registry values, and
this plugin's marketplace and plugin registration in Codex, pointed at that installation. The
plugin's instructions have Codex tell you before it does any of that.

This route downloads a published archive, and every archive published so far, v0.5.0 through
v0.5.7, was built by the earlier single-job release workflow, with GitHub Actions referred to
by floating tags and executables that cannot be rebuilt byte for byte. Step 2 of
[From the release archive](#from-the-release-archive) lists what replaces that; those changes
are on the main branch and ship in the release after v0.5.7.

The plugin as added from GitHub carries the skills, that setup script and the engine's Python
source, but no interpreter to run that source, and its manifest declares no MCP server (the
`.mcp.json` it carries points at an executable that only the release contains); the running
watcher, the settings window, the panel's own server and the Windows runtime all come from
that release. That is why there is a download, and why it is worth reading
[`docs/PLUGIN.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md)
if you would rather know exactly what the script will and will not do before running it.

### From the release archive

If you would rather download the release yourself instead of having the setup script do it:

1. Download `CodexAutoResume-vX.Y.Z-win-x64.zip` from the
   [latest release](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest).
2. **Verify it before you extract it.** `Install.cmd` does not verify the archive it came in (no
   hash, no signature), so this step is the check. In PowerShell, in the folder you downloaded it to:

   ```powershell
   (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   ```

   The value must match the `.sha256` file published beside the archive, and the digest
   recorded for that version in
   [`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json)
   on the `main` branch (`Get-FileHash` prints capital letters; the case does not matter). The
   `.sha256` comes from the same place as the archive, so it shows the download is intact; the
   `release.json` entry is a commit in this repository, not a release asset, so it is a separate
   record: changing it takes a new commit on `main`. It is added after a
   release is published, so a brand-new version may not be listed yet, and anything before
   v0.5.2 has no entry; the attestation check
   below does not depend on it. With the GitHub CLI you can check which workflow run and commit
   built the archive (archives from v0.5.4 on carry an attestation):

   ```powershell
   gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip --repo songyb111-gachon/codex-auto-resume-windows
   ```

   If anything does not match, delete the file and do not run it.
   [`docs/VERIFY.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)
   explains each check and what it does and does not prove. Every archive published so far,
   v0.5.0 through v0.5.7, was built by the earlier single-job release workflow, which referred
   to its GitHub Actions by floating tags and produced executables that cannot be rebuilt byte
   for byte. Separate build and publish jobs, actions pinned to exact commits, and reproducible
   executables are on the main branch and ship in the release after v0.5.7.
3. Extract it anywhere and double-click **`Install.cmd`**.

The archive carries its own Python runtime, so there is nothing to install first, and the
recommended settings are already on when it finishes. `Install.cmd` downloads nothing itself:
it registers the Codex plugin from the files in the archive, so this route gets the panel too.
It does ask Codex to refresh marketplaces, though. The installer in v0.5.7, the latest release
and so also the one the Codex route installs today, asks Codex to refresh every Git marketplace
you have configured, and Codex fetches each of them from wherever it is hosted. On the main
branch the installer names only this product's marketplace, which does nothing for the local
registration it has just made; Codex fetches only if an earlier GitHub registration of that
marketplace survived the repoint. That change ships in the release after v0.5.7.

Nothing this project builds is Authenticode-signed: not the two executables, not `Install.cmd`
or `Uninstall.cmd`, and not its PowerShell or Python scripts. The bundled Python interpreter
keeps the Python Software Foundation's signature (`pythonw.exe`, `python.exe` and the Python
DLLs; its two Visual C++ runtime DLLs are signed by Microsoft), and the watcher runs under that
`pythonw.exe`. On either route, Smart App Control, where it is turned on, may block the two
unsigned executables: the settings window `CodexAutoResumeSettings.exe` and
`codex-auto-resume-mcp.exe`, which Codex starts for the plugin's tools and panel. On this manual
route it may also block `Install.cmd` and `Uninstall.cmd`, and SmartScreen may warn of an
unknown publisher, because Explorer keeps the downloaded-file mark. Such a warning or block means the file is unsigned and has no
reputation with Microsoft yet (or is a script type downloaded from the internet); it does not
tell you whether the file is the one this project published. Step 2 does.

### Either way

Both routes end at the same installation, by default in `%USERPROFILE%\.codex-auto-resume`: one
watcher, one database, one settings file, one sign-in entry. Running either again is the
upgrade and the repair path, and keeps anything already waiting to resume. An upgrade asks the
running watcher to stop and waits up to a minute so the new version takes over; it never kills
it, and if the old one is still finishing it leaves it running and says so. If Codex cannot
replace the plugin because this plugin's own MCP launcher is holding its files open, the
installer force-stops that launcher and tries again; Codex starts a new one when it next needs
it. `Uninstall.cmd`, or asking Codex to remove it, removes it; see [Uninstall](#uninstall) for
what each route leaves behind.

Afterwards, change anything from **Start Menu → Codex Auto Resume**, or by asking Codex to
*open auto resume settings*.

## What it looks like

When a task is interrupted, Windows tells you — as **Codex Auto Resume**, not as whatever
process happened to raise it. Doing nothing resumes; the button is the only action, and it
only ever cancels.

<img src="docs/images/notification.png" alt="A Windows notification from Codex Auto Resume saying a usage limit was reached and the task will resume after the reset, with a Don't resume button" width="470">

Inside Codex, ask to *open auto resume settings* and the panel shows what is waiting and
lets you change any of it. This is the panel's own page, rendered from the exact resource
the plugin serves to Codex, rather than a photograph of the Codex window around it:

<img src="docs/images/settings-panel.png" alt="The Codex Auto Resume settings panel: a status line saying the watcher is watching for interruptions with two recoveries pending, a table of what is waiting to resume, and cards for the recovered failure categories, the attempt limits and the notification switches" width="680">

The Start Menu opens a standalone window, which works with Codex closed. On the main branch,
shipping in the release after v0.5.7, it is a Dashboard: what the watcher is doing, what is
waiting and when it is next looked at, what finished and how, the last week's numbers, the
watcher's health, and the settings. It is a native window; there is no local web server and
nothing opens in a browser. The pictures below are of a scratch installation holding sample
records, not of anyone's real conversations; until that release, the version in their footer
is the latest release's number, because the version changes only when a release is made.

<img src="docs/images/dashboard-overview.png" alt="The Codex Auto Resume Dashboard overview: automatic recovery on, the watcher running and the Codex engine verified, two recoveries waiting with the next check in a minute and a half, the last seven days' interruptions, continuations sent, recoveries and success rate, and the four most recently finished recoveries" width="680">

Each waiting recovery shows why it is waiting and when it is next checked. **Retry now** only
asks the watcher to look again now — every check still applies, and nothing is sent unless
they all pass. **Cancel** stops recovering that interruption and everything that continues it:
a record that was never sent is cancelled outright, one that may already be in Codex is marked
and taken back if it is still queued, and a finished one is marked too, so no later failure of
that task can start a new chain from it. A turn already running in Codex is not stopped, and the
confirmation says so. **Turn off for this conversation** cancels its waiting recoveries and keeps
automatic recovery off for that conversation until you turn it back on — the Pending and History
pages then offer **Turn on for this conversation**:

<img src="docs/images/dashboard-pending.png" alt="The Pending page of the Dashboard: two conversations waiting, one for the usage reset in about forty-two minutes and one with a retry scheduled in about a minute, with Retry now, Cancel, Timeline and Turn off for this conversation buttons" width="680">

<img src="docs/images/settings-window.png" alt="The Settings page of the Dashboard, showing which failures are recovered, the attempt limits, the retry timing, the notification switches and the Windows options" width="680">

While the watcher runs it also puts an icon in the notification area. It belongs to the watcher
process itself, so it appears when one starts and goes when it stops. Its tooltip says whether
recovery is paused, how many recoveries are waiting, how many are running in Codex and how long
until the next check; its menu opens this window, pauses or resumes recovery, and stops the
watcher. The countdown only means the watcher looks again — nothing is sent because it reaches
zero. It is on by default and can be switched off on the Settings page. Main branch; it ships in
the release after v0.5.7.

## Please read this limitation first

This tool can only auto-resume a thread that the Windows ChatGPT/Codex desktop app **currently has
loaded**.

After the app restarts, a target thread is `notLoaded`. There is **no verified, supported way to wake an
unloaded thread programmatically**. When this was measured, a message queued for an unloaded thread
stayed in the queue and was not delivered as a conversation turn during the 90 seconds the thread
stayed unloaded; see
[`docs/evidence/unloaded-thread-delivery.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/evidence/unloaded-thread-delivery.json).
Codex may still deliver such a message later, when the thread next loads. So this tool queues only
for a thread it has just confirmed is loaded, and asks Codex to withdraw its own queued message if the
thread is reported unloaded before the message arrives. If Codex does not confirm the withdrawal, the
message may stay queued; the record is then marked `submission_unknown` and is never resent.

So an unloaded thread is resumed **only after you open that conversation in the ChatGPT app yourself**.
Until then the watcher simply waits in its `waiting_for_loaded_thread` state, which the window and
the Codex panel report as the public code `waiting_thread` and show as "waiting for the
conversation", and which the command line prints beside the state. It
will not use GUI automation, will not force the conversation open, and will not queue a message on
the off chance.

This is not fully unattended auto-resume across app restarts, and this README will not pretend otherwise.

## Project direction

> Keep the recovery engine small, local, conservative, and fail-closed. Spend complexity on making it
> easy to install and control, not on making the runtime do more.

The recovery engine is deliberately one small watcher. Everything else exists to see and control it:
a standalone Windows window — a settings window up to v0.5.7, a Dashboard on the main branch — a
settings panel inside Codex over MCP, the command line, the watcher's own notification-area icon, and
Windows notifications. None of those can recover anything by itself, and the watcher keeps running
whether or not any of them is open.

What the project still avoids: a separate tray process, a management web UI, a supervisor process, a
Windows service, a second recovery engine, and a second state database. The notification-area icon is
not an exception: the watcher owns it, so it cannot show a watcher that is not there, and everything
its menu offers goes through the same control layer as the other surfaces.

## Features

- Recovers usage limits and clearly classified temporary failures, on separate policies. Never
  retries a failure it cannot classify.
- Tracks the exact thread UUID. Never `--last`, never a guessed thread.
- Waits for the real reset timestamp when one is available, instead of sleeping a fixed number of hours.
- Verifies the desktop app is running and the thread is genuinely loaded before sending anything.
- Never resumes the same interruption twice, including across a crash or a watcher restart.
- Durable pending state in SQLite that survives reboots.
- Handles several interrupted threads independently.
- Bounded retry backoff, a global kill switch, and per-thread control.
- Single-instance protection, optional per-user Windows autostart, and a conservative uninstall.
- Three ways to change a setting — a Start Menu window, a panel inside Codex, and the command
  line — all writing the same file through the same validator, so they cannot disagree.
- Windows notifications across the lifecycle: interruption detected, recovery starting, how it
  turned out, and when it stops for good. Each one has its own switch.

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
- The official Windows ChatGPT/Codex desktop app, running, with its engine at
  `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`.
- The engine is located automatically. A version this tool has been verified against is trusted
  outright; after a Codex update an unrecognised version is accepted only if `codex queue` still
  offers `--thread` and `--message`, and `status`/`doctor` label it as unverified. Anything that
  cannot prove that interface is refused rather than guessed at.

**Python is not required by either install route** — the installation brings its own runtime, and
the plugin's setup script is PowerShell. Python 3.12+ is needed only if you run the engine from a
source checkout.

## What is recovered, and what is not

Automatically recovered:

| Failure | Policy |
| --- | --- |
| Usage limit (`usageLimitExceeded`) | Waits for the real reset timestamp, then re-checks live usage |
| Connection failure (`httpConnectionFailed`) | Bounded backoff |
| Timeout (HTTP 408/425) | Bounded backoff |
| Transient rate limit (HTTP 429, `rateLimitExceeded`, and `responseTooManyFailedAttempts` carrying a 429) | Bounded backoff, with a first wait of at least a minute |
| Server error (HTTP 5xx, `serverOverloaded`, `internalServerError`) | Bounded backoff |
| Stream disconnection (`responseStreamDisconnected`, `responseStreamConnectionFailed`) | Bounded backoff |

Never recovered — these need a person, and retrying only wastes attempts:

user cancellation · permission · approval required · content policy · invalid request ·
context length exceeded · permanent authentication (401/403, `unauthorized`) · `badRequest` ·
`sandboxError` · `responseTooManyFailedAttempts` with any status but 429 · **anything unrecognised**.

Classification is structural: it reads the `codexErrorInfo` variant Codex writes, then an HTTP status
carried by that variant. Message text is consulted only when there is no structured code at all, and
only for transport failures that have none. A structured code is never overridden by message text.

Recovery is bounded three times over: at most 4 attempts per interruption, it stops after 3
consecutive recoveries that produced no visible progress, and one task receives at most 6
continuations in total across every failure of it — a failure of our own recovery turn continues that
same chain instead of starting a fresh budget. The per-task limit accepts 1 to 10 and nothing outside
it. If you carry on in that conversation yourself, the old interruption is dropped rather than
replayed on top of your work.

## Managing it from Codex

Once it is installed, either route gives you the same skill. Just ask, in the app:

> Set up auto resume

and afterwards "show auto resume status", "show pending auto resumes", "open auto resume
settings", "turn auto resume off" and "turn auto resume back on", "cancel auto resume for this
task", "show auto resume statistics", "show the timeline for that recovery", "try that recovery
now", "give that recovery its attempts back", "start the watcher", "clear auto resume history",
"uninstall auto resume".

Nothing that turns automation down is marked as needing your confirmation: pausing recovery, turning
it off for one conversation, asking for a re-check. Turning it back on, changing a setting, starting
the watcher, cancelling a recovery, giving a recovery its attempts back and clearing the history are
all marked so that Codex asks you first.

The plugin is a thin front end over the same validated control layer the command line and the Start
Menu window use: its tools call that layer directly, and the skill falls back to the commands below
when the tools are not available. It adds no second engine and no background service. It keeps its
state in `%USERPROFILE%\.codex-auto-resume\`, outside the plugin directory, so updating or removing
the plugin never loses a pending resume. The watcher keeps running when the Codex app is closed, and
starts again at Windows sign-in.

See [docs/PLUGIN.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md) for the layout, exactly what the setup script will and will
not do, the update and removal lifecycle, and why the usage-limit notice does **not** get a checkbox.

> There is one installation, and both routes converge on it. If you also run a source checkout,
> keep only one: separate state means two watchers, and two watchers could resume the same task
> twice. Setup detects that and refuses rather than creating the second one.

## Running it from source

For development, or if you would rather run it yourself. This is not a third way to install the
product — it is the engine on its own, with no settings window, no panel and no bundled runtime,
and it needs **Python 3.12 or newer** on your PATH.

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

`doctor` queues no message and opens none of Codex's files for writing; the only things it may
create are this tool's own state and log folders, the ownership marker in each, and its log
file, if they are missing. It reports the discovered engine, whether the app is paired, whether
the Restart Manager probe works, and whether the local history is readable.

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
| `doctor` | Environment check that queues nothing: engine, app pairing, Restart Manager, history. |
| `enable [thread-id]` | Turn auto-resume on globally, or for one thread. |
| `disable [thread-id]` | Kill switch: stop all automatic resumes, or just one thread. |
| `status` | Enablement, watcher state, autostart, engine, and record counts. |
| `pending` | Interruptions waiting to resume (`--all`, `--json`). |
| `cancel <thread-id>` | Cancel pending resumes for one thread and disable it. |
| `logs` | Recent log lines (`-n N`). |
| `run` | Run the watcher in the foreground (`--once`, `--poll N`). |
| `stop` | Ask a running watcher to exit. |
| `install` | Create the owned directories and state (`--startup`). |
| `uninstall` | Remove autostart and owned state/logs (`--keep-logs`, `--keep-state`). |
| `diagnostics` | Write one redacted diagnostics file, to read before you share it (`--out`). |
| `downgrade-state --to 2` | Rewrite the state file for a v0.5 release; stop the watcher first. |

Global options: `--home` (where this tool keeps its own state), `--codex-exe`, `--codex-home`, `--quiet`.

By default, failures up to 6 hours old at the moment you run `enable` are still eligible. Change it with
`enable --lookback-hours N`.

## The notification

When the watcher records an interruption, Windows shows one notification naming the task, with a
single cancel button.

```
Payment retry refactor
Codex usage limit reached. This task will resume at 05:56.
example-project  ·  Thread: 0a1b2c3d-0109-7000-8000-000000000109
                                             [Don't resume]
```

The first line is the conversation title, or the project, or the working directory's name, or
"Codex task". The **exact thread UUID is always shown**: titles repeat, identity must not. A
temporary failure says "Codex was temporarily interrupted. Retrying automatically." instead, with a
**Don't retry** button.

Three lines, not four: Windows renders at most three and drops the rest, so the reason comes
before the identifiers rather than after them.

Those names are for display only. Recovery never resolves a thread by title, project or recency.

Doing nothing resumes — that is the default. Pressing the button cancels the auto-resume for that
one conversation and nothing else.

This is the only point where a control can be offered at the time it matters. By the time a usage
limit appears in the Codex app, that turn has already failed, so nothing can be added to the app's
own usage-limit notice; the watcher, however, is running. See [docs/PLUGIN.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md) for
why the notice itself cannot get a checkbox.

Details worth knowing:

- The button needs a handler, so `install` registers a per-user `codex-auto-resume:` URL protocol
  under `HKCU\Software\Classes`. `uninstall` removes it again, and only when it points at this
  installation.
- That protocol accepts exactly one action, cancelling. A hostile or mistyped URI can only ever
  *stop* a resume, never cause one, and the interruption id must match a real record.
- The notification shows labels, a local time and the thread UUID — never prompt text, error text,
  or account data. Display names come from `threads.name` only; `title`, `preview` and
  `first_user_message` hold the raw first prompt on this schema and are never read.
- It is best effort. If it cannot be shown, the resume still happens exactly as it would have.
- They are attributed to **Codex Auto Resume**, with this project's own icon. That takes two
  registrations, not one: an AppUserModelID under `HKCU\Software\Classes\AppUserModelId` supplies
  the name and icon, and a Start Menu shortcut carrying the same id is what makes Windows draw
  the toast at all. Without the shortcut the platform accepts the notification, logs it, and
  files it in the notification centre without ever showing it. That was measured, not assumed.

Three more notifications follow the first: recovery starting, how it turned out, and recovery
stopping for good. Each is raised once, from the state change itself, so what the notification
says and what the record holds can never disagree. An uncertain submission is reported as
uncertain rather than as a failure that will be retried, because it is the one outcome that is
deliberately never resent.

Turn any of them off in the settings window, or from Codex, or with `update_settings`. Doing so
changes nothing about whether a task is recovered.

## Settings

Everything configurable lives in one place and is reachable three ways:

- **Start Menu → Codex Auto Resume** — a standalone window. It works with Codex closed, the
  plugin disabled, no network, no sign-in and no system Python, because configuration matters
  most exactly when the thing it configures is unavailable.
- **Inside Codex** — ask to open auto resume settings and a panel appears in the conversation.
- **The command line** — for scripting and for repair.

All three write the same file through the same validator, so a value set in one is the value the
others show. Nothing needs to be memorised and nothing needs hand-editing: a hand-written
settings file is validated on read, so a bad value is quietly replaced by the safe default and
you are left believing you changed something.

You can choose which classified failure categories are recovered, how many attempts each
interruption gets, how many continuations one task may receive in total, when to give up after
recoveries that produce nothing, how long to wait between attempts, which notifications appear, and
whether the watcher shows its notification-area icon.

You cannot switch off a safety property, because none of them is a setting. There is no option
that retries an unclassified failure, resolves a conversation by title, resends an uncertain
submission or forces a send — by design, not by omission.

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

Run `Uninstall.cmd` from a release archive, or ask Codex to uninstall auto resume.
`Uninstall.cmd` keeps your settings and pending recoveries by default (it deletes its main and
error logs; `logs\launcher.log` stays), so reinstalling picks them up; `Uninstall.cmd -Purge` deletes those too, or you can delete the installation folder
(by default `%USERPROFILE%\.codex-auto-resume\`) yourself. Asking Codex stops the watcher,
removes its Windows registrations and the plugin, and keeps your settings and pending
recoveries unless you ask it to delete them too; it leaves the installation folder, which still
holds the program files, for you to delete. `Uninstall.cmd` also removes this product's
marketplace from Codex while it still points at this installation.

From a source checkout, the same command-line tool also deletes this tool's own state and logs
(`--keep-logs` keeps the logs):

```bash
python src\auto_resume.py uninstall
```

```bash
python src\auto_resume.py uninstall --keep-logs
```

Uninstall is deliberately conservative:

- It asks the watcher to stop first. If a watcher is still running, **or if it cannot verify
  whether one is running**, it aborts before removing anything.
- It removes the sign-in autostart value and the notification identity only while they belong
  to **this** installation. A value that starts a different copy of the tool is reported and
  kept, never silently removed. The Start Menu entry is kept while the notification identity
  belongs to a different installation; if no notification identity is registered at all, the
  entry at its fixed location is removed without an ownership check.
- It deletes only inside directories it can prove it owns. The source command requires this
  tool's provenance marker (`.owned-by-codex-auto-resume`) in each directory it deletes from;
  `Uninstall.cmd` requires the marker at the installation root or in `config/`, or a
  `runtime.json` that names that very directory. A directory that merely contains folders called
  `app`, `runtime`, `config` or `logs` is refused and reported, and nothing in it is deleted.
- The source command deletes only its own file names inside its own directories, so unrelated
  files there survive. `Uninstall.cmd` removes the program folders `app\` and `runtime\` whole,
  and with `-Purge` also the rest of `config\` and `logs\`.
- `Uninstall.cmd` asks the `codex` CLI to remove this plugin and its marketplace only while they
  still point at this installation; if either points somewhere else, it leaves it configured and
  says so. Removing the plugin makes Codex delete its own cached copy of it. The source command
  does not touch the Codex registration.
- None of them deletes a ChatGPT or Codex conversation, a Codex file, a user repository or a
  parent directory itself.

## Safety model

What it writes itself while running: its own `config/` and `logs/` (plus the bytecode cache
Python writes inside its own program folder). Turning start-at-sign-in on or off from the
settings changes the per-user Run value, and Windows keeps the notifications it shows in its
notification history. One thing it writes elsewhere, and only when asked: **Export diagnostics...**
on the Diagnostics page, and `diagnostics` on the command line, write one redacted JSON bundle to a
path you choose; it sends nothing and refuses to overwrite an existing file. What it asks Codex to
do, through official interfaces: queue one
continuation message for one exact thread (`codex queue`), and withdraw that same queued
message if it has to (the App Server's `thread/queue/delete`). Installing asks
the `codex` CLI to register this plugin and its local marketplace, and a marketplace already
registered under this product's name (`codex-auto-resume-windows`) is repointed at this
installation. Installing also asks Codex to refresh marketplaces. The v0.5.7 installer
refreshes every Git marketplace you have configured. Refreshing only
`codex-auto-resume-windows` is on the main branch and ships in the release after v0.5.7.
`Uninstall.cmd` asks the `codex` CLI to unregister the plugin and its marketplace, only while
they still point here.

Design rules enforced in code:

- **No network code.** Nothing in the recovery runtime imports a networking module, and a test
  fails if an import line in a tracked Python file under `src/` or `scripts/` names one of the
  common networking modules (`socket`, `ssl`, `http`, `urllib.request` and others), so the
  watcher opens no connection of its own. What does reach the network, and through what, is listed under [Privacy](#privacy).
- **Opens no Codex file for writing.** Codex databases are opened with `mode=ro` and
  `query_only`, and no Codex database, rollout or configuration file is opened for writing. For a
  database in SQLite's WAL mode, a read-only reader may still update the shared-memory index
  (`-shm`) beside it; whether Codex's databases use WAL has not been checked. Changes to Codex's
  state are requested from Codex itself, as above. The Codex processes it starts may update
  Codex's own logs and caches, as any Codex process does.
- **Fail closed.** Unknown loaded state, unknown usage, an unavailable probe, or any ambiguity results in
  waiting, never in sending.
- **Checked again at the last moment.** Immediately before sending, it re-reads the record and
  checks that it is still valid and allowed, that the same app is running with the thread
  loaded, and that usage is available (from a usage reading at most 30 seconds old). The
  reservation is one SQLite write transaction, so only one watcher can reserve a given
  interruption, and only one watcher at a time can run against the same state directory
  within a Windows session.
- **Exact thread only.** Thread ids are validated as canonical UUIDs and passed as separate argv
  elements. No Python code uses `shell=True`, `os.system`, `eval` or `exec`, and every Python
  subprocess gets an argument list.
- **Only what it can classify.** A failure it cannot classify is not retried, and neither is any
  category listed as never recovered under
  [What is recovered, and what is not](#what-is-recovered-and-what-is-not).
- **Values are data, not script.** Windows PowerShell runs the installer, the uninstaller and the
  plugin's setup script. The tool's own code also uses it, each time with a fixed script, to list
  the ChatGPT/Codex processes, raise notifications and create the Start Menu shortcut. Values such
  as a conversation title or a folder name reach those scripts as environment variables, which the
  scripts read as plain text and do not run. Releases v0.4.0 through v0.5.6 wrote those names into
  the script text, where a name containing a curly quote could run PowerShell; v0.5.7 and later
  pass them only as data.
- **No duplicate resume.** The interruption is durably reserved before any external process can
  accept a message. If the outcome of a send is uncertain, it is never resent: the watcher keeps
  checking for up to 24 hours whether the message arrived, and marks it resumed if it did.
- **Logs are built from codes, not from content.** Engine events are logged from a fixed message
  table as reason codes, timestamps and identifiers, with any other detail masked, so no prompt
  text, Codex error text or account identifier is written through it. The main log also records
  its own state directory, a path that, at the default location, contains your Windows user name,
  and the version string of an engine this tool has not been verified against. Tracebacks go to a
  separate rotating `errors.log`, which also contains local paths. The launcher writes its own
  exception messages to `logs\launcher.log`.
- **Settings are policy only.** No setting can switch off a safety property; see
  [Settings](#settings).
- **Never used:** GUI automation, mouse or keyboard simulation, OCR, screen scraping, accessibility-API
  clicking, binary patching, DLL injection, process-memory manipulation, credential extraction.

## Privacy

Nothing is sent to this project: there is no telemetry, analytics, crash reporting or update
check, and no server of this project's to receive them. The tool itself transmits none of your
prompts, the assistant's replies, tool input or output, file contents, account identifiers,
credentials or error text anywhere. The recovery runtime (`src/`, `scripts/*.py`) imports no
networking module, and a test fails if an import line in a tracked Python file under `src/` or
`scripts/` names one of the common networking modules (`socket`, `ssl`, `http`,
`urllib.request` and others).

What this tool causes to reach the network, as far as has been checked, goes to OpenAI and
GitHub, and, while the v0.5.7 installer runs,
to wherever your other Git marketplaces are hosted:

- **OpenAI, through Codex.** Before a resume, the official Codex process this tool starts asks
  OpenAI for your current usage. The resumed turn runs in the desktop app under your own Codex
  settings and sends that conversation to OpenAI, as any turn you start does. When the plugin's
  tools or commands run inside a Codex conversation, what they return (status, pending
  recoveries with their conversation ids, and, from commands such as `status`, `doctor` and
  `logs`, local paths that at the default location contain your Windows user name) becomes part
  of that conversation, and Codex sends it to OpenAI like any tool output. In v0.5.7 the
  `get_status` and `open_settings` tools also return the installation folder's path. Removing
  it from those tools is on the main branch and ships in the release after v0.5.7. The commands
  still print local paths.
- **GitHub, when installing.** Installing or updating from the plugin makes the setup script
  download that version's release archive from GitHub over HTTPS (and its `.sha256` when the
  plugin has no digest recorded for that version). Nothing is uploaded, but GitHub sees the
  request, as with any download. Downloading the archive yourself is the same GitHub download;
  after that, `Install.cmd` downloads nothing itself, but it does ask Codex to refresh
  marketplaces (next item).
- **Your Git marketplaces' hosts, while the v0.5.7 installer runs.** Both install routes run
  that installer today whenever they install or upgrade (the plugin's repair of an
  already-installed version does not). It asks Codex to refresh every Git marketplace you have
  configured, and Codex fetches each one from wherever it is hosted, which may be neither
  OpenAI nor GitHub. Naming only this product's marketplace instead is on the main branch and
  ships in the release after v0.5.7; see [From the release archive](#from-the-release-archive).

Codex's local state is opened read-only. Recovery decisions come from Codex's structured
records (and, only where Codex recorded no error code, a short list of transport-failure
phrases in the error message), not from what was said in the conversation, but some reads do pass over conversation content: for a
usage limit it parses up to 8 MiB of the conversation's rollout file before the failure to find
the reset time, keeping only the rate-limit numbers; and to confirm its own message arrived, it
has SQLite search that conversation's user and queued messages for its own marker. That content
is handled in memory and discarded; none of it is stored, and the main log does not record it.

Its own records live in the installation folder (by default `%USERPROFILE%\.codex-auto-resume\`).
Elsewhere it leaves a Start Menu shortcut, a sign-in entry, the Windows registrations its
notifications need, and this plugin and its marketplace registered in Codex; `Uninstall.cmd`
removes those that belong to this installation. Separately, Windows' notification history keeps
the notifications it showed, and each resumed conversation keeps the continuation message and
its marker as part of the conversation. [PRIVACY.md](PRIVACY.md) has the details.

## Known limitations

- Only threads already loaded in the app can be auto-resumed. Unloaded threads wait for you to open them.
- The blocking usage bucket cannot always be identified with certainty, so live availability is
  re-checked immediately before sending rather than trusted from history.
- Codex app updates are survivable but not guaranteed. Database files are found by schema generation
  (`state_5` -> `state_6`) and validated by the columns actually read, and an updated engine is accepted
  when the `codex queue` interface is unchanged. A change that removes a column this tool reads, or that
  alters the queue interface, still stops it: it refuses rather than guessing.
- If the watcher process dies in the narrow window after reserving but before the send result is known,
  that interruption is deliberately left unresumed rather than risking a duplicate.
- The full end-to-end path has now been observed once in ordinary use: a real usage limit was detected,
  the thread was confirmed loaded, the interruption was reserved, one continuation was submitted through
  `codex queue`, and delivery was independently confirmed 30 seconds later. That is one run, not a
  track record. Transient-failure recovery has been exercised by tests, not yet by a real outage.

## Testing

Run the automated suite:

```bash
python -m unittest discover -s tests
```

Set `PYTHONPATH=src` first (or use `set PYTHONPATH=src` on Windows).

These tests use fakes and temporary directories. They never contact the ChatGPT app and never send a
message to any conversation, so they are safe to run anywhere and are what CI runs.

There is also an opt-in live check against your real environment. It verifies binary discovery,
app pairing, loaded-state classification, and usage reading. It sends no message to any
conversation; reading usage does ask OpenAI for your current usage through Codex, as the watcher
does before a resume:

```bash
set CODEX_AR_LIVE=1 && python -m unittest tests.test_integration_live
```

## Security

See [SECURITY.md](SECURITY.md) for the full model, the review process, and the issues that were found
and fixed. In short: the recovery runtime has no network code and reads no credentials; it reads
Codex's state read-only, opens none of Codex's files for writing, and makes its changes to Codex's
state by asking Codex through official interfaces; what reaches OpenAI is Codex's own traffic; it
fails closed; and uninstall is conservative. The only download the shipped code makes itself is
the plugin's setup script fetching the matching release from GitHub, which it checks before
installing; the v0.5.7 installer also asks Codex to refresh your configured Git marketplaces (see
[From the release archive](#from-the-release-archive)). Release archives from v0.5.4 on also
carry a GitHub build provenance attestation, and
[docs/VERIFY.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)
shows how to check a download yourself. Every archive published so far, v0.5.0 through v0.5.7,
was built by the earlier single-job release workflow, with GitHub Actions referred to by floating
tags and executables that cannot be rebuilt byte for byte; the split into build and publish jobs,
commit-pinned actions and reproducible executables are on the main branch and ship in the release
after v0.5.7. Nothing this project builds is Authenticode-signed; the bundled Python interpreter
keeps the Python Software Foundation's signature.

The project went through three adversarial review rounds plus mutation testing, a crash-window matrix,
and a cross-process race test. Confirmed issues were fixed and covered by regression tests.

If you find a security issue, please open an issue on this repository. Do not paste
credentials, tokens, private conversation text or private repository content into a public
issue; diagnosing a problem does not need them.

## Documentation

| | |
| --- | --- |
| [docs/PLUGIN.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md) | The Codex plugin layer: what the setup script may fetch and what it checks, the update and removal lifecycle, and why the usage-limit notice cannot get a checkbox. |
| [docs/VERIFY.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md) | How to check that a downloaded archive is the one this project published, how to rebuild a release, and what those checks do and do not prove. |
| [docs/COMPARISON.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/COMPARISON.md) | Other projects in this space, and every feature adopted, adapted, rejected or deferred — with the reason. |
| [docs/BRAND.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/BRAND.md) | The palette, the mark, and why each is what it is. |
| [docs/DEVELOPMENT.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/DEVELOPMENT.md) | How it was built, including the measurements behind the loaded/notLoaded limitation. |
| [PRIVACY.md](PRIVACY.md) | What is read, what is stored, and what is sent anywhere. |
| [SECURITY.md](SECURITY.md) | The threat model and how to report a vulnerability. |
| [SUPPORT.md](SUPPORT.md) | Where to report each kind of problem, and what not to paste into a public issue. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Tests, the release build, fixture conventions, and the safety properties a change has to keep. |

## Development and credits

Built by **Youngbin Song** with the assistance of two AI development tools:

- **OpenAI Codex** — initial Windows/Codex architecture and protocol investigation, the exact-thread
  queue proof of concept, loaded/notLoaded verification, usage-limit and reset research, and the initial
  implementation.
- **Anthropic Claude Code** — took over that prototype, completed the watcher, CLI, Windows integration
  and persistence, expanded the tests, fixed correctness bugs, and ran the security and adversarial audits.

OpenAI Codex and Anthropic Claude Code are AI development tools, not human contributors or GitHub
accounts. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the full breakdown and
[docs/DEVELOPMENT.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/DEVELOPMENT.md) for the development history, including the measurements behind
the loaded/notLoaded limitation.

## License

MIT. See [LICENSE](LICENSE).

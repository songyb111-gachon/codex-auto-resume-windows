# Privacy

Codex Auto Resume runs on your machine. It has no server, no account and no telemetry, and
the watcher makes no outbound network request of its own.

It does cause network traffic, though, and that is worth stating up front rather than in a
footnote. There are three kinds, and they are genuinely different:

- **OpenAI, through Codex.** The watcher drives the official Codex binary already signed in
  on your machine. When a recovery is due, it asks Codex for your current usage, and Codex
  asks OpenAI. Codex identifies these requests as coming from this tool (client name
  `codex_auto_resume` and a version number), so OpenAI can see that you use it and when it
  checks. The resumed turn itself runs in your Codex desktop app and goes to OpenAI like any
  turn you start. And when you use the plugin's tools inside a Codex conversation, what they
  return becomes part of that conversation.
- **GitHub and, through Codex's marketplace refresh, other marketplace hosts, at install.**
  Installing or updating from the Codex plugin downloads the release from GitHub, as does
  downloading the ZIP yourself. The installer then asks Codex to refresh marketplaces: the
  installers of v0.4.0 through v0.5.7 refresh every Git marketplace you have configured,
  wherever it is hosted, while the installer from v0.6.0, refreshes only a surviving `codex-auto-resume-windows` registration, from
  wherever it points.

- **GitHub, when you ask whether there is a newer version.** From v0.6.0 the Diagnostics
  page has a *Check for updates* button, and `scripts/bootstrap.ps1 -CheckOnly` does the
  same from a command line. Pressing it makes one HTTPS request to
  `github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest`. It is a `HEAD`
  request, so no page is transferred and none is read: the answer is the address the
  redirect ends at. Choosing to install then downloads that release's archive and its
  checksum, which is the same download the installer has always made.

  Nothing about you is sent. The request carries no identifier this product invented — no
  installation id, no version of yours, no machine name, no account — and GitHub sees what
  it sees for any anonymous request to a public page: an IP address, a time and a user
  agent. It happens when you press the button and at no other time.

**There is no automatic update check.** Nothing polls, nothing checks on a schedule, and
nothing checks when the window opens or when the watcher starts. A machine that is never
asked makes none of these requests, and a machine that never installs makes none of the
GitHub requests at all.

The sections below take each in turn.

## What it sends to the developer

Nothing, beyond the aggregate download count GitHub shows for every release (see
[Installing it](#installing-it)) and, if you press *Check for updates*, one more anonymous
request to a public GitHub page. There is no telemetry, no analytics, no crash reporting,
no opt-in reporting and no automatic update check — no endpoint of any kind exists to
receive them, because no collection service is operated for this project. Local statistics
in the window are read from your own database and never leave it.

Specifically, this tool itself sends none of the following to its developer or to anyone
else; what reaches OpenAI through Codex is described next:

- your prompts, or any conversation content;
- assistant replies;
- tool input or tool output;
- file or repository contents;
- account identifiers, email addresses or subscription details;
- credentials, API keys, tokens or cookies;
- raw error bodies from the provider;
- conversation titles, project names or working directory paths;
- conversation UUIDs, recovery counts or any other statistic about what it did.

Some of it does leave your computer, and then through Codex, to OpenAI (or, for the
conversation, to whichever model provider you have configured Codex to use): the
conversation, when the desktop app runs the resumed turn; the usage check, which Codex
makes with your existing sign-in and identifies as coming from this tool; and, when you use
the plugin inside a Codex conversation, whatever its tools and commands return — which can
include conversation UUIDs, recovery counts and local paths.
[When you use it from Codex](#when-you-use-it-from-codex) says exactly what that is.

This is a property of the code rather than a policy: nothing under `src/` or `scripts/*.py`
imports a networking module, and a test fails if an import statement names one, so the
watcher opens no connection of its own. The connections it causes go through the official
Codex binary.

## Installing it

The Codex plugin is the recommended way in, and it is not self-contained: the watcher, the
settings window and the Windows runtime arrive in the release archive. So when you ask Codex
to set up auto resume, `scripts/bootstrap.ps1` downloads that archive, unless that version
is already installed and you did not pass `-Force` (then it re-runs setup instead: it
repairs the registrations and starts the watcher if it is not running) or you pass it a
file with `-ArchivePath`.

- The download contacts **github.com** and GitHub's release storage over HTTPS, following at
  most five redirects. After the download finishes, the host it finally landed on is
  checked. If it is not one of three GitHub hosts, the file is discarded and nothing from it
  runs. Because the check comes after the download, a redirect to another host would still
  send the request there, with the details below, before the file is refused.
- It downloads at most two things: this version's release archive and, only when the
  plugin carries no pinned digest for that version, the `.sha256` published beside it.
- The URL is built from constants in the repository and the plugin's own version. There is
  no "latest", and nothing you type becomes part of it.
- It uploads nothing. No prompt, conversation, account identifier, machine identifier or
  recovery data is attached to the request. GitHub sees your IP address and PowerShell's
  standard User-Agent, which names your Windows version and locale (for example `ko-KR`),
  as it would for any download made from PowerShell.

The downloaded archive is checked before anything in it runs: against the digest pinned for
that version in the plugin's `scripts/release.json`, which comes from the main branch, where
each version's digest is committed after its release is published; or, for a version with no
pin yet, against the `.sha256` published beside it. The bootstrap says which of the two it
used. When you hand the bootstrap a file with `-ArchivePath` instead and the version has no
pinned digest, there is nothing to compare the file with; the bootstrap says so, and only
its checks of the archive's contents apply.

The installer it then runs copies the program into the installation directory, registers
that copy with Codex as a local plugin marketplace, and installs the plugin from those files,
so Codex does not fetch the plugin again. Installing repoints the `codex-auto-resume-windows`
marketplace at this installation, replacing whatever source that name had. The installer
then asks Codex to refresh marketplaces, and how far that reaches depends on the version:

- From v0.6.0, the installer runs `codex plugin marketplace upgrade codex-auto-resume-windows`
— this product's marketplace, by name, and not the form that refreshes every Git marketplace
you have configured. For the local marketplace just registered, that command does nothing; it
only has an effect if an earlier registration under that name is still in place, and then Codex
refreshes it from wherever that registration points (normally GitHub). This is new in v0.6.0. -
The installers of v0.4.0 through v0.5.7 run `codex plugin marketplace upgrade` with no name.
Codex's own help describes that form as upgrading all the Git marketplaces you have configured,
so installing one of those releases can contact other marketplaces' hosts as well as GitHub.

GitHub therefore sees an ordinary download request, with the IP address and User-Agent
described above, and counts it in the repository's public download total; no wording here
can make installing this tool invisible to GitHub. Downloading the ZIP yourself from the
releases page is the same kind of GitHub download, counted the same way. After that,
`Install.cmd` itself downloads nothing: it installs from the files already on disk, and its
only download-like step is the marketplace refresh described above. The Codex commands it
runs may do whatever any Codex process does at start-up, and the watcher it starts behaves
as described under [What it runs](#what-it-runs).

On that route nothing in this tool checks the archive for you — `Install.cmd` installs
whatever it was unpacked from — so check the ZIP before you extract it. In PowerShell:

```powershell
(Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
```

Compare the result, ignoring case, with the `.sha256` file published beside the archive,
and with the digest pinned for that version in
[`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json)
on the main branch. The pinned digest reaches you by a different channel — a commit in this
repository, not a release asset. A version is pinned once its archive has been published,
so for the newest release there may briefly be only the `.sha256` to compare with. With the
GitHub CLI you can also check which workflow built the archive, for releases from v0.5.4 on
(this asks GitHub for the archive's attestation, and fetches Sigstore's public signing
roots):

```powershell
gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip --repo songyb111-gachon/codex-auto-resume-windows
```

An attestation says which workflow run built the archive. Every archive published so far,
v0.5.0 through v0.5.7, was built by the earlier single-job release workflow, which referred to
its GitHub Actions by floating tags rather than pinned commits, and the executables in those
archives are not reproducible, so you cannot rebuild them byte for byte to compare. The
separate build and publish jobs, the commit-pinned actions and the reproducible executables are
new in v0.6.0. Nothing this project builds is Authenticode-signed — the two executables,
`Install.cmd`, `Uninstall.cmd` and the PowerShell scripts — while the bundled Python
interpreter (`pythonw.exe`, `python.exe` and its DLLs) keeps the Python Software Foundation's
signature.

The watcher itself contacts no GitHub host: the code that reaches the network is the
PowerShell installer, and a test fails if any module under `src/` or `scripts/*.py` imports
a networking module. The update check is that same installer, run by the button rather than
on a schedule, and never by the watcher. A Codex
process, including one this tool starts, may refresh Git marketplaces of its own accord;
that is Codex's behaviour, and once installing has
repointed this product's marketplace, it points at the local copy rather than at GitHub.

## What it reads

It reads Codex's own local state to notice that a task was interrupted and to decide when
resuming is safe. Codex's databases are opened read-only (SQLite `mode=ro` with
`query_only`), and rollout files are opened for reading only:

- lifecycle records — whether a turn failed, when, and where it sits in the conversation;
- the error Codex recorded for the failed turn. The category comes from the structured error
  code Codex recorded and the HTTP status it carries. The error's message text is consulted
  only when Codex recorded no code at all, and then only for a short fixed list of
  connection, timeout and stream-interruption phrases. Either way only a category name is
  kept, and the error itself is dropped at once;
- the exact conversation UUID, turn id and turn ordinal;
- the conversation's row in Codex's thread list and the first line of its rollout file (the
  session header). The header is parsed whole, up to 256 KiB, and only its id and origin
  fields are used, to confirm the conversation is a desktop-app conversation it may act on.
  The header can hold other session details as well, such as the working directory's full
  path; those are parsed and discarded;
- rate-limit and usage snapshots, for the reset timestamp;
- `threads.name`, the project name and the working directory (only its last segment is
  kept), used only as labels in a notification.

It also asks Windows content-free questions, chiefly two: which ChatGPT and Codex processes are
running (process id, parent and executable path), to find the desktop app; and, through the
Restart Manager, which process has the conversation's lock file open, to tell whether the
conversation is open in the app. The rest are content-free too: the path and start time of a
process it found, to confirm it is still the same one; the per-user registry values it
registered itself; and the integrity level of the watcher's single-instance mutex and stop
event, a check that is new in v0.6.0.

No decision rests on the text of your messages, except whether one of them carries this
tool's own marker (below). It never selects the `title`, `preview` or
`first_user_message` columns, which on the current Codex schema contain the raw first
message, and the conversation-name label comes from `threads.name` only. Identity always
comes from the UUID, never from a label.

Three reads pass over your conversation itself, and it is better to say so plainly:

- **For a usage limit only**, to find when the limit resets, it reads up to 8 MiB of the
  conversation's rollout file ending at the failure, into memory. That part of the file is
  your conversation. It keeps only the rate-limit numbers and whether the failure was a
  usage limit, and discards the rest when the scan ends.
- **To prove its own message arrived**, it has SQLite search that conversation's user
  messages and queued messages for its own marker. SQLite reads those rows to answer; only
  rows containing the marker — the tool's own continuation message — come back.
- **To read what its own message led to**, it asks SQLite how many items of each kind the one
  turn that message started holds, whether any user message in that turn is not its own, and
  whether a later turn has finished. Those rows are your conversation — the assistant's replies
  in that turn, and anyone else's messages in it — but only counts and yes/no answers come back,
  never text. What is kept is that turn's status and whether anything was produced in it.

No conversation content from any of them is stored, logged or sent. What is kept is the reset
time (which is also logged) and the limit's bucket name, and the id of the tool's own queued
message.

It does not itself open a Codex database, rollout or configuration file for writing. SQLite's
read-only access does take shared locks and, for a WAL-mode database, opens the
shared-memory index (the `-shm` file) for writing to update it. It does not take the app's
thread writer lock, and does not itself read credential storage: the Codex processes it
starts use Codex's own stored sign-in, and this tool never sees it.

When Codex's state has to change, it asks Codex to make the change through Codex's own
interfaces:

- `codex queue` adds its one continuation message to one exact conversation;
- the App Server's `thread/queue/delete` withdraws that same message, when it has to;
- at install and uninstall, `codex plugin marketplace add` registers the installation
  directory as the `codex-auto-resume-windows` marketplace and `remove` removes it by name,
  and `codex plugin add` and `remove` act on this plugin. In v0.4.0 through v0.5.7,
  `codex plugin marketplace upgrade` acts on every Git marketplace you have configured;
  acting on that marketplace alone, by name, is new in v0.6.0 (see [Installing it](#installing-it)). Installing repoints the
  `codex-auto-resume-windows` marketplace at this installation, replacing whatever source
  that name had; uninstalling removes it only while it still points at this installation.

Codex makes those changes itself. The Codex processes it starts may also update Codex's own
logs and caches as a side effect, as any Codex process does.

## What it runs

Every process it starts for recovery runs on your machine, against the Codex installation
already there:

- the official `codex` binary — `codex queue` to continue the conversation, and
  `codex app-server --stdio` to read your usage and to remove a queued item it put there
  itself. The only requests it sends the App Server are `initialize`,
  `account/rateLimits/read` and `thread/queue/delete`, plus the `initialized` notification
  that completes the handshake; it refuses every request the server sends back;
- short `codex --version` and `codex queue --help` probes, to confirm it is driving the
  interface it expects;
- Windows PowerShell, by its full path under `System32` and with fixed scripts, to list the
  running ChatGPT and Codex processes and to raise a notification. The Restart Manager is
  called directly, not through PowerShell. Setting up the Start Menu shortcut runs a fixed
  PowerShell script too.

Values such as a notification's label or a shortcut's path reach those scripts as
environment variables rather than as script text, so PowerShell does not parse them as code.
From v0.4.0 through v0.5.6 the names a notification shows were written into the script, and
a conversation, project or folder name containing a curly quote could run as a command
(before v0.4.0, notifications held only fixed text, a time and a short id). In v0.5.0
through v0.5.6 the Start Menu shortcut's paths were written into its script the same way;
those come from where the tool is installed rather than from a conversation. v0.5.7 fixed
both. No Python code here uses `shell=True`, `os.system`, `eval` or `exec`, and every
Python subprocess gets an argument list. Installing, uninstalling and the plugin's setup are PowerShell
scripts as well (`install\install.ps1`, `scripts\bootstrap.ps1`), and the installer runs
the `codex plugin` commands listed above.

The resumed turn is not run by any of those processes. `codex queue` places the message in
Codex's queue and exits; your Codex desktop app picks it up and runs the turn, signed in as you
and under your own settings, exactly as if you had typed the message yourself, and sends it to
OpenAI as it does every turn. The one thing this tool asks the Codex processes it starts to
fetch from OpenAI is your usage (`account/rateLimits/read`). Codex identifies these requests as
coming from this tool (client name `codex_auto_resume` and a version number), so OpenAI can see
that you use it and when it checks. Every App Server session it opens, including one that only
withdraws its own queued message, introduces itself to Codex that way. In v0.5.7 and earlier
releases the version it gives is a fixed `0.1`; giving the product's real version is new in
v0.6.0. It asks for usage only when a recovery is due and the conversation is open in the app,
and reuses the answer for 30 seconds. What a Codex process does on its own account when it
starts — keeping its sign-in current, for instance — is Codex's behaviour, not something this
tool requests, and it has not been measured.

Every `codex` process the recovery runtime starts runs with `OTEL_SDK_DISABLED=true` set in
its environment. The `codex app-server` and `codex queue` processes also get flags that turn
analytics off (`analytics.enabled=false`), set the OpenTelemetry exporters
(`otel.exporter`, `otel.trace_exporter`, `otel.metrics_exporter`) to none, turn prompt
logging off (`otel.log_user_prompt=false`) and pin the ChatGPT base URL to the official one.
Those settings apply only to the processes this tool starts. They do not change the desktop
app: the resumed turn runs in the app under your own Codex settings.

## When you use it from Codex

The plugin gives Codex tools — `get_status`, `list_pending`, `get_recovery_timeline`,
`get_recovery_statistics`, `open_settings`, and the controls (`retry_now`, `cancel_recovery`,
`reset_recovery_budget`, `pause_auto_recovery` and `resume_auto_recovery`,
`disable_conversation_recovery` and `enable_conversation_recovery`, `clear_recovery_history`,
`start_watcher`, `update_settings`, `restore_default_settings`) — and a skill that runs the
tool's commands (for example `status`, `pending`, `doctor` and `logs`). When they run inside a
Codex conversation, what they return becomes part of that conversation. The
one-line summary always does, and the structured data may as well; Codex sends the
conversation to OpenAI like any tool output. That is:

- from `get_status`: the version, whether recovery is on, whether the watcher is running and
  whether sign-in autostart is registered, counts by state, and your settings — which
  include the Codex executable path if you set one. It no longer returns the installation
  directory's path, which normally includes your Windows user name; v0.5.0 through v0.5.7
  did, and a conversation held with one of them still carries it;
- from `list_pending`: the pending recoveries, with their conversation ids, interruption ids,
  states, categories, times and attempt counts, and the finished ones too when it is asked for
  them; `open_settings` returns those together with the status and settings above;
- from `get_recovery_timeline`: one recovery's whole chain as event codes, reasons, actor, turn
  references, counters and times, with the interruption ids of that chain and not the
  conversation's — codes and times only, no prompt, reply or error text;
- from `get_recovery_statistics`: over the last few days or all of it, how many interruptions
  were detected and how many continuations were sent, how they ended, the medians and a count by
  kind — numbers only;
- from the commands: the same, plus each pending recovery's reset time, limit bucket and
  last reason code, the desktop app's process ids, and local paths such as the Codex executable, the Codex home,
  the state file and the log file — which normally include your Windows user name — and,
  from `logs`, recent log lines.

None of it is prompt text, assistant output or tool content. The window opened from the Start
Menu reads the same information on your machine and sends it nowhere.

## What it stores, and where

Its own records live in its installation directory, `%USERPROFILE%\.codex-auto-resume\` by
default (or wherever `CODEX_AUTO_RESUME_PLUGIN_HOME`, or failing that
`CODEX_AUTO_RESUME_HOME`, points):

- `config/state.sqlite` — pending recoveries: conversation UUID, the interruption's id, the
  failed turn's id and ordinal, timestamps, failure category, for a usage limit the limit's
  bucket name and reset time and whether that reading was uncertain, attempt counts, state,
  flags and the last reason code, and the two ids it needs to prove delivery (its marker and
  the queued item's id); also the on/off switch for recovery, with when it was switched on
  and the poll interval, and the switch for each conversation. Beside those it holds a bounded
  journal of what happened to each recovery - codes, ids, actor, turn references, counters and
  times, at most 5,000 entries and 90 days, with no prompt, reply or error text - and one row
  for the watcher itself: its process id, session id, start and last-tick times, and which code
  version wrote them. None of it is content;
- `config/state.vN-backup-<timestamp>.sqlite` — a copy of the state file, taken before the first
  watcher of a new version upgrades the schema and before `downgrade-state` rewrites it. It holds
  what `state.sqlite` held, and it is kept to explain a bad upgrade rather than as a way back.
  Deleting `state.sqlite` does not remove it: `Uninstall.cmd` with `-Purge` takes it with the
  rest of `config/`, and without `-Purge` it stays, as the state file does; the command line's
  `uninstall` deletes `state.sqlite` unless you pass `--keep-state`, and leaves this copy either way;
- `config/settings.json` — your settings;
- `logs/` — `auto-resume.log`, what the watcher did, by reason code and conversation UUID;
  `errors.log`, the Python traceback when something goes wrong; and `launcher.log`, a line
  per launch (and why, if one failed).

Engine events are written from a fixed message table. The main log also records the state
directory's path, which normally includes your Windows user name, and — for a Codex version
this tool was not verified against — the version string `codex --version` printed. Prompt
text, assistant output, tool output and Codex's error text are not deliberately written to
any log. When something fails, `errors.log` receives the full Python traceback, and
`launcher.log` and `errors.log` receive the exception's message; this tool does not control
what text an exception carries.

Beside those it keeps the program itself (`app\` and `runtime\`), the window, the
icon notifications use, the sign-in launcher, and `runtime.json`, which records where the
plugin is installed.

One more file appears while an installation replaces one that is already there:
`.codex-auto-resume-install-journal.json`, at the installation root. A first install writes
none, because it has nothing to move aside. The installer writes it before it moves anything,
and it holds the time it was written, the installation directory, and one entry per program
folder being replaced - `app\` or `runtime\`, the path it lives at, and the `*.old-*` name it
was moved aside as. Nothing in it is about your conversations: it is a handful of directory
names, times and a format number. Those paths sit inside the installation directory, which
normally includes your Windows user name. It is deleted as soon as both folders are in place,
so a run that finished leaves none behind. Finding one means an installation did not finish -
it lost power part way, or it failed and put the old copy back - and the next run reads it to
restore anything still moved aside instead of sweeping it up. Uninstalling removes it with
the rest.

One more file exists only if you ask for it, and only where you put it. **Export
diagnostics...** in the window, or `auto_resume.py diagnostics` on the command line (`--out`
names the file; without it, a new one in the current directory), writes one JSON file: your
settings, one entry per recovery with its state,
reason and the checks it is waiting on, up to 2,000 journal entries, and the last 300 lines
of each log. Conversation and interruption ids are replaced by aliases that mean nothing
outside that one file; paths, your Windows user name and e-mail-shaped text are removed.
`errors.log` can carry exception text this tool did not write, which is redacted the same way
rather than filtered - so read the file before you send it to anyone. Nothing is sent by this
tool, and a file that already exists is never overwritten.

Two traces of your conversations live outside that directory, and neither is written by
this tool directly.
Windows keeps the notifications it showed in its notification history for a while, or until
you clear them.
And each resumed conversation contains the continuation message, with its
`[codex-auto-resume:…]` marker, in Codex's own history, like any message.

Outside that directory it also registers ordinary per-user Windows plumbing, none of it
needing administrator rights and none of it containing anything about your conversations: a
Start Menu shortcut carrying the tool's notification identity, which Windows requires before
it will draw a toast at all; the registry entry that gives that identity its name and icon;
the sign-in autostart value (unless you skip it); and the handler for the notification
button's `codex-auto-resume:` link. Through the `codex plugin` commands it registers this
plugin and its local marketplace in your Codex configuration, and Codex keeps its own copy
of the plugin. Uninstalling removes those Windows entries that belong to this installation,
and asks Codex to remove the plugin and the marketplace only while they still point at this
installation; Codex then removes its own copy.

Uninstalling keeps the state directory by default so a reinstall does not lose pending
recoveries; `Uninstall.cmd -Purge` removes it. You can delete it yourself at any time.

## Notifications

Windows notifications are raised locally through the operating system's own notification
API. They show up to two labels — drawn from the conversation's name as Codex stores it, the
project name and the folder name — each on one line and at most 72 characters, plus the
conversation UUID. A usage-limit notice also shows the local reset time. They carry no error
text or account data, and this tool does not route them through any service. If Codex
derived the name from your first message, the label reflects it, as Codex's own list does.

## Third parties

**GitHub**, for the release download when you install or update from the plugin, or when
you download the ZIP yourself, and for the marketplace refresh described under
[Installing it](#installing-it) when a marketplace it refreshes points at GitHub. It is
subject to GitHub's own privacy practices, as any download would be.

**OpenAI**, only through the official Codex app and CLI already signed in on your machine:
the usage check, which Codex identifies as coming from this tool; the resumed turn; and
whatever the plugin's tools and commands return inside a Codex conversation. This tool has
no connection to OpenAI of its own; that traffic is Codex's, under your own account. If you
have configured Codex to use a different model provider, the conversation goes there
instead, as all your Codex conversations do.

**Other marketplace hosts**, through Codex's marketplace refresh at install: a surviving
registration named `codex-auto-resume-windows` is refreshed from wherever it points, and the
installers of v0.4.0 through v0.5.7 refresh every Git marketplace you have configured, from
wherever each one points. Refreshing only this product's marketplace, by name, is new in
v0.6.0.

Beyond these, and a host that a GitHub redirect might send the download request to (see
[Installing it](#installing-it)), this tool sends nothing to any other party; Windows may
make certificate checks of its own during the download. What runs is
the Python standard library, the interpreter that ships in the release archive, two small
Windows programs built from this repository — the settings window and the MCP launcher —
Windows PowerShell, the .NET C# compiler Windows PowerShell uses to build the shortcut
helper when it creates the Start Menu shortcut, `cmd.exe` (with `chcp.com`, which sets the
console to UTF-8) for `Install.cmd` and `Uninstall.cmd`, and the Codex installation already
on your machine.

## Questions

Open an issue, or see [SECURITY.md](SECURITY.md) for the security reporting process.

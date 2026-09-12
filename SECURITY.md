# Security

This document describes what the tool is allowed to touch, how that is enforced, how releases are
built and can be checked, how it was reviewed, and what was actually found and fixed.

The latest published release is v0.5.7. Several properties below exist only on the `main` branch
and ship in the release after v0.5.7. Each of them says so, and, where it matters, says what v0.5.7
does instead.

## Reporting

If you find a security issue, please open an issue on this repository.

This project operates no service of its own - no server, no endpoint, no telemetry - so there is no
vendor backend to notify. The only service the code this project ships contacts is GitHub
(github.com, and the GitHub storage hosts it redirects release downloads to), when setup downloads
a release. The Codex processes it starts talk to OpenAI with your existing sign-in, as Codex does
(see *No network code in the recovery runtime* below). A finding in GitHub or in Codex itself
belongs to that vendor's own reporting process, not here.

## What it touches

**Reads**, read-only for everything that is not its own:

- Codex's SQLite state (thread metadata, turn history, the queue), opened with `mode=ro`,
  `PRAGMA query_only=ON` and `PRAGMA trusted_schema=OFF`. SQLite takes its normal shared read
  locks while it reads.
- The conversation's rollout JSONL file, opened read-only: its first line, to confirm it is a
  desktop-app conversation, and, for a usage limit only, up to 8 MiB just before the failure,
  parsed in memory to find the reset time. That part of the file is conversation content.
  Only the reset time and the name of the limit it belongs to, taken from the rate-limit snapshot,
  are kept. Everything else is discarded, and nothing else from it is stored, logged or sent.
- To prove its own message arrived, it has SQLite search that conversation's user messages and
  queued messages for this tool's marker. Only rows containing the marker come back.
- The recorded error of a failed turn. Its structured error type decides the category; only when a
  failure carries no structured error at all is its message matched against a short fixed list of
  transport failures. Either way, only the category name is kept.
- Its own state and settings.
- Windows process and Restart Manager information needed to identify the desktop app and its engine.

No prompt, assistant or tool content is kept in its state or written to its main log, apart from
the conversation title Codex shows, which may be derived from your first message: notifications
display it, and Windows keeps them in its notification history.

**Writes** while running:

- Files in its own `config/` and `logs/` directories, including the copy of the state file it
  takes before the first watcher of a new version upgrades the schema, and before
  `downgrade-state` rewrites it (`state.vN-backup-*.sqlite`), kept for forensics.
- One continuation message to one exact thread, through the official `codex queue` CLI.
- When that message has to be withdrawn, `thread/queue/delete` requests to the official Codex App
  Server for that exact queued item, repeated if the withdrawal cannot be confirmed.
- The notifications it raises, which Windows keeps in its notification history.
- When you switch **Run at Windows sign-in** on or off in the window, its single `Run`
  value is written or removed.
- Only when you ask for it, one diagnostics JSON file at a path you choose, from **Export
  diagnostics...** in the window or `auto_resume.py diagnostics`. It holds versions, settings,
  every record's state, reason and the checks it is waiting on, the content-free journal (up to
  2,000 entries) and the last 300 lines of each log; conversation and interruption ids become
  aliases valid only inside that one file, and file-system paths, the Windows user name and
  anything shaped like an e-mail address are replaced. It refuses to overwrite an existing file,
  and nothing sends it. `errors.log` carries exception text this product did not write: that is
  redacted the same way rather than filtered, and the file says so at the top.

The Codex processes it starts (`codex app-server`, `codex queue`) may also update Codex's own logs
and caches, as any Codex process does.

**Writes** at install time, for the current user only and never system-wide: a Start Menu shortcut,
the sign-in autostart value unless you decline it, the notification sender identity Windows requires
before it will draw a toast at all, and the handler for the notification button's own URL scheme.
Through the `codex plugin` CLI it also registers a local plugin marketplace and this plugin in your
Codex configuration, and asks Codex to refresh marketplaces. v0.5.7 and earlier releases run that
refresh with no name, so Codex refreshes every Git marketplace you have configured. On the `main`
branch, which ships in the release after v0.5.7, it names this product's own marketplace and
refreshes only that one. Uninstalling removes all of these, under the ownership checks
described below.

**Never reads**: `auth.json`, tokens, cookies, authorization headers, or process memory. The Codex
processes it starts use Codex's own stored sign-in; this tool never sees it.

**Never opens for writing**: a Codex database, rollout or configuration file. If a Codex database
uses SQLite's write-ahead log, SQLite may still update the shared-memory index file (`-shm`) beside
it while reading. Codex's state changes when the product asks official Codex interfaces to act:
`codex queue` (add one message), `thread/queue/delete` (withdraw that same message), and
`codex plugin` / `codex plugin marketplace` at install and uninstall (register, refresh or remove
this product's plugin and marketplace).

## Enforced properties

- **No network code in the recovery runtime.** No file under `src/` or `scripts/*.py` imports a
  networking module, and a test fails if one gains an import of a networking module, so the
  watcher opens no connection of its own. That is a property of the code, checked by that test,
  not a sandbox. The traffic we know the product causes comes from elsewhere:
  - The Codex processes it starts ask OpenAI for your current usage (`account/rateLimits/read`)
    while a recovery is due. Codex identifies this tool to OpenAI by the client name and version
    the tool gives it: `codex_auto_resume` and `0.1` in v0.5.7; on the `main` branch, which ships
    in the release after v0.5.7, `codex_auto_resume` and the product's real version from the
    plugin manifest. These processes may also make Codex's own background requests (for example
    refreshing your sign-in), as any Codex process does. The resumed turn itself runs in your Codex
    desktop app, under your own Codex settings, and goes to OpenAI like any turn you start.
  - Setup: `scripts/bootstrap.ps1` downloads the release from GitHub over HTTPS and verifies it
    before anything in it runs. The installer then asks Codex to refresh marketplaces. In v0.5.7
    and earlier releases it names none, so Codex refreshes every Git marketplace you have
    configured, fetching from their hosts. On the `main` branch, which ships in the release after
    v0.5.7, it names this product's own marketplace; for the local marketplace it registers that is
    a no-op, and Codex fetches only if an earlier GitHub registration of that name is still in
    place.
  - When you use this plugin's tools, or ask Codex to run its commands, inside a conversation, what
    they return (status, pending recoveries with their conversation ids, and for the commands,
    local paths that include your Windows user name) becomes part of that conversation, which Codex
    sends to OpenAI like any tool output. `get_status` also carries the engine path (`codex_exe`)
    if you have set one, and in v0.5.7 the install path, which contains your Windows user name; on
    the `main` branch, which ships in the release after v0.5.7, it no longer includes the install
    path.

  There is no telemetry and no update check. This tool sends nothing to its developer; there is no
  service of the developer's to send it to.
- **No shell, and no values in script text.** No Python code uses `shell=True`, `os.system`, `eval`
  or `exec`, and every Python subprocess gets an argument list. Windows PowerShell runs the
  installer, the uninstaller and the plugin's setup script; the Python runtime uses it to list
  ChatGPT and Codex processes (a fixed script) and raise notifications, and at setup to create the
  Start Menu shortcut. The last two receive their values - toast text, shortcut paths - as
  environment variables read by a constant script (`src/codex_auto_resume/pwsh.py`). PowerShell
  does not parse an environment variable's value as code, so no character in a conversation title
  or a folder name can change what runs. The Python runtime starts PowerShell by its full path under
  `%SystemRoot%\System32`, and `Install.cmd` and `Uninstall.cmd` call both `chcp` and PowerShell the
  same way, so a program of the same name sitting beside them is not run instead. The two small
  Windows programs start the bundled Python with a command line quoted by the `CommandLineToArgvW`
  rules.
- **Its own code, found by path.** This is on the `main` branch and ships in the release after
  v0.5.7. The skill tells Codex (an instruction, not a check) to run the setup script by its
  absolute path inside the plugin, not as a relative `scripts/bootstrap.ps1`, which would resolve
  against the user's project and could run a script of the same name from it. The sign-in launcher
  starts the installed application; its fallback, for installations older than the application
  directory, searches Codex's plugin cache only under this product's own marketplace
  (`codex-auto-resume-windows`), and the only other copy it will start is the one recorded when
  setup ran. If neither qualifies, the launcher logs that no engine was found and starts nothing.
  In v0.5.7 the skill gives the relative path, and the fallback accepts a same-named plugin from
  any marketplace in the cache.
- **Exact thread only.** Thread ids must be canonical UUIDs. `--last` is never used.
- **No secrets in logs or state.** Engine events are logged from a fixed message table, with
  untrusted values masked unless they are hex or digits. Prompt text, error text and account
  identifiers are discarded at parse time. From the usage response, only numeric usage windows,
  reset times and the limit bucket's name are kept; from an error, only its category.
  A few lines outside the table record local facts: the main log records the state directory's
  path, which contains your Windows user name, and, for an engine this tool was not verified
  against, that engine's version string. Tracebacks go only to a separate error log (`errors.log`),
  and the main log records the exception class name only.
- **Fail closed.** Unknown loaded state, unknown usage, an unavailable probe, or a corrupted state file
  results in waiting or refusing, never in sending.
- **No duplicate resume.** The interruption is durably reserved (SQLite, `synchronous=FULL`,
  `BEGIN IMMEDIATE`) before any external process can accept a message. If the result of a send is
  ambiguous, the record enters `submission_unknown` and is never resent. The watcher keeps checking
  it for 24 hours, and if the message turns out to have arrived it is matched to the exact turn
  it started and follows that turn to its outcome. (`resumed`, the name v0.5 wrote on delivery,
  is kept so old rows stay valid and is never written now.)
- **Path confinement.** Owned directories are rejected if they are links, or if they resolve outside the
  configured home. The resolve-based check also catches NTFS junctions, which `is_symlink()` does not.
- **No contention with the app's thread lock.** There is no byte-lock API anywhere in the adapter.
  Loaded state is determined purely from the Restart Manager inventory, so the tool never takes
  the app's own thread writer lock. Reading Codex's databases uses SQLite's normal shared read locks.
- **Least privilege.** No administrator rights are required. Optional autostart writes a single value
  under the current user's `Run` key. No service, no scheduled task, nothing system-wide.
- **Named objects planted by a less-trusted process are refused.** This is on the `main` branch and
  ships in the release after v0.5.7. The watcher's single-instance mutex and its stop event have
  predictable names in the session namespace, where a process running at Low integrity may create
  objects. If either already exists with an integrity label below Medium (the level an ordinary
  user's programs run at), the watcher refuses it and logs `named_object_squatted`. A planted
  mutex makes the watcher refuse to run and status read unknown; uninstall treats that unknown as
  it treats any other, and aborts before removing anything. A planted stop event makes the watcher
  refuse to start, so status reads not running. This covers an object a lower-integrity process
  creates first. It does not cover a lower-integrity process that opens the running watcher's
  mutex and takes it when the watcher exits: that mutex carries the watcher's own Medium label, so
  it is not refused, and status reports a running watcher when none is, as in v0.5.7. In v0.5.7 a
  planted mutex makes status report a watcher running when none is, and a planted, signalled stop
  event makes a real watcher quit on start, logging only an ordinary stop request - nothing that
  points to the planted event.
- **Tools that turn recovery back up are marked so Codex asks first.** This is on the `main` branch
  and ships in the release after v0.5.7. The plugin's MCP tools that can turn recovery back on or
  up, or change its settings - `resume_auto_recovery`, `enable_conversation_recovery`,
  `reset_recovery_budget`, `start_watcher`, `update_settings`, `restore_default_settings` - are
  annotated `destructiveHint: true`, and so are `cancel_recovery` and `clear_recovery_history`, so
  Codex asks the user before running them in its default approval mode. `pause_auto_recovery`,
  `disable_conversation_recovery` and `retry_now` are not: pausing and switching one conversation
  off never add automation, and `retry_now` only moves an already-registered attempt earlier, with
  every check still applied. The two switches do not cost the same, though. Pausing withdraws a
  continuation already waiting in Codex's queue, and a withdrawal the watcher can confirm puts that
  recovery back in its waiting state with its attempt returned, so resuming picks it up again; only
  a withdrawal that cannot be confirmed becomes `submission_unknown`, and only a pause over a
  submission that was already uncertain ends as `failed`. Switching one conversation off cancels
  every recovery it has waiting, and a cancelled recovery is final: switching that conversation
  back on does not revive it, and giving attempts back refuses it. The prompt is Codex's to show:
  this product can only mark its tools, and Codex's approval settings decide whether a prompt
  appears. `update_settings` offers and accepts only the settings a person can change in the
  window, not the engine path (`codex_exe`) or the detection look-back, and `get_status` does not
  include the install path. In v0.5.7 only `restore_default_settings` and `cancel_recovery` are
  marked; `set_auto_recovery`, `reset_recovery_budget`, `start_watcher` and `update_settings`,
  which there also offers the engine path, run without a prompt in Codex's default approval mode,
  and a pause-withdrawn recovery there is cancelled outright.

## Destructive-operation safety

**Nothing is destroyed that this installation cannot prove it owns, with two exceptions at install
time.** The rule covers files, directories, processes and registrations, when installing and when
uninstalling, because "it has the right name" was never evidence for any of them. The two exceptions
are things installing replaces by name, both described under *Installing*: this product's own
per-user registrations, which exist once per user, and the Codex marketplace name it registers
under.

- **Installing.** The install path destroys things too: it sweeps set-aside copies, moves `app/`
  and `runtime/` out of the way, and deletes what it moved. On the `main` branch, which ships in
  the release after v0.5.7, it writes a small JSON journal at the installation root before the
  first move, naming every tree it is about to move and the `*.old-*` name it will use - written
  to a temporary name and moved over the real one, so a crash during the write leaves either the
  previous journal or none. The next run reads it before it sweeps anything: it puts back a tree
  whose target is missing, and checks both ends of every move against the installation it has
  already proved is its own. The two files that belong at the installation root are copied there
  by name rather than by wildcard, so nothing else a payload happens to carry reaches the home -
  including a file named like this product's own provenance marker. It cannot ask the question the
  uninstaller asks, because the first install happens into a directory that is not ours yet. So it
  asks the other half: is anything of ours here? A directory already holding `app`, `runtime`,
  `config`, `logs` or a set-aside copy, with no proof any of it is ours, is refused and nothing in
  it is touched. A directory holding none of them has nothing to destroy, and is marked as ours
  *before* the first file is written - never afterwards, because a marker written after the fact
  would authorise the deletions backwards. Two things are replaced by name. The notification
  identity, the Start Menu shortcut and the URL handler exist once per user, so installing writes
  this installation's values over whatever is registered under those names - in practice, another
  copy of this product that did not register for sign-in. The sign-in value is not replaced: if it
  belongs to another installation, setup stops before writing any of the per-user entries above
  and says so. By then the installer has already copied the files and registered the Codex
  plugin and marketplace, including the repointing described next. And if
  the marketplace name `codex-auto-resume-windows` is already registered from a different source,
  installing removes that registration and registers the name again, pointing at this
  installation, without checking what the old source was.
- **Upgrading.** Before replacing its files, an upgrade asks a running watcher to stop through its
  stop event - the same request `stop` and uninstall make - and waits up to a minute. It never
  kills the watcher: one stopped mid-submission would leave that recovery unable to prove whether it
  was sent. If the watcher is still running after the wait, the upgrade completes and says that the
  previous version is still running and how to replace it. The only processes an install stops by
  force are this plugin's own MCP launchers, identified by path as on uninstall, when they hold the
  plugin's files open and Codex cannot update the plugin; Codex starts a fresh one when it needs it.
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
  If Codex refuses a removal, that is reported as a refusal, never as a removal.
- **Uninstalling: registry and Start Menu.** The sign-in entry, the notification identity, the Start Menu
  shortcut and the `codex-auto-resume:` handler are per-user singletons that a second installation
  would overwrite, so each is removed only when it still belongs to the installation being
  removed.

Uninstall first asks a running watcher to stop through its stop event. If a watcher is still
running, or if it cannot verify whether one is running, uninstall aborts before removing anything
at all — registrations included. The proof of ownership is deleted after the last step that can
still stop the run, so an interrupted uninstall can be run again. Uninstall never deletes ChatGPT or
Codex files itself: it asks the `codex` CLI to unregister this plugin and its marketplace, only
while they still point at this installation, and Codex removes its own cached copy of the plugin.
User repositories and parent directories are never deleted.

## Release integrity

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) from the
tagged commit, not from a developer's working tree.

Every archive published so far, v0.5.0 through v0.5.7, was built by the earlier single-job
workflow, which referenced its actions by floating tags and produced executables that were not
reproducible. The two-job split, the pinned actions, the reproducible executables and the version
resource described below are on the `main` branch and apply from the release after v0.5.7.

- **Two jobs, split by privilege.** On the `main` branch; applies from the release after v0.5.7.
  `build` runs the repository's code - the tests and the build scripts - with a read-only token
  that is not left on disk. `publish` holds the rights to create the release and attest it, runs
  no script from the repository - only the steps written in the workflow itself (it does not check
  the repository out) - and runs only on a tag push. A manual run builds and verifies whatever ref it names and never reaches `publish`.
- **Pinned actions.** On the `main` branch; applies from the release after v0.5.7. Every GitHub
  Action the workflows use is pinned to a full commit SHA, with the release it corresponds to in a
  comment, and a test enforces it. Dependabot proposes updates as pull requests for a person to
  review; nothing in the repository merges them automatically.
- **A published version is not replaced by the workflow.** On the `main` branch, which ships in the
  release after v0.5.7, `publish` refuses a version that already has assets, so a correction needs
  a new version; the earlier single-job workflow refused the same way from v0.5.4 on. These are
  not GitHub "immutable releases": that repository setting is not enabled, so the rule is this
  workflow's rather than a platform guarantee, and a person with write access to the repository
  could still change a release's assets by hand. The digest an install is checked against is
  therefore kept as a commit on `main` rather than as a release asset; the next item says what
  that does and does not catch.
- **What an install is checked against.** The plugin's setup script verifies the archive's SHA-256
  against the digest pinned for that version in `scripts/release.json` - the copy that came with
  the plugin from the `main` branch, where the pin is committed after the archive is published. It
  is a commit on `main`, not a release asset. A replaced asset no longer matches it unless the pin
  is changed too, and that change is a new commit on `main`, visible in its history unless that
  history is rewritten; the pin lives in the same
  repository, under the same write access. For a version with no pin yet - between publication
  and the pin commit - the script falls back to the `.sha256` published beside the archive and says
  so; that file shows the download is intact, not where it came from. A file passed with
  `-ArchivePath` is checked only against a pinned digest; if the version has none, its SHA-256 is
  compared with nothing, and the script says so. Every archive from v0.5.4 on also carries a GitHub
  build provenance attestation, which ties it to the workflow run and the commit that built it.
- **Reproducible executables.** On the `main` branch; applies from the release after v0.5.7. The
  in-box C# compiler stamps every build with the time and a random module id (MVID).
  `build/normalize_pe.py` fixes the PE timestamp and derives the MVID from the module's content, so
  the two executables depend only on their source and the compiler build (which the build log
  records), and the release build compiles them twice and refuses to publish if the two builds
  differ. Text files are checked out with CRLF everywhere (`.gitattributes`), because their line
  endings are part of the archive's bytes. Two full builds from fresh clones on one machine, with
  the same compiler, Python and zlib, produced byte-identical archives. Whether GitHub's runner
  produces the same bytes as a local build has not been verified.
- **Version resource.** On the `main` branch; applies from the release after v0.5.7. Both
  executables carry a Windows version resource - product, publisher, file and product version -
  generated from the plugin manifest, so a file's Properties name what it is. That is a label, not
  a signature: it says nothing about who built the file.

## Code signing

Nothing this project builds is Authenticode-signed - the two executables, `Install.cmd`,
`Uninstall.cmd` and the PowerShell scripts. The bundled Python interpreter keeps the signatures it
was published with: the Python Software Foundation's on `pythonw.exe`, `python.exe` and the Python
DLLs, and Microsoft's on the two Visual C++ runtime DLLs.

- What the sign-in entry starts is the bundled `pythonw.exe`, which carries the Python Software
  Foundation's signature.
- The two small executables - the settings window and the MCP launcher - are unsigned, and with
  Smart App Control on, Windows may block them. On the manual route SmartScreen may warn, because a
  ZIP downloaded in a browser and extracted with Explorer passes the mark of the web on to its
  files. A `.cmd` file cannot carry an embedded Authenticode signature.

Without a signature on this project's own files, what establishes that a file is the one this
repository published is the checking described under *Release integrity* and below.

## Verifying a release

If you download the archive yourself, verify it before extracting it. In PowerShell:

```powershell
(Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
```

Compare the result, ignoring case, with the `.sha256` file published beside the archive, and with
the digest pinned for that version in
[`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json)
on the `main` branch. The pin reaches you by a different channel - a commit on `main`, not a
release asset - so it is the comparison that does not rest on the release page alone. It is still
in the same repository; a change to it is a new commit on `main`, visible in its history unless
that history is rewritten. v0.5.0 and v0.5.1 have no pin, and a version published very recently
may not be pinned yet. For v0.5.4 and later, you can also check the build provenance with
the GitHub CLI:

```powershell
gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip --repo songyb111-gachon/codex-auto-resume-windows
```

`Install.cmd` checks nothing about the archive it came in; this step is the check. The plugin route
does the SHA-256 comparison itself, except for a file passed with `-ArchivePath` for a version with
no pin, as described under *Release integrity*.
[`docs/VERIFY.md`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md)
goes through each step, what the plugin route checks for you, and how to rebuild a release and
compare. Archives up to and including v0.5.7 were not built reproducibly, so a rebuild of those tags
is not expected to match them byte for byte.

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

A later review took in the installer, the plugin's skill and MCP tools, the Windows named objects and
the release workflow as well as the runtime, and its findings were checked again by a second,
independent pass. What held up is in the last two lists below. The PowerShell fix is tested by
running the original payload through the real interpreter (`tests/test_pwsh.py`), and the
named-object check, which is on the `main` branch and ships in the release after v0.5.7, was
measured against a real low-integrity process.

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

From the later review, fixed in v0.5.7:

- **A folder or conversation name could run PowerShell.** Toast text and shortcut paths were
  written into the script as single-quoted strings, escaping only the ASCII apostrophe. PowerShell
  also treats U+2018, U+2019, U+201A and U+201B as single quotes, so a name containing one ended the
  string and the rest ran as PowerShell under the user's account, silently. Every release from
  v0.4.0 through v0.5.6 was affected; the next release fixed it. Values now travel as environment
  variables to constant scripts.
- **An upgrade could leave the old watcher running.** Renaming `app/` under a live watcher succeeds,
  so the old code carried on from the renamed copy and a security fix could be installed but not in
  effect. The installer now asks it to stop, as described under *Upgrading*.
- **`Install.cmd` and `Uninstall.cmd` called `chcp` and PowerShell by bare name**, so `cmd.exe`
  would run a program of the same name sitting in the same folder - which, if that folder is
  Downloads, could be any earlier download. Both are now called by full path.

From the later review, fixed on the `main` branch and shipping in the release after v0.5.7 (v0.5.7
still has each of these):

- **The MCP tools let content in a conversation turn recovery back up without asking.**
  `set_auto_recovery` needed no approval in either direction, so a prompt-injected turn could undo
  the user's pause; `reset_recovery_budget` revived exhausted recoveries the same way; and
  `update_settings` offered the engine path. On the `main` branch, see *Tools that turn recovery
  back up are marked so Codex asks first*.
- **The installer refreshed every Git marketplace the user had configured**, because it ran
  `codex plugin marketplace upgrade` with no name - an action on other publishers' plugins, and a
  network fetch from their hosts. On the `main` branch it names its own marketplace.
- **The sign-in launcher's fallback accepted a plugin of the same name from any marketplace** in
  Codex's plugin cache, and, for an installation with no application directory, could have run it
  at sign-in. On the `main` branch it searches only
  this product's own marketplace, besides the copy recorded when setup ran.
- **The skill ran the setup script by a relative path**, which resolves against the user's project.
  On the `main` branch it gives the absolute path inside the plugin.
- **A lower-integrity process could squat the watcher's mutex or stop event.** Creating the mutex
  first made status report a running watcher when none existed and kept the real one from
  starting; creating and signalling the stop event made a real watcher quit on start, logging only
  an ordinary stop request - nothing that points to the planted event. On the `main` branch such
  objects are refused and logged. This covers an object a lower-integrity process creates first. It
  does not cover a lower-integrity process that opens the running watcher's mutex and takes it
  when the watcher exits: that mutex carries the watcher's own Medium label, so it is not refused,
  and status reports a running watcher, as in v0.5.7.
- **The release workflow's dry run was not one.** A manual run against a tag could publish, and a
  manual run against any ref ran that ref's code holding a write token left in `.git/config`. On
  the `main` branch the workflow is split into the two jobs described under *Release integrity*.
- **An interrupted install was destroyed by the run that came next.** The old `app\` and
  `runtime\` are moved aside before the new ones are copied in, and the first thing the next run
  does is delete every `*.old-*` directory it finds - so a power cut between the two left the only
  complete copy under exactly that name, and the recovery attempt was what destroyed the
  installation. On the `main` branch a journal written before the first move tells the next run
  what to put back, as described under *Installing*.
- **Whatever sat at the payload root was copied into the installation home.** It was a wildcard
  copy, so a stray file in a release landed in the home under whatever name it carried, including
  the two this product reads as proof that the home is its own (`.owned-by-codex-auto-resume`,
  `runtime.json`). On the `main` branch the two files that belong there are copied by name, and a
  payload missing either fails the install before anything is moved.
- **An upgrade switched automatic recovery back on, and put back a sign-in start that had been
  removed.** Plain `setup` runs the engine's `enable`, so upgrading over an installation whose
  owner had paused recovery turned it back on silently, under the name of an update. On the `main`
  branch the installer, and Repair in the window, run setup with `--keep-state` whenever the
  program directory is already there: the pause is left alone, and the sign-in entry is
  re-registered only where the one registered is already this installation's.

## Residual risks

- The blocking usage bucket cannot always be identified from history with certainty, so live availability
  is re-checked immediately before sending. This reduces but does not eliminate the uncertainty.
- The tool no longer requires an exact engine version. An unrecognised build is accepted when the
  `codex queue` interface probe passes, which means a Codex update can change *semantics* without the
  probe noticing. This is mitigated rather than eliminated: every send is still proven afterwards by
  the per-interruption marker in that exact thread, an unproven send is never recorded as a
  recovery, and `status`/`doctor`/the log state clearly when the engine is unverified.
- Unloaded threads are not resumed at all; this is a documented product limitation, not a security control.
- If withdrawing its own queued message cannot be confirmed, the record becomes `submission_unknown`
  and the message may stay in Codex's queue, where it may be delivered if the conversation is
  opened later. The tool never sends it again.
- A lower-integrity process that holds the watcher's mutex or stop event name keeps recovery from
  running while it holds it, in v0.5.7 and on the `main` branch alike. On the `main` branch, which
  ships in the release after v0.5.7, a planted mutex makes status read unknown and a planted stop
  event makes the watcher refuse to start, so status reads not running; both are logged as
  `named_object_squatted`. This covers an object a lower-integrity process creates first. It does
  not cover a lower-integrity process that opens the running watcher's mutex and takes it when the
  watcher exits: that mutex carries the watcher's own Medium label, so it is not refused, and
  status reports a running watcher, as in v0.5.7. In v0.5.7 a planted mutex makes status report a
  running watcher and the real one exit as a duplicate, and a planted, signalled stop event makes
  a real watcher quit on start, logging only an ordinary stop request - nothing that points to the
  planted event.
- Content in a conversation can pause recovery without a prompt, in v0.5.7 (through
  `set_auto_recovery`) and on the `main` branch (through `pause_auto_recovery`, which ships in the
  release after v0.5.7) alike. Pausing withdraws a continuation already waiting in Codex's queue.
  On the `main` branch a withdrawal that can be confirmed returns that recovery to waiting with its
  attempt returned, so resuming picks it up; only a withdrawal that cannot be confirmed
  (`submission_unknown`), or a pause over an already uncertain submission (`failed`), is final. In
  v0.5.7 the recovery is cancelled for good and resuming does not bring it back. Either way the
  message is never sent twice.
- On the `main` branch, content in a conversation can also switch recovery off for one
  conversation without a prompt, through `disable_conversation_recovery` - and that one is not
  reversible. It cancels every recovery that conversation has waiting, switching the conversation
  back on does not revive them, and giving attempts back refuses a cancelled recovery. What it
  costs is unfinished work left unresumed, never a message sent twice.
- Whether Codex shows an approval prompt for the tools marked destructive is up to Codex's approval
  settings, not this product.
- Nothing this project builds is Authenticode-signed (the two executables, `Install.cmd`,
  `Uninstall.cmd` and the PowerShell scripts); the bundled Python interpreter keeps the signatures
  it was published with: the Python Software Foundation's on `pythonw.exe`, `python.exe` and the
  Python DLLs, and Microsoft's on the two Visual C++ runtime DLLs. Releases are not
  GitHub-immutable. Trust in a download rests on the pinned digest and the provenance attestation
  (*Release integrity*, *Verifying a release*).
- Every archive published so far, v0.5.0 through v0.5.7, was built by the earlier single-job
  workflow with floating action tags and executables that are not reproducible. Whether a local
  rebuild reproduces, byte for byte, an archive GitHub's runner publishes from the release after
  v0.5.7 on has not been verified.

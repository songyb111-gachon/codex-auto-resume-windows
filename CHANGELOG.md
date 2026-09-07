# Changelog

## v0.5.1 — Say what the product actually is

A patch release. No change to how recovery works, what it will retry, or what it refuses to
retry. What changed is everything around that: the documentation was describing a version of
this project that no longer exists, and the install instructions contradicted the installer.

### Documentation that matches the product

- **Fixed: the one-click install told you to put Python on your PATH.** That archive exists
  precisely so you do not need Python — it carries its own runtime. The recommended install is
  now three steps at the top of the README, with no prerequisites, and Python appears only where
  it is genuinely needed: a source checkout, or installing the plugin straight from the
  marketplace.
- **Fixed: "there is no tray icon, no settings window, no management web UI".** Two of those
  stopped being true in v0.5. The project direction now says what is deliberately built — a
  Windows settings window, a panel inside Codex, the command line, notifications — and what is
  still deliberately refused: a tray controller, a management web UI, a supervisor, a service, a
  second recovery engine, a second database.
- **Fixed: the supported Python version was never the tested one.** Setup refused anything below
  3.10 while CI only ever ran 3.12 and 3.13, so two Python releases were accepted by the
  installer and never tested. The floor is now the lowest version that is actually tested, and a
  test ties the installer, the message the user sees, the skill and the bundled runtime together
  so they cannot drift apart again.
- The README opens with the problem and the download instead of the implementation, and states
  the loaded-conversation limitation in the same breath rather than further down.

### New public documentation

- **[PRIVACY.md](PRIVACY.md)** — what is read, what is stored, and the short answer to what is
  sent anywhere: nothing. No telemetry, no analytics, no update check, no outbound requests.
- **[SUPPORT.md](SUPPORT.md)** — where to report each kind of problem, what to include, and what
  not to paste into a public issue.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to run the tests and build a release, the fixture
  conventions, and the safety properties a change has to keep.
- **[README.ko.md](README.ko.md)** — a Korean README, linked from the English one.

### Repository hygiene

- A new check keeps local development environment out of the repository: home directories in
  examples must be placeholders, UUIDs in tracked files must be recognisably synthetic, and
  runtime state is never tracked. The rules describe what a fixture may look like rather than
  listing values, so the check cannot itself become a place where such values live.
- Test and documentation fixtures use the documented placeholders throughout.

### Packaging

- Plugin metadata describes the product in the words people actually search for, and the
  manifest, the skill and the release now agree on the version.

### Unchanged on purpose

Recovery is exactly as conservative as it was in v0.5.0. Same failure classification, same
bounded attempts, same fail-closed behaviour on anything unrecognised, same exact-conversation
identity, same refusal to resend a submission whose outcome is unknown. Codex still has to have
the conversation open for a recovery to be delivered; that limitation is unchanged and still
documented.

## v0.5.0 — Settings you can find, and a notification that says who it is from

### Settings, in three places, meaning one thing

- **A standalone Windows settings window**, on the Start Menu. It works with Codex closed, the
  plugin unloaded, the MCP server unavailable, no network, no sign-in and no system Python -
  because configuration matters most exactly when the thing it configures is unavailable.
- **A settings panel inside Codex**, over a plugin-declared MCP server. Ask to open auto resume
  settings and it renders in the conversation.
- **The command line**, unchanged.

All three read and write through one validated layer, so a value set in any of them is the value
the others show. That layer is also the fix for a real bug: the watcher used to have its own
settings reader that understood three of the sixteen fields, and a matching writer that persisted
only those three - so `enable --lookback-hours 8` silently erased every recovery category and
notification preference. There is now one reader and one writer.

### The settings finally govern the watcher

The schema described policy that nothing read. Now the engine adopts it: categories switched off
are never recorded, so nothing is scheduled, attempted or announced for them; the transient
backoff follows the chosen timing preset; and the attempt and no-progress budgets come from the
settings. Changes are picked up on the next poll, without restarting anything.

Policy stays policy. Everything a settings file can touch runs through the same coercion, so the
worst a hand-edited or hostile one can do is make recovery *more* conservative - and the engine's
safety limits are not in the schema at all. There is still no setting that retries an unclassified
failure, resolves a conversation by title, resends an uncertain submission or forces a send.

### Notifications that say who they are from, across the whole lifecycle

- **Fixed: Windows attributed our notifications to PowerShell.** They now show **Codex Auto
  Resume** with this project's own icon. That needs two registrations, not one: an
  AppUserModelID supplies the name and icon, and a Start Menu shortcut carrying the same id is
  what makes Windows *draw* the toast. Without the shortcut the platform accepts it, logs it, and
  files it in the notification centre without ever showing it. Found by looking at the screen
  rather than at the event log, which had said "delivered".
- Three more notifications join the first: recovery starting, how it turned out, and recovery
  stopping for good. Each is raised once, from the state change itself, so the notification and
  the record cannot disagree. An uncertain submission is reported as uncertain, never as a
  failure that will be retried.
- Each event has its own switch, plus a master switch, read at the moment of the event.

### Recovery

- **Fixed: an exhausted recovery could not be given its attempts back.** Running out of attempts
  leaves a record in a terminal state, and terminal records may not be reactivated - the guard
  that stops a finished, cancelled or uncertainly-submitted recovery from being restarted by a
  stray write. Resetting the budget therefore raised instead of resetting. Rather than widen that
  guard, the one stop a person may undo now has its own operation: it accepts only the two
  exhausted states, refuses anything cancelled or carrying any sign of a submission, and clears
  the budget and nothing else. The record re-enters the queue as a candidate and every gate runs
  again.
- **Retry now** brings a waiting recovery's next attempt forward. It is not a send: the watcher
  still revalidates, still needs the conversation open, still waits for usage, and still refuses
  anything uncertain.

### The usage-limit checkbox, re-investigated from scratch

Re-checked against `codex-cli 0.153.4` and ChatGPT desktop `26.901.5280.0`. The answer has not
changed: the notice is assembled from compiled message ids inside the Electron bundle, and no
manifest field, MCP surface or hook can address it. A Codex-native form at the moment of the
interruption is now technically possible and is still not shipped, for a stated reason rather
than a technical one - it would push a form into whatever conversation happens to be open, about
a different one that failed, only when Codex is running, and only where a remote feature gate is
on. Nothing was faked in its place. See [docs/PLUGIN.md](docs/PLUGIN.md).

### Three ways an install could quietly stop working

All three were found by using the product on a real machine after a reboot, not by reading
the code. The watcher was not running, and the settings panel was the only thing that said so.

- **Fixed: the autostart command was never quoted.** `subprocess.list2cmdline` quotes only a
  token that contains a space, so an installation under a path without one produced a completely
  unquoted Run value. Under `C:\Users\Example User\...` Windows reads that as the program
  `C:\Users\Example`, and the watcher never starts at sign-in - whether the product works at all
  depended on what the user is called. Every command written to the registry is now quoted by the
  documented CommandLineToArgvW rules, including the notification button's protocol handler and
  the Start Menu entry.
- **Fixed: an upgrade could not replace an installation that was in use.** Codex keeps this
  plugin's MCP server running, which holds the bundled interpreter's DLLs open, and a loaded DLL
  cannot be deleted - so removing the runtime directory failed part-way and left the application
  updated with the interpreter gone. Windows does allow renaming a directory that contains an
  open file, so the old copy is moved aside and swept up later. Everything is moved before
  anything is copied, and a failure at either step puts the installation back exactly as it was.
- **Fixed: Codex could not update the plugin while it was running the plugin.** `plugin add`
  backs up the cache directory and failed with an access error, because the open file is our own
  MCP launcher, which lives inside the plugin - it has to, since Codex accepts only a contained
  command path. The installer now stops just its own launchers and retries once; Codex starts a
  fresh one when it next needs the server.
- The watcher launcher records that it ran before anything can fail, and catches everything on
  the way out. Under `pythonw.exe` there is no stderr, so an early failure left no log line, no
  event and no trace - which is why "did Windows start it and it died, or did Windows never start
  it" could not be answered at all.
- The settings window and the Codex panel offer to **start the watcher** when it is stopped,
  rather than reporting a dead end. It starts the same process the installer starts.

### Packaging

- The plugin now ships a small launcher so its MCP server can start from the bundled interpreter:
  Codex accepts a plugin command only as a bare name or a contained path, and a bare `python`
  would put back the system-Python requirement this product removed.
- That launcher relays the standard streams rather than letting the child inherit them. A child
  started with `CREATE_NO_WINDOW` and no explicit handles gets no usable standard handles, so the
  server waits for input that never arrives and the host waits for a handshake that never comes.

## v0.4.1 — Put the reason back in the notification

- **Fixed: the notification never said why it appeared.** Windows renders at most three
  `<text>` elements in a toast and silently drops a fourth, so the four-line layout lost its
  body line: the toast showed the task name, the project and the thread id, but not
  "Codex usage limit reached" or "Codex was temporarily interrupted".
  It now fits three lines - name, reason, then project and the exact thread id together -
  with the reason ordered before the identifiers, because a line that does not fit is lost
  and losing the reason makes the notification pointless. The thread id is still always shown.
  Found by looking at the actual notification, not the generated markup.

## v0.4.0 — Recover more, guess less, install in one step

### Recovery beyond usage limits

- **Clearly temporary failures are now recovered too**, on a policy of their own. The two
  are deliberately not merged: a usage limit waits for its real reset timestamp, a dropped
  connection waits on a bounded ladder (5s, 15s, 30s, 60s, 120s) and never longer.
- Classification is **structural, not textual**. It reads the `codexErrorInfo` variant Codex
  itself writes, then an HTTP status carried by that variant. A message is consulted only
  when there is no structured code at all, and only for transport failures that have no code
  (timeouts, DNS, TLS, broken pipe). A structured code is never overridden by message text.
- **Recovered:** usage limit, connection failure, timeout (408/425), transient rate limit
  (429), server errors (500-599, `serverOverloaded`, `internalServerError`), stream
  disconnection.
- **Not recovered:** user cancellation, permission, approval, policy, invalid request,
  context length, permanent authentication (401/403/`unauthorized`), `badRequest`,
  `sandboxError`, `responseTooManyFailedAttempts` (Codex already retried and gave up),
  and anything unrecognised.
- **Unknown is never retried.** An error this tool cannot place is never registered at all,
  so no later stage can act on it. This is the opposite of retrying by default, and it is
  the point: a missed recovery is cheaper than a wrong one.
- **Bounded budgets.** A transient chain stops after 4 recovery attempts
  (`retry_budget_exhausted`), and after 3 consecutive recoveries that produced nothing
  (`no_progress_exhausted`). Progress is judged from lifecycle metadata only: whether a
  later turn completed, and whether it recorded a final agent item. No message text is read.
- **The user always wins.** If a later turn exists on that exact thread - because the user
  carried on, or because Codex did - the old interruption becomes `superseded_by_user` and
  is never resumed on top of the newer work.
- Existing state upgrades in place. Pending recoveries survive the update.

### Notifications that say which task

- The notification now leads with a name a person recognises: the conversation title, else
  the project, else the working directory's name, else "Codex task". The **exact thread UUID
  is always shown** on its own line, because titles repeat and identity must not.
- Wording follows the failure: a usage limit says when it will resume; a temporary failure
  says it is retrying. One cancel button either way.
- Display names are read from `threads.name` only. On this schema `title`, `preview` and
  `first_user_message` all hold the raw first prompt (observed at 67 KB, multi-line), so they
  are never read. Labels are capped and must be single-line, so a schema change cannot turn a
  prompt into a notification.
- **Names are for display only.** Recovery still resolves nothing by title, project or
  recency; the exact UUID remains the sole identity.

### One-click installation

- `install/Install.cmd` registers the marketplace, installs or updates the plugin, checks for
  Python, and hands over to the plugin's own setup. It is a bootstrapper, not a runtime: no
  administrator rights, no service, no scheduled task, HKCU only, and it never deletes state.
  Re-running it upgrades in place. `Uninstall.cmd` reverses it, watcher first.
- Python is never downloaded or installed automatically; a missing interpreter is reported
  with a link and the installer stops without leaving anything running.
- Checked first and not available: this Codex build has no plugin install deep-link, and
  `codex plugin add` requires a registered marketplace, so the two commands cannot be reduced
  to one officially.
- Fixed while testing the installer for real: a single-result PowerShell pipeline is a scalar,
  so indexing it took the first character of the engine path; an already-registered marketplace
  kept a stale snapshot, so updates never arrived; the Python version probe's quoting did not
  survive argument passing; and setup compared the registered autostart by exact string, so
  upgrading Python made one installation look like two and setup refused forever.

## v0.3.2 — Make the login autostart actually start

- **Fixed: the registered sign-in autostart could never run.** The Run value ended in `run`, and
  the launcher appended `run` again, so the command died with an argument error at every login.
  It went unnoticed because starting the watcher from setup passes no arguments and worked fine.
  The launcher now treats its arguments as the command to run, defaulting to the watcher.
- **Fixed: the notification button broke on the next plugin update.** It was registered against
  the plugin's own directory, which is named after its version. It now goes through the same
  stable launcher as the autostart, so neither registration can be orphaned by an update.
- Both registrations are now checked by tests that parse the exact command that gets registered
  and feed it to the real argument parser.

## v0.3.1 — Keep the state out of somebody else's sandbox

- **Runtime state moved from `%LOCALAPPDATA%` to `%USERPROFILE%\.codex-auto-resume\`.**
  Setup may be run from a packaged (MSIX) host, and Windows silently redirects such a host's
  AppData writes into its own private `LocalCache`: the environment variable still reads as the
  normal path while the files land inside an unrelated application. Installing this way put the
  state, the logs and the autostart launcher inside another app's sandbox, where uninstalling
  that app would have taken them with it. The user profile root is not redirected, which is why
  Codex keeps its own state in `~/.codex`.
  Found by installing the plugin for real and reading back where the files actually went.

## v0.3.0 — A control at the moment it matters

- **Windows notification when an interruption is detected.** The watcher is running at that
  moment, so this is the one place a control can be offered in time; the Codex turn has already
  failed by then, so nothing can be added to the app's own usage-limit notice.
  The toast says when the conversation will continue and carries a single **Don't resume**
  button. Doing nothing resumes, which is the default.
- The button is handled through a per-user `codex-auto-resume:` URL protocol registered under
  `HKCU\Software\Classes`. It accepts exactly one action — cancelling — so a hostile URI can
  only ever stop a resume, never cause one. The interruption id is validated as opaque hex and
  must match a real record; nothing is resolved by thread name or recency.
- The toast shows only a shortened conversation id and a local time. Never prompt text, error
  text or account data. PowerShell is invoked with `-EncodedCommand`, so no message text can be
  reinterpreted as script.
- Delivery is best effort. A notification that cannot be shown, times out, or raises is logged
  and ignored; it never changes whether a resume happens.
- Turn it off with `"notifications": false` in `config/settings.json`.
- Fixed before release: the toast document was escaped as if it were an XML *attribute*, which
  turned its own angle brackets into entities and made every notification fail silently. The
  document is now embedded as a PowerShell string literal, and a test parses the document out of
  the command that is actually sent.

## v0.2.0 — Install and control it from inside Codex

- **Codex plugin.** The repository root is now also a Codex plugin root, with a marketplace index
  (`.agents/plugins/marketplace.json`), a manifest (`.codex-plugin/plugin.json`) and one skill.
  Install with `codex plugin marketplace add songyb111-gachon/codex-auto-resume-windows` followed by
  `codex plugin add codex-auto-resume@codex-auto-resume-windows`, then ask Codex to set it up.
  There is exactly one copy of `src/`; the engine ships with the plugin rather than being duplicated.
- The plugin is a thin front end over the existing command-line interface. It adds no MCP server, no
  second engine, no recovery logic of its own, and never queues a message to a thread.
- **Runtime state moved out of the plugin directory** for plugin installs, to
  `%USERPROFILE%\.codex-auto-resume\`. Plugin updates and removals no longer risk pending resumes.
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

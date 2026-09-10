# Changelog

## v0.5.5 — Say only what you checked

The last corrective release before v0.6. **Recovery is untouched** again: the same failure
categories, the same refusals, the same identity rules, the same bounded retries, the same
database. What changes is that several things which had been quietly asserting rather than
checking now check - and that the Korean branch stops being a second copy of the product.

### The watcher is reported as running only when it is

- **Fixed: starting the watcher claimed success it had not verified.** `start_watcher`
  returned as soon as Windows created a process, which proves nothing about whether the
  watcher survived its imports, took the single-instance mutex or stayed alive. Four
  surfaces turned that into a statement of fact, and the contradiction showed: the MCP
  tool said "The watcher is running." and the very next status said it was not. It now
  waits for the same probe the status line reads — on a monotonic deadline, in several
  short looks — and reports which of four things actually happened: running, already
  running, started but not confirmed, or started and exited. Only the first two are
  allowed to mention a running watcher, and a test enforces it. Measured here, the
  ordinary case now answers in about a third of a second, where the settings window used
  to sleep a fixed 1.2 s and hope.
- The watcher also now retries a momentarily busy mutex once before concluding another
  watcher owns the machine. Every status read takes that mutex for microseconds to test
  it, and a check must not be able to convince a starting watcher that it lost a race to
  itself. A real second watcher holds it for its whole life, so single-instance safety is
  unchanged.

### Screenshots that cannot go stale quietly

- **Fixed: every screenshot showed v0.5.2**, three releases behind, because there was no
  script that made them — only a sequence somebody had to remember. `build/make_screenshots.py`
  now renders both from the working tree: the settings window from a scratch installation
  assembled out of `src/` and the manifest, and the Codex panel from the panel's own
  source with sample data built by the real control surface. There is no version number
  in the generator and no mock JSON on disk; change `.codex-plugin/plugin.json` and both
  images say the new version.
- The same picture is no longer *captured* twice. There is one canonical asset per
  screenshot and the documentation copy is generated from it — both files are still
  committed, and a test now requires them to be byte-identical, which is the point.
  `assets/screenshots.json` records what they were rendered from, so the suite fails when
  the sources move and the images do not.

### The Retry timing control is drawn in full

- **Fixed: the Retry timing box lost its bottom border at every display scaling above
  100%.** Not a drawing bug: a ComboBox under-reports its height until it is shown, then
  resizes itself to fit the font while keeping the position it was given, so it hung past
  the bottom of its own row — by 2 px at 125% and 9 px at 250% — and a child is clipped to
  its parent. The editor is now anchored to the top, and the row reserves the editor's
  measured height, which also puts the label back on its centre line.

### The Korean branch is generated, not maintained

- **Fixed: `ko` was three releases behind, and wrong in the ways that matter.** It was an
  independent fork carrying its own engine, installer, workflows and tests, kept in step
  by someone remembering to merge. It still told Korean readers the tool made no network
  request, still led installation with "download the release archive", still said there
  was no third party to report a security issue to, and still described an uninstall that
  predated every ownership rule v0.5.4 added. Its README linked to itself for the English
  version.
- There is no second copy now. `ko` is main's tree at a commit whose tests passed, with
  each Korean document put in place of its English sibling. `.github/workflows/sync-ko.yml`
  does it automatically, from the SHA that was actually tested rather than whatever main's
  head is by then, and it refuses a run from a fork or from a red main.
- The Korean text moved to main where it can be reviewed. `SECURITY.ko.md` had its three
  false claims corrected and its six-line uninstall section replaced with the current
  ownership rules before it was carried; `README.ko.md` gained the requirements, the
  two-watchers refusal, the safety model and the known limitations, so a Korean-only
  reader is no longer sent to the English page for them. `docs/PLUGIN.md` and the
  changelog are listed as untranslated rather than shipped stale — an English page is
  accurate, and a stale translation is not.

### Housekeeping

- **Fixed: 83 tests were skipped for anyone running a test file directly.** Six files kept
  their `unittest.main()` guard in the middle, so the classes below it never existed by
  the time it ran. `unittest discover` was never affected, which is why nothing said so.
- Both workflows now declare a concurrency group. The release workflow's refusal to
  republish a version reads the release's assets and then uploads, which two runs of the
  same tag could both pass; serialising by tag closes that window.
- Bumping the product version no longer turns the suite red for a reason that is not about
  the product: `scripts/release.json` no longer needs a placeholder entry added by hand.
  What it does check now is the direction that matters — that a version which was released
  did not stay unpinned.

## v0.5.4 — Prove it before you delete it

The final v0.5 hardening release. **Recovery is untouched**: the same failure categories,
the same refusals, the same identity rules, the same bounded retries, the same database.
What changes is that installing, updating and removing this product now act only on things
they can prove belong to them.

Four of the five issues this closes were the same mistake in different places — a *name*
being taken as evidence of ownership. Reviewing the fix for one of them found the same
mistake, unreported, on the install path, where it was worse.

### Nothing is destroyed without proof of ownership

- **Fixed: installing had no ownership check at all.** Issue #1 was reported against the
  uninstaller, and fixing only that left the more dangerous half in place: the install
  path also sweeps `*.old-*`, moves `app` and `runtime` aside and then deletes what it
  moved — under the same environment-variable root, with no check. The uninstaller would
  refuse a stranger's directory while an install into that same directory deleted their
  files and finished with "Installed and running." (Reproduced, on a directory holding
  real files, before and after the fix.) The install path cannot ask the uninstaller's
  question — the first install of all happens into a directory that is not ours yet — so
  it asks the other half: a directory already holding `app`, `runtime`, `config`, `logs`
  or a set-aside copy, with no proof any of it is ours, is refused and left untouched; a
  directory holding none of them has nothing to destroy and is claimed *before* the first
  file is written. Every deletion in the installer now goes through the one gate, and
  there is a test that fails if a new one does not.
- **Fixed: the uninstaller could delete directories it never created.**
  ([#1](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/1)) The
  installation root comes from an environment variable, and the PowerShell uninstaller
  removed `app`, `runtime`, every `*.old-*` and — with `-Purge` — `config` and `logs`
  beneath it, with no check at all. Pointed at a directory that merely *contained* folders
  with those names, it would have deleted them. Now the root has to be one we created, and
  the answer comes from the engine's own provenance rule rather than a second
  implementation in PowerShell that could drift from it. Every path is then re-checked
  against the canonical root before deletion, resolving each component, so a junction
  inside the installation cannot redirect a recursive delete out of it.
- **Fixed: the installer force-stopped any process named `codex-auto-resume-mcp.exe`.**
  ([#2](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/2)) A
  filename is not ownership: another installation, a build, or a test fixture running under
  that name was killed by an unrelated install. The executable's resolved path now has to
  lie inside this installation or this plugin's own Codex cache, and a process whose path
  cannot be read is skipped — not being able to tell is not permission to kill.
- **Fixed: uninstall removed the Codex marketplace by name.**
  ([#5](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/5)) If you had
  repointed `codex-auto-resume-windows` at a fork of your own, removing this product took
  your configuration with it. Both the marketplace and the installed plugin are now checked
  against where they currently point, read from `codex plugin marketplace list --json` and
  `codex plugin list --json`, and left alone with an explanation when they are no longer
  ours.
- The same rule already covered the sign-in entry, the notification identity, the Start
  Menu shortcut and the notification handler as of v0.5.3.
  [SECURITY.md](SECURITY.md) now states it once, for every kind of resource.

### Removing says what actually happened

- **Fixed: a removal Codex refused was reported as a removal.** The plugin and marketplace
  removals threw their exit codes away, so when Codex declined — it holds the plugin cache
  open while the app is running, the same refusal the install path handles by name — the
  uninstaller deleted the program files anyway and printed "Removed." over the top, leaving
  Codex pointing at a directory that no longer exists. Both are now checked, and the branch
  no longer ends on an unqualified success.
- **Fixed: a purge that could not finish could not be retried.** When files were still in
  use, uninstall correctly stopped and asked you to close Codex and run it again — but it
  had already deleted the proof of ownership the retry needs, so the second run refused the
  half-removed installation and there was no way forward. The proof is now the last thing
  to go, after the step that can still stop the run.
- **Fixed: `powershell -File build/make_gui.ps1`, the command `CONTRIBUTING.md` gives, did
  not work.** `$PSScriptRoot` is empty while parameter defaults are bound, so the two
  defaults derived from it threw. Invoked the other way — which is how CI does it — it
  happened to work, so only the documented route was broken.

### A published version is immutable

- **Fixed: a published release asset could be replaced.**
  ([#4](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/4)) The
  workflow had a path that rebuilt an existing tag and re-uploaded over its assets. Since
  the plugin's bootstrap pins that version's SHA-256, a replacement would make every
  install of that version fail — or, worse, succeed with bytes the digest does not
  describe. Publishing now refuses outright if the version already has assets; a
  correction needs a new version. What remains of the manual dispatch is a dry run that
  builds and verifies but cannot touch a release.
- Published archives now carry **build provenance**, attested before publication, so a
  download can be traced to the workflow run and commit that produced it.

### Already fixed, now proven

- **[#3](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/3) was fixed
  in v0.5.3** by explicit Windows argument quoting. It now has regression evidence rather
  than a claim: every case the issue lists — a home with a space, a folder like
  `OneDrive - Company`, a trailing backslash, an embedded quote, a non-ASCII path — is
  round-tripped through `CommandLineToArgvW`, the function Windows itself uses to split a
  command line.

### Settings at high DPI

- **Fixed: the settings window clipped its own labels at 200% scaling.** Windows Forms
  scales the font and leaves explicit pixel sizes exactly as written, so the window kept
  its width while its text doubled. Every fixed size now scales with the display, and the
  window is additionally clamped to the working area, because 780 units at 250% is wider
  than a 1920-pixel screen. The DPI comes from Windows rather than from `DeviceDpi`, which
  reports 96 on a 192-DPI screen unless a .NET Framework opt-in this product does not ship
  is present — a fix written against it changes nothing, and there is a test saying so.

## v0.5.3 — Say what the network does, and close the v0.5 line

The last v0.5 release. **Nothing about recovery changes** — same failure categories, same
refusals, same identity rules, same database, same bounded retries. What changes is that the
documentation now matches the product v0.5.2 turned it into.

### The privacy wording was left behind by plugin-first install

Until v0.5.2 this project made no outbound request at all, and said so in the strongest terms
available. Then the Codex plugin became the recommended way in, and the plugin installs the
product by downloading its release. Those sentences became false on the same day, in five
files and two languages.

- **[PRIVACY.md](PRIVACY.md) is restructured** around the distinction that now matters: what
  the running watcher does, and what installing it does. The watcher's promise is unchanged
  and is still the strong one — nothing under `src/` imports a networking module, so it
  cannot open a connection even by accident. Installing from the plugin fetches one archive
  (and its checksum, when no digest is pinned) from github.com and nowhere else. It uploads
  nothing, but GitHub sees the request and counts the download, and this release stops
  implying otherwise. The release-archive route still touches no network at all.
- **Fixed: "Third parties: none."** GitHub is one, at install time.
- **Fixed: "the fact that you installed it at all" never leaves your computer.** On the
  recommended route it does.
- **Fixed: the tool launches more than `codex queue`.** It also runs `codex app-server
  --stdio`, two short interface probes, and PowerShell for the Restart Manager and toasts.
- **Fixed: it keeps state outside its own directory.** The sign-in value, the notification
  sender identity, the notification button's URL handler and the Start Menu entry are all
  per-user Windows registrations, and they are now listed where the storage is described.
- **Fixed: [SUPPORT.md](SUPPORT.md) pointed at a private security channel** that
  [SECURITY.md](SECURITY.md) says does not exist.
- **Fixed: `docs/PLUGIN.md` claimed nothing downloaded is passed to a shell** — while the
  bootstrap runs the installer out of the archive it has just unpacked. The claim that holds
  is narrower: nothing from the network is *piped into* a shell.
- **Fixed: the bootstrap's own header overstated what `-ArchivePath` checks.** A local file
  has no sidecar to fetch, so without a pinned digest for that version only the contents
  checks stand behind it. It now says which of the three cases it took.

### Install and uninstall bugs an adversarial re-audit turned up

None of these change recovery. All of them are cases where the product did something
other than what it said.

- **Fixed: the plugin was never registered for anyone whose user folder has a space in
  it.** `Start-Process -ArgumentList` joins its arguments with spaces and quotes nothing,
  so a marketplace path under `C:\Users\Example User\` arrived at `codex` as two
  arguments. Registration failed, the failure was only a warning, and the installer still
  ended with "Installed and running." The watcher and the settings window worked; the
  skill and the panel the user had asked for were simply absent. The installer now quotes
  the way `CommandLineToArgvW` reads back — the same rule the sign-in entry has used since
  v0.5.0 — verified by round-tripping through that function.
- **Fixed: "uninstall aborted before deleting any state" was true only of state.** The
  fail-closed check for a running watcher ran *after* the autostart value, the
  notification identity, the Start Menu entry and the toast handler had already been
  removed. Refusing therefore left an installation that still ran and still had pending
  recoveries, but no longer started at sign-in and could no longer show a notification.
  The check is now the first thing the command does.
- **Fixed: uninstalling one copy silenced another copy's notifications.** The Start Menu
  shortcut and the notification identity are per-user singletons at fixed locations, so a
  second installation overwrites them rather than adding its own — and they were removed
  with no ownership check, unlike the autostart and the URL handler beside them. They now
  get the same check, and say whose they were when they keep them.
- **Fixed: `Uninstall.cmd` threw away the exit code of the step that refuses to remove a
  running installation**, then deleted the engine and the interpreter anyway and reported
  success.
- **Fixed: uninstall reported "Removed." after a removal that half-failed.** With Codex
  open, its MCP server holds the bundled interpreter's images open and they cannot be
  deleted. The install path has stopped those launchers first since v0.5.1; the uninstall
  path now does too, and checks afterwards rather than swallowing the error.
- **Fixed: the plugin's setup script failed every download on PowerShell 7.** The check
  on where a redirect finally landed read a property that only exists on Windows
  PowerShell 5.1, and under `Set-StrictMode` reading the other one throws. It now reads
  either, and refuses if it can read neither.
- **Fixed: the repair path took no lock.** Re-running setup on an already-installed
  version skips the installer, so it skipped the installer's lock as well and could run
  beside one.
- **Fixed: the MCP launcher was the one component that ignored the install-home
  override**, so moving the installation left the panel unable to find it.
- **Fixed: running the test suite wrote a real registry entry.** One test class guarded
  the registry function by function and had missed `install_protocol`, so every run left
  a `codex-auto-resume:` handler in the user's own HKCU pointing at a temporary directory
  that no longer existed. It was found by an uninstall correctly refusing to remove a
  handler that belonged to "a different installation" — which it did. The class now fakes
  the registry module itself, the way the other test modules already did.
- Smaller hardening in the same script: the file the install actually executes is now in
  the required-contents list; an archive whose manifest differs only in letter case is
  refused rather than crashing; a manifest with no version at all gets the intended
  message; and the case where nothing could be compared no longer prints a tick and a
  hash beside it.

### One property was undocumented rather than overstated

Every `codex` subprocess this tool starts already runs with analytics off, every
OpenTelemetry exporter off, prompt logging off, and the ChatGPT base URL pinned so a stray
local configuration cannot send a continuation somewhere else. That has been true for
several releases and appeared in no document. It does now, and a test keeps it.

### Tests that stop this happening again

`tests/test_privacy_claims.py` asserts the code property the wording rests on — which files
may reach the network, and that the watcher's cannot — and then that no absolute network
claim stands without its qualifier nearby. The checks are shape-based rather than exact
strings, so a rewrite that is still true keeps passing. It guards the other direction too:
the changelog must keep a section for every released tag, so a future sweep for a retired
phrase cannot take the history with it.

### Smaller corrections

- The README no longer implies a screenshot of the Codex panel was photographed inside
  Codex; it is a render of the exact resource the plugin serves, and now says so.
- `watcher_launcher.py` still described the engine-resolution order from before v0.5.2.
- `make_release.py` called the archive byte-identical across builds, three lines from its own
  docstring explaining why it is not.
- The README claimed Python was needed to install the plugin from a marketplace. It is not —
  the setup script is PowerShell — and a duplicated sentence left over from v0.5.2 is gone.

## v0.5.2 — Install it from Codex, and look like one product

A patch release. Recovery is unchanged: the same failure categories, the same refusals, the
same identity rules, the same database. What changed is how you install it and what it looks
like once you have.

### Installing it from Codex actually installs it

Adding this plugin from a marketplace used to hand you a source tree and a skill whose first
instruction was to find any Python that would run. That produced a **second, lesser
installation**: a watcher registered against whatever interpreter answered, no settings
window, no panel, an engine loaded from the plugin cache — and if the machine already had a
real installation, both of them sharing one state directory.

- **The plugin now installs the product.** Ask Codex to *set up auto resume* and it runs
  `scripts/bootstrap.ps1`, which downloads the matching release, verifies it and installs it.
  Nothing has to be installed first: no Python, no administrator rights, no manual download.
- **What it is allowed to fetch is narrow on purpose.** One URL shape, built from constants
  and this plugin's own version — no "latest", and no input that reaches a URL, so a v0.5.2
  plugin can ask for the v0.5.2 archive and nothing else. HTTPS with TLS 1.2 minimum, and the
  final response has to come from GitHub.
- **It verifies before it runs anything.** SHA-256 against a digest pinned in the plugin when
  there is one and the published `.sha256` otherwise — it prints which of the two it used
  rather than implying the stronger one — then that the archive contains what a release is
  defined to contain, that its manifest declares this product at this version, and that no
  entry escapes extraction. Any failure deletes the download and stops. Checked against a
  file that is not an archive, a genuine archive declaring the wrong version, and a correct
  archive against a wrong pinned digest.
- The README now leads with the Codex route and keeps the archive route for anyone who would
  rather nothing downloaded on their behalf. Both end at the same installation.

### One installation, whichever way you arrive

- **Fixed: a plugin update could swap the engine underneath an installation.** The watcher
  resolved its code from the newest copy in the Codex plugin cache, by modification time, so
  installing a newer plugin from a marketplace silently replaced the running engine while the
  settings window still talked to the installed one. The installed application now wins.
- **Fixed: setup would configure a watcher with nothing to run it.** It now refuses unless the
  bundled runtime and the application are both present, and prints the command that installs
  them, instead of improvising a lesser installation.
- **Fixed: the sign-in entry could name a different interpreter from the installed one.** Every
  registration setup writes — autostart, the notification handler, the watcher itself — now
  names the interpreter the installer deployed.
- **Fixed: the installer ignored the state-directory override the Python side honours**, so
  setting it deployed to one place and configured another.
- **Two installers can no longer run at once.** A double-clicked `Install.cmd` and a plugin
  bootstrap used to be able to copy over each other's half-written payload.

### A new look

- **The green is retired.** The identity is a deep-blue to cyan ramp that carries the product's
  own behaviour: deep blue while it waits, cyan the moment it acts.
- **A new mark.** Four concepts were built and compared at all nine icon sizes on light and
  dark grounds — `build/icon_concepts.py` still renders the sheet — and the winner is an open
  ring with a bright head at its leading end: the ring is the wait, the gap is the
  interruption, the head is the resume. There is a vector master at `assets/brand/icon.svg`.
- **The settings window and the Codex panel were redesigned together.** State leads on both
  now: what the watcher is doing is the first thing and the largest type, where it used to be a
  muted sentence along the bottom under sixteen checkboxes. What is waiting to resume comes
  before what is configured, and the cards run in the order the argument does — what may be
  recovered, how hard it will try, what it will tell you, when it starts.
- **The plugin card has artwork.** Codex has always validated an icon, a light and dark logo
  and screenshots; this project never supplied any of them.
- **Fixed: white text on the panel's dark-theme accent measured 2.6:1.** Found by a contrast
  assertion, not by looking at it. Text drawn on the accent is now its own colour, and it goes
  dark exactly when the accent goes light.
- **Fixed: the panel asked for a colour variable the generator never emitted.** That is not an
  error in CSS — the declaration is dropped and the text quietly inherits.

### One palette instead of four

Four surfaces carried their own copies of the colours — the settings window in C# literals,
the panel in a stylesheet, the icon renderer, the plugin manifest — and they had already
drifted. The palette now lives in one module; `gui/Brand.cs` and the panel's stylesheet are
generated from it, and tests regenerate both and compare, so a hand-edit fails the suite
instead of shipping. A test also sweeps every tracked file for the retired colours, because
that is how a colour survives a rebrand: in a document nobody reopened.
[`docs/BRAND.md`](docs/BRAND.md) records the decisions.

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

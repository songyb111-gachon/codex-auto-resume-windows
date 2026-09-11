# The Codex plugin layer

This project keeps the recovery engine small, local, conservative and fail-closed, and uses
Codex itself as the installation and control interface instead of building a second
management application.

The plugin is a **thin front end**. It installs no second engine and holds no recovery logic,
and none of its tools or skill commands queues a message to a thread; only the watcher does
that. The skill works through the same command line a manual installation uses, and the
tools through the control layer the settings window uses; where the two overlap, both end in
the same store operations.

```
Codex UI  ->  plugin skill  ->  existing CLI  ->  small safe watcher
```

## Layout

The repository root *is* the plugin root. There is exactly one copy of `src/`.

| Path | Purpose |
| --- | --- |
| `.agents/plugins/marketplace.json` | Marketplace index; one entry whose `source.path` is `"."`. |
| `.codex-plugin/plugin.json` | Plugin manifest. Declares `skills` and the card's artwork; nothing else executable. The release build adds `mcpServers` to its copy (see below). |
| `skills/codex-auto-resume/SKILL.md` | What Codex reads to answer "turn on auto resume". |
| `scripts/bootstrap.ps1` | Turns the plugin into an installation (see below). |
| `scripts/release.json` | The only location the bootstrap may fetch from, and the pinned digests. |
| `scripts/plugin_setup.py` | The control layer the skill calls. |
| `scripts/watcher_launcher.py` | Stable autostart entry point (see below). |

`codex plugin add` copies the **plugin root subtree** into
`<CODEX_HOME>/plugins/cache/<marketplace>/<plugin>/<version>/`. Because the root is the plugin
root, `src/` travels with it. A nested `plugins/codex-auto-resume/` layout would have required
duplicating the engine, since the copy cannot reach outside the plugin root.

Verified against `codex-cli 0.153.4`, including with the plugin folder name deliberately
different from the plugin name (a clone is named `codex-auto-resume-windows`, the plugin is
`codex-auto-resume`). Codex's own `validate_plugin.py` accepts this layout.

## The MCP server

The manifest in this repository does not declare `mcpServers`; the release build adds it
to the copy it ships. That split is deliberate. The server runs on the
interpreter that comes in the release archive, so a marketplace install straight from
GitHub has no interpreter to run it with - and with the declaration in the repository
manifest, `codex plugin add` from a clone succeeds and registers the server as *enabled*,
pointing at an executable that is not there. The user gets a permanently failing entry
rather than an error they can act on. Measured against `codex-cli 0.153.4`, in an
isolated `CODEX_HOME`. `.mcp.json` itself stays in the repository, because a
security-relevant declaration should be reviewable as source rather than assembled out of
a string in a build script.

`hooks` is **rejected** by Codex plugin validation, so it is not used.

The server exists so the product can be managed from inside Codex - status, pending
recoveries, settings, pause and resume, cancel - and so those actions mean the same thing they
mean everywhere else, because every one of them goes through the same control layer
(`control.py`) the settings window's bridge uses. The ones the command line also offers -
pausing, resuming, cancelling, the status and the pending list - end in the same store
operations it uses.

It is a front end and nothing more. No tool detects a failure, reserves an interruption or
sends a continuation; the watcher stays the only thing that recovers, and it keeps running when
the server is not. Two tools change *when* the watcher next looks at a record: `retry_now` moves
a waiting record's next check to now, and `reset_recovery_budget` returns an exhausted record to
waiting with its recovery attempts and its no-progress count reset to zero, and switches
recovery for that conversation back on. Every gate still runs. That is a property of the
surface, not a rule the model is asked to follow: there is no call that retries an unclassified
failure, resolves a conversation by anything but its exact id, resends an uncertain submission
or forces a send.

### The tools, and which ones Codex asks about

The table describes the server on the main branch, which ships in the release after v0.5.7.
The server runs from the installed release, not from the plugin you add, so until that release
is installed you have the server of the release you installed, v0.5.7 or earlier, which
differs in four ways: pause and resume are one tool, `set_auto_recovery`, marked in neither
direction; of the other tools that change something, only `restore_default_settings` and
`cancel_recovery` are marked; `update_settings` also accepts two advanced settings; and
`get_status` also reports the installation directory. The last two are described below the
table.

| Tool | What it does | Marked destructive |
| --- | --- | --- |
| `open_settings` | Shows the settings panel. Opening it changes nothing. | no |
| `get_status` | Whether recovery is on, whether the watcher is running, counts by state, the version and the current settings. | no |
| `list_pending` | Pending recoveries with their interruption ids, conversation ids, states and attempt counts. | no |
| `pause_auto_recovery` | Global pause. The watcher sends nothing while paused. A continuation already waiting in Codex's queue is withdrawn when the watcher reaches it, and that recovery is cancelled - or, if the withdrawal cannot be confirmed, it is marked `submission_unknown` and never resent, though Codex's queue may still hold it; if Codex delivers it first, it counts as resumed. | no |
| `retry_now` | Moves a waiting record's next check to now. | no |
| `resume_auto_recovery` | Undoes a global pause. | yes |
| `update_settings` | Changes user-facing settings: the recovery categories, the limits and the notifications. | yes |
| `restore_default_settings` | Puts every setting back to its recommended value. | yes |
| `cancel_recovery` | Stops recovery for the conversation the named interruption belongs to: every unfinished record on it is cancelled (one whose message is already on its way is reconciled instead and never resent), and the conversation is switched off. | yes |
| `reset_recovery_budget` | Returns an exhausted record to waiting, as above. | yes |
| `start_watcher` | Starts the watcher the installer starts, if it is not running. | yes |

"Marked destructive" is MCP's `destructiveHint` annotation, which the server declares for
each tool. Codex decides whether to ask under your approval settings; in its Auto approval
mode it asks before running a tool marked this way. A tool that can add automation is marked.
Turning recovery back on, re-arming a record that had stopped, changing or restoring settings
(either can switch a recovery category back on) and starting a watcher you stopped can all add
automation. `cancel_recovery` is marked too, because it switches a whole conversation off in a
way no tool reverses: no tool restarts a record it cancelled, and through this plugin's tools and skill
commands the conversation comes back on only if you give an exhausted recovery on it its
attempts back. Outside them, the command line's `enable` with that conversation's id switches
it back on. Pause and `retry_now` are not marked: a pause only reduces automation, though it
also withdraws and cancels a continuation already waiting in Codex's queue, which no tool
restores; `retry_now` cannot make anything recoverable that was not already pending. In
v0.5.7 and earlier, pause and
resume are one tool, `set_auto_recovery`, not marked destructive in either direction, so in
Codex's Auto approval mode it runs without asking and a prompt-injected turn can quietly
reverse a pause.

On the main branch, `update_settings` neither offers nor accepts the advanced settings -
`codex_exe`, which engine binary to run, and `detection_lookback_hours` - which the settings
window and the panel do not show either; a client that sends them anyway is refused. And
`get_status` does not report the installation directory, whose path contains your Windows user
name, though the settings it returns do include `codex_exe`, which is empty unless an engine
path has been set, by hand or through `update_settings` in v0.5.7 or earlier. Both changes
ship in the release after v0.5.7. In v0.5.7 and earlier, `update_settings` accepts those two settings
as well and is not marked destructive, so in Codex's Auto approval mode it accepts them
without asking, and `get_status` reports the installation directory as `home`.

What a tool returns becomes part of the Codex conversation it was called from, and should be
treated as sent to OpenAI like any tool output: the status summary (in v0.5.7 and earlier,
with the installation directory), the settings, and for `list_pending` and `open_settings`
the conversation and interruption ids with their states and counts. No tool returns a
conversation's title or content. The same holds for command output the skill asks Codex to read back - `status`,
`pending`, `doctor`, `logs` - which also includes local paths and log lines.

### Two constraints that shaped it

**The command must be contained in the plugin.** Codex accepts a plugin stdio `command` only as a
bare executable name or a path inside the plugin, and `cwd` only as a contained `./`,
`${PLUGIN_ROOT}` or `${PLUGIN_DATA}` path. An absolute path to the bundled interpreter is
neither, and a bare `python` would put back the system-Python requirement the product removed.
So the payload ships `mcp/codex-auto-resume-mcp.exe`, a small launcher that resolves the
interpreter from the runtime home and starts the server.

**The launcher relays the standard streams; it does not let the child inherit them.** A child
process started with `CREATE_NO_WINDOW` and no explicit handle passing is given no usable
standard handles at all. The server then waits forever for input, the host waits forever for a
handshake, and nothing appears in any log. That was measured here, not guessed: the first
version inherited, and both processes sat idle until they were killed.

Registration was verified against `codex-cli 0.153.4`:

```
> codex mcp get codex-auto-resume
codex-auto-resume
  enabled: true
  transport: stdio
  command: ./mcp/codex-auto-resume-mcp.exe
  cwd: ...\plugins\cache\codex-auto-resume-windows\codex-auto-resume\0.5.0\.
```

`"cwd": "."` rather than `"${PLUGIN_ROOT}"`: both are accepted by the validator, but the
variable form is reported back as a literal path segment appended to the plugin root, so the
plain form is the one that resolves the way it reads.

## The plugin is not the product, so it installs the product

A plugin is a source tree. The parts that do the work — a Python runtime, a settings
window, an MCP launcher — are a runtime and two compiled binaries, and they have no
business in a source repository. So they are not in the plugin, and cannot be.

**Codex has no install hook to put them there either.** Measured against `codex-cli
0.153.4`, on a machine with nineteen installed plugins: a manifest may declare `skills`,
`mcpServers`, `apps` and `hooks`, and none of those runs a command when a plugin is
installed. `apps` names *hosted connectors* by id, which is no use to a local Windows
tool. `hooks` fires on conversation lifecycle events and routes to an MCP tool — and the
CLI's own guidance is to omit it from an authored manifest, because validation rejects it.
`codex plugin` offers `add`, `list`, `marketplace` and `remove`, and nothing else.

So `scripts/bootstrap.ps1` fetches the matching release and runs its installer. It is
PowerShell rather than Python because Python is one of the things it installs. What it is
allowed to do is deliberately narrow:

| | |
| --- | --- |
| **Where from** | One URL shape, built from `scripts/release.json` and the version in this plugin's own manifest. No "latest", no parameter that reaches a URL: a plugin at a given version can fetch that version's archive and the `.sha256` published beside it, and nothing else. It fetches the `.sha256` only when there is no pinned digest to check against. |
| **Over what** | HTTPS, TLS 1.2 minimum, and the *final* response URI has to be one of exactly three hosts - `github.com`, `objects.githubusercontent.com` or `release-assets.githubusercontent.com` - because a release download redirects to GitHub's object storage and nowhere else. |
| **Checked how** | SHA-256 against the digest pinned in this plugin's `release.json` when there is one, and otherwise against the `.sha256` published beside the archive - and it says which. Then that the archive contains everything the release is defined to contain, that its manifest declares this product at this version, and that no entry escapes extraction. |
| **Then** | Extract to a fresh temporary directory and run `install/install.ps1` from it. That installer is code from the downloaded archive, and nothing from the archive runs before all of the above passes. |
| **Never** | Administrator rights, any change to a Windows security setting, any execution-policy change beyond its own process, and nothing from the network is ever piped into a shell. Any failure deletes the download and stops. |

**About the two digest cases**, because the difference is worth stating rather than
blurring. A pinned digest is a commitment made in the repository: the file has to be
exactly those bytes. The sidecar is served from the same origin as the archive, so
checking one against the other is trust-on-first-use over TLS to GitHub — it proves the
download is intact and is a coherent build of this exact version, not that GitHub served
what the author intended. The script prints which of the two it used — and a third case,
a local file handed to `-ArchivePath` for a version with no pinned digest, where there is
nothing to compare against at all and it says so without a tick.

A version has no digest in `release.json` at the moment it is tagged. Its entry is added after
publication, by a commit to `main` that records the digest of the published file; the bootstrap
treats a missing entry and a `null` one the same way. Two consequences follow, and neither is a
bug to be fixed so much as a shape to be aware of:

* **The copy of the plugin inside the release has no digest for its own version**, so it
  could verify only by sidecar. That copy is the one Codex installs from after the installer
  runs — and it has no need to bootstrap, because by then the product is already installed.
  The pinned digest is for the plugin someone adds from the marketplace, which tracks `main`
  and therefore picks up the post-release pin commit.
* **The release workflow will not replace a published version.** It used to be able to
  rebuild an existing tag and upload over its assets; a digest recorded from the old archive
  would then match nothing, and the bootstrap would refuse to install that version for
  everybody. Since v0.5.4 the workflow refuses to publish when the version already has
  assets, so a correction takes a new version number. That refusal is the workflow's own:
  the releases are not GitHub "immutable releases", a repository setting that is not enabled
  today, so someone with write access to the repository could still replace an asset by
  hand. The pin is what would reveal that: the bootstrap refuses an archive that no longer
  matches the digest pinned for its version, and changing a published pin takes a commit to
  `main`, visible in its history unless that history is rewritten. A version whose pin has
  not landed yet has no such protection, and neither do v0.5.0 and v0.5.1, which have no pin.

The bootstrap's checks were verified by feeding it a file that is not an archive, a genuine
archive declaring a different version, and a correct archive against a deliberately wrong
pinned digest. All three were refused with nothing installed.

Every archive published since v0.5.4 also carries a GitHub build provenance attestation,
which ties it to the workflow run and the commit that built it. The bootstrap does not check
the attestation; `gh attestation verify` does, for anyone with the GitHub CLI.

Every archive published so far, v0.5.0 through v0.5.7, was built by the earlier single-job
release workflow, which referred to its Actions by floating tags, and its executables are not
reproducible: each carries a build time and a random module id, and no rebuild of them will
match. On the main branch the release workflow builds and publishes in separate jobs, pins
every Action to a commit, and removes what made the executables differ from one build to the
next; the checkout also gives every text file CRLF line endings whatever the machine's Git
settings, because the archive's bytes include them. That ships in the release after v0.5.7,
which is the first built that way. The in-box C# compiler stamps a build time and a fresh
module version id into each executable, so the build normalises both - a fixed PE timestamp,
and a module id derived from the content - and the workflow compiles the two executables
twice and refuses to publish if they differ. When that normalisation was added, two local
builds and a build from a separate clone produced byte-identical executables; the workflow's
double compile repeats that check on every release build. That measurement covers the executables, not the
whole archive, and whether GitHub's runner produces the same bytes as a local build has not
been verified, so the pin is still taken from the published file rather than from a
rebuild. [VERIFY.md](VERIFY.md) has the rebuild procedure, and what a match or a mismatch
does and does not show.

### Checking a download yourself

`Install.cmd` checks nothing about the archive it came in. On the plugin route the bootstrap
did the checking before it extracted anything; on the manual route that is your step, and it
belongs before you extract the ZIP, not after. In PowerShell, in the folder you downloaded to:

```powershell
(Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
```

Compare the result with the `.sha256` file published beside the archive, with the SHA-256
GitHub shows beside the asset on the release page, and with the digest pinned for that version
in
[`scripts/release.json` on the main branch](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json).
The pin is the one that matters: it is a commit in the repository rather than a file next to
the download, so it comes through a separate channel. Read it from `main`; the copy inside a tag
or inside the archive has no digest for its own version. `Get-FileHash` prints upper-case hex
and `release.json` stores lower case, so compare them ignoring case. A version released so
recently that its pin commit has not landed yet has the sidecar, the digest GitHub shows on the
release page, and the attestation, and no pin. Versions before v0.5.2 have no pin, and
versions before v0.5.4 have no attestation. With the GitHub CLI, also check where the
archive was built:

```powershell
gh attestation verify .\CodexAutoResume-vX.Y.Z-win-x64.zip --repo songyb111-gachon/codex-auto-resume-windows
```

If you have the plugin from the marketplace, its bootstrap can install a file you already
have instead of downloading one: `-ArchivePath` takes the archive for the plugin's own version,
checks it against the pinned digest when that version has one, and says plainly when it has
nothing to compare against.

[VERIFY.md](VERIFY.md) sets out the same checks step by step, what each one does and does not
prove, and how to rebuild a release yourself.

## Where each route ends up

Every way in converges on one installation, in `%USERPROFILE%\.codex-auto-resume` by default: one
bundled interpreter, one watcher, one SQLite database, one `settings.json`, one sign-in
entry, one notification handler and one Start Menu entry. `tests/test_convergence.py`
pins the rules that make that true.

| You do this | What happens |
| --- | --- |
| Download the archive, check it (above), run `Install.cmd` | Deploys the runtime and the application, registers the plugin from the payload itself rather than downloading it, then runs setup. It verifies nothing about the archive. |
| `codex plugin add`, then *set up auto resume* | The skill has Codex run `bootstrap.ps1`; the bootstrap downloads and verifies the matching release and runs the same installer. Identical result. On the main branch the skill tells Codex to run `bootstrap.ps1` by its absolute path inside the plugin, and never as a relative `scripts/bootstrap.ps1`; that ships in the release after v0.5.7, and the skill in v0.5.2 through v0.5.7 gives the relative form. Codex follows the skill of the plugin you added: one added from the GitHub marketplace is a copy of `main` as it was when the marketplace was added or last upgraded, so it gives the absolute path only if that was after the change reached main (2026-09-11) - an older copy gives the relative form until the marketplace is upgraded with `codex plugin marketplace upgrade codex-auto-resume-windows` - while the copy the installer registers from an installed release carries that release's skill. |
| Either of the above with something already installed | The installer first asks a running watcher to stop through its stop event and waits up to a minute. It does not kill it: if the old watcher is still running when the wait ends, the upgrade completes and says so, and the new version takes over once the old watcher has exited and a watcher is started again (`start_watcher`, the settings window's Start watcher, or the next sign-in). Then it moves the old payload aside, copies, and rolls back on failure. Settings, pending recoveries, retry budgets and logs are kept. Setup does switch automatic recovery on, and registers the sign-in start again unless it is run with `--no-startup` (the bootstrap's `-NoStartup`, the installer's `-SkipStartup`), so a global pause does not survive a reinstall, an upgrade or a repair, and neither does a sign-in start you had turned off unless you pass that switch. Unless it is run with `-Force`, the bootstrap skips the download entirely when the installed version already matches, and re-runs setup to repair its Windows registrations - the sign-in entry, the notification button's handler and, while notifications are on, the notification sender identity and the Start Menu entry - and start the watcher if it is not running. That repair does not re-register the plugin or its marketplace in Codex; only the installer does that. |
| Ask for anything else with nothing installed | `setup` refuses and prints the command that installs it. Nothing is registered, so there is no half-installation for a later run to mistake for a real one. |
| `codex plugin remove` | Removes the skill, the tools and the panel. The watcher keeps running, from the installed application rather than from the cache copy that just disappeared. `uninstall` is what removes it. |
| Two installers at once | The second is refused by a named lock. |
| A source checkout beside an installation | Refused, as before: `setup` stops when the registered sign-in entry belongs to a different home, because two watchers could each resume the same interruption. |

## Runtime state lives outside the plugin

The plugin cache path contains the version, so it changes on every update. Three
consequences are designed around:

- **State must not live in the plugin.** Pending interruptions, settings and logs live in
  `%USERPROFILE%\.codex-auto-resume\` by default. Updating or removing the plugin does not touch them.
- **Autostart must not point into the plugin.** Setup copies `watcher_launcher.py` to that same
  stable directory and registers *that*, so an update needs no re-registration.
- **The installed application is the engine**, not the plugin cache copy. The launcher
  resolves the installation's `app` directory first - under the home `runtime.json` records,
  `%USERPROFILE%\.codex-auto-resume\app` by default - and, for a plugin installation, falls
  back to the cache only when that directory holds no usable application. It used to prefer
  the newest cache copy by modification time, which meant installing a newer plugin from a
  marketplace silently swapped the engine underneath an older installation while the
  settings window still talked to the old one. Updating a plugin should update the skills and the manifest;
  replacing the engine is what the installer is for. On the main branch the cache fallback
  considers only copies from this product's own marketplace, `codex-auto-resume-windows`, and
  skips a same-named plugin from another marketplace; that ships in the release after
  v0.5.7, and the launcher in v0.5.7 and earlier takes the newest same-named copy from any
  marketplace. After the cache, the launcher tries the directory setup last ran from, which
  `runtime.json` records; the installer runs setup from the installed application, so that is
  normally the same directory.

Tested: after replacing `0.2.0` with `0.2.1+codex.local-test` and deleting the old directory,
the launcher resolved the new one and the state was untouched.

## `codex plugin remove` vs `uninstall`

They are different operations and neither implies the other.

| | `codex plugin remove` | `plugin_setup.py uninstall` |
| --- | --- | --- |
| Removes the skill from Codex | yes | no |
| Stops a running watcher | no | yes |
| Removes sign-in autostart | no | yes |
| Deletes settings and pending state | no | only with `--purge` |
| Deletes logs | no | yes |
| Deletes the program files and the bundled runtime | no | no |

There is no plugin uninstall hook to attach to, so removing the plugin cannot clean up on its
own.

Nor does either of them remove the *installation*. `uninstall` stops the watcher and takes away
its Windows registrations - the sign-in entry, the notification sender identity, the
notification button's handler and the Start Menu entry, each only where it belongs to this
installation - and `--purge` additionally deletes settings and pending recoveries - but the
application, the bundled interpreter and the settings window stay in the installation
directory (`%USERPROFILE%\.codex-auto-resume` by default), because they are what a later `setup` would pick up again.
Of this product's commands, only `Uninstall.cmd` from the release archive removes those.
Deleting the directory by hand removes the same files, along with the settings and pending
recoveries in it, and is safe once `uninstall` has run, because the watcher no longer runs from
it. Unlike `Uninstall.cmd`, it leaves this plugin and its marketplace registered in Codex,
pointing at a directory that no longer exists; run
`codex plugin remove codex-auto-resume@codex-auto-resume-windows` first, and
`codex plugin marketplace remove codex-auto-resume-windows` for the marketplace. If the plugin
is still installed, close Codex first: Codex starts the plugin's tools on the bundled
interpreter.

The order matters: run `uninstall` first, then `codex plugin remove`. The other way round leaves
a watcher running with no skill to stop it.

## Two installations are refused, not merged

A manual checkout and a plugin installation keep separate state and separate single-instance
locks, so both watchers would run and could each resume the same interruption. `setup` therefore
checks the registered autostart value and stops if it belongs to a different installation.
`status` reports the same conflict.

Since v0.5.2 there is a second, earlier refusal, because the first one arrived too late.
`setup` will not configure a watcher at all unless the bundled runtime and the application
are both present in the state directory — it prints the bootstrap command instead. What it
used to do was register a watcher against whatever interpreter was running it, which is how
a marketplace install produced a lesser second product in the first place: a different
Python, no settings window, no panel, and the same state directory as a real install. Every
registration setup writes — the sign-in entry, the notification handler and the watcher
itself — now names the interpreter the installer deployed, not the one that ran setup.

The installer takes a named lock for the same reason, so a double-clicked `Install.cmd`
and a plugin bootstrap cannot copy over each other's half-written payload. It is not
released explicitly: the installer has many exit points, Windows releases a mutex when the
process ends, and an *abandoned* lock means the previous holder died, so it is taken rather
than treated as contention.

Related: `uninstall` only unregisters an autostart value that belongs to the home being
uninstalled. It reports and keeps anything else.

## Language

The product's own interface text - the notifications, the settings window, the settings panel
in Codex and the plugin layer's messages - is in English by default, and in Korean only when
the first language the detection below finds is Korean - normally, when Korean is the **most
preferred** UI language. Some text does not follow the detection: the output of the
`auto_resume.py` command line and the MCP tools' text replies are in English, and the
continuation message the watcher queues into a conversation is in Korean for every user.

Detection reads the same source the ChatGPT desktop app uses for its own display language:
Electron's `app.getPreferredSystemLanguages()`, which on Windows is `GetUserPreferredUILanguages`.
Falling back, it reads `LC_ALL` / `LC_MESSAGES` / `LANG`, and `CODEX_AUTO_RESUME_LANG` overrides
everything. No language is inferred from an IP address, a time zone, a user name, a country or a
keyboard layout. When none of these gives an answer, the language is English, never a guess.

The translated strings live in two small tables in `src/codex_auto_resume/`: `messages.py` for
the plugin layer's messages and the notifications, and `interface.py` for the settings window
and the panel, which are both handed the strings for the language `messages.py` decides. Text
outside them - the `auto_resume.py` command line's output, the MCP tools' replies, the
continuation message and the settings window's built-in English fallbacks - is not
translated. No i18n framework and no new dependency.

## The usage-limit checkbox: not possible through any official API

The goal was to add exactly one line to the usage-limit notice Codex already shows:

> ☑ Automatically resume this task after the reset

**This cannot be done through the official Codex plugin API.** It is not implemented, and nothing
pretending to be it was built in its place. Re-checked from scratch for v0.5; the answer has not
changed.

What was checked, against `codex-cli 0.153.4` and ChatGPT desktop `26.901.5280.0`:

1. **The plugin manifest has no UI surface.** Codex's own bundled plugin-authoring documentation
   and its `validate_plugin.py` accept exactly these top-level fields: `id`, `name`, `version`,
   `description`, `skills`, `apps`, `mcpServers`, `interface`, `author`, `homepage`, `repository`,
   `license`, `keywords`. `interface` is catalog presentation only — display name, description,
   category, logo, brand colour, screenshots, default prompts. Nothing addresses an error state
   or an app surface.
2. **`apps` / `.app.json` is not a UI extension.** Its entries carry only `id` and `category`;
   it registers connector apps, it does not render controls.
3. **Plugin-provided UI is conversation-scoped.** MCP App `ui://` resources are fetched through
   `mcpServer/resource/read` with an `originCallId` and a `threadId`, and render in a sandboxed
   iframe attached to a tool result. There is no placement that anchors to app chrome.
4. **The banner is hardcoded in the desktop app.** The notice is a React component built from
   compiled `react-intl` messages (`codex.upsellBanner.merged.title`,
   `codex.upsellBanner.*.headline`) inside the Electron bundle.
5. **`pluginSlots` is unrelated.** The name looks promising but it belongs to the sidebar
   onboarding checklist, mapping roles such as `mailApp` to connector names such as `gmail` so a
   prefilled prompt can mention the right plugin. It is not a rendering slot.
6. **There is no usage-limit lifecycle hook.** The hook event names in the binary are
   `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `SessionEnd`, `Stop`,
   `SubagentStop` and `Notification`. None fires on a usage limit — and plugin validation rejects
   `hooks` anyway.

### The three options, ranked, and what each one is worth

The question was re-opened from scratch for v0.5 against the build above, on the chance that a
newer Codex had added a surface. It has not. What follows is what each option is actually worth
today, best first.

**A — a real control inside the notice. Still impossible.** Everything in the list above was
re-checked against this build. The banner is still assembled from compiled `react-intl` message
ids inside the Electron bundle (`codex.upsellBanner.*.headline`, `codex.upsellBanner.cta.*`);
there is no id, slot, prop or plugin hook anywhere near it. Nothing in the plugin manifest, the
MCP schema or the app's own bundled plugins can address app chrome.

**B — a Codex-native form at the moment of the interruption. Available in principle, not shipped.**
An MCP server can call `elicitation/create`, and this build renders it: the wire types
`ElicitRequestParamsWire::Form` and `::Url` are present, and the response is `accept` / `decline`
/ `cancel`. A boolean property becomes a real checkbox. It carries no turn id, so it is not
structurally bound to a live turn.

It is not shipped anyway, and the reason is honest rather than technical. To reach a person at
the moment of the interruption, the server would have to push a form into whatever conversation
happens to be open, about a different conversation that failed - unasked, while they are working
on something else. It also only reaches them if Codex is open, which is exactly when it is least
needed, and the feature sits behind `features.tool_call_mcp_elicitation` (Statsig layer
`223073164`, param `enable_tool_call_mcp_elicitation`), so on a machine where the gate is off it
would silently do nothing at all. Building an interruption whose delivery cannot be relied on,
into a place the user did not ask for it, is worse than not building it.

What *is* shipped is the same mechanism where it belongs: an MCP settings panel the user opens by
asking. It renders in the conversation as a `ui://` resource on a read-only tool result, shows the
current state and every option, and can pause recovery or change a setting - the whole control
surface, at the moment the user wants it rather than at a moment we chose for them.

**C — a Windows notification. Shipped, and the one that actually arrives.** The watcher raises it
the moment the interruption is recorded, whether or not Codex is open, carrying the one control
the checkbox would have offered: a **Don't resume** button for that exact conversation, with
resuming as the default. It is not inside the Codex notice, but it arrives at the same moment,
which is the part that matters.

None of this is worked around. The only ways to put a control in that banner would be DOM or
renderer injection, an Electron or binary patch, a CDP/DevTools bridge, accessibility-control
injection, or GUI automation - all of them out of scope by design, and all of them would make
this tool something a person should not install.

## Local installs copy the whole working tree

Installing from a local path copies every file in the directory, including files Git ignores
(`config/`, `logs/`, build scratch). Installing from GitHub clones the repository, so only
tracked files ship. Prefer the GitHub source unless you are developing the plugin.

This is not what the installer does, despite also registering a local marketplace. It points
Codex at the installed application directory, which is a payload the build assembled from an
explicit list — no ignored files, no scratch, and no working tree to leak from. Doing it that
way means the plugin is installed from the same bytes the archive's checksum covers, rather
than from a second download.

Two details of that registration. If the `codex-auto-resume-windows` marketplace name is
already registered from a different source, the installer removes that registration and adds
this installation in its place. It then asks Codex to upgrade that one marketplace by name,
`codex plugin marketplace upgrade codex-auto-resume-windows`, rather than the form without a
name, which, by Codex's own help text, refreshes every Git marketplace you have configured. For
the local marketplace it has just registered, the named upgrade does nothing; it
fetches anything only if an earlier Git registration of that name survived the
repointing. The named form is on the main branch and ships in the release after v0.5.7; the
installer in v0.5.7 and earlier runs the form without a name.

## Long paths

The plugin cache path plus the script path can exceed the Windows `MAX_PATH` limit of 260
characters if `CODEX_HOME` is itself deeply nested. The default location is short and unaffected.

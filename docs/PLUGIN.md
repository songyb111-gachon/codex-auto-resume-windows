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
waiting with its recovery attempts and its no-progress count reset to zero. It does not switch
recovery for that conversation back on: where that conversation is off, the reply says so and
nothing will run until it is switched on, and it can be used at most three times for one task.
Every gate still runs. That is a property of the surface, not a rule the model is asked to
follow: there is no call that retries an unclassified failure, resolves a conversation by
anything but its exact id, resends an uncertain submission or forces a send.

### The tools, and which ones Codex asks about

The table describes the server from v0.6.4. The server runs from the installed release, not from
the plugin you add. An installation on v0.6.3 has the same seventeen tools, but its
`update_settings` does not offer the theme. One on v0.6.0 through v0.6.2 has sixteen tools, without
`preview_recovery_message`, and its `update_settings` offers only the recovery categories, the
limits and the notifications: the language and continuation settings do not exist before
v0.6.3, and neither does a switch for `auth_service_transient`. An installation still on
v0.5.7 or earlier differs from v0.6.0 in six more ways: it has ten tools
rather than sixteen, without `disable_conversation_recovery`, `enable_conversation_recovery`,
`get_recovery_statistics`, `get_recovery_timeline` and `clear_recovery_history`; its
`cancel_recovery` stops recovery for the whole conversation the named interruption belongs to
and switches that conversation off, rather than stopping one interruption and the records that
continue it; pause and resume are one tool, `set_auto_recovery`, marked in neither direction;
of the other tools that change something, only `restore_default_settings` and `cancel_recovery`
are marked; `update_settings` also accepts two advanced settings; and `get_status` also reports
the installation directory. The last two are described below the table.

| Tool | What it does | Marked destructive |
| --- | --- | --- |
| `open_settings` | Shows the settings panel. Opening it changes nothing. | no |
| `get_status` | Whether recovery is on, whether the watcher is running, counts by state, the version and the current settings. | no |
| `list_pending` | Pending recoveries with their interruption ids, conversation ids, stored state, public code, reason, overlays and attempt counts. With `include_finished: true`, the recoveries that have already finished as well. | no |
| `get_recovery_statistics` | How many interruptions were detected, how many continuations were sent, how they ended, and the median waits, over the last `days` days or all of it. Counts only; no ids. | no |
| `get_recovery_timeline` | One interruption and everything that continued it, as codes and times. | no |
| `preview_recovery_message` | The exact text the watcher would send for one recoverable kind of interruption, under the current settings or with an unsaved Interface language, Continuation language, Message style or Custom mode. Built by the same function the watcher sends with. Accepts no Custom text; saves nothing and sends nothing. | no |
| `pause_auto_recovery` | Global pause. The watcher sends nothing while paused. A continuation already waiting in Codex's queue is withdrawn when the watcher reaches it; a withdrawal the watcher can confirm returns that recovery to its waiting state with its attempt back, so resuming picks it up again. Only a withdrawal that cannot be confirmed is marked `submission_unknown` and never resent, though Codex's queue may still hold it; if Codex delivers it first, the engine follows the turn that continuation started and records what that turn actually did. | no |
| `retry_now` | Moves a waiting record's next check to now. | no |
| `disable_conversation_recovery` | Switches recovery off for one exact conversation, its later interruptions included, and cancels what it has waiting. | no |
| `resume_auto_recovery` | Undoes a global pause. | yes |
| `enable_conversation_recovery` | Switches recovery back on for one exact conversation. Nothing is sent; every check still applies. | yes |
| `update_settings` | Changes user-facing settings: the Interface language, the recovery categories, the limits, the notifications, the continuation message's language, style and Custom mode, and the theme. Not the Custom message text itself (below). | yes |
| `restore_default_settings` | Puts every setting back to its recommended value. | yes |
| `cancel_recovery` | Stops the named interruption and every record that continues it. One that was never sent is cancelled outright; one that may already be in Codex is marked, and the watcher takes back whatever is still queued - a turn already running is not stopped. The conversation itself stays switched on. | yes |
| `reset_recovery_budget` | Returns an exhausted record to waiting, as above. | yes |
| `clear_recovery_history` | Hides finished recoveries from the history. Deletes nothing and cancels nothing; a recovery that may still change stays visible, and hidden rows still count for every safety check. | yes |
| `start_watcher` | Starts the watcher the installer starts, if it is not running. | yes |

"Marked destructive" is MCP's `destructiveHint` annotation, which the server declares for
each tool. It requests approval; Codex and your approval settings decide whether to ask.
Actual Codex approval behavior has not been observed for this release; the tests check the
annotations only. A tool that can add automation is marked.
Turning recovery back on - globally, or for one conversation - re-arming a record that had
stopped, changing or restoring settings (either can switch a recovery category back on) and
starting a watcher you stopped can all add automation. `cancel_recovery` is marked for the
opposite reason: no tool restarts a record it cancelled, so for that interruption and the
records that continue it the stop is one-way. Switching a whole conversation off is a separate
action, `disable_conversation_recovery`, and the switch itself is reversible -
`enable_conversation_recovery` turns that conversation back on, as does the command line's
`enable` with that conversation's id - though the records it cancelled stay cancelled.
`clear_recovery_history` is marked for the same one-way reason: it deletes nothing and cancels
nothing, but nothing puts a hidden row back in the history. Pause, `retry_now` and the
read-only tools are not marked: a pause only reduces automation: a continuation already
waiting in Codex's queue is withdrawn, and a withdrawal the watcher can confirm returns that
recovery to waiting with its attempt back, so resuming picks it up again - only a withdrawal
it cannot confirm, or a pause over a submission that was already uncertain, is final, and
neither is ever sent again; `retry_now`
cannot make anything recoverable that was not already pending. In v0.5.7 and earlier, pause and
resume are one tool, `set_auto_recovery`, not marked destructive in either direction, so
the annotation does not request approval to resume. A host that permits the call without
asking can let a prompt-injected turn reverse a pause.

From v0.6.0, `update_settings` neither offers nor accepts the advanced settings - `codex_exe`,
which engine binary to run, and `detection_lookback_hours` - which the settings window and the
panel do not show either; a client that sends them anyway is refused. And `get_status` does not
report the installation directory, whose path contains your Windows user name, though the
settings it returns do include `codex_exe`, which is empty unless an engine path has been set,
by hand or through `update_settings` in v0.5.7 or earlier. Both changes ship in v0.6.0. In
v0.5.7 and earlier, `update_settings` accepts those two settings as well and is not marked
destructive, so it does not request approval through that annotation, and `get_status`
reports the installation directory as `home`. Nor does `update_settings` offer the two
preferences that belong to Windows, the notification-area icon (`show_tray`) and Reduce motion
(`reduce_motion`), which the panel does not show either. From v0.6.4 it does offer the theme,
the one appearance setting the panel shows.

**Custom message text cannot be written from Codex.** `update_settings` offers
`custom_message_mode` - one message for every interruption, or one per kind - but neither
`custom_message` nor any `custom_message_<category>`, and a client that sends one anyway is
refused; `preview_recovery_message` accepts only the four choices named in its row. The reason
is what the text is for. The watcher later sends it into your conversations, on your behalf,
when nobody is watching, so a model that had been talked into changing it by a page it read
would turn one injected instruction into a standing one, delivered at every later interruption.
The text is therefore written in the Windows Dashboard, by the person it will speak for. What
Codex can change - the language and the style - only chooses among texts this product ships or
you wrote.

What a tool returns becomes part of the Codex conversation it was called from, and should be
treated as sent to OpenAI like any tool output: the status summary (in v0.5.7 and earlier,
with the installation directory), the settings, and for `list_pending` and `open_settings` the conversation and
interruption ids with their states, codes and counts, and for `get_recovery_timeline` one
chain's interruption ids with its event codes and times; `get_recovery_statistics` returns counts and times and no ids at all. The settings that
`get_status`, `open_settings`, `update_settings` and `restore_default_settings` return include
any Custom message text you wrote in the Dashboard, and `preview_recovery_message` returns the
text that would be sent, which under the Custom style is that text. No tool returns
a conversation's title or content. The same holds for command output the skill asks Codex to read back - `status`,
`pending`, `doctor`, `logs` - which also includes local paths and log lines.

### The settings panel

`open_settings` returns the panel as a `ui://` resource, which Codex renders beneath the tool
result. It is one self-contained page - no script, stylesheet or font from anywhere else - and
it draws itself from the settings schema the tool returns, so it shows the fields the settings
module defines rather than a list of its own. It follows Codex's light or dark theme unless the
Theme setting chooses one, and Codex's reduced-motion preference, in the visual language the
Dashboard and the popup share ([BRAND.md](BRAND.md)). Top to bottom:

* **The state**: what the watcher is doing, in a word beside a halo - monitoring, waiting,
  recovering, paused, or needing you when the watcher is not running, which is the only case
  that offers **Start watcher**.
* **Waiting to resume**, when anything is: up to eight tasks, each with its code, reason, next
  check and attempts, and an **Auto-resume** switch for that task's conversation. The switch
  calls `disable_conversation_recovery` or `enable_conversation_recovery` with the exact thread
  id the row was drawn from, and the row changes only when the tool answers for that same
  thread. Turning it off is confirmed in the panel first, because it cancels what that
  conversation has waiting; turning it back on adds automation, so Codex may ask. The switch
  in the Dashboard and the popup also checks the exact interruption before acting; no MCP tool
  takes both ids, so the panel's switch names the conversation alone.
* **General**: the Interface language. Once a new one is saved, the panel speaks it at once.
* **Automatic recovery**: pause or resume, which acts at once, a check box for each recovery
  category, and the limits, folded away.
* **Notifications**, folded away: the switch for notifications, and a check box for each event.
* **Continuation message**: the continuation language and the message style. Under *Custom* it
  shows which stored message is used and what it says, read-only, with a note that Custom
  messages are written in the Windows Dashboard. The page has no text field for them, and
  neither its Save request nor its Preview request can carry one.
* **Preview**: the exact text for a chosen kind of interruption, from
  `preview_recovery_message`, following the language and style chosen but not yet saved. The
  page never assembles a continuation of its own.
* **Appearance**: the theme - Use system setting, Light or Dark. Once a new one is saved, the
  panel draws itself in it at once.
* **Save**, for the settings above that wait for it. It sends the Interface language and the
  theme only when they were changed in the panel, so a save cannot put back one changed elsewhere.

Where the host gives the page no way to call tools, it is a read-only summary and says so.

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
| **Where from** | One URL shape, built from `scripts/release.json` and a version this script chose. No parameter reaches a URL. An ordinary run fetches the version in this plugin's own manifest and the `.sha256` published beside it, and nothing else; it fetches the `.sha256` only when there is no pinned digest to check against. `-Update` is the one exception and the version it fetches is not an input either: it is three integers read out of a redirect under this exact owner and repository, and every check below still applies. |
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

Archives v0.5.0 through v0.5.7 were built by the earlier single-job
release workflow, which referred to its Actions by floating tags, and its executables are not
reproducible: each carries a build time and a random module id, and no rebuild of them will
match. From v0.6.0 the release workflow builds and publishes in separate jobs, pins every
Action to a commit, and removes what made the executables differ from one build to the next;
the checkout also gives every text file CRLF line endings whatever the machine's Git settings,
because the archive's bytes include them. That ships in v0.6.0, which is the first built that
way. The in-box C# compiler stamps a build time and a fresh module version id into each
executable, so the build normalises both - a fixed PE timestamp, and a module id derived from
the content - and the workflow compiles the two executables twice and refuses to publish if
they differ. When that normalisation was added, two local builds and a build from a separate
clone produced byte-identical executables; the workflow's double compile repeats that check on
every release build. That measurement covers the executables, not the whole archive, and
whether GitHub's runner produces the same bytes as a local build has not been verified, so the
pin is still taken from the published file rather than from a rebuild. [VERIFY.md](VERIFY.md)
has the rebuild procedure, and what a match or a mismatch does and does not show.

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
| `codex plugin add`, then *set up auto resume* | The skill has Codex run `bootstrap.ps1`; the bootstrap downloads and verifies the matching release and runs the same installer. Identical result. From v0.6.0 the skill tells Codex to run `bootstrap.ps1` by its absolute path inside the plugin, and never as a relative `scripts/bootstrap.ps1`; the skill in v0.5.2 through v0.5.7 gives the relative form. Codex follows the skill of the plugin you added: one added from the GitHub marketplace is a copy of `main` as it was when the marketplace was added or last upgraded, so it gives the absolute path only if that was after the change reached main (2026-09-11) - an older copy gives the relative form until the marketplace is upgraded with `codex plugin marketplace upgrade codex-auto-resume-windows` - while the copy the installer registers from an installed release carries that release's skill. |
| Either of the above with something already installed | The installer first asks a running watcher to stop through its stop event and waits up to a minute. It does not kill it: if the old watcher is still running when the wait ends, the upgrade completes and says so, and the new version takes over once the old watcher has exited and a watcher is started again (`start_watcher`, the settings window's Start watcher, or the next sign-in). Then it moves the old payload aside, copies, and rolls back on failure. Settings, pending recoveries, retry budgets and logs are kept. Setup runs with `--keep-state` whenever there is already an installation to repair: the installer adds that switch when the program directory `app\` is present, and the bootstrap adds it on the repair described next. `--keep-state` does not run the engine's `enable`, and it does not create a sign-in entry - it re-registers one only when the entry already registered is this installation's, which still repairs a stale path after the runtime moves. So a global pause survives an upgrade, a reinstall over an existing installation and that repair, and so does a sign-in start you had turned off. A first install is the exception, and has to be: with no `app\` directory there is no decision to preserve, so setup switches automatic recovery on and registers the sign-in start unless it is run with `--no-startup` (the bootstrap's `-NoStartup`, the installer's `-SkipStartup`). Unless it is run with `-Force`, the bootstrap skips the download entirely when the installed version already matches, and re-runs setup to repair its Windows registrations - the sign-in entry, the notification button's handler and, while notifications are on, the notification sender identity and the Start Menu entry - and start the watcher if it is not running. That repair does not re-register the plugin or its marketplace in Codex; only the installer does that. |
| Ask for anything else with nothing installed | `setup` refuses and prints the command that installs it. Nothing is registered, so there is no half-installation for a later run to mistake for a real one. |
| `codex plugin remove` | Removes the skill, the tools and the panel. The watcher keeps running, from the installed application rather than from the cache copy that just disappeared. `uninstall` is what removes it. |
| Two installers at once | The second is refused by a named lock. |
| A source checkout beside an installation | Refused, as before: `setup` stops when the registered sign-in entry belongs to a different home, because two watchers could each resume the same interruption. |

## Runtime state lives outside the plugin

The plugin cache path contains the version, so it changes on every update. Three
consequences are designed around:

- **State must not live in the plugin.** Pending interruptions, settings and logs live in
`%USERPROFILE%\.codex-auto-resume\` by default. Updating or removing the plugin does not touch
them. - **Autostart must not point into the plugin.** Setup copies `watcher_launcher.py` to
that same stable directory and registers *that*, so an update needs no re-registration. - **The
installed application is the engine**, not the plugin cache copy. The launcher resolves the
installation's `app` directory first - under the home `runtime.json` records,
`%USERPROFILE%\.codex-auto-resume\app` by default - and, for a plugin installation, falls back
to the cache only when that directory holds no usable application. It used to prefer the newest
cache copy by modification time, which meant installing a newer plugin from a marketplace
silently swapped the engine underneath an older installation while the settings window still
talked to the old one. Updating a plugin should update the skills and the manifest; replacing
the engine is what the installer is for. From v0.6.0 the cache fallback considers only copies
from this product's own marketplace, `codex-auto-resume-windows`, and skips a same-named plugin
from another marketplace; that ships in v0.6.0, and the launcher in v0.5.7 and earlier takes
the newest same-named copy from any marketplace. After the cache, the launcher tries the
directory setup last ran from, which `runtime.json` records; the installer runs setup from the
installed application, so that is normally the same directory.

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

The product's own interface - the Dashboard, the notification-area popup and its menu, Windows
notifications, the settings panel in Codex and the plugin layer's messages - ships in nine
languages: English, 한국어, 日本語, 简体中文, 繁體中文, Español, Deutsch, Français and Português
(Brasil). Until v0.6.3 it was English or Korean.

**Which one.** The **Interface language** setting decides (General, in the Dashboard's Settings
and in the panel). Its default, *System*, follows Windows, read from the same source the ChatGPT
desktop app uses for its own display language: Electron's `app.getPreferredSystemLanguages()`,
which on Windows is `GetUserPreferredUILanguages`. Falling back, it reads `LC_ALL` /
`LC_MESSAGES` / `LANG`, and `CODEX_AUTO_RESUME_LANG` replaces all of those. Only the first
language counts: if this product does not ship it, the answer is English, never a language
further down the list and never a guess. An explicit choice in the setting wins over Windows
and over `CODEX_AUTO_RESUME_LANG` alike, which only decides while the setting is *System*, and it
survives restarts, repairs and updates. One function, `l10n.normalize`, maps a tag to a
catalog: Chinese by script or region (`Hant`, `TW`, `HK` and `MO` are traditional, anything
else simplified), and `pt` and `pt-PT` to Brazilian Portuguese. No language is inferred from an
IP address, a time zone, a user name, a country or a keyboard layout.

**The continuation message is localized too**, in its own setting, **Continuation language**,
which by default follows the interface: the language you read and the language you want Codex
addressed in are not always the same one. A Custom message is sent exactly as you typed it, in
whatever language that was.

**What is not translated.** The output of the `auto_resume.py` command line; the MCP tools'
text replies - the one-line summary each tool returns and the sentence a refusal carries - which
are English (the panel says a refusal in your language from the code that travels beside the
sentence); and the Dashboard's built-in English fallbacks, which appear only for a key a catalog
does not have.

**Where the words live.** One JSON catalog per language, in `src/codex_auto_resume/locales/`.
English is the source, and every other catalog is a layer over it, so a key a translation has not
reached yet shows in English rather than as a blank or an error; the loader refuses a catalog
with a duplicated key. `l10n.py` and `interface.py` read their strings from these catalogs
rather than keeping tables of their own. Each translation is tracked against the English it was
made from: `build/l10n.py` records, for every translated key, a digest of the English sentence
in `build/l10n/<locale>.basis.json`, so a sentence changed in English shows as stale in every
language, and the tests fail until someone has looked at it again. The basis files live under
`build/`, which is not part of a release. Nothing is fetched from the network - no translation
service, no runtime download - and there is no i18n framework and no new dependency.

## The usage-limit checkbox: not possible through any official API

The goal was to add exactly one line to the usage-limit notice Codex already shows:

> ☑ Automatically resume this task after the reset

**This cannot be done through the official Codex plugin API.** It is not implemented, and nothing
pretending to be it was built in its place. Re-checked from scratch for v0.5, and again for
v0.6.3; the answer has not changed.

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

For v0.6.3 the list was checked again - the validator's accepted fields, `apps` entries, the
conversation-scoped MCP App views, the banner's compiled `codex.upsellBanner.*` messages with
their closed set of calls to action, `pluginSlots` and the hook events - and it reads the same:
nothing fires on a usage limit, and plugin validation still rejects `hooks`. One more surface was
looked at: `openai/events/subscribe` exists, but it requires a trusted connector scope that a
plugin does not have.

### Where the control is instead, in order of how close it gets

Every placement that was built binds to the exact interruption and the exact conversation it is
shown beside, changes policy only - whether the watcher may resume that task - and never sends
anything. The watcher still decides, checks everything again, and is still the only thing that
sends.

**A — a real control inside Codex's notice. Impossible.** The banner is assembled from compiled
`react-intl` message ids inside the Electron bundle, with no id, slot, prop or plugin hook
anywhere near it, so the only way in is to inject into the desktop app, which this project does
not do.

**B — a Codex-native form at the moment of the interruption. Available in principle, not
shipped.** An MCP server can call `elicitation/create`, and the desktop app renders it: a boolean
property becomes a real checkbox, and the response is `accept` / `decline` / `cancel`. In the
desktop app's JavaScript as inspected on 2026-09-07, each request is filed under the turn that
raised it (its `turnId`); which Codex version that bundle belongs to was not recorded. It is
still not shipped. To
reach a person at the moment of the interruption, the server would have to push a form into
whatever conversation happens to be open, about a different conversation that failed, unasked;
it only arrives while Codex is open; and it sits behind a feature gate
(`features.tool_call_mcp_elicitation`) that can be off, in which case it silently does nothing.
Building an interruption whose delivery cannot be relied on, into a place the user did not ask
for it, is worse than not building it.

**C — a Windows notification. Shipped, and the one that actually arrives.** The watcher raises it
the moment the interruption is recorded, whether or not Codex is open, with **Don't resume** (or
**Don't retry**, for a transient failure) for that exact interruption, resuming as the default,
and **Open Dashboard**, which opens the Pending page and can do nothing else.

**D — the notification-area popup.** A single click on the watcher's icon opens a compact popup
listing what is waiting; each task has its own switch, *Automatically resume this task when the
limit resets* (or *Automatically retry this task*), bound to that task's interruption and
conversation ids.

**E — the Dashboard's Pending page.** The **Auto-resume** column carries the same switch for every
waiting task, beside **Why it is waiting** and the rest of the task's record.

A click on D or E that reaches a record which has since finished, disappeared, or turned out to
belong to another conversation is refused by the control layer and changes nothing.

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
the local marketplace it has just registered, the named upgrade does nothing; it fetches
anything only if an earlier Git registration of that name survived the repointing. The named
form is new in v0.6.0; the installer in v0.5.7 and earlier runs the form without a name.

## Long paths

The plugin cache path plus the script path can exceed the Windows `MAX_PATH` limit of 260
characters if `CODEX_HOME` is itself deeply nested. The default location is short and unaffected.

## The public Plugin Directory, and why this plugin is not in it

Checked against OpenAI's current submission documentation on 2026-09-12, because the answer
had changed shape since it was last looked at and it is not the answer this project wanted.

A directory listing needs a verified publisher identity and an organisation role with
Apps Management write access; a name, a short and a long description, a logo and a
category; website, support, privacy and terms URLs; the skill bundle; five positive test
cases with fixtures, three negative ones, five starter prompts, release notes; and the
regions it should be available in. All of that is preparable, and most of it exists
already in this repository.

One requirement is not preparable, and it is the one that decides this:

> If your MCP server runs locally, deploy it to a public HTTPS URL. If you can't, reach
> out to your OpenAI contact for local MCP support.

This product's MCP server is a local executable, on purpose. Making it a public HTTPS
endpoint would mean this project operating a server that receives people's recovery state,
which is the single thing `PRIVACY.md` says it does not do and will not do. So there are
three routes and only one of them is this product:

1. **Submit as skills-only**, dropping the MCP server from the listing. That removes the
   panel inside Codex and the typed control tools - a different product with the same name,
   and the one a person would install from the directory would be the lesser one.
2. **Ask OpenAI about local MCP support**, which the documentation names as the route for
   exactly this case. That is a conversation a person has, not something a release can do.
3. **Stay off the directory** and be installed the way it is installed today, from this
   repository's marketplace.

Until (2) has an answer, (3) is what happens, and this section is here so that is a
recorded decision rather than a thing nobody got round to.

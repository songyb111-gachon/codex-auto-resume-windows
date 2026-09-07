# The Codex plugin layer

This project keeps the recovery engine small, local, conservative and fail-closed, and uses
Codex itself as the installation and control interface instead of building a second
management application.

The plugin is a **thin front end**. It installs no second engine, holds no recovery logic, and
never queues a message to a thread. Everything it does goes through the same command-line
interface a manual installation uses.

```
Codex UI  ->  plugin skill  ->  existing CLI  ->  small safe watcher
```

## Layout

The repository root *is* the plugin root. There is exactly one copy of `src/`.

| Path | Purpose |
| --- | --- |
| `.agents/plugins/marketplace.json` | Marketplace index; one entry whose `source.path` is `"."`. |
| `.codex-plugin/plugin.json` | Plugin manifest. Declares `skills` and the card's artwork; nothing else executable. |
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

The manifest in this repository declares only `skills`; the release build adds
`mcpServers` to the copy it ships. That split is deliberate. The server runs on the
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
recoveries, settings, pause, cancel - and so those actions mean the same thing they mean
everywhere else, because every one of them calls the same validated control layer the
command line and the settings window call.

It is a front end and nothing more. No tool detects a failure, schedules an attempt, reserves
an interruption or sends a continuation; the watcher stays the only thing that recovers, and it
keeps running when the server is not. That is a property of the surface, not a rule the model is
asked to follow: there is no call that retries an unclassified failure, resolves a conversation
by anything but its exact id, resends an uncertain submission or forces a send.

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
| **Where from** | One URL shape, built from `scripts/release.json` and the version in this plugin's own manifest. No "latest", no parameter that reaches a URL: a v0.5.2 plugin can fetch the v0.5.2 archive and nothing else. |
| **Over what** | HTTPS, TLS 1.2 minimum, and the *final* response URI has to be `github.com` or `*.githubusercontent.com`, because a release download redirects to GitHub's object storage and nowhere else. |
| **Checked how** | SHA-256 against the digest pinned in `release.json` when there is one, and otherwise against the `.sha256` published beside the archive. Then that the archive contains everything the release is defined to contain, that its manifest declares this product at this version, and that no entry escapes extraction. |
| **Then** | Extract to a fresh temporary directory and run `install/install.ps1` from it. Nothing from the archive runs before all of the above passes. |
| **Never** | Administrator rights, any change to a Windows security setting, any execution-policy change beyond its own process, and nothing downloaded is ever passed to a shell. Any failure deletes the download and stops. |

**About the two digest cases**, because the difference is worth stating rather than
blurring. A pinned digest is a commitment made in the repository: the file has to be
exactly those bytes. The sidecar is served from the same origin as the archive, so
checking one against the other is trust-on-first-use over TLS to GitHub — it proves the
download is intact and is a coherent build of this exact version, not that GitHub served
what the author intended. The script prints which of the two it used. A version's digest
is null at the moment it is tagged and filled in after publication, because the archive is
not reproducible: the in-box C# compiler stamps a fresh module version GUID into every
build, so the digest can only come from the published file.

Verified by feeding it a file that is not an archive, a genuine archive declaring a
different version, and a correct archive against a deliberately wrong pinned digest. All
three were refused with nothing installed.

## Runtime state lives outside the plugin

The plugin cache path contains the version, so it changes on every update. Three
consequences are designed around:

- **State must not live in the plugin.** Pending interruptions, settings and logs live in
  `%USERPROFILE%\.codex-auto-resume\`. Updating or removing the plugin never destroys them.
- **Autostart must not point into the plugin.** Setup copies `watcher_launcher.py` to that same
  stable directory and registers *that*, so an update needs no re-registration.
- **The installed application is the engine**, not the plugin cache copy. The launcher
  resolves `%USERPROFILE%\.codex-auto-resume\app` first and only falls back to the cache
  when there is no installation. It used to prefer the newest cache copy by modification
  time, which meant installing a newer plugin from a marketplace silently swapped the
  engine underneath an older installation while the settings window still talked to the
  old one. Updating a plugin should update the skills and the manifest; replacing the
  engine is what the installer is for.

Tested: after replacing `0.2.0` with `0.2.1+codex.local-test` and deleting the old directory,
the launcher resolved the new one and the state was untouched.

## `codex plugin remove` vs `uninstall`

They are different operations and neither implies the other.

| | `codex plugin remove` | `plugin_setup.py uninstall` |
| --- | --- | --- |
| Removes the skill from Codex | yes | no |
| Stops a running watcher | no | yes |
| Removes sign-in autostart | no | yes |
| Deletes pending state and logs | no | yes |

There is no plugin uninstall hook to attach to, so removing the plugin cannot clean up on its
own. It does not leave a watcher running forever either: with the plugin gone the launcher finds
no engine, logs one line and exits, so autostart stops at the next sign-in. To remove everything
at once, run `uninstall` first, then `codex plugin remove`.

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

English is the default. Korean is used only when Korean is the **most preferred** UI language.

Detection reads the same source the ChatGPT desktop app uses for its own display language:
Electron's `app.getPreferredSystemLanguages()`, which on Windows is `GetUserPreferredUILanguages`.
Falling back, it reads `LC_ALL` / `LC_MESSAGES` / `LANG`, and `CODEX_AUTO_RESUME_LANG` overrides
everything. No language is inferred from an IP address, a time zone, a user name, a country or a
keyboard layout. An unavailable probe means English, never a guess.

Strings live in one small table in `src/codex_auto_resume/messages.py`. No i18n framework and no
new dependency.

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

If Codex later exposes an official inline control surface for this state, it is a small change:
one checkbox, defaulting to on, mapped to the existing per-thread cancel. No panel, no card, no
popup, no tray.

## Local installs copy the whole working tree

Installing from a local path copies every file in the directory, including files Git ignores
(`config/`, `logs/`, build scratch). Installing from GitHub clones the repository, so only
tracked files ship. Prefer the GitHub source unless you are developing the plugin.

## Long paths

The plugin cache path plus the script path can exceed the Windows `MAX_PATH` limit of 260
characters if `CODEX_HOME` is itself deeply nested. The default location is short and unaffected.

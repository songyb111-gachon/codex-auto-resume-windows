# Privacy

Codex Auto Resume runs on your machine. It has no server, no account and no telemetry, and
the watcher makes no outbound network request of its own.

There is one exception, and it is worth stating up front rather than in a footnote:
**installing or updating it from the Codex plugin downloads the release from GitHub.** The
sections below separate the two, because they are genuinely different.

## What it sends to the developer

Nothing. There is no telemetry, no analytics, no crash reporting and no automatic update
check — no endpoint of any kind exists to receive them.

Specifically, none of the following ever leaves your computer:

- your prompts, or any conversation content;
- assistant replies;
- tool input or tool output;
- file or repository contents;
- account identifiers, email addresses or subscription details;
- credentials, API keys, tokens or cookies;
- raw error bodies from the provider;
- conversation titles, project names or working directory paths;
- conversation UUIDs, recovery counts or any other statistic about what it did.

This is a property of the code rather than a policy: nothing under `src/` or `scripts/*.py`
imports a networking module, so the watcher cannot open a connection even by accident.

## Installing it

The Codex plugin is the recommended way in, and it is not self-contained: the watcher, the
settings window and the Windows runtime arrive in the release archive. So when you ask Codex
to set up auto resume, `scripts/bootstrap.ps1` downloads that archive.

- It contacts **github.com** and GitHub's release storage, over HTTPS, and nothing else.
- It downloads exactly two things: this version's release archive, and — only when the
  plugin carries no pinned checksum for that version — the `.sha256` published beside it.
- The URL is built from constants in the repository and the plugin's own version. There is
  no "latest", and nothing you type becomes part of it.
- It uploads nothing. No prompt, conversation, account identifier, machine identifier or
  recovery data is attached to the request; there is nowhere for it to go.

GitHub therefore sees an ordinary download request — as it would for any download — and
counts it in the repository's public download total. That is the one respect in which
installing this tool is not invisible, and no wording here can make it otherwise. The
release-archive route avoids it entirely: once you have the ZIP, `Install.cmd` uses no
network at all.

Nothing about **using** the tool involves GitHub. It never checks for updates.

## What it reads

It reads Codex's own local state, read-only, to notice that a task was interrupted:

- lifecycle records — whether a turn failed, and the structured error variant Codex recorded;
- the exact conversation UUID and turn ordinal;
- rate-limit and usage snapshots, for the reset timestamp;
- `threads.name`, the project name and the working directory's last path segment, used only as
  labels in a notification.

It deliberately does not read the fields that hold your prompt. On the current Codex schema
`title`, `preview` and `first_user_message` contain the raw first message, so they are never
read; display labels come from `threads.name` only. Identity always comes from the UUID, never
from a label.

It never writes to Codex's files, never takes a lock on them, and never touches credential
storage.

## What it runs

Every process it starts for recovery runs on your machine, against the Codex installation
already there:

- the official `codex` binary — `codex queue` to continue the conversation, and
  `codex app-server --stdio` to read your usage and to remove a queued item it put there
  itself;
- short `codex --version` and `codex queue --help` probes, to confirm it is driving the
  interface it expects;
- Windows PowerShell, to ask the Restart Manager which process owns a Codex file and to
  raise a notification.

Model requests are made by the official Codex binary, already signed in, exactly as they
would be if you had typed the message yourself.

On every one of those invocations it also turns Codex's own reporting off: analytics
disabled, every OpenTelemetry exporter set to none, prompt logging off, and the ChatGPT
base URL pinned to the official one so a stray local configuration cannot send a
continuation somewhere else. Those are settings for the subprocess this tool starts, not
for your own Codex sessions, which are unaffected.

## What it stores, and where

Everything it records about your work lives under `%USERPROFILE%\.codex-auto-resume\`:

- `config/state.sqlite` — pending recoveries: conversation UUID, turn ordinal, timestamps,
  failure category, attempt counts, state;
- `config/settings.json` — your settings;
- `logs/` — what the watcher did, by state name and conversation UUID.

The logs record state transitions and identifiers, not content. No prompt text, assistant
output, tool output or error body is written to them.

Outside that directory it registers ordinary per-user Windows plumbing, none of it needing
administrator rights and none of it containing anything about your conversations: a Start
Menu shortcut, the sign-in autostart value (unless you skip it), the notification sender
identity Windows requires before it will draw a toast at all, and the handler for the
notification button's `codex-auto-resume:` link. Uninstalling removes them.

Uninstalling keeps the state directory by default so a reinstall does not lose pending
recoveries; `Uninstall.cmd` with the purge option removes it. You can delete it yourself at
any time.

## Notifications

Windows notifications are raised locally through the operating system's own notification API.
They show a display label, a local time and the conversation UUID — never prompt text, error
text or account data. They are not routed through any service.

## Third parties

**GitHub, when you install or update from the plugin** — the download described above, and
nothing else. It is subject to GitHub's own privacy practices, as any download would be.

Apart from that there are none. What runs is the Python standard library, the interpreter
that ships in the release archive, and two small Windows programs built from this repository
— the settings window and the MCP launcher. It integrates only with the Codex installation
already on your machine.

## Future versions

If any form of opt-in reporting is ever added, it will be off by default, it will say exactly
what it would send before sending anything, and this document will describe it before the
release that contains it. Nothing of the kind exists today.

## Questions

Open an issue, or see [SECURITY.md](SECURITY.md) for the security reporting process.

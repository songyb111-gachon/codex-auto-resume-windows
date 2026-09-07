# Privacy

Codex Auto Resume runs entirely on your machine. It has no server, no account, and no network
calls of its own.

## What it sends to the developer

Nothing.

There is no telemetry, no analytics, no crash reporting and no update check. Specifically, none
of the following ever leaves your computer:

- your prompts, or any conversation content;
- assistant replies;
- tool input or tool output;
- file or repository contents;
- account identifiers, email addresses or subscription details;
- credentials, API keys, tokens or cookies;
- raw error bodies from the provider;
- conversation titles, project names or working directory paths;
- the fact that you installed it at all.

This is a property of the code rather than a policy: the tool makes no outbound requests. The
only process it launches for recovery is the official `codex queue` command, on your machine,
against your own local Codex installation.

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

## What it stores, and where

Everything it keeps lives under `%USERPROFILE%\.codex-auto-resume\`:

- `config/state.sqlite` — pending recoveries: conversation UUID, turn ordinal, timestamps,
  failure category, attempt counts, state;
- `config/settings.json` — your settings;
- `logs/` — what the watcher did, by state name and conversation UUID.

The logs record state transitions and identifiers, not content. No prompt text, assistant output,
tool output or error body is written to them.

Uninstalling keeps that directory by default so a reinstall does not lose pending recoveries;
`Uninstall.cmd` with the purge option removes it. You can delete it yourself at any time.

## Notifications

Windows notifications are raised locally through the operating system's own notification API.
They show a display label, a local time and the conversation UUID — never prompt text, error
text or account data. They are not routed through any service.

## Third parties

None. The tool has no dependencies beyond the Python standard library and the interpreter that
ships in the release archive, and it integrates only with the Codex installation already on your
machine.

Downloading a release from GitHub is subject to GitHub's own privacy practices, as any download
would be. The tool itself does not contact GitHub.

## Future versions

If any form of opt-in reporting is ever added, it will be off by default, it will say exactly
what it would send before sending anything, and this document will describe it before the
release that contains it. Nothing of the kind exists today.

## Questions

Open an issue, or see [SECURITY.md](SECURITY.md) for the security reporting process.

# Codex Auto Resume

**Automatically resume the exact same Codex task on Windows after a usage limit resets.**

[![tests](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml/badge.svg)](https://github.com/songyb111-gachon/codex-auto-resume-windows/actions/workflows/test.yml)
[![latest release](https://img.shields.io/github/v/release/songyb111-gachon/codex-auto-resume-windows?label=release)](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest)
[![platform: Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)](#install)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![languages: 9](https://img.shields.io/badge/languages-9-0891b2)](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md#languages)

<sub>🇰🇷 <a href="README.ko.md">한국어 README</a> · The app speaks nine languages: English · 한국어 · 日本語 · 简体中文 · 繁體中文 · Español · Deutsch · Français · Português (Brasil)</sub>

Codex stops mid-task and tells you to try again at 6:34 AM. You are asleep at 6:34 AM, and in
the morning the task is exactly where it stopped.

Codex Auto Resume waits out the reset, checks that continuing is genuinely safe, and then
continues **that exact conversation**, by sending one continuation message through the official
`codex queue` command. It also recovers temporary rate limits, network failures, timeouts, server
errors and interrupted streams - but only a failure it can name, and only where it is safe to retry.
**It deliberately does not retry everything.**

This page is the short version. **[The full guide](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md)** has everything else: every
setting, the notification, the command line, the safety model and privacy in full.

|  |  |
| --- | --- |
| **Recovers** | Codex usage limits, and - when Codex records a specific error for them - rate limits (HTTP 429), network failures, timeouts, temporary server errors (5xx) and dropped response streams |
| **Never touches** | user cancellation · permission · approval · content policy · invalid requests · context length · permanent authentication failures · anything unclassified |
| **Identity** | the exact conversation UUID only — never `--last`, never "the most recent one", never a title or a folder name |
| **Configure it** | the Dashboard from the Start Menu, a settings panel inside Codex, or the command line |
| **Languages** | English · 한국어 · 日本語 · 简体中文 · 繁體中文 · Español · Deutsch · Français · Português (Brasil) |
| **Privacy** | no telemetry, no analytics, no automatic update check. Setting it up from Codex downloads the release from GitHub, and *Check for updates* asks GitHub which release is newest only when you press it. The watcher has no network code; the usage check and the resumed turn go to OpenAI through Codex, as Codex's traffic always does |

> **One honest limitation, up front.** Codex has to currently have that conversation open for a
> recovery to be delivered. If the app restarted since, open the conversation once and recovery
> continues on its own. [Why](#please-read-this-limitation-first).

## Install

**Windows 10/11. No Python needed. No administrator rights.**

### From Codex (recommended)

Add the plugin, then ask Codex to **set up auto resume**.

```
codex plugin marketplace add songyb111-gachon/codex-auto-resume-windows
codex plugin add codex-auto-resume@codex-auto-resume-windows
```

The setup script downloads the matching release from this repository over HTTPS, checks its SHA-256
against the digest recorded for that version in
[`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json),
and installs it for your Windows account only.

### From the release archive

1. Download `CodexAutoResume-vX.Y.Z-win-x64.zip` from the
   [latest release](https://github.com/songyb111-gachon/codex-auto-resume-windows/releases/latest).
2. Check it before you extract it, in PowerShell, in the folder you downloaded it to:

   ```powershell
   (Get-FileHash .\CodexAutoResume-vX.Y.Z-win-x64.zip -Algorithm SHA256).Hash
   ```

   The value must match the `.sha256` file published beside the archive and the digest for that
   version in [`scripts/release.json`](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/scripts/release.json).
   [docs/VERIFY.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md) has the full check.
3. Extract it and run `Install.cmd`.

### Either way

Both routes end at the same installation, by default in `%USERPROFILE%\.codex-auto-resume`.
Running either again upgrades or repairs it, and keeps anything already waiting to resume.

## First steps

- There is nothing to set up: the recommended settings are on from the start.
- When a task stops, a notification names it, as a card beside the notification area (or Windows'
  own notification where a card must not show). Doing nothing resumes it,
  **Don't resume** cancels only that one, and **Open Dashboard** shows what is waiting.
- The notification-area icon shows what the watcher is doing; click it to see what is waiting or
  to pause recovery.
- Change anything from **Start Menu → Codex Auto Resume**, or just ask Codex: "show auto resume
  status", "show pending auto resumes", "open auto resume settings", "turn auto resume off".

## What it looks like

The status light breathes wherever it is shown - on the card, in the Dashboard, in the panel inside
Codex and on the notification-area icon - and the pictures below breathe with it.

The notification card, as the product draws it:

<img src="docs/images/notification-card.png" alt="The notification card in the light theme: Codex Auto Resume with a cyan status light and a Usage limit chip, the task example-project, the line Codex usage limit reached. This task will resume at 08:42., the conversation's exact identifier, and the buttons Don't resume and Open Dashboard" width="388">

The panel inside Codex - its own page, rendered from the exact resource the plugin serves to
Codex, rather than a photograph of the Codex window around it:

<img src="docs/images/settings-panel.png" alt="The Codex Auto Resume panel: a status card saying two recoveries are waiting, the two waiting conversations each with an Auto-resume switch, the interface language, the recovered failure categories, Limits and Notifications folded away, the continuation language and message style, and a Preview of the Standard message for a usage limit" width="680">

The Dashboard from the Start Menu, drawn from synthetic sample data (the conversations in these
pictures are examples, not anybody's work):

<img src="docs/images/dashboard-overview.png" alt="The Codex Auto Resume Dashboard overview: automatic recovery on, the watcher running and the Codex engine compatible, two recoveries waiting with the next check in a minute and a half, the last seven days' interruptions, continuations sent, recoveries and success rate, and the four most recently finished recoveries" width="680">

<img src="docs/images/dashboard-pending.png" alt="The Pending page of the Dashboard: two conversations waiting, one for the usage reset and one with a retry scheduled, each with a state chip and an Auto-resume switch, the Why it is waiting checklist for the selected task, and Retry now, Cancel, Timeline, Turn off for this conversation and Cancel all buttons" width="680">

<img src="docs/images/settings-window.png" alt="The Continuation message section of the Dashboard's Settings page: the continuation language, the four message styles with Standard selected, and a Preview of the message sent for a usage limit" width="680">

The notification-area icon, moving:

<img src="docs/images/icon-motion.png" alt="The notification-area icon's motion, drawn from the icon's own frames, on a light taskbar. From the left: watching, whose bright head breathes and then sweeps clockwise along the ring's white stroke and back, at full brightness; recovering, sweeping out and back all the time; needing attention, amber, breathing slowly in its place; failed, red, sweeping out and back twice as quickly as recovering and blinking as it goes; paused, grey and still" width="360">

[The full guide](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md#what-it-looks-like) shows every part in every theme and language.

## Please read this limitation first

This tool can only auto-resume a thread that the Windows ChatGPT/Codex desktop app **currently has
loaded**. After the app restarts, a thread is `notLoaded`, and there is no verified, supported way to
wake an unloaded thread programmatically. Codex may still deliver such a message later, when the
thread next loads. So this tool queues only for a thread it has just confirmed is loaded, and an
unloaded thread is resumed **only after you open that conversation in the app yourself**. It will
not use GUI automation, will not force the conversation open, and will not queue a message on the
off chance. [The full guide](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md#please-read-this-limitation-first) has the measurement
behind it.

## Safety and privacy

It resumes only the exact conversation that stopped, by its UUID, and only for a failure it can name;
anything unclassified is left alone, and whenever it cannot be sure, it waits rather than sends. It
reads Codex's own state read-only, and never resends a message that may already have been delivered.
The watcher itself has no network code and nothing is sent to this project: the usage check and the
resumed turn go to OpenAI through Codex, and setting it up from Codex downloads the release from
GitHub. [PRIVACY.md](PRIVACY.md) says what is read, stored and sent, and [SECURITY.md](docs/SECURITY.md)
gives the threat model and how to report a vulnerability.

## Requirements

- Windows 10/11 and the official Windows ChatGPT/Codex desktop app, running.
- No Python for either install route; the installation brings its own runtime. Python 3.12 or newer
  is needed only to run it from a source checkout.

## Uninstall

Run `Uninstall.cmd` from a release archive, or ask Codex to uninstall auto resume. By default your
settings and pending recoveries are kept, so reinstalling picks them up; `Uninstall.cmd -Purge`
deletes them too. It removes only what it can prove is its own: directories it can show it owns (by
its provenance marker), and Windows registrations that belong to this installation.

## Learn more

| | |
| --- | --- |
| **[The full guide](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/GUIDE.md)** | Everything above in full, and every setting, the notification, the command line, the safety model, privacy and testing. |
| [docs/VERIFY.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/VERIFY.md) | How to check a downloaded archive is the one this project published, and how to rebuild a release. |
| [docs/FEATURE_MATRIX.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/FEATURE_MATRIX.md) | Every capability this product claims, beside the evidence it has actually earned. |
| [docs/PLUGIN.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PLUGIN.md) | The Codex plugin layer: what setup fetches and checks, updates and removal. |
| [docs/COMPARISON.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/COMPARISON.md) | Other projects in this space, and what each does better than this one. |
| [docs/ROADMAP.md](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/ROADMAP.md) | Where the project is heading, release by release: a planned direction, not a promise. |
| [PRIVACY.md](PRIVACY.md) | What is read, what is stored, and what is sent anywhere. |
| [SECURITY.md](docs/SECURITY.md) | The threat model and how to report a vulnerability. |
| [SUPPORT.md](docs/SUPPORT.md) | Where to report each kind of problem, and what not to paste into a public issue. |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | Tests, the release build, and the safety properties a change has to keep. |
| [codex-compat-reporter](https://github.com/songyb111-gachon/codex-compat-reporter) | A separate tool you can run to report how this product behaved on your machine, with your Codex version. It writes one file of counts, states and times - no conversation text, no identifiers, no paths - which you read before you send it. Such a report is counted under **Reported**, a grade of its own that never raises a version to verified or checked. |

## Credits and license

Built by **Youngbin Song** with the assistance of two AI development tools, OpenAI Codex and
Anthropic Claude Code; [CONTRIBUTORS.md](CONTRIBUTORS.md) has the full breakdown.

MIT. See [LICENSE](LICENSE).

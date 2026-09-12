# Why this project stays small

There is a larger, more ambitious project in this space:
[`sybxxx/codex-auto-retry`](https://github.com/sybxxx/codex-auto-retry). It is worth reading.
Several ideas here were shaped by studying it.

Reviewed again for v0.5.0 against its current state: `d25fda6`, release **v0.7.9**, last pushed
2026-09-02 — unchanged since the previous review, so nothing new arrived to reconsider. What did
change is this project: it now has an MCP server and a settings window, and two entries below
moved from *rejected* to *adapted* because of it. Saying so is the point of keeping this file.

Not re-reviewed for v0.5.2: that release changed how the product is installed and what it
looks like, and nothing in it came from reading another project. Saying that is cheaper than
implying a review that did not happen.

Not re-reviewed for the release after v0.5.7 either, and again nothing in it came from
reading another project. What changed is this project: the Start Menu window became a
Dashboard and the watcher grew a notification-area icon, which moves two more entries below
— a tray icon out of *rejected*, a live countdown out of *deferred*.

Reviewed again for v0.6.0 on 2026-09-12, against `sybxxx/codex-auto-retry` **v0.7.11**,
published that morning. Its scope has moved since the v0.5.0 review and this file has been
corrected for it: the list of failures its watchdog says it retries is network failures,
timeouts, rate limits, HTTP 5xx, one structured upstream wrapper, interrupted streams,
completions with no final model reply, and temporarily unavailable authentication services -
and a usage limit is not in it. Its goal handling says plainly that a usage-limited goal is
never turned into a continuation. Waiting out a usage limit and continuing the exact task is
therefore the thing this project does that the larger one does not say it does, which is the
opposite of the shape this file assumed a release ago. It also now recovers empty responses,
and restores an unloaded *parent* thread - with its own persisted settings rather than current
defaults - inside goal-mode subagent chains.

Two entries below moved because of that re-read, and the rest of this file stands.

## Others in the same space

Re-surveyed on 2026-09-12: every project below was checked against its repository that day, and
each line says what that project says about itself. None of them changed what this project
builds. They are here because a reader deciding between them deserves an accurate map, and
because two of them answer the same need in a way this project has ruled out, which is worth
being explicit about rather than quiet about.

| Project | What it is | How it differs from this one |
| --- | --- | --- |
| [`sybxxx/codex-auto-retry`](https://github.com/sybxxx/codex-auto-retry) | A Go watchdog for Codex on Windows with a tray controller and an embedded management panel (v0.7.11) | Broader recovery - unknown provider failures on their own budget, empty responses, goal chains, and an opt-in shared app-server that can restore an unloaded parent thread. Its stated retry list does not include a usage limit. Compared feature by feature below |
| [`saaranshM/unsnooze`](https://github.com/saaranshM/unsnooze) | A cross-platform resumer for Claude Code, Codex CLI, Grok, Qwen, Kimi, OpenCode and Antigravity across tmux, Zellij and VS Code | Far more agents and three platforms, and it reads `~/.codex/sessions` so it covers the desktop app's session files too. It resumes by **injecting keystrokes into a live terminal pane**, which it says plainly; this project does not simulate input anywhere, and resumes a conversation through Codex's own queue rather than a terminal |
| [`banana2556/codex-never-give-up`](https://github.com/banana2556/codex-never-give-up) | Auto-retry for the Codex desktop app on Windows, on the app-server IPC stream | Complementary rather than competing: it retries capacity, writer-conflict and shared-task errors and **deliberately does not retry a usage limit**, which is this project's main case. It works by injecting a hook into the app, with a DevTools console for diagnostics; this project adds no code to Codex |
| [`Matrtex/codex-auto-retry-plugin`](https://github.com/Matrtex/codex-auto-retry-plugin) | A Python Codex plugin that retries high-demand, 429, 5xx and transient stream or network errors | Similar failure classes; a plugin rather than a background watcher, so it acts while Codex is running rather than waiting out a reset after you close the app |
| [`ravhello/claude-codex-queue`](https://github.com/ravhello/claude-codex-queue) | A queue that continues Claude Code sessions and Codex App tasks after usage limits, preserving prompt order | Covers Claude Code as well, and is a queue rather than a failure classifier: it decides *when* to run queued work, where this decides *whether* a specific failure may be resumed at all |
| [`StylesDevelopments/agent-autoresume`](https://github.com/StylesDevelopments/agent-autoresume) | Auto-resume for Claude Code and Codex across usage-limit resets, with iTerm2 and tmux watchers | macOS and Linux, and terminal-shaped: it watches and drives a terminal session. This is Windows-only and watches the desktop app's own state |
| [`qxd-ljy/codex-goal-auto-retry-build`](https://github.com/qxd-ljy/codex-goal-auto-retry-build) | A Rust patch to Codex's own Goal auto-continuation, with reproducible source validation | It changes Codex; this does not. Goal state is something this project deliberately does not read or set |
| [`tidingman/codex-retry-watcher`](https://github.com/tidingman/codex-retry-watcher) | A macOS menu-bar app that presses Codex Desktop's Retry button when the model is at capacity | Other platform, and the method this project rules out: it clicks the button for you |
| [`Justin1491/codex-dashboard`](https://github.com/Justin1491/codex-dashboard) | A dashboard for understanding Codex usage and resets | Shows usage; recovers nothing |
| [`terryso/claude-auto-resume`](https://github.com/terryso/claude-auto-resume) | The most-starred tool in this space (820 stars), resuming Claude CLI tasks when limits lift | Claude only, not Codex. Listed because it is where most people in this space have ended up, and because its one-line description is a lesson in being findable |

Different architecture is not worse architecture. Retrying an unknown provider failure, owning a
shared app-server so an unloaded thread can be woken, or typing into a terminal pane, each buys
real capability this project does not have; each is the wrong trade *here* because this
project's promise is narrower. If what you want is maximum recovery, or an agent other than
Codex, or a platform other than Windows, one of the others will suit you better.

One thing several of them still do better: they are easier to find. On 2026-09-12 a plain search
for the sentence this product exists to answer - automatically resume a Codex task after a usage
limit resets, on Windows - returned Codex's own issues and two unrelated tools, and not this
repository. That is a fact about this repository, not about theirs.

No code was copied, then or now. Everything here was written against this project's own
architecture, from its own reading of Codex's local state.

## The two goals

| | `codex-auto-retry` | this project |
| --- | --- | --- |
| Goal | maximum recovery capability | minimum necessary complexity for safe recovery |
| Unknown failure | retried, on its own budget | never retried |
| Authentication failure | retried, with a lower limit | never retried; a person is needed |
| Classification | message and wrapper matching | structured `codexErrorInfo`, then HTTP status |
| Unloaded threads | woken through a shared app-server | left alone until you open them |
| Long-lived processes | supervisor, worker, optional app-server, MCP server | one watcher, plus an MCP server while Codex runs and one control process while the window is open |
| Interface | tray icon, settings window, Codex panel | Start Menu Dashboard (Overview, Pending, History, Statistics, Diagnostics, Settings), notification-area icon, Codex panel, notifications |

Neither column is a criticism. Retrying an unknown failure is a reasonable choice for a tool whose
goal is to recover as much as possible. It is the wrong choice for this one, whose promise is
narrower and, because of that, easier to trust: **it acts only on failures it can name.**

## Feature by feature

### Adopted — taken as an idea, built here from scratch

| Idea | How it exists here |
| --- | --- |
| A **named failure taxonomy** instead of a "did it fail" boolean | Built from Codex's structured `codexErrorInfo` variants and HTTP status, not from message text |
| A **retry budget** so a chain cannot run forever | `max_recovery_attempts`, user-configurable, default 4 |
| A **no-progress limit**, separate from the retry budget | `max_no_progress`, default 3; carried across interruptions on the same thread |
| **Per-thread recovery state**, so one stuck thread cannot block another | Per-thread enable flag and per-interruption records in SQLite |
| **Progress correlation** — a later unrelated success must not mark a retry as recovered | Delivery is proven by this record's own unique marker in that exact thread |
| **Configurable wait strategy** | Three named presets rather than raw ladders, so no setting can produce a zero or unbounded delay |
| **Restart an exhausted task with a fresh budget** | `reset_recovery_budget`, which restores the budget and sends nothing |
| **Retry a pending task now** | `retry_now`, which moves the schedule and nothing else; every gate still runs |
| **A live countdown per pending recovery** | The Dashboard's Pending page counts down to each record's next check, on the window's own timer (`Dashboard.cs:UpdateCountdowns`); the notification-area tooltip carries the same countdown |
| **A persistent pause switch** | The existing global kill switch, reused rather than duplicated |
| **State writes that survive a sharing violation** | Atomic replace from a uniquely named temporary; a failed write raises rather than corrupting |
| **A self-contained Windows ZIP with a double-click installer**, no runtime prerequisite | The release carries its own Python; no administrator rights, no network at install time |

### Adapted — the same need, answered differently

| Their approach | Here |
| --- | --- |
| **An embedded Codex management panel** | Adopted in v0.5 as a read-only settings panel over MCP. It shows state and changes settings; it cannot recover anything, and the watcher runs whether or not it is open. Previously rejected — the reason given was that it would replace something a user could do in words. That was true of a panel that only *displayed*; it stopped being true once there were sixteen settings to find. |
| **A graphical settings window** | Adopted in v0.5 as a standalone Start Menu window, for a different reason than theirs: settings must be reachable when Codex is closed and nothing else is running. |
| **A tray icon and a supervisor process** | The icon was adopted in the release after v0.5.7, as a thread of the watcher itself (`app.py:_start_tray`) rather than a second process, so it cannot show a watcher that is not running. Its menu opens the window, pauses recovery and stops the watcher; `show_tray` turns it off. The supervisor is still rejected: another long-lived process to make one visible |
| **An MCP server** | Adopted, deliberately narrow: typed configuration and safe control only. No tool detects, schedules, reserves or sends. |
| **Notification of a retry limit being reached** | One of four lifecycle notifications, each with its own switch |
| **Empty-input continuation, so no user bubble appears** | Not possible without their app-server route. A continuation message is sent, and the README says so plainly rather than implying the conversation is untouched |
| **A fallback retry text the user can edit** | Not exposed. The continuation text is not a setting here, because a user-authored instruction sent automatically into a conversation is a much larger surface than it looks |

### Rejected — a deliberate choice, not an omission

| Feature | Why not |
| --- | --- |
| **Retrying unknown provider failures** on a separate budget | The single line that defines this project. A failure it cannot name is a failure it does not act on |
| **Retrying authentication failures**, even with a lower limit | An auth failure needs a person. Retrying it can only burn attempts or lock an account |
| **A shared local app-server** (`CODEX_APP_SERVER_WS_URL`) | It means owning a piece of Codex's own transport, and a bug in it degrades Codex itself rather than degrading recovery |
| **Waking unloaded threads** via `thread/resume` | Follows from the above. The one route anybody has demonstrated - restoring an unloaded parent with its persisted settings - runs through that shared app-server, which means Codex pointing at an endpoint this project owns. Re-examined for v0.6.0 and still refused: an unloaded thread waits here until the user opens it, and the README states that limitation rather than engineering around it |
| **Injecting items into a thread** (`thread/inject_items`) | Writing into a conversation by any route other than the documented queue is not something this tool should be able to do |
| **Goal-state manipulation** | Reading and setting Codex's native goal state is a second model of what a task *is*, and every ambiguity in it becomes a way to resume the wrong work |
| **Subagent recovery** | Recovering a child thread on a parent's behalf multiplies the identity problem that this project's safety rests on |
| **Restoring model, provider, service tier, reasoning and permission settings** before recovery | It requires reading and replaying a slice of Codex's own session configuration. Here the thread is resumed as the user left it |
| **Dispatching several due tasks at once** | Sequential dispatch under one lock is what makes the no-duplicate-send argument short enough to check |

### Deferred — reasonable, not now

| Feature | Condition |
| --- | --- |
| **Empty-response recovery** — treating a completion with no assistant reply as a temporary failure | Re-examined for v0.6.0. Their handling is careful and privacy-bounded — a boolean for whether a final message was present, never its contents — and they now also note that Codex's own "finished a turn" popup fires before a completion can be classified, so a false completion cannot be un-notified. The failure is real and the detection can be content-free. It stays out because nothing in this repository has ever seen one: distinguishing it from a model that legitimately had nothing to say needs privacy-stripped structural captures from real Codex history, and there are none. It would ship default-off |
| **A break-glass "safely disable" action** | Their version exists because shared mode can leave Codex pointing at a dead endpoint. Nothing here can put Codex in a state it needs rescuing from, so the action has nothing to undo. If that ever stops being true, this becomes required rather than optional |

## The line that decides

> Keep the recovery engine small, local, conservative, and fail-closed; expand recovery only for
> clearly classified transient failures, and improve installation and control without turning the
> project into a second management application.

When a proposed feature would make the runtime do more rather than make the tool easier to install,
understand or trust, it belongs in the other project, not this one. The v0.5 surfaces were added
under exactly that test: they change how the product is *configured and explained*, and not one of
them can recover anything.

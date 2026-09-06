# Why this project stays small

There is a larger, more ambitious project in this space:
[`sybxxx/codex-auto-retry`](https://github.com/sybxxx/codex-auto-retry). It is worth reading.
Some of the ideas here were shaped by studying it (at `d25fda6`, release v0.7.9): a failure
taxonomy, a retry budget, per-thread recovery state, and a one-click Windows installer.

The two projects want different things.

| | `codex-auto-retry` | this project |
| --- | --- | --- |
| Goal | maximum recovery capability | minimum necessary complexity for safe recovery |
| Unknown failure | retried, with an attempt cap | never retried |
| Authentication failure | retried, with an attempt cap | never retried; a person is needed |
| Classification | message substring matching | structured `codexErrorInfo`, then HTTP status |
| Long-lived processes | daemon, supervisor, optional shared app-server, MCP server | one small watcher |
| Interface | tray, management panel, settings GUI, MCP | Codex skill plus one notification |
| Unloaded threads | woken through a shared app-server | left alone until you open them |

Neither column is a criticism. Retrying an unknown failure is a reasonable choice for a tool whose
goal is to recover as much as possible. It is the wrong choice for this one, whose promise is
narrower and, because of that, easier to trust: **it acts only on failures it can name.**

The same reasoning explains the rest. A shared app-server can wake an unloaded thread, but it means
owning a piece of Codex's own transport. A tray application and a settings panel make more state
visible, but they are a second application to maintain. Each of those buys capability with
complexity, and this project spends that budget very differently.

What was taken from studying the other project:

- The idea of a **named failure taxonomy** rather than a single "did it fail" boolean — implemented
  here from Codex's structured error variants instead of message matching.
- A **retry budget**, so a recovery chain cannot run forever.
- **Per-thread recovery state**, so one stuck thread cannot block another.
- A **one-click Windows installer** that automates the documented commands.

What was deliberately not taken: shared app-server and `CODEX_APP_SERVER_WS_URL` handling,
`thread/resume`-based waking of unloaded threads, MCP management surfaces, tray and settings GUIs,
a supervisor process, Goal manipulation, subagent recovery, broad authentication retry, and
retrying unknown provider failures.

No code was copied. Everything here was written against this project's own architecture.

## The line that decides

> Keep the recovery engine small, local, conservative, and fail-closed; expand recovery only for
> clearly classified transient failures, and improve installation and control without turning the
> project into a second management application.

When a proposed feature would make the runtime do more rather than make the tool easier to install,
understand or trust, it belongs in the other project, not this one.

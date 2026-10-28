# Contributors

This project was created by one human maintainer working with two AI development tools. The split below
is recorded honestly: the AI assistance was substantial, and it is not hidden.

## songyb111-gachon

Project creator and maintainer. Copyright holder.

- Project conception and goal definition
- Requirements definition
- Safety constraints (local-only, read-only, exact-thread, fail-closed, and the explicit list of
  techniques that are out of scope)
- Architecture direction
- Provided and validated the real Windows / ChatGPT / Codex environment
- Testing and verification decisions
- Final approval
- Release and maintenance

## OpenAI Codex

*AI-assisted development contribution.*

- Initial investigation of the Windows ChatGPT/Codex desktop app architecture
- Codex protocol and local-state investigation
- Exact-thread queue proof of concept
- loaded / notLoaded behaviour verification, including the measurement that established the project's
  central limitation
- `usageLimitExceeded` and reset-timestamp investigation
- Initial implementation of the detector, durable store, Windows adapter, and first scheduler

## Anthropic Claude Code

*AI-assisted development contribution.*

- Inherited and reviewed the Codex prototype
- Completed the watcher loop, CLI, Windows integration, and persistence
- Expanded the automated test suite
- Fixed correctness bugs, including two that made the inherited prototype non-functional end to end
- Security review and adversarial audit (three rounds, plus mutation testing, a crash-window matrix, and
  a cross-process race test)
- Public release preparation
- The v0.6.x development, maintenance and releases: the Dashboard, the two editions, the installer and the
  releases themselves, as [CHANGELOG.md](CHANGELOG.md) tells release by release

## People who reported, suggested and tested

Everyone below is a person outside the project who helped it, in the order they first did.

- [@cervinho](https://github.com/cervinho) asked for the computer to shut down or sleep once every recovery has
  finished ([discussion #22](https://github.com/songyb111-gachon/codex-auto-resume-windows/discussions/22)).
- [@barkshah2002-pixel](https://github.com/barkshah2002-pixel) reported a usage-limit interruption that was not
  detected ([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27)) and suggested logging every failed turn the watcher does not take up, with why.
- [@ZionZhang42](https://github.com/ZionZhang42) proved the cause of that missed detection ([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27)).
- [@aca22jy](https://github.com/aca22jy) reported a missed detection on a desktop conversation ([#27](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/27)) and then a conversation whose turns Codex
  records under another id ([#30](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/30)).
- [@Hunweibyn](https://github.com/Hunweibyn) suggested watching the usage limit ahead of time, with a safe pause
  and resume ([#29](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/29)).
- [@Zephreo](https://github.com/Zephreo) suggested resuming a goal that was running ([#36](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/36)).
- [@Kdevaulo](https://github.com/Kdevaulo) reported a terminal conversation continued in the Codex Desktop that
  was left out of recovery ([#37](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/37)) and an update status that misled when GitHub could not be reached ([#41](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/41)),
  and sent the fix that resumes a goal after a usage-limit reset ([#49](https://github.com/songyb111-gachon/codex-auto-resume-windows/pull/49)) and the one that
  sends a continuation to Codex's managed daemon where one runs and says in fixed words what a queue answer without a receipt was
  ([#53](https://github.com/songyb111-gachon/codex-auto-resume-windows/pull/53)).
- [@weng-wen-jun](https://github.com/weng-wen-jun) asked for a manual rescan that reconciles obsolete
  pending recoveries ([#39](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/39)), then proposed the Pending and editor work for queued messages and the
  usage check behind Retry now and Rescan, and the searchable conversation picker that became Find a conversation
  ([#50](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/50)).
- [@kano0222](https://github.com/kano0222) reported that a conversation an agent made was never recovered, even when the
  person went on using it from the input box, and traced it to the exact rule in the code ([#54](https://github.com/songyb111-gachon/codex-auto-resume-windows/issues/54)).

## A note on the AI contributors

**OpenAI Codex and Anthropic Claude Code are AI development tools, not human contributors or GitHub
accounts.**

They are credited here because they did meaningful design and implementation work, and because readers
of the source deserve to know how it was produced. They are deliberately **not**:

- given GitHub accounts, profiles, or contributor avatars,
- named as copyright holders,
- given an e-mail address of their own invention.

The commits that were written with Claude carry a `Co-Authored-By` trailer that names the Claude model that wrote
them, with Anthropic's own `noreply@anthropic.com` address. People, the maintainer and everyone who reported or
suggested something, are credited by their GitHub login.

Copyright is held by the human maintainer. Responsibility for the code, including its safety properties,
rests with the maintainer, not with the tools.

See [docs/DEVELOPMENT.md](DEVELOPMENT.md) for the phase-by-phase history.

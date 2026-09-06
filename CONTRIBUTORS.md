# Contributors

This project was created by one human maintainer working with two AI development tools. The split below
is recorded honestly: the AI assistance was substantial, and it is not hidden.

## Youngbin Song

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

## A note on the AI contributors

**OpenAI Codex and Anthropic Claude Code are AI development tools, not human contributors or GitHub
accounts.**

They are credited here because they did meaningful design and implementation work, and because readers
of the source deserve to know how it was produced. They are deliberately **not**:

- listed as commit authors or co-authors with invented email addresses,
- given GitHub accounts, profiles, or contributor avatars,
- named as copyright holders.

Copyright is held by the human maintainer. Responsibility for the code, including its safety properties,
rests with the maintainer, not with the tools.

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the phase-by-phase history.

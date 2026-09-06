Codex Auto Resume for Windows

=============================



Double-click Install.cmd.



It installs the Codex plugin and a small background watcher that resumes a Codex

task after a usage limit resets, and retries one after a clearly temporary failure.



Requirements

  - Windows 10 or 11

  - The ChatGPT/Codex desktop app, run at least once

  - Python 3.10 or newer on PATH (the installer tells you if it is missing;

    it never downloads or installs Python for you)



No administrator rights. No Windows service and no scheduled task. Everything it

registers lives under your own user account, and Uninstall.cmd removes it again.



Re-running Install.cmd upgrades in place and keeps anything already waiting to resume.



After installing, ask Codex in a new conversation:  show auto resume status



Source and documentation:

  https://github.com/songyb111-gachon/codex-auto-resume-windows


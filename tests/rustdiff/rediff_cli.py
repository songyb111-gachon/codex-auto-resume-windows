"""Re-diff S5.2 against a tag: the MCP server and the panel (car-control `mcp/`), the command line, plugin_setup.py's
commands and the dispatcher (car-bin), and every published legacy line handed through car-legacy.

    python -X utf8 tests/rustdiff/rediff_cli.py --reference v0.6.26
    python -X utf8 tests/rustdiff/rediff_cli.py                    # reference.TAG

S5.2 was ported from the v0.6.26 final. This says, in order: which of the ported files differ between the final and the
tag (`git diff --stat`, so a change is seen even where no diff reaches it); whether car-bin's parser tables are the tag's
(`gen_cli.py --check --reference TAG`); and then runs `diffs_mcp`, `diffs_cli` and `diffs_legacy` with the tag as the
reference (`run.py --build --reference TAG`). Exit 0 only when the tables are fresh and the diffs equal; a changed file
is printed, not failed on - the diffs decide.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTED = ("src/auto_resume.py", "src/codex_auto_resume/cli.py", "src/codex_auto_resume/commands/__init__.py",
          "src/codex_auto_resume/commands/base.py", "src/codex_auto_resume/commands/install.py",
          "src/codex_auto_resume/commands/records.py", "src/codex_auto_resume/commands/status.py",
          "src/codex_auto_resume/commands/watcher.py", "src/codex_auto_resume/mcpserver.py",
          "src/codex_auto_resume/mcp/__init__.py", "src/codex_auto_resume/mcp/server.py",
          "src/codex_auto_resume/mcp/tools.py", "src/codex_auto_resume/mcp/panel.py",
          "src/codex_auto_resume/mcp/assets/panel.css", "src/codex_auto_resume/mcp/assets/panel.js",
          "src/codex_auto_resume/notice_uris.py", "src/codex_auto_resume/codex_link.py", "scripts/plugin_setup.py",
          "gui/McpLauncher.cs", "src/codex_auto_resume/compat/report.py")
BASE = "v0.6.26"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--reference", metavar="TAG", default=None)
    args = parser.parse_args(argv)
    tag = args.reference
    if tag is None:
        sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
        from rustdiff import reference
        tag = reference.TAG
    changed = subprocess.run(["git", "diff", "--stat", BASE, tag, "--", *PORTED], cwd=ROOT, capture_output=True,
                             encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if changed.returncode != 0:
        print(changed.stderr.strip())
        return 2
    print("ported files changed from %s to %s:\n%s" % (BASE, tag, changed.stdout.strip() or "  none"))
    sys.stdout.flush()
    tables = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "gen_cli.py"), "--check", "--reference", tag],
                            cwd=ROOT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    diffs = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "run.py"), "--build", "--reference", tag,
                            "-k", "diffs_mcp", "-k", "diffs_cli", "-k", "diffs_legacy"], cwd=ROOT,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW).returncode
    print("rediff against %s: parser tables %s; diffs %s" % (tag, "fresh" if tables == 0 else "STALE",
                                                             "equal" if diffs == 0 else "DIFFER"))
    return 0 if tables == 0 and diffs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

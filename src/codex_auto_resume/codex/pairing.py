"""Binding the configured Codex to exactly one Windows Store package, and the inventory it reads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess as S

from ..domain.errors import AdapterError
from ..win.kernel import NO_WINDOW, process_identity


_INVENTORY_PS = r"""
$ErrorActionPreference='Stop'
# Windows PowerShell 5.1 emits the console OEM code page by default; force UTF-8 so
# non-ASCII executable paths (e.g. a non-ASCII user profile) survive the round-trip.
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
@(Get-CimInstance Win32_Process -Filter "Name = 'ChatGPT.exe' OR Name = 'codex.exe'" |
 ForEach-Object { [pscustomobject]@{
 pid=[int]$_.ProcessId; parent=[int]$_.ParentProcessId; path=$_.ExecutablePath
 } }) | ConvertTo-Json -Compress
"""


def inventory():
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = S.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", _INVENTORY_PS],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=15, creationflags=NO_WINDOW, check=True, shell=False)
        rows = json.loads(result.stdout) if result.stdout.strip() else []
        return rows if isinstance(rows, list) else [rows]
    except (OSError, S.SubprocessError, ValueError):
        raise AdapterError("process_inventory_unavailable") from None


def desktop_pair(rows, codex_exe):
    """Bind the configured official engine to exactly one Windows Store app main."""
    # Under WOW64 (32-bit Python on 64-bit Windows) ProgramFiles is the (x86) directory;
    # ProgramW6432 always holds the native one, where WindowsApps actually lives.
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
    app_pattern = re.compile(re.escape(str(Path(program_files) / "WindowsApps")) +
                             r"\\OpenAI\.Codex_[0-9.]+_(x64|arm64)__2p2nqsd0c76g0\\app\\ChatGPT\.exe", re.I)
    apps = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
            and app_pattern.fullmatch(row["path"])]
    app_ids = {row["pid"] for row in apps}
    mains = [row for row in apps if row.get("parent") not in app_ids]
    if len(mains) != 1:
        raise AdapterError("desktop_main_missing_or_ambiguous")
    servers = [row for row in rows if isinstance(row, dict) and isinstance(row.get("path"), str)
               and row["path"].lower() == str(codex_exe).lower() and row.get("parent") == mains[0]["pid"]]
    if len(servers) != 1:
        raise AdapterError("desktop_server_missing_or_ambiguous")
    app = process_identity(mains[0]["pid"])
    server = process_identity(servers[0]["pid"])
    if app["path"] != mains[0]["path"].lower() or server["path"] != str(codex_exe).lower():
        raise AdapterError("process_identity_changed")
    if server["created"] < app["created"]:
        raise AdapterError("process_parent_identity_invalid")
    return {**app, "server": server}

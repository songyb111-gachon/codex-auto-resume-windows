"""The Start Menu shortcut that gives this tool a Windows application identity.

Windows will not show a toast from an unpackaged application until a Start Menu
shortcut carries the same AppUserModelID the notification is sent under. Measured on
Windows 11 rather than assumed, because the obvious reading is wrong in a way that
wastes a lot of time: without the shortcut the platform still *accepts* the toast and
logs it as delivered (event 3153, and it appears in the notification history), it
simply never draws it. Only once the shortcut exists does Windows create
``Notifications\\Settings\\<AUMID>`` and start displaying with our name and icon.

The same shortcut is the Start Menu entry a user opens to change settings, so one
artefact serves both purposes.

The shortcut is written through the shell's own COM interfaces, driven from PowerShell
because setting ``System.AppUserModel.ID`` needs ``IPropertyStore`` and there is no
supported way to attach it with a plain .lnk writer.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from . import pwsh

SHORTCUT_NAME = "Codex Auto Resume.lnk"
TIMEOUT_SECONDS = 60

# PKEY_AppUserModel_ID = {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}, 5
_MAKER = r"""
$ErrorActionPreference = 'Stop'
Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CodexAutoResumeShell {
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] internal class CShellLink {}
  [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  internal interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder f, int c, IntPtr d, int fl);
    void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder n, int c);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder d, int c);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string d);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder a, int c);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string a);
    void GetHotkey(out short h); void SetHotkey(short h);
    void GetShowCmd(out int c); void SetShowCmd(int c);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder i, int c, out int idx);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string i, int idx);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string p, int r);
    void Resolve(IntPtr h, int fl);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string p);
  }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  internal interface IPropertyStore {
    void GetCount(out uint c); void GetAt(uint i, out PropertyKey k);
    void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v);
    void Commit();
  }
  [StructLayout(LayoutKind.Sequential, Pack = 4)] internal struct PropertyKey {
    public Guid fmtid; public uint pid;
    public PropertyKey(Guid g, uint p) { fmtid = g; pid = p; }
  }
  [StructLayout(LayoutKind.Explicit)] internal struct PropVariant {
    [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p;
  }
  [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  internal interface IPersistFile {
    void GetClassID(out Guid c); int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string f, int m);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool r);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
  }
  public static class Maker {
    public static void Create(string lnk, string target, string args, string workdir,
                              string icon, string aumid, string desc) {
      var link = (IShellLinkW)new CShellLink();
      link.SetPath(target);
      if (!string.IsNullOrEmpty(args)) link.SetArguments(args);
      if (!string.IsNullOrEmpty(workdir)) link.SetWorkingDirectory(workdir);
      if (!string.IsNullOrEmpty(icon)) link.SetIconLocation(icon, 0);
      link.SetDescription(desc);
      var store = (IPropertyStore)link;
      var key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
      var value = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(aumid) };
      store.SetValue(ref key, ref value);
      store.Commit();
      Marshal.FreeCoTaskMem(value.p);
      ((IPersistFile)link).Save(lnk, true);
    }
  }
}
'@
[CodexAutoResumeShell.Maker]::Create($env:CODEX_AUTO_RESUME_ARG_LNK, $env:CODEX_AUTO_RESUME_ARG_TARGET, $env:CODEX_AUTO_RESUME_ARG_ARGS, $env:CODEX_AUTO_RESUME_ARG_WORKDIR, $env:CODEX_AUTO_RESUME_ARG_ICON, $env:CODEX_AUTO_RESUME_ARG_AUMID, $env:CODEX_AUTO_RESUME_ARG_DESC)
"""


class ShortcutError(RuntimeError):
    """Static reason only; never includes a shell transcript."""


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def shortcut_path() -> Path:
    return start_menu_dir() / SHORTCUT_NAME


def exists() -> bool:
    try:
        return shortcut_path().is_file()
    except OSError:
        return False


def install(target, arguments="", icon=None, aumid=None, description="Codex Auto Resume") -> bool:
    """Create or replace our Start Menu shortcut. Returns True when written."""
    if pwsh.executable() is None:
        raise ShortcutError("PowerShell is unavailable; cannot create the Start Menu entry")
    if aumid is None:
        from .startup import AUMID
        aumid = AUMID
    destination = shortcut_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ShortcutError("Cannot create the Start Menu folder") from exc
    # Paths come from the install location, which can contain any character the user's
    # profile name does - an apostrophe included. They are passed beside the constant
    # script, never inside it; see pwsh.py for why quoting them was not enough.
    values = {
        "LNK": destination,
        "TARGET": Path(target).resolve(),
        "ARGS": arguments or "",
        "WORKDIR": Path(target).resolve().parent,
        "ICON": Path(icon).resolve() if icon else "",
        "AUMID": aumid,
        "DESC": description or "",
    }
    try:
        code = pwsh.run(_MAKER, values, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError, pwsh.PowerShellError) as exc:
        raise ShortcutError("Cannot create the Start Menu entry") from exc
    if code != 0 or not destination.is_file():
        raise ShortcutError("The Start Menu entry could not be written")
    return True


def uninstall() -> bool:
    """Remove only the shortcut at our own name and location. Idempotent."""
    destination = shortcut_path()
    try:
        if destination.is_file() and not destination.is_symlink():
            destination.unlink()
            return True
    except OSError:
        pass
    return False

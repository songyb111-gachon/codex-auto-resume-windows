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

The setup window also offers one on the Desktop, off unless a person ticks it (the owner, 2026-11-05). It is the same
shortcut in a second place, but not a singleton of ours: the Desktop is the person's, and a shortcut there with our
name may be theirs. So nothing here writes over or removes one unless its target is inside this installation.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess

from . import pwsh

SHORTCUT_NAME = "Codex Auto Resume.lnk"
TIMEOUT_SECONDS = 60

# Where the Desktop shortcut goes instead of the person's Desktop: what a smoke run or a test sets, as they point APPDATA
# for the Start Menu entry. Windows' known folder ignores a scratch USERPROFILE, so without it there is no scratch Desktop.
DESKTOP_ENV = "CODEX_AUTO_RESUME_DESKTOP"
FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"

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

# Reads a shortcut, and saves nothing: whether its target is inside the installation (0) or not (3). 4: it has no target.
_READER = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$target = $shell.CreateShortcut($env:CODEX_AUTO_RESUME_ARG_LNK).TargetPath
if ([string]::IsNullOrEmpty($target)) { exit 4 }
$root = [IO.Path]::GetFullPath($env:CODEX_AUTO_RESUME_ARG_ROOT).TrimEnd('\') + '\'
if ([IO.Path]::GetFullPath($target).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { exit 0 }
exit 3
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
    destination = shortcut_path()
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ShortcutError("Cannot create the Start Menu folder") from exc
    return _write(destination, target, arguments, icon, aumid, description, "the Start Menu entry")


def _write(destination, target, arguments, icon, aumid, description, what) -> bool:
    if aumid is None:
        from .startup import AUMID
        aumid = AUMID
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
        raise ShortcutError("Cannot create %s" % what) from exc
    if code != 0 or not destination.is_file():
        raise ShortcutError("%s could not be written" % (what[0].upper() + what[1:]))
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


class DesktopTaken(ShortcutError):
    """A shortcut with our name is on the Desktop, and it is not ours. It stays as it is."""


def desktop_dir() -> Path | None:
    """The person's Desktop, where Windows says it is: a Desktop redirected to OneDrive is there, never under
    %USERPROFILE%. None where Windows cannot say."""
    given = os.environ.get(DESKTOP_ENV)
    if given:
        return Path(given)
    if os.name != "nt":
        return None
    try:
        ole32 = ctypes.WinDLL("ole32")
        shell32 = ctypes.WinDLL("shell32")
        folder = (ctypes.c_ubyte * 16)()
        if ole32.CLSIDFromString(FOLDERID_DESKTOP, ctypes.byref(folder)) != 0:
            return None
        path = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None, ctypes.byref(path)) != 0:
            return None
        try:
            return Path(path.value) if path.value else None
        finally:
            ole32.CoTaskMemFree(path)
    except (OSError, ValueError, AttributeError):
        return None


def desktop_path() -> Path | None:
    folder = desktop_dir()
    return None if folder is None else folder / SHORTCUT_NAME


def _present(link: Path) -> bool:
    try:
        return os.path.lexists(link)
    except OSError:
        return False


def _inside(link: Path, home) -> bool:
    """Whether the shortcut `link` opens something inside the installation at `home`. Asked of the shell, which reads
    it and saves nothing. Raises ShortcutError where it cannot be told, which is never an answer of yes."""
    if not link.is_file() or link.is_symlink():
        return False
    try:
        code = pwsh.run(_READER, {"LNK": link, "ROOT": Path(home).resolve()}, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError, pwsh.PowerShellError) as exc:
        raise ShortcutError("The shortcut on the Desktop could not be read") from exc
    if code in (0, 3, 4):
        return code == 0
    raise ShortcutError("The shortcut on the Desktop could not be read")


def install_desktop(home, target, arguments="", icon=None, aumid=None, description="Codex Auto Resume") -> bool:
    """Create or replace this installation's shortcut on the Desktop. Raises DesktopTaken where another shortcut has
    the name, and ShortcutError where it cannot be written; what it opens must be inside the installation, or it
    would not be ours to remove afterwards."""
    root = Path(home).resolve()
    if root not in Path(target).resolve().parents:
        raise ShortcutError("What the Desktop shortcut would open is not inside this installation")
    link = desktop_path()
    if link is None:
        raise ShortcutError("Windows did not say where the Desktop is")
    if _present(link) and not _inside(link, root):
        raise DesktopTaken("Another shortcut with this name is on the Desktop")
    if pwsh.executable() is None:
        raise ShortcutError("PowerShell is unavailable; cannot create the Desktop shortcut")
    if not link.parent.is_dir():
        raise ShortcutError("The Desktop folder is not there")
    return _write(link, target, arguments, icon, aumid, description, "the Desktop shortcut")


def uninstall_desktop(home) -> bool:
    """Remove the shortcut on the Desktop if it is this installation's, and nothing else. Idempotent. Raises
    ShortcutError where it is there and could not be read or removed."""
    link = desktop_path()
    if link is None or not _present(link) or not _inside(link, home):
        return False
    try:
        link.unlink()
    except OSError as exc:
        raise ShortcutError("The Desktop shortcut could not be removed") from exc
    return True

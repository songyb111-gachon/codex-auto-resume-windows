
$ErrorActionPreference = 'Stop'
Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace CodexAutoResumeShell {
  [ComImport, Guid("@@CLSID_SHELL_LINK@@")] internal class CShellLink {}
  [ComImport, Guid("@@IID_SHELL_LINK_W@@"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
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
  [ComImport, Guid("@@IID_PROPERTY_STORE@@"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
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
  [ComImport, Guid("@@IID_PERSIST_FILE@@"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
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
      var key = new PropertyKey(new Guid("@@PKEY_APP_USER_MODEL_ID@@"), 5);
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

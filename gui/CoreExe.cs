// Codex Auto Resume - the one program every start of the window's runs (v0.6.27-alpha, the Rust core).
//
// The window starts four things, and all four are this installation's console core, app\bin\codex-auto-resume.exe:
// the one-shot bridge (`bridge <command> [-]`, Bridge.Call in gui/SettingsApp.cs), the Dashboard's long-lived one
// (`bridge serve`, PersistentBridge in gui/Dashboard.cs), Repair (`setup --keep-state`, gui/DashboardMaintenance.cs)
// and the Desktop shortcut (`desktop-shortcut make|remove`, DesktopShortcut.Change in gui/InstallerFlow.cs). The core
// answers each with the words, codes and bytes the Python programs it replaces answered with (the wire is unchanged),
// so the window reads them as it always did.
//
// There is one core per installation, so there is nothing to choose: no bundled and chosen interpreter, no fallback
// from one to the other, no interpreter option to put first. Every start passes UseShellExecute = false and
// CreateNoWindow = true, as before: the core is a console program, and its console is never shown.
//
// In [installer] because the setup programs are compiled with that group too (build/make_setup.py) and ask the same
// core for the Desktop shortcut. C# 5 and System.dll only.

namespace CodexAutoResume
{
    internal static class CoreExe
    {
        /// The core's file name, inside the installation's app\bin.
        internal const string Name = "codex-auto-resume.exe";

        /// root\app\bin\codex-auto-resume.exe: the program every start of the window's runs. Pure.
        internal static string Path(string root)
        {
            return System.IO.Path.Combine(System.IO.Path.Combine(System.IO.Path.Combine(root ?? "", "app"), "bin"), Name);
        }
    }
}

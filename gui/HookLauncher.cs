// Starts the advanced edition's Stop hook handler using the runtime that shipped with it.
//
// The twin of gui/McpLauncher.cs, for the one capability that is started by Codex itself rather
// than by this product: "Continue inside the turn" (stop_hook_continuation). Codex runs a hook's
// command when a turn stops, hands it one JSON object on standard input and reads its answer from
// standard output. The handler is Python, and Python is this installation's own bundled
// interpreter, which only this launcher knows how to find - so the declaration names this file.
//
// It is a launcher and nothing else. It holds no configuration, decides nothing about recovery
// and writes nothing of its own to standard output: the child's one answer is relayed byte for
// byte, and a stray byte on that stream would be read by Codex as the hook's decision. It never
// writes to standard error either: whatever goes wrong, a hook that says nothing and exits 0 is a
// hook that lets the turn end as it would have, which is the only safe failure.
//
// The streams are redirected and relayed rather than inherited, for the reason McpLauncher gives:
// a child started with CREATE_NO_WINDOW and no explicit handles has no usable standard handles.
// The child's standard error is read and dropped, so a diagnostic of the handler's never reaches
// Codex. And the child is bounded: the handler answers within its own budget or passes, and past
// this launcher's longer bound it is ended and the launcher exits 0 with nothing written.
//
// Built only into the advanced edition (build/make_gui.ps1 -Edition advanced) and shipped only in
// its archive, at payload/app/hook/ (build/make_release.py), reproducibly like every executable here.

using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace CodexAutoResume
{
    internal static class HookLauncher
    {
        // The handler answers within two seconds or passes (codex_auto_resume_advanced.hook.handler,
        // BUDGET_SECONDS); this is the outer bound, for an interpreter that never got that far.
        private const int BoundMilliseconds = 8000;

        // Both overrides, in the order the rest of the product resolves them (McpLauncher.InstallHome).
        private static string InstallHome()
        {
            string configured = Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_PLUGIN_HOME");
            if (string.IsNullOrEmpty(configured))
                configured = Environment.GetEnvironmentVariable("CODEX_AUTO_RESUME_HOME");
            if (!string.IsNullOrEmpty(configured)) return configured;
            string profile = Environment.GetEnvironmentVariable("USERPROFILE");
            if (string.IsNullOrEmpty(profile))
                profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(profile, ".codex-auto-resume");
        }

        internal static int Main(string[] argv)
        {
            string home = InstallHome();
            string python = Path.Combine(home, "runtime", "python.exe");
            string source = Path.Combine(home, "app", "src");
            // Nothing installed is nothing to say: the turn ends as it would have.
            if (!File.Exists(python) || !Directory.Exists(source)) return 0;

            // The paths go in as arguments, never inside the code (McpLauncher says why).
            string code = "import sys;sys.path.insert(0,sys.argv[1]);" +
                          "from codex_auto_resume_advanced.hook import main;" +
                          "sys.exit(main(sys.argv[2:]))";

            var info = new ProcessStartInfo();
            info.FileName = python;
            info.Arguments = "-I -c " + Quote(code) + " " + Quote(source) +
                             " --home " + Quote(home);
            info.UseShellExecute = false;
            info.RedirectStandardInput = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            info.WorkingDirectory = home;

            try
            {
                using (Process process = Process.Start(info))
                {
                    var answer = new MemoryStream();
                    Thread output = Relay(process.StandardOutput.BaseStream, answer);
                    Thread errors = Relay(process.StandardError.BaseStream, Stream.Null);
                    // The one object Codex hands over, then end of input, on a thread of its own: an
                    // input that never ends must not keep this launcher past its bound.
                    Stream childInput = process.StandardInput.BaseStream;
                    var input = new Thread(delegate ()
                    {
                        Pump(Console.OpenStandardInput(), childInput);
                        try { childInput.Close(); }
                        catch (Exception) { /* the child may already have gone */ }
                    });
                    input.IsBackground = true;
                    input.Start();
                    if (!process.WaitForExit(BoundMilliseconds))
                    {
                        try { process.Kill(); }
                        catch (Exception) { /* it ended as it was asked to */ }
                        return 0;
                    }
                    output.Join(2000);
                    errors.Join(2000);
                    // Only a handler that finished is relayed, and only whole: a decision cut short is
                    // no decision, and an exit other than 0 is a doubt, which passes.
                    if (process.ExitCode != 0) return 0;
                    byte[] bytes = answer.ToArray();
                    if (bytes.Length > 0)
                    {
                        Stream stdout = Console.OpenStandardOutput();
                        stdout.Write(bytes, 0, bytes.Length);
                        stdout.Flush();
                    }
                    return 0;
                }
            }
            catch (Exception)
            {
                return 0;
            }
        }

        private static Thread Relay(Stream from, Stream to)
        {
            var thread = new Thread(delegate () { Pump(from, to); });
            thread.IsBackground = true;
            thread.Start();
            return thread;
        }

        private static void Pump(Stream from, Stream to)
        {
            var buffer = new byte[8192];
            try
            {
                while (true)
                {
                    int read = from.Read(buffer, 0, buffer.Length);
                    if (read <= 0) return;
                    to.Write(buffer, 0, read);
                    to.Flush();
                }
            }
            catch (Exception) { /* either end closing is an ordinary end */ }
        }

        // Windows command-line quoting, by the documented CommandLineToArgvW rules (McpLauncher.Quote).
        internal static string Quote(string value)
        {
            var builder = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in value ?? string.Empty)
            {
                if (c == '\\') { slashes++; continue; }
                if (c == '\"') builder.Append('\\', slashes * 2 + 1).Append('\"');
                else builder.Append('\\', slashes).Append(c);
                slashes = 0;
            }
            return builder.Append('\\', slashes * 2).Append('\"').ToString();
        }
    }
}

// Starts the Codex Auto Resume MCP server using the runtime that shipped with it.
//
// This exists because of one Codex rule: a plugin's stdio `command` must be a bare
// executable name or a path contained inside the plugin. An absolute path to our
// bundled interpreter is neither, and a bare `python` would reintroduce exactly the
// system-Python requirement the product removed. So the plugin ships this, and this
// finds the interpreter.
//
// It is a launcher and nothing else. It holds no configuration, makes no decisions
// about recovery, and never writes to standard output: the child owns that stream, and
// a single stray byte on it would corrupt the JSON-RPC the server speaks. Diagnostics
// go to standard error, where Codex logs them.
//
// The three standard streams are redirected and relayed byte for byte rather than left
// to inheritance. Inheritance looks simpler and does not work: a child started with
// CREATE_NO_WINDOW and no explicit handles is handed no usable standard handles at all,
// so the server sits waiting for input that never arrives and the host waits for a
// handshake that never comes - a hang, with nothing in any log. Measured, not assumed.
// Relaying also means the exact bytes cross the boundary, with no text encoding in the
// middle to reinterpret them.

using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace CodexAutoResume
{
    internal static class McpLauncher
    {
        // Both overrides, in the order the rest of the product resolves them.
        //
        // CODEX_AUTO_RESUME_PLUGIN_HOME is the one that moves the *installation*: the
        // installer deploys there and setup configures there. CODEX_AUTO_RESUME_HOME
        // moves the core CLI's state directory and is the older, narrower knob. This
        // launcher honoured only the second, so setting the first moved the runtime and
        // left the MCP server looking for it in the profile - the panel would then be
        // the one surface that could not find an installation everything else agreed on.
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

            if (!File.Exists(python) || !Directory.Exists(source))
            {
                Console.Error.WriteLine(
                    "Codex Auto Resume is not installed at " + home + "; " +
                    "run its installer, then reload the plugin.");
                return 1;
            }

            // The interpreter gets the paths as arguments rather than baked into the
            // code: a Windows path inside a Python string literal has to survive two
            // separate escaping rules, and getting either wrong is silent.
            string code = "import sys;sys.path.insert(0,sys.argv[1]);" +
                          "from codex_auto_resume.mcpserver import main;" +
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
                    // Output and error are pumped on their own threads so neither can
                    // block the other; a full pipe on one stream would otherwise stall
                    // the server mid-reply.
                    Thread output = Relay(process.StandardOutput.BaseStream,
                                          Console.OpenStandardOutput());
                    Thread errors = Relay(process.StandardError.BaseStream,
                                          Console.OpenStandardError());
                    // Input is pumped here: when the host closes it, the child's stdin
                    // is closed too, which is how the server learns to shut down.
                    Pump(Console.OpenStandardInput(), process.StandardInput.BaseStream);
                    try { process.StandardInput.BaseStream.Close(); }
                    catch (Exception) { /* the child may already have gone */ }
                    process.WaitForExit();
                    output.Join(2000);
                    errors.Join(2000);
                    return process.ExitCode;
                }
            }
            catch (Exception error)
            {
                Console.Error.WriteLine("Could not start the Codex Auto Resume MCP server: " + error.Message);
                return 1;
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
            // Flushed after every read rather than every buffer: this carries a
            // request/response protocol, and a reply sitting in a buffer is a hang.
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
            catch (Exception) { /* either end closing is an ordinary shutdown */ }
        }

        // Windows command-line quoting, by the documented CommandLineToArgvW rules: a
        // run of backslashes is only special immediately before a quote, where 2n means
        // n literal backslashes and a delimiter, and 2n+1 means n and a literal quote.
        // Doubling every backslash instead - the obvious-looking version - turns a path
        // into one with doubled separators. Windows tolerates that, so it works right up
        // until something compares two paths for equality.
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

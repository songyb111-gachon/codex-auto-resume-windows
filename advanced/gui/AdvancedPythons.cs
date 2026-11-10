// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - the Python version card on the Advanced features page (v0.6.23, python_choice).
//
// While the capability is on or watched, its column has a card: the Python the watcher runs on now, the one the program came
// with, and - after a press of Check python.org, and only then - one line for each newest release python.org lists, with one
// button that downloads, verifies and puts it in use. While that runs the card shows the bytes truly written, never an
// estimate; a refusal says which step refused, in plain words. Back to the bundled version stands on the card whenever a
// version is chosen, however broken that version is: the long-lived bridge leaves a broken chosen Python for the bundled one
// by itself (PersistentBridge), so this page stays reachable. advanced-python is read when the capability is opened, and every
// PythonPollMilliseconds while something is running. Each button asks first. Nothing here reaches the network: the bridge does.
//
// C# 5 (the in-box compiler), as the rest of the window.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Forms;

namespace CodexAutoResume
{
    internal sealed partial class SettingsForm
    {
        private const string PythonId = "python_choice";
        private const int PythonPollMilliseconds = 700;
        private const double PythonMegabyte = 1024.0 * 1024.0;

        // advanced-python's last answer, or null; the timer that reads it while something runs.
        private Dictionary<string, object> advancedPython;
        private Timer pythonTimer;
        private bool pythonPolling;
        // The buttons as the card was built: Check python.org, Back, and one for each offered version.
        private Button pythonCheck, pythonBack;
        private readonly List<Button> pythonUse = new List<Button>();

        private void ReadPython(MethodInvoker done)
        {
            AdvancedCall("advanced-python", "{}", false, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                advancedPython = AdvancedDone(result) ? result : null;
                ShowAdvancedDetail();
                WatchPython();
                if (done != null) done();
            });
        }

        private bool PythonRunning()
        {
            return advancedPython != null && Map(advancedPython, "job") != null;
        }

        /// The timer runs while the bridge is at work, never in a test's window, which reads the card itself ({"do": "poll_python"}).
        private void WatchPython()
        {
            if (!PythonRunning() || advancedScript != null || auditing)
            {
                if (pythonTimer != null) pythonTimer.Stop();
                return;
            }
            if (pythonTimer == null)
            {
                pythonTimer = new Timer();
                pythonTimer.Interval = PythonPollMilliseconds;
                pythonTimer.Tick += delegate { PollPython(); };
                Disposed += delegate { pythonTimer.Dispose(); };
            }
            pythonTimer.Start();
        }

        private void PollPython()
        {
            if (pythonPolling || advancedOpen != PythonId) return;
            pythonPolling = true;
            ReadPython(delegate { pythonPolling = false; });
        }

        /// What the card is built from, for ShowAdvancedDetail to build it again only when it changed.
        private string PythonShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != PythonId) return "";
            return AdvancedWritten(advancedPython);
        }

        private void ForgetPythonCard()
        {
            pythonCheck = pythonBack = null;
            pythonUse.Clear();
        }

        private string PythonInUse()
        {
            string version = Str(advancedPython, "in_use");
            return version == null
                ? Word("page.python.in_use_none", "The watcher is not running now.")
                : Word("page.python.in_use", "The watcher runs on Python {version}.", "version", version);
        }

        /// While something runs: how far it has come, in the bytes truly written.
        private string PythonStage(Dictionary<string, object> job)
        {
            string version = Str(job, "version") ?? "";
            string stage = Str(job, "stage");
            if (stage == "checking") return Word("page.python.checking", "Asking python.org...");
            if (stage == "downloading")
                return Word("page.python.downloading", "Downloading Python {version}: {got} of {total} MB", "version", version)
                    .Replace("{got}", Mirror.Embed(PythonMegabytes(Number(job, "got"))))
                    .Replace("{total}", Mirror.Embed(PythonMegabytes(Number(job, "total"))));
            if (stage == "verifying")
                return Word("page.python.verifying", "Checking Python {version} before it runs...", "version", version);
            return Word("page.python.restarting", "Restarting the watcher...");
        }

        private static string PythonMegabytes(double bytes)
        {
            return (bytes / PythonMegabyte).ToString("0.0", CultureInfo.CurrentCulture);
        }

        /// How the last press ended, or null.
        private string PythonOutcome(Dictionary<string, object> outcome)
        {
            if (outcome == null) return null;
            string version = Str(outcome, "version") ?? "";
            string word = Str(outcome, "word");
            if (word == "chosen") return Word("page.python.done", "The watcher now runs on Python {version}.", "version", version);
            if (word == "next_start")
                return Word("page.python.next_start", "Python {version} is ready. The watcher takes it when it next starts.", "version", version);
            if (word == "back") return Word("page.python.done_back", "Back on the bundled version.");
            string step = Str(outcome, "step");
            if (step == "list") return Word("page.python.failed.list", "python.org could not be read. Nothing was changed.");
            if (step == "source") return Word("page.python.failed.source", "python.org did not give the official address or digest for this version, so nothing was downloaded.");
            if (step == "download") return Word("page.python.failed.download", "The download did not finish. Nothing was changed.");
            if (step == "digest") return Word("page.python.failed.digest", "The file does not match the digest python.org published. It was deleted, and nothing was changed.");
            if (step == "unpack") return Word("page.python.failed.unpack", "The package could not be unpacked safely. It was deleted, and nothing was changed.");
            if (step == "signature") return Word("page.python.failed.signature", "A program in the package is not signed by the Python Software Foundation. It was deleted, and nothing was changed.");
            if (step == "import") return Word("page.python.failed.import", "This program does not run on that version: not every part of it could be loaded. It was deleted, and nothing was changed.");
            return Word("page.python.failed.start", "The watcher did not start on that version, so it is back on the one it was on.");
        }

        /// That a choice was taken back by itself, until the next one is made.
        private string PythonReturned(Dictionary<string, object> returned)
        {
            if (returned == null) return null;
            string version = Str(returned, "version") ?? "";
            string why = Str(returned, "why");
            if (why == "line")
                return Word("page.python.returned.line", "This version of the program no longer offers Python {version}, so it went back to the bundled version.", "version", version);
            if (why == "off")
                return Word("page.python.returned.off", "This feature was off when the watcher started, so it went back to the bundled version.");
            return Word("page.python.returned.start", "The watcher did not start on Python {version}, so it went back to the bundled version by itself.", "version", version);
        }

        /// The open capability's card, while it is on or watched.
        private void BuildPython(Dictionary<string, object> item)
        {
            ForgetPythonCard();
            if (Str(item, "id") != PythonId || !Standing(item) || advancedPython == null) return;
            TableLayoutPanel card = NewGroup(Word("page.python.title", "Python version"), advancedStack);
            var used = HelpText(PythonInUse());
            used.ForeColor = Ink;
            used.Margin = Pad(0, 6, 0, 2);
            card.Controls.Add(used);
            string bundled = Str(advancedPython, "bundled"), chosen = Str(advancedPython, "chosen");
            if (bundled != null)
                card.Controls.Add(HelpText(Word("page.python.bundled", "Came with this program: Python {version}, always kept.", "version", bundled)));
            if (chosen != null)
                card.Controls.Add(HelpText(Word("page.python.chosen", "Chosen: Python {version}, from python.org.", "version", chosen)));
            Dictionary<string, object> job = Map(advancedPython, "job");
            if (job != null) card.Controls.Add(HelpText(PythonStage(job)));
            string ended = PythonOutcome(Map(advancedPython, "outcome"));
            if (ended != null) card.Controls.Add(HelpText(ended));
            string returned = PythonReturned(Map(advancedPython, "returned"));
            if (returned != null) card.Controls.Add(HelpText(returned));
            if (Equals(Get(advancedPython, "button"), true)) BuildPythonOffers(card, chosen);
            if (chosen != null)
            {
                pythonBack = CardButton(card, Word("page.python.back", "Back to the bundled version"), delegate { PythonGoBack(); });
                pythonBack.Margin = Pad(0, 8, 0, 4);
            }
        }

        private void BuildPythonOffers(TableLayoutPanel card, string chosen)
        {
            card.Controls.Add(HelpText(Word("page.python.help",
                "Nothing is read from the network until you press a button. Check python.org lists the newest release of each version; Use this version downloads it from www.python.org and checks it before it runs.")));
            pythonCheck = CardButton(card, Word("page.python.check", "Check python.org"), delegate { PythonAsk(); });
            pythonCheck.Margin = Pad(0, 8, 0, 4);
            if (!Equals(Get(advancedPython, "checked"), true)) return;
            List<object> offers = Items(advancedPython, "offers") ?? new List<object>();
            if (offers.Count == 0) card.Controls.Add(HelpText(Word("page.python.none", "python.org lists no version this program can use.")));
            foreach (object entry in offers)
            {
                var offer = entry as Dictionary<string, object>;
                if (offer == null) continue;
                string version = Str(offer, "version");
                string shown = Equals(Get(offer, "preview"), true)
                    ? Word("page.python.preview", "Python {version} (preview: the bundled version moves to it only in a later version)", "version", version)
                    : Word("page.python.version", "Python {version}", "version", version);
                card.Controls.Add(Caption(shown));
                if (version == chosen)
                {
                    card.Controls.Add(HelpText(Word("page.python.current", "Chosen now.")));
                    continue;
                }
                string pressed = version;
                Button use = CardButton(card, Word("page.python.use", "Use this version"), delegate { PythonPut(pressed); });
                use.Margin = Pad(0, 2, 0, 6);
                pythonUse.Add(use);
            }
        }

        private void UpdatePythonButtons(bool idle)
        {
            bool free = idle && advancedListing != null && advancedPython != null && !PythonRunning();
            if (pythonCheck != null) pythonCheck.Enabled = free;
            if (pythonBack != null) pythonBack.Enabled = free;
            foreach (Button use in pythonUse) use.Enabled = free;
        }

        private void PythonAsk()
        {
            if (busy > 0 || pythonCheck == null) return;
            PythonPress("advanced-python-check", "{}");
        }

        private void PythonPut(string version)
        {
            if (busy > 0) return;
            string question = Word("page.confirm.python_use",
                "Download Python {version} from www.python.org, check it, and restart the watcher on it? If the watcher does not start on it, it goes back by itself.",
                "version", version);
            if (!AskAdvanced(question, Affirm(Word("page.python.use", "Use this version")))) return;
            PythonPress("advanced-python-use", "{\"version\":" + Json.Escape(version) + "}");
        }

        private void PythonGoBack()
        {
            if (busy > 0 || pythonBack == null) return;
            string question = Word("page.confirm.python_back", "Go back to the Python that came with this program, and restart the watcher on it?");
            if (!AskAdvanced(question, Affirm(Word("page.python.back", "Back to the bundled version")))) return;
            PythonPress("advanced-python-back", "{}");
        }

        private void PythonPress(string command, string argument)
        {
            AdvancedCall(command, argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (!AdvancedDone(result)) TellAdvanced(PythonRefusal(Str(result, "refusal")));
                ReadPython(null);
            });
        }

        private string PythonRefusal(string refusal)
        {
            if (refusal == "python_busy") return Word("page.refused.python_busy", "It is already at work. Wait for it to finish.");
            return ResetRefusal(refusal);
        }
    }
}

// ADVANCED-EDITION-CODE: in the advanced edition's window, never the standard one's.
//
// Codex Auto Resume - chat with a conversation, on the Advanced features page (v0.6.19).
//
// While Chat with a conversation in the Dashboard is on, a Chat tab sits right of the Advanced features tab (and only
// then); it opens this page at the chat's own column. There, under its limits, a card: the conversation picked from
// those Pending and History list, its last turns as flat lines - "You:" and "Codex:" with the words, a turn's commands
// and file changes as counts, "In progress" while a turn runs (approvals are answered in Codex) - this page's own
// messages to it ("Sending...", "Sent", "Codex did not take it"), and the box a message is written in, with Send... and,
// for one still waiting, Cancel. Each is the bridge's (advanced-chat-read, advanced-chat-send, advanced-chat-cancel),
// the Dashboard's alone. The conversation is read when the card is opened or the conversation changes, and again every
// two seconds only while this column is on screen and something is still going on; what is read is shown and dropped.
// A message written while the usage limit is full waits, and the card says it is sent when the limit resets. Under the
// box, while chat is on, where a click on a notice goes - its page, that conversation's chat here, or Codex at that
// conversation - which is the standard setting `notice_click`, written here alone (`update`, settings.DASHBOARD_ONLY).
// A notice whose click opens the chat starts the window with `--chat=<conversation>` (ui/tray/dashboard.open_chat).
//
// Nothing here draws anything the page does not draw already.
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
        private const string ChatId = "codex_chat";
        private const string ChatPageName = "chat";
        private NavButton chatTab;
        private SoftCombo chatConversation;
        private SoftTextArea chatWords;
        private Button chatSend, chatCancel;
        private string chatThread, chatDraft = "";
        // advanced-chat-read's last answer for chatThread, or null.
        private Dictionary<string, object> chatView;
        private Timer chatTimer;
        private SoftCombo chatClick;
        // The conversation the command line asked the chat to open at (`--chat=`, AdvancedPage.ArgumentParsed), until
        // the card takes it.
        private static string askedChat;
        private const string ChatArgument = "--chat=";
        private static readonly System.Text.RegularExpressions.Regex ChatShape = new System.Text.RegularExpressions.Regex(
            "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
        // The values of the standard setting `notice_click` (settings.NOTICE_CLICKS), in the order they are offered.
        private static readonly string[] ChatClicks = { "page", "chat", "codex" };

        /// `--chat=<conversation>` read from the command line: kept only as a conversation id's canonical text.
        private static bool ChatArgumentParsed(string argument)
        {
            if (!argument.StartsWith(ChatArgument, StringComparison.Ordinal)) return false;
            string thread = argument.Substring(ChatArgument.Length);
            if (ChatShape.IsMatch(thread)) askedChat = thread;
            return true;
        }

        // ---------------------------------------------------------------- the tab
        /// The Chat tab, right of the Advanced features tab, as that one is made: hidden until chat is on.
        private void AddChatTab(NavButton advanced)
        {
            var tab = new NavButton();
            tab.Font = advanced.Font;
            tab.AutoSize = true;
            tab.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            tab.FlatStyle = FlatStyle.Flat;
            tab.FlatAppearance.BorderSize = 0;
            tab.ForeColor = Secondary;
            tab.Padding = advanced.Padding;
            tab.Margin = advanced.Margin;
            tab.Cursor = Cursors.Hand;
            tab.UseVisualStyleBackColor = false;
            tab.Visible = false;
            tab.Click += delegate { OpenChat(); };
            advanced.Parent.Controls.Add(tab);
            chatTab = tab;
            chatTimer = new Timer();
            chatTimer.Interval = 2000;
            chatTimer.Tick += delegate { ChatPoll(); };
        }

        /// The Chat tab shown only while chat is on, as the list last said (FillAdvancedList).
        private void UpdateChatTab()
        {
            if (chatTab == null) return;
            bool on = false;
            foreach (object entry in Items(advancedListing, "capabilities") ?? new List<object>())
            {
                var item = entry as Dictionary<string, object>;
                if (item != null && Str(item, "id") == ChatId && Str(item, "state") == StateArmed) on = true;
            }
            chatTab.Text = Word("page.chat.nav", "Chat");
            chatTab.AccessibleName = chatTab.Text;
            if (chatTab.Visible == on) return;
            chatTab.Visible = on;
            HoldTabs();
        }

        /// The Chat tab pressed: this page, at chat's own column.
        private void OpenChat()
        {
            ShowAdvanced();
            OpenAdvanced(ChatId);
        }

        // ---------------------------------------------------------------- the card
        /// What the chat card is built from, for ShowAdvancedDetail to compare.
        private string ChatShown(Dictionary<string, object> item)
        {
            if (item == null || Str(item, "id") != ChatId) return "";
            var settings = snapshot == null ? null : Map(Map(snapshot, "status"), "settings");
            return (chatThread ?? "") + "|" + (askedChat ?? "") + "|" + (Str(settings, "notice_click") ?? "") + "|" +
                   AdvancedWritten(chatView);
        }

        private void BuildChat(Dictionary<string, object> item)
        {
            chatConversation = null;
            chatClick = null;
            chatWords = null;
            chatSend = chatCancel = null;
            if (Str(item, "id") != ChatId || Str(item, "state") != StateArmed)
            {
                if (chatTimer != null) chatTimer.Stop();
                return;
            }
            TableLayoutPanel card = NewGroup(Word("page.chat.title", "Chat"), advancedStack);
            if (askedChat != null)
            {
                // Opened from a notice (`--chat=`): that conversation, once.
                chatThread = askedChat;
                askedChat = null;
                chatView = null;
                ReadChat();
            }
            Dictionary<string, string> offered = Conversations();
            if (chatThread != null && !offered.ContainsKey(chatThread))
                offered[chatThread] = chatThread.Substring(0, 8);
            string conversation = Word("page.resets.field.conversation", "Conversation");
            chatConversation = new SoftCombo();
            chatConversation.Width = Px(260);
            IgnoreWheel(chatConversation);
            chatConversation.AccessibleName = conversation;
            foreach (KeyValuePair<string, string> pair in offered)
            {
                var choice = new Choice(pair.Key, pair.Value);
                chatConversation.Items.Add(choice);
                if (pair.Key == chatThread) chatConversation.SelectedItem = choice;
            }
            chatConversation.SelectionChangeCommitted += delegate
            {
                var choice = chatConversation.SelectedItem as Choice;
                if (choice == null || choice.Value == chatThread) return;
                chatThread = choice.Value;
                chatView = null;
                ReadChat();
            };
            card.Controls.Add(NewRow(conversation, chatConversation));
            if (chatConversation.Items.Count == 0)
                card.Controls.Add(HelpText(Word("page.resets.no_conversation",
                    "No conversation is listed yet. One is offered here once Pending or History lists it.")));
            if (chatThread == null)
            {
                card.Controls.Add(HelpText(Word("page.chat.none", "Pick a conversation the Codex app has open.")));
                AddChatClick(card);
                return;
            }
            if (chatView == null)
                card.Controls.Add(HelpText(Word("page.chat.unread", "This conversation cannot be read now.")));
            else
                foreach (object entry in Items(chatView, "turns") ?? new List<object>())
                    AddChatTurn(card, entry as Dictionary<string, object>);
            bool waiting = false;
            foreach (object entry in Items(chatView, "messages") ?? new List<object>())
            {
                var message = entry as Dictionary<string, object>;
                if (message == null) continue;
                string state = Str(message, "state");
                bool full = Equals(Get(Map(chatView, "limit"), "full"), true);
                string line = state == "waiting" && full
                            ? Word("page.chat.limit", "The usage limit is full: this message waits and is sent when it resets.")
                            : state == "waiting" ? Word("page.chat.sending", "Sending...")
                            : state == "in_flight" ? Word("page.chat.sent", "Sent")
                            : Str(message, "reason") == "not_taken" ? Word("page.chat.not_taken", "Codex did not take it")
                            : null;
                if (line == null) continue;
                waiting |= state == "waiting";
                Label said = HelpText(line);
                said.ForeColor = Ink;
                card.Controls.Add(said);
            }
            string words = Word("page.chat.words", "Message");
            chatWords = new SoftTextArea();
            chatWords.Font = Font;
            chatWords.Box.Font = Font;
            chatWords.Box.MaxLength = Math.Max(1, Whole(Get(chatView, "words_limit")));
            chatWords.Box.AccessibleName = words;
            chatWords.Height = Px(72);
            chatWords.Dock = DockStyle.Fill;
            chatWords.Margin = Pad(0, 4, 0, 2);
            chatWords.Box.Text = chatDraft;
            SoftTextArea box = chatWords;
            box.Box.TextChanged += delegate
            {
                chatDraft = box.Box.Text;
                UpdateChatButtons(busy == 0);
            };
            card.Controls.Add(Caption(words));
            card.Controls.Add(chatWords);
            chatSend = CardButton(card, Word("page.chat.send", "Send..."), delegate { SendChat(); });
            if (waiting) chatCancel = CardButton(card, Word("page.chat.cancel", "Cancel"), delegate { CancelChat(); });
            AddChatClick(card);
            UpdateChatButtons(busy == 0);
            if (ChatGoingOn()) chatTimer.Start();
            else chatTimer.Stop();
        }

        /// Where a click on a notice goes while chat is on: the standard setting `notice_click`, as the status says it
        /// is, written at once when another is picked (`update`), and read again with the next status.
        private void AddChatClick(TableLayoutPanel card)
        {
            string label = Word("page.chat.click", "A click on a notice opens");
            chatClick = new SoftCombo();
            chatClick.Width = Px(260);
            IgnoreWheel(chatClick);
            chatClick.AccessibleName = label;
            var settings = snapshot == null ? null : Map(Map(snapshot, "status"), "settings");
            string current = Str(settings, "notice_click") ?? "page";
            foreach (string value in ChatClicks)
            {
                var choice = new Choice(value, Word("page.chat.click." + value, value == "page" ? "Its page in the Dashboard"
                                                    : value == "chat" ? "That conversation's chat here"
                                                    : "Codex, at that conversation"));
                chatClick.Items.Add(choice);
                if (value == current) chatClick.SelectedItem = choice;
            }
            chatClick.SelectionChangeCommitted += delegate
            {
                var choice = chatClick.SelectedItem as Choice;
                if (choice == null || choice.Value == current) return;
                var changes = new Dictionary<string, object>();
                changes["notice_click"] = choice.Value;
                CallAsync("update", Json.Write(changes), delegate(Dictionary<string, object> reply) { RefreshNow(); });
            };
            card.Controls.Add(NewRow(label, chatClick));
        }

        /// One turn as flat lines: each message with who wrote it, its counts, and "In progress" while it runs.
        private void AddChatTurn(TableLayoutPanel card, Dictionary<string, object> turn)
        {
            if (turn == null) return;
            foreach (object entry in Items(turn, "messages") ?? new List<object>())
            {
                var message = entry as Dictionary<string, object>;
                if (message == null) continue;
                string who = Str(message, "from") == "you" ? Word("page.chat.you", "You") : Word("page.chat.codex", "Codex");
                Label line = HelpText(who + ": " + (Str(message, "words") ?? ""));
                line.ForeColor = Ink;
                line.Margin = Pad(0, 4, 0, 0);
                card.Controls.Add(line);
            }
            var counts = Map(turn, "counts");
            int commands = Whole(Get(counts, "commands")), files = Whole(Get(counts, "files"));
            if (commands > 0 || files > 0)
                card.Controls.Add(HelpText(Word("page.chat.counts", "Ran {commands} commands, changed {files} files",
                    "commands", commands.ToString(CultureInfo.InvariantCulture))
                    .Replace("{files}", files.ToString(CultureInfo.InvariantCulture))));
            if (Str(turn, "status") == "inProgress")
                card.Controls.Add(HelpText(Word("page.chat.in_progress", "In progress - approvals are answered in Codex.")));
        }

        /// Whether a turn is running or a message of this page's is not yet settled: what the two-second read is for.
        private bool ChatGoingOn()
        {
            foreach (object entry in Items(chatView, "turns") ?? new List<object>())
                if (Str(entry as Dictionary<string, object>, "status") == "inProgress") return true;
            foreach (object entry in Items(chatView, "messages") ?? new List<object>())
            {
                string state = Str(entry as Dictionary<string, object>, "state");
                if (state == "waiting" || state == "in_flight") return true;
            }
            return false;
        }

        private void ChatPoll()
        {
            if (currentPage != AdvancedPageName || advancedOpen != ChatId || chatThread == null || busy > 0)
            {
                chatTimer.Stop();
                return;
            }
            ReadChat();
        }

        private void ReadChat()
        {
            if (chatThread == null) return;
            string thread = chatThread;
            AdvancedCall("advanced-chat-read", "{\"thread_id\":" + Json.Escape(thread) + "}", false,
                delegate(Dictionary<string, object> reply)
                {
                    if (thread != chatThread) return;
                    Dictionary<string, object> result = AdvancedResult(reply);
                    chatView = AdvancedDone(result) ? result : null;
                    ShowAdvancedDetail();
                });
        }

        private void UpdateChatButtons(bool free)
        {
            if (chatSend != null)
                chatSend.Enabled = free && chatThread != null && chatView != null && chatDraft.Trim().Length > 0;
            if (chatCancel != null) chatCancel.Enabled = free;
        }

        /// Ask, then send the message written: it waits until the watcher's next look takes it.
        private void SendChat()
        {
            if (busy > 0 || chatThread == null || chatDraft.Trim().Length == 0) return;
            if (!AskAdvanced(Word("page.confirm.chat", "Send this message to the conversation? It goes exactly as written, as your own message, once the Codex app has the conversation open."),
                             Affirm(Word("page.chat.send", "Send..."))))
                return;
            string argument = "{\"thread_id\":" + Json.Escape(chatThread) + ",\"words\":" + Json.Escape(chatDraft) +
                              ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-chat-send", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result))
                {
                    chatDraft = "";
                    chatView = result;
                    SetNote(advancedNote, Word("page.done.chat", "Sending. The watcher takes it at its next look."));
                }
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }

        private void CancelChat()
        {
            if (busy > 0 || chatThread == null) return;
            string argument = "{\"thread_id\":" + Json.Escape(chatThread) + ",\"generation\":" + AdvancedGeneration() + "}";
            AdvancedCall("advanced-chat-cancel", argument, true, delegate(Dictionary<string, object> reply)
            {
                Dictionary<string, object> result = AdvancedResult(reply);
                if (AdvancedDone(result)) chatView = result;
                ReadAdvanced(null);
                if (!AdvancedDone(result)) TellAdvanced(KeepOnRefusal(result));
            });
        }
    }
}

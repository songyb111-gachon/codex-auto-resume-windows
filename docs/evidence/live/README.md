# Live acceptance evidence

One JSON file per step of [`docs/LIVE_ACCEPTANCE.md`](../../LIVE_ACCEPTANCE.md), written
by the person who ran that step on a real Windows machine against a real Codex
installation. The schema is in that document; `python scripts/live_evidence.py` validates
everything here.

**This directory holding nothing but these two files means nothing has been accepted yet.**
It does not mean a release passed; it means no step has been run and written down. The two
are different sentences, and the validator exits 2 rather than 0 to keep them apart.

`example.json` is an example of the shape and records nothing that happened. It counts
towards no step.

What may never appear in a file here: a conversation or interruption id in the raw (write
the aliases the diagnostics export produces), a file-system path, a Windows user name, an
e-mail address, or anything a conversation said — no prompt, no reply, no title. Nor a
screenshot: a picture of a real Codex window publishes a conversation permanently, which
is why only JSON is accepted here.

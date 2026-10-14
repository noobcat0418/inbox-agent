# inbox-agent

Reads my Gmail, both new mail and older mail, and triages it with a **free local model** (Ollama).
Email never leaves this PC.

Each run writes:
- `out/summary-<date>.md` (or `backfill-<date>.md`): the **Important** emails first, then to-dos, FYI one-liners and noise.
- `out/todos.md`: a running list of open to-dos with due dates, kept across runs.

Milestone 1 is **read-only** (`gmail.readonly`). It cannot change, send or delete anything.
Auto-labelling comes in milestone 2.

## Setup (once)

1. **Google Cloud:** go to console.cloud.google.com, create a new project and enable the **Gmail API**.
2. **OAuth consent screen:**
   - set user type to **External** and add yourself as a test user;
   - then set publishing status to **In production**.
     Unverified is fine for personal use; you click through a warning once.
     In "Testing" status, Google expires the sign-in every 7 days.
3. **Credentials:** create an OAuth client ID of type **Desktop app**. Download it as `credentials.json` into this folder.
4. **Model:** install [Ollama](https://ollama.com), then run `ollama pull qwen2.5:3b`.
5. **Python:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   copy .env.example .env   # optional: only needed to change the model
   ```

## Use

```powershell
.\.venv\Scripts\python inbox.py --check                   # Gmail sign-in (browser, first time) + model check
.\.venv\Scripts\python inbox.py --dry-run                 # list what would be processed, no model calls
.\.venv\Scripts\python inbox.py                           # new mail since last run (first run: last 2 days)
.\.venv\Scripts\python inbox.py --backfill 90d --max 200  # older mail, newest first; rerun to continue
.\.venv\Scripts\python inbox.py --done 3 7                # close to-dos by id
```

- Gmail's **Promotions** and **Social** tabs are skipped unless you pass `--all-categories`.
- Mail you sent yourself is always skipped.
- Expect a few seconds per email on CPU. Ctrl+C is safe: finished emails are saved, and the same command resumes.
- An email the model couldn't classify is listed under **Errors** and retried on the next run.
- The new-mail window only moves forward after a complete run, so nothing is silently skipped.

## Safety

- Sender, subject and body are treated as **untrusted**. They go to the model inside `<email>` tags it is told never to obey.
  A forged closing tag is neutralised.
- The model can only answer with one of four categories (`important`, `todo`, `fyi`, `noise`). Anything else is rejected.
- Emails trying to instruct an AI, or asking for passwords or payment, are flagged `important` with a `Suspicious:` reason.
- Never committed: `credentials.json`, `token.json`, `.env`, `out/`, `inbox.db`.

## Changing the model

Any OpenAI-compatible endpoint works. Set it in `.env`:

```
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:3b
LLM_API_KEY=ollama
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Tests use a stub model, so no Gmail and no Ollama are needed.

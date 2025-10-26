# DeskPilot — Local-First Desktop Filing Copilot

> A Windows app + local agent that watches your Desktop, suggests where new files should go (from your **whitelist** of folders), explains *why*, learns from feedback, and keeps an in-app, undoable activity log.

---

## Features

- **Desktop watcher**: detects new files on your Windows Desktop.
- **Whitelist-only destinations**: you pick the allowed folders; each has a short human description.
- **Smart suggestions**: combines lightweight learning (by extension/tokens/recent) with **semantic matching** to your folder descriptions.
- **Explainability**: shows rationale + confidence for each suggestion.
- **Control**: **Accept / Decline / Ignore** for every file.
- **In-app Move Log**: see all actions; **Undo** any move safely.
- **Local-first**: no file contents leave your machine. Embeddings/index are memory-only.

---

## How suggestions work (hybrid score)

For a file \(f\) and a whitelisted folder \(d\):

$$
\text{score}(f,d) = 0.60s_{\text{sem}} + 0.45s_{\text{ext}} + 0.35s_{\text{tok}} + 0.20s_{\text{recent}}
$$

**sem**: cosine similarity between an embedding of the **file name (+ optional content snippet)** and an embedding of the **folder’s description** (MiniLM).

**ext**: weight learned from where files of this extension were filed.

**tok**: weight from matched name tokens (e.g., “invoice”, “EECS”).

**recent**: nudge toward where similar files were filed recently.

**Confidence** (displayed to the user):

$$
\mathrm{conf}=\min(0.99,\;\max(0.50,\;0.58 + \Delta/5)),\quad \Delta=\text{score}_{(1)}-\text{score}_{(2)}.
$$

**Content peek (conditional)**: for `.txt`/`.docx` with weak filename signal, we read a tiny snippet to enrich tokens/embedding. Never stored; bounded and fast.

---

## Tech stack

- **Agent**: Python 3.11, uAgents (Fetch.ai), SentenceTransformers (MiniLM-L6-v2), `requests`
- **UI**: PySide6 (Qt for Python), `watchdog`
- **OS**: Windows (focus for the hackathon)

---

## Quick start (Windows)

> Prereqs: [Python 3.11+](https://www.python.org/downloads/) with the `py` launcher.

1) **Clone / extract** the project.

2) **Run the two .bat files**

run Start_DesktopPilot.bat first then Start_UI.bat

---

## Configuration

- **Whitelist**: stored in `whitelist.json` (path + your description).
- **Learning state**: small JSON-safe weights for `ext`/`token`/`recent` (kept via uAgents KV).
- **Embeddings/index**: built in memory from the whitelist descriptions; never serialized.
- **Move history**: `moves.csv` (UTF-8 with BOM) under `%LOCALAPPDATA%\DeskPilot\` for easy Excel import.
- **Logs**: agent/controller/UI logs also under `%LOCALAPPDATA%\DeskPilot\`.

**Environment variables**

- `DESKPILOT_AGENT_URL` (default `http://127.0.0.1:8000`) — change if you run on a non-default port.
  

## Privacy & safety

- No file contents leave your machine.
- Content peek is **bounded** and **ephemeral** (used only in-process for `.txt/.docx` with weak names).
- You can **Undo** any move; whitelist removal purges related learned memory.

---

## Project structure (key files)

```
agent.py                 # uAgents-based local service (REST)
ui.py                    # PySide6 desktop app (File Pilot, Log, Whitelist)
requirements.txt         # Python deps
rules.json               # (optional) seed rules
whitelist.json           # user’s allowed folders (created via UI)
Start_DeskPilot.bat      # minimized agent + UI launcher with logging
```

## Acknowledgements

- Fetch.ai **uAgents**
- **SentenceTransformers** (MiniLM-L6-v2)
- Qt for Python (**PySide6**)
- **watchdog** for file watching

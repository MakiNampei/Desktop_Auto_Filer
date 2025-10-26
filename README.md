# DeskPilot — Local-First Desktop Filing Copilot

> A Windows app + local agent that watches your Desktop, suggests where new files should go (from your **whitelist** of folders), explains *why*, learns from feedback, and keeps an in-app, undoable activity log.

---

## ✨ Features

- **Desktop watcher**: detects new files on your Windows Desktop.
- **Whitelist-only destinations**: you pick the allowed folders; each has a short human description.
- **Smart suggestions**: combines lightweight learning (by extension/tokens/recent) with **semantic matching** to your folder descriptions.
- **Explainability**: shows rationale + confidence for each suggestion.
- **Control**: **Accept / Decline / Ignore** for every file.
- **In-app Move Log**: see all actions; **Undo** any move safely.
- **Local-first**: no file contents leave your machine. Embeddings/index are memory-only.

---

## 🖼️ UI at a glance

- **Main window**: Big title + buttons for **Manage Whitelist** and **See Move Log**.
- **File Pilot dialog**: pops up when a new file arrives with Accept / Decline / Ignore.
- **Whitelist Manager**: add/remove/clear; reindex embeddings.
- **Log Viewer**: renders `moves.csv` (newest first) with **Undo** per row.

---

## 🧠 How suggestions work (hybrid score)

For a file \(f\) and a whitelisted folder \(d\):

\[
\text{score}(f,d)
= 0.60\,s_{\text{sem}}
+ 0.45\,s_{\text{ext}}
+ 0.35\,s_{\text{tok}}
+ 0.20\,s_{\text{recent}}
\]

- \(s_{\text{sem}}\): cosine similarity between an embedding of the **file name (+ optional content snippet)** and an embedding of the **folder’s description** (MiniLM).
- \(s_{\text{ext}}\): weight learned from where files of this extension were filed.
- \(s_{\text{tok}}\): weight from matched name tokens (e.g., “invoice”, “EECS”).
- \(s_{\text{recent}}\): nudge toward where similar files were filed recently.

**Confidence** (displayed to the user):

\[
\mathrm{conf}=\min(0.99,\;\max(0.50,\;0.58 + \Delta/5)),
\quad
\Delta=\text{score}_{(1)}-\text{score}_{(2)}.
\]

**Content peek (conditional)**: for `.txt`/`.docx` with weak filename signal, we read a tiny snippet to enrich tokens/embedding. Never stored; bounded and fast.

---

## 🛠️ Tech stack

- **Agent**: Python 3.11, uAgents (Fetch.ai), SentenceTransformers (MiniLM-L6-v2), `requests`
- **UI**: PySide6 (Qt for Python), `watchdog`
- **OS**: Windows (focus for the hackathon)

---

## 📦 Quick start (Windows)

> Prereqs: [Python 3.11+](https://www.python.org/downloads/) with the `py` launcher.

1) **Clone / extract** the project.

2) **Create venv & install deps**
```bat
py -3.11 -m venv .venv
.\.venv\Scriptsctivate
pip install -r requirements.txt
```

3) **Run the agent (first time, visibly)**
```bat
python agent.py
```
You should see the server start (port 8000). In another terminal:
```bat
powershell -NoLogo -Command "Invoke-RestMethod 'http://127.0.0.1:8000/health'"
```
Expect: `{"status":"up"}`

4) **Run the UI**
```bat
python ui.py
```

5) **Add your whitelist** (from the main window → Manage Whitelist), then drop a file on your Desktop to see the File Pilot dialog.

> Daily use: optional `Start_DeskPilot.bat` launches the agent **minimized** (with logs) and starts the UI.

---

## ⚙️ Configuration

- **Whitelist**: stored in `whitelist.json` (path + your description).
- **Learning state**: small JSON-safe weights for `ext`/`token`/`recent` (kept via uAgents KV).
- **Embeddings/index**: built in memory from the whitelist descriptions; never serialized.
- **Move history**: `moves.csv` (UTF-8 with BOM) under `%LOCALAPPDATA%\DeskPilot\` for easy Excel import.
- **Logs**: agent/controller/UI logs also under `%LOCALAPPDATA%\DeskPilot\`.

**Environment variables**

- `DESKPILOT_AGENT_URL` (default `http://127.0.0.1:8000`) — change if you run on a non-default port.

---

## 🧪 Verifying things work

- Agent health:
```bat
.\.venv\Scripts\python.exe -c "import requests;print(requests.get('http://127.0.0.1:8000/health',timeout=5).text)"
```
- UI status bar should show: `Agent: Connected`.

---

## 🩺 Troubleshooting

- **UI says “Agent: Offline”**
  - Make `/health` instant (it already is in our code).
  - Ensure both agent and UI use the **same venv**.
  - Ensure port matches (`DESKPILOT_AGENT_URL`).
  - The UI HTTP client disables system proxies and auto-falls back between `localhost` ↔ `127.0.0.1`.

- **“watchdog not found”**
  - You’re likely using a different interpreter. Run:
    ```bat
    .\.venv\Scripts\python.exe -m pip install -U PySide6 watchdog
    .\.venv\Scripts\python.exe ui.py
    ```

- **First-run stalls** (model download)
  - The first suggestion may take longer. We build the embedding index lazily on `/suggest`.

- **Hidden agent crashes with `pythonw.exe`**
  - Our start script uses `python.exe` minimized and redirects output to `%LOCALAPPDATA%\DeskPilot\agent-run.log`.

- **Port conflict**
  ```bat
  netstat -ano | findstr :8000
  ```
  Change `port=` in `agent.py` and set `DESKPILOT_AGENT_URL` accordingly.

---

## 🔒 Privacy & safety

- No file contents leave your machine.
- Content peek is **bounded** and **ephemeral** (used only in-process for `.txt/.docx` with weak names).
- You can **Undo** any move; whitelist removal purges related learned memory.

---

## 🧩 Project structure (key files)

```
agent.py                 # uAgents-based local service (REST)
ui.py                    # PySide6 desktop app (File Pilot, Log, Whitelist)
requirements.txt         # Python deps
rules.json               # (optional) seed rules
whitelist.json           # user’s allowed folders (created via UI)
Start_DeskPilot.bat      # minimized agent + UI launcher with logging
```

---

## 📚 What inspired us

We’re all familiar with the messy Desktop problem. We aimed for a helper that is:
- **local**, **explainable**, and **reversible**,
- just smart enough to reduce friction,
- and respectful of user agency (whitelist-only moves).

---

## 🧠 What we learned

- Local-first + small models can beat cloud LLMs for trust, latency, and adoption.
- **Explainability + Undo** matter as much as accuracy.
- Health endpoints must be **instant**; do expensive work lazily.

---

## 🧱 Challenges we solved

- “Agent offline” despite running → proxy/IPv4/IPv6 pitfalls; fixed with proxy-free session and dual-stack fallback.
- Hidden crashes with `pythonw.exe` → logs + minimized `python.exe`.
- First-run download stalls → lazy index build on first `/suggest`.
- KV storage pitfalls → keep embeddings/index **out** of storage; persist only JSON-safe state.

---

## 🗺️ Roadmap

- Batch mode & confidence thresholds (auto-file when very confident).
- System tray notifications with inline actions.
- macOS/Linux support.
- On-device, smaller embedding models.
- Signed installer & autostart.

---

## 🤝 Contributing

Issues and PRs welcome! Please:
- keep the agent local-first,
- avoid storing raw file content,
- preserve explainability and undo in UX.

---

## 📄 License

Choose a license that fits your needs (e.g., MIT). Add `LICENSE` to the repo.

---

## 🙌 Acknowledgements

- Fetch.ai **uAgents**
- **SentenceTransformers** (MiniLM-L6-v2)
- Qt for Python (**PySide6**)
- **watchdog** for file watching

---

**DeskPilot** — a small, trustworthy copilot that keeps your Desktop clean, explains itself, learns what you want, and lets you undo anything.
